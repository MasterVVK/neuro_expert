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
import fitz  # PyMuPDF
import re

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PDFPageSplitter:
    """Класс для разделения PDF по страницам с объединением разделенных таблиц"""

    def __init__(self):
        pass

    def extract_and_merge_pages(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Извлекает страницы из PDF файла и объединяет если таблица разделена"""
        logger.info(f"Извлечение страниц из PDF: {pdf_path}")

        # Открываем PDF с помощью PyMuPDF
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        logger.info(f"Всего физических страниц в PDF: {total_pages}")

        pages = []

        # Извлекаем текст каждой страницы
        for page_num in range(total_pages):
            page = doc[page_num]
            text = page.get_text("text")  # Извлекаем текст страницы

            pages.append({
                'page_number': page_num + 1,
                'content': text,
                'has_split_table': False
            })

        doc.close()

        # Объединяем страницы с разделенными таблицами
        merged_pages = self._merge_split_table_pages(pages)

        return merged_pages

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

        # Анализируем последние строки страницы
        last_lines = lines[-10:] if len(lines) > 10 else lines

        # Признаки таблицы
        table_indicators = 0
        has_table_structure = False

        for line in last_lines:
            # Проверяем наличие вертикальных разделителей
            if '|' in line:
                has_table_structure = True
                table_indicators += 2

            # Проверяем структуру с несколькими колонками
            cells = re.split(r'\s{3,}|\t', line)
            if len(cells) >= 3 and any(cell.strip() for cell in cells):
                table_indicators += 1

            # Проверяем наличие числовых данных в колонках
            if re.search(r'\d+[.,]\d+|\d{2,}', line):
                table_indicators += 1

        # Если есть признаки таблицы
        if has_table_structure or table_indicators >= 3:
            last_line = lines[-1].strip()

            # Проверяем, что таблица не завершена
            if (not last_line.lower().startswith(('итого', 'всего', 'total'))  # Не итоговая строка
                    and not re.search(r'^[=\-]{10,}$', last_line)):  # Не завершающая линия таблицы
                return True

        return False

    def _starts_with_table_continuation(self, content: str) -> bool:
        """Проверяет, начинается ли страница с продолжения таблицы"""
        lines = content.strip().split('\n')
        if not lines:
            return False

        # Проверяем первые строки
        first_lines = lines[:5] if len(lines) > 5 else lines

        # Не должно быть заголовков в начале
        if first_lines[0].startswith('#') or first_lines[0].isupper():
            return False

        # Признаки продолжения таблицы
        continuation_indicators = 0

        for line in first_lines:
            # Табличная структура
            if '|' in line:
                continuation_indicators += 2

            # Множественные колонки
            cells = re.split(r'\s{3,}|\t', line)
            if len(cells) >= 3 and any(cell.strip() for cell in cells):
                continuation_indicators += 1

            # Числовые данные
            if re.search(r'\d+[.,]\d+|\d{2,}', line):
                continuation_indicators += 1

        return continuation_indicators >= 2

    def analyze_pages(self, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Анализирует страницы и возвращает статистику"""
        stats = {
            'total_pages': len(pages),
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
    splitter = PDFPageSplitter()

    try:
        # Засекаем время
        start_time = datetime.now()

        # Извлекаем и объединяем страницы
        merged_pages = splitter.extract_and_merge_pages(args.file_path)

        # Анализируем результаты
        stats = splitter.analyze_pages(merged_pages)

        # Вычисляем время выполнения
        execution_time = (datetime.now() - start_time).total_seconds()

        # Формируем результат
        result = {
            'file_path': args.file_path,
            'timestamp': datetime.now().isoformat(),
            'execution_time_seconds': execution_time,
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

        # Выводим статистику
        logger.info(f"Время выполнения: {execution_time:.2f} секунд")
        logger.info(f"Исходных страниц: {stats['original_pages_count']}")
        logger.info(f"Итоговых страниц: {stats['total_pages']}")
        logger.info(f"Объединено таблиц: {stats['merged_tables']}")

    except Exception as e:
        logger.exception(f"Ошибка при обработке: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()