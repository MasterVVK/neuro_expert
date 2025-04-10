"""
Конвертер PDF в Markdown с использованием docling
"""

import os
import logging
from typing import List, Optional

# Настройка логирования
logger = logging.getLogger(__name__)

# Проверяем наличие docling
try:
    import docling
    from docling.document_converter import DocumentConverter
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    logger.warning("Библиотека docling не установлена")


class DoclingPDFConverter:
    """Класс для конвертации PDF в Markdown с использованием docling"""

    def __init__(self, preserve_tables: bool = True):
        """
        Инициализирует конвертер PDF в Markdown.

        Args:
            preserve_tables: Сохранять ли таблицы в формате Markdown
        """
        if not DOCLING_AVAILABLE:
            raise ImportError("Библиотека docling не установлена")

        self.preserve_tables = preserve_tables
        self.converter = DocumentConverter()
        logger.info(f"Инициализирован конвертер docling версии {docling.__version__}")

    def convert_pdf_to_markdown(self, pdf_path: str, output_path: Optional[str] = None) -> str:
        """
        Конвертирует PDF в Markdown.

        Args:
            pdf_path: Путь к PDF-файлу
            output_path: Путь для сохранения результата (если None, возвращает текст)

        Returns:
            str: Содержимое в формате Markdown
        """
        logger.info(f"Начинаем конвертацию PDF: {pdf_path}")

        if not os.path.exists(pdf_path):
            logger.error(f"Файл не найден: {pdf_path}")
            return ""

        try:
            # Конвертируем PDF с помощью docling
            result = self.converter.convert(pdf_path)

            # Получаем Markdown представление
            markdown_content = result.document.export_to_markdown()

            # Если указан путь для сохранения
            if output_path:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(markdown_content)
                logger.info(f"Результат сохранен в файл: {output_path}")

            return markdown_content

        except Exception as e:
            logger.error(f"Ошибка при конвертации PDF в Markdown: {str(e)}")
            return ""

    def batch_convert(self, pdf_dir: str, output_dir: str, recursive: bool = False) -> List[str]:
        """
        Выполняет пакетную конвертацию PDF-файлов в директории.

        Args:
            pdf_dir: Путь к директории с PDF-файлами
            output_dir: Путь к директории для результатов
            recursive: Искать файлы рекурсивно в поддиректориях

        Returns:
            List[str]: Список путей к созданным файлам
        """
        if not os.path.exists(pdf_dir):
            logger.error(f"Директория не найдена: {pdf_dir}")
            return []

        # Создаем выходную директорию, если она не существует
        os.makedirs(output_dir, exist_ok=True)

        converted_files = []

        # Функция для обработки директории
        def process_directory(directory):
            nonlocal converted_files

            # Получаем список PDF-файлов
            for entry in os.scandir(directory):
                if entry.is_file() and entry.name.lower().endswith('.pdf'):
                    # Формируем путь для выходного файла
                    relative_path = os.path.relpath(entry.path, pdf_dir)
                    output_path = os.path.join(
                        output_dir,
                        os.path.splitext(relative_path)[0] + '.md'
                    )

                    # Создаем директории, если необходимо
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)

                    # Конвертируем файл
                    logger.info(f"Конвертация {entry.path}")
                    result = self.convert_pdf_to_markdown(entry.path, output_path)

                    if result:
                        converted_files.append(output_path)

                # Рекурсивно обрабатываем поддиректории
                elif entry.is_dir() and recursive:
                    process_directory(entry.path)

        # Начинаем обработку
        process_directory(pdf_dir)

        logger.info(f"Конвертировано файлов: {len(converted_files)}")
        return converted_files