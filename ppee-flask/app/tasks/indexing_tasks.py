from app import celery, db
from app.models import Application, File
import logging
import requests
import uuid

logger = logging.getLogger(__name__)

FASTAPI_URL = "http://localhost:8001"


@celery.task(bind=True)
def index_document_task(self, application_id, file_id):
    """Асинхронная задача для индексации документа через FastAPI"""
    # Получаем данные из БД
    application = Application.query.get(application_id)
    file = File.query.get(file_id)

    if not application or not file:
        return {'status': 'error', 'message': 'Заявка или файл не найдены'}

    # Записываем ID задачи
    task_id = self.request.id
    application.task_id = task_id
    db.session.commit()

    try:
        # Отправляем запрос в FastAPI
        response = requests.post(f"{FASTAPI_URL}/index", json={
            "task_id": task_id,
            "application_id": str(application_id),
            "document_path": file.file_path,
            "delete_existing": False
        })

        if response.status_code == 200:
            return {"status": "success", "message": "Индексация запущена"}
        else:
            raise Exception(f"FastAPI вернул ошибку: {response.text}")

    except Exception as e:
        logger.error(f"Ошибка при вызове FastAPI: {e}")
        application.status = "error"
        application.status_message = str(e)
        db.session.commit()
        return {"status": "error", "message": str(e)}