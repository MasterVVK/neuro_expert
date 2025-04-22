"""
Класс для семантического разделения документов ППЭЭ с использованием docling.
"""

import os
import re
import logging
import uuid
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

# Импорты из текущего модуля
from .models import SemanticChunk, DocumentAnalysisResult
from .utils import (
    detect_docling_availability,
    detect_gpu_availability,
    is_likely_table_continuation,
    identify_content_type,
    extract_section_info,
    generate_unique_id
)

# Импорты для интеграции с ppee_analyzer
from langchain_core.documents import Document
from ..document_processor.splitter import PPEEDocumentSplitter

# Настройка логирования
logger = logging.getLogger(__name__)


class SemanticChunker:
    """Класс для семантического разделения документов с использованием docling"""

    def __init__(self, use_gpu: bool = None, threads: int = 8):
        """
        Инициализирует чанкер для семантического разделения документов.

        Args:
            use_gpu: Использовать ли GPU (None - автоопределение)
            threads: Количество потоков
        """
        # Проверяем доступность docling
        self.docling_available = detect_docling_availability()
        if not self.docling_available:
            raise ImportError("Библиотека docling не установлена. Установите её для работы с SemanticChunker.")

        # Импортируем docling только если он доступен
        import docling
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, AcceleratorDevice, AcceleratorOptions

        # Проверяем доступность GPU
        if use_gpu is None:
            use_gpu = detect_gpu_availability()

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

        logger.info(f"SemanticChunker инициализирован (GPU: {use_gpu}, потоков: {threads})")

    def extract_chunks(self, pdf_path: str) -> List[Dict]:
        """
        Извлекает и структурирует документ по смысловым блокам.

        Args:
            pdf_path: Путь к PDF файлу

        Returns:
            List[Dict]: Список смысловых блоков документа
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"Файл не найден: {pdf_path}")

        logger.info(f"Начало обработки документа: {pdf_path}")

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

        logger.info(f"Документ разделен на {len(chunks)} смысловых блоков")
        logger.info(f"Обработано страниц: {sorted(list(pages_encountered))}")

        return chunks

    def post_process_tables(self, chunks: List[Dict]) -> List[Dict]:
        """
        Постобработка таблиц для объединения разорванных на страницах.

        Args:
            chunks: Список чанков документа

        Returns:
            List[Dict]: Обработанные чанки с объединенными таблицами
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

    def analyze_document(self, pdf_path: str) -> DocumentAnalysisResult:
        """
        Анализирует PDF документ и возвращает результаты в структурированном виде.

        Args:
            pdf_path: Путь к PDF файлу

        Returns:
            DocumentAnalysisResult: Результаты анализа документа
        """
        # Извлекаем чанки
        chunks = self.extract_chunks(pdf_path)

        # Обрабатываем таблицы
        processed_chunks = self.post_process_tables(chunks)

        # Собираем статистику
        pages = set()
        content_types = {}

        for chunk in processed_chunks:
            # Добавляем страницы
            if chunk.get("page"):
                pages.add(chunk["page"])
            elif chunk.get("pages"):
                pages.update(chunk["pages"])

            # Подсчитываем типы контента
            chunk_type = chunk.get("type", "unknown")
            content_types[chunk_type] = content_types.get(chunk_type, 0) + 1

        # Создаем объекты SemanticChunk
        semantic_chunks = []
        for chunk in processed_chunks:
            semantic_chunks.append(SemanticChunk(
                content=chunk["content"],
                type=chunk["type"],
                page=chunk.get("page"),
                heading=chunk.get("heading"),
                table_id=chunk.get("table_id"),
                pages=chunk.get("pages"),
                section_path=None  # Можно добавить логику определения section_path
            ))

        # Формируем результат
        statistics = {
            "total_chunks": len(semantic_chunks),
            "pages": sorted(list(pages)),
            "total_pages": len(pages),
            "content_types": content_types
        }

        return DocumentAnalysisResult(
            chunks=semantic_chunks,
            document_path=pdf_path,
            statistics=statistics
        )


class SemanticDocumentSplitter(PPEEDocumentSplitter):
    """
    Расширение PPEEDocumentSplitter для использования семантического разделения.
    Интегрирует функциональность SemanticChunker в инфраструктуру ppee_analyzer.
    """

    def __init__(
            self,
            use_gpu: bool = None,
            threads: int = 8,
            chunk_size: int = 1500,
            chunk_overlap: int = 150
    ):
        """
        Инициализирует семантический разделитель документов.

        Args:
            use_gpu: Использовать ли GPU (None - автоопределение)
            threads: Количество потоков
            chunk_size: Размер фрагмента для обычного текста (используется при fallback)
            chunk_overlap: Перекрытие между фрагментами (используется при fallback)
        """
        # Инициализируем базовый класс
        super().__init__(
            text_chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

        # Инициализируем семантический чанкер
        try:
            self.semantic_chunker = SemanticChunker(use_gpu=use_gpu, threads=threads)
            self.use_semantic_chunking = True
            logger.info("Инициализирован семантический разделитель документов")
        except ImportError as e:
            logger.warning(f"Не удалось инициализировать семантический разделитель: {e}")
            logger.warning("Будет использован базовый разделитель")
            self.use_semantic_chunking = False

    def process_document(self, text: str, application_id: str, document_id: str, document_name: str) -> List[Document]:
        """
        Обрабатывает документ ППЭЭ и разделяет его на фрагменты с метаданными.
        Переопределяет метод базового класса для использования семантического разделения.

        Args:
            text: Текст документа
            application_id: ID заявки
            document_id: ID документа
            document_name: Название документа

        Returns:
            List[Document]: Список фрагментов с метаданными
        """
        # Проверяем, используем ли семантическое разделение
        if not self.use_semantic_chunking:
            logger.info("Используется базовый разделитель")
            return super().process_document(text, application_id, document_id, document_name)

        # Получаем путь к документу из метаданных (если это текст, преобразуем во временный файл)
        if document_name.lower().endswith('.pdf'):
            # Ищем исходный PDF файл по имени документа
            # Для этого нужно знать структуру директорий проекта
            possible_paths = [
                os.path.join('uploads', document_name),
                os.path.join('data', document_name),
                document_name  # Абсолютный путь
            ]

            pdf_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    pdf_path = path
                    break

            if not pdf_path:
                logger.warning(f"PDF файл не найден: {document_name}")
                logger.info("Используется базовый разделитель")
                return super().process_document(text, application_id, document_id, document_name)

            # Анализируем PDF файл с помощью семантического чанкера
            try:
                analysis_result = self.semantic_chunker.analyze_document(pdf_path)
                logger.info(f"Документ разделен на {len(analysis_result.chunks)} смысловых блоков")

                # Преобразуем чанки в формат langchain Document
                documents = []
                for i, chunk in enumerate(analysis_result.chunks):
                    # Создаем метаданные
                    metadata = {
                        "application_id": application_id,
                        "document_id": document_id,
                        "document_name": document_name,
                        "content_type": chunk.type,
                        "chunk_index": i,
                        "section": chunk.heading or "Не определено",
                        "section_path": chunk.section_path,
                        "page_number": chunk.page
                    }

                    # Добавляем информацию о таблице
                    if chunk.type == "table":
                        metadata["table_id"] = chunk.table_id
                        if chunk.pages:
                            metadata["pages"] = chunk.pages

                    # Создаем документ
                    documents.append(Document(
                        page_content=chunk.content,
                        metadata=metadata
                    ))

                return documents

            except Exception as e:
                logger.error(f"Ошибка при семантическом разделении: {str(e)}")
                logger.info("Используется базовый разделитель")
                return super().process_document(text, application_id, document_id, document_name)
        else:
            # Для не-PDF документов используем базовый разделитель
            logger.info(f"Документ типа {document_name.split('.')[-1]} обрабатывается базовым разделителем")
            return super().process_document(text, application_id, document_id, document_name)