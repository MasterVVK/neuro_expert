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

                # Выполняем семантический поиск
                search_results = search(
                    application_id=application_id,
                    query=parameter.search_query,
                    limit=3
                )

                # Логируем результаты поиска
                logger.info(f"Результаты поиска для параметра {parameter.name}:")
                for i, doc in enumerate(search_results):
                    logger.info(f"Результат {i + 1}:")
                    if 'metadata' in doc:
                        logger.info(f"  Раздел: {doc['metadata'].get('section', 'Н/Д')}")
                        logger.info(f"  Тип: {doc['metadata'].get('content_type', 'Н/Д')}")

                    # Выводим полный текст для анализа
                    if 'text' in doc:
                        logger.info(f"  Полный текст:\n{doc['text']}")

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

                    db.session.add(result)
                    db.session.commit()

                    processed_count += 1
                    continue

                # Форматируем контекст для LLM
                context = _format_documents_for_context(search_results)

                # Логируем полный запрос к LLM
                full_prompt = parameter.llm_prompt_template.replace("{query}", parameter.search_query).replace(
                    "{context}", context)
                logger.info(f"Запрос к LLM для параметра {parameter.name}:")
                logger.info(f"Модель: {parameter.llm_model}")
                logger.info(f"Температура: {parameter.llm_temperature}")
                logger.info(f"Max tokens: {parameter.llm_max_tokens}")
                logger.info(f"Полный промпт:\n{full_prompt}")

                # Обрабатываем параметр через LLM
                llm_response = llm_provider.process_query(
                    model_name=parameter.llm_model,
                    prompt=parameter.llm_prompt_template,
                    context=context,
                    parameters={
                        'temperature': parameter.llm_temperature,
                        'max_tokens': parameter.llm_max_tokens
                    }
                )

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


def _format_documents_for_context(documents):
    """
    Форматирует документы для передачи в контекст LLM.

    Args:
        documents: Список документов

    Returns:
        str: Отформатированный контекст
    """
    formatted_docs = []

    for i, doc in enumerate(documents):
        formatted_doc = f"Документ {i + 1}:\n"

        if 'metadata' in doc:
            formatted_doc += f"Раздел: {doc['metadata'].get('section', 'Н/Д')}\n"
            formatted_doc += f"Тип: {doc['metadata'].get('content_type', 'Н/Д')}\n"

        formatted_doc += f"Текст:\n{doc.get('text', '')}\n"
        formatted_doc += "-" * 40 + "\n"

        formatted_docs.append(formatted_doc)

    context = "\n".join(formatted_docs)
    logger.info(f"Сформирован контекст длиной {len(context)} символов")

    return context


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

    # Сначала ищем формат "запрос: значение"
    lines = [line.strip() for line in response.split('\n') if line.strip()]
    logger.info(f"Обнаружено {len(lines)} строк в ответе")

    for i, line in enumerate(lines):
        logger.info(f"Строка {i + 1}: {line}")
        # Ищем строку с запросом и двоеточием
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                logger.info(f"Найдено значение в формате 'запрос: значение' - {parts[1].strip()}")
                return parts[1].strip()

    # Если не удалось найти формат "запрос: значение", пробуем найти строки, содержащие ключевые слова из запроса
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