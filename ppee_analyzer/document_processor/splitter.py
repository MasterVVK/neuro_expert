"""
Реализация класса для разделения документов ППЭЭ с учетом их структуры
"""

import re
from typing import List, Dict, Any, Optional
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document


class PPEEDocumentSplitter:
    """Класс для разделения документов ППЭЭ с учетом их структуры"""

    def __init__(
            self,
            text_chunk_size: int = 800,
            table_chunk_size: int = 2000,
            list_chunk_size: int = 1500,
            chunk_overlap: int = 150
    ):
        """
        Инициализирует разделитель документов ППЭЭ.

        Args:
            text_chunk_size: Размер фрагмента для обычного текста
            table_chunk_size: Размер фрагмента для таблиц
            list_chunk_size: Размер фрагмента для списков
            chunk_overlap: Перекрытие между фрагментами
        """
        self.text_chunk_size = text_chunk_size
        self.table_chunk_size = table_chunk_size
        self.list_chunk_size = list_chunk_size
        self.chunk_overlap = chunk_overlap

    def identify_content_type(self, text: str) -> str:
        """
        Определяет тип содержимого фрагмента.

        Args:
            text: Текст фрагмента

        Returns:
            str: Тип содержимого ("table", "list", "text")
        """
        # Проверка на таблицу (содержит | и типичные разделители таблиц в markdown)
        if "|" in text and re.search(r'\|[\s-]+\|', text):
            return "table"

        # Проверка на список
        if re.search(r'(\n\s*[-*]\s+[^\n]+){2,}', text):
            return "list"

        # По умолчанию - обычный текст
        return "text"

    def extract_section_info(self, text: str) -> Dict[str, str]:
        """
        Извлекает информацию о разделе и подразделе.

        Args:
            text: Текст фрагмента

        Returns:
            Dict[str, str]: Информация о разделе
        """
        section = "Не определено"
        subsection = ""
        section_path = ""

        # Поиск номера раздела (например, 4.г)
        section_number_match = re.search(r'(\d+(\.\w+)*)\.\s+', text)
        if section_number_match:
            section_path = section_number_match.group(1)

        # Поиск заголовка раздела
        section_match = re.search(r'## ([^#\n]+)', text)
        if section_match:
            section = section_match.group(1).strip()

        # Поиск подзаголовка
        subsection_match = re.search(r'### ([^#\n]+)', text)
        if subsection_match:
            subsection = subsection_match.group(1).strip()

        return {
            "section": section,
            "subsection": subsection,
            "section_path": section_path
        }

    def detect_special_content(self, text: str) -> Dict[str, bool]:
        """
        Определяет наличие специального содержимого.

        Args:
            text: Текст фрагмента

        Returns:
            Dict[str, bool]: Флаги специального содержимого
        """
        return {
            "contains_values": bool(re.search(r'\d+[.,]\d+', text)),
            "contains_dates": bool(re.search(r'\d{2}[./-]\d{2}[./-]\d{4}', text))
        }

    def extract_page_number(self, text: str) -> Optional[int]:
        """
        Пытается извлечь номер страницы.

        Args:
            text: Текст фрагмента

        Returns:
            Optional[int]: Номер страницы, если найден
        """
        # Поиск номера страницы в конце текста или в заголовке
        page_match = re.search(r'(\d+)\s*$', text)
        if page_match:
            try:
                return int(page_match.group(1))
            except ValueError:
                pass
        return None

    def split_by_sections(self, text: str) -> List[str]:
        """
        Разделяет текст на крупные секции по заголовкам.

        Args:
            text: Текст документа

        Returns:
            List[str]: Список секций
        """
        # Регулярное выражение для поиска заголовков разделов
        section_pattern = r'\n##\s+[^\n]+'

        # Находим все позиции заголовков
        matches = list(re.finditer(section_pattern, text))

        if not matches:
            return [text]

        sections = []

        # Добавляем текст до первого заголовка, если он есть
        if matches[0].start() > 0:
            sections.append(text[:matches[0].start()])

        # Добавляем каждую секцию
        for i in range(len(matches)):
            start = matches[i].start()
            end = matches[i + 1].start() if i < len(matches) - 1 else len(text)
            sections.append(text[start:end])

        return sections

    def split_section(self, section_text: str) -> List[str]:
        """
        Разделяет секцию на фрагменты с учетом типа содержимого.

        Args:
            section_text: Текст секции

        Returns:
            List[str]: Список фрагментов
        """
        content_type = self.identify_content_type(section_text)

        # Выбираем размер фрагмента в зависимости от типа контента
        if content_type == "table":
            # Для таблиц: проверка размера
            if len(section_text) <= self.table_chunk_size:
                return [section_text]  # Хранить таблицу целиком
            else:
                # Таблица слишком большая - делим по строкам
                rows = section_text.split('\n')
                header = rows[0:2]  # Заголовок и разделительная строка

                chunks = []
                current_chunk = header.copy()

                for row in rows[2:]:
                    current_chunk.append(row)
                    if len('\n'.join(current_chunk)) > self.table_chunk_size:
                        chunks.append('\n'.join(current_chunk))
                        current_chunk = header.copy()

                if current_chunk and len(current_chunk) > len(header):
                    chunks.append('\n'.join(current_chunk))

                return chunks

        elif content_type == "list":
            # Для списков: стараемся не разрывать связанные пункты
            if len(section_text) <= self.list_chunk_size:
                return [section_text]  # Список целиком
            else:
                # Делим список на логические группы
                list_items = re.split(r'(\n\s*[-*]\s+)', section_text)

                chunks = []
                current_chunk = ""

                for i in range(len(list_items)):
                    if i % 2 == 0:  # текст перед маркером списка
                        current_text = list_items[i]
                    else:  # маркер списка + текст после него
                        if i + 1 < len(list_items):
                            current_text = list_items[i] + list_items[i + 1]
                        else:
                            current_text = list_items[i]

                    if len(current_chunk + current_text) > self.list_chunk_size and current_chunk:
                        chunks.append(current_chunk)
                        current_chunk = current_text
                    else:
                        current_chunk += current_text

                if current_chunk:
                    chunks.append(current_chunk)

                return chunks

        else:  # Обычный текст или другой тип
            # Используем рекурсивный разделитель для обычного текста
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.text_chunk_size,
                chunk_overlap=self.chunk_overlap,
                separators=["\n\n", "\n", ". ", ", ", " ", ""],
                keep_separator=True
            )

            chunks = text_splitter.split_text(section_text)
            return chunks

    def process_document(self, text: str, application_id: str, document_id: str, document_name: str) -> List[Document]:
        """
        Обрабатывает документ ППЭЭ и разделяет его на фрагменты с метаданными.

        Args:
            text: Текст документа
            application_id: ID заявки
            document_id: ID документа
            document_name: Название документа

        Returns:
            List[Document]: Список фрагментов с метаданными
        """
        # Шаг 1: Разделение на крупные секции по заголовкам
        sections = self.split_by_sections(text)

        chunks = []
        chunk_index = 0

        # Шаг 2: Обработка каждой секции
        for section_text in sections:
            # Определяем информацию о разделе
            section_info = self.extract_section_info(section_text)
            content_type = self.identify_content_type(section_text)

            # Шаг 3: Разделяем секцию на фрагменты
            section_chunks = self.split_section(section_text)

            # Шаг 4: Добавляем метаданные к каждому фрагменту
            for i, chunk_text in enumerate(section_chunks):
                # Определяем дополнительную информацию
                special_content = self.detect_special_content(chunk_text)
                page_number = self.extract_page_number(chunk_text)

                # Создаем метаданные
                metadata = {
                    "application_id": application_id,
                    "document_id": document_id,
                    "document_name": document_name,
                    "section": section_info["section"],
                    "subsection": section_info["subsection"],
                    "section_path": section_info["section_path"],
                    "content_type": content_type,
                    "chunk_index": chunk_index,
                    "page_number": page_number,
                    "contains_values": special_content["contains_values"],
                    "contains_dates": special_content["contains_dates"]
                }

                # Создаем документ
                chunks.append(Document(page_content=chunk_text, metadata=metadata))
                chunk_index += 1

        return chunks

    def load_and_process_file(self, file_path: str, application_id: str) -> List[Document]:
        """
        Загружает файл и обрабатывает его.

        Args:
            file_path: Путь к файлу
            application_id: ID заявки

        Returns:
            List[Document]: Список фрагментов с метаданными
        """
        # Загрузка документа
        loader = TextLoader(file_path, encoding='utf-8')
        documents = loader.load()
        document_text = documents[0].page_content

        # Создаем идентификатор документа на основе имени файла
        import os
        document_id = f"doc_{os.path.basename(file_path).replace(' ', '_').replace('.', '_')}"
        document_name = os.path.basename(file_path)

        # Обрабатываем документ
        return self.process_document(
            text=document_text,
            application_id=application_id,
            document_id=document_id,
            document_name=document_name
        )