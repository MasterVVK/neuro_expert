import requests
import json
import time
import re
import sys


class OllamaClient:
    """Расширенный клиент для работы с Ollama API с детальным выводом информации"""

    def __init__(self, base_url="http://localhost:11434", verbose=True):
        """Инициализирует клиент Ollama.

        Args:
            base_url: URL для Ollama API
            verbose: Выводить подробные логи
        """
        self.base_url = base_url.rstrip('/')
        self.verbose = verbose
        self.context_cache = {}  # Для хранения контекста между запросами

        # Проверяем доступность API
        if self.verbose:
            print(f"[ИНФО] Инициализация OllamaClient с базовым URL: {self.base_url}")
            self._check_api_availability()

    def _check_api_availability(self):
        """Проверяет доступность Ollama API"""
        try:
            response = requests.get(f"{self.base_url}")
            print(f"[ИНФО] Статус Ollama API: {response.status_code}")

            if response.status_code == 200:
                print(f"[ИНФО] Ollama API доступен")

                # Проверяем наличие моделей
                models = self.list_models()
                if models:
                    print(f"[ИНФО] Доступные модели: {', '.join(models)}")
                else:
                    print(f"[ПРЕДУПРЕЖДЕНИЕ] Не найдено доступных моделей")
            else:
                print(f"[ОШИБКА] Ollama API недоступен, код ответа: {response.status_code}")
        except Exception as e:
            print(f"[ОШИБКА] Не удалось подключиться к Ollama API: {str(e)}")

    def list_models(self):
        """Получает список всех доступных моделей.

        Returns:
            list: Список названий моделей
        """
        try:
            if self.verbose:
                print(f"[ЗАПРОС] GET {self.base_url}/api/tags")

            response = requests.get(f"{self.base_url}/api/tags")

            if self.verbose:
                print(f"[ОТВЕТ] Статус: {response.status_code}")
                if response.status_code == 200:
                    print(f"[ОТВЕТ] Заголовки: {json.dumps(dict(response.headers), indent=2)}")

            if response.status_code == 200:
                data = response.json()

                if self.verbose:
                    print(f"[ОТВЕТ] Содержимое ответа (сокращенно): {len(data.get('models', []))} моделей")

                return [model.get("name") for model in data.get("models", [])]
            else:
                if self.verbose:
                    print(f"[ОШИБКА] {response.text}")
                return []
        except Exception as e:
            if self.verbose:
                print(f"[ИСКЛЮЧЕНИЕ] При получении списка моделей: {str(e)}")
            return []

    def get_model_info(self, model_name="gemma3:27b"):
        """Получает детальную информацию о модели из Ollama API без вывода.

        Args:
            model_name: Название модели

        Returns:
            dict: Полная информация о модели
        """
        try:
            # Формируем запрос
            url = f"{self.base_url}/api/show"
            payload = {"name": model_name, "verbose": True}

            # Отправляем запрос без вывода информации
            response = requests.post(
                url,
                json=payload,
                timeout=120  # Увеличенный таймаут для получения метаданных
            )

            if response.status_code == 200:
                return response.json()
            else:
                if self.verbose:
                    print(f"[ОШИБКА] Не удалось получить информацию о модели: {response.status_code}")
                return None

        except Exception as e:
            if self.verbose:
                print(f"[ИСКЛЮЧЕНИЕ] При получении информации о модели: {str(e)}")
            return None

    def extract_context_length(self, model_info):
        """Извлекает размер контекста из информации о модели.

        Args:
            model_info: Информация о модели

        Returns:
            int: Размер контекста модели
        """
        if not model_info:
            if self.verbose:
                print("[ИНФО] Информация о модели недоступна, используем значение по умолчанию: 8192")
            return 8192  # Значение по умолчанию

        # Прямое получение context_length из model_info для разных моделей
        if 'model_info' in model_info and isinstance(model_info['model_info'], dict):
            for key in model_info['model_info']:
                if key.endswith('.context_length'):
                    context_length = int(model_info['model_info'][key])
                    if self.verbose:
                        print(f"[ИНФО] Найден context_length в model_info.{key}: {context_length}")
                    return context_length

        # Проверяем другие возможные пути
        if 'parameters' in model_info:
            params = model_info['parameters']
            if isinstance(params, dict) and 'context_length' in params:
                context_length = int(params['context_length'])
                if self.verbose:
                    print(f"[ИНФО] Найден context_length в parameters: {context_length}")
                return context_length

        # Поиск в modelfile
        if 'modelfile' in model_info and isinstance(model_info['modelfile'], str):
            match = re.search(r'PARAMETER\s+(?:context_length|num_ctx|ctx_len)\s+(\d+)', model_info['modelfile'],
                              re.IGNORECASE)
            if match:
                context_length = int(match.group(1))
                if self.verbose:
                    print(f"[ИНФО] Найден context_length в modelfile: {context_length}")
                return context_length

        # Угадываем по названию модели
        model_name = model_info.get('name', '').lower()
        if model_name:
            context_map = {
                'gemma3:27b': 8192,
                'gemma3:7b': 8192,
                'gemma3:2b': 8192,
                'llama3:70b': 8192,
                'llama3:8b': 8192,
                'mistral': 8192,
                'mixtral': 32768,
                'phi3': 4096
            }

            for key, length in context_map.items():
                if key in model_name:
                    if self.verbose:
                        print(f"[ИНФО] Определен context_length по названию модели '{key}': {length}")
                    return length

        # Значение по умолчанию
        if self.verbose:
            print("[ИНФО] Не удалось определить context_length, используем значение по умолчанию: 8192")
        return 8192

    def generate_text(self, prompt, model_name="gemma3:27b", temperature=0.7, max_tokens=1000):
        """Генерирует текст с помощью модели Ollama.

        Args:
            prompt: Текст запроса
            model_name: Название модели
            temperature: Температура (креативность) генерации
            max_tokens: Максимальное количество токенов в ответе

        Returns:
            str: Сгенерированный текст
        """
        try:
            # Получаем информацию о модели без вывода
            model_info = self.get_model_info(model_name)

            # Определяем размер контекста
            context_length = self.extract_context_length(model_info)

            # Используем полученный размер контекста для настройки параметров
            options = {
#                "num_ctx": context_length,
                "num_ctx": 32768,
                "num_keep": 16384,
                "temperature": temperature,
                "num_predict": max_tokens
            }

            if self.verbose:
                print(f"[ИНФО] Используемые параметры: {json.dumps(options, indent=2)}")
                print(f"[ИНФО] Размер запроса: {len(prompt)} символов (~{len(prompt) // 4} токенов)")

            # Формируем запрос
            payload = {
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": options,
                "keep_alive": "5s"  # Держать модель в памяти 5 секунд
            }

            # Добавляем контекст, если он есть
            if model_name in self.context_cache:
                payload["context"] = self.context_cache[model_name]
                if self.verbose:
                    print(f"[ИНФО] Используется кэшированный контекст (id: {id(self.context_cache[model_name])})")

            url = f"{self.base_url}/api/generate"
            if self.verbose:
                print(f"[ЗАПРОС] POST {url}")
                print(
                    f"[ЗАПРОС] Параметры: {json.dumps({k: v for k, v in payload.items() if k != 'prompt' and k != 'context'}, indent=2)}")
                print(f"[ЗАПРОС] Prompt (первые 100 символов): {prompt[:100]}...")

            # Замеряем время выполнения запроса
            start_time = time.time()

            # Отправляем запрос с увеличенным таймаутом
            response = requests.post(
                url,
                json=payload,
                timeout=1200  # 20 минут на выполнение запроса
            )

            # Вычисляем время выполнения
            elapsed_time = time.time() - start_time

            if self.verbose:
                print(f"[ОТВЕТ] Статус: {response.status_code}")
                print(f"[ОТВЕТ] Заголовки: {json.dumps(dict(response.headers), indent=2)}")
                print(f"[ИНФО] Время запроса: {elapsed_time:.2f} сек.")

            if response.status_code == 200:
                result = response.json()

                # Сохраняем контекст для следующего запроса
                if "context" in result:
                    self.context_cache[model_name] = result["context"]
                    if self.verbose:
                        print(f"[ИНФО] Сохранен новый контекст (id: {id(result['context'])})")

                # Выводим статистику выполнения
                if self.verbose:
                    print("\n[СТАТИСТИКА]")
                    print(f"  Время запроса: {elapsed_time:.2f} сек.")
                    if "total_duration" in result:
                        print(f"  Общее время выполнения на сервере: {result['total_duration'] / 1e9:.2f} сек.")
                    if "load_duration" in result:
                        print(f"  Время загрузки модели: {result['load_duration'] / 1e9:.2f} сек.")
                    if "eval_count" in result and "eval_duration" in result:
                        tokens_per_sec = result['eval_count'] / (result['eval_duration'] / 1e9)
                        print(f"  Скорость генерации: {tokens_per_sec:.1f} токенов/сек")
                    if "prompt_eval_count" in result:
                        print(f"  Токенов в запросе: {result['prompt_eval_count']}")
                    if "eval_count" in result:
                        print(f"  Токенов в ответе: {result['eval_count']}")
                    print(f"  Длина ответа: {len(result.get('response', ''))} символов")
                    print("\n[ОТВЕТ] Первые 200 символов ответа:")
                    print(result.get("response", "")[:200] + "..." if len(
                        result.get("response", "")) > 200 else result.get("response", ""))

                return result.get("response", "")
            else:
                if self.verbose:
                    print(f"[ОШИБКА] Код ответа: {response.status_code}")
                    print(f"[ОШИБКА] Текст: {response.text}")
                return None

        except Exception as e:
            if self.verbose:
                print(f"[ИСКЛЮЧЕНИЕ] При генерации текста: {str(e)}")
            return None


# Пример использования с подробным выводом API-обращений
if __name__ == "__main__":
    print(f"Ollama API Client - Детальный вывод API обращений")
    print(f"=" * 80)
    print(f"Python: {sys.version}")
    print(f"Время запуска: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"=" * 80)

    client = OllamaClient(verbose=True)

    # Шаг 1: Вывод списка доступных моделей
    print("\n=== ДОСТУПНЫЕ МОДЕЛИ ===")
#    models = client.list_models()

    # Шаг 2: Генерация ответа с детальным выводом API-обмена
    print("\n=== ГЕНЕРАЦИЯ ТЕКСТА ===")
    model_name = "gemma3:27b"  # Можно заменить на любую доступную модель
    prompt = "Расскажи о себе кратко в 2-3 предложениях."
    response = client.generate_text(prompt, model_name=model_name, max_tokens=100)

    print("\n=== ВТОРОЙ ЗАПРОС (Демонстрация кэширования) ===")
    prompt = "Назови 3 интересных факта о нейросетях."
    response = client.generate_text(prompt, model_name=model_name, max_tokens=100)

    print("\n=== ГОТОВО ===")