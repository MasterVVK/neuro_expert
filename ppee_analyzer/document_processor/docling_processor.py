"""
Модуль для обработки документов с помощью docling
"""

import os
import tempfile
import logging
import pandas as pd

# Настройка логирования
logger = logging.getLogger(__name__)

try:
    import docling

    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False


class DoclingProcessor:
    """Класс для обработки документов с помощью docling"""

    @staticmethod
    def is_available() -> bool:
        """
        Проверяет доступность docling.

        Returns:
            bool: True если docling доступен, иначе False
        """
        return DOCLING_AVAILABLE

    @staticmethod
    def extract_tables_from_image(image_path: str) -> list:
        """
        Извлекает таблицы из изображения с помощью docling.

        Args:
            image_path: Путь к изображению

        Returns:
            list: Список найденных таблиц
        """
        if not DOCLING_AVAILABLE:
            logger.error("Библиотека docling не установлена")
            return []

        try:
            tables = docling.extract_tables(image_path)
            return tables
        except Exception as e:
            logger.error(f"Ошибка при извлечении таблиц с помощью docling: {str(e)}")
            return []

    @staticmethod
    def convert_tables_to_markdown(tables: list) -> list:
        """
        Конвертирует таблицы docling в формат Markdown.

        Args:
            tables: Список таблиц docling

        Returns:
            list: Список таблиц в формате Markdown
        """
        markdown_tables = []

        try:
            for table in tables:
                df = pd.DataFrame(table)

                # Применяем нормализацию к данным таблицы
                df = DoclingProcessor.normalize_table(df)

                # Преобразуем в Markdown
                markdown_table = df.to_markdown(index=False)
                markdown_tables.append(markdown_table)

        except Exception as e:
            logger.error(f"Ошибка при конвертации таблиц в Markdown: {str(e)}")

        return markdown_tables

    @staticmethod
    def normalize_table(df: pd.DataFrame) -> pd.DataFrame:
        """
        Нормализует таблицу данных.

        Args:
            df: DataFrame с таблицей

        Returns:
            pd.DataFrame: Нормализованная таблица
        """
        # Заполнение пустых значений
        df = df.fillna("")

        # Преобразование всех столбцов в строки
        for col in df.columns:
            df[col] = df[col].astype(str)

        # Удаление лишних пробелов
        for col in df.columns:
            df[col] = df[col].str.strip()

        return df

    @staticmethod
    def process_pdf_page(page, temp_dir: str = None) -> list:
        """
        Обрабатывает страницу PDF для извлечения таблиц.

        Args:
            page: Объект страницы PyMuPDF
            temp_dir: Директория для временных файлов

        Returns:
            list: Список таблиц в формате Markdown
        """
        if not DOCLING_AVAILABLE:
            return []

        # Создаем временную директорию, если не указана
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp()
        else:
            os.makedirs(temp_dir, exist_ok=True)

        try:
            # Создаем изображение страницы
            pix = page.get_pixmap()
            page_num = page.number
            img_path = os.path.join(temp_dir, f"temp_page_{page_num}.png")
            pix.save(img_path)

            # Извлекаем таблицы из изображения
            tables = DoclingProcessor.extract_tables_from_image(img_path)

            # Преобразуем таблицы в Markdown
            markdown_tables = DoclingProcessor.convert_tables_to_markdown(tables)

            # Удаляем временный файл
            os.remove(img_path)

            return markdown_tables

        except Exception as e:
            logger.error(f"Ошибка при обработке страницы PDF: {str(e)}")
            return []