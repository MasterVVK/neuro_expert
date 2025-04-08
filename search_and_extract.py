"""
Файл для выполнения семантического поиска по параметру в документах ППЭЭ,
с последующим извлечением конкретного значения через LLM (Gemma 3:27b).
"""

import os
import time
import logging
import json
import requests
from typing import List, Dict, Any, Optional, Tuple
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Импорт классов из нашего проекта
from ppee_analyzer.vector_store import QdrantManager
from langchain_core.documents import Document

# Параметры поиска и Qdrant
# Можно изменить запрос здесь
SEARCH_QUERY = "Краткое наименование юридического лица"  # Параметр для поиска
APPLICATION_ID = "app1"  # Идентификатор заявки
QDRANT_HOST = "localhost"  # Хост Qdrant
QDRANT_PORT = 6333  # Порт Qdrant
COLLECTION_NAME = "ppee_applications"  # Имя коллекции

# Параметры эмбеддингов
EMBEDDINGS_TYPE = "ollama"  # Тип эмбеддингов: "huggingface" или "ollama"
EMBEDDINGS_MODEL = "bge-m3"  # Модель для Ollama
DEVICE = "cuda"  # Устройство (cpu/cuda) для HuggingFace
OLLAMA_URL = "http://localhost:11434"  # URL для Ollama API

# Параметры LLM
LLM_MODEL = "gemma3:27b"  # Модель LLM для анализа
LIMIT = 3  # Количество результатов для поиска


# Для извлечения значений используем только LLM


def semantic_search(query: str) -> List[Document]:
    """
    Выполняет семантический поиск по параметру в Qdrant.

    Args:
        query: Поисковый запрос

    Returns:
        List[Document]: Список найденных документов
    """
    logger.info(f"Выполнение семантического поиска для запроса: '{query}'")

    try:
        # Инициализируем менеджер Qdrant
        qdrant_manager = QdrantManager(
            collection_name=COLLECTION_NAME,
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            embeddings_type=EMBEDDINGS_TYPE,
            model_name=EMBEDDINGS_MODEL,
            device=DEVICE,
            ollama_url=OLLAMA_URL,
            create_collection=False  # Не создаем коллекцию, если она не существует
        )

        # Выполняем семантический поиск
        docs = qdrant_manager.search(
            query=query,
            filter_dict={"application_id": APPLICATION_ID},
            k=LIMIT
        )

        logger.info(f"Найдено {len(docs)} документов")
        return docs

    except Exception as e:
        logger.error(f"Ошибка при поиске: {str(e)}")
        return []


def format_search_results(docs: List[Document]) -> str:
    """
    Форматирует результаты поиска для передачи в LLM.

    Args:
        docs: Список найденных документов

    Returns:
        str: Форматированный текст с результатами
    """
    if not docs:
        return "Информация не найдена."

    results = []

    for i, doc in enumerate(docs):
        section = doc.metadata.get('section', 'Неизвестный раздел')
        content_type = doc.metadata.get('content_type', 'Неизвестно')
        text = doc.page_content

        result = f"Результат {i + 1}:\n"
        result += f"Раздел: {section}\n"
        result += f"Тип содержимого: {content_type}\n"
        result += f"Текст:\n{text}\n"
        result += "-" * 40 + "\n"

        results.append(result)

    return "\n".join(results)


def extract_with_llm(query: str, formatted_results: str) -> Tuple[str, str]:
    """
    Отправляет запрос к LLM через Ollama для извлечения конкретного значения.

    Args:
        query: Исходный поисковый запрос
        formatted_results: Форматированные результаты поиска

    Returns:
        Tuple[str, str]: Кортеж (параметр, значение)
    """
    logger.info(f"Отправка запроса к LLM для извлечения значения параметра")

    try:
        # Формируем промпт для LLM
        prompt = f"""Ты эксперт по анализу документов программы повышения экологической эффективности (ППЭЭ).

Мы выполнили поиск по параметру: "{query}"

Найденные результаты:
{formatted_results}

Твоя задача - извлечь точное значение для параметра "{query}" из предоставленных документов.

Результат представь СТРОГО в формате:
{query}: [значение]

Правила:
1. Если значение найдено в нескольких местах, выбери наиболее полное и точное.
2. Если значение в таблице, внимательно определи соответствие между строкой и нужным столбцом.
3. Не добавляй никаких комментариев, рассуждений или пояснений - только параметр и его значение.
4. Если параметр не найден, укажи: "{query}: информация не найдена".

Ответь одной строкой в указанном формате."""

        # Формируем запрос к Ollama API
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": LLM_MODEL,
                "prompt": prompt,
                "stream": False,
                "temperature": 0.1,  # Очень низкая температура для точности
                "max_tokens": 250  # Ограничиваем длину ответа
            },
            timeout=120
        )

        response.raise_for_status()
        result = response.json()
        llm_response = result.get("response", "Нет ответа от модели").strip()

        # Разбираем ответ на параметр и значение
        try:
            parameter, value = llm_response.split(":", 1)
            return parameter.strip(), value.strip()
        except ValueError:
            # Если не удалось разделить по двоеточию
            return query, llm_response

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при запросе к LLM: {str(e)}")
        return query, f"Ошибка при запросе к LLM: {str(e)}"


def main():
    """Основная функция для поиска и извлечения значения параметра"""
    start_time = time.time()

    print(f"\n{'=' * 80}")
    print(f"Поиск и извлечение значения параметра: '{SEARCH_QUERY}'")
    print(f"Заявка: {APPLICATION_ID}")
    print(f"Модель эмбеддингов: {EMBEDDINGS_MODEL}")
    print(f"Модель LLM: {LLM_MODEL}")
    print(f"{'=' * 80}\n")

    try:
        # 1. Выполняем семантический поиск
        docs = semantic_search(SEARCH_QUERY)

        if not docs:
            print("Информация не найдена.")
            return

        # 2. Выводим результаты поиска
        print(f"Найдено результатов: {len(docs)}\n")

        for i, doc in enumerate(docs):
            print(f"Результат {i + 1}:")
            print(f"Раздел: {doc.metadata.get('section', 'Неизвестный раздел')}")

            # Получаем тип содержимого
            content_type = doc.metadata.get('content_type', 'Неизвестно')
            print(f"Тип содержимого: {content_type}")

            # Форматированный вывод текста
            text = doc.page_content

            # Для таблиц выводим полный текст, для остального - можем обрезать
            should_truncate = content_type != "table" and len(text) > 500

            if should_truncate:
                print(f"Текст (сокращенно):")
                print("-" * 40)
                print(text[:497] + "...")
            else:
                print(f"Текст:")
                print("-" * 40)
                print(text)

            print("-" * 40)
            print()

        # 3. Форматируем результаты для LLM
        formatted_results = format_search_results(docs)

        # 4. Отправляем на извлечение в LLM
        print("Отправка запроса к LLM для извлечения значения параметра...\n")
        parameter, value = extract_with_llm(SEARCH_QUERY, formatted_results)

        # 5. Выводим результат
        print(f"\n{'=' * 80}")
        print("РЕЗУЛЬТАТ ИЗВЛЕЧЕНИЯ:")
        print(f"{'=' * 80}\n")
        print(f"{parameter}: {value}")

        # 6. Выводим статистику выполнения
        elapsed_time = time.time() - start_time
        print(f"\n{'=' * 80}")
        print(f"Выполнение завершено за {elapsed_time:.2f} секунд")
        print(f"{'=' * 80}\n")

    except Exception as e:
        print(f"Ошибка при выполнении: {str(e)}")


if __name__ == "__main__":
    main()