"""
Задачи Celery для выполнения семантического поиска и ререйтинга.
"""

import time
import logging
from app import celery
from app.adapters.qdrant_adapter import QdrantAdapter
from app.adapters.llm_adapter import OllamaLLMProvider
from app.utils.formatting import format_documents_for_context
from flask import current_app

logger = logging.getLogger(__name__)


@celery.task(bind=True)
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

    # Начальное состояние
    self.update_state(state='PROGRESS',
                      meta={'progress': 5,
                            'status': 'starting',
                            'message': 'Инициализация поиска...'})

    qdrant_adapter = None
    start_time = time.time()

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

        # Выполняем поиск
        search_start_time = time.time()

        # Для ререйтинга нужно получить больше первичных результатов
        if rerank_limit is None and use_reranker:
            rerank_limit = limit * 4  # Получаем в 4 раза больше результатов для ререйтинга

        results = qdrant_adapter.search(
            application_id=application_id,
            query=query_text,
            limit=limit if not use_reranker else rerank_limit,
            rerank_limit=rerank_limit
        )

        # Если включен ререйтинг, обновляем статус
        if use_reranker:
            self.update_state(state='PROGRESS',
                              meta={'progress': 60,
                                    'status': 'reranking',
                                    'message': 'Выполнение ререйтинга...'})

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
            self.update_state(state='PROGRESS',
                              meta={'progress': 75,
                                    'status': 'llm_processing',
                                    'message': 'Обработка результатов через LLM...'})

            llm_start_time = time.time()

            try:
                # Инициализируем LLM провайдер
                llm_provider = OllamaLLMProvider(base_url="http://localhost:11434")

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
                value = _extract_value_from_response(llm_response, query_text)
                confidence = _calculate_confidence(llm_response)

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

    except Exception as e:
        logger.exception(f"Ошибка при выполнении поиска: {str(e)}")

        # Освобождаем ресурсы в случае ошибки
        if qdrant_adapter and hasattr(qdrant_adapter, 'use_reranker') and qdrant_adapter.use_reranker:
            try:
                qdrant_adapter.cleanup()
            except:
                pass

        return {
            'status': 'error',
            'message': str(e)
        }



def _extract_value_from_response(response: str, query: str) -> str:
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


def _calculate_confidence(response: str) -> float:
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