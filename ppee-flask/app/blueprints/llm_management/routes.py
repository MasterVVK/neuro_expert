from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from app.blueprints.llm_management import bp
from app.adapters.llm_adapter import OllamaLLMProvider
import requests
import logging

logger = logging.getLogger(__name__)


@bp.route('/')
def index():
    """Страница управления LLM"""
    try:
        # Получаем информацию о доступных моделях
        llm_provider = OllamaLLMProvider(base_url=current_app.config['OLLAMA_URL'])
        available_models = llm_provider.get_available_models()

        # Получаем дополнительную информацию о моделях из Ollama API
        models_info = {}
        for model_name in available_models:
            try:
                model_info = llm_provider.get_model_info(model_name)
                models_info[model_name] = model_info
            except Exception as e:
                models_info[model_name] = {"error": str(e)}

        return render_template('llm_management/index.html',
                               title='Управление LLM',
                               available_models=available_models,
                               models_info=models_info,
                               ollama_url=current_app.config['OLLAMA_URL'])
    except Exception as e:
        logger.error(f"Ошибка при получении информации о моделях: {str(e)}")
        flash(f"Ошибка при получении информации о моделях: {str(e)}", "error")
        return render_template('llm_management/index.html',
                               title='Управление LLM',
                               available_models=[],
                               models_info={},
                               error=str(e),
                               ollama_url=current_app.config['OLLAMA_URL'])


@bp.route('/test', methods=['GET', 'POST'])
def test():
    """Страница для тестирования LLM"""
    if request.method == 'POST':
        model_name = request.form.get('model_name')
        prompt = request.form.get('prompt')
        temperature = float(request.form.get('temperature', 0.1))
        max_tokens = int(request.form.get('max_tokens', 1000))
        context_length = int(request.form.get('context_length', 4096))

        try:
            # Тестируем модель
            llm_provider = OllamaLLMProvider(base_url=current_app.config['OLLAMA_URL'])
            response = llm_provider.process_query(
                model_name=model_name,
                prompt=prompt,
                context="",  # При тестировании нет контекста
                parameters={
                    'temperature': temperature,
                    'max_tokens': max_tokens,
                    'context_length': context_length
                }
            )

            return render_template('llm_management/test.html',
                                   title='Тест LLM',
                                   model_name=model_name,
                                   prompt=prompt,
                                   temperature=temperature,
                                   max_tokens=max_tokens,
                                   context_length=context_length,
                                   response=response)
        except Exception as e:
            logger.error(f"Ошибка при тестировании модели: {str(e)}")
            flash(f"Ошибка при тестировании модели: {str(e)}", "error")

    # Получаем список доступных моделей
    try:
        llm_provider = OllamaLLMProvider(base_url=current_app.config['OLLAMA_URL'])
        available_models = llm_provider.get_available_models()
    except Exception as e:
        logger.error(f"Ошибка при получении списка моделей: {str(e)}")
        available_models = ['gemma3:27b', 'llama3:8b', 'mistral:7b']

    return render_template('llm_management/test.html',
                           title='Тест LLM',
                           available_models=available_models)


@bp.route('/model_info')
def model_info():
    """API для получения информации о модели"""
    model_name = request.args.get('name')

    if not model_name:
        return jsonify({'error': 'Не указано имя модели'}), 400

    try:
        llm_provider = OllamaLLMProvider(base_url=current_app.config['OLLAMA_URL'])

        # Получаем информацию о модели
        model_info = llm_provider.get_model_info(model_name)

        # Определяем context_length
        context_length = llm_provider.get_context_length(model_name)

        # Формируем ответ
        response = {
            'name': model_name,
            'context_length': context_length
        }

        # Добавляем дополнительную информацию, если она есть
        if 'parameters' in model_info:
            response['parameters'] = model_info['parameters']

        if 'family' in model_info:
            response['family'] = model_info['family']

        if 'parameter_size' in model_info:
            response['parameter_size'] = model_info['parameter_size']

        return jsonify(response)

    except Exception as e:
        logger.error(f"Ошибка при получении информации о модели {model_name}: {str(e)}")
        return jsonify({'error': str(e)}), 500