from app import celery, db, create_app
from app.models import Application, ParameterResult
from datetime import datetime
import logging
import requests
import time

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
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении результата: {e}")
        db.session.rollback()
        return False


@celery.task(bind=True)
def process_parameters_task(self, application_id):
    """Асинхронная задача для обработки параметров с потоковым сохранением"""
    # Создаем контекст приложения для работы с БД
    app = create_app()

    with app.app_context():
        application = Application.query.get(application_id)
        if not application:
            return {'status': 'error', 'message': f"Заявка с ID {application_id} не найдена"}

        # Обновляем статус
        task_id = self.request.id
        application.status = "analyzing"
        application.task_id = task_id
        application.analysis_started_at = datetime.utcnow()

        # Собираем параметры и устанавливаем общее количество
        checklist_items = []
        total_params = 0

        for checklist in application.checklists:
            for param in checklist.parameters.all():
                total_params += 1
                checklist_items.append({
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

        application.analysis_total_params = total_params
        application.analysis_completed_params = 0
        db.session.commit()

        try:
            # Отправляем в FastAPI для начала анализа
            response = requests.post(f"{FASTAPI_URL}/analyze", json={
                "task_id": task_id,
                "application_id": str(application_id),
                "checklist_items": checklist_items,
                "llm_params": {
                    "temperature": 0.1,
                    "max_tokens": 1000,
                    "use_smart_search": True,
                    "hybrid_threshold": 10
                }
            })

            if response.status_code == 200:
                # Опрашиваем статус анализа через FastAPI
                max_attempts = 1200  # Максимум 20 минут
                attempt = 0
                saved_params = set()  # Для отслеживания уже сохраненных параметров

                while attempt < max_attempts:
                    # Получаем статус задачи через FastAPI
                    status_response = requests.get(f"{FASTAPI_URL}/tasks/{task_id}/status")

                    if status_response.status_code == 200:
                        status_data = status_response.json()

                        # Логируем прогресс
                        if status_data.get('status') == 'PROGRESS':
                            progress = status_data.get('progress', 0)
                            message = status_data.get('message', '')
                            logger.info(f"Анализ заявки {application_id}: {progress}% - {message}")

                        # Проверяем, завершена ли задача
                        if status_data.get('status') == 'SUCCESS':
                            # Получаем финальные результаты
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
                                                application.analysis_completed_params = len(saved_params)
                                                db.session.commit()

                            # Обновляем финальный статус
                            application.status = "analyzed"
                            application.status_message = "Анализ завершен успешно"
                            application.analysis_completed_at = datetime.utcnow()
                            db.session.commit()

                            logger.info(f"Анализ заявки {application_id} завершен успешно")
                            return {"status": "success", "message": "Анализ завершен"}

                        elif status_data.get('status') == 'FAILURE':
                            # Произошла ошибка
                            raise Exception(status_data.get('message', 'Ошибка анализа'))

                    # Периодически проверяем промежуточные результаты
                    if attempt % 5 == 0:  # Каждые 5 секунд
                        # Пытаемся получить промежуточные результаты
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
                                                application.analysis_completed_params = len(saved_params)
                                                db.session.commit()
                                                logger.info(f"Сохранен результат для параметра {param_id} ({len(saved_params)}/{total_params})")
                        except Exception as e:
                            logger.debug(f"Не удалось получить промежуточные результаты: {e}")

                    # Ждем и повторяем
                    time.sleep(1)
                    attempt += 1

                # Если вышли по таймауту
                raise Exception("Превышено время ожидания анализа")

            else:
                raise Exception(f"FastAPI вернул ошибку: {response.text}")

        except Exception as e:
            logger.error(f"Ошибка при анализе: {e}")
            application.status = "error"
            application.status_message = str(e)
            application.last_operation = 'analyzing'
            db.session.commit()
            return {"status": "error", "message": str(e)}