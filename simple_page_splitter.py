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

# Настройка детального логирования
logging.basicConfig(
    level=logging.DEBUG,  # Включаем DEBUG уровень
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Включаем дебаг для docling
docling_logger = logging.getLogger('docling')
docling_logger.setLevel(logging.DEBUG)

# Импортируем docling
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


class SimplePageSplitter:
    """Класс для разделения документа по страницам с объединением таблиц"""

    def __init__(self):
        logger.debug("Инициализация SimplePageSplitter")

        # Настраиваем docling с отключенной обработкой изображений
        self.pipeline_options = PdfPipelineOptions()
        self.pipeline_options.generate_picture_images = False
        self.pipeline_options.images_scale = 1
        self.pipeline_options.table_structure_options.do_cell_matching = True

        logger.debug(f"Pipeline options: generate_picture_images={self.pipeline_options.generate_picture_images}, "
                     f"images_scale={self.pipeline_options.images_scale}, "
                     f"do_cell_matching={self.pipeline_options.table_structure_options.do_cell_matching}")

        # Настраиваем опции PDF
        self.pdf_format_option = PdfFormatOption(
            pipeline_options=self.pipeline_options,
            extract_images=False,
            extract_tables=True
        )

        logger.debug("Создаем DocumentConverter")

        try:
            # Создаем конвертер
            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: self.pdf_format_option
                }
            )
            logger.debug("DocumentConverter успешно создан")
        except Exception as e:
            logger.error(f"Ошибка при создании DocumentConverter: {e}", exc_info=True)
            raise

    def extract_and_merge_pages(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Извлекает страницы из PDF файла и объединяет если таблица разделена"""
        logger.info(f"Начинаем конвертацию PDF через docling: {pdf_path}")

        # Проверяем файл
        if not os.path.exists(pdf_path):
            logger.error(f"Файл не существует: {pdf_path}")
            raise FileNotFoundError(f"Файл не найден: {pdf_path}")

        file_size = os.path.getsize(pdf_path)
        logger.debug(f"Размер файла: {file_size} байт")

        try:
            logger.debug("Вызываем converter.convert()")
            result = self.converter.convert(pdf_path)
            logger.debug(f"Результат конвертации получен: {type(result)}")

            # Проверяем структуру результата
            if hasattr(result, 'document'):
                logger.debug(f"result.document присутствует: {type(result.document)}")
            else:
                logger.error("result.document отсутствует")
                logger.debug(f"Доступные атрибуты result: {dir(result)}")

            # Получаем документ docling
            doc = result.document
            logger.debug(f"Тип документа: {type(doc)}")
            logger.debug(f"Доступные атрибуты документа: {dir(doc)}")

            # Получаем markdown представление
            logger.debug("Экспортируем в markdown")
            markdown_content = doc.export_to_markdown()
            logger.debug(f"Markdown получен, длина: {len(markdown_content)}")

            # Печатаем первые 500 символов для диагностики
            logger.debug(f"Начало markdown: {markdown_content[:500]}")

            # Разделяем по страницам
            pages = self._split_by_pages(markdown_content)
            logger.debug(f"Получено страниц: {len(pages)}")

            # Объединяем разделенные таблицы
            merged_pages = self._merge_split_table_pages(pages)
            logger.debug(f"После объединения таблиц: {len(merged_pages)} страниц")

            return merged_pages

        except Exception as e:
            logger.error(f"Ошибка при конвертации: {e}", exc_info=True)
            raise

    def _split_by_pages(self, markdown_content: str) -> List[Dict[str, Any]]:
        """Разделяет markdown контент по страницам"""
        logger.debug("Начинаем разделение по страницам")

        # Проверяем наличие разделителей
        if '---' in markdown_content:
            logger.debug("Найдены разделители '---'")
            page_contents = markdown_content.split('---')
        else:
            logger.debug("Разделители '---' не найдены, ищем альтернативные разделители")
            # Пробуем другие разделители
            if '\f' in markdown_content:  # Form feed character
                logger.debug("Найден символ form feed")
                page_contents = markdown_content.split('\f')
            else:
                logger.debug("Разделители не найдены, возвращаем весь контент как одну страницу")
                page_contents = [markdown_content]

        pages = []

        for i, content in enumerate(page_contents):
            if content.strip():
                pages.append({
                    'page_number': i + 1,
                    'content': content.strip(),
                    'has_split_table': False
                })
                logger.debug(f"Страница {i + 1}: {len(content)} символов")

        return pages

    def _merge_split_table_pages(self, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Объединяет страницы с разделенными таблицами"""
        logger.debug("Начинаем объединение страниц с разделенными таблицами")
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

            # Проверяем на разделенную таблицу
            if self._has_incomplete_table(page_content) and i < len(pages) - 1:
                next_page = pages[i + 1]
                if self._starts_with_table_continuation(next_page['content']):
                    logger.debug(
                        f"Обнаружена разделенная таблица между страницами {current_page['page_number']} и {next_page['page_number']}")
                    page_content += '\n' + next_page['content']
                    page_metadata['page_numbers'].append(next_page['page_number'])
                    page_metadata['table_merged'] = True
                    i += 1

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

        last_lines = lines[-5:] if len(lines) > 5 else lines
        table_lines = [line for line in last_lines if '|' in line]

        if not table_lines:
            return False

        last_line = lines[-1]
        if '|' in last_line and not last_line.strip().endswith('|'):
            logger.debug(f"Найдена неполная таблица, последняя строка: {last_line}")
            return True

        if table_lines and table_lines[-1] == lines[-1]:
            logger.debug(f"Найдена таблица в конце страницы: {table_lines[-1]}")
            return True

        return False

    def _starts_with_table_continuation(self, content: str) -> bool:
        """Проверяет, начинается ли страница с продолжения таблицы"""
        lines = content.strip().split('\n')
        if not lines:
            return False

        first_lines = lines[:5] if len(lines) > 5 else lines

        if '|' in first_lines[0] and not first_lines[0].strip().startswith('#'):
            logger.debug(f"Найдено продолжение таблицы, первая строка: {first_lines[0]}")
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

    logger.debug(f"Аргументы: file_path={args.file_path}, output={args.output}")

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
        splitter = SimplePageSplitter()

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

        # Выводим краткую статистику
        logger.info(f"Исходных страниц: {stats['original_pages_count']}")
        logger.info(f"Итоговых страниц: {stats['total_pages']}")
        logger.info(f"Объединено таблиц: {stats['merged_tables']}")

    except Exception as e:
        logger.exception(f"Ошибка при обработке: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()