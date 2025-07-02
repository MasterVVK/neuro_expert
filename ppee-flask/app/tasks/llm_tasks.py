from app import celery, db, create_app
from app.models import Application, ParameterResult
from datetime import datetime
import logging
import requests
import time
import re
from celery.exceptions import Terminated, WorkerLostError

logger = logging.getLogger(__name__)
FASTAPI_URL = "http://localhost:8001"


def save_single_result(application_id, parameter_id, result_data):
    """Сохраняет результат для одного параметра"""
    try:
        # Проверяем, есть ли уже результат
        existing = ParameterResult.query.filter_by(
            application_id=application_id,
            parameter_id=parameter_id
        ).first()

        if existing:
            # Обновляем существующий
            existing.value = result_data['value']
            existing.confidence = result_data['confidence']
            existing.search_results = result_data['search_results']
            existing.llm_request = result_data.get('llm_request', {})
        else:
            # Создаем новый
            param_result = ParameterResult(
                application_id=application_id,
                parameter_id=parameter_id,
                value=result_data['value'],
                confidence=result_data['confidence'],
                search_results=result_data['search_results'],
                llm_request=result_data.get('llm_request', {})
            )
            db.session.add(param_result)

        db.session.commit()
        logger.info(f"Результат сохранен для параметра {parameter_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении результата для параметра {parameter_id}: {e}")
        db.session.rollback()
        return False


def get_all_chunks_for_application(application_id, batch_size=100):
    """Получает все чанки для заявки партиями"""
    try:
        offset = 0
        all_chunks = []

        while True:
            response = requests.get(
                f"{FASTAPI_URL}/applications/{application_id}/chunks",
                params={"limit": batch_size, "offset": offset}
            )

            if response.status_code != 200:
                logger.error(f"Ошибка получения чанков: {response.text}")
                break

            data = response.json()
            chunks = data.get("chunks", [])

            if not chunks:
                break

            all_chunks.extend(chunks)
            offset += batch_size

            # Если получили меньше чем batch_size, значит это последняя партия
            if len(chunks) < batch_size:
                break

        return all_chunks
    except Exception as e:
        logger.error(f"Ошибка при получении всех чанков: {e}")
        return []


def process_chunks_batch_through_llm(chunks_batch, param_data, model_name):
    """Обрабатывает пакет чанков через LLM"""
    try:
        # Форматируем контекст из пакета чанков
        context_parts = []
        for i, chunk in enumerate(chunks_batch):
            chunk_text = format_single_chunk_for_context(chunk)
            context_parts.append(f"Чанк {i + 1}:\n{chunk_text}")

        context = "\n\n".join(context_parts)

        # Подготавливаем промпт
        prompt = param_data['prompt_template'].format(
            query=param_data['llm_query'],
            context=context
        )

        # Отправляем запрос к LLM
        llm_response = requests.post(f"{FASTAPI_URL}/llm/process", json={
            "model_name": model_name,
            "prompt": prompt,
            "context": "",  # Контекст уже включен в промпт
            "parameters": {
                'temperature': param_data['temperature'],
                'max_tokens': param_data['max_tokens'],
                'search_query': param_data['llm_query']
            },
            "query": param_data['llm_query']
        })

        if llm_response.status_code == 200:
            llm_text = llm_response.json()["response"]

            # Проверяем, найдена ли информация
            if "информация не найдена" not in llm_text.lower():
                # Извлекаем значение
                value = extract_value_from_response(llm_text, param_data['llm_query'])

                # Если значение не содержит "информация не найдена"
                if "информация не найдена" not in value.lower():
                    return {
                        'found': True,
                        'value': value,
                        'chunks': chunks_batch,  # Возвращаем все чанки из пакета
                        'response': llm_text,
                        'prompt': prompt  # ДОБАВЛЕНО: возвращаем промпт!
                    }

        return {'found': False}

    except Exception as e:
        logger.error(f"Ошибка при обработке пакета чанков через LLM: {e}")
        return {'found': False}


def group_chunks_by_size(chunks, max_size=14000):
    """Группирует чанки по размеру для оптимизации запросов к LLM"""
    batches = []
    current_batch = []
    current_size = 0

    for chunk in chunks:
        # Получаем размер контента из метаданных
        metadata = chunk.get('metadata', {})
        content_length = metadata.get('content_length')

        # Если нет content_length, обрабатываем чанк отдельно
        if content_length is None:
            # Если есть накопленный пакет, добавляем его
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_size = 0

            # Добавляем чанк как отдельный пакет
            batches.append([chunk])
            continue

        # Если добавление чанка превысит лимит, создаем новый пакет
        if current_size + content_length > max_size and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_size = 0

        # Добавляем чанк в текущий пакет
        current_batch.append(chunk)
        current_size += content_length

    # Добавляем последний пакет, если есть
    if current_batch:
        batches.append(current_batch)

    return batches


def format_single_chunk_for_context(chunk):
    """Форматирует один чанк для контекста"""
    text = chunk.get('text', '')
    metadata = chunk.get('metadata', {})

    doc_text = "Документ:\n"
    if metadata.get('section'):
        doc_text += f"Раздел: {metadata['section']}\n"
    if metadata.get('content_type'):
        doc_text += f"Тип: {metadata['content_type']}\n"
    if metadata.get('page_number'):
        doc_text += f"Страница: {metadata['page_number']}\n"
    doc_text += f"Текст:\n{text}"
    doc_text = f"{text}\n"

    return doc_text


@celery.task(bind=True)
def process_parameters_task(self, application_id):
    """Трехэтапная обработка: поиск, LLM, и полное сканирование при необходимости"""
    # Создаем контекст приложения для работы с БД
    app = create_app()

    with app.app_context():
        # Используем свежий запрос к БД для избежания проблем с кешированием
        application = db.session.query(Application).filter_by(id=application_id).first()

        if not application:
            return {'status': 'error', 'message': f"Заявка с ID {application_id} не найдена"}

        # Логируем начало задачи
        logger.info(f"[TASK {self.request.id}] Начало анализа заявки {application_id}")

        # Обновляем статус
        task_id = self.request.id
        application.status = "analyzing"
        application.task_id = task_id
        application.analysis_started_at = datetime.utcnow()

        # Собираем все параметры
        all_params = []
        for checklist in application.checklists:
            for param in checklist.parameters.all():
                all_params.append(param)

        total_params = len(all_params)
        application.analysis_total_params = total_params
        application.analysis_completed_params = 0
        db.session.commit()

        try:
            # ЭТАП 1: Поиск и подготовка промптов для всех параметров
            logger.info(f"Этап 1: Поиск для {total_params} параметров")

            self.update_state(
                state='PROGRESS',
                meta={
                    'status': 'progress',
                    'progress': 5,
                    'stage': 'search',
                    'message': f'Этап 1/3: Поиск информации для всех параметров (0/{total_params})...'
                }
            )

            # Словарь для хранения подготовленных данных
            prepared_requests = {}  # {param_id: {search_results, prompt, model, ...}}
            params_need_full_scan = []  # Параметры для полного сканирования

            # Выполняем поиск для каждого параметра
            for i, param in enumerate(all_params):
                # Обновляем прогресс
                search_progress = 5 + int((i / total_params) * 40)
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'status': 'progress',
                        'progress': search_progress,
                        'stage': 'search',
                        'message': f'Этап 1/3: Поиск ({i + 1}/{total_params}): {param.name}'
                    }
                )

                # Выполняем поиск используя search_query
                try:
                    search_response = requests.post(f"{FASTAPI_URL}/search", json={
                        "application_id": str(application_id),
                        "query": param.search_query,  # Всегда используем search_query для поиска
                        "limit": param.search_limit,
                        "use_reranker": param.use_reranker,
                        "rerank_limit": param.rerank_limit if param.use_reranker else None,
                        "use_smart_search": True,
                        "vector_weight": 0.5,
                        "text_weight": 0.5,
                        "hybrid_threshold": 10
                    })

                    if search_response.status_code == 200:
                        search_results = search_response.json()["results"]

                        # Форматируем контекст
                        context = format_documents_for_context(search_results)

                        # Используем правильный запрос для LLM
                        llm_query = param.get_llm_query() if hasattr(param,
                                                                     'get_llm_query') else param.llm_query or param.search_query

                        # Подготавливаем промпт с правильным query
                        prompt = param.llm_prompt_template.format(
                            query=llm_query,
                            context=context
                        )

                        # Сохраняем подготовленные данные
                        prepared_requests[param.id] = {
                            'param': param,
                            'search_results': search_results,
                            'prompt': prompt,
                            'model': param.llm_model,
                            'temperature': param.llm_temperature,
                            'max_tokens': param.llm_max_tokens,
                            'llm_query': llm_query,
                            'search_query': param.search_query,
                            'use_full_scan': getattr(param, 'use_full_scan', False)  # Добавляем флаг
                        }

                        logger.info(f"Поиск завершен для параметра {param.id}: {param.name}")
                    else:
                        logger.error(f"Ошибка поиска для параметра {param.id}: {search_response.text}")

                except Exception as e:
                    logger.error(f"Ошибка при поиске для параметра {param.id}: {e}")

                # Проверяем отмену
                if check_if_cancelled(self):
                    return handle_cancellation(application_id)

            # ЭТАП 2: Группируем по моделям и обрабатываем через LLM
            logger.info(f"Этап 2: Обработка через LLM")

            self.update_state(
                state='PROGRESS',
                meta={
                    'status': 'progress',
                    'progress': 45,
                    'stage': 'analyze',
                    'message': 'Этап 2/3: Группировка запросов по моделям...'
                }
            )

            # Группируем подготовленные запросы по моделям
            model_groups = {}
            for param_id, data in prepared_requests.items():
                model = data['model']
                if model not in model_groups:
                    model_groups[model] = []
                model_groups[model].append((param_id, data))

            logger.info(f"Запросы сгруппированы по моделям: {list(model_groups.keys())}")

            # Обрабатываем каждую группу
            completed_params = 0

            for model_name, param_group in model_groups.items():
                logger.info(f"Обработка {len(param_group)} параметров через модель {model_name}")

                # Обновляем прогресс
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'status': 'progress',
                        'progress': 50 + int((completed_params / total_params) * 35),
                        'stage': 'analyze',
                        'message': f'Этап 2/3: Обработка через {model_name} (запросов:{len(param_group)})'
                    }
                )

                # Обрабатываем каждый параметр в группе
                for param_id, data in param_group:
                    try:
                        # Отправляем запрос к LLM
                        llm_response = requests.post(f"{FASTAPI_URL}/llm/process", json={
                            "model_name": model_name,
                            "prompt": data['prompt'],
                            "context": "",  # Контекст уже включен в промпт
                            "parameters": {
                                'temperature': data['temperature'],
                                'max_tokens': data['max_tokens'],
                                'search_query': data['llm_query']
                            },
                            "query": data['llm_query']
                        })

                        if llm_response.status_code == 200:
                            llm_text = llm_response.json()["response"]

                            # Извлекаем значение и рассчитываем уверенность
                            value = extract_value_from_response(llm_text, data['llm_query'])
                            confidence = calculate_confidence(llm_text)

                            # Проверяем, найдена ли информация
                            if "информация не найдена" in value.lower() and data.get('use_full_scan', False):
                                # Добавляем в список для полного сканирования
                                params_need_full_scan.append({
                                    'param_id': param_id,
                                    'data': data,
                                    'initial_search_results': data['search_results'],
                                    'initial_llm_response': llm_text
                                })
                                logger.info(f"Параметр {param_id} добавлен для полного сканирования")
                            else:
                                # Сохраняем результат
                                result_data = {
                                    'parameter_id': param_id,
                                    'value': value,
                                    'confidence': confidence,
                                    'search_results': data['search_results'],
                                    'llm_request': {
                                        'prompt': data['prompt'],
                                        'model': model_name,
                                        'temperature': data['temperature'],
                                        'max_tokens': data['max_tokens'],
                                        'response': llm_text,
                                        'search_query': data['search_query'],
                                        'llm_query': data['llm_query']
                                    }
                                }

                                # Сохраняем в БД
                                if save_single_result(application_id, param_id, result_data):
                                    completed_params += 1

                                    # Обновляем счетчик в заявке
                                    application.analysis_completed_params = completed_params
                                    db.session.commit()

                                    # Обновляем прогресс
                                    current_param_name = data['param'].name
                                    self.update_state(
                                        state='PROGRESS',
                                        meta={
                                            'status': 'progress',
                                            'progress': 50 + int((completed_params / total_params) * 35),
                                            'stage': 'analyze',
                                            'message': f'Проанализирован параметр {completed_params}/{total_params}: {current_param_name} [Модель: {model_name}]',
                                            'completed_params': completed_params,
                                            'total_params': total_params
                                        }
                                    )

                    except Exception as e:
                        logger.error(f"Ошибка обработки параметра {param_id}: {e}")

                    # Проверяем отмену после каждого параметра
                    if check_if_cancelled(self):
                        return handle_cancellation(application_id)

            # ЭТАП 3: Полное сканирование для параметров, где информация не найдена
            if params_need_full_scan:
                logger.info(f"Этап 3: Полное сканирование для {len(params_need_full_scan)} параметров")

                self.update_state(
                    state='PROGRESS',
                    meta={
                        'status': 'progress',
                        'progress': 85,
                        'stage': 'full_scan',
                        'message': f'Этап 3/3: Полное сканирование чанков для {len(params_need_full_scan)} параметров...'
                    }
                )

                # Получаем все чанки заявки
                all_chunks = get_all_chunks_for_application(application_id)
                total_chunks = len(all_chunks)
                logger.info(f"Получено {total_chunks} чанков для полного сканирования")

                # Группируем чанки по размеру
                chunk_batches = group_chunks_by_size(all_chunks, max_size=14000)
                total_batches = len(chunk_batches)
                logger.info(f"Чанки сгруппированы в {total_batches} пакетов")

                # Обрабатываем каждый параметр
                for param_idx, param_info in enumerate(params_need_full_scan):
                    param_id = param_info['param_id']
                    data = param_info['data']
                    param_name = data['param'].name

                    logger.info(f"Полное сканирование для параметра {param_name}")

                    # Обновляем прогресс
                    self.update_state(
                        state='PROGRESS',
                        meta={
                            'status': 'progress',
                            'progress': 85 + int((param_idx / len(params_need_full_scan)) * 10),
                            'stage': 'full_scan',
                            'message': f'Этап 3/3: Полное сканирование для "{param_name}" (0/{total_batches} пакетов)...'
                        }
                    )

                    found = False
                    found_chunks = None
                    found_response = None
                    found_value = None
                    found_prompt = None  # ДОБАВЛЕНО: переменная для промпта
                    chunks_processed = 0

                    # Проверяем каждый пакет чанков
                    for batch_idx, chunk_batch in enumerate(chunk_batches):
                        # Проверяем отмену
                        if check_if_cancelled(self):
                            return handle_cancellation(application_id)

                        # Обновляем прогресс
                        self.update_state(
                            state='PROGRESS',
                            meta={
                                'status': 'progress',
                                'progress': 85 + int((param_idx / len(params_need_full_scan)) * 10),
                                'stage': 'full_scan',
                                'message': f'Этап 3/3: Сканирование для "{param_name}" (пакет {batch_idx + 1}/{total_batches}, {chunks_processed}/{total_chunks} чанков)...'
                            }
                        )

                        # Обрабатываем пакет чанков через LLM
                        result = process_chunks_batch_through_llm(chunk_batch, {
                            'prompt_template': data['param'].llm_prompt_template,
                            'llm_query': data['llm_query'],
                            'temperature': data['temperature'],
                            'max_tokens': data['max_tokens']
                        }, data['model'])

                        chunks_processed += len(chunk_batch)

                        if result['found']:
                            found = True
                            found_chunks = result['chunks']
                            found_response = result['response']
                            found_value = result['value']
                            found_prompt = result.get('prompt', '')  # ДОБАВЛЕНО: сохраняем промпт
                            logger.info(f"Информация найдена для параметра {param_name} в пакете {batch_idx + 1}")
                            break

                    # Сохраняем результат
                    if found:
                        # Форматируем найденные чанки как результаты поиска
                        search_results = []

                        # Логируем информацию о найденных чанках для отладки
                        logger.info(f"Найдено {len(found_chunks)} чанков в пакете для параметра {param_name}")

                        for chunk in found_chunks:
                            metadata = chunk.get('metadata', {})
                            page_num = metadata.get('page_number')
                            doc_id = metadata.get('document_id')

                            logger.info(f"  Чанк: документ={doc_id}, страница={page_num}")

                            search_results.append({
                                'text': chunk.get('text', ''),
                                'metadata': metadata,
                                'score': 1.0,  # Максимальная релевантность
                                'search_type': 'full_scan'
                            })

                        result_data = {
                            'parameter_id': param_id,
                            'value': found_value,
                            'confidence': 0.9,  # Высокая уверенность при полном сканировании
                            'search_results': search_results,  # Сохраняем ВСЕ чанки из пакета
                            'llm_request': {
                                'prompt': found_prompt or 'Промпт не сохранен',  # ИСПРАВЛЕНО: используем реальный промпт
                                'model': data['model'],
                                'temperature': data['temperature'],
                                'max_tokens': data['max_tokens'],
                                'response': found_response,
                                'search_query': data['search_query'],
                                'llm_query': data['llm_query'],
                                'full_scan': True,
                                'chunks_scanned': chunks_processed,
                                'batch_size': len(found_chunks),
                                'batch_pages': [chunk.get('metadata', {}).get('page_number', 'unknown') for chunk in
                                                found_chunks]
                            }
                        }
                    else:
                        # Информация не найдена даже после полного сканирования
                        result_data = {
                            'parameter_id': param_id,
                            'value': f"Информация не найдена по всем {total_chunks} чанкам",
                            'confidence': 0.1,
                            'search_results': param_info['initial_search_results'],
                            'llm_request': {
                                'prompt': data['prompt'],
                                'model': data['model'],
                                'temperature': data['temperature'],
                                'max_tokens': data['max_tokens'],
                                'response': param_info['initial_llm_response'],
                                'search_query': data['search_query'],
                                'llm_query': data['llm_query'],
                                'full_scan': True,
                                'chunks_scanned': total_chunks,
                                'batches_processed': total_batches,
                                'full_scan_result': 'not_found'
                            }
                        }

                    # Сохраняем в БД
                    if save_single_result(application_id, param_id, result_data):
                        completed_params += 1
                        application.analysis_completed_params = completed_params
                        db.session.commit()

            # Завершаем анализ
            application.status = "analyzed"
            application.status_message = "Анализ завершен успешно"
            application.analysis_completed_at = datetime.utcnow()  # ИЗМЕНЕНИЕ: устанавливаем время завершения
            db.session.commit()

            self.update_state(
                state='SUCCESS',
                meta={
                    'status': 'success',
                    'progress': 100,
                    'stage': 'complete',
                    'message': 'Анализ завершен!'
                }
            )

            logger.info(f"Анализ заявки {application_id} завершен. Обработано {completed_params} параметров")
            return {"status": "success", "message": "Анализ завершен"}

        except (Terminated, WorkerLostError) as e:
            # Задача была отменена
            logger.info(f"Задача анализа заявки {application_id} была отменена: {e}")
            return handle_cancellation(application_id)

        except Exception as e:
            logger.error(f"Ошибка при анализе: {e}")
            error_app = Application.query.get(application_id)
            if error_app:
                error_app.status = "error"
                error_app.status_message = str(e)
                error_app.last_operation = 'analyzing'
                # ИЗМЕНЕНИЕ: При ошибке также сохраняем время окончания
                if not error_app.analysis_completed_at:
                    error_app.analysis_completed_at = datetime.utcnow()
                db.session.commit()
            logger.info(f"[TASK {self.request.id}] Ошибка анализа заявки {application_id}: {e}")
            return {"status": "error", "message": str(e)}


def format_documents_for_context(documents, max_docs=8):
    """Форматирует документы для контекста"""
    formatted = []
    for i, doc in enumerate(documents[:max_docs]):
        text = doc.get('text', '')
        metadata = doc.get('metadata', {})

        doc_text = f"Документ {i + 1}:\n"
#        if metadata.get('section'):
#            doc_text += f"Раздел: {metadata['section']}\n"
#        if metadata.get('content_type'):
#            doc_text += f"Тип: {metadata['content_type']}\n"
#        doc_text += f"Текст:\n{text}\n" + "-" * 40
        doc_text += f"{text}\n" + "-" * 40


        formatted.append(doc_text)

    return "\n\n".join(formatted)


def extract_value_from_response(response, query):
    """Извлекает значение из ответа LLM"""
    lines = [line.strip() for line in response.split('\n') if line.strip()]

    # Ищем строку с результатом
    for line in lines:
        if line.startswith("РЕЗУЛЬТАТ:"):
            return line.replace("РЕЗУЛЬТАТ:", "").strip()

    # Ищем строку с двоеточием
    for line in lines:
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()

    # Возвращаем последнюю строку
    return lines[-1] if lines else "Информация не найдена"


def calculate_confidence(response):
    """Рассчитывает уверенность в ответе"""
    uncertainty_phrases = [
        "возможно", "вероятно", "может быть", "предположительно",
        "не ясно", "не уверен", "не определено", "информация не найдена"
    ]

    confidence = 0.8
    response_lower = response.lower()

    for phrase in uncertainty_phrases:
        if phrase in response_lower:
            confidence -= 0.1

    return max(0.1, min(confidence, 1.0))


def check_if_cancelled(celery_task):
    """Проверяет, была ли задача отменена"""
    try:
        from celery import current_app as celery_app
        task_state = celery_app.AsyncResult(celery_task.request.id).state
        return task_state == 'REVOKED'
    except:
        return False


def handle_cancellation(application_id):
    """Обрабатывает отмену анализа"""
    application = Application.query.get(application_id)
    if not application:
        return {"status": "error", "message": "Заявка не найдена"}

    saved_count = ParameterResult.query.filter_by(application_id=application_id).count()

    if saved_count > 0:
        application.status = "analyzed"
        application.status_message = f"Анализ остановлен. Сохранено результатов: {saved_count}"
    else:
        application.status = "indexed"
        application.status_message = "Анализ остановлен пользователем"

    application.last_operation = 'analyzing'

    # ИЗМЕНЕНИЕ: При отмене также сохраняем время окончания
    if not application.analysis_completed_at:
        application.analysis_completed_at = datetime.utcnow()

    db.session.commit()

    logger.info(f"Анализ заявки {application_id} остановлен. Сохранено {saved_count} результатов")
    return {"status": "cancelled", "message": "Анализ остановлен пользователем"}