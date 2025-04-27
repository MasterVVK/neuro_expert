"""
Задачи Celery для выполнения семантического поиска и ререйтинга.
"""

import time
import logging
from app import celery
from app.adapters.llm_adapter import OllamaLLMProvider
from app.utils import format_documents_for_context, extract_value_from_response, calculate_confidence
from app.services.vector_service import search
from app.tasks.base_task import BaseTask
from flask import current_app

# Настройка логирования
logger = logging.getLogger(__name__)


@celery.task(bind=True)
@BaseTask.task_wrapper
def semantic_search_task(self, application_id, query_text, limit=5, use_reranker=False,
                         rerank_limit=None, use_llm=False, llm_params=None):
    """
    Асинхронная задача для выполнения семантического поиска с ререйтингом и обработкой LLM.

    Args:
        application_id: ID заявки
        query_text: Текст запроса
        limit: Максимальное количество результатов
        use_reranker: Использовать ли ререйтинг
        rerank_limit: Количество документов для ререйтинга
        use_llm: Использовать ли LLM для обработки результатов
        llm_params: Параметры для LLM

    Returns:
        dict: Результаты поиска
    """
    logger.info(f"Запуск задачи поиска: запрос='{query_text}', заявка={application_id}, " +
                f"ререйтинг={use_reranker}, использование LLM={use_llm}")

    start_time = time.time()

    # Обновляем статус - начинаем векторный поиск
    BaseTask.update_progress(self, 30, 'vector_search', 'Выполнение векторного поиска...')

    # Выполняем поиск
    search_start_time = time.time()

    results = search(
        application_id=application_id,
        query=query_text,
        limit=limit,
        use_reranker=use_reranker,
        rerank_limit=rerank_limit
    )

    # Если включен ререйтинг, обновляем статус
    if use_reranker:
        BaseTask.update_progress(self, 60, 'reranking', 'Выполнение ререйтинга...')

    # Время выполнения поиска
    search_time = time.time() - search_start_time
    logger.info(f"Поиск выполнен за {search_time:.2f} сек., найдено {len(results)} результатов")

    # Форматируем результаты
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

    # Обработка результатов через LLM, если требуется
    llm_result = None
    if use_llm and llm_params and formatted_results:
        BaseTask.update_progress(self, 75, 'llm_processing', 'Обработка результатов через LLM...')

        llm_start_time = time.time()

        try:
            # Инициализируем LLM провайдер
            llm_provider = OllamaLLMProvider(base_url=current_app.config['OLLAMA_URL'])

            # Форматируем результаты для контекста LLM
            context = format_documents_for_context(formatted_results, include_metadata=True)

            # Выполняем обработку через LLM
            llm_response = llm_provider.process_query(
                model_name=llm_params.get('model_name', 'gemma3:27b'),
                prompt=llm_params.get('prompt_template', ''),
                context=context,
                parameters={
                    'temperature': llm_params.get('temperature', 0.1),
                    'max_tokens': llm_params.get('max_tokens', 1000),
                    'search_query': query_text
                },
                query=query_text
            )

            # Анализируем ответ
            value = extract_value_from_response(llm_response, query_text)
            confidence = calculate_confidence(llm_response)

            llm_result = {
                'value': value,
                'confidence': confidence,
                'raw_response': llm_response
            }

            llm_time = time.time() - llm_start_time
            logger.info(f"Обработка через LLM выполнена за {llm_time:.2f} сек.")
            logger.info(f"Результат LLM: {value} (уверенность: {confidence:.2f})")

        except Exception as llm_error:
            logger.error(f"Ошибка при обработке через LLM: {str(llm_error)}")
            llm_result = {
                'value': f"Ошибка обработки: {str(llm_error)}",
                'confidence': 0.0,
                'error': str(llm_error)
            }

    # Общее время выполнения
    total_time = time.time() - start_time

    # Возвращаем результаты
    return {
        'status': 'success',
        'count': len(formatted_results),
        'use_reranker': use_reranker,
        'use_llm': use_llm,
        'execution_time': round(total_time, 2),
        'results': formatted_results,
        'llm_result': llm_result
    }