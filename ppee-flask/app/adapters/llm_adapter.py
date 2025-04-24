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
            # Вариант 1: Используем POST-запрос с JSON-телом
            # Этот вариант более надежен для имен с спецсимволами
            url = f"{self.base_url}/api/show"

            response = requests.post(
                url,
                json={"name": model_name},
                timeout=5
            )

            # Если POST не работает, попробуем другие методы
            if response.status_code != 200:
                logger.info(f"POST запрос не сработал, пробуем другие варианты для {model_name}")

                # Вариант 2: Получаем список всех моделей и ищем нужную
                models_response = requests.get(f"{self.base_url}/api/tags")
                models_response.raise_for_status()

                models_data = models_response.json().get("models", [])
                found_model = None

                # Ищем модель по имени (без учета регистра)
                for model in models_data:
                    if model.get("name", "").lower() == model_name.lower():
                        found_model = model
                        break

                if found_model:
                    logger.info(f"Модель {model_name} найдена в списке моделей")
                    self._models_cache[model_name] = found_model
                    return found_model
                else:
                    # Если модель не найдена, создаем базовую информацию
                    logger.warning(f"Модель {model_name} не найдена в API Ollama")
                    default_info = {
                        "name": model_name,
                        "not_found": True,
                        # Устанавливаем значения по умолчанию
                        "parameters": {
                            "context_length": self._get_default_context_length(model_name)
                        }
                    }
                    self._models_cache[model_name] = default_info
                    return default_info

            # Если запрос успешный, обрабатываем результат
            model_info = response.json()
            logger.info(f"Получена информация о модели {model_name}")

            # Сохраняем в кэш
            self._models_cache[model_name] = model_info
            return model_info
        except Exception as e:
            logger.error(f"Ошибка при получении информации о модели {model_name}: {str(e)}")
            # Возвращаем информацию с отметкой об ошибке и значениями по умолчанию
            default_info = {
                "name": model_name,
                "error": str(e),
                "parameters": {
                    "context_length": self._get_default_context_length(model_name)
                }
            }
            self._models_cache[model_name] = default_info
            return default_info

    def _get_default_context_length(self, model_name: str) -> int:
        """
        Возвращает размер контекста по умолчанию для модели на основе ее названия.

        Args:
            model_name: Название модели

        Returns:
            int: Размер контекста по умолчанию
        """
        model_name_lower = model_name.lower()

        if "gemma3:27b" in model_name_lower:
            return 8192
        elif "gemma3:7b" in model_name_lower:
            return 8192
        elif "gemma3:2b" in model_name_lower:
            return 8192
        elif "llama3:70b" in model_name_lower:
            return 8192
        elif "llama3:8b" in model_name_lower:
            return 8192
        elif "mistral" in model_name_lower:
            return 8192
        elif "mixtral" in model_name_lower:
            return 32768
        elif "phi3" in model_name_lower:
            return 4096

        # Значение по умолчанию
        return 4096

    def get_context_length(self, model_name: str) -> int:
        """
        Получает максимальный размер контекста для модели.

        Args:
            model_name: Название модели

        Returns:
            int: Максимальный размер контекста
        """
        # Получаем информацию о модели
        model_info = self.get_model_info(model_name)

        # Пытаемся найти информацию о размере контекста в разных местах
        # в зависимости от версии Ollama и типа модели
        context_length = None

        # Вариант 1: Если модель не найдена, возвращаем значение по умолчанию
        if model_info.get("not_found") or model_info.get("error"):
            context_length = model_info.get("parameters", {}).get("context_length")
            if context_length is not None:
                try:
                    return int(context_length)
                except (ValueError, TypeError):
                    pass
            return self._get_default_context_length(model_name)

        # Вариант 2: Прямой параметр context_length
        if 'context_length' in model_info:
            context_length = model_info['context_length']
            if context_length is not None:
                try:
                    return int(context_length)
                except (ValueError, TypeError):
                    pass

        # Вариант 3: Внутри parameters
        elif 'parameters' in model_info:
            params = model_info['parameters']
            context_length = params.get('context_length')
            if context_length is not None:
                try:
                    return int(context_length)
                except (ValueError, TypeError):
                    pass

        # Вариант 4: Внутри modelfile в виде строки
        elif 'modelfile' in model_info:
            modelfile = model_info['modelfile']
            match = re.search(r'PARAMETER\s+context_length\s+(\d+)', modelfile)
            if match:
                try:
                    context_length = int(match.group(1))
                    return context_length
                except (ValueError, IndexError):
                    pass

        # Если не удалось найти, используем значение по умолчанию
        return self._get_default_context_length(model_name)

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
            # Исправленная часть - надежная обработка context_length
            context_length = None
            if "context_length" in parameters:
                try:
                    context_length = int(parameters.get("context_length"))
                except (ValueError, TypeError):
                    logger.warning(
                        f"Невалидное значение context_length в параметрах: {parameters.get('context_length')}")
                    context_length = None

            if context_length is None:
                try:
                    context_length = self.get_context_length(model_name)
                except Exception as e:
                    logger.warning(f"Ошибка при получении context_length: {str(e)}")
                    context_length = 4096  # Значение по умолчанию

            # Формируем запрос к Ollama API в корректном формате
            payload = {
                "model": model_name,
                "prompt": full_prompt,
                "stream": False,
                "temperature": parameters.get("temperature", 0.1),
                "max_tokens": parameters.get("max_tokens", 1000),
                "context_length": context_length
            }

            logger.info(f"Отправка запроса к модели {model_name} через Ollama API")
            logger.debug(
                f"Параметры запроса: контекст={context_length}, температура={parameters.get('temperature', 0.1)}, max_tokens={parameters.get('max_tokens', 1000)}")

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