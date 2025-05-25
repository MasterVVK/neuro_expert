import os
from flask import render_template, redirect, url_for, flash, request, current_app, jsonify
from werkzeug.utils import secure_filename
import uuid

from app import db
from app.models import Application, File, Checklist
from app.blueprints.applications import bp
from app.tasks.indexing_tasks import index_document_task
from qdrant_client.http import models  # Добавляем импорт для создания фильтров в Qdrant
from app.services.fastapi_client import FastAPIClient



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

        # Проверяем, выбран ли хотя бы один чек-лист
        if not checklist_ids:
            flash('Необходимо выбрать хотя бы один чек-лист', 'error')
            return render_template('applications/create.html',
                               title='Создание заявки',
                               checklists=checklists)

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
    """Удаление заявки через FastAPI"""
    try:
        application = Application.query.get_or_404(id)

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
        flash(f'Ошибка при удалении заявки: {str(e)}', 'error')

    return redirect(url_for('applications.index'))

# НОВЫЙ МАРШРУТ: Статус по ID задачи Celery

@bp.route('/status/<task_id>')
def task_status(task_id):
    """Возвращает текущий статус задачи через FastAPI"""
    try:
        # Используем FastAPI клиент для получения статуса
        client = FastAPIClient()
        task_data = client.get_task_status(task_id)

        # Преобразуем статус из FastAPI формата в формат Flask
        if task_data['status'] == 'PROGRESS':
            response_data = {
                'status': 'progress',
                'progress': task_data.get('progress', 0),
                'message': task_data.get('message', ''),
                'stage': task_data.get('stage', '')
            }
        elif task_data['status'] == 'SUCCESS':
            response_data = {
                'status': 'success',
                'progress': 100,
                'message': 'Задача успешно завершена',
                'stage': 'complete'
            }
        elif task_data['status'] == 'FAILURE':
            response_data = {
                'status': 'error',
                'message': task_data.get('message', 'Неизвестная ошибка')
            }
        else:
            response_data = task_data

        return jsonify(response_data)

    except Exception as e:
        # Если не удалось получить статус из FastAPI, проверяем БД
        application = Application.query.filter_by(task_id=task_id).first()
        if not application:
            return jsonify({'status': 'error', 'message': 'Задача не найдена'}), 404

        # Возвращаем статус из БД
        return jsonify({
            'status': application.status,
            'application_status': application.status,
            'progress': 100 if application.status in ['indexed', 'analyzed'] else 0,
            'message': application.status_message or 'Обработка...'
        })


def save_analysis_results(application_id, results):
    """Сохраняет результаты анализа в БД"""
    from app.models import ParameterResult, ChecklistParameter

    application = Application.query.get(application_id)
    if not application:
        return

    # Создаем словарь параметров для быстрого доступа
    params_dict = {}
    for checklist in application.checklists:
        for param in checklist.parameters:
            params_dict[param.id] = param

    for result in results:
        parameter_id = result['parameter_id']
        parameter = params_dict.get(parameter_id)

        if not parameter:
            continue

        # Формируем полный промпт так же, как он был отправлен
        full_prompt = parameter.llm_prompt_template.replace(
            "{query}", parameter.search_query
        ).replace(
            "{context}", result.get('context', '[Контекст из результатов поиска]')
        )

        # Формируем полную информацию о запросе
        llm_request_data = {
            'model': parameter.llm_model,
            'temperature': parameter.llm_temperature,
            'max_tokens': parameter.llm_max_tokens,
            'prompt': full_prompt,  # Сохраняем полный промпт
            'response': result.get('llm_response', ''),  # Ответ LLM если есть
            'search_query': parameter.search_query,
            'context_length': result.get('context_length', 8192)
        }

        # Проверяем, есть ли уже результат для этого параметра
        existing_result = ParameterResult.query.filter_by(
            application_id=application_id,
            parameter_id=parameter_id
        ).first()

        if existing_result:
            # Обновляем существующий результат
            existing_result.value = result['value']
            existing_result.confidence = result['confidence']
            existing_result.search_results = result['search_results']
            existing_result.llm_request = llm_request_data  # Сохраняем полную информацию
        else:
            # Создаем новый результат
            param_result = ParameterResult(
                application_id=application_id,
                parameter_id=parameter_id,
                value=result['value'],
                confidence=result['confidence'],
                search_results=result['search_results'],
                llm_request=llm_request_data  # Сохраняем полную информацию
            )
            db.session.add(param_result)

    db.session.commit()


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
        'progress': 0,
        'message': application.status_message or application.get_status_display(),
        'stage': application.status
    }

    return jsonify(response_data)

@bp.route('/<int:id>/chunks')
def view_chunks(id):
    """Просмотр чанков документов заявки через FastAPI"""
    try:
        application = Application.query.get_or_404(id)

        # Используем FastAPI клиент
        client = FastAPIClient()

        # Получаем статистику
        stats = client.get_application_stats(str(application.id))

        # Получаем чанки
        chunks = client.get_application_chunks(str(application.id), limit=500)

        return render_template('applications/chunks.html',
                               title=f'Чанки заявки {application.name}',
                               application=application,
                               chunks=chunks,
                               stats=stats)
    except Exception as e:
        current_app.logger.error(f"Ошибка при просмотре чанков заявки {id}: {str(e)}")
        flash(f"Ошибка при просмотре чанков: {str(e)}", "error")
        return redirect(url_for('applications.index'))