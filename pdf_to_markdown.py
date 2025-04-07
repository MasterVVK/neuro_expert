#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PDF to Markdown Converter
Простой скрипт для конвертации PDF-документов в Markdown формат
с использованием библиотеки docling и специализированных инструментов для извлечения таблиц.
"""

import os
import sys
import argparse
from typing import Optional


def parse_arguments():
    """
    Обработка аргументов командной строки.
    """
    parser = argparse.ArgumentParser(description='Конвертация PDF в Markdown')
    parser.add_argument('input_file', help='Путь к PDF файлу для конвертации')
    parser.add_argument('-o', '--output', help='Путь для сохранения Markdown файла')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Подробный вывод процесса конвертации')
    parser.add_argument('--table-method', choices=['docling', 'camelot'], default='docling',
                        help="Метод извлечения таблиц: 'docling' (по умолчанию) или 'camelot'")
    return parser.parse_args()


def is_valid_pdf(file_path: str) -> bool:
    """
    Проверяет корректность PDF-файла, используя сигнатуру '%PDF'.

    Args:
        file_path: Путь к файлу.

    Returns:
        True, если файл корректен, иначе False.
    """
    try:
        with open(file_path, 'rb') as f:
            if f.read(4) != b'%PDF':
                print(f"Ошибка: Файл {file_path} не является корректным PDF.")
                return False
        return True
    except Exception as e:
        print(f"Ошибка при проверке PDF: {e}")
        return False


def check_docling_installation():
    """
    Проверяет установлена ли библиотека docling.
    """
    try:
        import docling
        return True
    except ImportError:
        print("Ошибка: Библиотека docling не установлена.")
        print("Установите её с помощью команды: pip install docling")
        return False


def extract_tables_camelot(input_path: str, verbose: bool = False) -> str:
    """
    Извлекает таблицы из PDF с использованием библиотеки Camelot и возвращает их в формате Markdown.
    """
    try:
        import camelot
    except ImportError:
        print("Ошибка: Библиотека Camelot не установлена. Установите её: pip install camelot-py[cv]")
        return ""
    if verbose:
        print(f"Извлечение таблиц с использованием Camelot из: {input_path}")
    try:
        # Пробуем метод 'lattice' для PDF с явными линиями таблиц
        tables = camelot.read_pdf(input_path, pages='all', flavor='lattice')
        if verbose:
            print(f"Найдено таблиц (lattice): {len(tables)}")
    except Exception as e:
        print(f"Ошибка при извлечении таблиц методом lattice: {e}")
        tables = []
    # Если таблицы не найдены методом lattice, пробуем метод stream
    if not tables:
        try:
            tables = camelot.read_pdf(input_path, pages='all', flavor='stream')
            if verbose:
                print(f"Найдено таблиц (stream): {len(tables)}")
        except Exception as e:
            print(f"Ошибка при извлечении таблиц методом stream: {e}")
            return ""
    markdown_tables = ""
    for idx, table in enumerate(tables):
        markdown_tables += f"### Таблица {idx + 1}\n\n"
        markdown_tables += table.df.to_markdown() + "\n\n"
    return markdown_tables


def convert_pdf_to_markdown(input_path: str, output_path: Optional[str] = None,
                            verbose: bool = False, table_method: str = 'docling') -> Optional[str]:
    """
    Конвертирует PDF в Markdown.

    Если выбран метод table_method = 'camelot', таблицы извлекаются с помощью Camelot,
    иначе используется стандартное преобразование через docling.

    Args:
        input_path: Путь к PDF файлу.
        output_path: Путь для сохранения Markdown файла (опционально).
        verbose: Флаг для подробного вывода.
        table_method: Метод извлечения таблиц ('docling' или 'camelot').

    Returns:
        Содержимое Markdown файла или None в случае ошибки.
    """
    if not os.path.isfile(input_path):
        print(f"Ошибка: Файл не найден: {input_path}")
        return None

    if not input_path.lower().endswith('.pdf'):
        print(f"Предупреждение: Файл не имеет расширения .pdf: {input_path}")

    if not is_valid_pdf(input_path):
        return None

    if not output_path:
        output_path = os.path.splitext(input_path)[0] + '.md'

    try:
        markdown_content = ""
        if table_method == 'camelot':
            # Используем специализированное извлечение таблиц с Camelot
            markdown_content = extract_tables_camelot(input_path, verbose)
        else:
            # Используем docling для конвертации всего документа
            from docling.document_converter import DocumentConverter
            if verbose:
                print(f"Конвертация PDF в Markdown с использованием docling: {input_path}")
                print(f"Выходной файл: {output_path}")
            converter = DocumentConverter()
            result = converter.convert(input_path)
            markdown_content = result.document.export_to_markdown()

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        if verbose:
            print(f"Конвертация успешно завершена. Markdown сохранен в: {output_path}")

        return markdown_content

    except ImportError:
        print("Ошибка: Не удалось импортировать необходимые модули для конвертации.")
        return None

    except Exception as e:
        print(f"Ошибка при конвертации: {str(e)}")
        return None


def main():
    """
    Основная функция скрипта.
    """
    args = parse_arguments()

    if not check_docling_installation():
        sys.exit(1)

    result = convert_pdf_to_markdown(args.input_file, args.output, args.verbose, args.table_method)

    if result is None:
        sys.exit(1)
    else:
        if args.verbose:
            print("Готово!")
        sys.exit(0)


if __name__ == "__main__":
    main()
