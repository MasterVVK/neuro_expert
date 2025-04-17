from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from app import db
from app.models import Checklist, ChecklistParameter
from app.blueprints.checklists import bp
from app.adapters.llm_adapter import OllamaLLMProvider


@bp.route('/')
def index():
    """Страница со списком чек-листов"""
    checklists = Checklist.query.order_by(Checklist.created_at.desc()).all()
    return render_template('checklists/index.html', title='Чек-листы', checklists=checklists)


@bp.route('/create', methods=['GET', 'POST'])
def create():
    """Создание нового чек-листа"""
    if request.method == 'POST':
        name = request.form['name']
        description = request.form.get('description', '')

        checklist = Checklist(name=name, description=description)
        db.session.add(checklist)
        db.session.commit()

        flash('Чек-лист успешно создан', 'success')
        return redirect(url_for('checklists.view', id=checklist.id))

    return render_template('checklists/create.html', title='Создание чек-листа')


@bp.route('/<int:id>')
def view(id):
    """Просмотр чек-листа и его параметров"""
    checklist = Checklist.query.get_or_404(id)
    return render_template('checklists/view.html',
                           title=f'Чек-лист {checklist.name}',
                           checklist=checklist)


@bp.route('/<int:id>/parameter/create', methods=['GET', 'POST'])
def create_parameter(id):
    """Создание нового параметра для чек-листа"""
    checklist = Checklist.query.get_or_404(id)

    if request.method == 'POST':
        name = request.form['name']
        description = request.form.get('description', '')
        search_query = request.form['search_query']

        # Получаем настройки поиска
        search_limit = int(request.form.get('search_limit', 3))
        use_reranker = 'use_reranker' in request.form
        rerank_limit = int(request.form.get('rerank_limit', 10))

        # Получаем настройки LLM
        llm_model = request.form['llm_model']
        llm_prompt_template = request.form['llm_prompt_template']
        llm_temperature = float(request.form.get('llm_temperature', 0.1))
        llm_max_tokens = int(request.form.get('llm_max_tokens', 1000))

        parameter = ChecklistParameter(
            checklist_id=checklist.id,
            name=name,
            description=description,
            search_query=search_query,
            search_limit=search_limit,
            use_reranker=use_reranker,
            rerank_limit=rerank_limit,
            llm_model=llm_model,
            llm_prompt_template=llm_prompt_template,
            llm_temperature=llm_temperature,
            llm_max_tokens=llm_max_tokens
        )

        db.session.add(parameter)
        db.session.commit()

        flash('Параметр успешно добавлен', 'success')
        return redirect(url_for('checklists.view', id=checklist.id))

    # Получаем список доступных моделей
    llm_provider = OllamaLLMProvider(base_url=current_app.config['OLLAMA_URL'])
    available_models = llm_provider.get_available_models()

    # Если не удалось получить список моделей, используем фиксированный список
    if not available_models:
        available_models = ['gemma3:27b', 'llama3:8b', 'mistral:7b']

    # Шаблон промпта по умолчанию
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

    return render_template('checklists/create_parameter.html',
                           title=f'Добавление параметра - {checklist.name}',
                           checklist=checklist,
                           available_models=available_models,
                           default_prompt=default_prompt)


@bp.route('/parameters/<int:id>/edit', methods=['GET', 'POST'])
def edit_parameter(id):
    """Редактирование параметра чек-листа"""
    parameter = ChecklistParameter.query.get_or_404(id)
    checklist = parameter.checklist

    if request.method == 'POST':
        parameter.name = request.form['name']
        parameter.description = request.form.get('description', '')
        parameter.search_query = request.form['search_query']

        # Обновляем настройки поиска
        parameter.search_limit = int(request.form.get('search_limit', 3))
        parameter.use_reranker = 'use_reranker' in request.form
        parameter.rerank_limit = int(request.form.get('rerank_limit', 10))

        # Обновляем настройки LLM
        parameter.llm_model = request.form['llm_model']
        parameter.llm_prompt_template = request.form['llm_prompt_template']
        parameter.llm_temperature = float(request.form.get('llm_temperature', 0.1))
        parameter.llm_max_tokens = int(request.form.get('llm_max_tokens', 1000))

        db.session.commit()

        flash('Параметр успешно обновлен', 'success')
        return redirect(url_for('checklists.view', id=checklist.id))

    # Получаем список доступных моделей
    llm_provider = OllamaLLMProvider(base_url=current_app.config['OLLAMA_URL'])
    available_models = llm_provider.get_available_models()

    # Если не удалось получить список моделей, используем фиксированный список
    if not available_models:
        available_models = ['gemma3:27b', 'llama3:8b', 'mistral:7b']

    return render_template('checklists/edit_parameter.html',
                           title=f'Редактирование параметра - {parameter.name}',
                           checklist=checklist,
                           parameter=parameter,
                           available_models=available_models)


@bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    """Удаление чек-листа"""
    checklist = Checklist.query.get_or_404(id)

    try:
        db.session.delete(checklist)
        db.session.commit()
        flash('Чек-лист успешно удален', 'success')
    except Exception as e:
        flash(f'Ошибка при удалении чек-листа: {str(e)}', 'error')

    return redirect(url_for('checklists.index'))


@bp.route('/parameters/<int:id>/delete', methods=['POST'])
def delete_parameter(id):
    """Удаление параметра чек-листа"""
    parameter = ChecklistParameter.query.get_or_404(id)
    checklist_id = parameter.checklist_id

    try:
        db.session.delete(parameter)
        db.session.commit()
        flash('Параметр успешно удален', 'success')
    except Exception as e:
        flash(f'Ошибка при удалении параметра: {str(e)}', 'error')

    return redirect(url_for('checklists.view', id=checklist_id))