import logging
from app import db
from app.models import Application, ChecklistParameter, ParameterResult
from app.adapters.llm_adapter import OllamaLLMProvider
from app.services.vector_service import search
from flask import current_app

logger = logging.getLogger(__name__)


def get_llm_provider():
    """Создает и возвращает провайдер LLM"""
    return OllamaLLMProvider(
        base_url=current_app.config['OLLAMA_URL']
    )


def analyze_application(application_id):
    """
    Анализирует заявку по чек-листам.

    Args:
        application_id: ID заявки

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

    # Проверяем, что заявка готова к анализу
    if application.status not in ["indexed", "analyzed"]:
        error_msg = f"Заявка в статусе {application.status} не может быть проанализирована"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Проверяем наличие чек-листов
    if not application.checklists:
        error_msg = "Для заявки не назначен ни один чек-лист"
        logger.error(error_msg)
        raise ValueError(error_msg)

    try:
        # Обновляем статус заявки
        application.status = "analyzing"
        db.session.commit()

        # Получаем провайдер LLM
        llm_provider = get_llm_provider()

        # Обрабатываем каждый параметр
        processed_count = 0
        error_count = 0

        # Соберем все параметры из всех чек-листов
        parameters = []
        for checklist in application.checklists:
            parameters.extend(checklist.parameters.all())

        logger.info(f"Всего параметров для анализа: {len(parameters)}")

        for parameter in parameters:
            try:
                logger.info(f"Обработка параметра {parameter.id}: {parameter.name}")
                logger.info(f"Поисковый запрос: {parameter.search_query}")
                logger.info(
                    f"Ререйтинг: {parameter.use_reranker}, Лимит: {parameter.search_limit}, Лимит ререйтинга: {parameter.rerank_limit}")

                # Выполняем семантический поиск с учетом настроек параметра
                search_results = search(
                    application_id=application_id,
                    query=parameter.search_query,
                    limit=parameter.search_limit,
                    use_reranker=parameter.use_reranker,
                    rerank_limit=parameter.rerank_limit
                )

                # Логируем результаты поиска
                logger.info(f"Результаты поиска для параметра {parameter.name}:")
                for i, doc in enumerate(search_results):
                    logger.info(f"Результат {i + 1}:")
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
                        'error': 'Не найдено результатов поиска'
                    }

                    db.session.add(result)
                    db.session.commit()

                    processed_count += 1
                    continue

                # Форматируем контекст для LLM
                context = _format_documents_for_context(search_results)

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
                    'max_tokens': parameter.llm_max_tokens
                }

                # Добавляем context_length, если он был получен
                if model_context_length:
                    llm_request['context_length'] = model_context_length

                # Логируем полный запрос к LLM
                logger.info(f"Запрос к LLM для параметра {parameter.name}:")
                logger.info(f"Модель: {parameter.llm_model}")
                logger.info(f"Температура: {parameter.llm_temperature}")
                logger.info(f"Max tokens: {parameter.llm_max_tokens}")
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
                value = _extract_value_from_response(llm_response, parameter.search_query)
                confidence = _calculate_confidence(llm_response)

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

            except Exception as e:
                logger.exception(f"Ошибка при обработке параметра {parameter.id}: {str(e)}")
                error_count += 1

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

        raise


def _format_documents_for_context(documents, max_tokens=8192, include_metadata=False):
    """
    Форматирует документы для передачи в контекст LLM с учетом ограничения размера.

    Args:
        documents: Список документов
        max_tokens: Максимальный размер контекста в токенах
        include_metadata: Включать ли метаданные в форматирование (для поискового интерфейса)

    Returns:
        str: Отформатированный контекст
    """
    formatted_docs = []

    # Примерная оценка токенов: 1 токен ~ 4 символа
    approx_tokens_per_char = 0.25
    total_estimated_tokens = 0

    # Резервируем токены для промпта (инструкции и вопроса)
    reserved_tokens = 500
    available_tokens = max_tokens - reserved_tokens

    for i, doc in enumerate(documents):
        # Если мы уже приблизились к лимиту токенов, прекращаем добавление
        if total_estimated_tokens >= available_tokens:
            formatted_docs.append(
                "\nПримечание: Некоторые документы не были включены из-за ограничения размера контекста.")
            break

        formatted_doc = f"Документ {i + 1}:\n"

        # Добавляем информацию о документе только если include_metadata=True
        if include_metadata and 'metadata' in doc:
            metadata = doc.get('metadata', {})
            formatted_doc += f"Раздел: {metadata.get('section', 'Н/Д')}\n"
            formatted_doc += f"Тип: {metadata.get('content_type', 'Н/Д')}\n"

            # Добавляем информацию о ререйтинге, если доступна
            if 'rerank_score' in doc:
                formatted_doc += f"Оценка релевантности (ререйтинг): {doc.get('rerank_score', 0.0):.4f}\n"

            formatted_doc += f"Оценка релевантности: {doc.get('score', 0.0):.4f}\n"

        # Добавляем текст документа
        text = doc.get('text', '')

        # Оцениваем количество токенов в текущем документе
        doc_chars = len(formatted_doc) + len(text)
        doc_estimated_tokens = doc_chars * approx_tokens_per_char

        # Если текущий документ слишком большой, сокращаем его
        if doc_estimated_tokens > available_tokens - total_estimated_tokens:
            # Вычисляем, сколько символов мы можем добавить
            available_chars = int((available_tokens - total_estimated_tokens) / approx_tokens_per_char) - len(
                formatted_doc) - 50
            if available_chars > 100:  # Если осталось достаточно места
                text = text[:available_chars] + "... [сокращено]"
                formatted_doc += f"Текст:\n{text}\n"
                formatted_doc += "-" * 40 + "\n"
                formatted_docs.append(formatted_doc)

            # Добавляем предупреждение и прекращаем добавление
            formatted_docs.append("\nПримечание: Документы были сокращены из-за ограничения размера контекста.")
            break

        # Если include_metadata=True, добавляем слово "Текст:" перед содержимым
        if include_metadata:
            formatted_doc += f"Текст:\n{text}\n"
        else:
            formatted_doc += f"{text}\n"

        formatted_doc += "-" * 40 + "\n"

        total_estimated_tokens += doc_estimated_tokens
        formatted_docs.append(formatted_doc)

    return "\n".join(formatted_docs)


def _extract_value_from_response(response, query):
    """
    Извлекает значение из ответа LLM.

    Args:
        response: Ответ LLM
        query: Исходный поисковый запрос

    Returns:
        str: Извлеченное значение
    """
    logger.info("Извлечение значения из ответа LLM")

    # Сначала ищем формат "РЕЗУЛЬТАТ: значение"
    lines = [line.strip() for line in response.split('\n') if line.strip()]
    logger.info(f"Обнаружено {len(lines)} строк в ответе")

    for i, line in enumerate(lines):
        # Ищем строку с РЕЗУЛЬТАТ:
        if line.startswith("РЕЗУЛЬТАТ:"):
            value = line.replace("РЕЗУЛЬТАТ:", "").strip()
            logger.info(f"Найдено значение в формате 'РЕЗУЛЬТАТ: значение' - {value}")
            return value

    # Далее ищем формат "запрос: значение"
    for i, line in enumerate(lines):
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                # Проверяем, что это не строка с запросом
                if not parts[0].strip().lower() == "запрос":
                    logger.info(f"Найдено значение в формате 'запрос: значение' - {parts[1].strip()}")
                    return parts[1].strip()

    # Если не удалось найти по форматам, ищем строки, содержащие ключевые слова из запроса
    query_keywords = [word.lower() for word in query.split() if len(word) > 3]
    for line in lines:
        line_lower = line.lower()
        if any(keyword in line_lower for keyword in query_keywords) and ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                logger.info(f"Найдено значение по ключевым словам: {parts[1].strip()}")
                return parts[1].strip()

    # Если не удалось найти по ключевым словам, берем последнюю строку
    if lines:
        logger.info(f"Значение не найдено по ключевым словам, возвращаем последнюю строку: {lines[-1]}")
        return lines[-1]

    logger.info("Ответ не содержит строк, возвращаем сообщение об ошибке")
    return "Не удалось извлечь значение"


def _calculate_confidence(response):
    """
    Рассчитывает уровень уверенности в ответе.

    Args:
        response: Ответ LLM

    Returns:
        float: Уровень уверенности (от 0.0 до 1.0)
    """
    # Простая эвристика: если есть выражения неуверенности, понижаем оценку
    uncertainty_phrases = [
        "возможно", "вероятно", "может быть", "предположительно",
        "не ясно", "не уверен", "не определено", "информация не найдена"
    ]

    base_confidence = 0.8
    lowered_confidence = base_confidence

    for phrase in uncertainty_phrases:
        if phrase in response.lower():
            lowered_confidence -= 0.1
            logger.info(f"Обнаружена фраза неуверенности: '{phrase}', понижаем оценку")

    final_confidence = max(0.1, min(lowered_confidence, 1.0))  # Ограничиваем значением от 0.1 до 1.0
    logger.info(f"Итоговая оценка уверенности: {final_confidence}")

    return final_confidence