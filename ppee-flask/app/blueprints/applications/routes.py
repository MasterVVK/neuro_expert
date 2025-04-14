import os
from flask import render_template, redirect, url_for, flash, request, current_app ,jsonify
from werkzeug.utils import secure_filename
import uuid

from app import db
from app.models import Application, File, Checklist
from app.blueprints.applications import bp
from app.tasks.indexing_tasks import index_document_task


@bp.route('/')
def index():
    """Страница со списком заявок"""
    applications = Application.query.order_by(Application.created_at.desc()).all()
    return render_template('applications/index.html',
                           title='Заявки',
                           applications=applications)


@bp.route('/create', methods=['GET', 'POST'])
def create():
    """Создание новой заявки"""
    checklists = Checklist.query.all()

    if request.method == 'POST':
        name = request.form['name']
        description = request.form.get('description', '')
        checklist_ids = request.form.getlist('checklists')

        # Создаем заявку
        application = Application(
            name=name,
            description=description,
            status='created'
        )

        # Добавляем выбранные чек-листы
        for checklist_id in checklist_ids:
            checklist = Checklist.query.get(int(checklist_id))
            if checklist:
                application.checklists.append(checklist)

        db.session.add(application)
        db.session.commit()

        flash('Заявка успешно создана', 'success')
        return redirect(url_for('applications.view', id=application.id))

    return render_template('applications/create.html',
                           title='Создание заявки',
                           checklists=checklists)


@bp.route('/<int:id>')
def view(id):
    """Просмотр заявки"""
    application = Application.query.get_or_404(id)
    return render_template('applications/view.html',
                           title=f'Заявка {application.name}',
                           application=application)


@bp.route('/<int:id>/upload', methods=['GET', 'POST'])
def upload_file(id):
    """Загрузка файла для заявки"""
    application = Application.query.get_or_404(id)

    if request.method == 'POST':
        # Проверяем, был ли файл добавлен к запросу
        if 'document' not in request.files:
            flash('Не выбран файл', 'error')
            return redirect(request.url)

        file = request.files['document']

        # Если пользователь не выбрал файл
        if file.filename == '':
            flash('Не выбран файл', 'error')
            return redirect(request.url)

        if file:
            # Создаем безопасное имя файла
            original_filename = file.filename
            filename = secure_filename(original_filename)

            # Добавляем уникальный идентификатор для избежания конфликтов
            unique_id = str(uuid.uuid4())
            filename = f"{unique_id}_{filename}"

            # Полный путь к файлу
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)

            # Создаем директорию, если она не существует
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Сохраняем файл
            file.save(file_path)

            # Получаем размер файла
            file_size = os.path.getsize(file_path)

            # Определяем тип файла
            _, ext = os.path.splitext(original_filename)
            file_type = 'document'  # По умолчанию

            # Создаем запись о файле
            file_record = File(
                application_id=application.id,
                filename=filename,
                original_filename=original_filename,
                file_path=file_path,
                file_size=file_size,
                file_type=file_type
            )

            # Обновляем статус заявки
            application.status = 'indexing'
            db.session.add(file_record)
            db.session.commit()

            # Запускаем задачу индексации асинхронно через Celery
            try:
                task = index_document_task.delay(application.id, file_record.id)

                # Сохраняем ID задачи
                application.task_id = task.id
                db.session.commit()

                flash('Файл успешно загружен и отправлен на индексацию', 'success')
            except Exception as e:
                flash(f'Ошибка при индексации файла: {str(e)}', 'error')
                application.status = 'error'
                application.status_message = str(e)
                db.session.commit()
                current_app.logger.error(f"Ошибка при индексации файла: {str(e)}")

            return redirect(url_for('applications.view', id=application.id))

    return render_template('applications/upload.html',
                           title=f'Загрузка файла - {application.name}',
                           application=application)
@bp.route('/<int:id>/analyze')
def analyze(id):
    """Запуск анализа заявки"""
    application = Application.query.get_or_404(id)

    # Проверяем, что заявка готова к анализу
    if application.status not in ['indexed', 'analyzed']:
        flash('Заявка не готова к анализу. Дождитесь завершения индексации.', 'error')
        return redirect(url_for('applications.view', id=application.id))

    # Проверяем наличие чек-листов
    if not application.checklists:
        flash('Для заявки не назначен ни один чек-лист', 'error')
        return redirect(url_for('applications.view', id=application.id))

    try:
        # Вызываем функцию analyze_application, которая сама изменит статус
        from app.services.llm_service import analyze_application
        analyze_application(application.id)

        flash('Анализ заявки успешно запущен', 'success')
    except Exception as e:
        flash(f'Ошибка при запуске анализа: {str(e)}', 'error')
        application.status = 'error'
        application.status_message = str(e)
        db.session.commit()

    return redirect(url_for('applications.view', id=application.id))


@bp.route('/<int:id>/results')
def results(id):
    """Просмотр результатов анализа заявки"""
    application = Application.query.get_or_404(id)

    # Проверяем, что у заявки есть результаты
    if application.status != 'analyzed':
        flash('Результаты анализа еще не готовы', 'info')
        return redirect(url_for('applications.view', id=application.id))

    # Получаем результаты по чек-листам
    checklist_results = {}

    for checklist in application.checklists:
        parameters = checklist.parameters.all()
        parameter_results = []

        for parameter in parameters:
            result = parameter.results.filter_by(application_id=application.id).first()
            if result:
                parameter_results.append({
                    'parameter': parameter,
                    'result': result
                })

        checklist_results[checklist.id] = {
            'checklist': checklist,
            'results': parameter_results
        }

    return render_template('applications/results.html',
                           title=f'Результаты анализа - {application.name}',
                           application=application,
                           checklist_results=checklist_results)


@bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    """Удаление заявки"""
    application = Application.query.get_or_404(id)

    try:
        # Удаляем файлы заявки
        for file in application.files:
            if os.path.exists(file.file_path):
                os.remove(file.file_path)

        # Удаляем данные из векторного хранилища
        from app.services.vector_service import delete_application_data
        delete_application_data(str(application.id))

        # Удаляем заявку из базы данных
        db.session.delete(application)
        db.session.commit()

        flash('Заявка успешно удалена', 'success')
    except Exception as e:
        flash(f'Ошибка при удалении заявки: {str(e)}', 'error')

    return redirect(url_for('applications.index'))


@bp.route('/<int:id>/status')
def status(id):
    """Возвращает текущий статус заявки в формате JSON"""
    application = Application.query.get_or_404(id)

    # Базовый ответ
    response_data = {
        'status': application.status,
        'progress': None,
        'message': application.status_message or 'Выполняется обработка...',
        'stage': None
    }

    # Если приложение использует Celery и индексируется, получаем статус задачи
    if application.status == 'indexing' and application.task_id:
        from app.tasks.indexing_tasks import index_document_task
        task = index_document_task.AsyncResult(application.task_id)

        if task.state == 'PROGRESS' and task.info:
            # Копируем все доступные данные из информации о задаче
            for key, value in task.info.items():
                response_data[key] = value

    return jsonify(response_data)