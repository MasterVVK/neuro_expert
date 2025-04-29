import logging
from app import db
from app.models import Application, ChecklistParameter, ParameterResult
from app.adapters.llm_adapter import OllamaLLMProvider
from app.services.vector_service import search
from app.utils import format_documents_for_context, extract_value_from_response, calculate_confidence
from flask import current_app

logger = logging.getLogger(__name__)


def get_llm_provider():
    """Создает и возвращает провайдер LLM"""
    return OllamaLLMProvider(
        base_url=current_app.config['OLLAMA_URL']
    )


def analyze_application(application_id, progress_callback=None, skip_status_check=False):
    """
    Анализирует заявку по чек-листам.

    Args:
        application_id: ID заявки
        progress_callback: Функция обратного вызова для обновления прогресса
        skip_status_check: Пропустить проверку статуса (для Celery задачи)

    Returns:
        dict: Результат анализа
    """
    logger.info(f"Анализ заявки {application_id}")

    # Получаем данные из БД
    application = Application.query.get(application_id)
    if not application:
        error_msg = f"Заявка с ID {application_id} не найдена"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Проверяем, что заявка готова к анализу (если проверка не пропущена)
    if not skip_status_check and application.status not in ["indexed", "analyzed"]:
        error_msg = f"Заявка в статусе {application.status} не может быть проанализирована"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Проверяем наличие чек-листов
    if not application.checklists:
        error_msg = "Для заявки не назначен ни один чек-лист"
        logger.error(error_msg)
        raise ValueError(error_msg)

    try:
        # Обновляем статус заявки (если он не 'analyzing' и проверка не пропущена)
        if not skip_status_check:
            application.status = "analyzing"
            db.session.commit()

        # Обновляем прогресс
        if progress_callback:
            progress_callback(10, 'prepare', 'Инициализация анализа...')

        # Получаем провайдер LLM
        llm_provider = get_llm_provider()

        # Обрабатываем каждый параметр
        processed_count = 0
        error_count = 0

        # Соберем все параметры из всех чек-листов
        parameters = []
        for checklist in application.checklists:
            parameters.extend(checklist.parameters.all())

        total_parameters = len(parameters)
        logger.info(f"Всего параметров для анализа: {total_parameters}")

        # Обновляем прогресс перед началом обработки параметров
        if progress_callback:
            progress_callback(15, 'analyze', f'Начало анализа {total_parameters} параметров...')

        # Получаем настройки умного поиска из конфигурации приложения
        use_smart_search = True  # Включаем умный поиск
        hybrid_threshold = 10    # Порог длины запроса для выбора метода поиска

        for i, parameter in enumerate(parameters):
            try:
                # Обновляем прогресс для текущего параметра
                if progress_callback:
                    progress = 15 + int(75 * (i / total_parameters))
                    progress_callback(progress, 'analyze',
                                      f'Анализ параметра {i + 1}/{total_parameters}: {parameter.name}')

                logger.info(f"Обработка параметра {parameter.id}: {parameter.name}")
                logger.info(f"Поисковый запрос: {parameter.search_query}")
                logger.info(
                    f"Ререйтинг: {parameter.use_reranker}, Лимит: {parameter.search_limit}, Лимит ререйтинга: {parameter.rerank_limit}")

                # Определяем метод поиска на основе длины запроса
                query = parameter.search_query
                if len(query) < hybrid_threshold:
                    logger.info(f"Используем гибридный поиск для запроса '{query}' (<{hybrid_threshold} символов)")
                    search_method = "hybrid"
                else:
                    logger.info(f"Используем векторный поиск для запроса '{query}' (>={hybrid_threshold} символов)")
                    search_method = "vector"

                # Выполняем поиск с нужными параметрами
                search_results = search(
                    application_id=application_id,
                    query=parameter.search_query,
                    limit=parameter.search_limit,
                    use_reranker=parameter.use_reranker,
                    rerank_limit=parameter.rerank_limit,
                    use_smart_search=True,  # Всегда используем умный поиск
                    hybrid_threshold=hybrid_threshold  # Порог в 10 символов
                )

                # Логируем результаты поиска
                logger.info(f"Результаты поиска для параметра {parameter.name}:")
                for j, doc in enumerate(search_results):
                    logger.info(f"Результат {j + 1}:")
                    if 'metadata' in doc:
                        logger.info(f"  Раздел: {doc['metadata'].get('section', 'Н/Д')}")
                        logger.info(f"  Тип: {doc['metadata'].get('content_type', 'Н/Д')}")
                        if parameter.use_reranker and 'rerank_score' in doc:
                            logger.info(f"  Оценка ререйтинга: {doc.get('rerank_score', 0.0)}")
                        logger.info(f"  Оценка векторная: {doc.get('score', 0.0)}")

                # Если не найдено результатов, создаем запись об этом
                if not search_results:
                    logger.warning(f"По запросу '{parameter.search_query}' не найдено результатов")

                    # Создаем или обновляем результат
                    result = ParameterResult.query.filter_by(
                        application_id=application_id,
                        parameter_id=parameter.id
                    ).first() or ParameterResult(
                        application_id=application_id,
                        parameter_id=parameter.id
                    )

                    result.value = "Информация не найдена"
                    result.confidence = 0.0
                    result.search_results = []
                    result.llm_request = {
                        'prompt_template': parameter.llm_prompt_template,
                        'query': parameter.search_query,
                        'context': '',
                        'model': parameter.llm_model,
                        'temperature': parameter.llm_temperature,
                        'max_tokens': parameter.llm_max_tokens,
                        'error': 'Не найдено результатов поиска',
                        'search_method': search_method
                    }

                    db.session.add(result)
                    db.session.commit()

                    processed_count += 1
                    continue

                # Форматируем контекст для LLM
                context = format_documents_for_context(search_results, include_metadata=False)

                # Создаем полный запрос к LLM
                full_prompt = parameter.llm_prompt_template.replace("{query}", parameter.search_query).replace(
                    "{context}", context)

                # Получаем context_length для модели
                try:
                    model_context_length = llm_provider.get_context_length(parameter.llm_model)
                    logger.info(f"Получен context_length для модели {parameter.llm_model}: {model_context_length}")
                except Exception as e:
                    logger.warning(f"Не удалось получить context_length для модели {parameter.llm_model}: {str(e)}")
                    model_context_length = None

                # Сохраняем запрос для последующего отображения
                llm_request = {
                    'prompt_template': parameter.llm_prompt_template,
                    'query': parameter.search_query,
                    'context': context,
                    'full_prompt': full_prompt,
                    'model': parameter.llm_model,
                    'temperature': parameter.llm_temperature,
                    'max_tokens': parameter.llm_max_tokens,
                    'search_method': search_method  # Добавляем информацию о методе поиска
                }

                # Добавляем context_length, если он был получен
                if model_context_length:
                    llm_request['context_length'] = model_context_length

                # Логируем полный запрос к LLM
                logger.info(f"Запрос к LLM для параметра {parameter.name}:")
                logger.info(f"Модель: {parameter.llm_model}")
                logger.info(f"Температура: {parameter.llm_temperature}")
                logger.info(f"Max tokens: {parameter.llm_max_tokens}")
                logger.info(f"Метод поиска: {search_method}")
                if model_context_length:
                    logger.info(f"Context length: {model_context_length}")

                # Обрабатываем параметр через LLM
                llm_parameters = {
                    'temperature': parameter.llm_temperature,
                    'max_tokens': parameter.llm_max_tokens,
                    'search_query': parameter.search_query
                }

                # Добавляем context_length, если он был получен
                if model_context_length:
                    llm_parameters['context_length'] = model_context_length

                llm_response = llm_provider.process_query(
                    model_name=parameter.llm_model,
                    prompt=parameter.llm_prompt_template,
                    context=context,
                    parameters=llm_parameters,
                    query=parameter.search_query
                )

                # Добавляем ответ LLM в запрос
                llm_request['response'] = llm_response

                # Логируем ответ от LLM
                logger.info(f"Ответ от LLM для параметра {parameter.name}:")
                logger.info(f"Raw response: {llm_response}")

                # Анализируем ответ
                value = extract_value_from_response(llm_response, parameter.search_query)
                confidence = calculate_confidence(llm_response)

                logger.info(f"Извлеченное значение: {value}")
                logger.info(f"Уверенность: {confidence}")

                # Создаем или обновляем результат
                result = ParameterResult.query.filter_by(
                    application_id=application_id,
                    parameter_id=parameter.id
                ).first() or ParameterResult(
                    application_id=application_id,
                    parameter_id=parameter.id
                )

                result.value = value
                result.confidence = confidence
                result.search_results = search_results
                result.llm_request = llm_request

                db.session.add(result)
                db.session.commit()

                processed_count += 1
                logger.info(f"Обработан параметр {parameter.id}: {parameter.name}")

                # Обновляем прогресс после обработки параметра
                if progress_callback:
                    progress = 15 + int(75 * ((i + 1) / total_parameters))
                    progress_callback(progress, 'analyze',
                                      f'Проанализировано {i + 1}/{total_parameters} параметров')

            except Exception as e:
                logger.exception(f"Ошибка при обработке параметра {parameter.id}: {str(e)}")
                error_count += 1

                # Обновляем прогресс с информацией об ошибке
                if progress_callback:
                    progress = 15 + int(75 * ((i + 1) / total_parameters))
                    progress_callback(progress, 'analyze',
                                      f'Ошибка при анализе параметра {parameter.name}: {str(e)}')

        # Обновляем прогресс перед завершением
        if progress_callback:
            progress_callback(95, 'complete', 'Завершение анализа...')

        # Обновляем статус заявки
        if error_count == 0:
            application.status = "analyzed"
            logger.info(f"Анализ для заявки {application_id} успешно завершен")
        else:
            application.status = "analysis_partial"
            application.status_message = f"Ошибки при обработке {error_count} параметров"
            logger.warning(
                f"Анализ для заявки {application_id} завершен с ошибками: {error_count} из {len(parameters)}")

        db.session.commit()

        # Финальное обновление прогресса
        if progress_callback:
            progress_callback(100, 'complete', 'Анализ успешно завершен')

        return {
            "status": "success",
            "processed": processed_count,
            "errors": error_count,
            "total": len(parameters)
        }

    except Exception as e:
        logger.exception(f"Ошибка при анализе заявки: {str(e)}")

        # Обновляем статус заявки
        application.status = "error"
        application.status_message = str(e)
        db.session.commit()

        # Обновляем прогресс с информацией об ошибке
        if progress_callback:
            progress_callback(0, 'error', f'Ошибка анализа: {str(e)}')

        raise