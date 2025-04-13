"""
Скрипт для конвертации PDF в Markdown с использованием docling
"""

import os
import sys
import argparse
import logging
from typing import List, Optional

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
# Проверяем наличие docling
try:
    import docling
except ImportError:
    logger.error("Библиотека docling не установлена. Установите ее с помощью: pip install docling")
    sys.exit(1)

# Импортируем наш конвертер
try:
    from ppee_analyzer.document_processor import DoclingPDFConverter
except ImportError:
    logger.error("Не удалось импортировать DoclingPDFConverter. Убедитесь, что модуль ppee_analyzer доступен.")
    sys.exit(1)


def main():
    """Основная функция командной строки"""
    parser = argparse.ArgumentParser(
        description="Конвертация PDF документов в Markdown с использованием docling"
    )

    # Группа аргументов для входных данных
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "-f", "--file",
        help="Путь к PDF файлу для конвертации"
    )
    input_group.add_argument(
        "-d", "--directory",
        help="Путь к директории с PDF файлами для пакетной конвертации"
    )

    # Аргументы для выходных данных
    parser.add_argument(
        "-o", "--output",
        help="Путь для сохранения результата (файл или директория)"
    )

    # Дополнительные опции
    parser.add_argument(
        "--no-tables",
        action="store_true",
        help="Отключить сохранение таблиц"
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Рекурсивно обрабатывать поддиректории (для режима директории)"
    )
    parser.add_argument(
        "--describe-images",
        action="store_true",
        help="Включить описание изображений с помощью Ollama"
    )

    args = parser.parse_args()

    # Инициализация конвертера
    try:
        converter = DoclingPDFConverter(
            preserve_tables=not args.no_tables,
            enable_image_description=args.describe_images
        )
    except Exception as e:
        logger.error(f"Ошибка при инициализации конвертера: {str(e)}")
        sys.exit(1)

    # Определение режима работы (файл или директория)
    if args.file:
        # Режим одиночного файла
        if not os.path.exists(args.file):
            logger.error(f"Файл не найден: {args.file}")
            sys.exit(1)

        # Определение выходного пути
        output_path = args.output
        if not output_path:
            output_path = os.path.splitext(args.file)[0] + ".md"

        logger.info(f"Конвертация файла: {args.file} -> {output_path}")

        try:
            # Конвертация файла
            result = converter.convert_pdf_to_markdown(args.file, output_path)

            if result:
                logger.info(f"Конвертация успешно завершена. Результат сохранен в {output_path}")
            else:
                logger.error("Не удалось выполнить конвертацию.")
                sys.exit(1)
        except Exception as e:
            logger.error(f"Ошибка при конвертации: {str(e)}")
            sys.exit(1)

    elif args.directory:
        # Режим пакетной обработки
        if not os.path.exists(args.directory):
            logger.error(f"Директория не найдена: {args.directory}")
            sys.exit(1)

        # Определение выходной директории
        output_dir = args.output
        if not output_dir:
            output_dir = os.path.join(os.path.dirname(args.directory), "markdown_output")

        logger.info(f"Пакетная конвертация: {args.directory} -> {output_dir}")

        try:
            # Выполняем пакетную конвертацию
            converted_files = converter.batch_convert(
                args.directory,
                output_dir,
                recursive=args.recursive
            )

            if converted_files:
                logger.info(f"Пакетная конвертация успешно завершена.")
                logger.info(f"Конвертировано файлов: {len(converted_files)}")
                logger.info(f"Результаты сохранены в {output_dir}")
            else:
                logger.warning("Не удалось конвертировать ни один файл.")
                sys.exit(1)
        except Exception as e:
            logger.error(f"Ошибка при пакетной конвертации: {str(e)}")
            sys.exit(1)


if __name__ == "__main__":
    main()