from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from app.blueprints.llm_management import bp
from app.services.fastapi_client import FastAPIClient
import logging

logger = logging.getLogger(__name__)


@bp.route('/')
def index():
    """Страница управления LLM через FastAPI"""
    try:
        client = FastAPIClient()

        # Получаем список моделей
        available_models = client.get_llm_models()

        # Получаем подробную информацию о моделях через FastAPI
        models_info = client.get_llm_models_info()

        # Если информация не получена, создаем базовую структуру
        if not models_info:
            models_info = {}
            for model_name in available_models:
                models_info[model_name] = {
                    "parameter_size": "Неизвестно",
                    "context_length": 8192,
                    "family": "Неизвестно"
                }

        return render_template('llm_management/index.html',
                               title='Управление LLM',
                               available_models=available_models,
                               models_info=models_info,
                               ollama_url=current_app.config['OLLAMA_URL'])

    except Exception as e:
        logger.error(f"Ошибка при получении информации о моделях: {str(e)}")
        return render_template('llm_management/index.html',
                               title='Управление LLM',
                               available_models=[],
                               models_info={},
                               error=str(e),
                               ollama_url=current_app.config['OLLAMA_URL'])


@bp.route('/test', methods=['GET', 'POST'])
def test():
    """Страница для тестирования LLM через FastAPI"""
    if request.method == 'POST':
        model_name = request.form.get('model_name')
        prompt = request.form.get('prompt')
        temperature = float(request.form.get('temperature', 0.1))
        max_tokens = int(request.form.get('max_tokens', 1000))
        context_length = int(request.form.get('context_length', 4096))

        try:
            # Тестируем модель через FastAPI
            client = FastAPIClient()

            # Используем метод process_llm_query вместо прямого HTTP запроса
            response = client.process_llm_query(
                model_name=model_name,
                prompt=prompt,
                context="",  # При тестировании нет контекста
                parameters={
                    'temperature': temperature,
                    'max_tokens': max_tokens,
                    'context_length': context_length
                }
            )

            # Извлекаем ответ
            llm_response = response.get("response", "Нет ответа от модели")

            return render_template('llm_management/test.html',
                                   title='Тест LLM',
                                   model_name=model_name,
                                   prompt=prompt,
                                   temperature=temperature,
                                   max_tokens=max_tokens,
                                   context_length=context_length,
                                   response=llm_response,
                                   available_models=client.get_llm_models())

        except Exception as e:
            logger.error(f"Ошибка при тестировании модели: {str(e)}")
            flash(f"Ошибка при тестировании модели: {str(e)}", "error")

    # Получаем список доступных моделей
    try:
        client = FastAPIClient()
        available_models = client.get_llm_models()
    except Exception as e:
        logger.error(f"Ошибка при получении списка моделей: {str(e)}")
        available_models = []

    return render_template('llm_management/test.html',
                           title='Тест LLM',
                           available_models=available_models)


@bp.route('/model_info')
def model_info():
    """API для получения информации о модели через FastAPI"""
    model_name = request.args.get('name')

    if not model_name:
        return jsonify({'error': 'Не указано имя модели'}), 400

    try:
        client = FastAPIClient()

        # Получаем информацию о всех моделях
        models_info = client.get_llm_models_info()

        if model_name in models_info:
            model_data = models_info[model_name]

            return jsonify({
                'name': model_name,
                'context_length': model_data.get('context_length', 8192),
                'parameters': model_data.get('context_length', 8192),  # Для обратной совместимости
                'parameter_size': model_data.get('parameter_size', 'Неизвестно'),
                'family': model_data.get('family', 'Неизвестно'),
                'quantization': model_data.get('quantization', 'Неизвестно'),
                'size_gb': model_data.get('size_gb')
            })

        # Если модель не найдена, пробуем получить детальную информацию
        model_details = client.get_model_details(model_name)
        if model_details:
            return jsonify({
                'name': model_name,
                'context_length': model_details.get('context_length', 8192),
                'parameters': model_details.get('context_length', 8192),
                'parameter_size': model_details.get('details', {}).get('parameter_size', 'Неизвестно'),
                'family': model_details.get('details', {}).get('family', 'Неизвестно'),
                'quantization': model_details.get('details', {}).get('quantization_level', 'Неизвестно')
            })

        # Если ничего не найдено, возвращаем значения по умолчанию
        return jsonify({
            'name': model_name,
            'context_length': 8192,
            'parameters': 8192,
            'parameter_size': 'Неизвестно',
            'family': 'Неизвестно'
        })

    except Exception as e:
        logger.error(f"Ошибка при получении информации о модели: {str(e)}")
        return jsonify({'error': str(e)}), 500