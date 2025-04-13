"""
Файл для выполнения семантического поиска по параметру в документах ППЭЭ.
Запускается непосредственно в PyCharm.
"""

import os
import logging
from dotenv import load_dotenv
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

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
APPLICATION_ID = "app2"  # Идентификатор заявки
QDRANT_HOST = "localhost"  # Хост Qdrant
QDRANT_PORT = 6333  # Порт Qdrant
COLLECTION_NAME = "ppee_applications"  # Имя коллекции

# Параметры эмбеддингов
EMBEDDINGS_TYPE = "ollama"  # Тип эмбеддингов: "huggingface" или "ollama"
MODEL_NAME = "bge-m3"  # Модель для Ollama (версия для локального Ollama)
# MODEL_NAME = "BAAI/bge-m3"  # Альтернативная модель для HuggingFace
DEVICE = "cuda"  # Устройство (cpu/cuda) для HuggingFace
OLLAMA_URL = "http://localhost:11434"  # URL для Ollama API

LIMIT = 5  # Количество результатов


def main():
    """Основная функция для семантического поиска"""

    print(f"\n{'=' * 80}")
    print(f"Поиск: '{SEARCH_QUERY}'")
    print(f"Заявка: {APPLICATION_ID}")
    print(f"Тип эмбеддингов: {EMBEDDINGS_TYPE}")
    print(f"Модель: {MODEL_NAME}")
    print(f"{'=' * 80}\n")

    try:
        # 1. Инициализируем клиент Qdrant напрямую
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

        # 2. Инициализируем менеджер Qdrant для использования эмбеддингов
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

        # 3. Предобработка запроса для BGE моделей
        if "bge" in MODEL_NAME.lower():
            processed_query = f"query: {SEARCH_QUERY}"
        else:
            processed_query = SEARCH_QUERY

        # 4. Получаем эмбеддинг запроса
        query_embedding = qdrant_manager.embeddings.embed_query(processed_query)

        # 5. Создаем фильтр для поиска по application_id
        search_filter = Filter(
            must=[
                FieldCondition(
                    key="metadata.application_id",
                    match=MatchValue(value=APPLICATION_ID)
                )
            ]
        )

        # 6. Выполняем поиск через метод query_points, как в примере
        search_result = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            query_filter=search_filter,
            limit=LIMIT
        )

        # 7. Обрабатываем результаты
        if not search_result:
            print("Информация не найдена.")
            return

        print(f"Найдено результатов: {len(search_result)}\n")

        # 8. Подготовка результатов для вывода
        document_list = [point.payload['page_content'] for point in search_result]
        document_ids = [point.id for point in search_result]
        document_scores = [point.score for point in search_result]
        metadata_list = [point.payload.get('metadata', {}) for point in search_result]

        # 9. Вывод результатов в виде таблицы
        search_results_df = pd.DataFrame({
            "ID": document_ids,
            "Score": document_scores,
            "Section": [metadata.get('section', 'Неизвестно') for metadata in metadata_list],
            "Type": [metadata.get('content_type', 'Неизвестно') for metadata in metadata_list]
        })
        print(search_results_df)
        print()

        # 10. Вывод результатов в детальном формате
        for i, (doc, score, metadata) in enumerate(zip(document_list, document_scores, metadata_list)):
            print(f"Результат {i + 1}:")
            print(f"Релевантность: {score:.4f}")
            print(f"Раздел: {metadata.get('section', 'Неизвестный раздел')}")
            print(f"Тип содержимого: {metadata.get('content_type', 'Неизвестно')}")

            # Форматированный вывод текста
            should_truncate = metadata.get('content_type', 'Неизвестно') != "table" and len(doc) > 1000

            if should_truncate:
                print(f"Текст (сокращенно):")
                print("-" * 40)
                print(doc[:997] + "...")
            else:
                print(f"Текст:")
                print("-" * 40)
                print(doc)

            print("-" * 40)
            print()

    except Exception as e:
        print(f"Ошибка при поиске: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()