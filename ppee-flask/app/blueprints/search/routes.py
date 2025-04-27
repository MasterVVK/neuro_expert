from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from app.blueprints.search import bp
from app.models import Application, Checklist, ChecklistParameter
from app.tasks.search_tasks import semantic_search_task
from app.adapters.llm_adapter import OllamaLLMProvider


@bp.route('/')
def index():
    """Страница семантического поиска"""
    # Получаем список доступных заявок
    applications = Application.query.filter(Application.status.in_(['indexed', 'analyzed'])).all()

    # Получаем список доступных моделей LLM
    llm_provider = OllamaLLMProvider(base_url=current_app.config['OLLAMA_URL'])
    available_models = llm_provider.get_available_models()

    # Если не удалось получить список моделей, используем фиксированный список
    if not available_models:
        available_models = ['gemma3:27b', 'llama3:8b', 'mistral:7b']

    # Получаем шаблон промпта из базы данных
    default_prompt = None

    try:
        # Пытаемся найти шаблон промпта в базе данных
        # Для примера берем первый параметр первого чек-листа
        checklist = Checklist.query.first()
        if checklist:
            parameter = ChecklistParameter.query.filter_by(checklist_id=checklist.id).first()
            if parameter and parameter.llm_prompt_template:
                default_prompt = parameter.llm_prompt_template
    except Exception as e:
        current_app.logger.error(f"Ошибка при получении шаблона промпта: {str(e)}")

    # Если не удалось получить промпт из базы данных
    if not default_prompt:
        flash(
            'Не удалось загрузить шаблон промпта из базы данных. Пожалуйста, введите его вручную или создайте параметры чек-листа.',
            'warning')
        # Оставляем пустое значение вместо шаблона по умолчанию
        default_prompt = ""

    return render_template('search/index.html',
                           title='Семантический поиск',
                           applications=applications,
                           available_models=available_models,
                           default_prompt=default_prompt)  # Передаем промпт в шаблон


@bp.route('/execute', methods=['POST'])
def execute_search():
    """Выполняет поиск и возвращает результаты в формате JSON"""
    application_id = request.form.get('application_id')
    query = request.form.get('query')
    search_limit = int(request.form.get('search_limit', 5))
    use_reranker = request.form.get('use_reranker') == 'true'
    rerank_limit = int(request.form.get('rerank_limit', 10)) if use_reranker else None

    # Параметры LLM
    use_llm = request.form.get('use_llm') == 'true'
    llm_params = None

    if use_llm:
        llm_params = {
            'model_name': request.form.get('llm_model', 'gemma3:27b'),
            'prompt_template': request.form.get('llm_prompt_template', ''),
            'temperature': float(request.form.get('llm_temperature', 0.1)),
            'max_tokens': int(request.form.get('llm_max_tokens', 1000))
        }

    if not application_id or not query:
        return jsonify({
            'status': 'error',
            'message': 'Не указана заявка или поисковый запрос'
        })

    try:
        # Логируем запрос
        current_app.logger.info(
            f"Поиск: '{query}', Заявка: {application_id}, Ререйтинг: {use_reranker}, LLM: {use_llm}")

        # Вызываем асинхронную задачу Celery для выполнения поиска
        task = semantic_search_task.delay(
            application_id=application_id,
            query_text=query,
            limit=search_limit,
            use_reranker=use_reranker,
            rerank_limit=rerank_limit,
            use_llm=use_llm,
            llm_params=llm_params
        )

        # Возвращаем ID задачи для последующего отслеживания
        return jsonify({
            'status': 'pending',
            'task_id': task.id,
            'message': 'Поиск запущен асинхронно'
        })

    except Exception as e:
        current_app.logger.error(f"Ошибка при запуске задачи поиска: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        })


@bp.route('/status/<task_id>')
def check_status(task_id):
    """Проверяет статус выполнения задачи поиска"""
    task = semantic_search_task.AsyncResult(task_id)

    current_app.logger.debug(f"Проверка статуса задачи поиска {task_id}: {task.state}")

    if task.state == 'PENDING':
        response = {
            'status': 'pending',
            'progress': 0,
            'message': 'Задача ожидает выполнения...'
        }
    elif task.state == 'PROGRESS':
        # Сохраняем структуру исходного ответа задачи и добавляем общий статус
        response = {
            'status': 'progress',
            'progress': task.info.get('progress', 0),
            'message': task.info.get('message', ''),
            'stage': task.info.get('stage', '')  # Используем ключ 'stage' вместо 'substatus'
        }
    elif task.state == 'FAILURE':
        error_msg = str(task.result) if task.result else "Неизвестная ошибка при выполнении задачи"
        response = {
            'status': 'error',
            'message': error_msg
        }
        current_app.logger.error(f"Ошибка выполнения задачи поиска {task_id}: {error_msg}")
    elif task.state == 'SUCCESS':
        response = task.info
    else:
        response = {
            'status': 'unknown',
            'message': f'Неизвестный статус задачи: {task.state}'
        }

    current_app.logger.info(f"Статус задачи поиска {task_id}: {response.get('status')}, прогресс: {response.get('progress', 0)}%")
    return jsonify(response)