from app import celery
from app.services.llm_service import analyze_application

@celery.task
def process_parameters_task(application_id):
    """
    Асинхронная задача для обработки параметров чек-листа.
    
    Args:
        application_id: ID заявки
    """
    return analyze_application(application_id)
