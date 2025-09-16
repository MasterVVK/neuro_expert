from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app.blueprints.search import bp
from app.models import Application, Checklist, ChecklistParameter
from app.tasks.search_tasks import semantic_search_task
from app.services.fastapi_client import FastAPIClient
from celery import current_app as celery_app


@bp.route('/')
@login_required
def index():
    """Страница семантического поиска"""
    # Получаем все заявки со статусом indexed или analyzed
    all_applications = Application.query.filter(
        Application.status.in_(['indexed', 'analyzed'])
    ).all()

    # Для обычных пользователей фильтруем на стороне шаблона через JavaScript
    # Это позволяет динамически переключать видимость без перезагрузки страницы
    applications = all_applications

    # Получаем список доступных моделей LLM через FastAPI
    try:
        client = FastAPIClient()
        available_models = client.get_llm_models()
    except Exception as e:
        current_app.logger.error(f"Ошибка при получении списка моделей: {str(e)}")
        available_models = ['gemma3:27b', 'llama3:8b', 'mistral:7b']

    # Получаем модель по умолчанию из конфигурации
    default_llm_model = current_app.config.get('DEFAULT_LLM_MODEL', 'gemma3:27b')

    # Получаем шаблон промпта из конфигурации
    default_prompt = current_app.config.get('DEFAULT_LLM_PROMPT_TEMPLATE')

    # Если в конфигурации нет, используем захардкоженный fallback
    if not default_prompt:
        default_prompt = """Ты эксперт по поиску информации в документах.

Нужно найти значение для параметра: "{query}"

Найденные результаты:
{context}

Твоя задача - извлечь точное значение для параметра "{query}" из предоставленных документов.

Правила:
1. Если значение найдено в нескольких местах, выбери наиболее полное и точное.
2. Если значение в таблице, внимательно определи соответствие между строкой и нужным столбцом.
3. Не добавляй никаких комментариев или пояснений - только параметр и его значение.
4. Значение должно содержать данные, которые есть в документах.
5. Если параметр не найден, укажи: "Информация не найдена".

Ответь одной строкой в указанном формате:
{query}: [значение]"""

    # Получаем DEFAULT_HYBRID_THRESHOLD из конфигурации
    default_hybrid_threshold = current_app.config.get('DEFAULT_HYBRID_THRESHOLD', 20)

    return render_template('search/index.html',
                           title='Семантический поиск',
                           applications=applications,
                           available_models=available_models,
                           default_llm_model=default_llm_model,
                           default_prompt=default_prompt,
                           default_hybrid_threshold=default_hybrid_threshold)


@bp.route('/execute', methods=['POST'])
@login_required  # ДОБАВЛЕНО: требуется авторизация
def execute_search():
    """Выполняет поиск и возвращает результаты в формате JSON"""
    # Проверяем режим поиска - множественный или одиночный
    multi_search = request.form.get('multi_search') == 'true'
    
    if multi_search:
        # Режим множественного выбора
        application_ids_str = request.form.get('application_ids', '')
        if not application_ids_str:
            return jsonify({
                'status': 'error',
                'message': 'Не выбраны заявки для поиска'
            })
        application_ids = [int(id.strip()) for id in application_ids_str.split(',') if id.strip()]
        application_id = None  # Для совместимости с существующим кодом
    else:
        # Режим одиночного выбора
        application_id = request.form.get('application_id')
        application_ids = [int(application_id)] if application_id else []
    
    query = request.form.get('query')
    # Приводим поисковый запрос к нижнему регистру для улучшения поиска
    if query:
        query = query.lower()
    search_limit = int(request.form.get('search_limit', 5))
    use_reranker = request.form.get('use_reranker') == 'true'
    rerank_limit = int(request.form.get('rerank_limit', 10)) if use_reranker else None

    # Параметры для умного/гибридного поиска
    use_smart_search = request.form.get('use_smart_search') == 'true'
    vector_weight = float(request.form.get('vector_weight', 0.5))
    text_weight = float(request.form.get('text_weight', 0.5))
    # Используем DEFAULT_HYBRID_THRESHOLD из конфигурации как fallback
    default_threshold = current_app.config.get('DEFAULT_HYBRID_THRESHOLD', 20)
    hybrid_threshold = int(request.form.get('hybrid_threshold', default_threshold))

    # Параметры LLM
    use_llm = request.form.get('use_llm') == 'true'
    llm_params = None

    if use_llm:
        # Получаем модель по умолчанию из конфигурации
        default_llm_model = current_app.config.get('DEFAULT_LLM_MODEL', 'gemma3:27b')

        llm_params = {
            'model_name': request.form.get('llm_model', default_llm_model),
            'prompt_template': request.form.get('llm_prompt_template', ''),
            'temperature': float(request.form.get('llm_temperature', 0.1)),
            'max_tokens': int(request.form.get('llm_max_tokens', 1000))
        }

    if not application_ids or not query:
        return jsonify({
            'status': 'error',
            'message': 'Не указана заявка или поисковый запрос'
        })

    try:
        # Проверяем права доступа для всех выбранных заявок
        applications = []
        doc_names_mapping = {}
        
        for app_id in application_ids:
            application = Application.query.get(app_id)
            
            if not application:
                return jsonify({
                    'status': 'error',
                    'message': f'Заявка {app_id} не найдена'
                })
            
            if not current_user.can_view_application(application):
                return jsonify({
                    'status': 'error',
                    'message': f'У вас нет доступа к заявке {app_id}'
                })
            
            applications.append(application)
            # Объединяем маппинги документов от всех заявок
            app_mapping = application.get_document_names_mapping()
            doc_names_mapping.update(app_mapping)

        # Логируем запрос
        if multi_search:
            current_app.logger.info(
                f"Множественный поиск: '{query}', Заявки: {application_ids}, "
                f"Ререйтинг: {use_reranker}, Умный поиск: {use_smart_search}, LLM: {use_llm}")
        else:
            current_app.logger.info(
                f"Поиск: '{query}', Заявка: {application_ids[0]}, "
                f"Ререйтинг: {use_reranker}, Умный поиск: {use_smart_search}, LLM: {use_llm}")

        # Вызываем асинхронную задачу Celery для выполнения поиска
        task = semantic_search_task.delay(
            application_id=application_ids[0] if len(application_ids) == 1 else None,
            application_ids=application_ids if multi_search else None,
            query_text=query,
            limit=search_limit,
            use_reranker=use_reranker,
            rerank_limit=rerank_limit,
            use_llm=use_llm,
            llm_params=llm_params,
            use_smart_search=use_smart_search,
            vector_weight=vector_weight,
            text_weight=text_weight,
            hybrid_threshold=hybrid_threshold,
            doc_names_mapping=doc_names_mapping,  # Передаем маппинг
            multi_search=multi_search
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
@login_required  # ДОБАВЛЕНО: требуется авторизация
def check_status(task_id):
    """Проверяет статус выполнения задачи поиска"""
    task = semantic_search_task.AsyncResult(task_id)

    current_app.logger.debug(f"Проверка статуса задачи поиска {task_id}: {task.state}")

    if task.state == 'PENDING':
        response = {
            'status': 'pending',
            'progress': 0,
            'message': 'Задача ожидает выполнения...',
            'stage': 'pending'
        }
    elif task.state == 'PROGRESS':
        # Используем meta данные из update_state
        response = task.info
        # Убеждаемся, что есть все необходимые поля
        if 'status' not in response:
            response['status'] = 'progress'
    elif task.state == 'SUCCESS':
        # Возвращаем результат
        response = task.result if task.result else task.info
        # Убеждаемся, что статус установлен
        if response and isinstance(response, dict):
            response['status'] = 'success'
    elif task.state == 'FAILURE':
        # Обрабатываем ошибку
        if task.info and isinstance(task.info, dict):
            response = task.info
        else:
            error_msg = str(task.info) if task.info else "Неизвестная ошибка при выполнении задачи"
            response = {
                'status': 'error',
                'message': error_msg,
                'progress': 0,
                'stage': 'error'
            }
    else:
        response = {
            'status': 'unknown',
            'message': f'Неизвестный статус задачи: {task.state}',
            'progress': 0,
            'stage': 'unknown'
        }

    current_app.logger.info(
        f"Статус задачи поиска {task_id}: {response.get('status')}, прогресс: {response.get('progress', 0)}%")
    return jsonify(response)


@bp.route('/cancel/<task_id>', methods=['POST'])
@login_required  # ДОБАВЛЕНО: требуется авторизация
def cancel_search(task_id):
    """Отменяет выполнение задачи поиска"""
    try:
        # Пытаемся отменить задачу через Celery
        celery_app.control.revoke(task_id, terminate=True, signal='SIGKILL')

        current_app.logger.info(f"Задача поиска {task_id} отменена")

        return jsonify({
            'status': 'success',
            'message': 'Задача успешно отменена'
        })
    except Exception as e:
        current_app.logger.error(f"Ошибка при отмене задачи {task_id}: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Не удалось отменить задачу: {str(e)}'
        }), 500