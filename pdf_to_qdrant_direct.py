"""
Скрипт для прямой конвертации PDF через docling в векторную базу Qdrant
с сохранением структурных элементов, включая целостные таблицы.
"""

import os
import logging
import argparse
import re
from typing import List, Dict, Any, Optional

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Импорт классов из проекта
from ppee_analyzer.vector_store import QdrantManager
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
        ollama_url: str = "http://localhost:11434"
):
    """
    Конвертирует PDF напрямую в векторную базу Qdrant через docling.

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

    Returns:
        Dict[str, Any]: Результаты индексации
    """
    if not DOCLING_AVAILABLE:
        return {"error": "Библиотека docling не установлена", "status": "error"}

    logger.info(f"Обработка PDF файла напрямую в Qdrant: {pdf_path}")

    try:
        # Получаем имя файла без расширения для ID документа
        document_id = os.path.splitext(os.path.basename(pdf_path))[0]

        # 1. Настраиваем опции для PDF
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

        # 2. Инициализируем конвертер docling с опциями
        logger.info("Инициализация конвертера docling")
        try:
            converter = DocumentConverter(format_options=format_options)
        except Exception as e:
            logger.warning(f"Не удалось создать конвертер с опциями: {str(e)}")
            converter = DocumentConverter()

        # 3. Конвертируем PDF напрямую в структуру docling
        logger.info(f"Конвертация PDF через docling")
        docling_result = converter.convert(pdf_path)

        if not docling_result:
            logger.error("Не удалось конвертировать PDF через docling")
            return {"error": "Не удалось конвертировать PDF через docling", "status": "error"}

        logger.info(f"PDF успешно конвертирован через docling")

        # Анализируем структуру результата docling для отладки
        logger.info(f"Результат docling: тип={type(docling_result)}")
        logger.info(f"Доступные атрибуты: {dir(docling_result)}")

        if hasattr(docling_result, 'document'):
            logger.info(f"Тип document: {type(docling_result.document)}")
            logger.info(f"Атрибуты document: {dir(docling_result.document)}")

        # 4. Создаем фрагменты напрямую из структуры docling
        logger.info("Создание фрагментов из структуры docling")
        chunks = create_chunks_from_docling(
            docling_result=docling_result,
            application_id=application_id,
            document_id=document_id
        )

        logger.info(f"Создано {len(chunks)} фрагментов документа")

        # 5. Инициализируем менеджер Qdrant
        logger.info("Инициализация менеджера Qdrant")
        qdrant_manager = QdrantManager(
            collection_name=collection_name,
            host=qdrant_host,
            port=qdrant_port,
            embeddings_type=embeddings_type,
            model_name=model_name,
            device=device,
            ollama_url=ollama_url
        )

        # 6. Добавляем фрагменты в векторную базу данных
        logger.info(f"Индексация фрагментов в Qdrant")
        indexed_count = qdrant_manager.add_documents(chunks)

        # 7. Собираем статистику
        content_types = {}
        for chunk in chunks:
            content_type = chunk.metadata["content_type"]
            content_types[content_type] = content_types.get(content_type, 0) + 1

        # 8. Возвращаем результат
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


def create_chunks_from_docling(
        docling_result: Any,
        application_id: str,
        document_id: str
) -> List[Document]:
    """
    Создает фрагменты документов напрямую из структуры docling,
    следуя логике деления из index_document.py.

    Args:
        docling_result: Результат конвертации docling
        application_id: Идентификатор заявки
        document_id: Идентификатор документа

    Returns:
        List[Document]: Список фрагментов-документов
    """
    chunks = []

    # Получаем доступ к документу
    docling_doc = docling_result.document

    # Экспортируем в markdown для дальнейшей обработки как в index_document.py
    markdown_content = docling_doc.export_to_markdown()

    if not markdown_content:
        logger.error("Не удалось получить markdown-контент из документа")
        return []

    # Начинаем обработку по разделам
    logger.info("Обработка markdown-контента для создания фрагментов")

    # Регулярное выражение для поиска заголовков
    header_pattern = r'^(#{1,6})\s+(.+)$'

    # Разделяем на строки
    lines = markdown_content.split('\n')

    # Структура для хранения разделов и их содержимого
    sections = []
    current_section = {
        'title': 'Введение',
        'level': 0,
        'content': []
    }

    # Разбиваем контент на секции
    for line in lines:
        header_match = re.match(header_pattern, line)

        if header_match:
            # Если встретили новый заголовок, сохраняем предыдущий раздел
            if current_section['content']:
                sections.append(current_section)

            # Создаем новый раздел
            level = len(header_match.group(1))
            title = header_match.group(2).strip()

            current_section = {
                'title': title,
                'level': level,
                'content': []
            }
        else:
            # Добавляем строку к текущему разделу
            current_section['content'].append(line)

    # Не забываем добавить последний раздел
    if current_section['content']:
        sections.append(current_section)

    # Обрабатываем секции и создаем фрагменты
    for section in sections:
        section_content = '\n'.join(section['content'])

        # Проверяем содержимое на наличие таблиц
        # Исправленный паттерн для поиска таблиц
        has_table = False
        table_lines = []

        # Разбиваем на строки для более простого поиска таблиц
        content_lines = section_content.split('\n')
        in_table = False
        table_start_index = -1

        for i, line in enumerate(content_lines):
            # Определяем начало таблицы
            if line.strip().startswith('|') and '|' in line[1:]:
                if not in_table:
                    in_table = True
                    table_start_index = i
            # Определяем конец таблицы
            elif in_table and (not line.strip().startswith('|') or '|' not in line[1:]):
                if i > table_start_index + 1:  # Минимальная таблица должна иметь хотя бы 2 строки
                    has_table = True
                    table = '\n'.join(content_lines[table_start_index:i])
                    table_lines.append((table_start_index, i, table))
                in_table = False

        # Если таблица заканчивается в конце раздела
        if in_table and table_start_index >= 0:
            has_table = True
            table = '\n'.join(content_lines[table_start_index:])
            table_lines.append((table_start_index, len(content_lines), table))

        # Если в разделе есть таблицы, обрабатываем их отдельно
        if has_table:
            # Создаем фрагменты текста между таблицами
            last_end = 0

            for start, end, table in table_lines:
                # Добавляем текст до таблицы
                if start > last_end:
                    text_content = '\n'.join(content_lines[last_end:start])
                    if text_content.strip():
                        # Определяем тип контента
                        content_type = "text"
                        if any(line.strip().startswith(('-', '*', '+')) for line in text_content.split('\n')):
                            content_type = "list"

                        chunks.append(Document(
                            page_content=text_content.strip(),
                            metadata={
                                "application_id": application_id,
                                "document_id": document_id,
                                "section": section['title'],
                                "section_level": section['level'],
                                "content_type": content_type
                            }
                        ))

                # Добавляем таблицу
                chunks.append(Document(
                    page_content=table.strip(),
                    metadata={
                        "application_id": application_id,
                        "document_id": document_id,
                        "section": section['title'],
                        "section_level": section['level'],
                        "content_type": "table"
                    }
                ))

                last_end = end

            # Добавляем оставшийся текст после последней таблицы
            if last_end < len(content_lines):
                text_content = '\n'.join(content_lines[last_end:])
                if text_content.strip():
                    # Определяем тип контента
                    content_type = "text"
                    if any(line.strip().startswith(('-', '*', '+')) for line in text_content.split('\n')):
                        content_type = "list"

                    chunks.append(Document(
                        page_content=text_content.strip(),
                        metadata={
                            "application_id": application_id,
                            "document_id": document_id,
                            "section": section['title'],
                            "section_level": section['level'],
                            "content_type": content_type
                        }
                    ))
        else:
            # Если таблиц нет, добавляем содержимое как один фрагмент
            if section_content.strip():
                # Определяем тип контента
                content_type = "text"
                if any(line.strip().startswith(('-', '*', '+')) for line in section_content.split('\n')):
                    content_type = "list"

                chunks.append(Document(
                    page_content=section_content.strip(),
                    metadata={
                        "application_id": application_id,
                        "document_id": document_id,
                        "section": section['title'],
                        "section_level": section['level'],
                        "content_type": content_type
                    }
                ))

    # Если после всех попыток фрагментов нет, добавляем весь документ как один фрагмент
    if not chunks:
        logger.warning("Не удалось создать фрагменты, добавляем весь документ целиком")
        chunks.append(Document(
            page_content=markdown_content,
            metadata={
                "application_id": application_id,
                "document_id": document_id,
                "section": "Весь документ",
                "section_level": 0,
                "content_type": "text"
            }
        ))

    logger.info(f"Создано {len(chunks)} фрагментов")

    # Выводим статистику
    content_types = {}
    for chunk in chunks:
        content_type = chunk.metadata["content_type"]
        content_types[content_type] = content_types.get(content_type, 0) + 1

    logger.info(f"Статистика типов фрагментов: {content_types}")

    return chunks


# Модифицированный метод search в файле pdf_to_qdrant_direct.py
def test_search():
    """Тестовая функция для проверки поиска"""
    qdrant_manager = QdrantManager(
        collection_name="ppee_applications",
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
                print(f"\nРезультат {i + 1}:")
                print(f"Раздел: {doc.metadata.get('section', 'Неизвестный раздел')}")
                print(f"Тип: {doc.metadata.get('content_type', 'Неизвестно')}")

                # Печатаем первые 200 символов текста
                content = doc.page_content
                if len(content) > 200:
                    content = content[:197] + "..."
                print(f"Содержание: {content}")
                print(f"{'-' * 60}")
        else:
            print("Ничего не найдено")

def main():
    """Функция командной строки для запуска процесса"""
    parser = argparse.ArgumentParser(
        description="Прямая конвертация PDF в Qdrant через docling"
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
        ollama_url=args.ollama_url
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
    else:
        print(f"\nОШИБКА при обработке: {result.get('error', 'Неизвестная ошибка')}")


if __name__ == "__main__":
    main()