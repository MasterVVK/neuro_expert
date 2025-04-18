"""
Файл для загрузки документа ППЭЭ в векторную базу данных Qdrant,
используя модель BAAI/bge-m3 напрямую через HuggingFace.
"""

import os
import logging
import time
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

# Импорт классов из нашего проекта
from ppee_analyzer.document_processor import PPEEDocumentSplitter

# Параметры, которые можно изменить
FILE_PATH = "data/ППЭЭ итог ЖУЛЕБИНО_21.06.2024 (2).md"  # Путь к файлу документа
APPLICATION_ID = "app1"  # Идентификатор заявки
QDRANT_HOST = "localhost"  # Хост Qdrant
QDRANT_PORT = 6333  # Порт Qdrant
COLLECTION_NAME = "ppee_applications_direct"  # Имя коллекции (отличное от стандартной)

# Параметры эмбеддингов
MODEL_NAME = "BAAI/bge-m3"  # Прямое использование модели через HuggingFace
DEVICE = "cuda"  # Устройство (cpu/cuda)
VECTOR_SIZE = 1024  # Размерность векторов для bge-m3


class DirectEmbeddingsManager:
    """Класс для работы с эмбеддингами через HuggingFace напрямую"""

    def __init__(
        self,
        collection_name: str = "ppee_applications_direct",
        host: str = "localhost",
        port: int = 6333,
        model_name: str = "BAAI/bge-m3",
        vector_size: int = 1024,
        device: str = "cuda",
    ):
        """
        Инициализирует менеджер эмбеддингов.

        Args:
            collection_name: Имя коллекции в Qdrant
            host: Хост Qdrant
            port: Порт Qdrant
            model_name: Название модели для эмбеддингов
            vector_size: Размерность векторов
            device: Устройство для вычислений (cuda/cpu)
        """
        self.collection_name = collection_name
        self.host = host
        self.port = port
        self.model_name = model_name
        self.vector_size = vector_size
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

        # Проверяем существование коллекции и создаем при необходимости
        self._ensure_collection_exists()

        # Инициализация векторного хранилища
        self.vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=self.collection_name,
            embedding=self.embeddings
        )

    def _ensure_collection_exists(self):
        """Проверяет существование коллекции и создает при необходимости"""
        collections = self.client.get_collections().collections
        collection_names = [collection.name for collection in collections]

        if self.collection_name not in collection_names:
            logger.info(f"Создание коллекции {self.collection_name}")
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE
                )
            )
            logger.info(f"Коллекция {self.collection_name} успешно создана")

            # Создаем индексы для ускорения фильтрации
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="metadata.application_id",
                field_schema="keyword"
            )
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="metadata.content_type",
                field_schema="keyword"
            )
        else:
            logger.info(f"Коллекция {self.collection_name} уже существует")

    def add_documents(self, documents: List[Document], batch_size: int = 32) -> int:
        """
        Добавляет документы в векторное хранилище.

        Args:
            documents: Список документов для добавления
            batch_size: Размер партии для индексации

        Returns:
            int: Количество добавленных документов
        """
        total_documents = len(documents)
        logger.info(f"Индексация {total_documents} документов")

        # Добавляем документы пакетами для оптимизации
        for i in range(0, total_documents, batch_size):
            end_idx = min(i + batch_size, total_documents)
            batch = documents[i:end_idx]

            logger.info(f"Индексация партии {i+1}-{end_idx} из {total_documents}")
            start_time = time.time()

            self.vector_store.add_documents(batch)

            batch_time = time.time() - start_time
            logger.info(f"Партия обработана за {batch_time:.2f} сек")

        logger.info(f"Индексация завершена. Добавлено {total_documents} документов")
        return total_documents

    def search(
            self,
            query: str,
            filter_dict: Optional[Dict[str, Any]] = None,
            k: int = 3
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

        return documents

    def get_application_ids(self) -> List[str]:
        """
        Получает список ID заявок в хранилище.

        Returns:
            List[str]: Список ID заявок
        """
        response = self.client.scroll(
            collection_name=self.collection_name,
            limit=1000,
            with_payload=["metadata.application_id"],
            with_vectors=False
        )

        application_ids = set()
        for point in response[0]:
            if "metadata" in point.payload and "application_id" in point.payload["metadata"]:
                application_ids.add(point.payload["metadata"]["application_id"])

        return list(application_ids)

    def delete_application(self, application_id: str) -> int:
        """
        Удаляет заявку из хранилища.

        Args:
            application_id: ID заявки

        Returns:
            int: Количество удаленных точек
        """
        # Находим все точки, связанные с данной заявкой
        response = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.application_id",
                        match=models.MatchValue(value=application_id)
                    )
                ]
            ),
            limit=10000,
            with_payload=False,
            with_vectors=False
        )

        # Получаем ID точек для удаления
        points_to_delete = [point.id for point in response[0]]

        if points_to_delete:
            # Удаляем точки
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(
                    points=points_to_delete
                )
            )
            logger.info(f"Удалено {len(points_to_delete)} точек для заявки {application_id}")
            return len(points_to_delete)

        logger.info(f"Не найдено точек для заявки {application_id}")
        return 0

    def get_stats(self, application_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Получает статистику по хранилищу.

        Args:
            application_id: ID заявки для фильтрации (None - по всем заявкам)

        Returns:
            Dict[str, Any]: Статистика
        """
        # Настраиваем фильтр, если указан application_id
        scroll_filter = None
        if application_id:
            scroll_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.application_id",
                        match=models.MatchValue(value=application_id)
                    )
                ]
            )

        # Запрашиваем данные из Qdrant
        response = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=10000,  # Ограничение на количество результатов
            with_payload=["metadata"],
            with_vectors=False
        )

        # Анализируем результаты
        points = response[0]

        # Статистика по типам документов
        content_types = {}
        applications = set()
        documents = set()
        sections = set()

        for point in points:
            if "metadata" in point.payload:
                metadata = point.payload["metadata"]

                # Тип контента
                content_type = metadata.get("content_type", "unknown")
                content_types[content_type] = content_types.get(content_type, 0) + 1

                # Приложения и документы
                if "application_id" in metadata:
                    applications.add(metadata["application_id"])
                if "document_id" in metadata:
                    documents.add(metadata["document_id"])
                if "section" in metadata:
                    sections.add(metadata["section"])

        return {
            "total_points": len(points),
            "content_types": content_types,
            "applications_count": len(applications),
            "documents_count": len(documents),
            "sections_count": len(sections),
            "applications": list(applications),
            "documents": list(documents)
        }


def main():
    """Основная функция для загрузки документа в Qdrant"""

    print(f"Загрузка документа {FILE_PATH} в Qdrant с использованием прямой модели...")
    print(f"Используемая модель эмбеддингов: {MODEL_NAME}")
    print(f"Устройство: {DEVICE}")

    try:
        # Замеряем время выполнения
        start_time = time.time()

        # 1. Инициализируем разделитель документов
        splitter = PPEEDocumentSplitter()

        # 2. Загружаем и разделяем документ
        logger.info(f"Загрузка и разделение документа {FILE_PATH}")
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

        # 3. Инициализируем менеджер эмбеддингов
        logger.info(f"Инициализация эмбеддингов с моделью {MODEL_NAME}")
        embedding_manager = DirectEmbeddingsManager(
            collection_name=COLLECTION_NAME,
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            model_name=MODEL_NAME,
            device=DEVICE
        )

        # 4. Добавляем фрагменты в векторную базу данных
        logger.info(f"Начало индексации {len(chunks)} фрагментов")
        indexed_count = embedding_manager.add_documents(chunks)

        # Общее время выполнения
        total_time = time.time() - start_time

        print(f"\nДокумент успешно загружен в Qdrant")
        print(f"  - Проиндексировано фрагментов: {indexed_count}")
        print(f"  - Коллекция: {COLLECTION_NAME}")
        print(f"  - Идентификатор заявки: {APPLICATION_ID}")
        print(f"  - Модель: {MODEL_NAME}")
        print(f"  - Устройство: {DEVICE}")
        print(f"  - Время выполнения: {total_time:.2f} сек")

    except Exception as e:
        print(f"Ошибка при загрузке документа: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()