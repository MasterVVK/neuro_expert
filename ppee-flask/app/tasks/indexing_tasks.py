from app import celery, db, create_app
from app.models import Application, File
import logging
import requests
import time

logger = logging.getLogger(__name__)

FASTAPI_URL = "http://localhost:8001"


@celery.task(bind=True)
def index_document_task(self, application_id, file_id):
    """Асинхронная задача для индексации документа через FastAPI"""
    # Создаем контекст приложения для работы с БД
    app = create_app()

    with app.app_context():
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
            # Отправляем запрос в FastAPI для начала индексации
            response = requests.post(f"{FASTAPI_URL}/index", json={
                "task_id": task_id,
                "application_id": str(application_id),
                "document_path": file.file_path,
                "delete_existing": False
            })

            if response.status_code == 200:
                # Опрашиваем статус индексации через FastAPI
                max_attempts = 1200  # Максимум 5 минут (300 * 1 сек)
                attempt = 0

                while attempt < max_attempts:
                    # Получаем статус задачи через FastAPI
                    status_response = requests.get(f"{FASTAPI_URL}/tasks/{task_id}/status")

                    if status_response.status_code == 200:
                        status_data = status_response.json()

                        if status_data.get('status') == 'SUCCESS':
                            # Индексация завершена успешно
                            application.status = "indexed"
                            application.status_message = "Индексация завершена успешно"
                            db.session.commit()

                            logger.info(f"Индексация заявки {application_id} завершена успешно")
                            return {"status": "success", "message": "Индексация завершена"}

                        elif status_data.get('status') == 'FAILURE':
                            # Произошла ошибка
                            raise Exception(status_data.get('message', 'Ошибка индексации'))

                        # Логируем прогресс
                        elif status_data.get('status') == 'PROGRESS':
                            progress = status_data.get('progress', 0)
                            message = status_data.get('message', '')
                            logger.info(f"Индексация заявки {application_id}: {progress}% - {message}")

                    # Ждем и повторяем
                    time.sleep(2)
                    attempt += 1

                # Если вышли по таймауту
                raise Exception("Превышено время ожидания индексации")

            else:
                raise Exception(f"FastAPI вернул ошибку: {response.text}")

        except Exception as e:
            logger.error(f"Ошибка при индексации: {e}")
            application.status = "error"
            application.status_message = str(e)
            db.session.commit()
            return {"status": "error", "message": str(e)}