import os
from flask import render_template, redirect, url_for, flash, request, current_app, jsonify
from werkzeug.utils import secure_filename
import uuid

from app import db
from app.models import Application, File, Checklist
from app.blueprints.applications import bp
from app.tasks.indexing_tasks import index_document_task
from qdrant_client.http import models  # Добавляем импорт для создания фильтров в Qdrant


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
    try:
        application = Application.query.get_or_404(id)
        return render_template('applications/view.html',
                               title=f'Заявка {application.name}',
                               application=application)
    except Exception as e:
        current_app.logger.error(f"Ошибка при просмотре заявки {id}: {str(e)}")
        flash(f"Ошибка при просмотре заявки: {str(e)}", "error")
        return redirect(url_for('applications.index'))


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
        # Запускаем задачу Celery для анализа
        from app.tasks.llm_tasks import process_parameters_task
        task = process_parameters_task.delay(application.id)

        # Сохраняем ID задачи в базе данных
        application.task_id = task.id
        application.status = 'analyzing'  # Обновляем статус на 'analyzing'
        db.session.commit()

        flash('Анализ заявки успешно запущен. Это может занять некоторое время.', 'success')
    except Exception as e:
        flash(f'Ошибка при запуске анализа: {str(e)}', 'error')
        application.status = 'error'
        application.status_message = str(e)
        db.session.commit()

    return redirect(url_for('applications.view', id=application.id))


@bp.route('/<int:id>/results')
def results(id):
    """Просмотр результатов анализа заявки"""
    try:
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
    except Exception as e:
        current_app.logger.error(f"Ошибка при просмотре результатов заявки {id}: {str(e)}")
        flash(f"Ошибка при просмотре результатов: {str(e)}", "error")
        return redirect(url_for('applications.index'))


@bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    """Удаление заявки"""
    try:
        application = Application.query.get_or_404(id)

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


# НОВЫЙ МАРШРУТ: Статус по ID задачи Celery
@bp.route('/status/<task_id>')
def task_status(task_id):
    """Возвращает текущий статус задачи Celery по ID задачи"""
    # Находим заявку по task_id
    application = Application.query.filter_by(task_id=task_id).first()

    # Если заявка не найдена по task_id, возвращаем ошибку
    if not application:
        current_app.logger.error(f"Заявка с task_id={task_id} не найдена")
        return jsonify({
            'status': 'error',
            'message': f'Задача с ID {task_id} не найдена'
        }), 404

    # Базовый ответ, добавляем статус заявки для дополнительной проверки на клиенте
    response_data = {
        'status': application.status,
        'application_status': application.status,  # Явно добавляем статус заявки
        'progress': 0,
        'message': application.status_message or 'Выполняется обработка...',
        'stage': 'starting'
    }

    # Если заявка уже в завершенном состоянии, отражаем это в ответе
    if application.status in ['indexed', 'analyzed']:
        response_data['status'] = 'success'
        response_data['progress'] = 100
        response_data['stage'] = 'complete'
        response_data['message'] = f'Задача успешно завершена ({application.status})'
        return jsonify(response_data)
    elif application.status == 'error':
        response_data['status'] = 'error'
        response_data['message'] = application.status_message or 'Произошла ошибка при выполнении задачи'
        return jsonify(response_data)

    # Если приложение использует Celery и находится в процессе обработки
    if application.task_id:
        if application.status == 'indexing':
            # Импортируем задачу индексации
            from app.tasks.indexing_tasks import index_document_task
            task = index_document_task.AsyncResult(application.task_id)
        elif application.status == 'analyzing':
            # Импортируем задачу анализа
            from app.tasks.llm_tasks import process_parameters_task
            task = process_parameters_task.AsyncResult(application.task_id)
        else:
            # Если статус не связан с асинхронной задачей, просто возвращаем базовый ответ
            return jsonify(response_data)

        # Обновляем данные ответа на основе информации о задаче
        if task.state == 'PENDING':
            response_data['status'] = 'pending'
            response_data['message'] = 'Задача в очереди на выполнение'
        elif task.state == 'STARTED':
            response_data['status'] = 'progress'
            response_data['progress'] = 5
            response_data['message'] = 'Задача начала выполнение'
        elif task.state == 'PROGRESS' and task.info:
            # Копируем все доступные данные из информации о задаче
            response_data['status'] = 'progress'
            for key, value in task.info.items():
                response_data[key] = value
        elif task.state == 'SUCCESS':
            # Если задача успешно завершена
            response_data['status'] = 'success'
            response_data['progress'] = 100
            response_data['stage'] = 'complete'

            # Если есть дополнительная информация в результате, добавляем ее
            if task.result and isinstance(task.result, dict):
                for key, value in task.result.items():
                    if key not in response_data:
                        response_data[key] = value

            # Обязательно указываем сообщение о завершении
            response_data['message'] = 'Задача успешно завершена'

            # Логируем успешное завершение для отладки
            logger.info(f"Задача {task_id} успешно завершена, статус заявки: {application.status}")
        elif task.state == 'FAILURE':
            response_data['status'] = 'error'
            response_data['message'] = f'Ошибка выполнения задачи: {str(task.result)}'

    current_app.logger.info(
        f"Статус задачи {task_id}: {response_data['status']} ({response_data.get('progress', 0)}%), заявка: {application.status}")
    return jsonify(response_data)


# ОБРАТНАЯ СОВМЕСТИМОСТЬ: Сохраняем старый маршрут, перенаправляя на новый
@bp.route('/<int:id>/status')
def status(id):
    """Возвращает текущий статус заявки по ID заявки"""
    application = Application.query.get_or_404(id)

    # Если у заявки есть task_id, перенаправляем на новый маршрут
    if application.task_id:
        return task_status(application.task_id)

    # Иначе формируем базовый ответ
    response_data = {
        'status': application.status,
        'progress': None,
        'message': application.status_message or 'Неизвестный статус',
        'stage': None
    }

    # Устанавливаем stage в зависимости от статуса
    if application.status == 'indexing':
        response_data['stage'] = 'prepare'
    elif application.status == 'analyzing':
        response_data['stage'] = 'prepare'

    return jsonify(response_data)


@bp.route('/<int:id>/chunks')
def view_chunks(id):
    """Просмотр чанков документов заявки"""
    try:
        application = Application.query.get_or_404(id)

        # Получаем адаптер Qdrant и статистику
        from app.services.vector_service import get_qdrant_adapter
        from qdrant_client.http import models

        qdrant_adapter = get_qdrant_adapter()

        # Получаем статистику по заявке
        stats = qdrant_adapter.qdrant_manager.get_stats(str(application.id))

        # Получаем все чанки заявки (ограничиваем 500 для производительности)
        response = qdrant_adapter.qdrant_manager.client.scroll(
            collection_name=qdrant_adapter.qdrant_manager.collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.application_id",
                        match=models.MatchValue(value=str(application.id))
                    )
                ]
            ),
            limit=500,
            with_payload=True,
            with_vectors=False
        )

        # Преобразуем результаты в более удобный формат
        chunks = []
        for point in response[0]:
            if "payload" in point.__dict__:
                # Получаем текст
                text = ""
                if "page_content" in point.payload:
                    text = point.payload["page_content"]

                # Получаем метаданные
                metadata = {}
                if "metadata" in point.payload:
                    metadata = point.payload["metadata"]

                # Добавляем в список
                chunk = {
                    "id": point.id,
                    "text": text,
                    "metadata": metadata
                }
                chunks.append(chunk)

        # Сортируем чанки по порядку (если есть chunk_index в метаданных)
        chunks.sort(key=lambda x: x["metadata"].get("chunk_index", 0) if x["metadata"] else 0)

        return render_template('applications/chunks.html',
                               title=f'Чанки заявки {application.name}',
                               application=application,
                               chunks=chunks,
                               stats=stats)
    except Exception as e:
        current_app.logger.error(f"Ошибка при просмотре чанков заявки {id}: {str(e)}")
        flash(f"Ошибка при просмотре чанков: {str(e)}", "error")
        return redirect(url_for('applications.index'))