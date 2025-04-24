import logging

logger = logging.getLogger(__name__)


def format_documents_for_context(documents, max_tokens=8192, include_metadata=True):
    """
    Форматирует документы для передачи в контекст LLM с учетом ограничения размера.

    Args:
        documents: Список документов
        max_tokens: Максимальный размер контекста в токенах
        include_metadata: Включать ли метаданные в форматирование

    Returns:
        str: Отформатированный контекст
    """
    formatted_docs = []

    # Примерная оценка токенов: 1 токен ~ 4 символа
    approx_tokens_per_char = 0.25
    total_estimated_tokens = 0

    # Резервируем токены для промпта
    reserved_tokens = 500
    available_tokens = max_tokens - reserved_tokens

    for i, doc in enumerate(documents):
        # Если мы уже достигли лимита токенов
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

            if 'score' in doc:
                formatted_doc += f"Оценка релевантности: {doc.get('score', 0.0):.4f}\n"

        # Добавляем текст документа
        text = doc.get('text', '')

        # Оцениваем количество токенов
        doc_chars = len(formatted_doc) + len(text)
        doc_estimated_tokens = doc_chars * approx_tokens_per_char

        # Обрабатываем случай большого документа
        if doc_estimated_tokens > available_tokens - total_estimated_tokens:
            available_chars = int((available_tokens - total_estimated_tokens) / approx_tokens_per_char) - len(
                formatted_doc) - 50
            if available_chars > 100:
                text = text[:available_chars] + "... [сокращено]"
                if include_metadata:
                    formatted_doc += f"Текст:\n{text}\n"
                else:
                    formatted_doc += f"{text}\n"
                formatted_doc += "-" * 40 + "\n"
                formatted_docs.append(formatted_doc)

            formatted_docs.append("\nПримечание: Документы были сокращены из-за ограничения размера контекста.")
            break

        if include_metadata:
            formatted_doc += f"Текст:\n{text}\n"
        else:
            formatted_doc += f"{text}\n"

        formatted_doc += "-" * 40 + "\n"

        total_estimated_tokens += doc_estimated_tokens
        formatted_docs.append(formatted_doc)

    return "\n".join(formatted_docs)


def extract_value_from_response(response, query):
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


def calculate_confidence(response):
    """
    Рассчитывает уровень уверенности в ответе LLM.

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