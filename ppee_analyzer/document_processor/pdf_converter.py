"""
Модуль для конвертации PDF документов в формат Markdown
с сохранением структуры документа, таблиц и списков.
"""

import os
import logging
import tempfile
from typing import List, Optional

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

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import docling
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False

# Импорт внутренних модулей
from .text_processor import TextProcessor
from .docling_processor import DoclingProcessor

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
            tesseract_path: Optional[str] = None,
            use_docling: bool = True,
            temp_dir: Optional[str] = None
    ):
        """
        Инициализирует конвертер PDF в Markdown.

        Args:
            use_ocr: Использовать ли OCR для извлечения текста
            ocr_language: Язык для OCR (rus, eng и т.д.)
            preserve_tables: Сохранять ли таблицы в формате Markdown
            pandoc_path: Путь к исполняемому файлу pandoc (при наличии)
            tesseract_path: Путь к исполняемому файлу tesseract (при использовании OCR)
            use_docling: Использовать ли docling для распознавания таблиц
            temp_dir: Директория для временных файлов
        """
        self.use_ocr = use_ocr
        self.ocr_language = ocr_language
        self.preserve_tables = preserve_tables
        self.pandoc_path = pandoc_path
        self.use_docling = use_docling and DoclingProcessor.is_available()
        self.temp_dir = temp_dir or tempfile.mkdtemp()

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

        if self.use_docling and not DOCLING_AVAILABLE:
            logger.warning("Библиотека docling не установлена. Улучшенное распознавание таблиц будет недоступно. "
                         "Установите ее командой: pip install docling")
            self.use_docling = False

        if self.use_docling and not PANDAS_AVAILABLE:
            logger.warning("Pandas и NumPy не установлены. Использование docling будет недоступно. "
                          "Установите их командами: pip install pandas numpy")
            self.use_docling = False

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
        table_marks = {}  # Словарь для хранения отметок о позициях таблиц

        try:
            # Открываем PDF-документ
            doc = fitz.open(pdf_path)

            # Обрабатываем каждую страницу
            for page_num, page in enumerate(doc):
                # Извлекаем текст со страницы
                page_text = page.get_text("text")

                # Если включено использование docling для таблиц
                if self.use_docling and self.preserve_tables:
                    # Обрабатываем страницу для поиска таблиц
                    markdown_tables = DoclingProcessor.process_pdf_page(page, self.temp_dir)

                    # Добавляем таблицы в текст
                    for i, table in enumerate(markdown_tables):
                        # Добавляем метку для вставки таблицы
                        table_mark = f"<TABLE_MARK_PAGE_{page_num}_TABLE_{i}>"
                        page_text += f"\n\n{table_mark}\n\n"

                        # Сохраняем таблицу для дальнейшей вставки
                        table_marks[table_mark] = f"\n\n{table}\n\n"

                # Добавляем номер страницы
                page_text += f"\n\nСтраница {page_num + 1}\n"
                full_text.append(page_text)

            # Закрываем документ
            doc.close()

            # Объединяем текст всех страниц
            text = "\n".join(full_text)

            # Заменяем метки таблиц на их содержимое
            for mark, table in table_marks.items():
                text = text.replace(mark, table)

            return text

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
        table_marks = {}  # Словарь для хранения отметок о позициях таблиц

        try:
            # Конвертируем PDF в изображения
            images = convert_from_path(pdf_path)

            # Обрабатываем каждую страницу
            for page_num, image in enumerate(images):
                # Сохраняем изображение во временный файл для обработки docling
                if self.use_docling and self.preserve_tables:
                    img_path = os.path.join(self.temp_dir, f"temp_ocr_page_{page_num}.png")
                    image.save(img_path)

                    # Извлекаем таблицы с помощью docling
                    tables = DoclingProcessor.extract_tables_from_image(img_path)
                    markdown_tables = DoclingProcessor.convert_tables_to_markdown(tables)

                    # Удаляем временный файл
                    os.remove(img_path)

                # Извлекаем текст с помощью OCR
                page_text = pytesseract.image_to_string(image, lang=self.ocr_language)

                # Добавляем таблицы в текст
                if self.use_docling and self.preserve_tables:
                    for i, table in enumerate(markdown_tables):
                        # Добавляем метку для вставки таблицы
                        table_mark = f"<TABLE_MARK_PAGE_{page_num}_TABLE_{i}>"
                        page_text += f"\n\n{table_mark}\n\n"

                        # Сохраняем таблицу для дальнейшей вставки
                        table_marks[table_mark] = f"\n\n{table}\n\n"

                # Добавляем номер страницы
                page_text += f"\n\nСтраница {page_num + 1}\n"
                full_text.append(page_text)

            # Объединяем текст всех страниц
            text = "\n".join(full_text)

            # Заменяем метки таблиц на их содержимое
            for mark, table in table_marks.items():
                text = text.replace(mark, table)

            return text

        except Exception as e:
            logger.error(f"Ошибка при извлечении текста с помощью OCR: {str(e)}")
            return ""

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

        # Создаем директорию для временных файлов, если ее нет
        os.makedirs(self.temp_dir, exist_ok=True)

        # Стратегия 1: Использование PyMuPDF
        text = self._extract_text_with_pymupdf(pdf_path)
        if text:
            logger.info("Извлечение текста с помощью PyMuPDF успешно")

            # Обрабатываем текст через TextProcessor, но отключаем встроенную обработку таблиц,
            # так как мы уже обработали их через docling
            markdown_content = TextProcessor.process_text(text, preserve_tables=False)

            # Если указан путь для сохранения
            if output_path:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(markdown_content)
                logger.info(f"Результат сохранен в файл: {output_path}")

            return markdown_content

        # Стратегия 2: Использование OCR
        if self.use_ocr:
            text = self._extract_text_with_ocr(pdf_path)
            if text:
                logger.info("Извлечение текста с помощью OCR успешно")
                markdown_content = TextProcessor.process_text(text, preserve_tables=False)

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

    def cleanup(self):
        """Удаляет временные файлы"""
        if os.path.exists(self.temp_dir):
            import shutil
            try:
                shutil.rmtree(self.temp_dir)
                logger.debug(f"Временная директория {self.temp_dir} удалена")
            except Exception as e:
                logger.warning(f"Не удалось удалить временную директорию {self.temp_dir}: {str(e)}")


# Пример использования
if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Пример использования для конвертации одного файла
    converter = PDFToMarkdownConverter(
        use_ocr=False,
        preserve_tables=True,
        use_docling=True
    )

    try:
        # Конвертация одного файла
        pdf_path = "example.pdf"
        output_path = "example.md"

        if os.path.exists(pdf_path):
            result = converter.convert_pdf_to_markdown(pdf_path, output_path)
            print(f"Результат сохранен в {output_path}")
        else:
            print(f"Файл {pdf_path} не найден.")
    finally:
        # Удаляем временные файлы
        converter.cleanup()