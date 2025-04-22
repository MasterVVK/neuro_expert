# semantic_pdf_chunker.py

import os
import warnings

# Устанавливаем переменную окружения для RTX 3090 (архитектура Ampere)
os.environ['TORCH_CUDA_ARCH_LIST'] = "8.6"
# Подавляем предупреждение о CUDA архитектуре
warnings.filterwarnings("ignore", message="TORCH_CUDA_ARCH_LIST is not set")

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    AcceleratorOptions,
    PdfPipelineOptions,
)
from typing import List, Dict
import re
import uuid


class SemanticChunker:
    def __init__(self, use_gpu: bool = True, threads: int = 8):
        # Настраиваем опции ускорителя
        accelerator_options = AcceleratorOptions(
            num_threads=threads,
            device=AcceleratorDevice.CUDA if use_gpu else AcceleratorDevice.CPU
        )

        # Настраиваем опции обработки PDF
        pipeline_options = PdfPipelineOptions()
        pipeline_options.accelerator_options = accelerator_options
        pipeline_options.do_table_structure = True
        pipeline_options.table_structure_options.do_cell_matching = True

        # Если используем GPU, включаем Flash Attention 2 для лучшей производительности
        if use_gpu:
            pipeline_options.accelerator_options.cuda_use_flash_attention2 = True

        # Настраиваем конвертер Docling
        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options
                )
            }
        )

    def extract_chunks(self, pdf_path: str) -> List[Dict]:
        """Извлекает и структурирует документ по смысловым блокам"""

        # Конвертируем PDF с помощью Docling
        result = self.converter.convert(pdf_path)
        document = result.document

        chunks = []
        current_chunk = {
            "content": "",
            "type": None,
            "page": None,
            "heading": None,
            "table_id": None
        }

        current_table = None
        last_caption = None  # Для хранения последнего заголовка таблицы

        # Словарь для отслеживания статистики по страницам
        pages_encountered = set()

        # Проходим по элементам документа
        for i, (element, level) in enumerate(document.iterate_items()):
            # Определяем страницу
            current_page = None
            if hasattr(element, 'prov') and element.prov and len(element.prov) > 0:
                current_page = element.prov[0].page_no
                pages_encountered.add(current_page)

            # Отладочный вывод для начальных элементов
            if i < 30 or (current_page and current_page <= 5):
                print(
                    f"Element {i}: page={current_page}, label={element.label if hasattr(element, 'label') else 'no label'}, content preview={str(element)[:50] if hasattr(element, '__str__') else 'no content'}")

            # Проверяем, есть ли у элемента атрибут label
            if not hasattr(element, 'label'):
                # Если нет label, но есть текст, добавляем как неопределенный тип
                if hasattr(element, 'text') and element.text.strip():
                    if current_chunk["content"]:
                        chunks.append(current_chunk.copy())

                    current_chunk = {
                        "content": element.text,
                        "type": "unknown",
                        "page": current_page,
                        "heading": None,
                        "table_id": None
                    }
                continue

            # Определяем тип элемента
            if element.label == "caption" or (
                    element.label == "text" and hasattr(element, 'text') and re.match(r'^Таблица\s*\d+[.:]',
                                                                                      element.text, re.IGNORECASE)):
                # Это заголовок таблицы
                if current_chunk["content"] and current_chunk["type"] != "table":
                    chunks.append(current_chunk.copy())

                last_caption = element.text if hasattr(element, 'text') else str(element)
                current_chunk = {
                    "content": "",
                    "type": None,
                    "page": current_page,
                    "heading": None,
                    "table_id": None
                }

            elif element.label == "table":
                # Обработка таблиц
                table_id = element.self_ref if hasattr(element, 'self_ref') else str(uuid.uuid4())

                # Получаем контент таблицы
                table_content = ""
                try:
                    # Пробуем экспортировать в markdown с передачей документа
                    table_content = element.export_to_markdown(doc=document)
                except:
                    try:
                        # Если не получилось, пробуем DataFrame
                        df = element.export_to_dataframe()
                        table_content = df.to_string()
                    except:
                        # В крайнем случае используем строковое представление data
                        table_content = str(element.data) if hasattr(element, 'data') else str(element)

                # Если есть caption, добавляем его
                if hasattr(element, 'caption_text'):
                    try:
                        caption = element.caption_text(document)
                        if caption and not last_caption:
                            last_caption = caption
                    except:
                        pass

                # Всегда создаем новый чанк для таблицы
                if current_chunk["content"]:
                    chunks.append(current_chunk.copy())

                # Создаем чанк для таблицы
                current_chunk = {
                    "content": table_content,
                    "type": "table",
                    "page": current_page,
                    "heading": last_caption,  # Привязываем заголовок к таблице
                    "table_id": table_id,
                    "pages": [current_page] if current_page else []
                }

                # Добавляем этот чанк таблицы
                chunks.append(current_chunk.copy())

                # Сбрасываем current_chunk и table-related переменные
                current_chunk = {
                    "content": "",
                    "type": None,
                    "page": None,
                    "heading": None,
                    "table_id": None
                }
                current_table = None
                last_caption = None

            elif element.label == "heading" or element.label == "section_header":
                # Если это заголовок раздела, начинаем новый чанк
                if current_chunk["content"]:
                    chunks.append(current_chunk.copy())

                current_table = None  # Сбрасываем идентификатор таблицы
                last_caption = None  # Сбрасываем заголовок таблицы
                current_chunk = {
                    "content": element.text if hasattr(element, 'text') else str(element),
                    "type": "heading",
                    "page": current_page,
                    "heading": element.text if hasattr(element, 'text') else str(element),
                    "level": level,
                    "table_id": None
                }

            elif element.label == "document_index":
                # Обработка оглавления как отдельного типа
                if current_chunk["content"]:
                    chunks.append(current_chunk.copy())

                # Пробуем получить контент оглавления
                content = ""
                if hasattr(element, 'text'):
                    content = element.text
                elif hasattr(element, 'export_to_markdown'):
                    try:
                        content = element.export_to_markdown(doc=document)
                    except:
                        content = str(element)
                else:
                    content = str(element)

                current_chunk = {
                    "content": content,
                    "type": "document_index",
                    "page": current_page,
                    "heading": "Оглавление",
                    "table_id": None
                }
                chunks.append(current_chunk.copy())

                # Сбрасываем current_chunk
                current_chunk = {
                    "content": "",
                    "type": None,
                    "page": None,
                    "heading": None,
                    "table_id": None
                }

            elif element.label == "text" or element.label == "paragraph" or element.label == "list-item":
                # Проверяем, не является ли текст подписью к таблице
                if hasattr(element, 'text') and re.match(r'^Таблица\s*\d+[.:]\s*', element.text, re.IGNORECASE):
                    # Это заголовок таблицы
                    if current_chunk["content"]:
                        chunks.append(current_chunk.copy())

                    last_caption = element.text
                    continue

                # Обычный текст или параграф
                current_table = None  # Сбрасываем идентификатор таблицы
                text_content = element.text if hasattr(element, 'text') else str(element)

                if current_chunk["type"] == "heading":
                    # Если предыдущий элемент был заголовком, добавляем текст к нему
                    current_chunk["content"] += "\n\n" + text_content
                    current_chunk["type"] = "section"
                elif current_chunk["type"] == "section":
                    # Если уже идет секция, продолжаем добавлять текст
                    current_chunk["content"] += "\n\n" + text_content
                else:
                    # Начинаем новый текстовый блок
                    if current_chunk["content"]:
                        chunks.append(current_chunk.copy())

                    current_chunk = {
                        "content": text_content,
                        "type": "paragraph" if element.label == "paragraph" else element.label,
                        "page": current_page,
                        "heading": None,
                        "table_id": None
                    }

            else:
                # Для всех остальных типов элементов
                if hasattr(element, 'text') and element.text.strip():
                    if current_chunk["content"]:
                        chunks.append(current_chunk.copy())

                    current_chunk = {
                        "content": element.text,
                        "type": element.label,
                        "page": current_page,
                        "heading": None,
                        "table_id": None
                    }

        # Добавляем последний чанк
        if current_chunk["content"]:
            chunks.append(current_chunk)

        print(f"Обработано страниц: {sorted(list(pages_encountered))}")

        return chunks

    def group_semantic_chunks(self, chunks: List[Dict], min_length: int = 200) -> List[Dict]:
        """
        Объединяет все чанки с одной страницы с учетом продолжения таблиц
        """
        grouped_chunks = []
        current_page_chunks = []
        current_page = None
        last_table_caption = None

        # Проверяем, является ли блок продолжением таблицы
        def is_likely_table_continuation(content: str) -> bool:
            # Признаки продолжения таблицы
            table_indicators = [
                r'\d+\.\s*\w+',  # Нумерация (29. Конструкция выпуска)
                r'^\d+',  # Начинается с числа
                r'Координаты:',  # Специфические слова
                r'^\s*[А-Яа-я\s\-]+$',  # Только текст (возможно заголовок колонки)
                r'соответствии',  # Признак продолжения текста
                r'^[А-Я][а-я]+\s+с',  # Начинается с заглавной буквы и предлога
                r'\|\s*$',  # Признак таблицы
            ]

            for indicator in table_indicators:
                if re.search(indicator, content.strip()[:100]):
                    return True
            return False

        for i, chunk in enumerate(chunks):
            chunk_page = chunk.get("page")

            # Проверяем, является ли текущий чанк заголовком таблицы
            if chunk["type"] == "text" or chunk["type"] == "paragraph":
                if re.match(r'^Таблица\s*\d+[:.]\s*', chunk["content"], re.IGNORECASE):
                    last_table_caption = chunk["content"]
                    continue  # Пропускаем этот чанк, сохраняя заголовок для следующей таблицы

            # Если это таблица
            if chunk["type"] == "table":
                # Добавляем заголовок к таблице, если он есть
                if last_table_caption and not chunk.get("heading"):
                    chunk["heading"] = last_table_caption
                last_table_caption = None

            # Проверяем, не является ли текущий блок продолжением таблицы
            if grouped_chunks and chunk["type"] in ["text", "paragraph", "merged_page"]:
                prev_chunk = grouped_chunks[-1]

                # Если предыдущий чанк - таблица, и текущий находится на следующей странице
                if (prev_chunk["type"] == "table" and
                        chunk_page == prev_chunk.get("page", 0) + 1 and
                        is_likely_table_continuation(chunk["content"])):

                    # Объединяем с предыдущей таблицей
                    prev_chunk["content"] += "\n\n" + chunk["content"]
                    if "pages" not in prev_chunk:
                        prev_chunk["pages"] = [prev_chunk.get("page")]
                    if chunk_page not in prev_chunk["pages"]:
                        prev_chunk["pages"].append(chunk_page)
                    prev_chunk["page"] = min(prev_chunk["pages"])  # Обновляем page до минимальной страницы
                    continue

            # Если страница изменилась и есть накопленные чанки
            if chunk_page != current_page and current_page_chunks:
                grouped_chunks.append(self._merge_page_chunks(current_page_chunks))
                current_page_chunks = [chunk]
                current_page = chunk_page

            # Добавляем чанк к текущей странице
            else:
                current_page_chunks.append(chunk)
                current_page = chunk_page

        # Объединяем последнюю страницу
        if current_page_chunks:
            grouped_chunks.append(self._merge_page_chunks(current_page_chunks))

        return grouped_chunks

    def _merge_page_chunks(self, chunks: List[Dict]) -> Dict:
        """
        Объединяет чанки с одной страницы
        """
        if not chunks:
            return {}

        if len(chunks) == 1:
            return chunks[0]

        # Берем базовую информацию из первого чанка
        merged_chunk = {
            "content": "",
            "type": "merged_page",
            "page": chunks[0].get("page"),
            "heading": None,
            "table_id": None
        }

        sections = []
        current_section = None

        for chunk in chunks:
            # Если это заголовок, начинаем новую секцию
            if chunk["type"] == "heading":
                if current_section:
                    sections.append(current_section)
                current_section = {
                    "heading": chunk["content"],
                    "content": []
                }

            # Если уже есть секция, добавляем контент
            elif current_section:
                current_section["content"].append(chunk["content"])

            # Иначе добавляем как отдельный контент
            else:
                if chunk["content"].strip():
                    sections.append({
                        "heading": None,
                        "content": [chunk["content"]]
                    })

        # Добавляем последнюю секцию
        if current_section:
            sections.append(current_section)

        # Объединяем все секции
        content_parts = []
        for section in sections:
            if section["heading"]:
                content_parts.append(f"## {section['heading']}")
            content_parts.extend(section["content"])

        merged_chunk["content"] = "\n\n".join(content_parts)

        return merged_chunk

    def post_process_tables(self, chunks: List[Dict]) -> List[Dict]:
        """
        Постобработка таблиц для объединения разорванных на страницах
        """
        processed_chunks = []
        current_table = None

        for i, chunk in enumerate(chunks):
            if chunk["type"] == "table":
                # Проверяем, является ли эта таблица продолжением предыдущей
                is_continuation = False

                if current_table is not None:
                    # Проверяем условия продолжения таблицы:

                    # Получаем страницы предыдущей таблицы
                    prev_pages = current_table.get("pages", [current_table.get("page")])
                    if not isinstance(prev_pages, list):
                        prev_pages = [prev_pages] if prev_pages else []

                    curr_page = chunk.get("page")

                    # Проверяем, что текущая страница идет сразу после последней страницы таблицы
                    if prev_pages and curr_page:
                        max_prev_page = max(prev_pages)
                        if curr_page == max_prev_page + 1:
                            # У таблицы нет заголовка или заголовок общий
                            if not chunk.get("heading") or chunk.get("heading") == current_table.get("heading"):
                                is_continuation = True

                if is_continuation:
                    # Объединяем с текущей таблицей
                    current_table["content"] += "\n\n" + chunk["content"]

                    # Обновляем страницы
                    existing_pages = current_table.get("pages", [])
                    if not isinstance(existing_pages, list):
                        existing_pages = [existing_pages] if existing_pages else []

                    curr_page = chunk.get("page")
                    if curr_page and curr_page not in existing_pages:
                        existing_pages.append(curr_page)
                        current_table["pages"] = sorted(existing_pages)
                else:
                    # Если была предыдущая таблица, добавляем её
                    if current_table:
                        processed_chunks.append(current_table)

                    # Это новая таблица
                    current_table = chunk.copy()
            else:
                # Не таблица
                if current_table:
                    processed_chunks.append(current_table)
                    current_table = None
                processed_chunks.append(chunk)

        # Добавляем последнюю таблицу, если она есть
        if current_table:
            processed_chunks.append(current_table)

        return processed_chunks


# Пример использования
if __name__ == "__main__":
    import os
    import time
    import json
    from pathlib import Path

    # Проверяем наличие CUDA
    try:
        import torch

        has_cuda = torch.cuda.is_available()
        if has_cuda:
            print(f"CUDA доступна. Используется GPU: {torch.cuda.get_device_name(0)}")
        else:
            print("CUDA недоступна. Используется CPU.")
    except ImportError:
        has_cuda = False
        print("PyTorch не установлен. Используется CPU.")

    # Создаем экземпляр чанкера с GPU если доступно
    chunker = SemanticChunker(use_gpu=has_cuda)

    # Путь к PDF файлу
    pdf_path = "data/docling-splitter-test.pdf"

    # Проверяем, существует ли файл
    if not os.path.exists(pdf_path):
        print(f"Файл {pdf_path} не найден. Пожалуйста, укажите правильный путь.")
        print(f"Текущая директория: {os.getcwd()}")
        exit(1)

    print(f"Обработка файла: {pdf_path}")

    try:
        start_time = time.time()

        # Извлекаем смысловые блоки
        chunks = chunker.extract_chunks(pdf_path)
        print(f"Найдено {len(chunks)} начальных блоков")

        # Обрабатываем таблицы
        processed_chunks = chunker.post_process_tables(chunks)
        print(f"После обработки таблиц: {len(processed_chunks)} блоков")

        # Группируем короткие блоки
        grouped_chunks = chunker.group_semantic_chunks(processed_chunks)
        print(f"После группировки: {len(grouped_chunks)} финальных блоков")

        end_time = time.time()
        print(f"Время обработки: {end_time - start_time:.2f} секунд")

        # Создаем папку для сохранения чанков
        output_dir = Path("data/md")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Сохраняем все чанки в JSON для анализа структуры
        with open(output_dir / "all_chunks.json", "w", encoding="utf-8") as f:
            json.dump(grouped_chunks, f, ensure_ascii=False, indent=2)

        # Сохраняем каждый чанк в отдельный файл
        for i, chunk in enumerate(grouped_chunks):
            chunk_type = chunk.get('type', 'unknown')
            page = chunk.get('page', 'no_page')

            # Создаем имя файла
            filename = f"chunk_{i + 1:03d}_{chunk_type}_page_{page}.md"

            # Сохраняем метаданные и контент в markdown формате
            with open(output_dir / filename, "w", encoding="utf-8") as f:
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

        print(f"\nЧанки сохранены в папку: {output_dir}")

        # Создаем сводный файл с информацией о всех чанках
        with open(output_dir / "summary.md", "w", encoding="utf-8") as f:
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

        print(f"Создан файл summary.md с общей информацией о чанках")

    except Exception as e:
        print(f"Ошибка при обработке файла: {e}")
        import traceback

        traceback.print_exc()