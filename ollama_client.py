import requests
import json
import time
import re


class OllamaClient:
    """Простой клиент для работы с Ollama API"""

    def __init__(self, base_url="http://localhost:11434"):
        """Инициализирует клиент Ollama.

        Args:
            base_url: URL для Ollama API
        """
        self.base_url = base_url.rstrip('/')
        self.context_cache = {}  # Для хранения контекста между запросами

    def get_model_info(self, model_name="gemma3:27b"):
        """Получает информацию о модели из Ollama API.

        Args:
            model_name: Название модели

        Returns:
            dict: Информация о модели
        """
        try:
            # Запрос информации о модели
            url = f"{self.base_url}/api/show"

            response = requests.post(
                url,
                json={"name": model_name, "verbose": True},
                timeout=120  # Увеличенный таймаут для получения метаданных
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"Ошибка при получении информации о модели: {response.status_code}")
                print(f"Текст ошибки: {response.text}")
                return None

        except Exception as e:
            print(f"Ошибка: {str(e)}")
            return None

    def extract_context_length(self, model_info):
        """Извлекает размер контекста из информации о модели.

        Args:
            model_info: Информация о модели

        Returns:
            int: Размер контекста модели
        """
        if not model_info:
            return 8192  # Значение по умолчанию

        # Прямое получение context_length из model_info для Gemma3
        if 'model_info' in model_info and 'gemma3.context_length' in model_info['model_info']:
            context_length = int(model_info['model_info']['gemma3.context_length'])
            print(f"Найден context_length в model_info.gemma3.context_length: {context_length}")
            return context_length

        # Проверка других возможных мест
        if 'model_info' in model_info and isinstance(model_info['model_info'], dict):
            for key in model_info['model_info']:
                if key.endswith('.context_length'):
                    context_length = int(model_info['model_info'][key])
                    print(f"Найден context_length в model_info.{key}: {context_length}")
                    return context_length

        # Значение по умолчанию
        print("Не удалось определить context_length, используем значение по умолчанию: 8192")
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
            # Получаем информацию о модели
            model_info = self.get_model_info(model_name)

            # Определяем размер контекста
            context_length = self.extract_context_length(model_info)

            # Используем полученный размер контекста для настройки параметров
            options = {
                "num_ctx": context_length,
                "num_keep": context_length,  # Сохраняем полный контекст
                "temperature": temperature,
                "num_predict": max_tokens
            }

            print(f"Используемые параметры: num_ctx={context_length}, num_keep={context_length}")

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

            # Замеряем время выполнения запроса
            start_time = time.time()

            # Отправляем запрос с увеличенным таймаутом
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=1200  # 20 минут на выполнение запроса
            )

            # Вычисляем время выполнения
            elapsed_time = time.time() - start_time

            if response.status_code == 200:
                result = response.json()

                # Сохраняем контекст для следующего запроса
                if "context" in result:
                    self.context_cache[model_name] = result["context"]

                # Выводим статистику выполнения
                print(f"Запрос выполнен за {elapsed_time:.2f} сек.")
                if "total_duration" in result:
                    print(f"Общее время выполнения на сервере: {result['total_duration'] / 1e9:.2f} сек.")
                if "load_duration" in result:
                    print(f"Время загрузки модели: {result['load_duration'] / 1e9:.2f} сек.")
                if "eval_count" in result and "eval_duration" in result:
                    tokens_per_sec = result['eval_count'] / (result['eval_duration'] / 1e9)
                    print(f"Скорость генерации: {tokens_per_sec:.1f} токенов/сек")

                return result.get("response", "")
            else:
                print(f"Ошибка при запросе к API: {response.status_code}")
                print(f"Текст ошибки: {response.text}")
                return None

        except Exception as e:
            print(f"Ошибка: {str(e)}")
            return None


def print_model_info(model_info):
    """Выводит только ключевую информацию о модели (DETAILS, MODEL INFO, CAPABILITIES)."""
    if not model_info:
        print("Информация о модели недоступна")
        return

    # Details
    if "details" in model_info and isinstance(model_info["details"], dict):
        print("\nDETAILS:")
        for key, value in model_info["details"].items():
            print(f"  {key}: {value}")
        print("-" * 50)

    # Model Info
    if "model_info" in model_info and isinstance(model_info["model_info"], dict):
        print("MODEL INFO:")
        for key, value in model_info["model_info"].items():
            # Не выводим очень большие массивы
            if isinstance(value, list) and len(value) > 10:
                print(f"  {key}: [список из {len(value)} элементов]")
            else:
                print(f"  {key}: {value}")
        print("-" * 50)

    # Capabilities
    if "capabilities" in model_info and model_info["capabilities"]:
        print("CAPABILITIES:")
        for capability in model_info["capabilities"]:
            print(f"  - {capability}")
        print("-" * 50)


# Пример использования
if __name__ == "__main__":
    client = OllamaClient()

    # Получение информации о модели
    print("Получение информации о модели gemma3:27b...")
    model_info = client.get_model_info("gemma3:27b")

    if model_info:
        # Выводим только нужные секции
        print_model_info(model_info)

        # Демонстрируем извлечение размера контекста
        context_size = client.extract_context_length(model_info)
        print(f"\nОпределенный размер контекста: {context_size}")

    # Можно закомментировать или раскомментировать нужные секции для тестирования

    # Генерация текста
    print("\nГенерация текста...")
    prompt = "Расскажи о себе кратко в 2-3 предложениях. Ты модель Gemma 3 от Google."
    response = client.generate_text(prompt, model_name="gemma3:27b", max_tokens=100)
    if response:
        print("\nОтвет модели:")
        print(response)

    # Второй запрос (должен быть быстрее, если keep_alive не истек)
    print("\nВторой запрос...")
    prompt = "Напиши 3 интересных факта о нейронных сетях."
    response = client.generate_text(prompt, model_name="gemma3:27b", max_tokens=100)
    if response:
        print("\nОтвет модели:")
        print(response)

    # Третий запрос после паузы
    print("\nЖдем 6 секунд (больше чем keep_alive)...")
    time.sleep(6)
    print("Третий запрос (вероятно с перезагрузкой модели)...")
    prompt = "Объясни кратко, как работает внимание (attention) в трансформерах."
    response = client.generate_text(prompt, model_name="gemma3:27b", max_tokens=100)
    if response:
        print("\nОтвет модели:")
        print(response)