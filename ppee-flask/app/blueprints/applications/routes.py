import os
from flask import render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user  # ДОБАВЛЕНО
from werkzeug.utils import secure_filename
import uuid
import logging
from datetime import datetime

from app.utils.pdf_generator import generate_pdf_report, create_pdf_response
from app import db
from app.models import Application, File, Checklist, ParameterResult, User
from app.blueprints.applications import bp
from app.tasks.indexing_tasks import index_document_task
from qdrant_client.http import models  # Прямой импорт для создания фильтров в Qdrant
from app.services.fastapi_client import FastAPIClient
from app.utils.db_utils import save_analysis_results  # Импортируем из utils
from app.decorators import admin_required, prompt_engineer_required

logger = logging.getLogger(__name__)


def update_application_status(application):
    """Обновляет статус заявки на основе статусов файлов"""
    file_statuses = [f.indexing_status for f in application.files]

    if not file_statuses:
        application.status = 'created'
    elif all(s == 'completed' for s in file_statuses):
        application.status = 'indexed'
        application.status_message = f"Проиндексировано файлов: {len(file_statuses)}"
    elif any(s == 'error' for s in file_statuses):
        errors_count = file_statuses.count('error')
        completed_count = file_statuses.count('completed')
        application.status = 'indexed' if completed_count > 0 else 'error'
        application.status_message = f"Успешно: {completed_count}, Ошибок: {errors_count}"
    elif any(s == 'indexing' for s in file_statuses):
        application.status = 'indexing'
    else:
        application.status = 'created'

    db.session.commit()


@bp.route('/')
@login_required  # ДОБАВЛЕНО
def index():
    """Страница со списком заявок"""
    # ИЗМЕНЕНО: фильтрация по роли
    if current_user.is_admin() or current_user.is_prompt_engineer():
        applications = Application.query.order_by(Application.created_at.desc()).all()
    else:
        applications = Application.query.filter_by(user_id=current_user.id) \
            .order_by(Application.created_at.desc()).all()

    # Получаем все уникальные чек-листы из заявок
    all_checklists = set()
    for app in applications:
        for checklist in app.checklists:
            all_checklists.add(checklist)
    
    # Сортируем чек-листы по имени
    checklists = sorted(list(all_checklists), key=lambda x: x.name)

    return render_template('applications/index.html',
                           title='Заявки',
                           applications=applications,
                           checklists=checklists)


@bp.route('/create', methods=['GET', 'POST'])
@login_required  # ДОБАВЛЕНО
def create():
    """Создание новой заявки"""
    # Фильтруем чек-листы в зависимости от роли пользователя
    if current_user.is_admin() or current_user.is_prompt_engineer():
        # Админы и промпт-инженеры видят все чек-листы
        checklists = Checklist.query.all()
    else:
        # Обычные пользователи видят свои чек-листы И публичные чек-листы
        from sqlalchemy import or_
        checklists = Checklist.query.filter(
            or_(
                Checklist.user_id == current_user.id,
                Checklist.is_public == True
            )
        ).all()

    if request.method == 'POST':
        name = request.form['name']
        description = request.form.get('description', '')
        checklist_ids = request.form.getlist('checklists')

        # Проверяем, выбран ли хотя бы один чек-лист
        if not checklist_ids:
            flash('Необходимо выбрать хотя бы один чек-лист', 'error')
            return render_template('applications/create.html',
                                   title='Создание заявки',
                                   checklists=checklists,
                                   selected_ids=[],
                                   form_id='application-form',
                                   label='Чек-листы',
                                   note='Необходимо выбрать хотя бы один чек-лист',
                                   empty_message='Нет доступных чек-листов. Создайте чек-лист в разделе "Чек-листы".')

        # Создаем заявку
        application = Application(
            name=name,
            description=description,
            status='created',
            user_id=current_user.id  # ДОБАВЛЕНО
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
                           checklists=checklists,
                           selected_ids=[],
                           form_id='application-form',
                           label='Чек-листы',
                           note='Необходимо выбрать хотя бы один чек-лист',
                           empty_message='Нет доступных чек-листов. Создайте чек-лист в разделе "Чек-листы".')



@bp.route('/<int:id>')
@login_required
def view(id):
    """Просмотр заявки"""
    try:
        application = Application.query.get_or_404(id)

        # Проверка доступа
        if not current_user.can_view_application(application):
            flash('У вас нет доступа к этой заявке', 'error')
            return redirect(url_for('applications.index'))

        # Получаем список пользователей для формы смены владельца (для админов и промпт-инженеров)
        users = []
        if current_user.is_admin() or current_user.is_prompt_engineer():
            users = User.query.order_by(User.username).all()

        return render_template('applications/view.html',
                               title=f'Заявка {application.name}',
                               application=application,
                               users=users)  # Добавляем список пользователей
    except Exception as e:
        current_app.logger.error(f"Ошибка при просмотре заявки {id}: {str(e)}")
        flash(f"Ошибка при просмотре заявки: {str(e)}", "error")
        return redirect(url_for('applications.index'))

@bp.route('/<int:id>/edit', methods=['POST'])
@login_required  # ДОБАВЛЕНО
def edit(id):
    """Редактирование названия и описания заявки (inline)"""
    application = Application.query.get_or_404(id)

    # ДОБАВЛЕНО: проверка прав
    if not current_user.can_edit_application(application):
        flash('У вас нет прав для редактирования этой заявки', 'error')
        return redirect(url_for('applications.view', id=application.id))

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()

    # Валидация
    if not name:
        flash('Название заявки не может быть пустым', 'error')
        return redirect(url_for('applications.view', id=application.id))

    # Проверяем, не занято ли имя другой заявкой ТОЛЬКО если название изменилось
    if name != application.name:  # ДОБАВЛЕНО: проверяем только если название изменилось
        existing = Application.query.filter(
            Application.name == name,
            Application.id != application.id
        ).first()

        if existing:
            flash('Заявка с таким названием уже существует', 'error')
            return redirect(url_for('applications.view', id=application.id))

    # Проверяем, были ли изменения
    changes_made = False

    if application.name != name:
        application.name = name
        changes_made = True

    if application.description != description:
        application.description = description if description else None
        changes_made = True

    if changes_made:
        try:
            db.session.commit()
            flash('Заявка успешно обновлена', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при обновлении заявки: {str(e)}', 'error')
    else:
        flash('Никаких изменений не было внесено', 'info')

    return redirect(url_for('applications.view', id=application.id))


@bp.route('/<int:id>/upload', methods=['GET', 'POST'])
@login_required  # ДОБАВЛЕНО
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
            # Получаем оригинальное имя файла
            original_filename = file.filename

            # ВАЖНОЕ ИЗМЕНЕНИЕ: Извлекаем расширение до обработки
            file_root, file_ext = os.path.splitext(original_filename)

            # Создаем безопасное имя файла для базовой части
            safe_filename = secure_filename(file_root)

            # Добавляем уникальный идентификатор
            unique_id = str(uuid.uuid4())

            # Формируем новое имя файла с сохранением расширения
            filename = f"{unique_id}_{safe_filename}{file_ext}"

            # Отладочная информация
            current_app.logger.info(f"Исходное имя: {original_filename}")
            current_app.logger.info(f"Базовая часть: {file_root}, Расширение: {file_ext}")
            current_app.logger.info(f"Обработанное базовое имя: {safe_filename}")
            current_app.logger.info(f"Итоговое имя с UUID: {filename}")

            # Полный путь к файлу
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)

            # Создаем директорию, если она не существует
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Сохраняем файл
            file.save(file_path)

            # Получаем размер файла
            file_size = os.path.getsize(file_path)

            # Определяем тип файла
            file_type = 'document'  # По умолчанию

            # Создаем запись о файле
            file_record = File(
                application_id=application.id,
                filename=filename,
                original_filename=original_filename,
                file_path=file_path,
                file_size=file_size,
                file_type=file_type,
                indexing_status='indexing'  # ИЗМЕНЕНО: сразу устанавливаем 'indexing' вместо 'pending'
            )

            # Обновляем статус заявки
            application.status = 'indexing'
            application.last_operation = 'indexing'
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
                file_record.indexing_status = 'error'  # ДОБАВЛЕНО: меняем статус файла на error
                file_record.error_message = str(e)     # ДОБАВЛЕНО: сохраняем сообщение об ошибке
                db.session.commit()
                current_app.logger.error(f"Ошибка при индексации файла: {str(e)}")

            return redirect(url_for('applications.view', id=application.id))

    return render_template('applications/upload.html',
                           title=f'Загрузка файла - {application.name}',
                           application=application)


@bp.route('/<int:id>/file/<int:file_id>/delete', methods=['POST'])
@login_required  # ДОБАВЛЕНО
def delete_file(id, file_id):
    """Удаление файла из заявки"""
    application = Application.query.get_or_404(id)
    file = File.query.get_or_404(file_id)

    # ДОБАВЛЕНО: проверка прав
    if not current_user.can_edit_application(application):
        flash('У вас нет прав для удаления файлов из этой заявки', 'error')
        return redirect(url_for('applications.view', id=application.id))

    # Проверяем, что файл принадлежит этой заявке
    if file.application_id != application.id:
        flash('Файл не принадлежит этой заявке', 'error')
        return redirect(url_for('applications.view', id=application.id))

    try:
        # Удаляем физический файл
        if os.path.exists(file.file_path):
            os.remove(file.file_path)
            current_app.logger.info(f"Удален файл: {file.file_path}")

        # Удаляем чанки из векторного хранилища
        client = FastAPIClient()
        deleted_count = 0

        # Пробуем удалить по file_id (новый метод)
        try:
            deleted_count = client.delete_file_chunks(str(application.id), str(file_id))
            current_app.logger.info(f"Удалено {deleted_count} чанков по file_id")
        except Exception as e:
            # Если не поддерживается, пробуем по document_id (старый метод)
            current_app.logger.warning(f"Не удалось удалить по file_id, пробуем по document_id: {e}")
            document_id = f"doc_{os.path.basename(file.file_path).replace(' ', '_').replace('.', '_')}"
            try:
                deleted_count = client.delete_document_chunks(str(application.id), document_id)
                current_app.logger.info(f"Удалено {deleted_count} чанков по document_id")
            except Exception as e2:
                current_app.logger.error(f"Не удалось удалить чанки: {e2}")

        # Удаляем запись из БД
        db.session.delete(file)
        db.session.commit()

        # Обновляем статус заявки
        update_application_status(application)

        flash(f'Файл "{file.original_filename}" успешно удален', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Ошибка при удалении файла: {str(e)}")
        flash(f'Ошибка при удалении файла: {str(e)}', 'error')

    return redirect(url_for('applications.view', id=application.id))


@bp.route('/<int:id>/file/<int:file_id>/reindex', methods=['POST'])
@login_required  # ДОБАВЛЕНО
def reindex_file(id, file_id):
    """Переиндексация отдельного файла"""
    application = Application.query.get_or_404(id)
    file = File.query.get_or_404(file_id)

    # ДОБАВЛЕНО: проверка прав
    if not current_user.can_edit_application(application):
        flash('У вас нет прав для переиндексации файлов в этой заявке', 'error')
        return redirect(url_for('applications.view', id=application.id))

    if file.application_id != application.id:
        flash('Файл не принадлежит этой заявке', 'error')
        return redirect(url_for('applications.view', id=application.id))

    try:
        # ВАЖНО: обновляем статус файла на 'indexing'
        file.indexing_status = 'indexing'
        file.error_message = None
        file.chunks_count = 0
        # Сбрасываем время для переиндексируемого файла
        file.indexing_started_at = None
        file.indexing_completed_at = None

        # Обновляем статус заявки на "indexing" для показа прогресс-бара
        application.status = 'indexing'
        application.last_operation = 'indexing'
        db.session.commit()  # Важно! Сохраняем изменения до удаления чанков

        # ПОТОМ удаляем старые чанки
        client = FastAPIClient()
        try:
            deleted_count = client.delete_file_chunks(str(application.id), str(file_id))
            current_app.logger.info(f"Удалено {deleted_count} чанков для файла {file_id}")
        except Exception as e:
            current_app.logger.warning(f"Не удалось удалить чанки по file_id: {e}")
            try:
                document_id = f"doc_{os.path.basename(file.file_path).replace(' ', '_').replace('.', '_')}"
                deleted_count = client.delete_document_chunks(str(application.id), document_id)
                current_app.logger.info(f"Удалено {deleted_count} чанков по document_id")
            except Exception as e2:
                current_app.logger.error(f"Не удалось удалить чанки: {e2}")

        # Запускаем переиндексацию
        task = index_document_task.delay(application.id, file.id)

        # Сохраняем task_id для отслеживания прогресса
        application.task_id = task.id
        db.session.commit()

        flash(f'Запущена переиндексация файла "{file.original_filename}"', 'success')

    except Exception as e:
        flash(f'Ошибка при запуске переиндексации: {str(e)}', 'error')
        # При ошибке возвращаем статус обратно
        file.indexing_status = 'error'
        file.error_message = str(e)
        db.session.commit()

    # Принудительная перезагрузка страницы с уникальным параметром
    import time
    return redirect(url_for('applications.view', id=application.id) + '?t=' + str(int(time.time())))


@bp.route('/<int:id>/analyze')
@login_required  # ДОБАВЛЕНО
def analyze(id):
    """Запуск анализа заявки"""
    application = Application.query.get_or_404(id)

    # ДОБАВЛЕНО: проверка прав
    if not current_user.can_analyze_application(application):
        flash('У вас нет прав для запуска анализа этой заявки', 'error')
        return redirect(url_for('applications.view', id=application.id))

    # Проверяем, что заявка готова к анализу
    if application.status == 'error':
        # При ошибке проверяем, есть ли проиндексированные файлы
        if application.files.filter_by(indexing_status='completed').count() == 0:
            flash('Нет успешно проиндексированных файлов для анализа.', 'error')
            return redirect(url_for('applications.view', id=application.id))
    elif application.status not in ['indexed', 'analyzed']:
        flash('Заявка не готова к анализу. Дождитесь завершения индексации.', 'error')
        return redirect(url_for('applications.view', id=application.id))

    # Проверяем наличие чек-листов
    if not application.checklists:
        flash('Для заявки не назначен ни один чек-лист', 'error')
        return redirect(url_for('applications.view', id=application.id))

    try:
        # ВАЖНО: Чистка старых результатов перед новым анализом
        # Получаем все параметры из чек-листов заявки
        param_ids = []
        for checklist in application.checklists:
            for param in checklist.parameters.all():
                param_ids.append(param.id)

        # Удаляем старые результаты только если есть параметры
        if param_ids:
            deleted_count = ParameterResult.query.filter(
                ParameterResult.application_id == application.id,
                ParameterResult.parameter_id.in_(param_ids)
            ).delete(synchronize_session=False)

            # Сбрасываем счетчик выполненных параметров
            application.analysis_completed_params = 0

            db.session.commit()
            current_app.logger.info(f"Удалено {deleted_count} старых результатов перед анализом заявки {id}")

        # Запускаем задачу Celery для анализа
        from app.tasks.llm_tasks import process_parameters_task
        task = process_parameters_task.delay(application.id)

        # Сохраняем ID задачи в базе данных
        application.task_id = task.id
        application.status = 'analyzing'
        application.last_operation = 'analyzing'
        db.session.commit()

        flash('Анализ заявки успешно запущен. Это может занять некоторое время.', 'success')
    except Exception as e:
        flash(f'Ошибка при запуске анализа: {str(e)}', 'error')
        application.status = 'error'
        application.status_message = str(e)
        application.last_operation = 'analyzing'
        db.session.commit()

    # Принудительная перезагрузка страницы с уникальным параметром
    import time
    return redirect(url_for('applications.view', id=application.id) + '?t=' + str(int(time.time())))


@bp.route('/<int:id>/results')
@login_required  # ДОБАВЛЕНО
def results(id):
    """Просмотр результатов анализа заявки"""
    try:
        application = Application.query.get_or_404(id)

        # Проверяем, что у заявки есть результаты
        if application.status != 'analyzed':
            flash('Результаты анализа еще не готовы', 'info')
            return redirect(url_for('applications.view', id=application.id))

        # Получаем маппинг имен документов
        doc_names_mapping = application.get_document_names_mapping()

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
                               checklist_results=checklist_results,
                               doc_names_mapping=doc_names_mapping)
    except Exception as e:
        current_app.logger.error(f"Ошибка при просмотре результатов заявки {id}: {str(e)}")
        flash(f"Ошибка при просмотре результатов: {str(e)}", "error")
        return redirect(url_for('applications.index'))


@bp.route('/<int:id>/delete', methods=['POST'])
@login_required  # ДОБАВЛЕНО
def delete(id):
    """Удаление заявки через FastAPI"""
    try:
        application = Application.query.get_or_404(id)

        # ДОБАВЛЕНО: проверка прав
        if not current_user.can_delete_application(application):
            flash('У вас нет прав для удаления этой заявки', 'error')
            return redirect(url_for('applications.view', id=application.id))

        # ДОБАВЛЕНО: Очистка связей с чек-листами
        application.checklists = []
        db.session.commit()

        # Удаляем файлы
        for file in application.files:
            if os.path.exists(file.file_path):
                os.remove(file.file_path)

        # Удаляем данные из векторного хранилища через FastAPI
        client = FastAPIClient()
        client.delete_application_data(str(application.id))

        # Удаляем из БД
        db.session.delete(application)
        db.session.commit()

        flash('Заявка успешно удалена', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении заявки: {str(e)}', 'error')

    return redirect(url_for('applications.index'))


@bp.route('/<int:id>/stop_analysis', methods=['POST'])
@login_required  # ДОБАВЛЕНО
def stop_analysis(id):
    """Остановка анализа заявки"""
    application = Application.query.get_or_404(id)

    # ДОБАВЛЕНО: проверка прав
    if not current_user.can_edit_application(application):
        flash('У вас нет прав для остановки анализа этой заявки', 'error')
        return redirect(url_for('applications.view', id=application.id))

    # Проверяем, что заявка в процессе анализа
    if application.status != 'analyzing':
        flash('Заявка не находится в процессе анализа', 'warning')
        return redirect(url_for('applications.view', id=application.id))

    try:
        # Отменяем задачу через Celery
        if application.task_id:
            from app import celery
            celery.control.revoke(application.task_id, terminate=True, signal='SIGKILL')
            current_app.logger.info(f"Остановлен анализ заявки {id}, task_id: {application.task_id}")

        # Устанавливаем время завершения анализа
        if not application.analysis_completed_at:
            application.analysis_completed_at = datetime.utcnow()

        # Обновляем статус заявки
        if application.analysis_completed_params > 0:
            # Если есть частичные результаты
            application.status = 'analyzed'
            application.status_message = f'Анализ остановлен пользователем. Обработано параметров: {application.analysis_completed_params} из {application.analysis_total_params}'
        else:
            # Если нет результатов
            application.status = 'indexed'
            application.status_message = 'Анализ остановлен пользователем'

        application.last_operation = 'analyzing'
        db.session.commit()

        if application.analysis_completed_params > 0:
            flash(
                f'Анализ остановлен. Обработано параметров: {application.analysis_completed_params} из {application.analysis_total_params}',
                'info')
        else:
            flash('Анализ остановлен', 'info')

    except Exception as e:
        flash(f'Ошибка при остановке анализа: {str(e)}', 'error')
        current_app.logger.error(f"Ошибка при остановке анализа заявки {id}: {str(e)}")

    return redirect(url_for('applications.view', id=application.id))


@bp.route('/status/<task_id>')
@login_required
def task_status(task_id):
    """Возвращает текущий статус задачи напрямую из Celery"""
    try:
        # Импортируем celery из нашего приложения
        from app import celery

        # Сначала проверяем статус в БД
        application = Application.query.filter_by(task_id=task_id).first()

        # Проверяем ошибки индексации файлов
        if application and application.status == 'indexing':
            # Проверяем, есть ли файлы с ошибками
            error_files = application.files.filter_by(indexing_status='error').all()
            if error_files:
                # Если есть файлы с ошибками при индексации, возвращаем ошибку
                error_messages = [f.error_message for f in error_files if f.error_message]
                return jsonify({
                    'status': 'error',
                    'message': error_messages[0] if error_messages else 'Ошибка при индексации файла',
                    'progress': 0,
                    'stage': 'error'
                })

        # Добавляем информацию о прогрессе анализа
        if application and application.status == 'analyzing':
            # Получаем статус напрямую из Celery
            try:
                # Получаем результат задачи из Celery
                task = celery.AsyncResult(task_id)

                progress = 0
                message = ''
                stage = 'prepare'  # Значение по умолчанию

                # Проверяем состояние задачи
                if task.state == 'PROGRESS':
                    # task.info содержит meta данные, которые мы передали в update_state
                    if isinstance(task.info, dict):
                        progress = task.info.get('progress', 0)
                        message = task.info.get('message', '')
                        stage = task.info.get('stage', 'prepare')  # ИСПРАВЛЕНО: берем stage из данных задачи!

                # Если не получили прогресс, используем расчет из БД
                if progress == 0 and application.analysis_total_params > 0:
                    progress = application.get_analysis_progress()

                # Если не получили сообщение, формируем из БД
                if not message:
                    message = f'Обработано параметров: {application.analysis_completed_params}/{application.analysis_total_params}'

                # ВАЖНО: Передаем полное сообщение и правильную стадию
                return jsonify({
                    'status': 'progress',
                    'progress': progress,
                    'message': message,  # Полное сообщение с названием параметра
                    'stage': stage,  # ИСПРАВЛЕНО: передаем правильную стадию из Celery
                    'completed_params': application.analysis_completed_params,
                    'total_params': application.analysis_total_params
                })
            except Exception as e:
                logger.error(f"Ошибка при получении статуса из Celery: {e}")
                # Fallback на базовую информацию из БД
                progress = application.get_analysis_progress()
                return jsonify({
                    'status': 'progress',
                    'progress': progress,
                    'message': f'Обработано параметров: {application.analysis_completed_params}/{application.analysis_total_params}',
                    'stage': 'analyze',  # Fallback значение
                    'completed_params': application.analysis_completed_params,
                    'total_params': application.analysis_total_params
                })

        if application and application.status == 'error':
            # Если в БД статус error, сразу возвращаем ошибку
            return jsonify({
                'status': 'error',
                'message': application.status_message or 'Произошла ошибка',
                'progress': 0,
                'stage': 'error'
            })

        # Для остальных случаев используем Celery напрямую
        try:
            task = celery.AsyncResult(task_id)

            # Преобразуем состояние Celery в наш формат
            if task.state == 'PENDING':
                response_data = {
                    'status': 'pending',
                    'progress': 0,
                    'message': 'Задача ожидает выполнения'
                }
            elif task.state == 'PROGRESS':
                # task.info содержит наши meta данные
                info = task.info or {}
                response_data = {
                    'status': 'progress',
                    'progress': info.get('progress', 0),
                    'message': info.get('message', ''),
                    'stage': info.get('stage', '')
                }
            elif task.state == 'SUCCESS':
                response_data = {
                    'status': 'success',
                    'progress': 100,
                    'message': 'Задача успешно завершена',
                    'stage': 'complete'
                }
            elif task.state == 'FAILURE':
                response_data = {
                    'status': 'error',
                    'message': str(task.info) if task.info else 'Неизвестная ошибка'
                }
            else:
                response_data = {
                    'status': task.state.lower(),
                    'message': f'Состояние: {task.state}'
                }

            return jsonify(response_data)

        except Exception as e:
            logger.error(f"Ошибка при получении статуса из Celery: {e}")
            # Fallback на статус из БД
            if application:
                return jsonify({
                    'status': application.status,
                    'application_status': application.status,
                    'progress': 100 if application.status in ['indexed', 'analyzed'] else 0,
                    'message': application.status_message or 'Обработка...'
                })
            else:
                return jsonify({'status': 'error', 'message': 'Задача не найдена'}), 404

    except Exception as e:
        logger.error(f"Ошибка в task_status: {e}")
        # Если не удалось получить статус, проверяем БД
        application = Application.query.filter_by(task_id=task_id).first()
        if not application:
            return jsonify({'status': 'error', 'message': 'Задача не найдена'}), 404

        # Возвращаем статус из БД
        if application.status == 'error':
            return jsonify({
                'status': 'error',
                'message': application.status_message or 'Произошла ошибка',
                'progress': 0,
                'stage': 'error'
            })
        else:
            return jsonify({
                'status': application.status,
                'application_status': application.status,
                'progress': 100 if application.status in ['indexed', 'analyzed'] else 0,
                'message': application.status_message or 'Обработка...'
            })

# ОБРАТНАЯ СОВМЕСТИМОСТЬ: Сохраняем старый маршрут, перенаправляя на новый
@bp.route('/<int:id>/status')
@login_required
def status(id):
    """Возвращает текущий статус заявки по ID заявки"""
    application = Application.query.get_or_404(id)

    # Если у заявки есть task_id, перенаправляем на новый маршрут
    if application.task_id:
        return task_status(application.task_id)

    # Иначе формируем базовый ответ
    response_data = {
        'status': application.status,
        'progress': 0,
        'message': application.status_message or application.get_status_display(),
        'stage': application.status
    }

    return jsonify(response_data)


@bp.route('/<int:id>/chunks')
@login_required
def view_chunks(id):
    """Просмотр чанков документов заявки через FastAPI"""
    try:
        application = Application.query.get_or_404(id)

        # Получаем маппинг имен документов
        doc_names_mapping = application.get_document_names_mapping()

        # Используем FastAPI клиент
        client = FastAPIClient()

        # Получаем статистику
        stats = client.get_application_stats(str(application.id))

        # Получаем чанки
        chunks = client.get_application_chunks(str(application.id), limit=1000)

        return render_template('applications/chunks.html',
                               title=f'Чанки заявки {application.name}',
                               application=application,
                               chunks=chunks,
                               stats=stats,
                               doc_names_mapping=doc_names_mapping)
    except Exception as e:
        current_app.logger.error(f"Ошибка при просмотре чанков заявки {id}: {str(e)}")
        flash(f"Ошибка при просмотре чанков: {str(e)}", "error")
        return redirect(url_for('applications.index'))


@bp.route('/<int:id>/add_checklist', methods=['GET', 'POST'])
@login_required
def add_checklist(id):
    """Добавление чек-листа к существующей заявке"""
    application = Application.query.get_or_404(id)

    # Получаем ID уже назначенных чек-листов
    assigned_checklist_ids = [c.id for c in application.checklists]

    # Фильтруем чек-листы в зависимости от роли пользователя
    from sqlalchemy import or_, and_
    if current_user.is_admin() or current_user.is_prompt_engineer():
        # Админы и промпт-инженеры видят все чек-листы (исключая уже назначенные)
        if assigned_checklist_ids:
            available_checklists = Checklist.query.filter(
                ~Checklist.id.in_(assigned_checklist_ids)
            ).all()
        else:
            available_checklists = Checklist.query.all()
    else:
        # Обычные пользователи видят свои чек-листы И публичные чек-листы (исключая уже назначенные)
        if assigned_checklist_ids:
            available_checklists = Checklist.query.filter(
                and_(
                    ~Checklist.id.in_(assigned_checklist_ids),
                    or_(
                        Checklist.user_id == current_user.id,
                        Checklist.is_public == True
                    )
                )
            ).all()
        else:
            available_checklists = Checklist.query.filter(
                or_(
                    Checklist.user_id == current_user.id,
                    Checklist.is_public == True
                )
            ).all()

    if request.method == 'POST':
        checklist_ids = request.form.getlist('checklists')

        if not checklist_ids:
            flash('Необходимо выбрать хотя бы один чек-лист', 'error')
            return render_template('applications/add_checklist.html',
                                   title=f'Добавление чек-листа - {application.name}',
                                   application=application,
                                   checklists=available_checklists,
                                   selected_ids=[],
                                   form_id='add-checklist-form',
                                   label='Выберите чек-листы для добавления',
                                   note='Выберите один или несколько чек-листов для добавления к заявке',
                                   empty_message='Нет доступных чек-листов для добавления. Все существующие чек-листы уже добавлены к этой заявке.')

        # Добавляем выбранные чек-листы
        added_count = 0
        for checklist_id in checklist_ids:
            checklist = Checklist.query.get(int(checklist_id))
            if checklist and checklist not in application.checklists:
                application.checklists.append(checklist)
                added_count += 1

        if added_count > 0:
            # Если заявка уже была проанализирована, сбрасываем статус
            if application.status == 'analyzed':
                application.status = 'indexed'
                application.status_message = 'Добавлены новые чек-листы. Требуется повторный анализ.'

            db.session.commit()
            flash(f'Успешно добавлено чек-листов: {added_count}', 'success')
        else:
            flash('Выбранные чек-листы уже добавлены к заявке', 'warning')

        return redirect(url_for('applications.view', id=application.id))

    return render_template('applications/add_checklist.html',
                           title=f'Добавление чек-листа - {application.name}',
                           application=application,
                           checklists=available_checklists,
                           selected_ids=[],
                           form_id='add-checklist-form',
                           label='Выберите чек-листы для добавления',
                           note='Выберите один или несколько чек-листов для добавления к заявке',
                           empty_message='Нет доступных чек-листов для добавления. Все существующие чек-листы уже добавлены к этой заявке.')


@bp.route('/<int:id>/remove_checklist/<int:checklist_id>', methods=['POST'])
@login_required
def remove_checklist(id, checklist_id):
    """Удаление чек-листа из заявки"""
    application = Application.query.get_or_404(id)
    checklist = Checklist.query.get_or_404(checklist_id)

    if checklist in application.checklists:
        application.checklists.remove(checklist)

        # Удаляем результаты анализа для параметров этого чек-листа
        for parameter in checklist.parameters:
            ParameterResult.query.filter_by(
                application_id=application.id,
                parameter_id=parameter.id
            ).delete()

        # Если заявка была проанализирована и остались другие чек-листы
        if application.status == 'analyzed' and application.checklists:
            application.status = 'indexed'
            application.status_message = 'Чек-лист удален. Требуется повторный анализ.'

        db.session.commit()
        flash(f'Чек-лист "{checklist.name}" успешно удален из заявки', 'success')
    else:
        flash('Чек-лист не найден в данной заявке', 'error')

    return redirect(url_for('applications.view', id=application.id))


@bp.route('/<int:id>/api/stats')
@login_required
def api_stats(id):
    """API endpoint для получения статистики заявки"""
    try:
        application = Application.query.get_or_404(id)

        # Используем FastAPI клиент для получения статистики
        client = FastAPIClient()
        stats = client.get_application_stats(str(application.id))

        # Добавляем информацию о статусе заявки и файлов
        files_info = {
            'total': application.files.count(),
            'completed': application.files.filter_by(indexing_status='completed').count(),
            'indexing': application.files.filter_by(indexing_status='indexing').count(),
            'error': application.files.filter_by(indexing_status='error').count(),
            'pending': application.files.filter_by(indexing_status='pending').count()
        }

        return jsonify({
            'status': 'success',
            'application_status': application.status,  # Добавляем статус заявки
            'files_status': files_info,  # Добавляем статусы файлов
            'total_chunks': stats.get('total_points', 0),
            'content_types': stats.get('content_types', {}),
            'application_id': id
        })
    except Exception as e:
        current_app.logger.error(f"Ошибка при получении статистики заявки {id}: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e),
            'total_chunks': 0
        }), 500

@bp.route('/<int:id>/partial_results')
@login_required  # ДОБАВЛЕНО
def partial_results(id):
    """Просмотр частичных результатов анализа заявки"""
    try:
        application = Application.query.get_or_404(id)

        # ДОБАВЛЕНО: проверка доступа
        if not current_user.can_view_application(application):
            flash('У вас нет доступа к этой заявке', 'error')
            return redirect(url_for('applications.index'))

        # Проверяем, что заявка в процессе анализа или уже проанализирована
        if application.status not in ['analyzing', 'analyzed']:
            flash('Анализ еще не начат', 'info')
            return redirect(url_for('applications.view', id=application.id))

        # ВАЖНО: Принудительное обновление из БД
        db.session.expire(application)
        db.session.commit()

        # Получаем маппинг имен документов
        doc_names_mapping = application.get_document_names_mapping()

        # Получаем результаты по чек-листам
        checklist_results = {}
        total_results = 0

        for checklist in application.checklists:
            parameters = checklist.parameters.all()
            parameter_results = []

            for parameter in parameters:
                # ВАЖНО: Используем свежий запрос для получения результатов
                result = ParameterResult.query.filter_by(
                    application_id=application.id,
                    parameter_id=parameter.id
                ).first()

                if result:
                    parameter_results.append({
                        'parameter': parameter,
                        'result': result
                    })
                    total_results += 1

            if parameter_results:  # Добавляем только если есть результаты
                checklist_results[checklist.id] = {
                    'checklist': checklist,
                    'results': parameter_results
                }

        # Если нет результатов, но счетчик показывает что они должны быть
        if total_results == 0 and application.analysis_completed_params > 0:
            logger.warning(
                f"Несоответствие: счетчик показывает {application.analysis_completed_params} результатов, но в БД найдено 0")

            # Попробуем еще раз с принудительным обновлением
            db.session.close()
            db.session = db.create_scoped_session()

            # Повторяем запрос
            application = Application.query.get(id)
            for checklist in application.checklists:
                for parameter in checklist.parameters.all():
                    result = ParameterResult.query.filter_by(
                        application_id=application.id,
                        parameter_id=parameter.id
                    ).first()

                    if result:
                        if checklist.id not in checklist_results:
                            checklist_results[checklist.id] = {
                                'checklist': checklist,
                                'results': []
                            }
                        checklist_results[checklist.id]['results'].append({
                            'parameter': parameter,
                            'result': result
                        })
                        total_results += 1

        # Определяем заголовок страницы
        if application.status == 'analyzing':
            title = f'Частичные результаты анализа - {application.name} ({total_results}/{application.analysis_total_params})'
        else:
            title = f'Результаты анализа - {application.name}'

        return render_template('applications/results.html',
                               title=title,
                               application=application,
                               checklist_results=checklist_results,
                               doc_names_mapping=doc_names_mapping,
                               partial_results=True if application.status == 'analyzing' else False)
    except Exception as e:
        current_app.logger.error(f"Ошибка при просмотре частичных результатов заявки {id}: {str(e)}")
        flash(f"Ошибка при просмотре результатов: {str(e)}", "error")
        return redirect(url_for('applications.index'))


@bp.route('/<int:id>/results/pdf')
@login_required  # ДОБАВЛЕНО
def results_pdf(id):
    """Генерация и скачивание PDF отчета с результатами анализа"""
    try:
        application = Application.query.get_or_404(id)

        # ДОБАВЛЕНО: проверка доступа
        if not current_user.can_view_application(application):
            flash('У вас нет доступа к этой заявке', 'error')
            return redirect(url_for('applications.index'))

        # Проверяем, что у заявки есть результаты
        if application.status != 'analyzed':
            flash('Результаты анализа еще не готовы', 'info')
            return redirect(url_for('applications.view', id=application.id))

        # Получаем маппинг имен документов
        doc_names_mapping = application.get_document_names_mapping()

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

        # Генерируем PDF
        pdf_bytes = generate_pdf_report(application, checklist_results, doc_names_mapping)

        # Формируем имя файла
        safe_name = secure_filename(application.name)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"otchet_analiza_{safe_name}_{timestamp}.pdf"

        # Возвращаем PDF как ответ
        return create_pdf_response(pdf_bytes, filename)

    except Exception as e:
        current_app.logger.error(f"Ошибка при генерации PDF для заявки {id}: {str(e)}")
        flash(f"Ошибка при генерации PDF: {str(e)}", "error")
        return redirect(url_for('applications.results', id=id))


# Добавить этот маршрут в файл app/blueprints/applications/routes.py

@bp.route('/<int:id>/change-owner', methods=['POST'])
@login_required
@prompt_engineer_required  # Администраторы и промпт-инженеры могут менять владельца
def change_owner(id):
    """Изменение владельца заявки (для администраторов и промпт-инженеров)"""
    application = Application.query.get_or_404(id)

    # Получаем нового владельца из формы
    new_owner_id = request.form.get('new_owner_id')

    if not new_owner_id:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'Не указан новый владелец'}), 400
        flash('Не указан новый владелец', 'error')
        return redirect(url_for('applications.view', id=application.id))

    # Проверяем существование пользователя
    new_owner = User.query.get(int(new_owner_id))
    if not new_owner:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'Пользователь не найден'}), 404
        flash('Пользователь не найден', 'error')
        return redirect(url_for('applications.view', id=application.id))

    # Сохраняем информацию о старом владельце для логирования
    old_owner = application.user
    if old_owner:
        old_owner_name = old_owner.username
        old_owner_info = f"{old_owner_name} (ID: {old_owner.id})"
    else:
        old_owner_name = "не указан"
        old_owner_info = "не указан"

    # Меняем владельца
    application.user_id = new_owner.id

    try:
        db.session.commit()

        # Логируем изменение с более подробной информацией
        current_app.logger.info(
            f"Владелец заявки {application.id} ({application.name}) изменен "
            f"с {old_owner_info} на {new_owner.username} (ID: {new_owner.id}) "
            f"пользователем {current_user.username} (роль: {current_user.role})"
        )

        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'status': 'success',
                'message': f'Владелец успешно изменен на {new_owner.username}',
                'new_owner': {
                    'id': new_owner.id,
                    'username': new_owner.username,
                    'is_current_user': new_owner.id == current_user.id
                }
            })

        flash(f'Владелец заявки изменен на {new_owner.username}', 'success')
        return redirect(url_for('applications.view', id=application.id))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Ошибка при смене владельца заявки {id}: {str(e)}")

        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'Ошибка при изменении владельца'}), 500

        flash('Ошибка при изменении владельца', 'error')
        return redirect(url_for('applications.view', id=application.id))