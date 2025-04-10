"""
Модуль для обнаружения и форматирования таблиц из текста
"""

import re
import logging

# Настройка логирования
logger = logging.getLogger(__name__)


class TableFormatter:
    """Класс для обнаружения и форматирования таблиц"""

    @staticmethod
    def convert_table_to_markdown(table) -> str:
        """
        Преобразование таблицы из PyMuPDF в формат Markdown.

        Args:
            table: Объект таблицы из PyMuPDF или распознанная таблица

        Returns:
            str: Таблица в формате Markdown
        """
        try:
            # Проверяем наличие необходимых атрибутов
            if not (hasattr(table, 'rows') and hasattr(table, 'cols') and hasattr(table, 'cells')):
                logger.warning("Таблица не содержит необходимых атрибутов")
                return "*Не удалось преобразовать таблицу*"

            rows_count = table.rows
            cols_count = table.cols

            # Создаем таблицу в формате Markdown
            md_table = []

            # Заголовок (первая строка)
            header = []
            for col in range(cols_count):
                try:
                    # Индекс ячейки = строка * количество_столбцов + столбец
                    cell_idx = 0 * cols_count + col
                    if cell_idx < len(table.cells):
                        cell = table.cells[cell_idx]
                        text = cell.text.strip() if hasattr(cell, 'text') else ""
                    else:
                        text = " "
                    header.append(text or " ")
                except Exception as e:
                    logger.error(f"Ошибка при получении заголовка столбца {col}: {str(e)}")
                    header.append(" ")

            md_table.append("| " + " | ".join(header) + " |")

            # Разделитель - добавляем выравнивание
            md_table.append("| " + " | ".join(["---" for _ in range(cols_count)]) + " |")

            # Строки данных (со второй строки)
            for row in range(1, rows_count):
                row_data = []
                for col in range(cols_count):
                    try:
                        cell_idx = row * cols_count + col
                        if cell_idx < len(table.cells):
                            cell = table.cells[cell_idx]
                            text = cell.text.strip() if hasattr(cell, 'text') else ""
                        else:
                            text = " "
                        row_data.append(text or " ")
                    except Exception as e:
                        logger.error(f"Ошибка при получении данных ячейки [{row}][{col}]: {str(e)}")
                        row_data.append(" ")

                md_table.append("| " + " | ".join(row_data) + " |")

            return "\n".join(md_table)

        except Exception as e:
            logger.error(f"Ошибка при преобразовании таблицы в Markdown: {str(e)}")
            return "*Ошибка преобразования таблицы*"

    @staticmethod
    def detect_and_format_tables(text: str) -> str:
        """
        Обнаруживает и форматирует таблицы в тексте на основе выравнивания.

        Args:
            text: Текст для обработки

        Returns:
            str: Текст с правильно отформатированными таблицами Markdown
        """
        # Регулярное выражение для поиска потенциальных таблиц
        # Ищем блоки текста, где строки содержат несколько пробелов подряд и выровнены по столбцам
        table_pattern = r'((?:^[\w\d\s\.]+(?:\s{2,})[\w\d\s\.]+(?:\s{2,})[\w\d\s\.]+\n){2,})'

        def format_table_match(match):
            table_text = match.group(1)
            lines = table_text.strip().split('\n')

            # Проверяем, что это действительно может быть таблица
            if len(lines) < 2:
                return table_text

            # Анализируем строки, чтобы определить столбцы
            # Ищем группы пробелов как разделители столбцов
            space_groups = []
            for line in lines:
                groups = []
                in_space = False
                start = -1

                for i, char in enumerate(line):
                    if char.isspace():
                        if not in_space:
                            in_space = True
                            start = i
                    else:
                        if in_space:
                            in_space = False
                            if i - start > 1:  # Более одного пробела
                                groups.append((start, i))

                space_groups.append(groups)

            # Находим общие группы пробелов
            if not space_groups:
                return table_text

            # Находим наиболее часто встречающиеся позиции пробелов
            all_positions = []
            for groups in space_groups:
                for start, end in groups:
                    mid = (start + end) // 2
                    all_positions.append(mid)

            # Группируем близкие позиции
            column_markers = []
            if all_positions:
                sorted_positions = sorted(all_positions)
                current_group = [sorted_positions[0]]

                for pos in sorted_positions[1:]:
                    if pos - current_group[-1] < 3:  # Близкие позиции
                        current_group.append(pos)
                    else:
                        if current_group:
                            column_markers.append(sum(current_group) // len(current_group))
                        current_group = [pos]

                if current_group:
                    column_markers.append(sum(current_group) // len(current_group))

            # Создаем таблицу Markdown
            md_table = []
            for line in lines:
                row_parts = []
                last_end = 0

                # Добавляем начало строки
                row_parts.append("| ")

                for marker in column_markers:
                    if marker > last_end:
                        cell_content = line[last_end:marker].strip()
                        row_parts.append(cell_content + " | ")
                        last_end = marker

                # Добавляем оставшуюся часть строки
                if last_end < len(line):
                    cell_content = line[last_end:].strip()
                    row_parts.append(cell_content + " |")

                md_table.append("".join(row_parts))

            # Добавляем разделитель после заголовка
            if len(md_table) >= 1:
                separator = "| " + " | ".join(["---" for _ in range(len(column_markers) + 1)]) + " |"
                md_table.insert(1, separator)

            return "\n".join(md_table)

        # Заменяем найденные потенциальные таблицы
        return re.sub(table_pattern, format_table_match, text, flags=re.MULTILINE)

    @staticmethod
    def detect_tables_by_delimiters(text: str) -> str:
        """
        Альтернативный метод для обнаружения таблиц, основанный на разделителях.

        Args:
            text: Текст для обработки

        Returns:
            str: Текст с правильно отформатированными таблицами Markdown
        """
        # Регулярное выражение для поиска возможных таблиц
        # Ищем строки, которые содержат большое количество разделителей (|)
        table_pattern = r'((?:^[^\n]*\|[^\n]*\n){2,})'

        def format_table_match(match):
            table_text = match.group(1)
            lines = table_text.strip().split('\n')

            # Проверяем, что это действительно может быть таблица
            if len(lines) < 2:
                return table_text

            # Обрабатываем каждую строку
            md_table = []
            for i, line in enumerate(lines):
                # Исправляем неправильные разделители (должны быть пробелы вокруг |)
                processed_line = re.sub(r'([^\s\|])\|', r'\1 |', line)
                processed_line = re.sub(r'\|([^\s\|])', r'| \1', processed_line)

                # Убеждаемся, что строка начинается и заканчивается разделителем
                if not processed_line.strip().startswith('|'):
                    processed_line = '| ' + processed_line
                if not processed_line.strip().endswith('|'):
                    processed_line = processed_line + ' |'

                md_table.append(processed_line)

            # Добавляем разделитель после заголовка
            if len(md_table) >= 1:
                # Подсчитываем количество столбцов по первой строке
                col_count = md_table[0].count('|') - 1
                separator = '| ' + ' | '.join(['---' for _ in range(col_count)]) + ' |'
                md_table.insert(1, separator)

            return "\n".join(md_table)

        # Заменяем найденные потенциальные таблицы
        return re.sub(table_pattern, format_table_match, text, flags=re.MULTILINE)

    @staticmethod
    def detect_and_format_simple_tables(text: str) -> str:
        """
        Обнаруживает и форматирует простые таблицы в тексте на основе структуры строк.

        Args:
            text: Текст для обработки

        Returns:
            str: Текст с правильно отформатированными таблицами Markdown
        """
        # Ищем потенциальные таблицы, используя такие шаблоны, как:
        # 1. Структурированные строки с числами в начале
        # 2. Строки с большим числом пробелов между словами

        # Первый шаблон - таблицы, где первый столбец это числа или коды
        pattern1 = r'((?:^\s*(?:\d+(?:\.\d+)*|#\s*\d+)\s+[^\n]+\n){3,})'

        # Второй шаблон - строки с постоянной структурой (например, 2+ слова, разделенные пробелами)
        pattern2 = r'((?:^\s*\S+(?:\s{2,}\S+){2,}\s*$\n){3,})'

        def process_table_match(match_text):
            lines = match_text.strip().split('\n')

            # Пробуем определить столбцы на основе выравнивания и пробелов
            col_positions = []

            # Просканируем несколько строк, чтобы найти общие позиции начала слов
            for line in lines[:min(5, len(lines))]:
                pos = 0
                line_positions = [0]  # Начальная позиция

                for i, char in enumerate(line):
                    if char.isspace() and i + 1 < len(line) and not line[i + 1].isspace():
                        line_positions.append(i + 1)

                col_positions.append(line_positions)

            # Найдем общие позиции
            if not col_positions:
                return match_text

            # Находим наиболее часто встречающиеся позиции
            all_positions = []
            for positions in col_positions:
                all_positions.extend(positions)

            # Если нет позиций, возвращаем исходный текст
            if not all_positions:
                return match_text

            # Группируем близкие позиции
            position_clusters = []
            if len(all_positions) > 0:
                current_cluster = [all_positions[0]]

                for pos in sorted(all_positions)[1:]:
                    if pos - current_cluster[-1] < 3:  # Близкие позиции
                        current_cluster.append(pos)
                    else:
                        if current_cluster:
                            position_clusters.append(sum(current_cluster) // len(current_cluster))
                        current_cluster = [pos]

                if current_cluster:
                    position_clusters.append(sum(current_cluster) // len(current_cluster))

            # Если найдено менее 2 позиций, возвращаем исходный текст
            if len(position_clusters) < 2:
                return match_text

            # Создаем Markdown таблицу
            md_table_lines = []

            for line in lines:
                if not line.strip():
                    continue

                row = "| "
                last_pos = 0

                for i, pos in enumerate(position_clusters):
                    if i == 0:
                        # Первый столбец от начала до первой позиции
                        cell_content = line[:pos].strip()
                    else:
                        # Остальные столбцы
                        start = position_clusters[i - 1]
                        end = pos if i < len(position_clusters) else len(line)
                        cell_content = line[start:end].strip()

                    row += cell_content + " | "
                    last_pos = pos

                # Добавляем оставшуюся часть строки в последний столбец
                if last_pos < len(line) and last_pos > 0:
                    cell_content = line[last_pos:].strip()
                    row += cell_content + " |"

                md_table_lines.append(row)

            # Добавляем разделитель после заголовка
            if md_table_lines:
                # Подсчитываем количество столбцов по первой строке
                col_count = md_table_lines[0].count('|') - 1
                separator = "| " + " | ".join(["---" for _ in range(col_count)]) + " |"
                md_table_lines.insert(1, separator)

            return "\n".join(md_table_lines)

        # Обрабатываем первый шаблон
        text = re.sub(pattern1, lambda m: process_table_match(m.group(0)), text, flags=re.MULTILINE)

        # Обрабатываем второй шаблон
        text = re.sub(pattern2, lambda m: process_table_match(m.group(0)), text, flags=re.MULTILINE)

        return text

    @staticmethod
    def postprocess_tables(text: str) -> str:
        """
        Дополнительная обработка таблиц после форматирования.

        Args:
            text: Текст с таблицами

        Returns:
            str: Текст с улучшенными таблицами
        """
        # Исправляем ячейки, содержащие только пробелы
        text = re.sub(r'\|\s+\|', '|  |', text)

        # Исправляем случаи, когда разделитель неправильно отформатирован
        text = re.sub(r'\|\s*[-]+\s*\|', '| --- |', text)

        # Удаляем избыточные пустые строки вокруг таблиц
        text = re.sub(r'\n{3,}(\|.*\|)\n', '\n\n\\1\n', text)

        return text