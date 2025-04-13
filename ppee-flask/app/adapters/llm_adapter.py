import logging
import requests
import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class LLMProvider(ABC):
    """Интерфейс для провайдеров LLM"""
    
    @abstractmethod
    def get_available_models(self) -> List[str]:
        """Возвращает список доступных моделей"""
        pass
    
    @abstractmethod
    def process_query(self, 
                      model_name: str, 
                      prompt: str, 
                      context: str, 
                      parameters: Dict[str, Any]) -> str:
        """Обрабатывает запрос к LLM"""
        pass

class OllamaLLMProvider(LLMProvider):
    """Реализация провайдера LLM через Ollama API"""
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        """
        Инициализирует провайдер Ollama.
        
        Args:
            base_url: URL для Ollama API
        """
        self.base_url = base_url.rstrip('/')
        logger.info(f"OllamaLLMProvider инициализирован с URL: {self.base_url}")
    
    def get_available_models(self) -> List[str]:
        """
        Возвращает список доступных моделей в Ollama.
        
        Returns:
            List[str]: Список имен моделей
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            
            models = []
            for model in response.json().get("models", []):
                models.append(model.get("name"))
            
            logger.info(f"Получено {len(models)} доступных моделей из Ollama")
            return models
        except Exception as e:
            logger.error(f"Ошибка при получении списка моделей из Ollama: {str(e)}")
            return []
    
    def process_query(self, 
                      model_name: str, 
                      prompt: str, 
                      context: str, 
                      parameters: Dict[str, Any]) -> str:
        """
        Обрабатывает запрос к LLM через Ollama API.
        
        Args:
            model_name: Название модели
            prompt: Шаблон промпта
            context: Контекст (результаты поиска)
            parameters: Параметры генерации
            
        Returns:
            str: Ответ модели
        """
        try:
            # Создаем полный промпт, заменяя placeholder для контекста
            full_prompt = prompt.replace("{context}", context)
            
            # Формируем запрос к Ollama API
            payload = {
                "model": model_name,
                "prompt": full_prompt,
                "stream": False,
                "options": {
                    "temperature": parameters.get("temperature", 0.1),
                    "num_predict": parameters.get("max_tokens", 1000)
                }
            }
            
            logger.info(f"Отправка запроса к модели {model_name} через Ollama API")
            
            # Отправляем запрос
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=120  # Увеличенный таймаут для сложных запросов
            )
            response.raise_for_status()
            
            # Получаем ответ
            result = response.json()
            answer = result.get("response", "")
            
            logger.info(f"Получен ответ от модели {model_name} длиной {len(answer)} символов")
            return answer
            
        except Exception as e:
            error_msg = f"Ошибка при обработке запроса через Ollama API: {str(e)}"
            logger.error(error_msg)
            return f"Ошибка: {error_msg}"
