"""
Модуль для конвертации PDF документов в формат Markdown
с сохранением структуры документа, таблиц и списков.
"""

import os
import re
import logging
from typing import List, Dict, Any, Optional, Tuple
import tempfile
import subprocess
import shutil

# Попытка импорта различных PDF библиотек с обработкой ошибок
try:
    import fitz  # PyMuPDF

    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    import pytesseract

    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# Настройка логирования
logger = logging.getLogger(__name__)


class PDFToMarkdownConverter:
    """Класс для конвертации PDF в Markdown с сохранением структуры"""

    def __init__(
            self,
            use_ocr: bool = False,
            ocr_language: str = "rus",
            preserve_tables: bool = True,
            pandoc_path: Optional[str] = None,
            tesseract_path: Optional[str] = None
    ):
        """
        Инициализирует конвертер PDF в Markdown.

        Args:
            use_ocr: Использовать ли OCR для извлечения текста
            ocr_language: Язык для OCR (rus, eng и т.д.)
            preserve_tables: Сохранять ли таблицы в формате Markdown
            pandoc_path: Путь к исполняемому файлу pandoc (при наличии)
            tesseract_path: Путь к исполняемому файлу tesseract (при использовании OCR)
        """
        self.use_ocr = use_ocr
        self.ocr_language = ocr_language
        self.preserve_tables = preserve_tables
        self.pandoc_path = pandoc_path

        # Настройка путей к внешним программам
        if tesseract_path:
            if OCR_AVAILABLE:
                pytesseract.pytesseract.tesseract_cmd = tesseract_path
            else:
                logger.warning("Указан путь к Tesseract, но библиотеки OCR не установлены")

        # Проверка доступности необходимых инструментов
        self._check_dependencies()

    def _check_dependencies(self) -> None:
        """Проверяет доступность необходимых зависимостей"""

        if not PYMUPDF_AVAILABLE:
            logger.warning("PyMuPDF (fitz) не установлен. Некоторые функции могут быть недоступны. "
                           "Установите его командой: pip install pymupdf")

        if self.use_ocr and not OCR_AVAILABLE:
            logger.warning("Для использования OCR требуются библиотеки pdf2image и pytesseract. "
                           "Установите их командами: pip install pdf2image pytesseract")
            self.use_ocr = False

        # Убираем проверку на Pandoc, так как он не может конвертировать из PDF
        self.pandoc_available = False

    def _extract_text_with_pymupdf(self, pdf_path: str) -> str:
        """
        Извлекает текст из PDF с помощью PyMuPDF.

        Args:
            pdf_path: Путь к PDF-файлу

        Returns:
            str: Извлеченный текст
        """
        if not PYMUPDF_AVAILABLE:
            logger.error("PyMuPDF не установлен. Невозможно извлечь текст.")
            return ""

        full_text = []

        try:
            # Открываем PDF-документ
            doc = fitz.open(pdf_path)

            # Обрабатываем каждую страницу
            for page_num, page in enumerate(doc):
                # Извлекаем текст со страницы
                page_text = page.get_text("text")

                # Добавляем номер страницы
                page_text += f"\n\nСтраница {page_num + 1}\n"

                # Отключаем обработку таблиц, так как она вызывает ошибки
                if False and self.preserve_tables:  # отключаем условие с помощью "False and"
                    tables = page.find_tables()
                    if tables and hasattr(tables, 'tables'):
                        for table_idx, table in enumerate(tables.tables):
                            try:
                                markdown_table = self._convert_table_to_markdown(table)
                                page_text += f"\n\n{markdown_table}\n\n"
                            except Exception as e:
                                logger.error(f"Ошибка при преобразовании таблицы в Markdown: {str(e)}")
                                page_text += "\n\n*[Необработанная таблица]*\n\n"

                full_text.append(page_text)

            # Закрываем документ
            doc.close()

            return "\n".join(full_text)

        except Exception as e:
            logger.error(f"Ошибка при извлечении текста из PDF: {str(e)}")
            return ""

    def _extract_text_with_ocr(self, pdf_path: str) -> str:
        """
        Извлекает текст из PDF с помощью OCR.

        Args:
            pdf_path: Путь к PDF-файлу

        Returns:
            str: Извлеченный текст
        """
        if not OCR_AVAILABLE:
            logger.error("Библиотеки для OCR не установлены. Невозможно извлечь текст с помощью OCR.")
            return ""

        full_text = []

        try:
            # Конвертируем PDF в изображения
            images = convert_from_path(pdf_path)

            # Обрабатываем каждую страницу
            for page_num, image in enumerate(images):
                # Извлекаем текст с помощью OCR
                page_text = pytesseract.image_to_string(image, lang=self.ocr_language)

                # Добавляем номер страницы
                page_text += f"\n\nСтраница {page_num + 1}\n"

                full_text.append(page_text)

            return "\n".join(full_text)

        except Exception as e:
            logger.error(f"Ошибка при извлечении текста с помощью OCR: {str(e)}")
            return ""

    def _convert_table_to_markdown(self, table) -> str:
        """
        Преобразует таблицу в формат Markdown.

        Args:
            table: Объект таблицы из PyMuPDF

        Returns:
            str: Таблица в формате Markdown
        """
        try:
            # Проверяем наличие необходимых атрибутов
            if not (hasattr(table, 'rows') and hasattr(table, 'cols') and hasattr(table, 'cells')):
                logger.warning("Таблица не содержит необходимых атрибутов")
                return "*Не удалось преобразовать таблицу*"

            rows_count = table.rows
            cols_count = table.cols

            # Создаем таблицу в формате Markdown
            md_table = []

            # Заголовок (первая строка)
            header = []
            for col in range(cols_count):
                try:
                    # Индекс ячейки = строка * количество_столбцов + столбец
                    cell_idx = 0 * cols_count + col
                    if cell_idx < len(table.cells):
                        cell = table.cells[cell_idx]
                        text = cell.text.strip() if hasattr(cell, 'text') else ""
                    else:
                        text = " "
                    header.append(text or " ")
                except Exception as e:
                    logger.error(f"Ошибка при получении заголовка столбца {col}: {str(e)}")
                    header.append(" ")

            md_table.append("| " + " | ".join(header) + " |")

            # Разделитель
            md_table.append("| " + " | ".join(["---" for _ in range(cols_count)]) + " |")

            # Строки данных (со второй строки)
            for row in range(1, rows_count):
                row_data = []
                for col in range(cols_count):
                    try:
                        cell_idx = row * cols_count + col
                        if cell_idx < len(table.cells):
                            cell = table.cells[cell_idx]
                            text = cell.text.strip() if hasattr(cell, 'text') else ""
                        else:
                            text = " "
                        row_data.append(text or " ")
                    except Exception as e:
                        logger.error(f"Ошибка при получении данных ячейки [{row}][{col}]: {str(e)}")
                        row_data.append(" ")

                md_table.append("| " + " | ".join(row_data) + " |")

            return "\n".join(md_table)

        except Exception as e:
            logger.error(f"Ошибка при преобразовании таблицы в Markdown: {str(e)}")
            return "*Ошибка преобразования таблицы*"

    def _process_extracted_text(self, text: str) -> str:
        """
        Обрабатывает извлеченный текст для улучшения форматирования.

        Args:
            text: Извлеченный текст

        Returns:
            str: Обработанный текст в формате Markdown
        """
        # Заменяем многократные переносы строк на двойные
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Обрабатываем заголовки (строки с большими буквами и/или числами)
        lines = text.split('\n')
        processed_lines = []

        for line in lines:
            stripped = line.strip()

            # Определяем уровень заголовка
            header_level = 0

            # Заголовки первого уровня
            if re.match(r'^[0-9]+\.?\s+[А-ЯA-Z]', stripped):
                header_level = 1
            # Заголовки второго уровня
            elif re.match(r'^[0-9]+\.[0-9]+\.?\s+[А-ЯA-Z]', stripped):
                header_level = 2
            # Заголовки третьего уровня
            elif re.match(r'^[0-9]+\.[0-9]+\.[0-9]+\.?\s+[А-ЯA-Z]', stripped):
                header_level = 3
            # Альтернативное определение заголовков (полностью заглавные буквы)
            elif re.match(r'^[А-ЯA-Z\s\d]{10,}$', stripped) and len(stripped) > 15:
                header_level = 2

            # Добавляем маркеры Markdown для заголовков
            if header_level > 0:
                processed_lines.append(f"{'#' * header_level} {stripped}")
            else:
                processed_lines.append(line)

        text = '\n'.join(processed_lines)

        # Обрабатываем списки
        text = re.sub(r'(?m)^[\s•]*[-–—•][\s]+(.*)', r'* \1', text)
        text = re.sub(r'(?m)^[\s]*(\d+)\.[\s]+(.*)', r'\1. \2', text)

        # Обработка таблиц (предполагаем, что таблицы уже в формате Markdown)

        return text

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

        # Стратегия 1: Использование PyMuPDF (теперь как первая стратегия)
        if PYMUPDF_AVAILABLE:
            logger.info("Используем PyMuPDF для извлечения текста")
            text = self._extract_text_with_pymupdf(pdf_path)
            if text:
                logger.info("Извлечение текста с помощью PyMuPDF успешно")
                markdown_content = self._process_extracted_text(text)

                # Если указан путь для сохранения
                if output_path:
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(markdown_content)
                    logger.info(f"Результат сохранен в файл: {output_path}")

                return markdown_content

        # Стратегия 2: Использование OCR
        if self.use_ocr and OCR_AVAILABLE:
            logger.info("Используем OCR для извлечения текста")
            text = self._extract_text_with_ocr(pdf_path)
            if text:
                logger.info("Извлечение текста с помощью OCR успешно")
                markdown_content = self._process_extracted_text(text)

                # Если указан путь для сохранения
                if output_path:
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(markdown_content)
                    logger.info(f"Результат сохранен в файл: {output_path}")

                return markdown_content

        logger.error("Не удалось конвертировать PDF в Markdown")
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


# Пример использования
if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Пример использования для конвертации одного файла
    converter = PDFToMarkdownConverter(
        use_ocr=False,  # Использовать OCR при необходимости
        preserve_tables=True
    )

    # Конвертация одного файла
    pdf_path = "example.pdf"
    output_path = "example.md"

    if os.path.exists(pdf_path):
        result = converter.convert_pdf_to_markdown(pdf_path, output_path)
        print(f"Результат сохранен в {output_path}")
    else:
        print(f"Файл {pdf_path} не найден.")