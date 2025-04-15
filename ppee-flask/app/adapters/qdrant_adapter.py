import os
import logging
from typing import List, Dict, Any, Optional

from ppee_analyzer.vector_store import QdrantManager, BGEReranker
from ppee_analyzer.document_processor import PPEEDocumentSplitter, DoclingPDFConverter, PDFToMarkdownConverter

logger = logging.getLogger(__name__)


class QdrantAdapter:
    """Адаптер для работы с Qdrant через ppee_analyzer"""

    def __init__(self,
                 host: str = "localhost",
                 port: int = 6333,
                 collection_name: str = "ppee_applications",
                 embeddings_type: str = "ollama",
                 model_name: str = "bge-m3",
                 device: str = "cuda",
                 ollama_url: str = "http://localhost:11434",
                 use_reranker: bool = False,
                 reranker_model: str = "BAAI/bge-reranker-v2-m3"):
        """
        Инициализирует адаптер для Qdrant.

        Args:
            host: Хост Qdrant сервера
            port: Порт Qdrant сервера
            collection_name: Имя коллекции в Qdrant
            embeddings_type: Тип эмбеддингов
            model_name: Название модели эмбеддингов
            device: Устройство для вычислений
            ollama_url: URL для Ollama API
            use_reranker: Использовать ре-ранкер для уточнения результатов
            reranker_model: Название модели ре-ранкера
        """
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.embeddings_type = embeddings_type
        self.model_name = model_name
        self.device = device
        self.ollama_url = ollama_url

        # Инициализируем QdrantManager
        self.qdrant_manager = QdrantManager(
            collection_name=collection_name,
            host=host,
            port=port,
            embeddings_type=embeddings_type,
            model_name=model_name,
            device=device,
            ollama_url=ollama_url
        )

        # Инициализируем сплиттер документов
        self.splitter = PPEEDocumentSplitter()

        # Инициализация ре-ранкера (при необходимости)
        self.use_reranker = use_reranker
        if use_reranker:
            try:
                self.reranker = BGEReranker(
                    model_name=reranker_model,
                    device=device
                )
                logger.info(f"Ре-ранкер инициализирован с моделью {reranker_model}")
            except Exception as e:
                logger.error(f"Ошибка при инициализации ре-ранкера: {str(e)}")
                self.use_reranker = False

        logger.info(f"QdrantAdapter инициализирован для коллекции {collection_name} на {host}:{port}")

    def _convert_pdf_to_markdown(self, pdf_path: str) -> str:
        """
        Конвертирует PDF в Markdown для последующей обработки.

        Args:
            pdf_path: Путь к PDF файлу

        Returns:
            str: Путь к созданному Markdown файлу
        """
        try:
            # Проверяем, что файл существует
            if not os.path.isfile(pdf_path):
                logger.error(f"PDF файл не найден: {pdf_path}")
                raise FileNotFoundError(f"PDF файл не найден: {pdf_path}")

            # Создаем путь для Markdown файла
            md_path = os.path.splitext(pdf_path)[0] + ".md"

            # Пытаемся использовать DoclingPDFConverter
            try:
                logger.info(f"Попытка конвертации PDF через DoclingPDFConverter: {pdf_path}")
                converter = DoclingPDFConverter(preserve_tables=True)
                converter.convert_pdf_to_markdown(pdf_path, md_path)

                if os.path.exists(md_path) and os.path.getsize(md_path) > 0:
                    logger.info(f"PDF успешно конвертирован через DoclingPDFConverter: {md_path}")
                    return md_path
                else:
                    logger.warning(f"DoclingPDFConverter не создал валидный Markdown файл")
            except Exception as e:
                logger.warning(f"Ошибка при использовании DoclingPDFConverter: {str(e)}")

            # Если DoclingPDFConverter не сработал, пробуем PDFToMarkdownConverter
            logger.info(f"Попытка конвертации PDF через PDFToMarkdownConverter: {pdf_path}")
            converter = PDFToMarkdownConverter()
            converter.convert_pdf_to_markdown(pdf_path, md_path)

            if os.path.exists(md_path) and os.path.getsize(md_path) > 0:
                logger.info(f"PDF успешно конвертирован через PDFToMarkdownConverter: {md_path}")
                return md_path
            else:
                logger.error(f"Не удалось конвертировать PDF в Markdown: {pdf_path}")
                raise RuntimeError(f"Не удалось конвертировать PDF в Markdown: {pdf_path}")

        except Exception as e:
            logger.exception(f"Ошибка при конвертации PDF в Markdown: {str(e)}")
            raise

    def search(self,
               application_id: str,
               query: str,
               limit: int = 5,
               rerank_limit: int = None) -> List[Dict[str, Any]]:
        """
        Выполняет семантический поиск с опциональным ре-ранкингом.

        Args:
            application_id: ID заявки
            query: Поисковый запрос
            limit: Количество результатов
            rerank_limit: Количество документов для ре-ранкинга (None - все найденные)

        Returns:
            List[Dict[str, Any]]: Результаты поиска
        """
        try:
            logger.info(f"Выполнение поиска '{query}' для заявки {application_id}")

            # Увеличиваем limit для ре-ранкинга
            search_limit = limit
            if self.use_reranker and rerank_limit is None:
                # Получаем больше результатов, чтобы ре-ранкер мог выбрать лучшие
                search_limit = max(limit * 3, 20)
            elif rerank_limit is not None:
                search_limit = rerank_limit

            # Выполняем поиск
            docs = self.qdrant_manager.search(
                query=query,
                filter_dict={"application_id": application_id},
                k=search_limit
            )

            # Преобразуем результаты
            results = []
            for doc in docs:
                results.append({
                    "text": doc.page_content,
                    "metadata": doc.metadata,
                    "score": doc.metadata.get('score', 0.0)  # Оценка векторного поиска
                })

            # Применяем ре-ранкинг, если он включен
            if self.use_reranker and results:
                logger.info(f"Применение ре-ранкинга к {len(results)} результатам")
                reranked_results = self.reranker.rerank(
                    query=query,
                    documents=results,
                    top_k=limit,
                    text_key="text"
                )
                return reranked_results[:limit]
            else:
                return results[:limit]

        except Exception as e:
            logger.error(f"Ошибка при поиске: {str(e)}")
            return []

    # ... остальные методы класса остаются без изменений ...