from app import db
from app.models import Application, ParameterResult, ChecklistParameter


def save_analysis_results(application_id, results):
    """Сохраняет результаты анализа в БД"""
    application = Application.query.get(application_id)
    if not application:
        return

    # Создаем словарь параметров для быстрого доступа
    params_dict = {}
    for checklist in application.checklists:
        for param in checklist.parameters:
            params_dict[param.id] = param

    for result in results:
        parameter_id = result['parameter_id']
        parameter = params_dict.get(parameter_id)

        if not parameter:
            continue

        # Просто сохраняем то, что пришло из FastAPI
        llm_request_data = result.get('llm_request', {})

        # Проверяем, есть ли уже результат для этого параметра
        existing_result = ParameterResult.query.filter_by(
            application_id=application_id,
            parameter_id=parameter_id
        ).first()

        if existing_result:
            # Обновляем существующий результат
            existing_result.value = result['value']
            existing_result.confidence = result['confidence']
            existing_result.search_results = result['search_results']
            existing_result.llm_request = llm_request_data
        else:
            # Создаем новый результат
            param_result = ParameterResult(
                application_id=application_id,
                parameter_id=parameter_id,
                value=result['value'],
                confidence=result['confidence'],
                search_results=result['search_results'],
                llm_request=llm_request_data
            )
            db.session.add(param_result)

    db.session.commit()