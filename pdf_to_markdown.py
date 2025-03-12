#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Улучшенный конвертер PDF в Markdown
Скрипт для конвертации PDF-документов в Markdown формат
с улучшенной поддержкой таблиц и структуры документа.
"""
import os
import sys
import argparse
import re
from typing import Optional, List, Dict, Tuple
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('pdf2md')


def parse_arguments():
    """
    Обработка аргументов командной строки.
    """
    parser = argparse.ArgumentParser(description='Конвертация PDF в Markdown')
    parser.add_argument('input_file', help='Путь к PDF файлу для конвертации')
    parser.add_argument('-o', '--output', help='Путь для сохранения Markdown файла')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Подробный вывод процесса конвертации')
    parser.add_argument('-t', '--tables-only', action='store_true',
                        help='Извлечь только таблицы из документа')
    parser.add_argument('--fix-tables', action='store_true',
                        help='Применить дополнительные исправления для таблиц')
    parser.add_argument('--table-width', type=int, default=80,
                        help='Максимальная ширина таблицы в символах (по умолчанию: 80)')
    parser.add_argument('--backend', choices=['docling', 'pymupdf', 'pdfplumber'], default='docling',
                        help='Выбор библиотеки для извлечения данных из PDF')
    return parser.parse_args()


def check_dependencies(backend='docling'):
    """
    Проверяет установлена ли выбранная библиотека.

    Args:
        backend: Название библиотеки для проверки.

    Returns:
        bool: True если библиотека установлена, иначе False.
    """
    try:
        if backend == 'docling':
            import docling
        elif backend == 'pymupdf':
            import fitz
        elif backend == 'pdfplumber':
            import pdfplumber
        return True
    except ImportError:
        logger.error(f"Ошибка: Библиотека {backend} не установлена.")
        logger.info(f"Установите её с помощью команды: pip install {backend}")
        return False


def fix_markdown_tables(markdown_content: str, max_width: int = 80) -> str:
    """
    Улучшает форматирование таблиц в Markdown.

    Args:
        markdown_content: Исходное содержимое Markdown.
        max_width: Максимальная ширина таблицы в символах.

    Returns:
        Улучшенное содержимое Markdown.
    """
    # Находим все таблицы в markdown
    table_pattern = r'(\|[^\n]+\|\n\|[-:|\s]+\|\n(?:\|[^\n]+\|\n)+)'
    tables = re.findall(table_pattern, markdown_content)

    if not tables:
        return markdown_content

    # Обрабатываем каждую таблицу
    for original_table in tables:
        # Разбиваем таблицу на строки
        table_lines = original_table.strip().split('\n')
        if len(table_lines) < 3:  # Проверяем, что это действительно таблица (заголовок + разделитель + данные)
            continue

        # Анализируем структуру таблицы
        header_line = table_lines[0]
        separator_line = table_lines[1]
        data_lines = table_lines[2:]

        # Получаем все ячейки из строк
        header_cells = [cell.strip() for cell in header_line.split('|')[1:-1]]

        # Определяем оптимальную ширину для каждой колонки
        col_widths = [len(cell) for cell in header_cells]

        # Анализируем данные для определения оптимальной ширины
        for line in data_lines:
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            for i, cell in enumerate(cells):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(cell), 3)  # Минимум 3 символа

        # Проверяем, не превышает ли суммарная ширина максимальную ширину
        total_width = sum(col_widths) + len(col_widths) + 1  # +1 для каждой | и +1 для конечной |
        if total_width > max_width:
            # Пропорционально уменьшаем ширину колонок
            scale_factor = max_width / total_width
            col_widths = [max(3, int(width * scale_factor)) for width in col_widths]

        # Создаем новую таблицу с оптимизированными ширинами
        new_table_lines = []

        # Форматируем заголовок
        header_formatted = '|'
        for i, cell in enumerate(header_cells):
            truncated_cell = cell[:col_widths[i]] if len(cell) > col_widths[i] else cell
            padding = ' ' * (col_widths[i] - len(truncated_cell))
            header_formatted += f" {truncated_cell}{padding} |"
        new_table_lines.append(header_formatted)

        # Форматируем разделитель
        separator_formatted = '|'
        for width in col_widths:
            separator_formatted += f" {'-' * width} |"
        new_table_lines.append(separator_formatted)

        # Форматируем данные
        for line in data_lines:
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            data_formatted = '|'
            for i, cell in enumerate(cells):
                if i < len(col_widths):
                    truncated_cell = cell[:col_widths[i]] if len(cell) > col_widths[i] else cell
                    padding = ' ' * (col_widths[i] - len(truncated_cell))
                    data_formatted += f" {truncated_cell}{padding} |"
            new_table_lines.append(data_formatted)

        # Собираем новую таблицу
        new_table = '\n'.join(new_table_lines)

        # Заменяем оригинальную таблицу на новую
        markdown_content = markdown_content.replace(original_table, new_table + '\n\n')

    return markdown_content


def detect_and_format_headers(text: str) -> str:
    """
    Обнаруживает заголовки и форматирует их согласно Markdown.

    Args:
        text: Исходный текст.

    Returns:
        Отформатированный текст с заголовками Markdown.
    """
    # Шаблон для поиска потенциальных заголовков (короткие строки, ЗАГЛАВНЫЕ буквы, с цифрами и т.д.)
    header_patterns = [
        # Заголовок с номером (например: "1. ВВЕДЕНИЕ")
        r'^(\d+\.\s+[А-Я][А-Я\s\d]+)$',
        # Заголовок с буквой (например: "а) ОБЩИЕ СВЕДЕНИЯ О ПРЕДПРИЯТИИ")
        r'^([а-я]\)\s+[А-Я][А-Я\s\d]+)$',
        # Заголовок без номера (например: "ВВЕДЕНИЕ")
        r'^([А-Я][А-Я\s\d]+)$'
    ]

    lines = text.split('\n')
    processed_lines = []

    for line in lines:
        # Пропускаем пустые строки
        if not line.strip():
            processed_lines.append(line)
            continue

        line_processed = False

        # Проверяем на соответствие шаблонам заголовков
        for i, pattern in enumerate(header_patterns):
            match = re.match(pattern, line.strip())
            if match:
                header_text = match.group(1)
                # Определяем уровень заголовка
                header_level = 2  # По умолчанию уровень 2

                # Если есть номер с точкой, это может быть заголовок уровня 1
                if re.match(r'^\d+\.\s+', header_text):
                    header_level = 1
                # Если начинается с буквы и скобки, это может быть заголовок уровня 3
                elif re.match(r'^[а-я]\)\s+', header_text):
                    header_level = 3

                processed_lines.append('#' * header_level + ' ' + header_text)
                line_processed = True
                break

        if not line_processed:
            processed_lines.append(line)

    return '\n'.join(processed_lines)


def extract_tables_using_docling(input_path: str, verbose: bool = False) -> str:
    """
    Извлекает и форматирует только таблицы из PDF документа с использованием docling.

    Args:
        input_path: Путь к PDF файлу.
        verbose: Флаг для подробного вывода.

    Returns:
        Markdown-представление таблиц.
    """
    try:
        from docling.document_converter import DocumentConverter
        import docling.document.content as content

        if verbose:
            logger.info(f"Извлечение таблиц из PDF: {input_path}")

        # Создаем экземпляр конвертера
        converter = DocumentConverter()

        # Конвертируем PDF
        result = converter.convert(input_path)

        # Извлекаем только таблицы
        markdown_content = ""
        table_count = 0

        for element in result.document.elements:
            if isinstance(element, content.Table):
                table_count += 1
                table_md = element.export_to_markdown()
                markdown_content += f"### Таблица {table_count}\n\n{table_md}\n\n"

        if verbose:
            logger.info(f"Найдено таблиц: {table_count}")

        return markdown_content

    except Exception as e:
        logger.error(f"Ошибка при извлечении таблиц: {str(e)}")
        return ""


def convert_pdf_using_docling(input_path: str, verbose: bool = False, fix_tables: bool = False,
                              table_width: int = 80) -> str:
    """
    Конвертирует PDF в Markdown с использованием docling.

    Args:
        input_path: Путь к PDF файлу.
        verbose: Флаг для подробного вывода.
        fix_tables: Применить дополнительные исправления для таблиц.
        table_width: Максимальная ширина таблицы в символах.

    Returns:
        Содержимое Markdown файла.
    """
    try:
        from docling.document_converter import DocumentConverter

        if verbose:
            logger.info(f"Конвертация PDF в Markdown с использованием docling: {input_path}")

        # Создаем экземпляр конвертера
        converter = DocumentConverter()

        # Конвертируем PDF
        result = converter.convert(input_path)

        # Получаем Markdown представление
        markdown_content = result.document.export_to_markdown()

        # Применяем дополнительные исправления для таблиц, если требуется
        if fix_tables:
            if verbose:
                logger.info("Применение исправлений для таблиц...")
            markdown_content = fix_markdown_tables(markdown_content, table_width)

        # Улучшаем форматирование заголовков
        markdown_content = detect_and_format_headers(markdown_content)

        return markdown_content

    except Exception as e:
        logger.error(f"Ошибка при конвертации с использованием docling: {str(e)}")
        return ""


def convert_pdf_using_pymupdf(input_path: str, verbose: bool = False, fix_tables: bool = False,
                              table_width: int = 80) -> str:
    """
    Конвертирует PDF в Markdown с использованием PyMuPDF (fitz).

    Args:
        input_path: Путь к PDF файлу.
        verbose: Флаг для подробного вывода.
        fix_tables: Применить дополнительные исправления для таблиц.
        table_width: Максимальная ширина таблицы в символах.

    Returns:
        Содержимое Markdown файла.
    """
    try:
        import fitz  # PyMuPDF

        if verbose:
            logger.info(f"Конвертация PDF в Markdown с использованием PyMuPDF: {input_path}")

        markdown_content = ""

        # Открываем PDF документ
        doc = fitz.open(input_path)

        # Обрабатываем каждую страницу
        for page_num, page in enumerate(doc):
            if verbose:
                logger.info(f"Обработка страницы {page_num + 1}/{len(doc)}")

            # Извлекаем текст со страницы
            text = page.get_text()

            # Добавляем номер страницы и текст
            markdown_content += f"\n\n## Страница {page_num + 1}\n\n{text}\n\n"

            # Извлекаем таблицы (если они есть)
            tables = page.find_tables()

            if tables and tables.tables:
                for i, table in enumerate(tables.tables):
                    rows = []
                    # Формируем заголовок таблицы
                    header = "| " + " | ".join([f"Колонка {j + 1}" for j in range(len(table.cells[0]))]) + " |"
                    rows.append(header)

                    # Формируем разделитель
                    separator = "| " + " | ".join(["---" for _ in range(len(table.cells[0]))]) + " |"
                    rows.append(separator)

                    # Формируем строки таблицы
                    for row in table.cells:
                        row_content = "| " + " | ".join([page.get_text("text", cell) for cell in row]) + " |"
                        rows.append(row_content)

                    # Добавляем таблицу в Markdown
                    markdown_content += f"\n\n### Таблица {i + 1} на странице {page_num + 1}\n\n"
                    markdown_content += "\n".join(rows) + "\n\n"

        # Применяем дополнительные исправления для таблиц, если требуется
        if fix_tables:
            if verbose:
                logger.info("Применение исправлений для таблиц...")
            markdown_content = fix_markdown_tables(markdown_content, table_width)

        # Улучшаем форматирование заголовков
        markdown_content = detect_and_format_headers(markdown_content)

        return markdown_content

    except Exception as e:
        logger.error(f"Ошибка при конвертации с использованием PyMuPDF: {str(e)}")
        return ""


def convert_pdf_using_pdfplumber(input_path: str, verbose: bool = False, fix_tables: bool = False,
                                 table_width: int = 80) -> str:
    """
    Конвертирует PDF в Markdown с использованием pdfplumber.

    Args:
        input_path: Путь к PDF файлу.
        verbose: Флаг для подробного вывода.
        fix_tables: Применить дополнительные исправления для таблиц.
        table_width: Максимальная ширина таблицы в символах.

    Returns:
        Содержимое Markdown файла.
    """
    try:
        import pdfplumber

        if verbose:
            logger.info(f"Конвертация PDF в Markdown с использованием pdfplumber: {input_path}")

        markdown_content = ""

        # Открываем PDF документ
        with pdfplumber.open(input_path) as pdf:
            # Обрабатываем каждую страницу
            for page_num, page in enumerate(pdf.pages):
                if verbose:
                    logger.info(f"Обработка страницы {page_num + 1}/{len(pdf.pages)}")

                # Извлекаем текст со страницы
                text = page.extract_text()

                # Добавляем номер страницы и текст
                markdown_content += f"\n\n## Страница {page_num + 1}\n\n{text}\n\n"

                # Извлекаем таблицы
                tables = page.extract_tables()

                if tables:
                    for i, table in enumerate(tables):
                        # Формируем Markdown таблицу
                        md_table = []

                        # Формируем строки таблицы
                        for j, row in enumerate(table):
                            # Заменяем None на пустые строки
                            row = ['' if cell is None else str(cell).strip() for cell in row]

                            # Форматируем строку таблицы
                            row_content = "| " + " | ".join(row) + " |"
                            md_table.append(row_content)

                            # Если это первая строка, добавляем разделитель
                            if j == 0:
                                separator = "| " + " | ".join(["---" for _ in row]) + " |"
                                md_table.append(separator)

                        # Добавляем таблицу в Markdown
                        markdown_content += f"\n\n### Таблица {i + 1} на странице {page_num + 1}\n\n"
                        markdown_content += "\n".join(md_table) + "\n\n"

        # Применяем дополнительные исправления для таблиц, если требуется
        if fix_tables:
            if verbose:
                logger.info("Применение исправлений для таблиц...")
            markdown_content = fix_markdown_tables(markdown_content, table_width)

        # Улучшаем форматирование заголовков
        markdown_content = detect_and_format_headers(markdown_content)

        return markdown_content

    except Exception as e:
        logger.error(f"Ошибка при конвертации с использованием pdfplumber: {str(e)}")
        return ""


def convert_pdf_to_markdown(
        input_path: str,
        output_path: Optional[str] = None,
        verbose: bool = False,
        tables_only: bool = False,
        fix_tables: bool = False,
        table_width: int = 80,
        backend: str = 'docling'
) -> Optional[str]:
    """
    Конвертирует PDF в Markdown.

    Args:
        input_path: Путь к PDF файлу.
        output_path: Путь для сохранения Markdown файла (опционально).
        verbose: Флаг для подробного вывода.
        tables_only: Извлечь только таблицы из документа.
        fix_tables: Применить дополнительные исправления для таблиц.
        table_width: Максимальная ширина таблицы в символах.
        backend: Библиотека для извлечения данных из PDF.

    Returns:
        Содержимое Markdown файла или None в случае ошибки.
    """
    # Проверяем, существует ли входной файл
    if not os.path.isfile(input_path):
        logger.error(f"Ошибка: Файл не найден: {input_path}")
        return None

    # Проверяем расширение файла
    if not input_path.lower().endswith('.pdf'):
        logger.warning(f"Предупреждение: Файл не имеет расширения .pdf: {input_path}")

    # Если выходной путь не указан, формируем его на основе входного
    if not output_path:
        if tables_only:
            output_path = os.path.splitext(input_path)[0] + '_tables.md'
        else:
            output_path = os.path.splitext(input_path)[0] + '.md'

    try:
        if verbose:
            if tables_only:
                logger.info(f"Извлечение таблиц из PDF: {input_path}")
            else:
                logger.info(f"Конвертация PDF в Markdown: {input_path}")
            logger.info(f"Выходной файл: {output_path}")
            logger.info(f"Используемая библиотека: {backend}")

        # Конвертируем PDF в зависимости от выбранной библиотеки
        if tables_only and backend == 'docling':
            markdown_content = extract_tables_using_docling(input_path, verbose)
        elif backend == 'docling':
            markdown_content = convert_pdf_using_docling(input_path, verbose, fix_tables, table_width)
        elif backend == 'pymupdf':
            markdown_content = convert_pdf_using_pymupdf(input_path, verbose, fix_tables, table_width)
        elif backend == 'pdfplumber':
            markdown_content = convert_pdf_using_pdfplumber(input_path, verbose, fix_tables, table_width)
        else:
            logger.error(f"Неподдерживаемый backend: {backend}")
            return None

        if not markdown_content:
            logger.error("Ошибка: Не удалось извлечь содержимое из PDF файла.")
            return None

        # Сохраняем в файл
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        if verbose:
            if tables_only:
                logger.info(f"Извлечение таблиц успешно завершено. Markdown сохранен в: {output_path}")
            else:
                logger.info(f"Конвертация успешно завершена. Markdown сохранен в: {output_path}")

        return markdown_content

    except Exception as e:
        logger.error(f"Ошибка при конвертации: {str(e)}")
        return None


def main():
    """
    Основная функция скрипта.
    """
    # Парсим аргументы командной строки
    args = parse_arguments()

    # Настраиваем уровень логирования
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Проверяем установлена ли выбранная библиотека
    if not check_dependencies(args.backend):
        sys.exit(1)

    # Конвертируем PDF в Markdown
    result = convert_pdf_to_markdown(
        args.input_file,
        args.output,
        args.verbose,
        args.tables_only,
        args.fix_tables,
        args.table_width,
        args.backend
    )

    # Проверяем результат
    if result is None:
        sys.exit(1)
    else:
        if args.verbose:
            logger.info("Готово!")
        sys.exit(0)


if __name__ == "__main__":
    main()