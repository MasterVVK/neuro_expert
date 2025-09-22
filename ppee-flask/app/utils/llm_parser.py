import json
import re
import logging
from typing import Union, Dict, Any, Optional

logger = logging.getLogger(__name__)


class LLMResponseParser:
    """
    Улучшенный парсер ответов от LLM с поддержкой различных форматов:
    - JSON
    - Двоеточие (ключ: значение)
    - Строки с префиксом РЕЗУЛЬТАТ:
    - Простой текст
    """

    def __init__(self):
        self.formats_tried = []

    def parse_response(self, response: str, query: str) -> Dict[str, Any]:
        """
        Парсит ответ от LLM и извлекает значение для параметра

        Args:
            response: Ответ от LLM
            query: Исходный запрос/параметр для поиска

        Returns:
            Словарь с результатами:
            - value: извлеченное значение
            - confidence: уверенность в результате
            - format: формат, в котором был распознан ответ
            - raw_response: исходный ответ
        """
        if not response:
            return {
                'value': 'Информация не найдена',
                'confidence': 0.0,
                'format': 'empty',
                'raw_response': response
            }

        response = response.strip()
        self.formats_tried = []

        # Проверяем на отсутствие информации
        if self._is_not_found(response):
            return {
                'value': 'Информация не найдена',
                'confidence': 0.1,
                'format': 'not_found',
                'raw_response': response
            }

        # Пытаемся парсить JSON
        json_result = self._try_parse_json(response, query)
        if json_result:
            return json_result

        # Пытаемся найти блок с JSON внутри текста
        json_block_result = self._try_extract_json_block(response, query)
        if json_block_result:
            return json_block_result

        # Пытаемся найти формат с префиксом РЕЗУЛЬТАТ:
        result_prefix = self._try_parse_result_prefix(response, query)
        if result_prefix:
            return result_prefix

        # Пытаемся найти формат "ключ: значение"
        key_value_result = self._try_parse_key_value(response, query)
        if key_value_result:
            return key_value_result

        # Пытаемся найти структурированный ответ с номерами
        structured_result = self._try_parse_structured(response, query)
        if structured_result:
            return structured_result

        # Если ничего не найдено, возвращаем весь ответ
        return {
            'value': response,
            'confidence': self._calculate_confidence(response),
            'format': 'plain_text',
            'raw_response': response,
            'formats_tried': self.formats_tried
        }

    def _is_not_found(self, response: str) -> bool:
        """Проверяет, указывает ли ответ на отсутствие информации"""
        not_found_patterns = [
            'информация не найдена',
            'данные не найдены',
            'не удалось найти',
            'отсутствует информация',
            'нет данных',
            'не указан',
            'не определен',
            'информация отсутствует'
        ]
        response_lower = response.lower()
        return any(pattern in response_lower for pattern in not_found_patterns)

    def _try_parse_json(self, response: str, query: str) -> Optional[Dict[str, Any]]:
        """Пытается распарсить ответ как чистый JSON"""
        self.formats_tried.append('pure_json')
        try:
            json_data = json.loads(response)

            # Если это словарь с нужными полями
            if isinstance(json_data, dict):
                # Ищем поле value или result
                if 'value' in json_data:
                    result = {
                        'value': str(json_data['value']),
                        'confidence': float(json_data.get('confidence', 0.9)),
                        'format': 'json',
                        'raw_response': response,
                        'parsed_data': json_data
                    }
                    # Добавляем информацию об источнике, если есть
                    if 'source' in json_data:
                        result['source'] = json_data['source']
                    if 'chunk' in json_data:
                        result['chunk'] = json_data['chunk']
                    if 'document' in json_data:
                        result['document'] = json_data['document']
                    if 'page' in json_data:
                        result['page'] = json_data['page']
                    return result
                elif 'result' in json_data:
                    result = {
                        'value': str(json_data['result']),
                        'confidence': float(json_data.get('confidence', 0.9)),
                        'format': 'json',
                        'raw_response': response,
                        'parsed_data': json_data
                    }
                    # Добавляем информацию об источнике, если есть
                    if 'source' in json_data:
                        result['source'] = json_data['source']
                    if 'chunk' in json_data:
                        result['chunk'] = json_data['chunk']
                    if 'document' in json_data:
                        result['document'] = json_data['document']
                    if 'page' in json_data:
                        result['page'] = json_data['page']
                    return result

                # Ищем по имени параметра
                query_lower = query.lower()
                for key, value in json_data.items():
                    if key.lower() in query_lower or query_lower in key.lower():
                        return {
                            'value': str(value),
                            'confidence': 0.85,
                            'format': 'json',
                            'raw_response': response,
                            'parsed_data': json_data
                        }

                # Если есть единственное поле, берем его
                if len(json_data) == 1:
                    key, value = next(iter(json_data.items()))
                    return {
                        'value': str(value),
                        'confidence': 0.8,
                        'format': 'json',
                        'raw_response': response,
                        'parsed_data': json_data
                    }

            # Если это список с одним элементом
            elif isinstance(json_data, list) and len(json_data) == 1:
                return {
                    'value': str(json_data[0]),
                    'confidence': 0.8,
                    'format': 'json_array',
                    'raw_response': response,
                    'parsed_data': json_data
                }

        except (json.JSONDecodeError, ValueError):
            pass

        return None

    def _try_extract_json_block(self, response: str, query: str) -> Optional[Dict[str, Any]]:
        """Пытается найти и извлечь JSON блок из текста"""
        self.formats_tried.append('json_block')

        # Паттерны для поиска JSON блоков
        json_patterns = [
            r'```json\s*(.*?)\s*```',  # Markdown JSON блок
            r'```\s*(.*?)\s*```',       # Обычный код блок
            r'\{[^{}]*\}',              # Простой JSON объект
            r'\{.*?\}',                 # JSON объект с вложенностью
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, response, re.DOTALL)
            for match in matches:
                # Пробуем распарсить найденный блок
                result = self._try_parse_json(match, query)
                if result:
                    result['format'] = 'json_block'
                    return result

        return None

    def _try_parse_result_prefix(self, response: str, query: str) -> Optional[Dict[str, Any]]:
        """Пытается найти ответ с префиксом РЕЗУЛЬТАТ:"""
        self.formats_tried.append('result_prefix')

        patterns = [
            r'РЕЗУЛЬТАТ:\s*(.+)',
            r'Результат:\s*(.+)',
            r'ОТВЕТ:\s*(.+)',
            r'Ответ:\s*(.+)',
            r'ЗНАЧЕНИЕ:\s*(.+)',
            r'Значение:\s*(.+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, response, re.MULTILINE | re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                return {
                    'value': value,
                    'confidence': 0.9,
                    'format': 'result_prefix',
                    'raw_response': response
                }

        return None

    def _try_parse_key_value(self, response: str, query: str) -> Optional[Dict[str, Any]]:
        """Пытается найти формат 'ключ: значение'"""
        self.formats_tried.append('key_value')

        lines = response.split('\n')

        # Сначала ищем точное совпадение с query
        query_pattern = re.escape(query)
        for line in lines:
            match = re.search(f'{query_pattern}\\s*:\\s*(.+)', line, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if value and not self._is_not_found(value):
                    return {
                        'value': value,
                        'confidence': 0.95,
                        'format': 'key_value_exact',
                        'raw_response': response
                    }

        # Ищем частичное совпадение
        query_words = query.lower().split()
        for line in lines:
            if ':' in line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    key = parts[0].strip().lower()
                    value = parts[1].strip()

                    # Проверяем, содержит ли ключ слова из запроса
                    if any(word in key for word in query_words) and value:
                        if not self._is_not_found(value):
                            return {
                                'value': value,
                                'confidence': 0.85,
                                'format': 'key_value_partial',
                                'raw_response': response
                            }

        # Если есть единственная строка с двоеточием
        lines_with_colon = [line for line in lines if ':' in line and line.strip()]
        if len(lines_with_colon) == 1:
            parts = lines_with_colon[0].split(':', 1)
            if len(parts) == 2:
                value = parts[1].strip()
                if value and not self._is_not_found(value):
                    return {
                        'value': value,
                        'confidence': 0.75,
                        'format': 'key_value_single',
                        'raw_response': response
                    }

        return None

    def _try_parse_structured(self, response: str, query: str) -> Optional[Dict[str, Any]]:
        """Пытается найти структурированный ответ с нумерацией или буллетами"""
        self.formats_tried.append('structured')

        # Паттерны для структурированных ответов
        patterns = [
            r'^\d+\.\s*(.+)$',      # 1. значение
            r'^-\s*(.+)$',          # - значение
            r'^•\s*(.+)$',          # • значение
            r'^\*\s*(.+)$',         # * значение
        ]

        lines = response.split('\n')
        structured_values = []

        for line in lines:
            line = line.strip()
            for pattern in patterns:
                match = re.match(pattern, line)
                if match:
                    value = match.group(1).strip()
                    if value and not self._is_not_found(value):
                        # Проверяем, относится ли к нашему запросу
                        if any(word in value.lower() for word in query.lower().split()):
                            structured_values.append(value)
                            break

        if structured_values:
            # Если нашли одно значение
            if len(structured_values) == 1:
                return {
                    'value': structured_values[0],
                    'confidence': 0.85,
                    'format': 'structured_single',
                    'raw_response': response
                }
            # Если нашли несколько, объединяем
            else:
                return {
                    'value': '; '.join(structured_values),
                    'confidence': 0.8,
                    'format': 'structured_multiple',
                    'raw_response': response,
                    'values': structured_values
                }

        return None

    def _calculate_confidence(self, response: str) -> float:
        """Рассчитывает уверенность в ответе"""
        uncertainty_phrases = [
            'возможно', 'вероятно', 'может быть', 'предположительно',
            'не ясно', 'не уверен', 'не определено', 'примерно',
            'около', 'приблизительно', 'предполагается'
        ]

        confidence = 0.7  # Базовая уверенность для plain text
        response_lower = response.lower()

        for phrase in uncertainty_phrases:
            if phrase in response_lower:
                confidence -= 0.1

        # Увеличиваем уверенность для коротких конкретных ответов
        if len(response) < 100 and not any(phrase in response_lower for phrase in uncertainty_phrases):
            confidence += 0.1

        return max(0.1, min(confidence, 1.0))


def extract_value_from_response(response: str, query: str) -> str:
    """
    Обратная совместимость с существующей функцией extract_value_from_response
    """
    parser = LLMResponseParser()
    result = parser.parse_response(response, query)
    return result['value']


def calculate_confidence(response: str) -> float:
    """
    Обратная совместимость с существующей функцией calculate_confidence
    """
    parser = LLMResponseParser()
    return parser._calculate_confidence(response)