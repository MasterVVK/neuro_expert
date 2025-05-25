from app import celery
import logging
import requests
import time

logger = logging.getLogger(__name__)

FASTAPI_URL = "http://localhost:8001"


@celery.task(bind=True)
def semantic_search_task(self, application_id, query_text, limit=5, use_reranker=False,
                         rerank_limit=None, use_llm=False, llm_params=None,
                         use_smart_search=False, vector_weight=0.5, text_weight=0.5,
                         hybrid_threshold=10):
    """Асинхронная задача для семантического поиска через FastAPI"""

    task_id = self.request.id
    start_time = time.time()  # Добавляем определение start_time здесь

    try:
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

        # Обработка через LLM если нужно
        llm_result = None
        if use_llm and llm_params and search_results:
            # Форматируем контекст
            context = format_documents_for_context(search_results)

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

        # Форматируем результаты
        formatted_results = []
        for i, result in enumerate(search_results):
            formatted_result = {
                'position': i + 1,
                'text': result.get('text', ''),
                'section': result.get('metadata', {}).get('section', 'Неизвестно'),
                'content_type': result.get('metadata', {}).get('content_type', 'Неизвестно'),
                'score': round(float(result.get('score', 0.0)), 4),
                'search_type': result.get('search_type', 'vector')
            }

            # Добавляем rerank_score если есть
            if 'rerank_score' in result:
                formatted_result['rerank_score'] = round(float(result.get('rerank_score', 0.0)), 4)

            formatted_results.append(formatted_result)

        # Определяем метод поиска
        search_method = 'vector'
        if use_smart_search:
            search_method = 'hybrid' if len(query_text) < hybrid_threshold else 'vector'

        return {
            'status': 'success',
            'count': len(formatted_results),
            'use_reranker': use_reranker,
            'use_smart_search': use_smart_search,
            'search_method': search_method,
            'use_llm': use_llm,
            'execution_time': round(time.time() - start_time, 2),
            'results': formatted_results,
            'llm_result': llm_result
        }

    except Exception as e:
        logger.error(f"Ошибка при поиске: {e}")
        return {
            'status': 'error',
            'message': str(e),
            'execution_time': round(time.time() - start_time, 2)
        }


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