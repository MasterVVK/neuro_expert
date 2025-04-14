import os
from flask import render_template, redirect, url_for, flash, request, current_app
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
        # Проверяем, был ли файл в запросе
        if 'document' not in request.files:
            flash('Файл не выбран', 'error')
            return redirect(request.url)

        file = request.files['document']

        # Если пользователь не выбрал файл
        if file.filename == '':
            flash('Файл не выбран', 'error')
            return redirect(request.url)

        if file:
            # Генерация уникального имени файла
            filename = secure_filename(file.filename)
            filename_parts = os.path.splitext(filename)
            unique_filename = f"{filename_parts[0]}_{uuid.uuid4().hex[:8]}{filename_parts[1]}"

            # Полный путь для сохранения
            uploads_path = os.path.join(current_app.root_path, current_app.config['UPLOAD_FOLDER'])
            application_uploads_path = os.path.join(uploads_path, f"app_{application.id}")
            os.makedirs(application_uploads_path, exist_ok=True)

            # Используем абсолютный путь для предотвращения проблем
            file_path = os.path.abspath(os.path.join(application_uploads_path, unique_filename))

            # Сохраняем файл
            file.save(file_path)

            # Проверяем, что файл успешно создан
            if not os.path.exists(file_path):
                flash(f'Ошибка при сохранении файла: файл не найден после сохранения', 'error')
                return redirect(request.url)

            # Создаем запись о файле
            file_record = File(
                application_id=application.id,
                filename=unique_filename,
                original_filename=filename,
                file_path=file_path,
                file_size=os.path.getsize(file_path),
                file_type='document'
            )

            # Обновляем статус заявки
            application.status = 'indexing'

            db.session.add(file_record)
            db.session.commit()

            # Запускаем задачу индексации в фоновом режиме
            # Поскольку Celery еще не настроен полностью, выполним синхронно
            try:
                # В реальном приложении здесь будет асинхронный вызов
                # index_document_task.delay(application.id, file_record.id)

                # Логгирование информации о файле
                current_app.logger.info(f"Загрузка файла: {file_record.original_filename}")
                current_app.logger.info(f"Путь к файлу: {file_record.file_path}")
                current_app.logger.info(f"Размер файла: {file_record.file_size} байт")

                # Синхронный вызов для тестирования
                from app.services.vector_service import index_document
                index_document(application.id, file_record.id)
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