#!/usr/bin/env python3
"""
Скрипт для разделения PDF документа по страницам с объединением разделенных таблиц
"""

import os
import sys
import json
import logging
import argparse
from typing import List, Dict, Any
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Импортируем docling
try:
    import docling
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    DOCLING_AVAILABLE = True
except ImportError:
    logger.error("Библиотека docling не установлена. Скрипт требует docling для работы.")
    sys.exit(1)


class SimplePageSplitter:
    """Класс для разделения документа по страницам с объединением таблиц"""

    def __init__(self):
        # Настраиваем docling для лучшего распознавания таблиц
        self.pipeline_options = PdfPipelineOptions()
        self.pipeline_options.generate_picture_images = True
        self.pipeline_options.images_scale = 2
        self.pipeline_options.table_structure_options.do_cell_matching = True

        # Настраиваем опции PDF
        self.pdf_format_option = PdfFormatOption(
            pipeline_options=self.pipeline_options,
            extract_images=True,
            extract_tables=True
        )

        # Создаем конвертер
        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: self.pdf_format_option
            }
        )

    def extract_and_merge_pages(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Извлекает страницы из PDF файла и объединяет если таблица разделена"""
        logger.info(f"Конвертация PDF через docling: {pdf_path}")
        result = self.converter.convert(pdf_path)

        pages = []
        current_page = []
        current_page_num = 1
        merged_pages = []

        # Сначала извлекаем все страницы
        for item in result.document.items:
            # Проверяем номер страницы
            if hasattr(item, 'page_no') and item.page_no > current_page_num:
                if current_page:
                    pages.append({
                        'page_number': current_page_num,
                        'content': '\n'.join(current_page),
                        'has_split_table': False  # Изначально предполагаем, что нет разделенной таблицы
                    })
                current_page = []
                current_page_num = item.page_no

            # Проверяем, является ли элемент таблицей и продолжается ли она
            if hasattr(item, 'type') and item.type == 'table':
                if hasattr(item, 'is_multipage') and item.is_multipage:
                    # Таблица продолжается на следующей странице
                    if pages:
                        pages[-1]['has_split_table'] = True  # Помечаем предыдущую страницу

            current_page.append(str(item))

        # Добавляем последнюю страницу
        if current_page:
            pages.append({
                'page_number': current_page_num,
                'content': '\n'.join(current_page),
                'has_split_table': False
            })

        # Теперь объединяем страницы с разделенными таблицами
        i = 0
        while i < len(pages):
            current_page = pages[i]
            page_content = current_page['content']
            page_metadata = {
                'page_numbers': [current_page['page_number']],
                'length': len(page_content),
                'has_split_table': current_page.get('has_split_table', False)
            }

            # Проверяем, есть ли разделенная таблица
            if current_page.get('has_split_table', False) and i < len(pages) - 1:
                # Объединяем с следующей страницей, так как таблица продолжается
                next_page = pages[i + 1]
                page_content += '\n' + next_page['content']
                page_metadata['page_numbers'].append(next_page['page_number'])
                page_metadata['table_merged'] = True
                i += 1

            # Добавляем обработанную страницу
            merged_pages.append({
                'content': page_content,
                'metadata': page_metadata
            })

            i += 1

        return merged_pages

    def analyze_pages(self, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Анализирует страницы и возвращает статистику"""
        stats = {
            'total_pages': len(pages),
            'page_sizes': [len(p['content']) for p in pages],
            'merged_tables': 0,
            'original_page_numbers': []
        }

        for page in pages:
            stats['original_page_numbers'].extend(page['metadata']['page_numbers'])

            if page['metadata'].get('table_merged', False):
                stats['merged_tables'] += 1

        stats['original_pages_count'] = len(set(stats['original_page_numbers']))
        return stats


def main():
    parser = argparse.ArgumentParser(
        description='Разделение PDF документа по страницам с объединением разделенных таблиц'
    )
    parser.add_argument('file_path', help='Путь к PDF файлу')
    parser.add_argument('--output', help='Путь для сохранения результатов в JSON')

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

    # Инициализируем разделитель
    splitter = SimplePageSplitter()

    try:
        # Извлекаем и объединяем страницы
        merged_pages = splitter.extract_and_merge_pages(args.file_path)

        # Анализируем результаты
        stats = splitter.analyze_pages(merged_pages)

        # Формируем результат
        result = {
            'file_path': args.file_path,
            'timestamp': datetime.now().isoformat(),
            'statistics': stats,
            'pages': []
        }

        # Добавляем информацию о каждой странице
        for i, page in enumerate(merged_pages):
            result['pages'].append({
                'index': i,
                'page_numbers': page['metadata']['page_numbers'],
                'length': len(page['content']),
                'preview': page['content'][:200] + '...' if len(page['content']) > 200 else page['content'],
                'table_merged': page['metadata'].get('table_merged', False)
            })

        # Выводим или сохраняем результаты
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info(f"Результаты сохранены в файл: {args.output}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

        # Выводим краткую статистику в логи
        logger.info(f"Исходных страниц: {stats['original_pages_count']}")
        logger.info(f"Итоговых страниц: {stats['total_pages']}")
        logger.info(f"Объединено таблиц: {stats['merged_tables']}")

    except Exception as e:
        logger.exception(f"Ошибка при обработке: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()