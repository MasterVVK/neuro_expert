from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility
import dspy
import numpy as np
import os
import requests
import json
import time
from typing import List, Dict, Any, Optional, Union


# Установите зависимости перед запуском:
# pip install pymilvus numpy dspy requests

# Класс для создания эмбеддингов через Ollama с моделью BGE-M3
class OllamaBGEM3Embedder:
    def __init__(self, model_name='bge-m3:latest', base_url='http://localhost:11434'):
        self.model_name = model_name
        self.base_url = base_url
        self.embedding_endpoint = f"{base_url}/api/embeddings"

        # Проверяем доступность модели и определяем размерность
        print(f"Проверка модели {model_name} для эмбеддингов через Ollama")

        # Пробуем загрузить модель, если она еще не загружена
        self._ensure_model_available()

        # Определяем размерность эмбеддингов
        self.embedding_dim = self._get_embedding_dimension()
        print(f"Модель {model_name} готова. Размерность эмбеддингов: {self.embedding_dim}")

    def _ensure_model_available(self):
        """Проверяет доступность модели и загружает ее при необходимости"""
        try:
            # Проверяем, доступна ли модель
            response = requests.get(f"{self.base_url}/api/tags")
            response.raise_for_status()

            models = response.json().get("models", [])
            model_names = [model.get("name") for model in models]

            if self.model_name not in model_names:
                print(f"Модель {self.model_name} не найдена. Пробуем загрузить...")

                # Запускаем загрузку модели
                pull_response = requests.post(
                    f"{self.base_url}/api/pull",
                    json={"name": self.model_name}
                )
                pull_response.raise_for_status()

                # Ждем завершения загрузки
                print(f"Запущена загрузка модели {self.model_name}. Это может занять некоторое время...")

                # Даем время на начало загрузки
                time.sleep(5)

                # Простая проверка готовности модели - пробуем получить эмбеддинг
                max_retries = 10
                for i in range(max_retries):
                    try:
                        test_embedding = self.get_query_embedding("Test loading model")
                        print(f"Модель {self.model_name} успешно загружена!")
                        return
                    except Exception as e:
                        print(f"Ожидание загрузки модели... Попытка {i + 1}/{max_retries}")
                        time.sleep(10)

                raise TimeoutError(f"Превышено время ожидания загрузки модели {self.model_name}")
            else:
                print(f"Модель {self.model_name} уже доступна")

        except Exception as e:
            print(f"Ошибка при проверке/загрузке модели: {e}")
            # Продолжаем выполнение, даже если не удалось проверить модель

    def _get_embedding_dimension(self):
        """Определяет размерность эмбеддингов"""
        try:
            # Получаем эмбеддинг для тестового текста
            test_embedding = self.get_query_embedding("This is a test")
            return len(test_embedding)
        except Exception as e:
            print(f"Ошибка при определении размерности эмбеддингов: {e}")
            # Для BGE-M3 чаще всего используется размерность 1024
            print("Используем размерность эмбеддингов по умолчанию для BGE-M3: 1024")
            return 1024

    def get_embeddings(self, texts: List[str], batch_size=10) -> List[List[float]]:
        """Получение эмбеддингов для списка текстов с учетом размера пакета"""
        embeddings = []

        # Обрабатываем тексты партиями, чтобы избежать перегрузки сервера
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            print(f"Обработка эмбеддингов: {i}/{len(texts)} до {i + len(batch_texts)}/{len(texts)}")

            # Обрабатываем каждый текст в пакете
            batch_embeddings = []
            for text in batch_texts:
                try:
                    embedding = self.get_query_embedding(text)
                    batch_embeddings.append(embedding)
                except Exception as e:
                    print(f"Ошибка при получении эмбеддинга: {e}")
                    # В случае ошибки генерируем случайный вектор
                    batch_embeddings.append(np.random.rand(self.embedding_dim).tolist())

            embeddings.extend(batch_embeddings)

            # Небольшая пауза между пакетами, чтобы не перегружать сервер
            if i + batch_size < len(texts):
                time.sleep(0.5)

        return embeddings

    def get_query_embedding(self, text: str) -> List[float]:
        """Получение эмбеддинга для одного текста запроса"""
        try:
            payload = {
                "model": self.model_name,
                "prompt": text
            }

            response = requests.post(self.embedding_endpoint, json=payload)
            response.raise_for_status()

            data = response.json()
            if 'embedding' not in data:
                raise ValueError(f"API Ollama не вернуло эмбеддинг. Ответ: {data}")

            return data['embedding']
        except Exception as e:
            print(f"Ошибка при запросе к Ollama API: {e}")
            raise


# Функция для загрузки документов из файла
def load_documents_from_file(file_path="documents.txt"):
    try:
        print(f"Загрузка документов из файла {file_path}")
        if not os.path.exists(file_path):
            print(f"Файл {file_path} не найден!")
            return []
        with open(file_path, 'r', encoding='utf-8') as f:
            documents = [line.strip() for line in f if line.strip()]
        print(f"Загружено {len(documents)} документов")
        return documents
    except Exception as e:
        print(f"Ошибка при загрузке документов: {e}")
        return []


# Создаем класс MilvusRM для интеграции Milvus с DSPy
class MilvusRM:
    def __init__(
            self,
            milvus_collection_name: str,
            embedder: OllamaBGEM3Embedder,
            milvus_host: str = "localhost",
            milvus_port: str = "19530",
            metadata_field: str = "document",
            embedding_field: str = "embedding",
            id_field: str = "id",
            text_field: str = "text",
            recreate_collection: bool = True,
    ):
        """Конструктор для создания Milvus Retriever Module."""
        self.milvus_collection_name = milvus_collection_name
        self.milvus_host = milvus_host
        self.milvus_port = milvus_port
        self.embedder = embedder
        self.embedding_dim = embedder.embedding_dim  # Получаем размерность из embedder
        self.metadata_field = metadata_field
        self.embedding_field = embedding_field
        self.id_field = id_field
        self.text_field = text_field
        self.recreate_collection = recreate_collection

        # Подключение к Milvus
        connections.connect(host=milvus_host, port=milvus_port)

        # Принудительно удаляем и пересоздаем коллекцию
        self._recreate_collection()

        # Получаем коллекцию
        self.collection = Collection(name=milvus_collection_name)
        self.collection.load()

    def _recreate_collection(self):
        """Удаление и пересоздание коллекции"""
        # Проверяем и удаляем существующую коллекцию
        try:
            if utility.has_collection(self.milvus_collection_name):
                print(f"Удаление существующей коллекции {self.milvus_collection_name}")
                utility.drop_collection(self.milvus_collection_name)
                print(f"Коллекция {self.milvus_collection_name} успешно удалена")
        except Exception as e:
            print(f"Ошибка при удалении коллекции: {e}")

        # Создаем новую коллекцию
        try:
            print(f"Создание коллекции {self.milvus_collection_name} с размерностью {self.embedding_dim}")

            # Определение схемы коллекции
            fields = [
                FieldSchema(name=self.id_field, dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name=self.text_field, dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name=self.metadata_field, dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name=self.embedding_field, dtype=DataType.FLOAT_VECTOR, dim=self.embedding_dim)
            ]
            schema = CollectionSchema(fields=fields)

            # Создание коллекции
            collection = Collection(name=self.milvus_collection_name, schema=schema)
            print(f"Коллекция {self.milvus_collection_name} успешно создана")

            # Создание индекса для быстрого поиска
            index_params = {
                "metric_type": "COSINE",
                "index_type": "HNSW",
                "params": {"M": 8, "efConstruction": 64}
            }
            collection.create_index(field_name=self.embedding_field, index_params=index_params)
            print(f"Индекс создан для поля {self.embedding_field}")

        except Exception as e:
            print(f"Ошибка при создании коллекции: {e}")
            raise e

    def add(self, documents: List[str]):
        """Добавление документов в Milvus с автоматическим созданием эмбеддингов."""
        if not documents:
            return

        print("Создание эмбеддингов для документов через BGE-M3...")
        embeddings = self.embedder.get_embeddings(documents)
        print(f"Созданы эмбеддинги размерности {len(embeddings[0])}")

        # Проверка размерности
        if len(embeddings[0]) != self.embedding_dim:
            raise ValueError(
                f"Размерность эмбеддингов {len(embeddings[0])} не соответствует размерности коллекции {self.embedding_dim}")

        # Формируем данные для вставки в правильном формате для Milvus
        entities = []
        for i, (doc, emb) in enumerate(zip(documents, embeddings)):
            entity = {
                self.text_field: doc,
                self.metadata_field: doc,  # В данном случае используем сам документ как метаданные
                self.embedding_field: emb
            }
            entities.append(entity)

        self.collection.insert(entities)
        self.collection.flush()  # Гарантирует запись данных на диск
        print(f"Добавлены документы в коллекцию, размерность векторов: {self.embedding_dim}")

    def search(self, query: str, k: int = 3) -> List[Dict[str, Any]]:
        """Поиск ближайших документов к запросу."""
        print(f"Создание эмбеддинга для запроса: '{query}'")
        query_embedding = self.embedder.get_query_embedding(query)

        # Проверка размерности запроса
        if len(query_embedding) != self.embedding_dim:
            raise ValueError(
                f"Размерность запроса {len(query_embedding)} не соответствует размерности коллекции {self.embedding_dim}")

        search_params = {"metric_type": "COSINE", "params": {"ef": 64}}

        results = self.collection.search(
            data=[query_embedding],
            anns_field=self.embedding_field,
            param=search_params,
            limit=k,
            output_fields=[self.text_field]
        )

        retrieved = []
        for hits in results:
            for hit in hits:
                retrieved.append({
                    "score": hit.score,
                    "text": hit.entity.get(self.text_field),
                    "metadata": {}
                })

        return retrieved

    def __call__(self, query: str, k: int = 3):
        """Метод для интеграции с DSPy."""
        try:
            results = self.search(query, k)

            # Формат, ожидаемый DSPy
            class RetrieveResult:
                def __init__(self, passages):
                    self.passages = passages

            if not results:
                print("Поиск не дал результатов")
                return RetrieveResult([])

            return RetrieveResult([r["text"] for r in results])
        except Exception as e:
            print(f"Ошибка при поиске: {e}")
            # В случае ошибки возвращаем пустой результат или документы-заглушки
            print("Возвращаем заглушку вместо результатов поиска")
            # Используем первые k документов как заглушку
            docs = load_documents_from_file()
            return RetrieveResult(docs[:k] if docs and len(docs) >= k else [])


# === ОСНОВНОЙ КОД ===

# Загружаем документы из файла
documents = load_documents_from_file("documents.txt")

# Создаем экземпляр embedder с BGE-M3
embedder = OllamaBGEM3Embedder(model_name='bge-m3:latest', base_url='http://localhost:11434')

# Принудительное пересоздание Milvus коллекции
milvus_retriever = MilvusRM(
    milvus_collection_name="document_parts",
    embedder=embedder,
    milvus_host="localhost",
    milvus_port="19530",
    recreate_collection=True
)

# Всегда загружаем документы заново
print("\n=== ДОБАВЛЕНИЕ ДОКУМЕНТОВ В MILVUS ===")
milvus_retriever.add(documents)
print(f"Добавлено {len(documents)} документов в Milvus")

# Настройка языковой модели для генерации (используем gemma:2b для генерации ответов)
gemma_model = dspy.LM('ollama/gemma:2b',
                      api_base='http://localhost:11434',
                      api_key='')

# Настройка DSPy
dspy.configure(lm=gemma_model, rm=milvus_retriever)


# Определение класса для извлечения событий
class Event(dspy.Signature):
    description = dspy.InputField(
        desc="Textual description of the event, including name, location and dates"
    )
    event_name = dspy.OutputField(desc="Name of the event")
    location = dspy.OutputField(desc="Location of the event")
    start_date = dspy.OutputField(desc="Start date of the event, YYYY-MM-DD")
    end_date = dspy.OutputField(desc="End date of the event, YYYY-MM-DD")


# Модуль для извлечения событий
class EventExtractor(dspy.Module):
    def __init__(self):
        super().__init__()
        # Используем наш MilvusRM напрямую
        self.retriever = milvus_retriever
        # Predict модуль для извлечения информации
        self.predict = dspy.Predict(Event)

    def forward(self, query: str):
        # Получение релевантных документов
        results = self.retriever(query, k=3)

        # Извлечение информации о событиях
        events = []
        for document in results.passages:
            print(f"Анализ документа: {document[:100]}...")
            event = self.predict(description=document)
            events.append(event)

        return events


# Инициализация и выполнение запроса
extractor = EventExtractor()
query = "Blockchain events close to Europe"
print(f"\nПоиск: {query}")
result = extractor.forward(query)

# Вывод результатов
print("\nИзвлеченные события:")
for i, event in enumerate(result, 1):
    print(f"\nСобытие {i}:")
    print(f"Название: {event.event_name}")
    print(f"Место: {event.location}")
    print(f"Дата начала: {event.start_date}")
    print(f"Дата окончания: {event.end_date}")