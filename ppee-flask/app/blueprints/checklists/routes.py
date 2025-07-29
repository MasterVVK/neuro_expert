from flask import render_template, redirect, url_for, flash, request, jsonify, current_app, session, abort
from flask_login import login_required, current_user
from app import db
from app.models import Checklist, ChecklistParameter
from app.blueprints.checklists import bp
from app.services.fastapi_client import FastAPIClient


@bp.route('/')
@login_required
def index():
    """Страница со списком чек-листов"""
    # Фильтруем чек-листы в зависимости от роли пользователя
    if current_user.is_admin() or current_user.is_prompt_engineer():
        # Админы и промпт-инженеры видят все чек-листы
        checklists = Checklist.query.order_by(Checklist.created_at.desc()).all()
    else:
        # Обычные пользователи видят свои чек-листы И публичные чек-листы
        from sqlalchemy import or_
        checklists = Checklist.query.filter(
            or_(
                Checklist.user_id == current_user.id,
                Checklist.is_public == True
            )
        ).order_by(Checklist.created_at.desc()).all()

    return render_template('checklists/index.html',
                           title='Чек-листы',
                           checklists=checklists)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Создание нового чек-листа (с поддержкой копирования)"""
    # Проверяем, это копирование или обычное создание
    copy_from_id = session.get('copy_from_id', None)
    prefilled_name = session.get('copy_name', '')
    prefilled_description = session.get('copy_description', '')

    original_checklist = None
    if copy_from_id:
        original_checklist = Checklist.query.get(copy_from_id)
        # Очищаем сессию
        session.pop('copy_from_id', None)
        session.pop('copy_name', None)
        session.pop('copy_description', None)

    if request.method == 'POST':
        name = request.form['name']
        description = request.form.get('description', '')
        copy_parameters = request.form.get('copy_parameters') == 'true'

        # Получаем ID оригинального чек-листа из скрытого поля формы
        original_checklist_id = request.form.get('original_checklist_id')

        # Проверяем уникальность имени
        existing = Checklist.query.filter_by(name=name).first()
        if existing:
            flash('Чек-лист с таким названием уже существует', 'error')
            return render_template('checklists/create.html',
                                   title='Создание чек-листа',
                                   prefilled_name=name,
                                   prefilled_description=description,
                                   original_checklist=original_checklist)

        try:
            # Получаем настройку публичности (только для владельцев или админов/промпт-инженеров)
            is_public = False
            if current_user.is_admin() or current_user.is_prompt_engineer():
                is_public = request.form.get('is_public') == 'on'

            # Создаем чек-лист с привязкой к текущему пользователю
            checklist = Checklist(
                name=name,
                description=description,
                user_id=current_user.id,  # Привязываем к текущему пользователю
                is_public=is_public
            )
            db.session.add(checklist)
            db.session.flush()  # Получаем ID нового чек-листа

            # Если это копирование и нужно скопировать параметры
            if original_checklist_id and copy_parameters:
                original = Checklist.query.get(original_checklist_id)
                if original:
                    # Копируем параметры
                    for param in original.parameters.order_by(ChecklistParameter.order_index):
                        new_param = ChecklistParameter(
                            checklist_id=checklist.id,
                            name=param.name,
                            description=param.description,
                            search_query=param.search_query,
                            llm_query=param.llm_query,
                            order_index=param.order_index,
                            use_reranker=param.use_reranker,
                            search_limit=param.search_limit,
                            rerank_limit=param.rerank_limit,
                            use_full_scan=param.use_full_scan,
                            llm_model=param.llm_model,
                            llm_prompt_template=param.llm_prompt_template,
                            llm_temperature=param.llm_temperature,
                            llm_max_tokens=param.llm_max_tokens
                        )
                        db.session.add(new_param)

            db.session.commit()
            flash('Чек-лист успешно создан', 'success')
            return redirect(url_for('checklists.view', id=checklist.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Ошибка при создании чек-листа: {str(e)}")
            flash(f'Ошибка при создании чек-листа: {str(e)}', 'error')
            return render_template('checklists/create.html',
                                   title='Создание чек-листа',
                                   prefilled_name=name,
                                   prefilled_description=description,
                                   original_checklist=original_checklist)

    return render_template('checklists/create.html',
                           title='Создание чек-листа',
                           prefilled_name=prefilled_name,
                           prefilled_description=prefilled_description,
                           original_checklist=original_checklist)


@bp.route('/<int:id>')
@login_required
def view(id):
    """Просмотр чек-листа и его параметров"""
    checklist = Checklist.query.get_or_404(id)

    # Проверяем права на просмотр чек-листа
    if not (current_user.is_admin() or current_user.is_prompt_engineer()):
        # Обычные пользователи могут просматривать свои чек-листы И публичные чек-листы
        if checklist.user_id != current_user.id and not checklist.is_public:
            flash('У вас нет прав для просмотра этого чек-листа', 'error')
            abort(403)

    return render_template('checklists/view.html',
                           title=f'Чек-лист {checklist.name}',
                           checklist=checklist,
                           can_edit=current_user.can_edit_checklist(checklist))


@bp.route('/<int:id>/edit', methods=['POST'])
@login_required
def edit(id):
    """Редактирование названия и описания чек-листа (inline)"""
    checklist = Checklist.query.get_or_404(id)

    # Проверяем права на редактирование
    if not current_user.can_edit_checklist(checklist):
        flash('У вас нет прав для редактирования этого чек-листа', 'error')
        abort(403)

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    
    # Получаем настройку публичности (только для владельцев или админов/промпт-инженеров)
    is_public_new = False
    if current_user.is_admin() or current_user.is_prompt_engineer():
        is_public_new = request.form.get('is_public') == 'on'
    elif checklist.user_id == current_user.id:
        # Владелец может изменять публичность своего чек-листа
        is_public_new = request.form.get('is_public') == 'on'

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

    if checklist.is_public != is_public_new:
        checklist.is_public = is_public_new
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


@bp.route('/<int:id>/copy')
@login_required
def copy(id):
    """Перенаправляет на страницу создания с предзаполненными данными"""
    original_checklist = Checklist.query.get_or_404(id)

    # Проверяем права на копирование
    if not (current_user.is_admin() or current_user.is_prompt_engineer()):
        # Обычные пользователи могут копировать свои чек-листы И публичные чек-листы
        if original_checklist.user_id != current_user.id and not original_checklist.is_public:
            flash('У вас нет прав для копирования этого чек-листа', 'error')
            abort(403)

    # Генерируем уникальное имя для копии
    suggested_name = f"{original_checklist.name} (копия)"
    counter = 1
    while Checklist.query.filter_by(name=suggested_name).first():
        counter += 1
        suggested_name = f"{original_checklist.name} (копия {counter})"

    # Сохраняем данные для копирования в сессии
    session['copy_from_id'] = original_checklist.id
    session['copy_name'] = suggested_name
    session['copy_description'] = original_checklist.description

    flash(f'Создание копии чек-листа "{original_checklist.name}"', 'info')

    return redirect(url_for('checklists.create'))


@bp.route('/<int:id>/parameter/create', methods=['GET', 'POST'])
@login_required
def create_parameter(id):
    """Создание нового параметра для чек-листа"""
    checklist = Checklist.query.get_or_404(id)

    # Проверяем права на редактирование
    if not current_user.can_edit_checklist(checklist):
        flash('У вас нет прав для добавления параметров в этот чек-лист', 'error')
        abort(403)

    if request.method == 'POST':
        name = request.form['name']
        description = request.form.get('description', '')
        search_query = request.form['search_query']

        # Обработка отдельного LLM запроса
        use_separate_llm_query = request.form.get('use_separate_llm_query') == 'true'
        llm_query = None
        if use_separate_llm_query:
            llm_query = request.form.get('llm_query', '').strip()
            if not llm_query:
                llm_query = None

        # Получаем настройки поиска
        search_limit = int(request.form.get('search_limit', 3))
        use_reranker = 'use_reranker' in request.form
        rerank_limit = int(request.form.get('rerank_limit', 10))
        use_full_scan = 'use_full_scan' in request.form

        # Получаем настройки LLM
        llm_model = request.form['llm_model']
        llm_prompt_template = request.form['llm_prompt_template']
        llm_temperature = float(request.form.get('llm_temperature', 0.1))
        llm_max_tokens = int(request.form.get('llm_max_tokens', 1000))

        # Получаем следующий order_index
        next_order = checklist.get_next_order_index()

        parameter = ChecklistParameter(
            checklist_id=checklist.id,
            name=name,
            description=description,
            search_query=search_query,
            llm_query=llm_query,
            order_index=next_order,
            search_limit=search_limit,
            use_reranker=use_reranker,
            rerank_limit=rerank_limit,
            use_full_scan=use_full_scan,
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

    if not available_models:
        available_models = ['gemma3:27b', 'llama3:8b', 'mistral:7b']

    # Получаем модель по умолчанию из конфигурации
    default_llm_model = current_app.config.get('DEFAULT_LLM_MODEL', 'gemma3:27b')

    # Получаем шаблон промпта из конфигурации
    default_prompt = current_app.config.get('DEFAULT_LLM_PROMPT_TEMPLATE')

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

    return render_template('checklists/create_parameter.html',
                           title=f'Добавление параметра - {checklist.name}',
                           checklist=checklist,
                           available_models=available_models,
                           default_llm_model=default_llm_model,
                           default_prompt=default_prompt)


@bp.route('/parameters/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_parameter(id):
    """Редактирование параметра чек-листа"""
    parameter = ChecklistParameter.query.get_or_404(id)
    checklist = parameter.checklist

    # Проверяем права на редактирование
    if not current_user.can_edit_checklist(checklist):
        flash('У вас нет прав для редактирования параметров этого чек-листа', 'error')
        abort(403)

    if request.method == 'POST':
        parameter.name = request.form['name']
        parameter.description = request.form.get('description', '')
        parameter.search_query = request.form['search_query']

        # Обработка отдельного LLM запроса
        use_separate_llm_query = request.form.get('use_separate_llm_query') == 'true'
        if use_separate_llm_query:
            llm_query = request.form.get('llm_query', '').strip()
            parameter.llm_query = llm_query if llm_query else None
        else:
            parameter.llm_query = None

        # Обновляем настройки поиска
        parameter.search_limit = int(request.form.get('search_limit', 3))
        parameter.use_reranker = 'use_reranker' in request.form
        parameter.rerank_limit = int(request.form.get('rerank_limit', 10))
        parameter.use_full_scan = 'use_full_scan' in request.form

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

    if not available_models:
        available_models = ['gemma3:27b', 'llama3:8b', 'mistral:7b']

    return render_template('checklists/edit_parameter.html',
                           title=f'Редактирование параметра - {parameter.name}',
                           checklist=checklist,
                           parameter=parameter,
                           available_models=available_models)


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    """Удаление чек-листа"""
    checklist = Checklist.query.get_or_404(id)

    # Проверяем права на удаление
    if not current_user.can_edit_checklist(checklist):
        flash('У вас нет прав для удаления этого чек-листа', 'error')
        abort(403)

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
@login_required
def delete_parameter(id):
    """Удаление параметра чек-листа"""
    parameter = ChecklistParameter.query.get_or_404(id)
    checklist_id = parameter.checklist_id
    checklist = parameter.checklist

    # Проверяем права на редактирование
    if not current_user.can_edit_checklist(checklist):
        flash('У вас нет прав для удаления параметров этого чек-листа', 'error')
        abort(403)

    try:
        # При удалении нужно обновить order_index для оставшихся параметров
        deleted_order = parameter.order_index

        # Удаляем параметр
        db.session.delete(parameter)

        # Обновляем order_index для параметров с большим индексом
        ChecklistParameter.query.filter(
            ChecklistParameter.checklist_id == checklist_id,
            ChecklistParameter.order_index > deleted_order
        ).update({ChecklistParameter.order_index: ChecklistParameter.order_index - 1})

        db.session.commit()
        flash('Параметр успешно удален', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении параметра: {str(e)}', 'error')

    return redirect(url_for('checklists.view', id=checklist_id))


@bp.route('/parameters/<int:id>/move_up', methods=['POST'])
@login_required
def move_parameter_up(id):
    """Перемещение параметра вверх"""
    parameter = ChecklistParameter.query.get_or_404(id)
    checklist_id = parameter.checklist_id
    checklist = parameter.checklist

    # Проверяем права на редактирование
    if not current_user.can_edit_checklist(checklist):
        flash('У вас нет прав для изменения порядка параметров', 'error')
        abort(403)

    if parameter.order_index > 0:
        # Находим параметр выше
        prev_param = ChecklistParameter.query.filter_by(
            checklist_id=checklist_id,
            order_index=parameter.order_index - 1
        ).first()

        if prev_param:
            # Меняем местами
            prev_param.order_index, parameter.order_index = parameter.order_index, prev_param.order_index
            db.session.commit()
            flash('Параметр перемещен вверх', 'success')

    return redirect(url_for('checklists.view', id=checklist_id))


@bp.route('/parameters/<int:id>/move_down', methods=['POST'])
@login_required
def move_parameter_down(id):
    """Перемещение параметра вниз"""
    parameter = ChecklistParameter.query.get_or_404(id)
    checklist_id = parameter.checklist_id
    checklist = parameter.checklist

    # Проверяем права на редактирование
    if not current_user.can_edit_checklist(checklist):
        flash('У вас нет прав для изменения порядка параметров', 'error')
        abort(403)

    # Находим параметр ниже
    next_param = ChecklistParameter.query.filter_by(
        checklist_id=checklist_id,
        order_index=parameter.order_index + 1
    ).first()

    if next_param:
        # Меняем местами
        next_param.order_index, parameter.order_index = parameter.order_index, next_param.order_index
        db.session.commit()
        flash('Параметр перемещен вниз', 'success')

    return redirect(url_for('checklists.view', id=checklist_id))


@bp.route('/<int:id>/parameters/reorder', methods=['POST'])
@login_required
def reorder_parameters(id):
    """AJAX endpoint для изменения порядка параметров через drag&drop"""
    checklist = Checklist.query.get_or_404(id)

    # Проверяем права на редактирование
    if not current_user.can_edit_checklist(checklist):
        return jsonify({'status': 'error', 'message': 'Нет прав доступа'}), 403

    try:
        # Получаем новый порядок параметров из запроса
        new_order = request.json.get('order', [])

        # Обновляем order_index для каждого параметра
        for index, param_id in enumerate(new_order):
            parameter = ChecklistParameter.query.get(param_id)
            if parameter and parameter.checklist_id == checklist.id:
                parameter.order_index = index

        db.session.commit()

        return jsonify({'status': 'success', 'message': 'Порядок параметров обновлен'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

    # Добавьте новый маршрут в app/blueprints/checklists/routes.py:


@bp.route('/parameters/<int:id>/view')
@login_required
def view_parameter(id):
    """Просмотр параметра чек-листа (только для чтения)"""
    parameter = ChecklistParameter.query.get_or_404(id)
    checklist = parameter.checklist

    # Получаем список доступных моделей для отображения
    client = FastAPIClient()
    available_models = client.get_llm_models()

    if not available_models:
        available_models = ['gemma3:27b', 'llama3:8b', 'mistral:7b']

    return render_template('checklists/view_parameter.html',
                           title=f'Просмотр параметра - {parameter.name}',
                           checklist=checklist,
                           parameter=parameter,
                           available_models=available_models,
                           can_edit=current_user.can_edit_checklist(checklist))