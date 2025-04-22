#!/usr/bin/env python3
"""
Улучшенный тестовый скрипт для анализа разбиения документа по страницам.
Использует возможности docling для обнаружения таблиц, продолжающихся на следующих страницах.
"""

import os
import sys
import json
import logging
import argparse
import tempfile
from typing import List, Dict, Any, Optional
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Импортируем необходимые компоненты
try:
    from ppee_analyzer.document_processor import DoclingPDFConverter
    from langchain_core.documents import Document
    import fitz  # PyMuPDF
except ImportError as e:
    logger.error(f"Ошибка импорта: {e}")
    sys.exit(1)

try:
    import docling
    from docling.datamodel.base_models import InputFormat, PipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    DOCLING_AVAILABLE = True
except ImportError:
    logger.warning("Библиотека docling не установлена. Некоторые функции будут недоступны.")
    DOCLING_AVAILABLE = False


class EnhancedPageSplitter:
    """Класс для улучшенного разбиения документа по страницам с использованием docling"""

    def __init__(self, min_page_size: int = 300, merge_split_tables: bool = True):
        self.min_page_size = min_page_size
        self.merge_split_tables = merge_split_tables

        if DOCLING_AVAILABLE:
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

    def extract_pages_with_docling(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Извлекает страницы из PDF файла с использованием docling"""
        if not DOCLING_AVAILABLE:
            raise ImportError("Библиотека docling не установлена")

        logger.info(f"Конвертация PDF через docling: {pdf_path}")
        result = self.converter.convert(pdf_path)

        pages = []
        current_page = []
        current_page_num = 1

        # Docling предоставляет структурированное представление документа
        # Используем это для обнаружения таблиц, продолжающихся между страницами
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
                    if current_page:
                        pages[-1]['has_split_table'] = True  # Помечаем предыдущую страницу

            current_page.append(str(item))

        # Добавляем последнюю страницу
        if current_page:
            pages.append({
                'page_number': current_page_num,
                'content': '\n'.join(current_page),
                'has_split_table': False
            })

        return pages

    def extract_pages_from_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Извлекает страницы из PDF файла (резервный метод через PyMuPDF)"""
        doc = fitz.open(pdf_path)
        pages = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()

            pages.append({
                'page_number': page_num + 1,
                'content': text,
                'width': page.rect.width,
                'height': page.rect.height,
                'has_split_table': False  # Без docling не можем определить разделенные таблицы
            })

        doc.close()
        return pages

    def detect_content_type(self, content: str) -> str:
        """Определяет тип контента (таблица, текст, список и т.д.)"""
        if '|' in content and content.count('|') > 4:
            return 'table'
        elif any(line.startswith(('* ', '- ', '+ ')) for line in content.split('\n')):
            return 'list'
        elif content.strip().startswith('##'):
            return 'heading'
        else:
            return 'text'

    def process_pages(self, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Обрабатывает страницы с учетом семантики и информации от docling"""
        processed_pages = []

        i = 0
        while i < len(pages):
            current_page = pages[i]
            page_content = current_page['content']
            page_metadata = {
                'page_numbers': [current_page['page_number']],
                'content_type': self.detect_content_type(page_content),
                'length': len(page_content),
                'has_split_table': current_page.get('has_split_table', False)
            }

            # Проверяем, нужно ли объединять с предыдущей страницей (малый размер)
            if len(page_content) < self.min_page_size and processed_pages:
                # Объединяем с предыдущей
                processed_pages[-1]['content'] += '\n\n' + page_content
                processed_pages[-1]['metadata']['page_numbers'].append(current_page['page_number'])
                i += 1
                continue

            # Проверяем, есть ли разделенная таблица
            if self.merge_split_tables and current_page.get('has_split_table', False) and i < len(pages) - 1:
                # Объединяем с следующей страницей, так как таблица продолжается
                next_page = pages[i + 1]
                page_content += '\n' + next_page['content']
                page_metadata['page_numbers'].append(next_page['page_number'])
                page_metadata['merged_table'] = True
                i += 1

            # Добавляем обработанную страницу
            processed_pages.append({
                'content': page_content,
                'metadata': page_metadata
            })

            i += 1

        return processed_pages

    def analyze_pages(self, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Анализирует страницы и возвращает статистику"""
        stats = {
            'total_pages': len(pages),
            'page_sizes': [len(p['content']) for p in pages],
            'content_types': {},
            'merged_pages': 0,
            'tables_merged': 0
        }

        for page in pages:
            content_type = page['metadata']['content_type']
            stats['content_types'][content_type] = stats['content_types'].get(content_type, 0) + 1

            if len(page['metadata']['page_numbers']) > 1:
                stats['merged_pages'] += 1

                if page['metadata'].get('merged_table', False):
                    stats['tables_merged'] += 1

        return stats


def main():
    parser = argparse.ArgumentParser(
        description='Улучшенный анализ разбиения документа по страницам с использованием docling'
    )
    parser.add_argument('file_path', help='Путь к файлу для анализа (PDF или Markdown)')
    parser.add_argument('--min-page-size', type=int, default=300,
                        help='Минимальный размер страницы (по умолчанию: 300)')
    parser.add_argument('--merge-tables', action='store_true',
                        help='Объединять таблицы, разделенные между страницами')
    parser.add_argument('--output', help='Путь для сохранения результатов в JSON')
    parser.add_argument('--use-docling', action='store_true',
                        help='Использовать docling для обнаружения таблиц')

    args = parser.parse_args()

    # Проверяем существование файла
    if not os.path.exists(args.file_path):
        logger.error(f"Файл не найден: {args.file_path}")
        sys.exit(1)

    # Определяем тип файла
    _, ext = os.path.splitext(args.file_path)
    ext = ext.lower()

    # Инициализируем разделитель по страницам
    splitter = EnhancedPageSplitter(
        min_page_size=args.min_page_size,
        merge_split_tables=args.merge_tables
    )

    try:
        # Извлекаем страницы в зависимости от типа файла
        if ext == '.pdf':
            if args.use_docling and DOCLING_AVAILABLE:
                # Используем docling для лучшего обнаружения таблиц
                pages = splitter.extract_pages_with_docling(args.file_path)
            else:
                # Извлекаем страницы напрямую из PDF
                pages = splitter.extract_pages_from_pdf(args.file_path)
        else:
            logger.error("Поддерживаются только PDF файлы")
            sys.exit(1)

        # Обрабатываем страницы
        processed_pages = splitter.process_pages(pages)

        # Анализируем результаты
        stats = splitter.analyze_pages(processed_pages)

        # Формируем результат
        result = {
            'file_path': args.file_path,
            'timestamp': datetime.now().isoformat(),
            'settings': {
                'min_page_size': args.min_page_size,
                'merge_tables': args.merge_tables,
                'used_docling': args.use_docling and DOCLING_AVAILABLE
            },
            'statistics': stats,
            'pages': []
        }

        # Добавляем информацию о каждой странице
        for i, page in enumerate(processed_pages):
            result['pages'].append({
                'index': i,
                'page_numbers': page['metadata']['page_numbers'],
                'content_type': page['metadata']['content_type'],
                'length': len(page['content']),
                'preview': page['content'][:200] + '...' if len(page['content']) > 200 else page['content'],
                'merged_table': page['metadata'].get('merged_table', False),
                'has_split_table': page['metadata'].get('has_split_table', False)
            })

        # Выводим или сохраняем результаты
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info(f"Результаты сохранены в файл: {args.output}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

        # Выводим краткую статистику в логи
        logger.info(f"Всего страниц: {stats['total_pages']}")
        logger.info(f"Объединено страниц: {stats['merged_pages']}")
        logger.info(f"Объединено таблиц: {stats['tables_merged']}")
        logger.info("Типы контента:")
        for content_type, count in stats['content_types'].items():
            logger.info(f"  - {content_type}: {count}")

    except Exception as e:
        logger.exception(f"Ошибка при обработке: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()