"""
Модуль для конвертации PDF документов в формат Markdown
с сохранением структуры документа, таблиц и списков.
Использует комбинацию pdfplumber + pandas + tabulate для извлечения таблиц.
"""

import os
import re
import logging
from typing import List, Dict, Any, Optional, Tuple
import tempfile
import subprocess
import shutil

# Попытка импорта различных PDF библиотек с обработкой ошибок
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    from tabulate import tabulate
    TABULATE_AVAILABLE = True
except ImportError:
    TABULATE_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# Настройка логирования
logger = logging.getLogger(__name__)


class PDFToMarkdownConverter:
    """Класс для конвертации PDF в Markdown с сохранением структуры и таблиц"""

    def __init__(
            self,
            use_ocr: bool = False,
            ocr_language: str = "rus",
            preserve_tables: bool = True,
            pandoc_path: Optional[str] = None,
            tesseract_path: Optional[str] = None
    ):
        """
        Инициализирует конвертер PDF в Markdown.

        Args:
            use_ocr: Использовать ли OCR для извлечения текста
            ocr_language: Язык для OCR (rus, eng и т.д.)
            preserve_tables: Сохранять ли таблицы в формате Markdown
            pandoc_path: Путь к исполняемому файлу pandoc (при наличии)
            tesseract_path: Путь к исполняемому файлу tesseract (при использовании OCR)
        """
        self.use_ocr = use_ocr
        self.ocr_language = ocr_language
        self.preserve_tables = preserve_tables
        self.pandoc_path = pandoc_path

        # Настройка путей к внешним программам
        if tesseract_path:
            if OCR_AVAILABLE:
                pytesseract.pytesseract.tesseract_cmd = tesseract_path
            else:
                logger.warning("Указан путь к Tesseract, но библиотеки OCR не установлены")

        # Проверка доступности необходимых инструментов
        self._check_dependencies()

    def _check_dependencies(self) -> None:
        """Проверяет доступность необходимых зависимостей"""

        if not PYMUPDF_AVAILABLE:
            logger.warning("PyMuPDF (fitz) не установлен. Некоторые функции могут быть недоступны. "
                           "Установите его командой: pip install pymupdf")

        if not PDFPLUMBER_AVAILABLE:
            logger.warning("PDFPlumber не установлен. Извлечение таблиц будет ограничено. "
                           "Установите его командой: pip install pdfplumber")

        if not PANDAS_AVAILABLE:
            logger.warning("Pandas не установлен. Некоторые функции могут быть недоступны. "
                           "Установите его командой: pip install pandas")

        if not TABULATE_AVAILABLE:
            logger.warning("Tabulate не установлен. Форматирование таблиц будет ограничено. "
                           "Установите его командой: pip install tabulate")

        if self.use_ocr and not OCR_AVAILABLE:
            logger.warning("Для использования OCR требуются библиотеки pdf2image и pytesseract. "
                           "Установите их командами: pip install pdf2image pytesseract")
            self.use_ocr = False

        # Убираем проверку на Pandoc, так как он не может конвертировать из PDF
        self.pandoc_available = False

    def _extract_text_with_pymupdf(self, pdf_path: str) -> str:
        """
        Извлекает текст из PDF с помощью PyMuPDF.

        Args:
            pdf_path: Путь к PDF-файлу

        Returns:
            str: Извлеченный текст
        """
        if not PYMUPDF_AVAILABLE:
            logger.error("PyMuPDF не установлен. Невозможно извлечь текст.")
            return ""

        full_text = []

        try:
            # Открываем PDF-документ
            doc = fitz.open(pdf_path)

            # Обрабатываем каждую страницу
            for page_num, page in enumerate(doc):
                # Извлекаем текст со страницы
                page_text = page.get_text("text")

                # Добавляем номер страницы
                page_text += f"\n\nСтраница {page_num + 1}\n"

                full_text.append(page_text)

            # Закрываем документ
            doc.close()

            return "\n".join(full_text)

        except Exception as e:
            logger.error(f"Ошибка при извлечении текста из PDF: {str(e)}")
            return ""

    def _extract_text_with_ocr(self, pdf_path: str) -> str:
        """
        Извлекает текст из PDF с помощью OCR.

        Args:
            pdf_path: Путь к PDF-файлу

        Returns:
            str: Извлеченный текст
        """
        if not OCR_AVAILABLE:
            logger.error("Библиотеки для OCR не установлены. Невозможно извлечь текст с помощью OCR.")
            return ""

        full_text = []

        try:
            # Конвертируем PDF в изображения
            images = convert_from_path(pdf_path)

            # Обрабатываем каждую страницу
            for page_num, image in enumerate(images):
                # Извлекаем текст с помощью OCR
                page_text = pytesseract.image_to_string(image, lang=self.ocr_language)

                # Добавляем номер страницы
                page_text += f"\n\nСтраница {page_num + 1}\n"

                full_text.append(page_text)

            return "\n".join(full_text)

        except Exception as e:
            logger.error(f"Ошибка при извлечении текста с помощью OCR: {str(e)}")
            return ""

    def _process_extracted_text(self, text: str) -> str:
        """
        Обрабатывает извлеченный текст для улучшения форматирования.

        Args:
            text: Извлеченный текст

        Returns:
            str: Обработанный текст в формате Markdown
        """
        # Заменяем многократные переносы строк на двойные
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Обрабатываем заголовки (строки с большими буквами и/или числами)
        lines = text.split('\n')
        processed_lines = []

        for line in lines:
            stripped = line.strip()

            # Определяем уровень заголовка
            header_level = 0

            # Заголовки первого уровня
            if re.match(r'^[0-9]+\.?\s+[А-ЯA-Z]', stripped):
                header_level = 1
            # Заголовки второго уровня
            elif re.match(r'^[0-9]+\.[0-9]+\.?\s+[А-ЯA-Z]', stripped):
                header_level = 2
            # Заголовки третьего уровня
            elif re.match(r'^[0-9]+\.[0-9]+\.[0-9]+\.?\s+[А-ЯA-Z]', stripped):
                header_level = 3
            # Альтернативное определение заголовков (полностью заглавные буквы)
            elif re.match(r'^[А-ЯA-Z\s\d]{10,}$', stripped) and len(stripped) > 15:
                header_level = 2

            # Добавляем маркеры Markdown для заголовков
            if header_level > 0:
                processed_lines.append(f"{'#' * header_level} {stripped}")
            else:
                processed_lines.append(line)

        text = '\n'.join(processed_lines)

        # Обрабатываем списки
        text = re.sub(r'(?m)^[\s•]*[-–—•][\s]+(.*)', r'* \1', text)
        text = re.sub(r'(?m)^[\s]*(\d+)\.[\s]+(.*)', r'\1. \2', text)

        return text

    def _extract_tables_with_pdfplumber(self, pdf_path: str) -> dict:
        """
        Извлекает таблицы из PDF с помощью pdfplumber.

        Args:
            pdf_path: Путь к PDF-файлу

        Returns:
            dict: Словарь с таблицами в формате Markdown
        """
        if not PDFPLUMBER_AVAILABLE or not PANDAS_AVAILABLE:
            logger.error("PDFPlumber или Pandas не установлены. Невозможно извлечь таблицы.")
            return {}

        tables_dict = {}
        table_count = 0

        try:
            logger.info("Извлечение таблиц с помощью PDFPlumber")

            # Открываем PDF с помощью pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                # Проходим по каждой странице
                for page_num, page in enumerate(pdf.pages):
                    # Извлекаем таблицы на текущей странице
                    tables = page.extract_tables()

                    for table_idx, table_data in enumerate(tables):
                        if not table_data or len(table_data) <= 1:
                            continue  # Пропускаем пустые или слишком маленькие таблицы

                        # Создаем DataFrame из полученных данных
                        df = pd.DataFrame(table_data)

                        # Если в первой строке есть заголовки, используем их
                        if df.shape[0] > 0:
                            headers = df.iloc[0].tolist()
                            df = df.iloc[1:].reset_index(drop=True)
                            df.columns = headers

                        # Очищаем данные
                        df = self._clean_dataframe(df)

                        # Проверяем, что таблица не пустая после очистки
                        if df.empty or df.shape[0] == 0 or df.shape[1] == 0:
                            continue

                        # Преобразуем в Markdown с использованием tabulate
                        if TABULATE_AVAILABLE:
                            table_md = tabulate(df, headers='keys', tablefmt='pipe', showindex=False)
                        else:
                            # Собственная реализация для случая, когда tabulate не установлен
                            headers = df.columns.tolist()
                            rows = [headers]
                            rows.append(['---'] * len(headers))
                            for _, row in df.iterrows():
                                rows.append(row.tolist())

                            table_md = '\n'.join(['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])

                        # Добавляем таблицу в словарь
                        table_count += 1
                        table_key = f"table_p{page_num+1}_{table_idx+1}"
                        tables_dict[table_key] = table_md

                        logger.info(f"Извлечена таблица {table_count} со страницы {page_num+1}")

            logger.info(f"Всего извлечено таблиц: {table_count}")
            return tables_dict

        except Exception as e:
            logger.error(f"Ошибка при извлечении таблиц с помощью PDFPlumber: {str(e)}")
            return {}

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Очищает и обрабатывает DataFrame с данными таблицы.

        Args:
            df: DataFrame таблицы

        Returns:
            pd.DataFrame: Очищенный DataFrame
        """
        if df.empty:
            return df

        # Заменяем None на пустые строки
        df = df.fillna('')

        # Преобразуем все значения в строки
        for col in df.columns:
            df[col] = df[col].astype(str)

        # Удаляем пробелы в начале и конце значений
        for col in df.columns:
            df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)

        # Удаляем строки, где все ячейки пусты
        df = df.loc[~(df == '').all(axis=1)]

        # Удаляем колонки, где все ячейки пусты
        df = df.loc[:, ~(df == '').all()]

        # Обрабатываем заголовки - заменяем None и пустые строки на Column N
        new_headers = []
        for i, col in enumerate(df.columns):
            if col == '' or str(col).lower() == 'none':
                new_headers.append(f"Column {i + 1}")
            else:
                new_headers.append(col)

        df.columns = new_headers

        return df

    def _insert_tables_into_content(self, content: str, tables: dict) -> str:
        """
        Вставляет таблицы в текстовый контент на основе эвристик.

        Args:
            content: Текстовый контент
            tables: Словарь таблиц в формате Markdown

        Returns:
            str: Обновленный контент с таблицами
        """
        if not tables:
            return content

        # Разбиваем контент на строки
        lines = content.split('\n')
        result = []
        tables_inserted = set()

        i = 0
        while i < len(lines):
            line = lines[i]
            result.append(line)

            # Ищем потенциальные маркеры таблиц
            table_markers = [
                r'[Тт]аблица\s*№?\s*\d+',  # Таблица №1
                r'[Тт]абл\.\s*№?\s*\d+',    # Табл. №1
                r'[Tt]able\s*\d+',          # Table 1
                r'список\s*[а-яА-Я\s]+:',   # список чего-либо:
                r'перечень\s*[а-яА-Я\s]+:'  # перечень чего-либо:
            ]

            is_table_marker = any(re.search(pattern, line, re.IGNORECASE) for pattern in table_markers)

            # Если нашли маркер таблицы, ищем лучшую таблицу для вставки
            if is_table_marker and i + 1 < len(lines):
                # Смотрим на следующую строку
                next_line = lines[i + 1]

                # Если следующая строка пустая или не начинается с | - подходящее место для таблицы
                if not next_line.strip() or not next_line.strip().startswith('|'):
                    available_tables = [t_id for t_id in tables if t_id not in tables_inserted]

                    if available_tables:
                        table_id = available_tables[0]
                        result.append("")  # Пустая строка перед таблицей
                        result.append(tables[table_id])
                        result.append("")  # Пустая строка после таблицы
                        tables_inserted.add(table_id)

            # Также ищем последовательные строки с числами или форматированием, указывающим на таблицу
            if i + 2 < len(lines):
                current = line.strip()
                next1 = lines[i + 1].strip()
                next2 = lines[i + 2].strip()

                # Признаки табличных данных
                has_numbers = re.search(r'\d+\s+\d+', current) and re.search(r'\d+\s+\d+', next1)
                has_spacing = re.search(r'\S+\s{2,}\S+', current) and re.search(r'\S+\s{2,}\S+', next1)

                if (has_numbers or has_spacing) and not any(line.strip().startswith('|') for line in [current, next1, next2]):
                    available_tables = [t_id for t_id in tables if t_id not in tables_inserted]

                    if available_tables:
                        table_id = available_tables[0]
                        result.append("")  # Пустая строка перед таблицей
                        result.append(tables[table_id])
                        result.append("")  # Пустая строка после таблицы
                        tables_inserted.add(table_id)
                        # Пропускаем следующие строки, которые были бы неструктурированной таблицей
                        i += 2

            i += 1

        # Добавляем оставшиеся таблицы в конец документа
        remaining_tables = [table_content for table_id, table_content in tables.items()
                           if table_id not in tables_inserted]

        if remaining_tables:
            result.append("\n## Извлеченные таблицы\n")
            for table_content in remaining_tables:
                result.append(table_content)
                result.append("\n")

        return '\n'.join(result)

    def _post_process_markdown(self, file_path: str) -> None:
        """
        Дополнительная обработка Markdown-файла для улучшения форматирования.

        Args:
            file_path: Путь к Markdown-файлу
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()

            # 1. Удаление лишних пустых строк
            content = re.sub(r'\n{3,}', '\n\n', content)

            # 2. Форматирование заголовков
            lines = content.split('\n')
            for i in range(len(lines)):
                # Если строка похожа на заголовок, но не форматирована
                if re.match(r'^[0-9]+\.\s+[А-ЯA-Z]', lines[i]) and not lines[i].startswith('#'):
                    lines[i] = f"# {lines[i]}"
                elif re.match(r'^[0-9]+\.[0-9]+\.\s+[А-ЯA-Z]', lines[i]) and not lines[i].startswith('#'):
                    lines[i] = f"## {lines[i]}"

            content = '\n'.join(lines)

            # 3. Исправление таблиц
            # Заменяем любые последовательные пробелы в таблицах одним пробелом
            table_rows = re.findall(r'^\|.*\|$', content, re.MULTILINE)
            for row in table_rows:
                fixed_row = re.sub(r'\|\s+', '| ', row)
                fixed_row = re.sub(r'\s+\|', ' |', fixed_row)
                content = content.replace(row, fixed_row)

            # Записываем обработанный контент обратно
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(content)

            logger.info(f"Постобработка файла {file_path} выполнена успешно")

        except Exception as e:
            logger.error(f"Ошибка при постобработке файла {file_path}: {str(e)}")

    def convert_pdf_to_markdown(self, pdf_path: str, output_path: Optional[str] = None) -> str:
        """
        Конвертирует PDF в Markdown с извлечением таблиц.

        Args:
            pdf_path: Путь к PDF-файлу
            output_path: Путь для сохранения результата (если None, возвращает текст)

        Returns:
            str: Содержимое в формате Markdown
        """
        logger.info(f"Начинаем конвертацию PDF: {pdf_path}")

        if not os.path.exists(pdf_path):
            logger.error(f"Файл не найден: {pdf_path}")
            return ""

        # Извлечение текста с помощью PyMuPDF
        if PYMUPDF_AVAILABLE:
            logger.info("Используем PyMuPDF для извлечения текста")
            text = self._extract_text_with_pymupdf(pdf_path)

            if text:
                logger.info("Извлечение текста с помощью PyMuPDF успешно")

                # Извлечение таблиц с помощью pdfplumber, если требуется
                tables = {}
                if self.preserve_tables and PDFPLUMBER_AVAILABLE:
                    tables = self._extract_tables_with_pdfplumber(pdf_path)

                # Обработка текста
                markdown_content = self._process_extracted_text(text)

                # Вставка таблиц в контент
                if tables:
                    markdown_content = self._insert_tables_into_content(markdown_content, tables)

                # Если указан путь для сохранения
                if output_path:
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(markdown_content)
                    logger.info(f"Результат сохранен в файл: {output_path}")

                    # Постобработка для улучшения форматирования
                    self._post_process_markdown(output_path)

                return markdown_content

        # Стратегия 2: Использование OCR
        if self.use_ocr and OCR_AVAILABLE:
            logger.info("Используем OCR для извлечения текста")
            text = self._extract_text_with_ocr(pdf_path)
            if text:
                logger.info("Извлечение текста с помощью OCR успешно")
                markdown_content = self._process_extracted_text(text)

                # Если указан путь для сохранения
                if output_path:
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(markdown_content)
                    logger.info(f"Результат сохранен в файл: {output_path}")

                return markdown_content

        logger.error("Не удалось конвертировать PDF в Markdown")
        return ""

    def batch_convert(self, pdf_dir: str, output_dir: str, recursive: bool = False) -> List[str]:
        """
        Выполняет пакетную конвертацию PDF-файлов в директории.

        Args:
            pdf_dir: Путь к директории с PDF-файлами
            output_dir: Путь к директории для результатов
            recursive: Искать файлы рекурсивно в поддиректориях

        Returns:
            List[str]: Список путей к созданным файлам
        """
        if not os.path.exists(pdf_dir):
            logger.error(f"Директория не найдена: {pdf_dir}")
            return []

        # Создаем выходную директорию, если она не существует
        os.makedirs(output_dir, exist_ok=True)

        converted_files = []

        # Функция для обработки директории
        def process_directory(directory):
            nonlocal converted_files

            # Получаем список PDF-файлов
            for entry in os.scandir(directory):
                if entry.is_file() and entry.name.lower().endswith('.pdf'):
                    # Формируем путь для выходного файла
                    relative_path = os.path.relpath(entry.path, pdf_dir)
                    output_path = os.path.join(
                        output_dir,
                        os.path.splitext(relative_path)[0] + '.md'
                    )

                    # Создаем директории, если необходимо
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)

                    # Конвертируем файл
                    logger.info(f"Конвертация {entry.path}")
                    result = self.convert_pdf_to_markdown(entry.path, output_path)

                    if result:
                        converted_files.append(output_path)

                # Рекурсивно обрабатываем поддиректории
                elif entry.is_dir() and recursive:
                    process_directory(entry.path)

        # Начинаем обработку
        process_directory(pdf_dir)

        logger.info(f"Конвертировано файлов: {len(converted_files)}")
        return converted_files


# Пример использования
if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Пример использования для конвертации одного файла
    converter = PDFToMarkdownConverter(
        use_ocr=False,  # Использовать OCR при необходимости
        preserve_tables=True
    )

    # Конвертация одного файла
    pdf_path = "example.pdf"
    output_path = "example.md"

    if os.path.exists(pdf_path):
        result = converter.convert_pdf_to_markdown(pdf_path, output_path)
        print(f"Результат сохранен в {output_path}")
    else:
        print(f"Файл {pdf_path} не найден.")