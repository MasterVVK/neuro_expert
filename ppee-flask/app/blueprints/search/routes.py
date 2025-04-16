from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from app.blueprints.search import bp
from app.models import Application
from app.tasks.search_tasks import semantic_search_task


@bp.route('/')
def index():
    """Страница семантического поиска"""
    # Получаем список доступных заявок
    applications = Application.query.filter(Application.status.in_(['indexed', 'analyzed'])).all()

    return render_template('search/index.html',
                           title='Семантический поиск',
                           applications=applications)


@bp.route('/execute', methods=['POST'])
def execute_search():
    """Выполняет поиск и возвращает результаты в формате JSON"""
    application_id = request.form.get('application_id')
    query = request.form.get('query')
    limit = int(request.form.get('limit', 5))
    use_reranker = request.form.get('use_reranker') == 'true'  # Получаем параметр ререйтинга

    if not application_id or not query:
        return jsonify({
            'status': 'error',
            'message': 'Не указана заявка или поисковый запрос'
        })

    try:
        # Логируем запрос
        current_app.logger.info(f"Поиск: '{query}', Заявка: {application_id}, Ререйтинг: {use_reranker}")

        # Вызываем асинхронную задачу Celery для выполнения поиска
        task = semantic_search_task.delay(
            application_id=application_id,
            query_text=query,
            limit=limit,
            use_reranker=use_reranker
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

    if task.state == 'PENDING':
        response = {
            'status': 'pending',
            'progress': 0,
            'message': 'Задача ожидает выполнения...'
        }
    elif task.state == 'PROGRESS':
        response = {
            'status': 'progress',
            'progress': task.info.get('progress', 0),
            'message': task.info.get('message', ''),
            'substatus': task.info.get('status', '')
        }
    elif task.state == 'FAILURE':
        response = {
            'status': 'error',
            'message': str(task.info)
        }
    elif task.state == 'SUCCESS':
        response = task.info
    else:
        response = {
            'status': 'unknown',
            'message': 'Неизвестный статус задачи'
        }

    return jsonify(response)