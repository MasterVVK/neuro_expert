#!/usr/bin/env python3
"""
Файл для загрузки документа ППЭЭ в векторную базу данных Qdrant
с использованием семантического разделения на чанки.
Запускается непосредственно в PyCharm.
"""

import os
import logging
import argparse
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

# Импорт классов из нашего проекта
from ppee_analyzer.vector_store import QdrantManager
from ppee_analyzer.semantic_chunker import SemanticChunker
from langchain_core.documents import Document


def detect_gpu_availability() -> bool:
    """
    Проверяет доступность CUDA для работы с GPU.

    Returns:
        bool: True если GPU доступен, иначе False
    """
    try:
        import torch
        has_cuda = torch.cuda.is_available()
        if has_cuda:
            logger.info(f"CUDA доступна. Используется GPU: {torch.cuda.get_device_name(0)}")
        else:
            logger.info("CUDA недоступна. Используется CPU.")
        return has_cuda
    except ImportError:
        logger.info("PyTorch не установлен. Используется CPU.")
        return False


def convert_semantic_chunks_to_documents(
        chunks: List[Dict],
        application_id: str,
        document_id: str,
        document_name: str
) -> List[Document]:
    """
    Преобразует семантические чанки в формат документов LangChain.

    Args:
        chunks: Список чанков
        application_id: ID заявки
        document_id: ID документа
        document_name: Имя документа

    Returns:
        List[Document]: Список документов LangChain
    """
    documents = []

    for i, chunk in enumerate(chunks):
        # Создаем метаданные
        metadata = {
            "application_id": application_id,
            "document_id": document_id,
            "document_name": document_name,
            "content_type": chunk.get("type", "unknown"),
            "chunk_index": i,
            "section": chunk.get("heading", "Не определено"),
        }

        # Добавляем информацию о странице
        if chunk.get("page"):
            metadata["page_number"] = chunk.get("page")

        # Добавляем информацию о таблице
        if chunk.get("type") == "table":
            metadata["table_id"] = chunk.get("table_id")

            # Если есть информация о нескольких страницах
            if chunk.get("pages"):
                metadata["pages"] = chunk.get("pages")

        # Создаем документ
        documents.append(Document(
            page_content=chunk.get("content", ""),
            metadata=metadata
        ))

    return documents


def main(
        file_path: str,
        application_id: str,
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        collection_name: str = "ppee_applications",
        embeddings_type: str = "ollama",
        model_name: str = "bge-m3",
        device: str = "cuda",
        ollama_url: str = "http://localhost:11434",
        use_gpu: bool = None
):
    """
    Основная функция для загрузки документа в Qdrant с семантическим разделением.

    Args:
        file_path: Путь к файлу
        application_id: ID заявки
        qdrant_host: Хост Qdrant
        qdrant_port: Порт Qdrant
        collection_name: Имя коллекции
        embeddings_type: Тип эмбеддингов
        model_name: Имя модели для эмбеддингов
        device: Устройство (cpu/cuda)
        ollama_url: URL для Ollama API
        use_gpu: Использовать ли GPU для семантического разделения
    """
    print(f"Загрузка документа {file_path} в Qdrant...")
    print(f"Используемый тип эмбеддингов: {embeddings_type}")
    print(f"Модель: {model_name}")

    start_time = time.time()

    try:
        # 1. Проверяем существование файла
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Файл не найден: {file_path}")

        # 2. Определяем расширение файла
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()

        # 3. Если это PDF, используем семантическое разделение
        if ext == '.pdf':
            logger.info("Используем семантическое разделение для PDF")

            # Инициализируем семантический чанкер
            chunker = SemanticChunker(use_gpu=use_gpu)

            # Шаг 1: Извлекаем смысловые блоки
            logger.info("Извлечение смысловых блоков...")
            chunks = chunker.extract_chunks(file_path)
            logger.info(f"Найдено {len(chunks)} начальных блоков")

            # Шаг 2: Обрабатываем таблицы
            logger.info("Обработка и объединение таблиц...")
            processed_chunks = chunker.post_process_tables(chunks)
            logger.info(f"После обработки таблиц: {len(processed_chunks)} блоков")

            # Шаг 3: Группируем короткие блоки
            logger.info("Группировка коротких блоков...")
            grouped_chunks = chunker.group_semantic_chunks(processed_chunks)
            logger.info(f"После группировки: {len(grouped_chunks)} финальных блоков")

            # Создаем идентификатор документа на основе имени файла
            document_id = f"doc_{os.path.basename(file_path).replace(' ', '_').replace('.', '_')}"
            document_name = os.path.basename(file_path)

            # Конвертируем чанки в формат документов для индексации
            documents = convert_semantic_chunks_to_documents(
                grouped_chunks,
                application_id,
                document_id,
                document_name
            )
        else:
            # Для других типов файлов используем стандартный сплиттер
            from ppee_analyzer.document_processor import PPEEDocumentSplitter

            logger.info(f"Используем стандартное разделение для файла типа {ext}")

            # Инициализируем разделитель документов
            splitter = PPEEDocumentSplitter()

            # Загружаем и разделяем документ
            documents = splitter.load_and_process_file(file_path, application_id)

        logger.info(f"Документ разделен на {len(documents)} фрагментов")

        # Статистика по типам фрагментов
        content_types = {}
        for chunk in documents:
            content_type = chunk.metadata["content_type"]
            content_types[content_type] = content_types.get(content_type, 0) + 1

        print("\nСтатистика по типам фрагментов:")
        for content_type, count in content_types.items():
            print(f"  - {content_type}: {count}")

        # 4. Инициализируем менеджер Qdrant
        qdrant_manager = QdrantManager(
            collection_name=collection_name,
            host=qdrant_host,
            port=qdrant_port,
            embeddings_type=embeddings_type,
            model_name=model_name,
            device=device,
            ollama_url=ollama_url
        )

        # 5. Добавляем фрагменты в векторную базу данных
        indexed_count = qdrant_manager.add_documents(documents)

        end_time = time.time()
        elapsed_time = end_time - start_time

        print(f"\nДокумент успешно загружен в Qdrant")
        print(f"  - Проиндексировано фрагментов: {indexed_count}")
        print(f"  - Коллекция: {collection_name}")
        print(f"  - Идентификатор заявки: {application_id}")
        print(f"  - Тип эмбеддингов: {embeddings_type}")
        print(f"  - Модель: {model_name}")
        print(f"  - Время выполнения: {elapsed_time:.2f} секунд")

    except Exception as e:
        print(f"Ошибка при загрузке документа: {str(e)}")
        logger.exception(f"Детали ошибки: {str(e)}")


if __name__ == "__main__":
    # Получаем параметры из аргументов командной строки или используем значения по умолчанию
    parser = argparse.ArgumentParser(
        description='Загрузка документа ППЭЭ в векторную базу данных Qdrant с семантическим разделением'
    )
    parser.add_argument('--file', type=str, help='Путь к файлу документа',
                        default="data/docling-splitter-test.pdf")
    parser.add_argument('--app-id', type=str, help='Идентификатор заявки', default="app3")
    parser.add_argument('--host', type=str, help='Хост Qdrant', default="localhost")
    parser.add_argument('--port', type=int, help='Порт Qdrant', default=6333)
    parser.add_argument('--collection', type=str, help='Имя коллекции', default="ppee_applications")
    parser.add_argument('--embeddings', type=str, help='Тип эмбеддингов: huggingface или ollama', default="ollama")
    parser.add_argument('--model', type=str, help='Модель для эмбеддингов', default="bge-m3")
    parser.add_argument('--device', type=str, help='Устройство (cpu/cuda)', default="cuda")
    parser.add_argument('--ollama-url', type=str, help='URL для Ollama API', default="http://localhost:11434")
    parser.add_argument('--use-gpu', action='store_true', help='Использовать GPU для семантического разделения')
    parser.add_argument('--cpu-only', action='store_true', help='Использовать только CPU')

    args = parser.parse_args()

    # Определяем, использовать ли GPU для семантического разделения
    use_gpu = None  # Автоопределение по умолчанию
    if args.use_gpu:
        use_gpu = True
    elif args.cpu_only:
        use_gpu = False

    # Вызываем основную функцию с параметрами
    main(
        file_path=args.file,
        application_id=args.app_id,
        qdrant_host=args.host,
        qdrant_port=args.port,
        collection_name=args.collection,
        embeddings_type=args.embeddings,
        model_name=args.model,
        device=args.device,
        ollama_url=args.ollama_url,
        use_gpu=use_gpu
    )