"""
Файл для загрузки документа ППЭЭ в векторную базу данных Qdrant.
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
from ppee_analyzer.document_processor import PPEEDocumentSplitter
from ppee_analyzer.vector_store import QdrantManager

# Параметры, которые можно изменить
FILE_PATH = "data/Очищенная ППЭЭ (с масками) итог.md"  # Путь к файлу документа
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


def main():
    """Основная функция для загрузки документа в Qdrant"""

    print(f"Загрузка документа {FILE_PATH} в Qdrant...")
    print(f"Используемый тип эмбеддингов: {EMBEDDINGS_TYPE}")
    print(f"Модель: {MODEL_NAME}")

    try:
        # 1. Инициализируем разделитель документов
        splitter = PPEEDocumentSplitter()

        # 2. Загружаем и разделяем документ
        chunks = splitter.load_and_process_file(FILE_PATH, APPLICATION_ID)
        print(f"Документ разделен на {len(chunks)} фрагментов")

        # Статистика по типам фрагментов
        content_types = {}
        for chunk in chunks:
            content_type = chunk.metadata["content_type"]
            content_types[content_type] = content_types.get(content_type, 0) + 1

        print("\nСтатистика по типам фрагментов:")
        for content_type, count in content_types.items():
            print(f"  - {content_type}: {count}")

        # 3. Инициализируем менеджер Qdrant
        qdrant_manager = QdrantManager(
            collection_name=COLLECTION_NAME,
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            embeddings_type=EMBEDDINGS_TYPE,
            model_name=MODEL_NAME,
            device=DEVICE,
            ollama_url=OLLAMA_URL
        )

        # 4. Добавляем фрагменты в векторную базу данных
        indexed_count = qdrant_manager.add_documents(chunks)

        print(f"\nДокумент успешно загружен в Qdrant")
        print(f"  - Проиндексировано фрагментов: {indexed_count}")
        print(f"  - Коллекция: {COLLECTION_NAME}")
        print(f"  - Идентификатор заявки: {APPLICATION_ID}")
        print(f"  - Тип эмбеддингов: {EMBEDDINGS_TYPE}")
        print(f"  - Модель: {MODEL_NAME}")

    except Exception as e:
        print(f"Ошибка при загрузке документа: {str(e)}")


if __name__ == "__main__":
    main()