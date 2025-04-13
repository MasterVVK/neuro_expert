"""
Скрипт для прямой конвертации PDF через docling в векторную базу Qdrant
с использованием PPEEDocumentSplitter для разделения документа.
"""

import os
import logging
import argparse
import tempfile
from typing import List, Dict, Any, Optional

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Импорт классов из проекта
from ppee_analyzer.vector_store import QdrantManager
from ppee_analyzer.document_processor import PPEEDocumentSplitter
from langchain_core.documents import Document

# Проверяем наличие docling
try:
    import docling
    from docling.document_converter import DocumentConverter, InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    logger.warning("Библиотека docling не установлена")


def pdf_to_qdrant_direct(
        pdf_path: str,
        application_id: str,
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        collection_name: str = "ppee_applications",
        embeddings_type: str = "ollama",
        model_name: str = "bge-m3",
        device: str = "cuda",
        ollama_url: str = "http://localhost:11434",
        delete_existing: bool = False
):
    """
    Конвертирует PDF через docling и индексирует в Qdrant с помощью PPEEDocumentSplitter.

    Args:
        pdf_path: Путь к PDF файлу
        application_id: Идентификатор заявки
        qdrant_host: Хост Qdrant
        qdrant_port: Порт Qdrant
        collection_name: Имя коллекции
        embeddings_type: Тип эмбеддингов
        model_name: Название модели эмбеддингов
        device: Устройство для вычислений
        ollama_url: URL для Ollama API
        delete_existing: Удалять ли существующие документы с тем же application_id

    Returns:
        Dict[str, Any]: Результаты индексации
    """
    if not DOCLING_AVAILABLE:
        return {"error": "Библиотека docling не установлена", "status": "error"}

    logger.info(f"Обработка PDF файла: {pdf_path}")

    try:
        # 1. Настраиваем опции для docling
        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_picture_images = True
        pipeline_options.images_scale = 2

        pdf_format_option = docling.document_converter.PdfFormatOption(
            pipeline_options=pipeline_options,
            extract_images=True
        )

        format_options = {
            InputFormat.PDF: pdf_format_option
        }

        # 2. Инициализируем конвертер docling
        logger.info("Инициализация конвертера docling")
        try:
            converter = DocumentConverter(format_options=format_options)
        except Exception as e:
            logger.warning(f"Не удалось создать конвертер с опциями: {str(e)}")
            converter = DocumentConverter()

        # 3. Конвертируем PDF в Markdown через docling
        logger.info(f"Конвертация PDF через docling")
        docling_result = converter.convert(pdf_path)

        if not docling_result:
            logger.error("Не удалось конвертировать PDF через docling")
            return {"error": "Не удалось конвертировать PDF через docling", "status": "error"}

        logger.info(f"PDF успешно конвертирован через docling")

        # 4. Сохраняем Markdown во временный файл
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as temp_file:
            temp_markdown_path = temp_file.name
            docling_result.document.save_as_markdown(temp_markdown_path)
            logger.info(f"Markdown сохранен во временный файл: {temp_markdown_path}")

        # 5. Используем PPEEDocumentSplitter для разделения документа
        logger.info("Инициализация PPEEDocumentSplitter")
        splitter = PPEEDocumentSplitter()

        # 6. Загружаем и разделяем документ
        logger.info(f"Разделение документа на фрагменты")
        chunks = splitter.load_and_process_file(temp_markdown_path, application_id)

        # 7. Удаляем временный файл
        os.unlink(temp_markdown_path)
        logger.info(f"Временный файл удален: {temp_markdown_path}")

        logger.info(f"Документ разделен на {len(chunks)} фрагментов")

        # 8. Инициализируем менеджер Qdrant
        logger.info("Инициализация QdrantManager")
        qdrant_manager = QdrantManager(
            collection_name=collection_name,
            host=qdrant_host,
            port=qdrant_port,
            embeddings_type=embeddings_type,
            model_name=model_name,
            device=device,
            ollama_url=ollama_url
        )

        # 9. Если нужно, удаляем существующие документы
        if delete_existing:
            deleted_count = qdrant_manager.delete_application(application_id)
            logger.info(f"Удалено {deleted_count} существующих документов для заявки {application_id}")

        # 10. Добавляем фрагменты в векторную базу данных
        logger.info(f"Индексация фрагментов в Qdrant")
        indexed_count = qdrant_manager.add_documents(chunks)

        # 11. Собираем статистику
        content_types = {}
        for chunk in chunks:
            content_type = chunk.metadata["content_type"]
            content_types[content_type] = content_types.get(content_type, 0) + 1

        # 12. Возвращаем результат
        result = {
            "pdf_path": pdf_path,
            "application_id": application_id,
            "total_chunks": len(chunks),
            "indexed_count": indexed_count,
            "content_types": content_types,
            "collection_name": collection_name,
            "status": "success"
        }

        return result

    except Exception as e:
        logger.error(f"Ошибка при обработке PDF: {str(e)}")
        return {"error": str(e), "status": "error"}


def test_search(collection_name: str = "ppee_applications"):
    """
    Тестовая функция для проверки поиска.

    Args:
        collection_name: Имя коллекции
    """
    qdrant_manager = QdrantManager(
        collection_name=collection_name,
        host="localhost",
        port=6333,
        embeddings_type="ollama",
        model_name="bge-m3"
    )

    # Тестовые запросы
    queries = [
        "полное наименование юридического лица",
        "ИНН организации",
        "ОГРН организации",
        "адрес местонахождения"
    ]

    for query in queries:
        print(f"\n{'=' * 60}")
        print(f"Поиск: '{query}'")
        print(f"{'=' * 60}")

        # Выполняем поиск
        docs = qdrant_manager.search(
            query=query,
            filter_dict={"application_id": "app1"},
            k=3
        )

        # Выводим результаты
        if docs:
            for i, doc in enumerate(docs):
                print(f"\nРезультат {i+1}:")
                print(f"Раздел: {doc.metadata.get('section', 'Неизвестный раздел')}")
                print(f"Тип: {doc.metadata.get('content_type', 'Неизвестно')}")

                # Печатаем контент (ограниченный)
                content = doc.page_content
                if len(content) > 300:
                    content = content[:297] + "..."

                print(f"Содержание: {content}")
                print(f"{'-' * 60}")
        else:
            print("Ничего не найдено")


def main():
    """Функция командной строки для запуска процесса"""
    parser = argparse.ArgumentParser(
        description="Конвертация PDF в Qdrant через docling с использованием PPEEDocumentSplitter"
    )

    # Обязательные аргументы
    parser.add_argument(
        "pdf_path",
        help="Путь к PDF файлу для обработки"
    )
    parser.add_argument(
        "--app-id",
        required=True,
        help="Идентификатор заявки"
    )

    # Настройки Qdrant
    parser.add_argument(
        "--qdrant-host",
        default="localhost",
        help="Хост Qdrant (по умолчанию: localhost)"
    )
    parser.add_argument(
        "--qdrant-port",
        type=int,
        default=6333,
        help="Порт Qdrant (по умолчанию: 6333)"
    )
    parser.add_argument(
        "--collection",
        default="ppee_applications",
        help="Имя коллекции в Qdrant (по умолчанию: ppee_applications)"
    )

    # Настройки эмбеддингов
    parser.add_argument(
        "--embeddings",
        choices=["ollama", "huggingface"],
        default="ollama",
        help="Тип эмбеддингов (по умолчанию: ollama)"
    )
    parser.add_argument(
        "--model",
        default="bge-m3",
        help="Название модели эмбеддингов (по умолчанию: bge-m3)"
    )
    parser.add_argument(
        "--device",
        choices=["cuda", "cpu"],
        default="cuda",
        help="Устройство для вычислений (по умолчанию: cuda)"
    )
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="URL для Ollama API (по умолчанию: http://localhost:11434)"
    )

    # Дополнительные настройки
    parser.add_argument(
        "--delete-existing",
        action="store_true",
        help="Удалять существующие документы с тем же application_id"
    )
    parser.add_argument(
        "--test-search",
        action="store_true",
        help="Выполнить тестовый поиск после индексации"
    )

    args = parser.parse_args()

    # Запуск процесса обработки
    result = pdf_to_qdrant_direct(
        pdf_path=args.pdf_path,
        application_id=args.app_id,
        qdrant_host=args.qdrant_host,
        qdrant_port=args.qdrant_port,
        collection_name=args.collection,
        embeddings_type=args.embeddings,
        model_name=args.model,
        device=args.device,
        ollama_url=args.ollama_url,
        delete_existing=args.delete_existing
    )

    # Вывод результата
    if result.get("status") == "success":
        print("\nОбработка успешно завершена!")
        print(f"PDF файл: {result['pdf_path']}")
        print(f"Идентификатор заявки: {result['application_id']}")
        print(f"Коллекция Qdrant: {result['collection_name']}")
        print(f"Количество фрагментов: {result['total_chunks']}")
        print(f"Проиндексировано фрагментов: {result['indexed_count']}")

        print("\nСтатистика по типам фрагментов:")
        for content_type, count in result['content_types'].items():
            print(f"  - {content_type}: {count}")

        # Если нужно, выполняем тестовый поиск
        if args.test_search:
            test_search(args.collection)
    else:
        print(f"\nОШИБКА при обработке: {result.get('error', 'Неизвестная ошибка')}")


if __name__ == "__main__":
    main()