from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from app.blueprints.search import bp
from app.models import Application
from app.adapters.qdrant_adapter import QdrantAdapter
from app.services.vector_service import search


@bp.route('/')
def index():
    """Страница семантического поиска"""
    # Получаем список доступных заявок
    applications = Application.query.filter(Application.status.in_(['indexed', 'analyzed'])).all()

    return render_template('search/index.html',
                           title='Семантический поиск',
                           applications=applications)


@bp.route('/execute', methods=['POST'])
def execute_search():
    """Выполняет поиск и возвращает результаты в формате JSON"""
    application_id = request.form.get('application_id')
    query = request.form.get('query')
    limit = int(request.form.get('limit', 5))
    use_reranker = request.form.get('use_reranker') == 'true'  # Получаем параметр ререйтинга

    if not application_id or not query:
        return jsonify({
            'status': 'error',
            'message': 'Не указана заявка или поисковый запрос'
        })

    try:
        # Фиксируем время начала поиска
        import time
        start_time = time.time()

        # Логируем запрос
        current_app.logger.info(f"Поиск: '{query}', Заявка: {application_id}, Ререйтинг: {use_reranker}")

        # Получаем адаптер для поиска с поддержкой ререйтинга
        qdrant_adapter = QdrantAdapter(
            host=current_app.config['QDRANT_HOST'],
            port=current_app.config['QDRANT_PORT'],
            collection_name=current_app.config['QDRANT_COLLECTION'],
            embeddings_type='ollama',
            model_name='bge-m3',
            ollama_url=current_app.config['OLLAMA_URL'],
            use_reranker=use_reranker,  # Передаем параметр ререйтинга
            reranker_model='BAAI/bge-reranker-v2-m3'  # Модель ререйтинга
        )

        # Выполняем поиск с учетом ререйтинга
        # Для ререйтинга нужно получить больше первичных результатов
        rerank_limit = limit * 4 if use_reranker else None

        results = qdrant_adapter.search(
            application_id=application_id,
            query=query,
            limit=limit,
            rerank_limit=rerank_limit
        )

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

        # Вычисляем общее время выполнения
        execution_time = time.time() - start_time
        current_app.logger.info(f"Поиск выполнен за {execution_time:.2f} сек., найдено {len(results)} результатов")

        return jsonify({
            'status': 'success',
            'count': len(results),
            'use_reranker': use_reranker,
            'execution_time': round(execution_time, 2),
            'results': formatted_results
        })

    except Exception as e:
        current_app.logger.error(f"Ошибка при выполнении поиска: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        })