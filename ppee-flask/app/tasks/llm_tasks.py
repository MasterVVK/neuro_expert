from app import celery, db
from app.models import Application
from app.services.llm_service import analyze_application
import logging

logger = logging.getLogger(__name__)


@celery.task(bind=True)
def process_parameters_task(self, application_id):
    """
    Асинхронная задача для обработки параметров чек-листа.

    Args:
        application_id: ID заявки
    """
    try:
        # Начальное состояние
        self.update_state(state='PROGRESS',
                          meta={'progress': 5,
                                'stage': 'prepare',
                                'message': 'Подготовка к анализу...'})

        # Получаем данные из БД и меняем статус
        application = Application.query.get(application_id)
        if not application:
            error_msg = f"Заявка с ID {application_id} не найдена"
            self.update_state(state='FAILURE',
                              meta={'progress': 0,
                                    'stage': 'error',
                                    'message': error_msg})
            return {'status': 'error', 'message': error_msg}

        # Обновляем статус заявки на analyzing
        application.status = "analyzing"
        db.session.commit()

        # Вызываем функцию analyze_application с колбэком для обновления прогресса
        result = analyze_application(
            application_id=application_id,
            skip_status_check=True,  # Пропускаем проверку статуса
            progress_callback=lambda progress, stage, message:
            self.update_state(state='PROGRESS',
                              meta={'progress': progress,
                                    'stage': stage,
                                    'message': message})
        )

        # Финальное обновление
        self.update_state(state='SUCCESS',
                          meta={'progress': 100,
                                'stage': 'complete',
                                'message': 'Анализ успешно завершен'})

        return result

    except Exception as e:
        logger.exception(f"Ошибка в задаче анализа: {str(e)}")

        # Обрабатываем исключение
        error_msg = str(e)
        self.update_state(state='FAILURE',
                          meta={'progress': 0,
                                'stage': 'error',
                                'message': f'Ошибка анализа: {error_msg}'})

        # Обновляем статус заявки в БД
        try:
            application = Application.query.get(application_id)
            if application:
                application.status = "error"
                application.status_message = error_msg
                db.session.commit()
        except Exception as db_error:
            logger.error(f"Не удалось обновить статус заявки: {str(db_error)}")

        return {'status': 'error', 'message': error_msg}