from app import celery, db
from app.models import Application, File
from app.services.vector_service import index_document as index_document_service
import logging
import re


@celery.task(bind=True)
def index_document_task(self, application_id, file_id):
    """
    Асинхронная задача для индексации документа.

    Args:
        application_id: ID заявки
        file_id: ID файла
    """
    try:
        # Получаем данные из БД
        application = Application.query.get(application_id)
        file = File.query.get(file_id)

        if not application or not file:
            return {'status': 'error', 'message': 'Заявка или файл не найдены'}

        # Записываем ID задачи в приложение
        application.task_id = self.request.id
        db.session.commit()

        # Начальное состояние
        self.update_state(state='PROGRESS',
                          meta={'progress': 5,
                                'stage': 'prepare',
                                'message': 'Подготовка к индексации...'})

        # Вызываем сервис индексации с отслеживанием прогресса
        result = index_document_service(
            application_id,
            file_id,
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
                                'message': 'Индексация успешно завершена'})

        return result

    except Exception as e:
        self.update_state(state='FAILURE',
                          meta={'error': str(e),
                                'message': f'Ошибка индексации: {str(e)}'})
        raise