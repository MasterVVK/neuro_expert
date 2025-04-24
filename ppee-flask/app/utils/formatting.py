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