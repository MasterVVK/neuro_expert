#!/usr/bin/env python3
"""
Скрипт для семантического разделения PDF документов с использованием библиотеки semantic_chunker.
Повторяет функциональность оригинального semantic_pdf_chunker.py.
"""

import os
import sys
import json
import logging
import argparse
import time
from pathlib import Path
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Попытка импорта модуля semantic_chunker
try:
    # Импортируем наш новый модуль
    from ppee_analyzer.semantic_chunker import SemanticChunker
except ImportError as e:
    logger.error(f"Ошибка импорта: {e}")
    logger.error("Убедитесь, что модуль ppee_analyzer.semantic_chunker установлен и доступен")
    sys.exit(1)


# Проверка наличия CUDA
def check_cuda_availability():
    """Проверяет наличие CUDA для работы с GPU"""
    try:
        import torch

        has_cuda = torch.cuda.is_available()
        if has_cuda:
            logger.info(f"CUDA доступна. Используется GPU: {torch.cuda.get_device_name(0)}")
        else:
            logger.info("CUDA недоступна. Используется CPU.")
        return has_cuda
    except ImportError:
        logger.info("PyTorch не установлен. Используется CPU.")
        return False


def process_document(pdf_path: str, output_dir: str = "data/md", use_gpu: bool = None):
    """
    Обрабатывает PDF документ и сохраняет результаты.

    Args:
        pdf_path: Путь к PDF файлу
        output_dir: Директория для сохранения результатов
        use_gpu: Использовать ли GPU (None - автоопределение)
    """
    # Проверяем, существует ли файл
    if not os.path.exists(pdf_path):
        logger.error(f"Файл {pdf_path} не найден. Пожалуйста, укажите правильный путь.")
        logger.error(f"Текущая директория: {os.getcwd()}")
        sys.exit(1)

    logger.info(f"Обработка файла: {pdf_path}")

    try:
        start_time = time.time()

        # Создаем экземпляр чанкера с GPU если доступно
        chunker = SemanticChunker(use_gpu=use_gpu)

        # Шаг 1: Извлекаем смысловые блоки
        chunks = chunker.extract_chunks(pdf_path)
        logger.info(f"Найдено {len(chunks)} начальных блоков")

        # Шаг 2: Обрабатываем таблицы
        processed_chunks = chunker.post_process_tables(chunks)
        logger.info(f"После обработки таблиц: {len(processed_chunks)} блоков")

        # Шаг 3: Группируем короткие блоки
        grouped_chunks = chunker.group_semantic_chunks(processed_chunks)
        logger.info(f"После группировки: {len(grouped_chunks)} финальных блоков")

        end_time = time.time()
        logger.info(f"Время обработки: {end_time - start_time:.2f} секунд")

        # Создаем папку для сохранения чанков
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        # Сохраняем все чанки в JSON для анализа структуры
        with open(output_dir_path / "all_chunks.json", "w", encoding="utf-8") as f:
            json.dump(grouped_chunks, f, ensure_ascii=False, indent=2)

        # Сохраняем каждый чанк в отдельный файл
        for i, chunk in enumerate(grouped_chunks):
            chunk_type = chunk.get('type', 'unknown')
            page = chunk.get('page', 'no_page')

            # Создаем имя файла
            filename = f"chunk_{i + 1:03d}_{chunk_type}_page_{page}.md"

            # Сохраняем метаданные и контент в markdown формате
            with open(output_dir_path / filename, "w", encoding="utf-8") as f:
                f.write(f"# Chunk {i + 1}\n\n")
                f.write(f"## Metadata\n\n")
                f.write(f"- **Type**: {chunk_type}\n")
                f.write(f"- **Page**: {page}\n")

                if chunk.get("heading"):
                    f.write(f"- **Heading**: {chunk['heading']}\n")

                if chunk_type == "table" and chunk.get("table_id"):
                    f.write(f"- **Table ID**: {chunk['table_id']}\n")
                    if chunk.get("pages"):
                        f.write(f"- **Pages**: {chunk['pages']}\n")

                f.write("\n## Content\n\n")

                # Для таблиц используем markdown table или code block
                if chunk_type == "table":
                    if chunk["content"].startswith("|"):
                        # Уже в markdown формате
                        f.write(chunk["content"])
                    else:
                        # Оборачиваем в code block
                        f.write("```\n")
                        f.write(chunk["content"])
                        f.write("\n```")
                else:
                    f.write(chunk["content"])

                f.write("\n")

        logger.info(f"\nЧанки сохранены в папку: {output_dir_path}")

        # Создаем сводный файл с информацией о всех чанках
        with open(output_dir_path / "summary.md", "w", encoding="utf-8") as f:
            f.write(f"# Сводная информация о чанках\n\n")
            f.write(f"## Общая статистика\n\n")
            f.write(f"- **Всего чанков**: {len(grouped_chunks)}\n")
            f.write(f"- **Время обработки**: {end_time - start_time:.2f} секунд\n\n")

            # Статистика по типам
            type_counts = {}
            for chunk in grouped_chunks:
                chunk_type = chunk.get('type', 'unknown')
                type_counts[chunk_type] = type_counts.get(chunk_type, 0) + 1

            f.write("## Статистика по типам\n\n")
            for chunk_type, count in type_counts.items():
                f.write(f"- **{chunk_type}**: {count}\n")

            f.write("\n## Список всех чанков\n\n")

            for i, chunk in enumerate(grouped_chunks):
                chunk_type = chunk.get('type', 'unknown')
                page = chunk.get('page', 'no_page')
                content_preview = chunk['content'][:100].replace('\n', ' ')

                f.write(f"### {i + 1}. Chunk {i + 1}\n\n")
                f.write(f"- **Тип**: {chunk_type}\n")
                f.write(f"- **Страница**: {page}\n")
                if chunk.get("heading"):
                    f.write(f"- **Заголовок**: {chunk['heading']}\n")
                f.write(f"- **Начало содержимого**: {content_preview}...\n\n")

        logger.info(f"Создан файл summary.md с общей информацией о чанках")

    except Exception as e:
        logger.error(f"Ошибка при обработке файла: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Основная функция для запуска скрипта из командной строки"""
    parser = argparse.ArgumentParser(
        description='Семантическое разделение PDF документов с использованием библиотеки semantic_chunker'
    )
    parser.add_argument('pdf_path', help='Путь к PDF файлу')
    parser.add_argument('--output', default='data/md', help='Директория для сохранения результатов')
    parser.add_argument('--use-gpu', action='store_true', help='Использовать GPU (если доступно)')
    parser.add_argument('--cpu-only', action='store_true', help='Использовать только CPU')

    args = parser.parse_args()

    # Определяем, использовать ли GPU
    use_gpu = None  # Автоопределение по умолчанию
    if args.use_gpu:
        use_gpu = True
    elif args.cpu_only:
        use_gpu = False

    # Обрабатываем документ
    process_document(args.pdf_path, args.output, use_gpu)


if __name__ == "__main__":
    main()