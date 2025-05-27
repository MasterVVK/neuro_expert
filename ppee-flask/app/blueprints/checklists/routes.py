from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from app import db
from app.models import Checklist, ChecklistParameter
from app.blueprints.checklists import bp
from app.services.fastapi_client import FastAPIClient


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


@bp.route('/<int:id>/edit', methods=['POST'])
def edit(id):
    """Редактирование названия и описания чек-листа (inline)"""
    checklist = Checklist.query.get_or_404(id)

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()

    # Валидация
    if not name:
        flash('Название чек-листа не может быть пустым', 'error')
        return redirect(url_for('checklists.view', id=checklist.id))

    # Проверяем, не занято ли имя другим чек-листом
    existing = Checklist.query.filter(
        Checklist.name == name,
        Checklist.id != checklist.id
    ).first()

    if existing:
        flash('Чек-лист с таким названием уже существует', 'error')
        return redirect(url_for('checklists.view', id=checklist.id))

    # Проверяем, были ли изменения
    changes_made = False

    if checklist.name != name:
        checklist.name = name
        changes_made = True

    if checklist.description != description:
        checklist.description = description if description else None
        changes_made = True

    if changes_made:
        try:
            db.session.commit()
            flash('Чек-лист успешно обновлен', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при сохранении изменений: {str(e)}', 'error')
    else:
        flash('Изменений не было', 'info')

    return redirect(url_for('checklists.view', id=checklist.id))


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
    client = FastAPIClient()
    available_models = client.get_llm_models()

    # Если не удалось получить список моделей, используем фиксированный список
    if not available_models:
        available_models = ['gemma3:27b', 'llama3:8b', 'mistral:7b']

    # Получаем модель по умолчанию из конфигурации
    default_llm_model = current_app.config.get('DEFAULT_LLM_MODEL', 'gemma3:27b')

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
                           default_llm_model=default_llm_model,
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
    client = FastAPIClient()
    available_models = client.get_llm_models()

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

    # Проверяем, используется ли чек-лист в заявках
    applications_count = checklist.applications.count()

    if applications_count > 0:
        # Формируем сообщение об ошибке
        error_message = f'Невозможно удалить чек-лист "{checklist.name}", так как он используется в {applications_count} '

        # Правильное склонение слова "заявка"
        if applications_count % 10 == 1 and applications_count % 100 != 11:
            error_message += 'заявке'
        elif applications_count % 10 in [2, 3, 4] and applications_count % 100 not in [12, 13, 14]:
            error_message += 'заявках'
        else:
            error_message += 'заявках'

        error_message += '. Сначала удалите чек-лист из всех заявок.'

        flash(error_message, 'error')
        return redirect(url_for('checklists.view', id=checklist.id))

    try:
        # Если чек-лист не используется, удаляем его
        db.session.delete(checklist)
        db.session.commit()
        flash(f'Чек-лист "{checklist.name}" успешно удален', 'success')
        return redirect(url_for('checklists.index'))
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении чек-листа: {str(e)}', 'error')
        return redirect(url_for('checklists.view', id=checklist.id))


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