"""
Файл для выполнения семантического поиска по параметру в документах ППЭЭ.
Запускается непосредственно в PyCharm.
"""

import os
import logging
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

# Параметры, которые можно изменить
SEARCH_QUERY = "полное наименование юридического лица"  # Параметр для поиска
#SEARCH_QUERY = "ИНН"  # Параметр для поиска
APPLICATION_ID = "app1"  # Идентификатор заявки
QDRANT_HOST = "localhost"  # Хост Qdrant
QDRANT_PORT = 6333  # Порт Qdrant
COLLECTION_NAME = "ppee_applications"  # Имя коллекции

# Параметры эмбеддингов
EMBEDDINGS_TYPE = "ollama"  # Тип эмбеддингов: "huggingface" или "ollama"
MODEL_NAME = "bge-m3"  # Модель для Ollama (версия для локального Ollama)
# MODEL_NAME = "BAAI/bge-m3"  # Альтернативная модель для HuggingFace
DEVICE = "cuda"  # Устройство (cpu/cuda) для HuggingFace
OLLAMA_URL = "http://localhost:11434"  # URL для Ollama API

LIMIT = 3  # Количество результатов


def main():
    """Основная функция для семантического поиска"""

    print(f"\n{'=' * 80}")
    print(f"Поиск: '{SEARCH_QUERY}'")
    print(f"Заявка: {APPLICATION_ID}")
    print(f"Тип эмбеддингов: {EMBEDDINGS_TYPE}")
    print(f"Модель: {MODEL_NAME}")
    print(f"{'=' * 80}\n")

    try:
        # 1. Инициализируем менеджер Qdrant
        qdrant_manager = QdrantManager(
            collection_name=COLLECTION_NAME,
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            embeddings_type=EMBEDDINGS_TYPE,
            model_name=MODEL_NAME,
            device=DEVICE,
            ollama_url=OLLAMA_URL,
            create_collection=False  # Не создаем коллекцию, если она не существует
        )

        # 2. Выполняем семантический поиск
        docs = qdrant_manager.search(
            query=SEARCH_QUERY,
            filter_dict={"application_id": APPLICATION_ID},
            k=LIMIT
        )

        # 3. Выводим результаты
        if not docs:
            print("Информация не найдена.")
            return

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
            should_truncate = content_type != "table" and len(text) > 1000

            if should_truncate:
                print(f"Текст (сокращенно):")
                print("-" * 40)
                print(text[:997] + "...")
            else:
                print(f"Текст:")
                print("-" * 40)
                print(text)

            print("-" * 40)
            print()

    except Exception as e:
        print(f"Ошибка при поиске: {str(e)}")


if __name__ == "__main__":
    main()