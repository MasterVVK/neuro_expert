#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PDF to Markdown Converter
Простой скрипт для конвертации PDF-документов в Markdown формат
с использованием библиотеки docling.
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
    return parser.parse_args()


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


def convert_pdf_to_markdown(input_path: str, output_path: Optional[str] = None,
                            verbose: bool = False) -> Optional[str]:
    """
    Конвертирует PDF в Markdown.

    Args:
        input_path: Путь к PDF файлу.
        output_path: Путь для сохранения Markdown файла (опционально).
        verbose: Флаг для подробного вывода.

    Returns:
        Содержимое Markdown файла или None в случае ошибки.
    """
    # Проверяем, существует ли входной файл
    if not os.path.isfile(input_path):
        print(f"Ошибка: Файл не найден: {input_path}")
        return None

    # Проверяем расширение файла
    if not input_path.lower().endswith('.pdf'):
        print(f"Предупреждение: Файл не имеет расширения .pdf: {input_path}")

    # Если выходной путь не указан, формируем его на основе входного
    if not output_path:
        output_path = os.path.splitext(input_path)[0] + '.md'

    try:
        # Импортируем docling
        from docling.document_converter import DocumentConverter

        if verbose:
            print(f"Конвертация PDF в Markdown: {input_path}")
            print(f"Выходной файл: {output_path}")

        # Создаем экземпляр конвертера
        converter = DocumentConverter()

        # Конвертируем PDF
        result = converter.convert(input_path)

        # Получаем Markdown представление
        markdown_content = result.document.export_to_markdown()

        # Сохраняем в файл
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        if verbose:
            print(f"Конвертация успешно завершена. Markdown сохранен в: {output_path}")

        return markdown_content

    except ImportError:
        print("Ошибка: Не удалось импортировать docling.document_converter.")
        return None

    except Exception as e:
        print(f"Ошибка при конвертации: {str(e)}")
        return None


def main():
    """
    Основная функция скрипта.
    """
    # Парсим аргументы командной строки
    args = parse_arguments()

    # Проверяем установлена ли библиотека docling
    if not check_docling_installation():
        sys.exit(1)

    # Конвертируем PDF в Markdown
    result = convert_pdf_to_markdown(args.input_file, args.output, args.verbose)

    # Проверяем результат
    if result is None:
        sys.exit(1)
    else:
        if args.verbose:
            print("Готово!")
        sys.exit(0)


if __name__ == "__main__":
    main()