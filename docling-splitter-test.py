"""
Тестовый скрипт для анализа разделения документа с использованием
существующих компонентов проекта.
"""

import os
import sys
import json
import logging
import argparse
from typing import List, Dict, Any

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Проверка аргументов командной строки
parser = argparse.ArgumentParser(description='Анализ разделения документа')
parser.add_argument('file_path', help='Путь к файлу для анализа (PDF или Markdown)')
parser.add_argument('--chunk-size', type=int, default=1500, help='Размер фрагмента (по умолчанию: 1500)')
parser.add_argument('--app-id', default='test_app', help='ID приложения (по умолчанию: test_app)')
parser.add_argument('--output', help='Путь для сохранения результатов (если не указан, выводится в консоль)')
parser.add_argument('--check-empty-headers', action='store_true', help='Проверка на пустые заголовки')

args = parser.parse_args()

try:
    # Импортируем компоненты проекта
    from ppee_analyzer.document_processor import DoclingPDFConverter, PPEEDocumentSplitter

    # Проверяем существование файла
    if not os.path.exists(args.file_path):
        logger.error(f"Файл не найден: {args.file_path}")
        sys.exit(1)

    # Определяем тип файла
    _, ext = os.path.splitext(args.file_path)
    ext = ext.lower()

    # Путь к файлу для обработки
    processing_path = args.file_path

    # Если это PDF, сначала конвертируем
    if ext == ".pdf":
        logger.info(f"Обнаружен PDF, конвертируем в Markdown: {args.file_path}")
        converter = DoclingPDFConverter()
        md_path = f"{os.path.splitext(args.file_path)[0]}_converted.md"
        converter.convert_pdf_to_markdown(args.file_path, md_path)
        logger.info(f"PDF сконвертирован в Markdown: {md_path}")
        processing_path = md_path

    # Инициализируем разделитель с указанным размером фрагмента
    splitter = PPEEDocumentSplitter(text_chunk_size=args.chunk_size)
    logger.info(f"Инициализирован разделитель с размером фрагмента {args.chunk_size}")

    # Разделяем документ
    chunks = splitter.load_and_process_file(processing_path, args.app_id)
    logger.info(f"Документ разделен на {len(chunks)} фрагментов")

    # Анализируем фрагменты
    results = []
    empty_headers = []

    for i, chunk in enumerate(chunks):
        content = chunk.page_content
        metadata = chunk.metadata

        # Проверка на пустые заголовки
        is_empty_header = False
        if args.check_empty_headers:
            if content.strip().startswith('##') and len(content.strip().split('\n')) <= 1:
                is_empty_header = True
                empty_headers.append({
                    "index": i,
                    "content": content,
                    "section": metadata.get("section", "")
                })

        # Добавляем информацию о фрагменте
        results.append({
            "chunk_index": i,
            "section": metadata.get("section", ""),
            "content_type": metadata.get("content_type", ""),
            "preview": content[:100] + ("..." if len(content) > 100 else ""),
            "full_length": len(content),
            "is_empty_header": is_empty_header,
            "metadata": {k: v for k, v in metadata.items() if k != "page_content"}
        })

    # Выводим статистику
    logger.info(f"Всего фрагментов: {len(chunks)}")

    if args.check_empty_headers:
        logger.info(f"Найдено пустых заголовков: {len(empty_headers)}")
        if empty_headers:
            logger.info("Примеры пустых заголовков:")
            for i, header in enumerate(empty_headers[:3]):  # Показываем только первые 3
                logger.info(f"  {i+1}. '{header['content'].strip()}' (фрагмент {header['index']})")

    # Статистика по типам контента
    content_types = {}
    for chunk in chunks:
        content_type = chunk.metadata.get("content_type", "unknown")
        content_types[content_type] = content_types.get(content_type, 0) + 1

    logger.info("Статистика по типам контента:")
    for content_type, count in content_types.items():
        logger.info(f"  - {content_type}: {count}")

    # Формируем выходные данные
    output_data = {
        "file_path": args.file_path,
        "processing_path": processing_path,
        "chunk_size": args.chunk_size,
        "total_chunks": len(chunks),
        "content_types": content_types,
        "empty_headers_count": len(empty_headers) if args.check_empty_headers else "Not checked",
        "chunks": results
    }

    # Выводим или сохраняем результаты
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Результаты сохранены в файл: {args.output}")
    else:
        print(json.dumps(output_data, ensure_ascii=False, indent=2))

except ImportError as e:
    logger.error(f"Ошибка импорта: {e}")
    sys.exit(1)
except Exception as e:
    logger.exception(f"Ошибка при обработке: {e}")
    sys.exit(1)