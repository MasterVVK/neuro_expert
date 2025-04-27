from app import celery, db
from app.models import Application, File
from app.services.vector_service import index_document as index_document_service
from app.tasks.base_task import BaseTask
import logging

# Настройка логирования
logger = logging.getLogger(__name__)


@celery.task(bind=True)
@BaseTask.task_wrapper
def index_document_task(self, application_id, file_id):
    """
    Асинхронная задача для индексации документа.

    Args:
        application_id: ID заявки
        file_id: ID файла

    Returns:
        dict: Результат индексации
    """
    # Получаем данные из БД
    application = Application.query.get(application_id)
    file = File.query.get(file_id)

    if not application or not file:
        return {'status': 'error', 'message': 'Заявка или файл не найдены'}

    # Записываем ID задачи в приложение
    application.task_id = self.request.id
    db.session.commit()

    # Начальное состояние (разовое обновление статуса)
    BaseTask.update_progress(self, 5, 'prepare', 'Подготовка к индексации...')

    # Обновляем статус перед конвертацией
    BaseTask.update_progress(self, 15, 'convert', 'Подготовка к конвертации документа...')

    # Индексируем документ с отслеживанием прогресса через callback
    result = index_document_service(
        application_id=application_id,
        file_id=file_id,
        progress_callback=lambda progress, stage, message:
        BaseTask.update_progress(self, progress, stage, message)
    )

    # Обновляем статус заявки на основе результата
    if result["status"] == "success":
        application.status = "indexed"
        logger.info(f"Индексация для заявки {application_id} успешно завершена")
    else:
        application.status = "error"
        application.status_message = result.get("error", "Неизвестная ошибка")
        logger.error(f"Ошибка при индексации заявки {application_id}: {result.get('error', 'Неизвестная ошибка')}")

    db.session.commit()

    # Финальное обновление прогресса будет выполнено в декораторе task_wrapper
    # Не нужно вызывать BaseTask.update_progress() для финального статуса

    return result