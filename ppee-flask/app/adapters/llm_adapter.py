import logging
import requests
import json
import re
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
        self._models_cache = {}  # Кэш для информации о моделях
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

    def get_model_info(self, model_name: str, refresh: bool = False) -> Dict[str, Any]:
        """
        Получает информацию о модели из Ollama API.

        Args:
            model_name: Название модели
            refresh: Принудительно обновить кэш

        Returns:
            Dict[str, Any]: Информация о модели
        """
        # Проверяем кэш, если обновление не требуется
        if not refresh and model_name in self._models_cache:
            return self._models_cache[model_name]

        try:
            url = f"{self.base_url}/api/show"
            response = requests.get(url, params={"name": model_name})
            response.raise_for_status()

            model_info = response.json()
            logger.info(f"Получена информация о модели {model_name}")

            # Сохраняем в кэш
            self._models_cache[model_name] = model_info
            return model_info
        except Exception as e:
            logger.error(f"Ошибка при получении информации о модели {model_name}: {str(e)}")
            return {}

    def get_context_length(self, model_name: str) -> int:
        """
        Получает максимальный размер контекста для модели.

        Args:
            model_name: Название модели

        Returns:
            int: Максимальный размер контекста
        """
        model_info = self.get_model_info(model_name)

        # Пытаемся найти информацию о размере контекста в разных местах
        # в зависимости от версии Ollama и типа модели
        context_length = None

        # Вариант 1: Прямой параметр context_length
        if 'context_length' in model_info:
            context_length = model_info['context_length']

        # Вариант 2: Внутри parameters
        elif 'parameters' in model_info:
            params = model_info['parameters']
            context_length = params.get('context_length')

        # Вариант 3: Внутри modelfile в виде строки
        elif 'modelfile' in model_info:
            modelfile = model_info['modelfile']
            match = re.search(r'PARAMETER\s+context_length\s+(\d+)', modelfile)
            if match:
                context_length = int(match.group(1))

        # Значение по умолчанию, если не удалось найти
        if context_length is None:
            # Стандартные значения для известных моделей
            if "gemma3:27b" in model_name:
                context_length = 8192
            elif "llama3" in model_name:
                context_length = 8192
            elif "mixtral" in model_name:
                context_length = 32768
            else:
                context_length = 4096  # Значение по умолчанию

        logger.info(f"Определен размер контекста для модели {model_name}: {context_length}")
        return context_length

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

            # Получаем информацию о размере контекста для модели
            context_length = parameters.get("context_length", self.get_context_length(model_name))

            # Формируем запрос к Ollama API в корректном формате
            payload = {
                "model": model_name,
                "prompt": full_prompt,
                "stream": False,
                "temperature": parameters.get("temperature", 0.1),
                "max_tokens": parameters.get("max_tokens", 1000),
                "context_length": context_length  # Используем определенный размер контекста
            }

            logger.info(f"Отправка запроса к модели {model_name} через Ollama API")
            logger.debug(
                f"Параметры запроса: контекст={context_length}, температура={parameters.get('temperature', 0.1)}, max_tokens={parameters.get('max_tokens', 1000)}")
            logger.debug(f"Полный payload для Ollama API: {json.dumps(payload, indent=2)}")

            # Отправляем запрос
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=1200  # Увеличенный таймаут для сложных запросов
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