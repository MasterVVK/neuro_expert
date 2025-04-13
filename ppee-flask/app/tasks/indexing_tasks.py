from app import celery
from app.services.vector_service import index_document

@celery.task
def index_document_task(application_id, file_id):
    """
    Асинхронная задача для индексации документа.
    
    Args:
        application_id: ID заявки
        file_id: ID файла
    """
    return index_document(application_id, file_id)
