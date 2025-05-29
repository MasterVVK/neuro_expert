from app import celery, create_app
import logging
import requests
import time
from celery.exceptions import Terminated, WorkerLostError

logger = logging.getLogger(__name__)

FASTAPI_URL = "http://localhost:8001"


@celery.task(bind=True)
def semantic_search_task(self, application_id, query_text, limit=5, use_reranker=False,
                         rerank_limit=None, use_llm=False, llm_params=None,
                         use_smart_search=False, vector_weight=0.5, text_weight=0.5,
                         hybrid_threshold=10, doc_names_mapping=None):
    """Асинхронная задача для семантического поиска через FastAPI с поддержкой отмены"""
    # Создаем контекст приложения для работы с БД
    app = create_app()

    with app.app_context():
        task_id = self.request.id
        start_time = time.time()

        try:
            # Функция для проверки, была ли задача отменена
            def check_if_cancelled():
                # Проверяем статус задачи
                result = celery.AsyncResult(task_id)
                if result.state == 'REVOKED':
                    raise Terminated("Задача была отменена пользователем")

            # Проверяем отмену перед началом
            check_if_cancelled()

            if use_reranker and rerank_limit == 9999:
                # Получаем статистику заявки через FastAPI
                try:
                    logger.info(f"Получение количества чанков для заявки {application_id}")
                    response = requests.get(f"{FASTAPI_URL}/applications/{application_id}/stats")
                    if response.status_code == 200:
                        stats = response.json()["stats"]
                        total_chunks = stats.get("total_points", 100)  # fallback на 100
                        rerank_limit = total_chunks
                        logger.info(f"Использование всех {total_chunks} чанков для ререйтинга в заявке {application_id}")
                    else:
                        # Если не удалось получить статистику, используем большое значение
                        rerank_limit = 1000
                        logger.warning(f"Не удалось получить количество чанков для заявки {application_id}, используем {rerank_limit}")
                except Exception as e:
                    logger.error(f"Ошибка при получении статистики заявки: {e}")
                    rerank_limit = 1000  # fallback


            # Обновляем статус - начало
            self.update_state(state='PROGRESS', meta={
                'status': 'progress',
                'progress': 10,
                'stage': 'initializing',
                'message': 'Инициализация поиска...'
            })

            # Проверяем отмену после инициализации
            check_if_cancelled()

            # Определяем метод поиска
            search_method = 'vector'
            if use_smart_search and len(query_text) < hybrid_threshold:
                search_method = 'hybrid'
                self.update_state(state='PROGRESS', meta={
                    'status': 'progress',
                    'progress': 30,
                    'stage': 'hybrid_search',
                    'message': 'Выполнение гибридного поиска...'
                })
            else:
                self.update_state(state='PROGRESS', meta={
                    'status': 'progress',
                    'progress': 30,
                    'stage': 'vector_search',
                    'message': 'Выполнение векторного поиска...'
                })

            # Проверяем отмену перед вызовом FastAPI
            check_if_cancelled()

            # Вызываем FastAPI для поиска
            response = requests.post(f"{FASTAPI_URL}/search", json={
                "application_id": str(application_id),
                "query": query_text,
                "limit": limit,
                "use_reranker": use_reranker,
                "rerank_limit": rerank_limit,
                "use_smart_search": use_smart_search,
                "vector_weight": vector_weight,
                "text_weight": text_weight,
                "hybrid_threshold": hybrid_threshold
            })

            if response.status_code != 200:
                raise Exception(f"FastAPI search error: {response.text}")

            search_results = response.json()["results"]

            # Проверяем отмену после получения результатов
            check_if_cancelled()

            # Если используется ререйтинг
            if use_reranker:
                self.update_state(state='PROGRESS', meta={
                    'status': 'progress',
                    'progress': 50,
                    'stage': 'reranking',
                    'message': 'Применение ререйтинга...'
                })

            # Проверяем отмену перед обработкой LLM
            check_if_cancelled()

            # Обработка через LLM если нужно
            llm_result = None
            if use_llm and llm_params and search_results:
                self.update_state(state='PROGRESS', meta={
                    'status': 'progress',
                    'progress': 70,
                    'stage': 'llm_processing',
                    'message': 'Обработка результатов через LLM...'
                })

                # Форматируем контекст
                context = format_documents_for_context(search_results)

                # Проверяем отмену перед вызовом LLM
                check_if_cancelled()

                # Вызываем LLM через FastAPI
                llm_response = requests.post(f"{FASTAPI_URL}/llm/process", json={
                    "model_name": llm_params.get('model_name', 'gemma3:27b'),
                    "prompt": llm_params.get('prompt_template', ''),
                    "context": context,
                    "parameters": {
                        'temperature': llm_params.get('temperature', 0.1),
                        'max_tokens': llm_params.get('max_tokens', 1000),
                        'search_query': query_text
                    },
                    "query": query_text
                })

                if llm_response.status_code == 200:
                    llm_text = llm_response.json()["response"]
                    llm_result = {
                        'value': extract_value_from_response(llm_text, query_text),
                        'confidence': calculate_confidence(llm_text),
                        'raw_response': llm_text
                    }

            # Проверяем отмену перед форматированием результатов
            check_if_cancelled()

            # Получаем маппинг имен документов, если не передан
            doc_names_mapping = doc_names_mapping or {}

            # Форматируем результаты
            formatted_results = []
            for i, result in enumerate(search_results):
                doc_id = result.get('metadata', {}).get('document_id', '')
                formatted_result = {
                    'position': i + 1,
                    'text': result.get('text', ''),
                    'document_id': doc_id,
                    'document_name': doc_names_mapping.get(doc_id, 'Неизвестный документ'),
                    'page_number': result.get('metadata', {}).get('page_number', 'Не указана'),
                    'score': round(float(result.get('score', 0.0)), 4),
                    'search_type': result.get('search_type', 'vector'),
                    # Сохраняем section и content_type для возможной отладки
                    'metadata': {
                        'section': result.get('metadata', {}).get('section'),
                        'content_type': result.get('metadata', {}).get('content_type')
                    }
                }

                # Добавляем rerank_score если есть
                if 'rerank_score' in result:
                    formatted_result['rerank_score'] = round(float(result.get('rerank_score', 0.0)), 4)

                formatted_results.append(formatted_result)

            # Финальное обновление статуса
            self.update_state(state='PROGRESS', meta={
                'status': 'progress',
                'progress': 90,
                'stage': 'finishing',
                'message': 'Завершение поиска...'
            })

            # Последняя проверка отмены
            check_if_cancelled()

            # Результат
            result = {
                'status': 'success',
                'count': len(formatted_results),
                'use_reranker': use_reranker,
                'use_smart_search': use_smart_search,
                'search_method': search_method,
                'use_llm': use_llm,
                'execution_time': round(time.time() - start_time, 2),
                'results': formatted_results,
                'llm_result': llm_result,
                'progress': 100,
                'stage': 'complete',
                'message': 'Поиск завершен'
            }

            # Важно! Устанавливаем финальный статус
            self.update_state(state='SUCCESS', meta=result)

            return result

        except (Terminated, WorkerLostError) as e:
            # Задача была отменена
            logger.info(f"Задача поиска {task_id} была отменена")
            cancelled_result = {
                'status': 'cancelled',
                'message': 'Поиск был отменен пользователем',
                'execution_time': round(time.time() - start_time, 2),
                'progress': 0,
                'stage': 'cancelled'
            }
            self.update_state(state='REVOKED', meta=cancelled_result)
            return cancelled_result

        except Exception as e:
            logger.error(f"Ошибка при поиске: {e}")
            error_result = {
                'status': 'error',
                'message': str(e),
                'execution_time': round(time.time() - start_time, 2),
                'progress': 0,
                'stage': 'error'
            }
            self.update_state(state='FAILURE', meta=error_result)
            return error_result


def format_documents_for_context(documents, max_docs=8):
    """Форматирует документы для контекста"""
    formatted = []
    for i, doc in enumerate(documents[:max_docs]):
        text = doc.get('text', '')
        metadata = doc.get('metadata', {})

        doc_text = f"Документ {i + 1}:\n"
        if metadata.get('section'):
            doc_text += f"Раздел: {metadata['section']}\n"
        if metadata.get('content_type'):
            doc_text += f"Тип: {metadata['content_type']}\n"
        doc_text += f"Текст:\n{text}\n" + "-" * 40

        formatted.append(doc_text)

    return "\n\n".join(formatted)


def extract_value_from_response(response, query):
    """Извлекает значение из ответа LLM"""
    lines = [line.strip() for line in response.split('\n') if line.strip()]

    # Ищем строку с результатом
    for line in lines:
        if line.startswith("РЕЗУЛЬТАТ:"):
            return line.replace("РЕЗУЛЬТАТ:", "").strip()

    # Ищем строку с двоеточием
    for line in lines:
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()

    # Возвращаем последнюю строку
    return lines[-1] if lines else "Информация не найдена"


def calculate_confidence(response):
    """Рассчитывает уверенность в ответе"""
    uncertainty_phrases = [
        "возможно", "вероятно", "может быть", "предположительно",
        "не ясно", "не уверен", "не определено", "информация не найдена"
    ]

    confidence = 0.8
    response_lower = response.lower()

    for phrase in uncertainty_phrases:
        if phrase in response_lower:
            confidence -= 0.1

    return max(0.1, min(confidence, 1.0))