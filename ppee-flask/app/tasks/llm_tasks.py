from app import celery, db
from app.models import Application
from app.services.llm_service import analyze_application
from app.tasks.base_task import BaseTask
import logging

# Настройка логирования
logger = logging.getLogger(__name__)


@celery.task(bind=True)
@BaseTask.task_wrapper
def process_parameters_task(self, application_id):
    """
    Асинхронная задача для обработки параметров чек-листа.

    Args:
        application_id: ID заявки

    Returns:
        dict: Результат анализа
    """
    # Получаем данные из БД и меняем статус
    application = Application.query.get(application_id)
    if not application:
        return {'status': 'error', 'message': f"Заявка с ID {application_id} не найдена"}

    # Обновляем статус заявки на analyzing
    application.status = "analyzing"
    application.task_id = self.request.id
    db.session.commit()

    # Начальное состояние
    BaseTask.update_progress(self, 5, 'prepare', 'Подготовка к анализу...')

    # Обновляем прогресс
    BaseTask.update_progress(self, 15, 'analyze', 'Инициализация анализа...')

    # Вызываем функцию analyze_application с колбэком для обновления прогресса
    result = analyze_application(
        application_id=application_id,
        skip_status_check=True,  # Пропускаем проверку статуса
        progress_callback=lambda progress, stage, message:
        BaseTask.update_progress(self, progress, stage, message)
    )

    # Финальное обновление будет выполнено автоматически через декоратор

    return result