"""
Файл для выполнения семантического поиска по параметру в документах ППЭЭ,
используя прямую модель BAAI/bge-m3 без переранжирования.
"""

import os
import logging
import time
import pandas as pd
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Импорт необходимых библиотек
from langchain_community.embeddings import HuggingFaceEmbeddings  # Исправленный импорт
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.http import models
from langchain_qdrant import QdrantVectorStore

# Параметры, которые можно изменить
SEARCH_QUERY = "Идентификационный номер налогоплательщика ИНН"  # Параметр для поиска
APPLICATION_ID = "app1"  # Идентификатор заявки
QDRANT_HOST = "localhost"  # Хост Qdrant
QDRANT_PORT = 6333  # Порт Qdrant
COLLECTION_NAME = "ppee_applications_direct"  # Имя коллекции (где хранятся эмбеддинги)

# Параметры эмбеддингов
MODEL_NAME = "BAAI/bge-m3"  # Прямое использование модели через HuggingFace
DEVICE = "cuda"  # Устройство (cpu/cuda)
LIMIT = 10  # Количество результатов


class DirectSearchManager:
    """Класс для семантического поиска с прямым использованием модели эмбеддингов"""

    def __init__(
            self,
            collection_name: str = "ppee_applications_direct",
            host: str = "localhost",
            port: int = 6333,
            model_name: str = "BAAI/bge-m3",
            device: str = "cuda"
    ):
        """
        Инициализирует менеджер поиска.

        Args:
            collection_name: Имя коллекции в Qdrant
            host: Хост Qdrant
            port: Порт Qdrant
            model_name: Название модели для эмбеддингов
            device: Устройство для вычислений (cuda/cpu)
        """
        self.collection_name = collection_name
        self.host = host
        self.port = port
        self.model_name = model_name
        self.device = device

        # Инициализация клиента Qdrant
        self.client = QdrantClient(host=host, port=port)

        # Инициализация модели эмбеддингов через HuggingFace
        logger.info(f"Инициализация HuggingFace Embeddings с моделью {model_name} на устройстве {device}")
        start_time = time.time()

        self.embeddings = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={'device': device},
            encode_kwargs={'normalize_embeddings': True}
        )

        init_time = time.time() - start_time
        logger.info(f"Инициализация модели завершена за {init_time:.2f} сек")

        # Проверяем существование коллекции
        self._check_collection_exists()

        # Инициализация векторного хранилища
        self.vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=self.collection_name,
            embedding=self.embeddings
        )

    def _check_collection_exists(self):
        """Проверяет существование коллекции"""
        collections = self.client.get_collections().collections
        collection_names = [collection.name for collection in collections]

        if self.collection_name not in collection_names:
            logger.error(f"Коллекция {self.collection_name} не существует")
            raise ValueError(
                f"Коллекция {self.collection_name} не существует. Сначала выполните индексацию документов.")
        else:
            logger.info(f"Коллекция {self.collection_name} существует")

    def search(
            self,
            query: str,
            filter_dict: Optional[Dict[str, Any]] = None,
            k: int = 10
    ) -> List[Document]:
        """
        Выполняет семантический поиск в векторном хранилище.

        Args:
            query: Текст запроса
            filter_dict: Словарь для фильтрации
            k: Количество результатов

        Returns:
            List[Document]: Список найденных документов
        """
        # Предпроцессинг запроса для модели bge
        processed_query = f"query: {query}" if "bge" in self.model_name.lower() else query
        logger.info(f"Обработанный запрос: {processed_query}")

        # Форматирование фильтра для Qdrant
        filter_obj = None
        if filter_dict:
            conditions = []
            for key, value in filter_dict.items():
                conditions.append(
                    models.FieldCondition(
                        key=f"metadata.{key}",
                        match=models.MatchValue(value=value)
                    )
                )
            if conditions:
                filter_obj = models.Filter(must=conditions)

        # Выполнение поиска
        logger.info(f"Выполнение поиска с фильтром: {filter_dict}")
        search_results = self.vector_store.similarity_search_with_score(
            query=processed_query,
            filter=filter_obj,
            k=k
        )

        # Преобразование результатов с сохранением scores
        documents = []
        for doc, score in search_results:
            # Добавляем score в метаданные
            doc.metadata['score'] = float(score)
            documents.append(doc)

        logger.info(f"Найдено {len(documents)} результатов")
        return documents


def format_results_for_display(results: List[Document]) -> None:
    """
    Форматирует и выводит результаты поиска.

    Args:
        results: Список найденных документов
    """
    if not results:
        print("Информация не найдена.")
        return

    print(f"Найдено результатов: {len(results)}\n")

    # Подготовка результатов для вывода в виде таблицы
    data = []
    for i, doc in enumerate(results):
        metadata = doc.metadata
        data.append({
            "Позиция": i + 1,
            "Оценка": round(metadata.get('score', 0.0), 4),
            "Раздел": metadata.get('section', 'Не указан')[:30],
            "Тип": metadata.get('content_type', 'Неизвестно'),
            "ID документа": metadata.get('document_id', 'Н/Д')
        })

    # Вывод в виде таблицы
    df = pd.DataFrame(data)
    print(df)
    print("\n")

    # Вывод детализированных результатов
    for i, doc in enumerate(results):
        print(f"\nРезультат {i + 1}:")
        print(f"Релевантность: {doc.metadata.get('score', 0.0):.4f}")

        # Выводим полную информацию о документе
        metadata = doc.metadata
        print(f"Документ: {metadata.get('document_name', 'Н/Д')}")
        print(f"Раздел: {metadata.get('section', 'Неизвестный раздел')}")
        print(f"Тип содержимого: {metadata.get('content_type', 'Неизвестно')}")

        if 'document_id' in metadata:
            print(f"ID документа: {metadata.get('document_id')}")
        if 'chunk_index' in metadata:
            print(f"Индекс фрагмента: {metadata.get('chunk_index')}")
        if 'page_number' in metadata and metadata['page_number'] is not None:
            print(f"Номер страницы: {metadata.get('page_number')}")

        # Выводим полный текст или ограниченную его часть
        content_type = metadata.get('content_type', 'Неизвестно')
        should_truncate = content_type != "table" and len(doc.page_content) > 500

        print(f"\nТекст:")
        print("-" * 40)
        if should_truncate:
            print(doc.page_content[:497] + "...")
        else:
            print(doc.page_content)
        print("-" * 40)


def main():
    """Основная функция для выполнения семантического поиска"""
    print(f"\n{'=' * 80}")
    print(f"Прямой семантический поиск без переранжирования")
    print(f"Запрос: '{SEARCH_QUERY}'")
    print(f"Заявка: {APPLICATION_ID}")
    print(f"Модель эмбеддингов: {MODEL_NAME}")
    print(f"Устройство: {DEVICE}")
    print(f"{'=' * 80}\n")

    try:
        # Замеряем время выполнения
        start_time = time.time()

        # Инициализируем менеджер поиска
        search_manager = DirectSearchManager(
            collection_name=COLLECTION_NAME,
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            model_name=MODEL_NAME,
            device=DEVICE
        )

        # Выполняем семантический поиск
        logger.info(f"Выполнение семантического поиска для запроса: '{SEARCH_QUERY}'")
        results = search_manager.search(
            query=SEARCH_QUERY,
            filter_dict={"application_id": APPLICATION_ID},
            k=LIMIT
        )

        # Время выполнения
        search_time = time.time() - start_time
        logger.info(f"Поиск завершен за {search_time:.2f} секунд")

        # Выводим результаты
        print(f"{'=' * 80}")
        print(f"РЕЗУЛЬТАТЫ ПРЯМОГО СЕМАНТИЧЕСКОГО ПОИСКА:")
        print(f"{'=' * 80}")
        format_results_for_display(results)

        # Выводим статистику времени выполнения
        print(f"\n{'=' * 80}")
        print(f"СТАТИСТИКА ВРЕМЕНИ ВЫПОЛНЕНИЯ:")
        print(f"{'=' * 80}\n")
        print(f"Семантический поиск: {search_time:.2f} секунд")

    except Exception as e:
        print(f"Ошибка при выполнении: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()