from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from app.blueprints.llm_management import bp
from app.services.fastapi_client import FastAPIClient
import requests
import logging

logger = logging.getLogger(__name__)


@bp.route('/')
def index():
    """Страница управления LLM через FastAPI"""
    try:
        client = FastAPIClient()
        available_models = client.get_llm_models()

        # Получаем информацию о моделях
        models_info = {}
        # Упрощаем - просто показываем список моделей
        for model_name in available_models:
            models_info[model_name] = {
                "context_length": 8192,  # Значение по умолчанию
                "parameter_size": "Неизвестно",
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

            # Отправляем запрос
            response = requests.post(f"{client.base_url}/llm/process", json={
                "model_name": model_name,
                "prompt": prompt,
                "context": "",  # При тестировании нет контекста
                "parameters": {
                    'temperature': temperature,
                    'max_tokens': max_tokens,
                    'context_length': context_length
                },
                "query": None
            })

            if response.status_code == 200:
                llm_response = response.json()["response"]
            else:
                raise Exception(f"FastAPI вернул ошибку: {response.text}")

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
        available_models = ['gemma3:27b', 'llama3:8b', 'mistral:7b']

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
        # Получаем список моделей через FastAPI
        client = FastAPIClient()
        models = client.get_llm_models()

        if model_name in models:
            # Возвращаем базовую информацию
            # В будущем можно расширить, запросив детальную информацию у FastAPI
            context_length = 8192  # Значение по умолчанию

            # Определяем контекст на основе имени модели
            if "gemma3" in model_name.lower():
                context_length = 8192
            elif "llama3" in model_name.lower():
                context_length = 8192
            elif "mixtral" in model_name.lower():
                context_length = 32768
            elif "phi3" in model_name.lower():
                context_length = 4096

            return jsonify({
                'name': model_name,
                'context_length': context_length,
                'parameters': context_length,  # Для обратной совместимости
                'family': 'Неизвестно'
            })

        return jsonify({'error': 'Модель не найдена'}), 404

    except Exception as e:
        logger.error(f"Ошибка при получении информации о модели: {str(e)}")
        return jsonify({'error': str(e)}), 500