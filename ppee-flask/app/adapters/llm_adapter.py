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
                      parameters: Dict[str, Any],
                      query: str = None) -> str:
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
                      parameters: Dict[str, Any],
                      query: str = None) -> str:
        """
        Обрабатывает запрос к LLM через Ollama API.

        Args:
            model_name: Название модели
            prompt: Шаблон промпта
            context: Контекст (результаты поиска)
            parameters: Параметры генерации
            query: Поисковый запрос (если нужно заменить {query} в шаблоне)

        Returns:
            str: Ответ модели
        """
        try:
            # Создаем полный промпт, заменяя плейсхолдеры
            full_prompt = prompt.replace("{context}", context)

            # Обязательно заменяем {query} на реальный запрос
            if query:
                full_prompt = full_prompt.replace("{query}", query)
            else:
                # Если query не передан, используем значение из параметра search_query
                # Это резервный вариант, лучше всегда передавать query
                search_query = parameters.get("search_query", "запрос")
                full_prompt = full_prompt.replace("{query}", search_query)

            # Формируем запрос к Ollama API в корректном формате
            payload = {
                "model": model_name,
                "prompt": full_prompt,
                "stream": False,
                "temperature": parameters.get("temperature", 0.1),
                "max_tokens": parameters.get("max_tokens", 1000)
            }

            logger.info(f"Отправка запроса к модели {model_name} через Ollama API")
            logger.debug(f"Полный payload для Ollama API: {json.dumps(payload, indent=2)}")

            # Отправляем запрос
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=120  # Увеличенный таймаут для сложных запросов
            )
            response.raise_for_status()

            # Получаем ответ
            result = response.json()

            # Проверяем на наличие ошибок в ответе
            if "error" in result:
                error_msg = f"Ошибка Ollama API: {result.get('error')}"
                logger.error(error_msg)
                return f"Ошибка: {error_msg}"

            answer = result.get("response", "")

            # Выводим полный ответ модели для отладки
            logger.info(f"Получен ответ от модели {model_name} длиной {len(answer)} символов")
            logger.debug(f"Полный ответ от модели {model_name}:\n{answer}")

            return answer

        except requests.exceptions.RequestException as e:
            error_msg = f"Ошибка HTTP при запросе к Ollama API: {str(e)}"
            logger.error(error_msg)
            return f"Ошибка сети: {error_msg}"
        except Exception as e:
            error_msg = f"Ошибка при обработке запроса через Ollama API: {str(e)}"
            logger.error(error_msg)
            return f"Ошибка: {error_msg}"