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
        max_length: int = 512
    ):
        """
        Инициализирует ре-ранкер на базе BGE.

        Args:
            model_name: Название модели для ре-ранкинга
            device: Устройство для вычислений (cuda/cpu)
            batch_size: Размер батча для обработки
            max_length: Максимальная длина входного текста
        """
        self.model_name = model_name
        self.device = device if torch.cuda.is_available() and device == "cuda" else "cpu"
        self.batch_size = batch_size
        self.max_length = max_length

        logger.info(f"Инициализация BGE Reranker с моделью {model_name} на устройстве {self.device}")

        try:
            # Загружаем токенизатор и модель
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self.model.to(self.device)
            self.model.eval()  # Переводим модель в режим оценки (не обучения)
            logger.info(f"Модель {model_name} успешно загружена")
        except Exception as e:
            logger.error(f"Ошибка при загрузке модели: {str(e)}")
            raise RuntimeError(f"Не удалось загрузить модель {model_name}: {str(e)}")

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

        logger.info(f"Выполнение ре-ранкинга для {len(documents)} документов")

        # Получаем тексты документов
        texts = [doc.get(text_key, "") for doc in documents]

        # Вычисляем оценки релевантности
        scores = self._compute_scores(query, texts)

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

        return scores