#!/usr/bin/env python3
"""
Переработанный скрипт для правильного разделения PDF документов по страницам.
Использует анализ структуры документа docling для корректного определения границ страниц.
"""

import os
import sys
import json
import logging
import argparse
import re
from typing import List, Dict, Any, Tuple
from datetime import datetime
from collections import defaultdict

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    import docling
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    DOCLING_AVAILABLE = True
    logger.debug(f"Docling версия: {docling.__version__ if hasattr(docling, '__version__') else 'unknown'}")
except ImportError as e:
    logger.error(f"Ошибка импорта docling: {e}")
    sys.exit(1)


class EnhancedPageSplitter:
    """Улучшенный класс для разделения документа по страницам"""

    def __init__(self, merge_split_tables: bool = True):
        """
        Инициализация splitter'а.

        Args:
            merge_split_tables: Объединять ли разбитые таблицы
        """
        self.merge_split_tables = merge_split_tables
        logger.debug("Инициализация EnhancedPageSplitter")

        # Настраиваем docling для анализа структуры документа
        self.pipeline_options = PdfPipelineOptions()
        self.pipeline_options.generate_picture_images = False
        self.pipeline_options.images_scale = 1
        self.pipeline_options.table_structure_options.do_cell_matching = True

        # Создаем опции для конвертера
        self.pdf_format_option = PdfFormatOption(
            pipeline_options=self.pipeline_options,
            extract_images=False,
            extract_tables=True
        )

        # Инициализируем конвертер
        try:
            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: self.pdf_format_option
                }
            )
            logger.debug("DocumentConverter успешно создан")
        except Exception as e:
            logger.error(f"Ошибка при создании DocumentConverter: {e}", exc_info=True)
            raise

    def _parse_document_structure(self, result) -> List[Dict[str, Any]]:
        """
        Анализирует структуру документа и извлекает элементы с информацией о страницах.

        Args:
            result: Результат конвертации docling

        Returns:
            List[Dict[str, Any]]: Список элементов документа с метаданными
        """
        document_elements = []

        try:
            # Извлекаем все элементы документа
            doc = result.document

            # Пытаемся получить элементы из различных атрибутов
            if hasattr(doc, 'items'):
                items = doc.items
                logger.debug(f"Найдено {len(items)} элементов через атрибут items")

                for item in items:
                    element = {
                        'content': str(item),
                        'page_number': None,
                        'type': getattr(item, 'type', 'unknown'),
                        'is_table': False,
                        'table_continues': False
                    }

                    # Определяем номер страницы
                    if hasattr(item, 'page_no'):
                        element['page_number'] = item.page_no
                    elif hasattr(item, 'metadata') and hasattr(item.metadata, 'page_number'):
                        element['page_number'] = item.metadata.page_number
                    elif hasattr(item, 'properties'):
                        for prop_key in ['page', 'page_no', 'page_number']:
                            if prop_key in item.properties:
                                element['page_number'] = item.properties[prop_key]
                                break

                    # Определяем тип элемента
                    if element['type'] == 'table':
                        element['is_table'] = True

                        # Проверяем, продолжается ли таблица
                        if hasattr(item, 'continues') and item.continues:
                            element['table_continues'] = True

                    document_elements.append(element)

            # Если элементы не найдены через items, пробуем другие атрибуты
            if not document_elements:
                logger.debug("Элементы через items не найдены, проверяем другие атрибуты")

                if hasattr(doc, 'pages'):
                    pages = doc.pages
                    logger.debug(f"Найдено {len(pages)} страниц через атрибут pages")

                    for page_idx, page in enumerate(pages):
                        if hasattr(page, 'elements'):
                            for elem in page.elements:
                                element = {
                                    'content': str(elem),
                                    'page_number': page_idx + 1,
                                    'type': getattr(elem, 'type', 'unknown'),
                                    'is_table': getattr(elem, 'type', 'unknown') == 'table',
                                    'table_continues': False
                                }
                                document_elements.append(element)

            return document_elements

        except Exception as e:
            logger.error(f"Ошибка при анализе структуры документа: {e}", exc_info=True)
            return []

    def _extract_pages_with_metadata(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Извлекает страницы из PDF с сохранением метаданных о структуре.

        Args:
            pdf_path: Путь к PDF файлу

        Returns:
            List[Dict[str, Any]]: Список страниц с метаданными
        """
        logger.info(f"Начинаем анализ PDF файла: {pdf_path}")

        try:
            # Конвертируем документ
            result = self.converter.convert(pdf_path)

            # Анализируем структуру документа
            elements = self._parse_document_structure(result)
            logger.debug(f"Найдено {len(elements)} элементов в документе")

            # Группируем элементы по страницам
            pages_dict = defaultdict(list)

            for elem in elements:
                page_num = elem['page_number']

                # Если номер страницы не определен, используем последний известный
                if page_num is None:
                    if pages_dict:
                        page_num = max(pages_dict.keys())
                    else:
                        page_num = 1

                pages_dict[page_num].append(elem)

            # Преобразуем в список страниц
            pages = []
            for page_num in sorted(pages_dict.keys()):
                page_elements = pages_dict[page_num]

                # Собираем содержимое страницы
                content_parts = []
                has_table = False
                has_split_table = False

                for elem in page_elements:
                    content_parts.append(elem['content'])

                    if elem['is_table']:
                        has_table = True

                    if elem['table_continues']:
                        has_split_table = True

                page = {
                    'page_number': page_num,
                    'content': '\n'.join(content_parts),
                    'has_table': has_table,
                    'has_split_table': has_split_table,
                    'element_count': len(page_elements)
                }

                pages.append(page)

            logger.info(f"Извлечено {len(pages)} страниц из документа")
            return pages

        except Exception as e:
            logger.error(f"Ошибка при извлечении страниц: {e}", exc_info=True)
            raise

    def _merge_split_table_pages(self, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Объединяет страницы с разделенными таблицами.

        Args:
            pages: Список страниц

        Returns:
            List[Dict[str, Any]]: Объединенные страницы
        """
        if not self.merge_split_tables:
            return pages

        merged_pages = []
        i = 0

        while i < len(pages):
            current_page = pages[i]

            # Если таблица продолжается на следующей странице
            if current_page['has_split_table'] and i < len(pages) - 1:
                next_page = pages[i + 1]

                # Проверяем, что следующая страница содержит продолжение таблицы
                if next_page['has_table']:
                    logger.debug(f"Объединяем страницы {current_page['page_number']} и {next_page['page_number']}")

                    # Объединяем содержимое
                    merged_page = {
                        'page_numbers': [current_page['page_number'], next_page['page_number']],
                        'content': current_page['content'] + '\n' + next_page['content'],
                        'merged_table': True
                    }

                    merged_pages.append(merged_page)
                    i += 2  # Пропускаем следующую страницу
                    continue

            # Если нет разделенной таблицы, сохраняем страницу как есть
            page_entry = {
                'page_numbers': [current_page['page_number']],
                'content': current_page['content'],
                'merged_table': False
            }
            merged_pages.append(page_entry)
            i += 1

        return merged_pages

    def analyze_document(self, pdf_path: str) -> Dict[str, Any]:
        """
        Анализирует документ и возвращает результаты.

        Args:
            pdf_path: Путь к PDF файлу

        Returns:
            Dict[str, Any]: Результаты анализа
        """
        # Извлекаем страницы с метаданными
        pages = self._extract_pages_with_metadata(pdf_path)

        # Объединяем разделенные таблицы
        merged_pages = self._merge_split_table_pages(pages)

        # Собираем статистику
        stats = {
            'total_pages': len(merged_pages),
            'page_sizes': [len(p['content']) for p in merged_pages],
            'merged_tables': sum(1 for p in merged_pages if p.get('merged_table', False)),
            'original_page_numbers': []
        }

        # Собираем все исходные номера страниц
        for page in merged_pages:
            stats['original_page_numbers'].extend(page['page_numbers'])

        stats['original_pages_count'] = len(set(stats['original_page_numbers']))

        result = {
            'file_path': pdf_path,
            'timestamp': datetime.now().isoformat(),
            'statistics': stats,
            'pages': []
        }

        # Добавляем информацию о каждой странице
        for i, page in enumerate(merged_pages):
            result['pages'].append({
                'index': i,
                'page_numbers': page['page_numbers'],
                'length': len(page['content']),
                'preview': page['content'][:200] + '...' if len(page['content']) > 200 else page['content'],
                'table_merged': page.get('merged_table', False)
            })

        return result


def main():
    parser = argparse.ArgumentParser(
        description='Улучшенное разделение PDF документа по страницам'
    )
    parser.add_argument('file_path', help='Путь к PDF файлу')
    parser.add_argument('--output', help='Путь для сохранения результатов в JSON')
    parser.add_argument('--merge-tables', action='store_true', default=True, help='Объединять разделенные таблицы')
    parser.add_argument('--no-merge-tables', action='store_false', dest='merge_tables',
                        help='Не объединять разделенные таблицы')

    args = parser.parse_args()

    # Проверяем существование файла
    if not os.path.exists(args.file_path):
        logger.error(f"Файл не найден: {args.file_path}")
        sys.exit(1)

    # Проверяем, что это PDF
    _, ext = os.path.splitext(args.file_path)
    if ext.lower() != '.pdf':
        logger.error("Скрипт поддерживает только PDF файлы")
        sys.exit(1)

    try:
        # Инициализируем разделитель
        splitter = EnhancedPageSplitter(merge_split_tables=args.merge_tables)

        # Анализируем документ
        result = splitter.analyze_document(args.file_path)

        # Выводим или сохраняем результаты
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info(f"Результаты сохранены в файл: {args.output}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

        # Выводим краткую статистику
        stats = result['statistics']
        logger.info(f"Исходных страниц: {stats['original_pages_count']}")
        logger.info(f"Итоговых страниц: {stats['total_pages']}")
        logger.info(f"Объединено таблиц: {stats['merged_tables']}")

    except Exception as e:
        logger.exception(f"Ошибка при обработке: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
