from app import celery, db, create_app
from app.models import Application, ParameterResult
import logging
import requests
import time

logger = logging.getLogger(__name__)

FASTAPI_URL = "http://localhost:8001"


@celery.task(bind=True)
def process_parameters_task(self, application_id):
    """Асинхронная задача для обработки параметров через FastAPI"""
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
        db.session.commit()

        try:
            # Собираем параметры для анализа
            checklist_items = []
            for checklist in application.checklists:
                for param in checklist.parameters.all():
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
                max_attempts = 600  # Максимум 10 минут
                attempt = 0

                while attempt < max_attempts:
                    # Получаем статус задачи через FastAPI
                    status_response = requests.get(f"{FASTAPI_URL}/tasks/{task_id}/status")

                    if status_response.status_code == 200:
                        status_data = status_response.json()

                        if status_data.get('status') == 'SUCCESS':
                            # Анализ завершен успешно
                            # Получаем результаты через FastAPI
                            results_response = requests.get(f"{FASTAPI_URL}/tasks/{task_id}/results")

                            if results_response.status_code == 200:
                                results_data = results_response.json()
                                if 'results' in results_data:
                                    save_analysis_results(application_id, results_data['results'])

                            # Обновляем статус
                            application.status = "analyzed"
                            application.status_message = "Анализ завершен успешно"
                            db.session.commit()

                            logger.info(f"Анализ заявки {application_id} завершен успешно")
                            return {"status": "success", "message": "Анализ завершен"}

                        elif status_data.get('status') == 'FAILURE':
                            # Произошла ошибка
                            raise Exception(status_data.get('message', 'Ошибка анализа'))

                        # Логируем прогресс
                        elif status_data.get('status') == 'PROGRESS':
                            progress = status_data.get('progress', 0)
                            message = status_data.get('message', '')
                            logger.info(f"Анализ заявки {application_id}: {progress}% - {message}")

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
            db.session.commit()
            return {"status": "error", "message": str(e)}


def save_analysis_results(application_id, results):
    """Сохраняет результаты анализа в БД"""
    try:
        for result in results:
            # Проверяем, есть ли уже результат для этого параметра
            existing_result = ParameterResult.query.filter_by(
                application_id=application_id,
                parameter_id=result['parameter_id']
            ).first()

            if existing_result:
                # Обновляем существующий результат
                existing_result.value = result['value']
                existing_result.confidence = result['confidence']
                existing_result.search_results = result['search_results']
                existing_result.llm_request = result.get('llm_request', {})
            else:
                # Создаем новый результат
                param_result = ParameterResult(
                    application_id=application_id,
                    parameter_id=result['parameter_id'],
                    value=result['value'],
                    confidence=result['confidence'],
                    search_results=result['search_results'],
                    llm_request=result.get('llm_request', {})
                )
                db.session.add(param_result)

        db.session.commit()
        logger.info(f"Результаты анализа для заявки {application_id} сохранены")
    except Exception as e:
        logger.error(f"Ошибка при сохранении результатов анализа: {e}")
        raise