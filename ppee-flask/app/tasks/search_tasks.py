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
                         rerank_limit=None, use_llm=False, llm_params=None,
                         use_smart_search=False, vector_weight=0.5, text_weight=0.5,
                         hybrid_threshold=10):
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
        use_smart_search: Использовать ли умный выбор метода поиска
        vector_weight: Вес векторного поиска (для гибридного)
        text_weight: Вес текстового поиска (для гибридного)
        hybrid_threshold: Порог длины запроса для гибридного поиска

    Returns:
        dict: Результаты поиска
    """
    logger.info(f"Запуск задачи поиска: запрос='{query_text}', заявка={application_id}, " +
                f"ререйтинг={use_reranker}, использование LLM={use_llm}, " +
                f"умный поиск={use_smart_search}, вес вектора={vector_weight}, " +
                f"вес текста={text_weight}, порог={hybrid_threshold}")

    start_time = time.time()

    # Обновляем статус - начинаем поиск
    search_type = "smart_search" if use_smart_search else "vector_search"
    BaseTask.update_progress(self, 30, search_type, 'Выполнение поиска...')

    # Выполняем поиск
    search_start_time = time.time()

    # Определяем метод поиска и обновляем соответствующий статус
    search_method = "vector"  # Значение по умолчанию

    if use_smart_search:
        # Для коротких запросов - гибридный поиск
        if len(query_text) < hybrid_threshold:
            BaseTask.update_progress(self, 40, 'hybrid_search', 'Выполнение гибридного поиска...')
            search_method = "hybrid"
        else:
            BaseTask.update_progress(self, 40, 'vector_search', 'Выполнение векторного поиска...')
            search_method = "vector"
    else:
        BaseTask.update_progress(self, 40, 'vector_search', 'Выполнение векторного поиска...')
        search_method = "vector"

    # Выполняем поиск с учетом заданных параметров и повторными попытками при необходимости
    try:
        # Получаем минимальный порог VRAM из конфигурации
        min_vram_mb = current_app.config.get('MIN_VRAM_MB', 500)

        # Максимальное количество попыток поиска
        max_retries = 2
        results = None

        for attempt in range(max_retries):
            try:
                # Увеличиваем минимальный порог VRAM с каждой попыткой
                attempt_min_vram = min_vram_mb + (attempt * 200)  # 500, 700, ...

                logger.info(f"Попытка {attempt+1}/{max_retries} с порогом VRAM {attempt_min_vram} МБ")

                # Выполняем поиск с текущим порогом VRAM
                results = search(
                    application_id=application_id,
                    query=query_text,
                    limit=limit,
                    use_reranker=use_reranker,
                    rerank_limit=rerank_limit,
                    use_smart_search=use_smart_search,
                    vector_weight=vector_weight,
                    text_weight=text_weight,
                    hybrid_threshold=hybrid_threshold,
                    min_vram_mb=attempt_min_vram
                )

                # Если получили результаты, выходим из цикла
                if results is not None:
                    logger.info(f"Поиск успешно выполнен на попытке {attempt+1}")
                    break

            except Exception as attempt_error:
                logger.warning(f"Попытка {attempt+1}/{max_retries} не удалась: {str(attempt_error)}")

                # Если это последняя попытка, сохраняем ошибку для логирования
                if attempt == max_retries - 1:
                    logger.error(f"Все попытки поиска завершились неудачно")
                else:
                    # Иначе логируем и пробуем еще раз с повышенным порогом VRAM
                    logger.warning(f"Пробуем еще раз с более высоким порогом VRAM...")
                    time.sleep(1)  # Добавляем небольшую задержку перед повторной попыткой

        # Если после всех попыток результаты не получены, создаем пустой список
        if results is None:
            logger.error(f"Не удалось получить результаты поиска после {max_retries} попыток")
            results = []

    except Exception as e:
        logger.error(f"Критическая ошибка при выполнении поиска: {str(e)}")
        results = []

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
            'score': round(float(result.get('score', 0.0)), 4),
            'search_type': result.get('search_type', search_method)
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
        'use_smart_search': use_smart_search,
        'search_method': search_method,  # Добавляем информацию о методе поиска
        'use_llm': use_llm,
        'execution_time': round(total_time, 2),
        'results': formatted_results,
        'llm_result': llm_result
    }