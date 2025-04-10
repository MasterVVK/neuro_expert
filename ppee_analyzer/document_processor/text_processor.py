"""
Модуль для обработки и форматирования текста в Markdown
"""

import re
import logging

# Настройка логирования
logger = logging.getLogger(__name__)


class TextProcessor:
    """Класс для обработки и форматирования текста"""

    @staticmethod
    def preprocess_text(text: str) -> str:
        """
        Предварительная обработка текста для улучшения распознавания структур.

        Args:
            text: Исходный текст

        Returns:
            str: Предобработанный текст
        """
        # Заменяем множественные пробелы на 2 пробела для лучшего распознавания структур
        text = re.sub(r'[ ]{3,}', '  ', text)

        # Заменяем многократные переносы строк на двойные
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text

    @staticmethod
    def format_headings(text: str) -> str:
        """
        Форматирует заголовки в тексте.

        Args:
            text: Текст для обработки

        Returns:
            str: Текст с отформатированными заголовками
        """
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

            # Исправляем неправильные # внутри текста:
            # Если строка начинается с # и это не заголовок
            elif stripped.startswith("#") and not re.match(r'^#+\s', stripped):
                # Заменяем # на номер или экранируем
                stripped = stripped.replace("#", "\\#", 1)
                processed_lines.append(stripped)
                continue

            # Добавляем маркеры Markdown для заголовков
            if header_level > 0:
                processed_lines.append(f"{'#' * header_level} {stripped}")
            else:
                processed_lines.append(line)

        return '\n'.join(processed_lines)

    @staticmethod
    def format_lists(text: str) -> str:
        """
        Форматирует списки в тексте.

        Args:
            text: Текст для обработки

        Returns:
            str: Текст с отформатированными списками
        """
        # Обрабатываем маркированные списки
        text = re.sub(r'(?m)^[\s•]*[-–—•][\s]+(.*)', r'* \1', text)

        # Обрабатываем нумерованные списки
        text = re.sub(r'(?m)^[\s]*(\d+)\.[\s]+(.*)', r'\1. \2', text)

        return text

    @staticmethod
    def fix_cyrillic(text: str) -> str:
        """
        Исправляет проблемы с кириллическими символами.

        Args:
            text: Текст для обработки

        Returns:
            str: Исправленный текст
        """
        # Исправляем буквы ё и е
        text = text.replace('ѐ', 'ё')
        text = text.replace('є', 'е')

        return text

    @staticmethod
    def format_page_breaks(text: str) -> str:
        """
        Форматирует разрывы страниц.

        Args:
            text: Текст для обработки

        Returns:
            str: Текст с отформатированными разрывами страниц
        """
        # Заменяем маркеры "Страница X" на горизонтальную линию
        text = re.sub(r'\n+Страница \d+\s*\n+', '\n\n---\n\n', text)

        return text

    @staticmethod
    def process_text(text: str, preserve_tables: bool = True) -> str:
        """
        Полная обработка текста для улучшения форматирования.

        Args:
            text: Текст для обработки
            preserve_tables: Сохранять ли таблицы

        Returns:
            str: Обработанный текст в формате Markdown
        """
        # Импортируем TableFormatter здесь, чтобы избежать циклического импорта
        from .table_formatter import TableFormatter

        # Предварительная обработка
        text = TextProcessor.preprocess_text(text)

        # Обработка таблиц, если включено
        if preserve_tables:
            # Применяем разные стратегии обнаружения таблиц
            text = TableFormatter.detect_and_format_tables(text)
            text = TableFormatter.detect_tables_by_delimiters(text)
            text = TableFormatter.detect_and_format_simple_tables(text)

        # Форматирование заголовков
        text = TextProcessor.format_headings(text)

        # Форматирование списков
        text = TextProcessor.format_lists(text)

        # Исправление кириллицы
        text = TextProcessor.fix_cyrillic(text)

        # Форматирование разрывов страниц
        text = TextProcessor.format_page_breaks(text)

        # Постобработка таблиц
        if preserve_tables:
            text = TableFormatter.postprocess_tables(text)

        return text