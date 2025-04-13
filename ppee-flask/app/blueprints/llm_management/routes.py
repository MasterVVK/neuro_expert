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
                response = requests.get(f"{current_app.config['OLLAMA_URL']}/api/show", 
                                       params={"name": model_name})
                if response.status_code == 200:
                    models_info[model_name] = response.json()
                else:
                    models_info[model_name] = {"error": f"Не удалось получить информацию (код {response.status_code})"}
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
        
        try:
            # Тестируем модель
            llm_provider = OllamaLLMProvider(base_url=current_app.config['OLLAMA_URL'])
            response = llm_provider.process_query(
                model_name=model_name,
                prompt=prompt,
                context="",  # При тестировании нет контекста
                parameters={
                    'temperature': temperature,
                    'max_tokens': max_tokens
                }
            )
            
            return render_template('llm_management/test.html',
                                  title='Тест LLM',
                                  model_name=model_name,
                                  prompt=prompt,
                                  temperature=temperature,
                                  max_tokens=max_tokens,
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
