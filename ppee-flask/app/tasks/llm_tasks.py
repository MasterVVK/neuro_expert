from app import celery, db
from app.models import Application, ParameterResult
import logging
import requests

logger = logging.getLogger(__name__)

FASTAPI_URL = "http://localhost:8001"


@celery.task(bind=True)
def process_parameters_task(self, application_id):
    """Асинхронная задача для обработки параметров через FastAPI"""
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

        # Отправляем в FastAPI с параметрами умного поиска
        response = requests.post(f"{FASTAPI_URL}/analyze", json={
            "task_id": task_id,
            "application_id": str(application_id),
            "checklist_items": checklist_items,
            "llm_params": {
                "temperature": 0.1,
                "max_tokens": 1000,
                "use_smart_search": True,  # Включаем умный поиск
                "hybrid_threshold": 10  # Порог для гибридного поиска
            }
        })

        if response.status_code == 200:
            return {"status": "success", "message": "Анализ запущен"}
        else:
            raise Exception(f"FastAPI вернул ошибку: {response.text}")

    except Exception as e:
        logger.error(f"Ошибка при вызове FastAPI: {e}")
        application.status = "error"
        application.status_message = str(e)
        db.session.commit()
        return {"status": "error", "message": str(e)}