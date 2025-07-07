"""
Утилиты для работы с чанками
"""
import logging

logger = logging.getLogger(__name__)


def calculate_chunks_total_size(search_results):
    """
    Вычисляет общий размер чанков в символах

    Args:
        search_results: Список результатов поиска (чанков)

    Returns:
        int: Общий размер в символах
    """
    if not search_results:
        return 0

    total_size = 0

    for chunk in search_results:
        try:
            # Обрабатываем разные варианты структуры данных
            if isinstance(chunk, dict):
                # Сначала пробуем получить content_length из метаданных
                metadata = chunk.get('metadata', {})
                if metadata and isinstance(metadata, dict):
                    content_length = metadata.get('content_length')
                    if content_length is not None:
                        try:
                            total_size += int(content_length)
                            continue
                        except (ValueError, TypeError):
                            logger.warning(f"Некорректное значение content_length: {content_length}")

                # Если нет content_length, используем длину текста
                text = chunk.get('text', '')
                if text:
                    total_size += len(text)
            else:
                # Если chunk - это объект, пробуем через атрибуты
                # Пробуем получить metadata как атрибут
                if hasattr(chunk, 'metadata'):
                    metadata = chunk.metadata
                    if hasattr(metadata, 'content_length') and metadata.content_length is not None:
                        try:
                            total_size += int(metadata.content_length)
                            continue
                        except (ValueError, TypeError):
                            logger.warning(f"Некорректное значение content_length: {metadata.content_length}")
                    elif isinstance(metadata, dict) and 'content_length' in metadata:
                        try:
                            total_size += int(metadata['content_length'])
                            continue
                        except (ValueError, TypeError):
                            logger.warning(f"Некорректное значение content_length: {metadata['content_length']}")

                # Если нет content_length, используем текст
                if hasattr(chunk, 'text') and chunk.text:
                    total_size += len(chunk.text)

        except Exception as e:
            logger.error(f"Ошибка при подсчете размера чанка: {e}")
            # Пробуем получить хотя бы длину текста
            try:
                if isinstance(chunk, dict) and 'text' in chunk:
                    total_size += len(chunk['text'])
                elif hasattr(chunk, 'text'):
                    total_size += len(chunk.text)
            except:
                pass

    return total_size


def get_chunk_metadata(chunk):
    """
    Извлекает метаданные из чанка

    Args:
        chunk: Чанк (словарь или объект)

    Returns:
        dict: Метаданные чанка
    """
    if isinstance(chunk, dict):
        return chunk.get('metadata', {})
    elif hasattr(chunk, 'metadata'):
        if isinstance(chunk.metadata, dict):
            return chunk.metadata
        else:
            # Если metadata - это объект, преобразуем в словарь
            return {
                'content_length': getattr(chunk.metadata, 'content_length', None),
                'document_id': getattr(chunk.metadata, 'document_id', None),
                'page_number': getattr(chunk.metadata, 'page_number', None),
                'section': getattr(chunk.metadata, 'section', None),
                'content_type': getattr(chunk.metadata, 'content_type', None),
            }
    return {}


def get_chunk_text(chunk):
    """
    Извлекает текст из чанка

    Args:
        chunk: Чанк (словарь или объект)

    Returns:
        str: Текст чанка
    """
    if isinstance(chunk, dict):
        return chunk.get('text', '')
    elif hasattr(chunk, 'text'):
        return chunk.text
    return ''