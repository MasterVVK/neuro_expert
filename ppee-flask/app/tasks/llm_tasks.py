from app import celery, db, create_app
from app.models import Application, ParameterResult
from datetime import datetime
import logging
import requests
import time
import re
from celery.exceptions import Terminated, WorkerLostError

logger = logging.getLogger(__name__)
FASTAPI_URL = "http://localhost:8001"


def save_single_result(application_id, parameter_id, result_data):
    """Сохраняет результат для одного параметра"""
    try:
        # Проверяем, есть ли уже результат
        existing = ParameterResult.query.filter_by(
            application_id=application_id,
            parameter_id=parameter_id
        ).first()

        if existing:
            # Обновляем существующий
            existing.value = result_data['value']
            existing.confidence = result_data['confidence']
            existing.search_results = result_data['search_results']
            existing.llm_request = result_data.get('llm_request', {})
        else:
            # Создаем новый
            param_result = ParameterResult(
                application_id=application_id,
                parameter_id=parameter_id,
                value=result_data['value'],
                confidence=result_data['confidence'],
                search_results=result_data['search_results'],
                llm_request=result_data.get('llm_request', {})
            )
            db.session.add(param_result)

        db.session.commit()
        logger.info(f"Результат сохранен для параметра {parameter_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении результата для параметра {parameter_id}: {e}")
        db.session.rollback()
        return False


@celery.task(bind=True)
def process_parameters_task(self, application_id):
    """Асинхронная задача для обработки параметров с потоковым сохранением"""
    # Создаем контекст приложения для работы с БД
    app = create_app()

    with app.app_context():
        # Используем свежий запрос к БД для избежания проблем с кешированием
        application = db.session.query(Application).filter_by(id=application_id).first()

        if not application:
            return {'status': 'error', 'message': f"Заявка с ID {application_id} не найдена"}

        # Логируем начало задачи
        logger.info(f"[TASK {self.request.id}] Начало анализа заявки {application_id}")

        # Обновляем статус
        task_id = self.request.id
        application.status = "analyzing"
        application.task_id = task_id
        application.analysis_started_at = datetime.utcnow()

        # Собираем параметры и устанавливаем общее количество
        checklist_items = []
        total_params = 0

        # ИЗМЕНЕНИЕ: Сначала собираем все параметры в словарь по моделям
        params_by_model = {}

        for checklist in application.checklists:
            for param in checklist.parameters.all():
                total_params += 1

                model_name = param.llm_model
                if model_name not in params_by_model:
                    params_by_model[model_name] = []

                params_by_model[model_name].append({
                    "id": param.id,
                    "name": param.name,
                    "search_query": param.search_query,
                    "search_limit": param.search_limit,
                    "use_reranker": param.use_reranker,
                    "rerank_limit": param.rerank_limit,
                    "llm_model": param.llm_model,
                    "llm_prompt_template": param.llm_prompt_template,
                    "llm_temperature": param.llm_temperature,
                    "llm_max_tokens": param.llm_max_tokens
                })

        # ИЗМЕНЕНИЕ: Теперь формируем список параметров, сгруппированный по моделям
        for model_name in sorted(params_by_model.keys()):  # Сортируем для предсказуемости
            checklist_items.extend(params_by_model[model_name])
            logger.info(f"Модель {model_name}: {len(params_by_model[model_name])} параметров")

        application.analysis_total_params = total_params
        application.analysis_completed_params = 0
        db.session.commit()

        try:
            # Отправляем в FastAPI для начала анализа
            response = requests.post(f"{FASTAPI_URL}/analyze", json={
                "task_id": task_id,
                "application_id": str(application_id),
                "checklist_items": checklist_items,  # Теперь отсортированы по моделям
                "llm_params": {
                    "temperature": 0.1,
                    "max_tokens": 1000,
                    "use_smart_search": True,
                    "hybrid_threshold": 10
                }
            })

            if response.status_code == 200:
                # Опрашиваем статус анализа через FastAPI
                max_attempts = 2200  # Максимум 20 минут
                attempt = 0
                saved_params = set()  # Для отслеживания уже сохраненных параметров
                current_model = None  # ИЗМЕНЕНИЕ: Отслеживаем текущую модель

                while attempt < max_attempts:
                    # Проверяем, не была ли задача отменена
                    if self.request.called_directly:
                        # Задача вызвана напрямую, не через воркер
                        pass
                    else:
                        # Проверяем статус задачи в Celery
                        from celery import current_app as celery_app
                        task_state = celery_app.AsyncResult(task_id).state
                        if task_state == 'REVOKED':
                            logger.info(f"Задача анализа {task_id} была отменена пользователем")
                            # Обновляем статус заявки
                            final_app = Application.query.get(application_id)
                            if final_app:
                                if len(saved_params) > 0:
                                    final_app.status = "analyzed"
                                    final_app.status_message = f"Анализ остановлен. Сохранено результатов: {len(saved_params)}"
                                else:
                                    final_app.status = "indexed"
                                    final_app.status_message = "Анализ остановлен пользователем"
                                db.session.commit()
                            return {"status": "cancelled", "message": "Анализ остановлен пользователем"}

                    # Получаем статус задачи через FastAPI
                    status_response = requests.get(f"{FASTAPI_URL}/tasks/{task_id}/status")

                    if status_response.status_code == 200:
                        status_data = status_response.json()

                        # Логируем прогресс
                        if status_data.get('status') == 'PROGRESS':
                            progress = status_data.get('progress', 0)
                            message = status_data.get('message', '')

                            # Сохраняем оригинальное сообщение из FastAPI
                            logger.info(f"Анализ заявки {application_id}: {progress}% - {message}")

                            # ИЗМЕНЕНИЕ: Определяем текущую модель по индексу
                            match = re.search(r'Анализ параметра (\d+)/(\d+):', message)
                            if match:
                                completed_params = int(match.group(1))

                                # Определяем какая модель сейчас обрабатывается
                                if completed_params > 0 and completed_params <= len(checklist_items):
                                    param_index = completed_params - 1
                                    new_model = checklist_items[param_index]['llm_model']
                                    if new_model != current_model:
                                        current_model = new_model
                                        logger.info(f"Переключение на модель: {current_model}")

                                # Добавляем задержку чтобы FastAPI успел сохранить результат
                                time.sleep(2)

                                # Пытаемся получить результаты (только через /results endpoint)
                                try:
                                    results_response = requests.get(f"{FASTAPI_URL}/tasks/{task_id}/results")

                                    if results_response.status_code == 200:
                                        results_data = results_response.json()
                                        if 'results' in results_data:
                                            # Сохраняем новые результаты
                                            for result in results_data['results']:
                                                param_id = result['parameter_id']
                                                if param_id not in saved_params:
                                                    if save_single_result(application_id, param_id, result):
                                                        saved_params.add(param_id)

                                except Exception as e:
                                    logger.error(f"Ошибка при получении результатов: {e}")

                                # Обновляем счетчик
                                try:
                                    fresh_app = Application.query.get(application_id)
                                    if fresh_app:
                                        # Обновляем счетчик на основе реально сохраненных результатов
                                        fresh_app.analysis_completed_params = len(saved_params)

                                        db.session.add(fresh_app)
                                        db.session.commit()

                                        # ИЗМЕНЕНИЕ: Добавляем информацию о текущей модели в сообщение
                                        enhanced_message = message
                                        if current_model:
                                            enhanced_message = f"{message} [Модель: {current_model}]"

                                        self.update_state(
                                            state='PROGRESS',
                                            meta={
                                                'current': fresh_app.analysis_completed_params,
                                                'total': total_params,
                                                'progress': progress,
                                                'status': 'progress',
                                                'message': enhanced_message,  # Сообщение с моделью
                                                'stage': 'analyze',
                                                'completed_params': fresh_app.analysis_completed_params,
                                                'total_params': total_params
                                            }
                                        )

                                        logger.info(f"Заявка {application_id}: обновлен прогресс {fresh_app.analysis_completed_params}/{total_params}")
                                except Exception as e:
                                    logger.error(f"Ошибка обновления прогресса для заявки {application_id}: {e}")
                                    db.session.rollback()

                        # Проверяем, завершена ли задача
                        if status_data.get('status') == 'SUCCESS':
                            # Получаем финальные результаты (на случай если что-то пропустили)
                            results_response = requests.get(f"{FASTAPI_URL}/tasks/{task_id}/results")

                            if results_response.status_code == 200:
                                results_data = results_response.json()
                                if 'results' in results_data:
                                    # Сохраняем все результаты (на случай если что-то пропустили)
                                    for result in results_data['results']:
                                        param_id = result['parameter_id']
                                        if param_id not in saved_params:
                                            if save_single_result(application_id, param_id, result):
                                                saved_params.add(param_id)

                            # Обновляем финальный статус
                            final_app = Application.query.get(application_id)
                            if final_app:
                                final_app.status = "analyzed"
                                final_app.status_message = "Анализ завершен успешно"
                                final_app.analysis_completed_at = datetime.utcnow()
                                final_app.analysis_completed_params = len(saved_params)
                                db.session.commit()

                            logger.info(f"Анализ заявки {application_id} завершен успешно. Сохранено {len(saved_params)} результатов")
                            logger.info(f"[TASK {self.request.id}] Завершение анализа заявки {application_id}")
                            return {"status": "success", "message": "Анализ завершен"}

                        elif status_data.get('status') == 'FAILURE':
                            # Произошла ошибка
                            raise Exception(status_data.get('message', 'Ошибка анализа'))

                    # Ждем и повторяем
                    time.sleep(1)
                    attempt += 1

                # Если вышли по таймауту
                raise Exception("Превышено время ожидания анализа")

            else:
                raise Exception(f"FastAPI вернул ошибку: {response.text}")

        except (Terminated, WorkerLostError) as e:
            # Задача была отменена
            logger.info(f"Задача анализа заявки {application_id} была отменена: {e}")
            error_app = Application.query.get(application_id)
            if error_app:
                saved_count = ParameterResult.query.filter_by(application_id=application_id).count()
                if saved_count > 0:
                    error_app.status = "analyzed"
                    error_app.status_message = f"Анализ остановлен. Обработано параметров: {saved_count}"
                else:
                    error_app.status = "indexed"
                    error_app.status_message = "Анализ остановлен пользователем"
                error_app.last_operation = 'analyzing'
                db.session.commit()
            return {"status": "cancelled", "message": "Анализ остановлен пользователем"}

        except Exception as e:
            logger.error(f"Ошибка при анализе: {e}")
            error_app = Application.query.get(application_id)
            if error_app:
                error_app.status = "error"
                error_app.status_message = str(e)
                error_app.last_operation = 'analyzing'
                db.session.commit()
            logger.info(f"[TASK {self.request.id}] Ошибка анализа заявки {application_id}: {e}")
            return {"status": "error", "message": str(e)}