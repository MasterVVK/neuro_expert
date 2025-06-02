from app import celery, db, create_app
from app.models import Application, File
import logging
import requests
import time
import uuid
import os
from datetime import datetime

logger = logging.getLogger(__name__)

FASTAPI_URL = "http://localhost:8001"


def update_application_status(application):
    """Обновляет статус заявки на основе статусов файлов"""
    file_statuses = [f.indexing_status for f in application.files]

    if not file_statuses:
        application.status = 'created'
    elif any(s == 'indexing' for s in file_statuses):
        # Хотя бы один файл еще индексируется
        application.status = 'indexing'
    elif any(s == 'error' for s in file_statuses):
        # Есть файлы с ошибками (приоритет над успешной индексацией)
        errors_count = file_statuses.count('error')
        completed_count = file_statuses.count('completed')

        # Всегда устанавливаем статус 'error' если есть хотя бы одна ошибка
        application.status = 'error'
        application.last_operation = 'indexing'  # Добавляем, чтобы знать, что ошибка при индексации

        if completed_count > 0:
            application.status_message = f"Индексация завершена с ошибками. Успешно: {completed_count}, Ошибок: {errors_count}"
        else:
            application.status_message = f"Ошибка индексации всех файлов ({errors_count})"
    elif all(s == 'completed' for s in file_statuses):
        # Все файлы успешно проиндексированы
        application.status = 'indexed'
        application.status_message = f"Успешно проиндексировано файлов: {len(file_statuses)}"
    else:
        application.status = 'created'

    db.session.commit()

def get_file_chunks_count(application_id, file_id):
    """Получает количество чанков для файла через FastAPI"""
    try:
        response = requests.get(
            f"{FASTAPI_URL}/applications/{application_id}/files/{file_id}/stats"
        )
        if response.status_code == 200:
            return response.json().get('chunks_count', 0)
    except Exception as e:
        logger.error(f"Ошибка при получении количества чанков: {e}")
    return 0


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

        # Генерируем уникальный ID сессии индексации
        index_session_id = str(uuid.uuid4())

        # Обновляем статус файла
        file.indexing_status = 'indexing'
        file.index_session_id = index_session_id
        file.indexing_started_at = datetime.utcnow()
        file.error_message = None

        # Записываем ID задачи
        task_id = self.request.id
        application.task_id = task_id
        db.session.commit()

        try:
            # Удаляем старые чанки если они есть
            if file.chunks_count > 0:
                logger.info(f"Удаление существующих чанков ({file.chunks_count}) для файла {file_id}")

                # Используем FastAPIClient для удаления
                from app.services.fastapi_client import FastAPIClient
                client = FastAPIClient()

                try:
                    deleted_count = client.delete_file_chunks(str(application_id), str(file_id))
                    logger.info(f"Успешно удалено {deleted_count} чанков по file_id")
                except Exception as e:
                    logger.warning(f"Не удалось удалить по file_id: {e}")
                    # Пробуем удалить по document_id как fallback
                    document_id = f"doc_{os.path.basename(file.file_path).replace(' ', '_').replace('.', '_')}"
                    try:
                        deleted_count = client.delete_document_chunks(str(application_id), document_id)
                        logger.info(f"Успешно удалено {deleted_count} чанков по document_id")
                    except Exception as e2:
                        logger.error(f"Не удалось удалить чанки: {e2}")
                        # Продолжаем индексацию даже если удаление не удалось

            # ВАЖНО: Определяем, нужно ли удалять старые данные
            delete_existing = False
            if file.chunks_count > 0:
                # Если у файла уже есть чанки, удаляем их перед новой индексацией
                logger.info(f"Обнаружены существующие чанки ({file.chunks_count}), будут удалены")
                delete_existing = True

            # Генерируем document_id для совместимости
            document_id = f"doc_{os.path.basename(file.file_path).replace(' ', '_').replace('.', '_')}"

            # Отправляем запрос в FastAPI для начала индексации
            response = requests.post(f"{FASTAPI_URL}/index", json={
                "task_id": task_id,
                "application_id": str(application_id),
                "document_path": file.file_path,
                "document_id": document_id,  # Передаем явно для совместимости
                "delete_existing": delete_existing,
                "metadata": {
                    "file_id": str(file_id),  # ВАЖНО: передаем file_id в метаданных
                    "index_session_id": index_session_id,
                    "original_filename": file.original_filename
                }
            })

            if response.status_code == 200:
                # Опрашиваем статус индексации через FastAPI
                max_attempts = 1200  # Максимум 40 минут (1200 * 2 сек)
                attempt = 0

                while attempt < max_attempts:
                    # Получаем статус задачи через FastAPI
                    status_response = requests.get(f"{FASTAPI_URL}/tasks/{task_id}/status")

                    if status_response.status_code == 200:
                        status_data = status_response.json()

                        if status_data.get('status') == 'SUCCESS':
                            # Индексация завершена успешно
                            # Получаем количество проиндексированных чанков
                            chunks_count = get_file_chunks_count(application_id, file_id)

                            file.indexing_status = 'completed'
                            file.chunks_count = chunks_count
                            file.indexing_completed_at = datetime.utcnow()

                            # Обновляем статус заявки
                            update_application_status(application)

                            db.session.commit()

                            logger.info(f"Индексация файла {file_id} заявки {application_id} завершена успешно: {chunks_count} чанков")
                            return {"status": "success", "message": "Индексация завершена", "chunks_count": chunks_count}

                        elif status_data.get('status') == 'FAILURE':
                            # Произошла ошибка
                            raise Exception(status_data.get('message', 'Ошибка индексации'))

                        # Логируем прогресс
                        elif status_data.get('status') == 'PROGRESS':
                            progress = status_data.get('progress', 0)
                            message = status_data.get('message', '')
                            logger.info(f"Индексация файла {file_id} заявки {application_id}: {progress}% - {message}")

                    # Ждем и повторяем
                    time.sleep(2)
                    attempt += 1

                # Если вышли по таймауту
                raise Exception("Превышено время ожидания индексации")

            else:
                raise Exception(f"FastAPI вернул ошибку: {response.text}")

        except Exception as e:
            logger.error(f"Ошибка при индексации файла {file_id}: {e}")

            file.indexing_status = 'error'
            file.error_message = str(e)
            db.session.commit()

            # Обновляем статус заявки
            update_application_status(application)

            return {"status": "error", "message": str(e)}