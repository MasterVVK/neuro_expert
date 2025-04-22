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
        # Настраиваем docling с отключенной обработкой изображений, но с полноценной обработкой таблиц
        self.pipeline_options = PdfPipelineOptions()
        self.pipeline_options.generate_picture_images = False  # Отключаем обработку картинок
        self.pipeline_options.images_scale = 1  # Минимальный масштаб
        self.pipeline_options.table_structure_options.do_cell_matching = True  # Сохраняем точное сопоставление ячеек таблиц

        # Настраиваем опции PDF
        self.pdf_format_option = PdfFormatOption(
            pipeline_options=self.pipeline_options,
            extract_images=False,  # Отключаем извлечение изображений
            extract_tables=True  # Оставляем только таблицы
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

        # Получаем документ docling
        doc = result.document

        # Получаем markdown представление для анализа
        markdown_content = doc.export_to_markdown()

        # Разделяем по страницам на основе маркеров
        pages = self._split_by_pages(markdown_content)

        # Определяем, какие страницы содержат разделенные таблицы
        merged_pages = self._merge_split_table_pages(pages)

        return merged_pages

    def _split_by_pages(self, markdown_content: str) -> List[Dict[str, Any]]:
        """Разделяет markdown контент по страницам"""
        # В docling страницы обычно разделяются маркерами --- или другими разделителями
        # Здесь мы предполагаем, что есть маркеры страниц

        # Если нет явных маркеров страниц, возвращаем весь контент как одну страницу
        if '---' not in markdown_content:
            return [{
                'page_number': 1,
                'content': markdown_content,
                'has_split_table': False
            }]

        # Разделяем по маркерам страниц
        page_contents = markdown_content.split('---')
        pages = []

        for i, content in enumerate(page_contents):
            if content.strip():
                pages.append({
                    'page_number': i + 1,
                    'content': content.strip(),
                    'has_split_table': False
                })

        return pages

    def _merge_split_table_pages(self, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Объединяет страницы с разделенными таблицами"""
        merged_pages = []
        i = 0

        while i < len(pages):
            current_page = pages[i]
            page_content = current_page['content']
            page_metadata = {
                'page_numbers': [current_page['page_number']],
                'length': len(page_content),
                'has_split_table': False
            }

            # Проверяем, заканчивается ли страница неполной таблицей
            if self._has_incomplete_table(page_content) and i < len(pages) - 1:
                next_page = pages[i + 1]
                # Проверяем, начинается ли следующая страница с продолжения таблицы
                if self._starts_with_table_continuation(next_page['content']):
                    # Объединяем страницы
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

    def _has_incomplete_table(self, content: str) -> bool:
        """Проверяет, заканчивается ли страница неполной таблицей"""
        lines = content.strip().split('\n')
        if not lines:
            return False

        # Проверяем последние строки на признаки таблицы
        last_lines = lines[-5:] if len(lines) > 5 else lines

        # Таблица обычно содержит символы |
        table_lines = [line for line in last_lines if '|' in line]

        if not table_lines:
            return False

        # Проверяем, есть ли в конце страницы строка таблицы без разделителя
        last_line = lines[-1]
        if '|' in last_line and not last_line.strip().endswith('|'):
            return True

        # Проверяем, заканчивается ли страница строкой таблицы
        if table_lines and table_lines[-1] == lines[-1]:
            return True

        return False

    def _starts_with_table_continuation(self, content: str) -> bool:
        """Проверяет, начинается ли страница с продолжения таблицы"""
        lines = content.strip().split('\n')
        if not lines:
            return False

        # Проверяем первые строки на признаки таблицы
        first_lines = lines[:5] if len(lines) > 5 else lines

        # Если первая строка содержит | и не является заголовком таблицы
        if '|' in first_lines[0] and not first_lines[0].strip().startswith('#'):
            return True

        return False

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