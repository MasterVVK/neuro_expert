"""
Файл для выполнения семантического поиска по параметру в документах ППЭЭ
с применением ререйтинга для улучшения результатов.
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

# Импорт классов из нашего проекта
from ppee_analyzer.vector_store import QdrantManager, BGEReranker
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
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"  # Модель для ререйтинга

LIMIT = 5  # Количество результатов для финального вывода
INITIAL_LIMIT = 20  # Количество результатов для ререйтинга


def semantic_search_with_reranking(query: str, use_reranker: bool = True) -> List[Dict[str, Any]]:
    """
    Выполняет семантический поиск по параметру в Qdrant с опциональным ререйтингом.

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
            logger.info(f"Инициализация ре-ранкера с моделью {RERANKER_MODEL}")
            reranker = BGEReranker(
                model_name=RERANKER_MODEL,
                device=DEVICE
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
    print(f"Использование ререйтинга: {USE_RERANKER}")
    if USE_RERANKER:
        print(f"Модель ререйтинга: {RERANKER_MODEL}")
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
            print("\nВыполнение поиска с ререйтингом...")
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
            print(f"РЕЗУЛЬТАТЫ С РЕРЕЙТИНГОМ:")
            print(f"{'=' * 80}")

            for i, result in enumerate(reranked_results):
                print(f"\nРезультат {i + 1}:")
                print(f"Релевантность (ререйтинг): {result.get('rerank_score', 0.0):.4f}")
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
            print(f"Поиск с ререйтингом: {rerank_time:.2f} секунд")
            print(f"Замедление из-за ререйтинга: {rerank_time/standard_time:.1f}x")
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
            print("Изменения позиций документов после ререйтинга:")
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

                    print(f"{i+1}. {doc_name} - {section}")
                    print(f"   Стандартный поиск: позиция {old_pos}, оценка: {standard_results[old_pos-1]['score']:.4f}")
                    print(f"   Ререйтинг: позиция {new_pos}, оценка: {rerank_result.get('rerank_score', 0.0):.4f}")
                    print(f"   {change_text}")
                else:
                    print(f"{i+1}. Новый документ в результатах после ререйтинга")
                print("-" * 40)

    except Exception as e:
        print(f"Ошибка при выполнении: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()