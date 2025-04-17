"""
Файл для выполнения семантического поиска по параметру в документах ППЭЭ
с применением ререйтинга через Ollama для улучшения результатов.
"""

import os
import logging
import time
import requests
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

# Импорт классов из нашего проекта
from ppee_analyzer.vector_store import QdrantManager
from langchain_core.documents import Document

# Параметры поиска и Qdrant
#SEARCH_QUERY = "полное наименование юридического лица"  # Параметр для поиска
SEARCH_QUERY = "Идентификационный номер налогоплательщика ИНН"
APPLICATION_ID = "1"  # Идентификатор заявки
QDRANT_HOST = "localhost"  # Хост Qdrant
QDRANT_PORT = 6333  # Порт Qdrant
COLLECTION_NAME = "ppee_applications"  # Имя коллекции

# Параметры эмбеддингов
EMBEDDINGS_TYPE = "ollama"  # Тип эмбеддингов: "huggingface" или "ollama"
MODEL_NAME = "bge-m3"  # Модель для Ollama
DEVICE = "cuda"  # Устройство (cpu/cuda) для HuggingFace
OLLAMA_URL = "http://localhost:11434"  # URL для Ollama API

# Параметры ререйтинга
USE_RERANKER = True  # Использовать ререйтинг
RERANKER_MODEL = "qllama/bge-reranker-v2-m3:f16"  # Модель для ререйтинга через Ollama

LIMIT = 5  # Количество результатов для финального вывода
INITIAL_LIMIT = 20  # Количество результатов для ререйтинга


class OllamaReranker:
    """Класс для ре-ранкинга результатов с использованием Ollama"""

    def __init__(
            self,
            model_name: str = "qllama/bge-reranker-v2-m3:f16",
            base_url: str = "http://localhost:11434",
            batch_size: int = 8,
            timeout: int = 60
    ):
        """
        Инициализирует ре-ранкер на базе Ollama.

        Args:
            model_name: Название модели для ре-ранкинга в Ollama
            base_url: URL для Ollama API
            batch_size: Размер батча для обработки
            timeout: Таймаут запроса в секундах
        """
        self.model_name = model_name
        self.base_url = base_url.rstrip('/')
        self.batch_size = batch_size
        self.timeout = timeout

        logger.info(f"Инициализация Ollama Reranker с моделью {model_name}")

        # Проверяем доступность модели
        self._check_model_availability()

    def _check_model_availability(self) -> None:
        """Проверяет доступность модели в Ollama"""
        try:
            # Проверяем доступность сервера
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=self.timeout
            )
            response.raise_for_status()

            models = response.json().get("models", [])
            model_exists = any(model.get("name") == self.model_name for model in models)

            if not model_exists:
                logger.info(f"Модель {self.model_name} не найдена. Попытка загрузки...")
                self._pull_model()
            else:
                logger.info(f"Модель {self.model_name} доступна для использования")

        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при проверке доступности Ollama: {str(e)}")
            raise ConnectionError(f"Не удалось подключиться к серверу Ollama: {str(e)}")

    def _pull_model(self) -> None:
        """Загружает модель, если она еще не загружена"""
        try:
            response = requests.post(
                f"{self.base_url}/api/pull",
                json={"name": self.model_name},
                timeout=None  # Убираем таймаут для загрузки модели
            )
            response.raise_for_status()
            logger.info(f"Модель {self.model_name} успешно загружена")
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при загрузке модели {self.model_name}: {str(e)}")
            raise RuntimeError(f"Не удалось загрузить модель {self.model_name}: {str(e)}")

    def rerank(
            self,
            query: str,
            documents: List[Dict[str, Any]],
            top_k: int = None,
            text_key: str = "text"
    ) -> List[Dict[str, Any]]:
        """
        Выполняет ре-ранкинг списка документов с использованием Ollama.

        Args:
            query: Поисковый запрос
            documents: Список документов (словарей с ключом 'text' или указанным в text_key)
            top_k: Количество документов в возвращаемом результате (None - все)
            text_key: Ключ, по которому извлекается текстовое содержимое документа

        Returns:
            List[Dict[str, Any]]: Отсортированный список документов с добавленной оценкой rerank_score
        """
        if not documents:
            return []

        if top_k is None:
            top_k = len(documents)

        logger.info(f"Выполнение ре-ранкинга через Ollama для {len(documents)} документов")

        # Получаем тексты документов
        texts = [doc.get(text_key, "") for doc in documents]

        # Вычисляем релевантности для текстов батчами
        reranked_documents = []

        for i in range(0, len(documents), self.batch_size):
            batch_end = min(i + self.batch_size, len(documents))
            batch_docs = documents[i:batch_end]
            batch_texts = texts[i:batch_end]

            logger.info(f"Обработка батча {i // self.batch_size + 1} из {(len(documents) - 1) // self.batch_size + 1}")

            # Рассчитываем оценки для текущего батча
            batch_scores = self._compute_scores_batch(query, batch_texts)

            # Добавляем оценки ре-ранкинга к документам
            for j, score in enumerate(batch_scores):
                batch_docs[j]["rerank_score"] = score
                reranked_documents.append(batch_docs[j])

        # Сортируем документы по убыванию оценки ре-ранкинга
        reranked_documents = sorted(reranked_documents, key=lambda x: x.get("rerank_score", 0.0), reverse=True)

        # Возвращаем top_k документов
        return reranked_documents[:top_k]

    def _compute_scores_batch(self, query: str, texts: List[str]) -> List[float]:
        """
        Вычисляет оценки релевантности для батча текстов.

        Args:
            query: Поисковый запрос
            texts: Список текстов документов

        Returns:
            List[float]: Список оценок релевантности
        """
        scores = []

        for text in texts:
            score = self._compute_score(query, text)
            scores.append(score)

        return scores

    def _compute_score(self, query: str, text: str) -> float:
        """
        Вычисляет оценку релевантности между запросом и текстом с помощью Ollama.

        Args:
            query: Поисковый запрос
            text: Текст документа

        Returns:
            float: Оценка релевантности
        """
        try:
            # Формируем промпт для ре-ранкера
            # БВ ре-ранкере bge-reranker ожидается формат [query] [passage]
            prompt = f"{query} {text}"

            # Отправляем запрос к Ollama API
            response = requests.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": self.model_name,
                    "prompt": prompt
                },
                timeout=self.timeout
            )
            response.raise_for_status()

            result = response.json()

            # В модели ре-ранкера оценка возвращается как первый элемент вектора эмбеддинга
            if "embedding" in result and len(result["embedding"]) > 0:
                # Возвращаем первый элемент вектора как оценку релевантности
                return float(result["embedding"][0])
            else:
                logger.warning(f"Неожиданный формат ответа: {result}")
                return 0.0

        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при запросе к Ollama: {str(e)}")
            return 0.0
        except Exception as e:
            logger.error(f"Ошибка при вычислении релевантности: {str(e)}")
            return 0.0

    def cleanup(self):
        """
        Освобождает ресурсы, занимаемые моделью.
        """
        logger.info("Освобождение ресурсов модели ререйтинга...")
        # Для Ollama нет необходимости в специальной очистке


def semantic_search_with_reranking(query: str, use_reranker: bool = True) -> List[Dict[str, Any]]:
    """
    Выполняет семантический поиск по параметру в Qdrant с опциональным ререйтингом через Ollama.

    Args:
        query: Поисковый запрос
        use_reranker: Использовать ре-ранкер для уточнения результатов

    Returns:
        List[Dict[str, Any]]: Результаты поиска
    """
    logger.info(f"Выполнение семантического поиска для запроса: '{query}'")
    start_time = time.time()

    try:
        # Инициализируем менеджер Qdrant
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

        # Выбираем лимит поиска в зависимости от использования ререйтинга
        search_limit = INITIAL_LIMIT if use_reranker else LIMIT

        # Выполняем семантический поиск
        docs = qdrant_manager.search(
            query=query,
            filter_dict={"application_id": APPLICATION_ID},
            k=search_limit
        )

        # Преобразуем результаты в нужный формат
        results = []
        for doc in docs:
            results.append({
                "text": doc.page_content,
                "metadata": doc.metadata,
                "score": doc.metadata.get('score', 0.0)  # Оценка векторного поиска
            })

        # Если нужно использовать ререйтинг и есть результаты
        if use_reranker and results:
            logger.info(f"Инициализация ре-ранкера Ollama с моделью {RERANKER_MODEL}")
            reranker = OllamaReranker(
                model_name=RERANKER_MODEL,
                base_url=OLLAMA_URL
            )

            logger.info(f"Применение ре-ранкинга к {len(results)} результатам")
            reranker_start_time = time.time()

            reranked_results = reranker.rerank(
                query=query,
                documents=results,
                top_k=LIMIT,
                text_key="text"
            )

            reranker_time = time.time() - reranker_start_time
            logger.info(f"Ре-ранкинг завершен за {reranker_time:.2f} секунд")

            # Итоговые результаты после ререйтинга
            final_results = reranked_results[:LIMIT]
        else:
            # Итоговые результаты без ререйтинга
            final_results = results[:LIMIT]

        search_time = time.time() - start_time
        logger.info(f"Всего найдено {len(docs)} документов, выбрано {len(final_results)}")
        logger.info(f"Поиск завершен за {search_time:.2f} секунд")

        return final_results

    except Exception as e:
        logger.error(f"Ошибка при поиске: {str(e)}")
        return []


def main():
    """Основная функция для поиска и сравнения результатов с ререйтингом и без него"""
    print(f"\n{'=' * 80}")
    print(f"Поиск: '{SEARCH_QUERY}'")
    print(f"Заявка: {APPLICATION_ID}")
    print(f"Модель эмбеддингов: {MODEL_NAME}")
    print(f"Использование ререйтинга Ollama: {USE_RERANKER}")
    if USE_RERANKER:
        print(f"Модель ререйтинга Ollama: {RERANKER_MODEL}")
    print(f"{'=' * 80}\n")

    try:
        # Замеряем время выполнения
        start_time = time.time()

        # Выполняем поиск без ререйтинга
        print("Выполнение поиска без ререйтинга...")
        standard_start = time.time()
        standard_results = semantic_search_with_reranking(SEARCH_QUERY, use_reranker=False)
        standard_time = time.time() - standard_start
        print(f"Стандартный поиск выполнен за {standard_time:.2f} секунд")

        # Выполняем поиск с ререйтингом (если указано)
        reranked_results = []
        rerank_time = 0
        if USE_RERANKER:
            print("\nВыполнение поиска с ререйтингом через Ollama...")
            rerank_start = time.time()
            reranked_results = semantic_search_with_reranking(SEARCH_QUERY, use_reranker=True)
            rerank_time = time.time() - rerank_start
            print(f"Поиск с ререйтингом выполнен за {rerank_time:.2f} секунд")

        # Общее время выполнения
        total_time = time.time() - start_time

        # Выводим результаты стандартного поиска
        print(f"\n{'=' * 80}")
        print(f"РЕЗУЛЬТАТЫ СТАНДАРТНОГО ПОИСКА:")
        print(f"{'=' * 80}")

        for i, result in enumerate(standard_results):
            print(f"\nРезультат {i + 1}:")
            print(f"Релевантность (векторная): {result['score']:.4f}")

            # Выводим полную информацию о документе
            metadata = result['metadata']
            print(f"Документ: {metadata.get('document_name', 'Н/Д')}")
            print(f"Раздел: {metadata.get('section', 'Неизвестный раздел')}")
            print(f"Тип содержимого: {metadata.get('content_type', 'Неизвестно')}")

            if 'document_id' in metadata:
                print(f"ID документа: {metadata.get('document_id')}")
            if 'chunk_index' in metadata:
                print(f"Индекс фрагмента: {metadata.get('chunk_index')}")
            if 'page_number' in metadata and metadata['page_number'] is not None:
                print(f"Номер страницы: {metadata.get('page_number')}")

            # Выводим полный текст
            print(f"\nТекст:")
            print("-" * 40)
            print(result['text'])
            print("-" * 40)

        # Выводим результаты с ререйтингом
        if USE_RERANKER and reranked_results:
            print(f"\n{'=' * 80}")
            print(f"РЕЗУЛЬТАТЫ С РЕРЕЙТИНГОМ ЧЕРЕЗ OLLAMA:")
            print(f"{'=' * 80}")

            for i, result in enumerate(reranked_results):
                print(f"\nРезультат {i + 1}:")
                print(f"Релевантность (ререйтинг Ollama): {result.get('rerank_score', 0.0):.4f}")
                print(f"Релевантность (векторная): {result['score']:.4f}")

                # Выводим полную информацию о документе
                metadata = result['metadata']
                print(f"Документ: {metadata.get('document_name', 'Н/Д')}")
                print(f"Раздел: {metadata.get('section', 'Неизвестный раздел')}")
                print(f"Тип содержимого: {metadata.get('content_type', 'Неизвестно')}")

                if 'document_id' in metadata:
                    print(f"ID документа: {metadata.get('document_id')}")
                if 'chunk_index' in metadata:
                    print(f"Индекс фрагмента: {metadata.get('chunk_index')}")
                if 'page_number' in metadata and metadata['page_number'] is not None:
                    print(f"Номер страницы: {metadata.get('page_number')}")

                # Выводим полный текст
                print(f"\nТекст:")
                print("-" * 40)
                print(result['text'])
                print("-" * 80)

        # Выводим статистику времени выполнения
        print(f"\n{'=' * 80}")
        print(f"СТАТИСТИКА ВРЕМЕНИ ВЫПОЛНЕНИЯ:")
        print(f"{'=' * 80}\n")
        print(f"Стандартный поиск: {standard_time:.2f} секунд")
        if USE_RERANKER:
            print(f"Поиск с ререйтингом через Ollama: {rerank_time:.2f} секунд")
            print(f"Замедление из-за ререйтинга: {rerank_time / standard_time:.1f}x")
        print(f"Общее время выполнения: {total_time:.2f} секунд")

        # Анализ изменений позиций после ререйтинга
        if USE_RERANKER and reranked_results:
            print(f"\n{'=' * 80}")
            print(f"АНАЛИЗ ИЗМЕНЕНИЙ ПОЗИЦИЙ:")
            print(f"{'=' * 80}\n")

            # Формируем идентификаторы документов для отслеживания
            standard_docs = []
            for result in standard_results:
                doc_id = result['metadata'].get('document_id', '')
                chunk_id = str(result['metadata'].get('chunk_index', ''))
                standard_docs.append(f"{doc_id}_{chunk_id}")

            reranked_docs = []
            for result in reranked_results:
                doc_id = result['metadata'].get('document_id', '')
                chunk_id = str(result['metadata'].get('chunk_index', ''))
                reranked_docs.append(f"{doc_id}_{chunk_id}")

            # Анализируем изменения позиций
            print("Изменения позиций документов после ререйтинга через Ollama:")
            for i, doc_id in enumerate(reranked_docs):
                if doc_id in standard_docs:
                    old_pos = standard_docs.index(doc_id) + 1
                    new_pos = i + 1

                    change = old_pos - new_pos

                    if change > 0:
                        change_text = f"↑ Поднялся на {change} позиций вверх"
                    elif change < 0:
                        change_text = f"↓ Опустился на {abs(change)} позиций вниз"
                    else:
                        change_text = "Позиция не изменилась"

                    # Извлекаем информацию о документе
                    rerank_result = reranked_results[i]
                    doc_name = rerank_result['metadata'].get('document_name', 'Н/Д')
                    section = rerank_result['metadata'].get('section', 'Н/Д')

                    print(f"{i + 1}. {doc_name} - {section}")
                    print(
                        f"   Стандартный поиск: позиция {old_pos}, оценка: {standard_results[old_pos - 1]['score']:.4f}")
                    print(
                        f"   Ререйтинг Ollama: позиция {new_pos}, оценка: {rerank_result.get('rerank_score', 0.0):.4f}")
                    print(f"   {change_text}")
                else:
                    print(f"{i + 1}. Новый документ в результатах после ререйтинга")
                print("-" * 40)

    except Exception as e:
        print(f"Ошибка при выполнении: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()