"""
Задачи Celery для выполнения семантического поиска и ререйтинга.
"""

import time
import logging
from app import celery
from app.adapters.qdrant_adapter import QdrantAdapter
from flask import current_app

logger = logging.getLogger(__name__)


@celery.task(bind=True)
def semantic_search_task(self, application_id, query_text, limit=5, use_reranker=False):
    """
    Асинхронная задача для выполнения семантического поиска с ререйтингом.

    Args:
        application_id: ID заявки
        query_text: Текст запроса
        limit: Максимальное количество результатов
        use_reranker: Использовать ли ререйтинг

    Returns:
        dict: Результаты поиска
    """
    logger.info(f"Запуск задачи поиска: запрос='{query_text}', заявка={application_id}, ререйтинг={use_reranker}")

    # Начальное состояние
    self.update_state(state='PROGRESS',
                      meta={'progress': 5,
                            'status': 'starting',
                            'message': 'Инициализация поиска...'})

    qdrant_adapter = None
    try:
        # Инициализируем QdrantAdapter с поддержкой ререйтинга
        self.update_state(state='PROGRESS',
                          meta={'progress': 10,
                                'status': 'initializing',
                                'message': 'Инициализация адаптера Qdrant...'})

        # Получаем настройки из конфигурации
        qdrant_adapter = QdrantAdapter(
            host="localhost",
            port=6333,
            collection_name="ppee_applications",
            embeddings_type='ollama',
            model_name='bge-m3',
            ollama_url="http://localhost:11434",
            use_reranker=use_reranker,
            reranker_model='BAAI/bge-reranker-v2-m3'
        )

        # Обновляем статус - начинаем векторный поиск
        self.update_state(state='PROGRESS',
                          meta={'progress': 30,
                                'status': 'vector_search',
                                'message': 'Выполнение векторного поиска...'})

        # Для ререйтинга нужно получить больше первичных результатов
        rerank_limit = limit * 4 if use_reranker else None

        # Выполняем поиск
        start_time = time.time()

        results = qdrant_adapter.search(
            application_id=application_id,
            query=query_text,
            limit=limit,
            rerank_limit=rerank_limit
        )

        # Если включен ререйтинг, обновляем статус
        if use_reranker:
            self.update_state(state='PROGRESS',
                              meta={'progress': 60,
                                    'status': 'reranking',
                                    'message': 'Выполнение ререйтинга...'})

        # Общее время выполнения
        execution_time = time.time() - start_time
        logger.info(f"Поиск выполнен за {execution_time:.2f} сек., найдено {len(results)} результатов")

        # Форматируем результаты для возврата
        formatted_results = []
        for i, result in enumerate(results):
            formatted_result = {
                'position': i + 1,
                'text': result.get('text', ''),
                'section': result.get('metadata', {}).get('section', 'Неизвестно'),
                'content_type': result.get('metadata', {}).get('content_type', 'Неизвестно'),
                'score': round(float(result.get('score', 0.0)), 4)
            }

            # Добавляем оценку ререйтинга, если она есть
            if use_reranker and 'rerank_score' in result:
                formatted_result['rerank_score'] = round(float(result.get('rerank_score', 0.0)), 4)

            formatted_results.append(formatted_result)

        # Обновляем статус - завершение
        self.update_state(state='PROGRESS',
                          meta={'progress': 90,
                                'status': 'finishing',
                                'message': 'Завершение поиска...'})

        # Освобождаем ресурсы
        if qdrant_adapter and qdrant_adapter.use_reranker:
            try:
                qdrant_adapter.cleanup()
                logger.info("Ресурсы ререйтинга освобождены")
            except Exception as cleanup_error:
                logger.error(f"Ошибка при освобождении ресурсов: {str(cleanup_error)}")

        # Возвращаем результаты
        return {
            'status': 'success',
            'count': len(formatted_results),
            'use_reranker': use_reranker,
            'execution_time': round(execution_time, 2),
            'results': formatted_results
        }

    except Exception as e:
        logger.exception(f"Ошибка при выполнении поиска: {str(e)}")

        # Освобождаем ресурсы в случае ошибки
        if qdrant_adapter and qdrant_adapter.use_reranker:
            try:
                qdrant_adapter.cleanup()
            except:
                pass

        return {
            'status': 'error',
            'message': str(e)
        }