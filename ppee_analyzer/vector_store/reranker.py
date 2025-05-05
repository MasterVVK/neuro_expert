"""
Класс для ре-ранкинга результатов поиска с использованием bge-reranker
"""

import logging
import torch
from typing import List, Dict, Any, Tuple
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)

class BGEReranker:
    """Класс для ре-ранкинга результатов с использованием BGE Reranker"""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        device: str = "cuda",
        batch_size: int = 8,
        max_length: int = 4096,
        min_vram_mb: int = 500  # Минимальное количество свободной VRAM в МБ
    ):
        """
        Инициализирует ре-ранкер на базе BGE.

        Args:
            model_name: Название модели для ре-ранкинга
            device: Устройство для вычислений (cuda/cpu)
            batch_size: Размер батча для обработки
            max_length: Максимальная длина входного текста
            min_vram_mb: Минимальное количество свободной VRAM в МБ для использования GPU
        """
        self.model_name = model_name
        self.requested_device = device  # Сохраняем изначально запрошенное устройство
        self.batch_size = batch_size
        self.max_length = max_length
        self.min_vram_mb = min_vram_mb

        # Определяем устройство с учетом доступной VRAM
        if device == "cuda" and torch.cuda.is_available():
            if self._check_vram_availability(min_vram_mb):
                self.device = "cuda"
                logger.info(f"Достаточно VRAM для использования GPU")
            else:
                self.device = "cpu"
                logger.warning(f"Недостаточно VRAM для использования GPU. Используем CPU.")
        else:
            self.device = "cpu"
            logger.info("GPU недоступен или не запрошен. Используем CPU.")

        logger.info(f"Инициализация BGE Reranker с моделью {model_name} на устройстве {self.device}")

        try:
            # Загружаем токенизатор и модель
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self.model.to(self.device)
            self.model.eval()  # Переводим модель в режим оценки (не обучения)
            logger.info(f"Модель {model_name} успешно загружена на {self.device}")
        except Exception as e:
            logger.error(f"Ошибка при загрузке модели: {str(e)}")
            raise RuntimeError(f"Не удалось загрузить модель {model_name}: {str(e)}")

    def _check_vram_availability(self, min_free_mb: int = 500) -> bool:
        """
        Проверяет доступность VRAM для работы ререйтинга.

        Args:
            min_free_mb: Минимальное количество свободной памяти в МБ

        Returns:
            bool: Достаточно ли памяти
        """
        if not torch.cuda.is_available():
            logger.warning("CUDA недоступен, проверка VRAM невозможна")
            return False

        try:
            # Очищаем кэш CUDA перед проверкой
            torch.cuda.empty_cache()

            # Используем subprocess для вызова nvidia-smi, чтобы получить реальные данные о памяти
            import subprocess
            import re

            # Выполняем команду nvidia-smi для получения информации о памяти
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.total,memory.used,memory.free', '--format=csv,noheader,nounits'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True)

            if result.returncode != 0:
                logger.warning(f"Не удалось выполнить nvidia-smi: {result.stderr}")
                # Запасной вариант - используем torch.cuda
                device = torch.cuda.current_device()
                total_mem = torch.cuda.get_device_properties(device).total_memory
                allocated_mem = torch.cuda.memory_allocated(device)
                free_mem = total_mem - allocated_mem
                free_mem_mb = free_mem / (1024 * 1024)
            else:
                # Парсим вывод nvidia-smi
                memory_values = result.stdout.strip().split(',')
                total_mem_mb = float(memory_values[0].strip())
                used_mem_mb = float(memory_values[1].strip())
                free_mem_mb = float(memory_values[2].strip())

                logger.info(
                    f"Данные от nvidia-smi: Всего: {total_mem_mb} МБ, Используется: {used_mem_mb} МБ, Свободно: {free_mem_mb} МБ")

            # Оцениваем необходимую память для модели
            estimated_mem = self._estimate_memory_requirements()
            logger.info(f"Оценочные требования памяти для модели: {estimated_mem:.1f} МБ")

            # Принимаем решение на основе свободной памяти
            if free_mem_mb >= min_free_mb and free_mem_mb >= estimated_mem:
                logger.info(f"Проверка VRAM: ОК (свободно {free_mem_mb:.1f} МБ > требуется {min_free_mb} МБ)")
                return True
            else:
                logger.warning(f"Проверка VRAM: НЕ ОК (свободно {free_mem_mb:.1f} МБ < требуется {min_free_mb} МБ)")
                return False
        except Exception as e:
            logger.error(f"Ошибка при проверке VRAM: {str(e)}")
            return False

    def _estimate_memory_requirements(self) -> float:
        """
        Оценивает потребление памяти для ререйтера.

        Returns:
            float: Оценка потребления VRAM в МБ
        """
        # Примерные размеры моделей в миллионах параметров
        model_sizes = {
            "bge-reranker-base": 110,  # ~110M параметров
            "bge-reranker-v2-m3": 350,  # ~350M параметров
            "bge-reranker-large": 870,  # ~870M параметров
        }

        # Находим ближайшую модель из известных
        model_size = 350  # По умолчанию для m3
        for known_model, size in model_sizes.items():
            if known_model.lower() in self.model_name.lower():
                model_size = size
                break

        # Расчет памяти (в МБ)
        model_memory = model_size * 4 / 1024  # Параметры модели (FP32)

        # Размер входных данных (2 входа - запрос и документ)
        input_memory = (self.batch_size * self.max_length * 2 * 2) / 1024  # 2 байта при mixed precision

        # Промежуточные активации и буферы (приблизительно)
        activations_memory = (model_memory * 0.4) + (input_memory * 3)

        # Служебная память PyTorch
        pytorch_overhead = 200

        # Общая оценка
        total_memory = model_memory + input_memory + activations_memory + pytorch_overhead

        return total_memory

    def _fallback_to_cpu(self) -> None:
        """
        Переключает модель на CPU при проблемах с VRAM.
        """
        if self.device != "cpu":
            logger.warning(f"Переключение модели {self.model_name} с {self.device} на CPU")
            self.device = "cpu"

            try:
                # Перемещаем модель на CPU
                self.model = self.model.to("cpu")

                # Очищаем кэш CUDA
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                logger.info(f"Модель успешно перемещена на CPU")
            except Exception as e:
                logger.error(f"Ошибка при переключении на CPU: {str(e)}")

                # Если не удалось переместить модель, пересоздаем её
                try:
                    # Удаляем текущую модель
                    del self.model

                    # Очищаем кэш CUDA
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

                    # Заново загружаем модель на CPU
                    self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
                    self.model.to("cpu")
                    self.model.eval()
                    logger.info(f"Модель {self.model_name} успешно перезагружена на CPU")
                except Exception as reload_error:
                    logger.error(f"Критическая ошибка при перезагрузке модели: {str(reload_error)}")
                    raise

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = None,
        text_key: str = "text"
    ) -> List[Dict[str, Any]]:
        """
        Выполняет ре-ранкинг списка документов.

        Args:
            query: Поисковый запрос
            documents: Список документов (словарей с ключом 'text' или указанным в text_key)
            top_k: Количество документов в возвращаемом результате (None - все)
            text_key: Ключ, по которому извлекается текстовое содержимое документа

        Returns:
            List[Dict[str, Any]]: Отсортированный список документов с добавленной оценкой rerank_score
        """
        if not documents:
            return []

        if top_k is None:
            top_k = len(documents)

        logger.info(f"Выполнение ре-ранкинга для {len(documents)} документов на устройстве {self.device}")

        # Если использование GPU, проверяем доступность VRAM
        if self.device == "cuda" and not self._check_vram_availability(self.min_vram_mb):
            logger.warning(f"Недостаточно VRAM перед ре-ранкингом. Переключаемся на CPU")
            self._fallback_to_cpu()

        # Получаем тексты документов
        texts = [doc.get(text_key, "") for doc in documents]

        try:
            # Вычисляем оценки релевантности
            scores = self._compute_scores(query, texts)
        except RuntimeError as e:
            # Если ошибка связана с CUDA и мы используем GPU
            if "CUDA out of memory" in str(e) and self.device != "cpu":
                logger.warning(f"Ошибка CUDA при ре-ранкинге: {str(e)}")

                # Переключаемся на CPU и повторяем попытку
                self._fallback_to_cpu()

                # Повторно вычисляем оценки
                scores = self._compute_scores(query, texts)
            else:
                # Если ошибка не связана с CUDA или мы уже на CPU, пробрасываем её дальше
                raise

        # Добавляем оценки ре-ранкинга к документам
        for i, score in enumerate(scores):
            documents[i]["rerank_score"] = float(score)

        # Сортируем документы по убыванию оценки ре-ранкинга
        reranked_documents = sorted(documents, key=lambda x: x.get("rerank_score", 0.0), reverse=True)

        # Возвращаем top_k документов
        return reranked_documents[:top_k]

    def _compute_scores(self, query: str, texts: List[str]) -> List[float]:
        """
        Вычисляет оценки релевантности между запросом и текстами.

        Args:
            query: Поисковый запрос
            texts: Список текстов документов

        Returns:
            List[float]: Список оценок релевантности
        """
        scores = []

        # Обрабатываем тексты батчами
        for i in range(0, len(texts), self.batch_size):
            batch_texts = texts[i:i + self.batch_size]

            try:
                # Подготавливаем входные данные для модели
                features = self.tokenizer(
                    [query] * len(batch_texts),
                    batch_texts,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt"
                ).to(self.device)

                # Отключаем вычисление градиентов
                with torch.no_grad():
                    outputs = self.model(**features)
                    batch_scores = outputs.logits.squeeze(-1)

                # Добавляем оценки батча к общему списку
                scores.extend(batch_scores.cpu().tolist())

            except RuntimeError as e:
                # Если ошибка CUDA и мы на GPU, переключаемся на CPU
                if "CUDA out of memory" in str(e) and self.device != "cpu":
                    logger.warning(f"Ошибка CUDA при обработке батча {i}: {str(e)}")

                    # Переключаемся на CPU
                    self._fallback_to_cpu()

                    # Подготавливаем входные данные заново для CPU
                    features = self.tokenizer(
                        [query] * len(batch_texts),
                        batch_texts,
                        padding=True,
                        truncation=True,
                        max_length=self.max_length,
                        return_tensors="pt"
                    ).to(self.device)  # теперь self.device - это "cpu"

                    # Вычисляем оценки
                    with torch.no_grad():
                        outputs = self.model(**features)
                        batch_scores = outputs.logits.squeeze(-1)

                    # Добавляем оценки батча к общему списку
                    scores.extend(batch_scores.cpu().tolist())
                else:
                    # Другой тип ошибки - пробрасываем дальше
                    raise

        return scores

    def cleanup(self):
        """
        Освобождает ресурсы, занимаемые моделью.
        Вызывается для очистки VRAM после использования.
        """
        logger.info("Освобождение ресурсов модели ререйтинга...")

        # Выгружаем модель из памяти GPU
        if hasattr(self, 'model'):
            try:
                # Переносим модель на CPU, если она была на GPU
                if self.device == "cuda":
                    self.model = self.model.to('cpu')

                # Удаляем ссылки на модель и токенизатор
                del self.model
                if hasattr(self, 'tokenizer'):
                    del self.tokenizer
                self.model = None
                self.tokenizer = None

                # Явно вызываем сборщик мусора
                import gc
                gc.collect()

                # Очищаем кэш CUDA если доступно
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.info("VRAM очищена после использования ререйтинга")
            except Exception as e:
                logger.error(f"Ошибка при очистке ресурсов ререйтинга: {str(e)}")