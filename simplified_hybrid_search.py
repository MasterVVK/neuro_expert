"""
simplified_hybrid_search.py - Скрипт для тестирования гибридного поиска в Qdrant
с автоматическим выбором типа поиска на основе длины запроса
"""

import os
import sys
import time
import logging
from typing import List, Dict, Any, Optional
import argparse

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Добавляем путь к проекту, чтобы можно было импортировать модули
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Импортируем необходимые компоненты из проекта
try:
    from ppee_analyzer.vector_store import QdrantManager, OllamaEmbeddings
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    from langchain_core.documents import Document
except ImportError as e:
    logger.error(f"Ошибка импорта модулей: {e}")
    logger.error("Убедитесь, что вы запускаете скрипт из корректного окружения и все зависимости установлены")
    sys.exit(1)


class SimpleSearchTester:
    """Класс для тестирования упрощенного гибридного поиска в Qdrant"""

    def __init__(
            self,
            host: str = "localhost",
            port: int = 6333,
            collection_name: str = "ppee_applications",
            embeddings_model: str = "bge-m3",
            ollama_url: str = "http://localhost:11434",
            hybrid_threshold: int = 10  # Порог для выбора гибридного поиска
    ):
        """
        Инициализирует тестер поиска.

        Args:
            host: Хост Qdrant
            port: Порт Qdrant
            collection_name: Имя коллекции в Qdrant
            embeddings_model: Модель для эмбеддингов
            ollama_url: URL для Ollama API
            hybrid_threshold: Пороговая длина запроса для выбора гибридного поиска
        """
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.embeddings_model = embeddings_model
        self.ollama_url = ollama_url
        self.hybrid_threshold = hybrid_threshold

        # Инициализируем клиент Qdrant
        logger.info(f"Подключение к Qdrant на {host}:{port}, коллекция {collection_name}")
        self.client = QdrantClient(host=host, port=port)

        # Проверяем существование коллекции
        try:
            collection_info = self.client.get_collection(collection_name=collection_name)
            logger.info(f"Найдена коллекция {collection_name}: {collection_info.points_count} точек")
        except Exception as e:
            logger.error(f"Ошибка при проверке коллекции: {str(e)}")
            sys.exit(1)

        # Проверяем наличие полнотекстового индекса
        self._check_text_index()

        # Инициализируем эмбеддинги
        logger.info(f"Инициализация эмбеддингов с моделью {embeddings_model}")
        self.embeddings = OllamaEmbeddings(
            model_name=embeddings_model,
            base_url=ollama_url,
            normalize_embeddings=True
        )

        # Инициализируем QdrantManager
        self.qdrant_manager = QdrantManager(
            collection_name=collection_name,
            host=host,
            port=port,
            embeddings_type="ollama",
            model_name=embeddings_model,
            ollama_url=ollama_url
        )

    def _check_text_index(self):
        """Проверяет наличие полнотекстового индекса для page_content"""
        try:
            # Проверяем, существует ли уже индекс
            collection_info = self.client.get_collection(collection_name=self.collection_name)

            # Проверяем текущие индексы
            if hasattr(collection_info,
                       'payload_schema') and collection_info.payload_schema and 'page_content' in collection_info.payload_schema:
                logger.info("Полнотекстовый индекс уже существует")
                return True

            logger.info("Полнотекстовый индекс не найден")
            return False

        except Exception as e:
            logger.warning(f"Ошибка при проверке индекса: {str(e)}")
            return False

    def get_application_ids(self) -> List[str]:
        """
        Получает список доступных ID заявок в коллекции.

        Returns:
            List[str]: Список ID заявок
        """
        try:
            # Используем метод из QdrantManager
            application_ids = self.qdrant_manager.get_application_ids()
            logger.info(f"Найдено {len(application_ids)} заявок в коллекции")
            return application_ids
        except Exception as e:
            logger.error(f"Ошибка при получении списка заявок: {str(e)}")
            return []

    def vector_search(
            self,
            application_id: str,
            query: str,
            k: int = 5
    ) -> List[Document]:
        """
        Выполняет векторный поиск.

        Args:
            application_id: ID заявки
            query: Поисковый запрос
            k: Количество результатов

        Returns:
            List[Document]: Результаты поиска
        """
        logger.info(f"Выполнение векторного поиска: '{query}' для заявки {application_id}")

        # Предпроцессинг запроса для модели bge
        processed_query = f"query: {query}" if "bge" in self.embeddings_model.lower() else query

        # Создаем фильтр для заявки
        filter_obj = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.application_id",
                    match=models.MatchValue(value=application_id)
                )
            ]
        )

        try:
            start_time = time.time()

            query_vector = self.embeddings.embed_query(processed_query)

            # Используем search для совместимости
            search_result = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=filter_obj,
                limit=k
            )

            elapsed_time = time.time() - start_time
            logger.info(
                f"Векторный поиск выполнен за {elapsed_time:.2f} сек., найдено {len(search_result)} результатов")

            # Преобразуем результаты
            documents = []
            for scored_point in search_result:
                metadata = scored_point.payload.get("metadata", {})
                text = scored_point.payload.get("page_content", "")
                metadata['score'] = float(scored_point.score)
                metadata['search_type'] = 'vector'

                doc = Document(page_content=text, metadata=metadata)
                documents.append(doc)

            return documents
        except Exception as e:
            logger.error(f"Ошибка при выполнении векторного поиска: {str(e)}")
            return []

    def text_search(
            self,
            application_id: str,
            query: str,
            k: int = 5
    ) -> List[Document]:
        """
        Выполняет текстовый поиск.

        Args:
            application_id: ID заявки
            query: Поисковый запрос
            k: Количество результатов

        Returns:
            List[Document]: Результаты поиска
        """
        logger.info(f"Выполнение текстового поиска: '{query}' для заявки {application_id}")

        try:
            start_time = time.time()

            # Создаем комбинированный фильтр для заявки и текстового поиска
            combined_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.application_id",
                        match=models.MatchValue(value=application_id)
                    ),
                    models.FieldCondition(
                        key="page_content",
                        match=models.MatchText(text=query)
                    )
                ]
            )

            # Получаем результаты через scroll
            results = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=combined_filter,
                limit=k,
                with_payload=True,
                with_vectors=False
            )[0]

            elapsed_time = time.time() - start_time
            logger.info(f"Текстовый поиск выполнен за {elapsed_time:.2f} сек., найдено {len(results)} результатов")

            # Преобразуем результаты в формат Document
            documents = []
            for i, point in enumerate(results):
                metadata = point.payload.get("metadata", {})
                text = point.payload.get("page_content", "")

                # Для результатов scroll нет score, добавляем искусственную оценку
                # (более ранние результаты имеют более высокую оценку)
                score = 1.0 - (i * 0.05)
                if score < 0.1:
                    score = 0.1

                # Добавляем информацию о поиске в метаданные
                metadata['score'] = score
                metadata['search_type'] = 'text'

                # Создаем Document
                doc = Document(page_content=text, metadata=metadata)
                documents.append(doc)

            return documents
        except Exception as e:
            logger.error(f"Ошибка при выполнении текстового поиска: {str(e)}")
            return []

    def hybrid_search(
            self,
            application_id: str,
            query: str,
            k: int = 5,
            vector_weight: float = 0.5,
            text_weight: float = 0.5
    ) -> List[Document]:
        """
        Выполняет гибридный поиск, объединяя результаты
        векторного и текстового поиска.

        Args:
            application_id: ID заявки
            query: Поисковый запрос
            k: Количество результатов
            vector_weight: Вес векторного поиска (от 0 до 1)
            text_weight: Вес текстового поиска (от 0 до 1)

        Returns:
            List[Document]: Результаты поиска
        """
        logger.info(f"Выполнение гибридного поиска: '{query}' для заявки {application_id} "
                    f"(вес вектора: {vector_weight}, вес текста: {text_weight})")

        try:
            start_time = time.time()

            # Получаем результаты векторного поиска
            vector_results = self.vector_search(application_id, query, k * 2)

            # Получаем результаты текстового поиска
            text_results = self.text_search(application_id, query, k * 2)

            # Объединяем результаты
            combined_results = self._combine_results(vector_results, text_results, vector_weight, text_weight, k)

            elapsed_time = time.time() - start_time
            logger.info(
                f"Гибридный поиск выполнен за {elapsed_time:.2f} сек., найдено {len(combined_results)} результатов")

            return combined_results

        except Exception as e:
            logger.error(f"Ошибка при выполнении гибридного поиска: {str(e)}")
            return []

    def _combine_results(
            self,
            vector_results: List[Document],
            text_results: List[Document],
            vector_weight: float,
            text_weight: float,
            k: int
    ) -> List[Document]:
        """
        Объединяет результаты векторного и текстового поиска.

        Args:
            vector_results: Результаты векторного поиска
            text_results: Результаты текстового поиска
            vector_weight: Вес векторного поиска
            text_weight: Вес текстового поиска
            k: Максимальное количество результатов

        Returns:
            List[Document]: Объединенные результаты
        """
        # Нормализуем веса
        total_weight = vector_weight + text_weight
        vector_weight = vector_weight / total_weight
        text_weight = text_weight / total_weight

        # Создаем словарь для хранения объединенных результатов
        results_dict = {}

        # Добавляем результаты векторного поиска
        for doc in vector_results:
            doc_key = self._get_document_key(doc)
            score = doc.metadata.get('score', 0.0) * vector_weight

            results_dict[doc_key] = {
                'doc': doc,
                'score': score,
                'search_type': 'hybrid'
            }

        # Добавляем или объединяем результаты текстового поиска
        for doc in text_results:
            doc_key = self._get_document_key(doc)
            text_score = doc.metadata.get('score', 0.0) * text_weight

            if doc_key in results_dict:
                # Если документ уже есть, обновляем оценку
                results_dict[doc_key]['score'] += text_score
                results_dict[doc_key]['search_type'] = 'hybrid'
            else:
                # Иначе добавляем новый документ
                results_dict[doc_key] = {
                    'doc': doc,
                    'score': text_score,
                    'search_type': 'hybrid'
                }

        # Сортируем результаты по оценке и ограничиваем количество
        sorted_results = sorted(results_dict.values(), key=lambda x: x['score'], reverse=True)[:k]

        # Преобразуем обратно в документы
        result_docs = []
        for item in sorted_results:
            doc = item['doc']
            doc.metadata['score'] = item['score']
            doc.metadata['search_type'] = item['search_type']
            result_docs.append(doc)

        return result_docs

    def _get_document_key(self, doc: Document) -> str:
        """
        Создает уникальный ключ для документа на основе его метаданных.

        Args:
            doc: Документ

        Returns:
            str: Уникальный ключ
        """
        metadata = doc.metadata

        # Создаем составной ключ из доступных метаданных
        doc_id_parts = []

        # Добавляем основные идентификаторы
        if 'document_id' in metadata:
            doc_id_parts.append(f"doc:{metadata['document_id']}")

        if 'chunk_index' in metadata:
            doc_id_parts.append(f"chunk:{metadata['chunk_index']}")

        if 'page_number' in metadata:
            doc_id_parts.append(f"page:{metadata['page_number']}")

        # Если есть хотя бы одна часть, создаем идентификатор
        if doc_id_parts:
            return "|".join(doc_id_parts)

        # В крайнем случае используем хеш текста
        return str(hash(doc.page_content))

    def search(
            self,
            application_id: str,
            query: str,
            k: int = 5,
            vector_weight: float = 0.5,
            text_weight: float = 0.5
    ):
        """
        Выполняет поиск в зависимости от длины запроса:
        - Если длина запроса < hybrid_threshold, используется гибридный поиск
        - Иначе только векторный поиск

        Args:
            application_id: ID заявки
            query: Поисковый запрос
            k: Количество результатов
            vector_weight: Вес векторного поиска для гибридного поиска
            text_weight: Вес текстового поиска для гибридного поиска

        Returns:
            List[Document]: Результаты поиска
        """
        # Выбираем стратегию поиска на основе длины запроса
        if len(query) < self.hybrid_threshold:
            logger.info(f"Запрос '{query}' короче {self.hybrid_threshold} символов, используем гибридный поиск")
            return self.hybrid_search(application_id, query, k, vector_weight, text_weight)
        else:
            logger.info(f"Запрос '{query}' длиннее {self.hybrid_threshold} символов, используем векторный поиск")
            return self.vector_search(application_id, query, k)

    def print_results(self, results: List[Document], result_type: str = "поиска"):
        """
        Выводит результаты поиска в консоль.

        Args:
            results: Результаты поиска
            result_type: Тип результатов для отображения
        """
        logger.info("-" * 80)
        logger.info(f"Результаты {result_type} ({len(results)}):")

        if not results:
            logger.info("Ничего не найдено")
            return

        for i, doc in enumerate(results):
            score = doc.metadata.get('score', 0.0)
            content_type = doc.metadata.get('content_type', 'unknown')
            section = doc.metadata.get('section', 'unknown')
            search_type = doc.metadata.get('search_type', 'unknown')

            logger.info(f"{i + 1}. Оценка: {score:.4f}, Раздел: {section}, Тип: {content_type}, Метод: {search_type}")
            # Ограничиваем длину текста для вывода
            display_text = doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
            logger.info(f"   Текст: {display_text}")


if __name__ == "__main__":
    # Создаем парсер аргументов командной строки
    parser = argparse.ArgumentParser(description='Упрощенный гибридный поиск в Qdrant')

    parser.add_argument('--host', type=str, default='localhost',
                        help='Хост Qdrant сервера (по умолчанию: localhost)')
    parser.add_argument('--port', type=int, default=6333,
                        help='Порт Qdrant сервера (по умолчанию: 6333)')
    parser.add_argument('--collection', type=str, default='ppee_applications',
                        help='Имя коллекции в Qdrant (по умолчанию: ppee_applications)')
    parser.add_argument('--application_id', type=str, required=True,
                        help='ID заявки для поиска (укажите "list" для просмотра доступных ID)')
    parser.add_argument('--model', type=str, default='bge-m3',
                        help='Модель для эмбеддингов (по умолчанию: bge-m3)')
    parser.add_argument('--ollama_url', type=str, default='http://localhost:11434',
                        help='URL для Ollama API (по умолчанию: http://localhost:11434)')
    parser.add_argument('--limit', type=int, default=5,
                        help='Количество результатов поиска (по умолчанию: 5)')
    parser.add_argument('--threshold', type=int, default=10,
                        help='Пороговая длина запроса для гибридного поиска (по умолчанию: 10)')
    parser.add_argument('--query', type=str, required=True,
                        help='Поисковый запрос')

    args = parser.parse_args()

    # Создаем экземпляр тестера
    tester = SimpleSearchTester(
        host=args.host,
        port=args.port,
        collection_name=args.collection,
        embeddings_model=args.model,
        ollama_url=args.ollama_url,
        hybrid_threshold=args.threshold
    )

    # Если указан application_id = 'list', выводим список доступных
    if args.application_id == 'list':
        app_ids = tester.get_application_ids()
        if app_ids:
            logger.info("Доступные ID заявок:")
            for app_id in app_ids:
                logger.info(f"- {app_id}")
        else:
            logger.info("Не найдено доступных заявок в коллекции")
        sys.exit(0)

    # Выполняем поиск с автоматическим выбором стратегии
    results = tester.search(
        application_id=args.application_id,
        query=args.query,
        k=args.limit
    )

    # Выводим результаты
    tester.print_results(results, "автоматического поиска")