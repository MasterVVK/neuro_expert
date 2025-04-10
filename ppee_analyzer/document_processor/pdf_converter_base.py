"""
Базовый модуль для конвертации PDF документов в формат Markdown
"""

import os
import logging
from typing import List, Optional
import tempfile

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

# Настройка логирования
logger = logging.getLogger(__name__)


class PDFConverterBase:
    """Базовый класс для конвертации PDF в Markdown"""

    def __init__(
            self,
            use_ocr: bool = False,
            ocr_language: str = "rus",
            preserve_tables: bool = True,
            pandoc_path: Optional[str] = None,
            tesseract_path: Optional[str] = None,
            use_docling: bool = False
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
        """
        self.use_ocr = use_ocr
        self.ocr_language = ocr_language
        self.preserve_tables = preserve_tables
        self.pandoc_path = pandoc_path
        self.use_docling = use_docling and DOCLING_AVAILABLE

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

        if not PANDAS_AVAILABLE and self.use_docling:
            logger.warning("Pandas и NumPy не установлены. Использование docling будет недоступно. "
                           "Установите их командами: pip install pandas numpy")
            self.use_docling = False

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

                # Если используется docling, сначала пытаемся распознать таблицы
                if self.use_docling and self.preserve_tables and DOCLING_AVAILABLE and PANDAS_AVAILABLE:
                    try:
                        # Создаем временное изображение страницы
                        pix = page.get_pixmap()
                        img_path = f"temp_page_{page_num}.png"
                        pix.save(img_path)

                        # Используем docling для распознавания таблиц
                        tables = docling.extract_tables(img_path)
                        for i, table in enumerate(tables):
                            df = pd.DataFrame(table)
                            markdown_table = df.to_markdown(index=False)
                            # Заменяем часть текста, соответствующую таблице
                            # Здесь должна быть логика определения позиции таблицы в тексте
                            page_text += f"\n\n{markdown_table}\n\n"

                        # Удаляем временный файл
                        os.remove(img_path)
                    except Exception as e:
                        logger.error(f"Ошибка при распознавании таблиц с docling: {str(e)}")

                # Добавляем номер страницы
                page_text += f"\n\nСтраница {page_num + 1}\n"

                # Обработка таблиц стандартным PyMuPDF способом, если docling не используется
                if self.preserve_tables and not self.use_docling:
                    try:
                        tables = page.find_tables()
                        if tables and hasattr(tables, 'tables'):
                            for table_idx, table in enumerate(tables.tables):
                                try:
                                    markdown_table = self._convert_table_to_markdown(table)
                                    page_text += f"\n\n{markdown_table}\n\n"
                                except Exception as e:
                                    logger.error(f"Ошибка при преобразовании таблицы в Markdown: {str(e)}")
                                    page_text += "\n\n*[Необработанная таблица]*\n\n"
                    except Exception as e:
                        logger.error(f"Ошибка при обработке таблиц: {str(e)}")

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