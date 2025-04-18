import logging
import os
from app import db
from app.models import Application, File
from app.adapters.qdrant_adapter import QdrantAdapter
from flask import current_app

logger = logging.getLogger(__name__)


def get_qdrant_adapter(use_reranker=False):
    """
    Создает и возвращает адаптер для Qdrant

    Args:
        use_reranker: Использовать ли ререйтинг

    Returns:
        QdrantAdapter: Адаптер для Qdrant
    """
    return QdrantAdapter(
        host=current_app.config['QDRANT_HOST'],
        port=current_app.config['QDRANT_PORT'],
        collection_name=current_app.config['QDRANT_COLLECTION'],
        embeddings_type='ollama',  # Можно сделать настраиваемым через конфигурацию
        model_name='bge-m3',  # Можно сделать настраиваемым через конфигурацию
        ollama_url=current_app.config['OLLAMA_URL'],
        use_reranker=use_reranker,
        reranker_model='BAAI/bge-reranker-v2-m3'
    )


def index_document(application_id, file_id, progress_callback=None):
    """
    Индексирует документ в векторной базе данных.

    Args:
        application_id: ID заявки
        file_id: ID файла
        progress_callback: Функция обратного вызова для обновления прогресса

    Returns:
        dict: Результат индексации
    """
    logger.info(f"Индексация документа для заявки {application_id}, файл {file_id}")

    # Получаем данные из БД
    file = File.query.get(file_id)
    if not file:
        error_msg = f"Файл с ID {file_id} не найден"
        logger.error(error_msg)
        raise ValueError(error_msg)

    application = Application.query.get(application_id)
    if not application:
        error_msg = f"Заявка с ID {application_id} не найдена"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Проверяем существование файла
    if not os.path.exists(file.file_path):
        error_msg = f"Файл не найден по пути: {file.file_path}"
        logger.error(error_msg)
        # Обновляем статус заявки
        application.status = "error"
        application.status_message = f"Файл не найден: {file.original_filename}"
        db.session.commit()
        raise FileNotFoundError(error_msg)

    # Обновляем статус
    if progress_callback:
        progress_callback(10, 'prepare', 'Проверка файла...')

    logger.info(f"Файл найден: {file.file_path} (размер: {os.path.getsize(file.file_path)} байт)")

    try:
        # Получаем адаптер Qdrant
        qdrant_adapter = get_qdrant_adapter()

        # Проверяем расширение файла
        _, ext = os.path.splitext(file.file_path)
        logger.info(f"Тип файла: {ext.lower()}")

        # Обновляем статус
        if progress_callback:
            progress_callback(15, 'convert', 'Конвертация документа...')

        # Индексируем документ с отслеживанием прогресса
        result = qdrant_adapter.index_document_with_progress(
            application_id=str(application_id),
            document_path=file.file_path,
            delete_existing=True,
            progress_callback=progress_callback
        )

        # Обновляем статус заявки на основе результата
        if result["status"] == "success":
            application.status = "indexed"
            logger.info(f"Индексация для заявки {application_id} успешно завершена")
        else:
            application.status = "error"
            application.status_message = result.get("error", "Неизвестная ошибка")
            logger.error(f"Ошибка при индексации заявки {application_id}: {result.get('error', 'Неизвестная ошибка')}")

        db.session.commit()
        return result

    except Exception as e:
        logger.exception(f"Ошибка при индексации документа: {str(e)}")

        # Обновляем статус заявки
        application.status = "error"
        application.status_message = str(e)
        db.session.commit()

        raise


def search(application_id, query, limit=5, use_reranker=False, rerank_limit=None):
    """
    Выполняет семантический поиск.

    Args:
        application_id: ID заявки
        query: Поисковый запрос
        limit: Максимальное количество результатов
        use_reranker: Использовать ли ререйтинг
        rerank_limit: Количество документов для ререйтинга

    Returns:
        list: Результаты поиска
    """
    logger.info(f"Выполнение поиска '{query}' для заявки {application_id} (ререйтинг: {use_reranker})")

    try:
        # Получаем адаптер Qdrant
        qdrant_adapter = get_qdrant_adapter(use_reranker=use_reranker)

        # Выполняем поиск
        results = qdrant_adapter.search(
            application_id=str(application_id),
            query=query,
            limit=limit,
            rerank_limit=rerank_limit
        )

        # Освобождаем ресурсы, если использовался ререйтинг
        if use_reranker:
            try:
                qdrant_adapter.cleanup()
            except Exception as e:
                logger.warning(f"Ошибка при освобождении ресурсов ререйтинга: {str(e)}")

        return results

    except Exception as e:
        logger.exception(f"Ошибка при выполнении поиска: {str(e)}")
        # Освобождаем ресурсы в случае ошибки
        if 'qdrant_adapter' in locals() and qdrant_adapter.use_reranker:
            try:
                qdrant_adapter.cleanup()
            except:
                pass
        raise


def delete_application_data(application_id):
    """
    Удаляет данные заявки из векторной базы данных.

    Args:
        application_id: ID заявки

    Returns:
        bool: Успешность операции
    """
    logger.info(f"Удаление данных заявки {application_id} из векторной базы данных")

    try:
        # Получаем адаптер Qdrant
        qdrant_adapter = get_qdrant_adapter()

        # Удаляем данные
        success = qdrant_adapter.delete_application_data(str(application_id))

        return success

    except Exception as e:
        logger.exception(f"Ошибка при удалении данных заявки: {str(e)}")
        raise