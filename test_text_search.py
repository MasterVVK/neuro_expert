"""
test_text_search.py - Скрипт для тестирования текстового поиска в Qdrant
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
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    from langchain_core.documents import Document
except ImportError as e:
    logger.error(f"Ошибка импорта модулей: {e}")
    logger.error("Убедитесь, что вы запускаете скрипт из корректного окружения и все зависимости установлены")
    sys.exit(1)


class TextSearchTester:
    """Класс для тестирования текстового поиска в Qdrant"""

    def __init__(
            self,
            host: str = "localhost",
            port: int = 6333,
            collection_name: str = "ppee_applications"
    ):
        """
        Инициализирует тестер текстового поиска.

        Args:
            host: Хост Qdrant
            port: Порт Qdrant
            collection_name: Имя коллекции в Qdrant
        """
        self.host = host
        self.port = port
        self.collection_name = collection_name

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

        # Проверяем и создаем текстовый индекс, если его нет
        self._ensure_text_index()

    def _ensure_text_index(self):
        """Проверяет и при необходимости создает полнотекстовый индекс для page_content"""
        try:
            # Проверяем, существует ли уже индекс
            collection_info = self.client.get_collection(collection_name=self.collection_name)

            # Проверяем текущие индексы
            if hasattr(collection_info,
                       'payload_schema') and collection_info.payload_schema and 'page_content' in collection_info.payload_schema:
                logger.info("Полнотекстовый индекс уже существует")
                return True

            # Если индекса нет, создаем его
            logger.info("Создание полнотекстового индекса для page_content...")

            # Используем правильный API для создания текстового индекса
            try:
                # Пытаемся использовать текстовые параметры, если доступны
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="page_content",
                    field_schema=models.TextIndexParams(
                        type="text",
                        tokenizer=models.TokenizerType.WORD,
                        min_token_len=2,
                        max_token_len=15,
                        lowercase=True
                    )
                )
            except Exception as e1:
                logger.warning(f"Не удалось создать индекс с TextIndexParams: {e1}")
                # Более простой вариант, если предыдущий не работает
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="page_content",
                    field_schema="text"
                )

            logger.info("Полнотекстовый индекс создан")
            return True
        except Exception as e:
            logger.warning(f"Ошибка при создании индекса: {str(e)}")
            return False

    def get_application_ids(self) -> List[str]:
        """
        Получает список доступных ID заявок в коллекции.

        Returns:
            List[str]: Список ID заявок
        """
        try:
            # Выполняем scroll запрос для получения уникальных application_id
            response = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                with_payload=["metadata.application_id"],
                with_vectors=False
            )

            points = response[0]
            application_ids = set()

            for point in points:
                if (point.payload and
                        "metadata" in point.payload and
                        "application_id" in point.payload["metadata"]):
                    application_ids.add(point.payload["metadata"]["application_id"])

            logger.info(f"Найдено {len(application_ids)} заявок в коллекции")
            return list(application_ids)
        except Exception as e:
            logger.error(f"Ошибка при получении списка заявок: {str(e)}")
            return []

    def perform_text_search(
            self,
            application_id: str,
            query: str,
            k: int = 5
    ) -> List[Dict]:
        """
        Выполняет текстовый поиск.

        Args:
            application_id: ID заявки
            query: Поисковый запрос
            k: Количество результатов

        Returns:
            List[Dict]: Результаты поиска
        """
        logger.info(f"Выполнение текстового поиска: '{query}' для заявки {application_id}")

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

            # Пробуем использовать text_key в scroll запросе (в новейших версиях API)
            try:
                # Вариант 1: Используем scroll с text_key
                results = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=filter_obj,
                    limit=k,
                    with_payload=True,
                    with_vectors=False,
                    text_key=query
                )[0]
                search_mode = "scroll с text_key"
            except Exception as e1:
                logger.warning(f"Метод scroll с text_key не сработал: {str(e1)}")

                # Вариант 2: Используем payload_keyword_filter
                try:
                    keyword_filter = models.FieldCondition(
                        key="page_content",
                        match=models.MatchText(text=query)
                    )

                    # Добавляем фильтр по ключевому слову к основному фильтру
                    combined_filter = models.Filter(
                        must=[
                            models.FieldCondition(
                                key="metadata.application_id",
                                match=models.MatchValue(value=application_id)
                            ),
                            keyword_filter
                        ]
                    )

                    results = self.client.scroll(
                        collection_name=self.collection_name,
                        scroll_filter=combined_filter,
                        limit=k,
                        with_payload=True,
                        with_vectors=False
                    )[0]
                    search_mode = "scroll с MatchText"
                except Exception as e2:
                    logger.warning(f"Метод scroll с MatchText не сработал: {str(e2)}")

                    # Вариант 3: Получаем все документы и фильтруем программно
                    all_docs = self.client.scroll(
                        collection_name=self.collection_name,
                        scroll_filter=filter_obj,
                        limit=1000,  # Получаем больше документов для фильтрации
                        with_payload=True,
                        with_vectors=False
                    )[0]

                    # Фильтруем программно
                    results = []
                    for doc in all_docs:
                        if (doc.payload and
                                "page_content" in doc.payload and
                                query.lower() in doc.payload["page_content"].lower()):
                            results.append(doc)

                    # Ограничиваем количество результатов
                    results = results[:k]
                    search_mode = "ручная фильтрация"

            elapsed_time = time.time() - start_time
            logger.info(
                f"Текстовый поиск ({search_mode}) выполнен за {elapsed_time:.2f} сек., найдено {len(results)} результатов")

            # Преобразуем результаты
            documents = []
            for i, point in enumerate(results):
                metadata = point.payload.get("metadata", {})
                text = point.payload.get("page_content", "")

                # Для результатов scroll нет score, добавляем искусственную оценку
                # (более ранние результаты имеют более высокую оценку)
                score = 1.0 - (i * 0.05)
                if score < 0.1:
                    score = 0.1

                documents.append({
                    "text": text,
                    "metadata": {
                        **metadata,
                        "score": score,
                        "search_type": "text"
                    }
                })

            return documents
        except Exception as e:
            logger.error(f"Ошибка при выполнении текстового поиска: {str(e)}")
            return []

    def search_by_chunk_index(
            self,
            application_id: str,
            chunk_index: int
    ) -> Optional[Dict]:
        """
        Ищет чанк по его индексу.

        Args:
            application_id: ID заявки
            chunk_index: Индекс чанка

        Returns:
            Optional[Dict]: Найденный чанк или None
        """
        logger.info(f"Поиск чанка с индексом {chunk_index} для заявки {application_id}")

        try:
            # Создаем фильтр для поиска
            filter_obj = models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.application_id",
                        match=models.MatchValue(value=application_id)
                    ),
                    models.FieldCondition(
                        key="metadata.chunk_index",
                        match=models.MatchValue(value=chunk_index)
                    )
                ]
            )

            # Выполняем скроллинг с фильтром
            response = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=filter_obj,
                limit=1,
                with_payload=True,
                with_vectors=False
            )

            points = response[0]

            if not points:
                logger.info(f"Чанк с индексом {chunk_index} не найден для заявки {application_id}")
                return None

            # Преобразуем результат
            point = points[0]
            result = {
                "page_content": point.payload.get("page_content", ""),
                "metadata": point.payload.get("metadata", {})
            }

            logger.info(f"Чанк с индексом {chunk_index} найден")
            return result

        except Exception as e:
            logger.error(f"Ошибка при поиске чанка: {str(e)}")
            return None

    def run_text_search(
            self,
            application_id: str,
            queries: List[Dict[str, str]],
            k: int = 5
    ):
        """
        Запускает текстовый поиск для набора запросов.

        Args:
            application_id: ID заявки
            queries: Список запросов с описаниями
            k: Количество результатов для каждого поиска
        """
        logger.info(f"Запуск текстового поиска для заявки {application_id}")

        for q_info in queries:
            query = q_info["query"]
            description = q_info.get("description", "")

            logger.info("=" * 80)
            logger.info(f"Запрос: {query}")
            if description:
                logger.info(f"Описание: {description}")
            logger.info("-" * 80)

            # Выполняем текстовый поиск
            text_results = self.perform_text_search(application_id, query, k)

            # Вывод результатов
            logger.info(f"Результаты текстового поиска ({len(text_results)}):")
            for i, doc in enumerate(text_results):
                score = doc["metadata"].get('score', 0.0)
                content_type = doc["metadata"].get('content_type', 'unknown')
                section = doc["metadata"].get('section', 'unknown')
                chunk_index = doc["metadata"].get('chunk_index', 'unknown')
                logger.info(
                    f"{i + 1}. Оценка: {score:.4f}, Индекс чанка: {chunk_index}, Раздел: {section}, Тип: {content_type}")
                # Ограничиваем длину текста для вывода
                display_text = doc["text"][:200] + "..." if len(doc["text"]) > 200 else doc["text"]
                logger.info(f"   Текст: {display_text}")

            logger.info("=" * 80)
            logger.info("")  # Пустая строка для разделения запросов


if __name__ == "__main__":
    # Создаем парсер аргументов командной строки
    parser = argparse.ArgumentParser(description='Тестирование текстового поиска в Qdrant')

    parser.add_argument('--host', type=str, default='localhost',
                        help='Хост Qdrant сервера (по умолчанию: localhost)')
    parser.add_argument('--port', type=int, default=6333,
                        help='Порт Qdrant сервера (по умолчанию: 6333)')
    parser.add_argument('--collection', type=str, default='ppee_applications',
                        help='Имя коллекции в Qdrant (по умолчанию: ppee_applications)')
    parser.add_argument('--application_id', type=str, required=True,
                        help='ID заявки для поиска (укажите "list" для просмотра доступных ID)')
    parser.add_argument('--limit', type=int, default=5,
                        help='Количество результатов поиска (по умолчанию: 5)')
    parser.add_argument('--chunk_index', type=int, default=None,
                        help='Индекс чанка для прямого поиска (по умолчанию: None)')

    args = parser.parse_args()

    # Создаем экземпляр тестера
    tester = TextSearchTester(
        host=args.host,
        port=args.port,
        collection_name=args.collection
    )

    # Если указан chunk_index, ищем конкретный чанк
    if args.chunk_index is not None:
        chunk = tester.search_by_chunk_index(args.application_id, args.chunk_index)
        if chunk:
            logger.info("=" * 80)
            logger.info(f"Найден чанк с индексом {args.chunk_index}:")
            logger.info("-" * 80)
            logger.info(f"Метаданные: {chunk['metadata']}")
            logger.info("-" * 80)
            logger.info(f"Содержимое: {chunk['page_content']}")
            logger.info("=" * 80)
        else:
            logger.info(f"Чанк с индексом {args.chunk_index} не найден")
        sys.exit(0)

    # Если не указан application_id, выводим список доступных
    if args.application_id == 'list':
        app_ids = tester.get_application_ids()
        if app_ids:
            logger.info("Доступные ID заявок:")
            for app_id in app_ids:
                logger.info(f"- {app_id}")
        else:
            logger.info("Не найдено доступных заявок в коллекции")
        sys.exit(0)

    # Список запросов для тестирования
    test_queries = [
        {"query": "ИНН", "description": "Поиск по ключевому слову ИНН"},
        {"query": "ИНН/КПП", "description": "Поиск по ключевой фразе ИНН/КПП"},
        {"query": "1010101010", "description": "Поиск по значению ИНН"},
        {"query": "Полное наименование", "description": "Поиск информации о наименовании"}
    ]

    # Запускаем текстовый поиск
    tester.run_text_search(
        application_id=args.application_id,
        queries=test_queries,
        k=args.limit
    )