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

    def index_document(self,
                       application_id: str,
                       document_path: str,
                       delete_existing: bool = False) -> Dict[str, Any]:
        """
        Индексирует документ в Qdrant.

        Args:
            application_id: ID заявки
            document_path: Путь к документу
            delete_existing: Удалить существующие данные заявки

        Returns:
            Dict[str, Any]: Результаты индексации
        """
        try:
            # Проверяем, что файл существует
            if not os.path.exists(document_path):
                error_msg = f"Документ не найден по пути: {document_path}"
                logger.error(error_msg)
                return {
                    "application_id": application_id,
                    "document_path": document_path,
                    "error": error_msg,
                    "status": "error"
                }

            logger.info(f"Начало индексации документа {document_path} для заявки {application_id}")
            logger.info(f"Абсолютный путь к файлу: {os.path.abspath(document_path)}")
            logger.info(f"Размер файла: {os.path.getsize(document_path)} байт")

            # Проверяем расширение файла
            _, ext = os.path.splitext(document_path)
            ext = ext.lower()
            logger.info(f"Расширение файла: {ext}")

            # Если это PDF, сначала конвертируем его в Markdown
            processing_path = document_path
            if ext == '.pdf':
                logger.info(f"Обнаружен PDF файл, требуется конвертация")
                try:
                    processing_path = self._convert_pdf_to_markdown(document_path)
                    logger.info(f"PDF успешно конвертирован в Markdown: {processing_path}")
                except Exception as e:
                    logger.error(f"Ошибка при конвертации PDF: {str(e)}")
                    # В случае ошибки продолжаем с исходным файлом
                    processing_path = document_path

            # Если нужно, удаляем существующие данные заявки
            if delete_existing:
                deleted_count = self.qdrant_manager.delete_application(application_id)
                logger.info(f"Удалено {deleted_count} существующих документов для заявки {application_id}")

            # Разделяем документ на фрагменты
            logger.info(f"Разделение документа на фрагменты: {processing_path}")
            chunks = self.splitter.load_and_process_file(processing_path, application_id)
            logger.info(f"Документ разделен на {len(chunks)} фрагментов")

            # Собираем статистику по типам фрагментов
            content_types = {}
            for chunk in chunks:
                content_type = chunk.metadata["content_type"]
                content_types[content_type] = content_types.get(content_type, 0) + 1

            # Индексируем фрагменты
            logger.info(f"Индексация {len(chunks)} фрагментов")
            indexed_count = self.qdrant_manager.add_documents(chunks)
            logger.info(f"Проиндексировано {indexed_count} фрагментов")

            # Формируем результат
            result = {
                "application_id": application_id,
                "document_path": document_path,
                "processing_path": processing_path,
                "total_chunks": len(chunks),
                "indexed_count": indexed_count,
                "content_types": content_types,
                "status": "success"
            }

            return result

        except Exception as e:
            logger.exception(f"Ошибка при индексации документа: {str(e)}")
            return {
                "application_id": application_id,
                "document_path": document_path,
                "error": str(e),
                "status": "error"
            }

    def delete_application_data(self, application_id: str) -> bool:
        """
        Удаляет данные заявки из хранилища.

        Args:
            application_id: ID заявки

        Returns:
            bool: Успешность операции
        """
        try:
            deleted_count = self.qdrant_manager.delete_application(application_id)
            logger.info(f"Удалено {deleted_count} документов для заявки {application_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении данных заявки: {str(e)}")
            return False

    def get_application_stats(self, application_id: str) -> Dict[str, Any]:
        """
        Получает статистику по данным заявки.

        Args:
            application_id: ID заявки

        Returns:
            Dict[str, Any]: Статистика
        """
        try:
            stats = self.qdrant_manager.get_stats(application_id)
            return stats
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {str(e)}")
            return {"error": str(e)}

    def index_document_with_progress(self,
                                     application_id: str,
                                     document_path: str,
                                     delete_existing: bool = False,
                                     progress_callback=None) -> Dict[str, Any]:
        """
        Индексирует документ в Qdrant с отслеживанием прогресса.

        Args:
            application_id: ID заявки
            document_path: Путь к документу
            delete_existing: Удалить существующие данные заявки
            progress_callback: Функция обратного вызова для обновления прогресса

        Returns:
            Dict[str, Any]: Результаты индексации
        """
        try:
            # Проверяем, что файл существует
            if not os.path.exists(document_path):
                error_msg = f"Документ не найден по пути: {document_path}"
                logger.error(error_msg)
                return {
                    "application_id": application_id,
                    "document_path": document_path,
                    "error": error_msg,
                    "status": "error"
                }

            # Обновляем прогресс
            if progress_callback:
                progress_callback(20, 'convert', 'Начало конвертации документа...')

            # Проверяем расширение файла
            _, ext = os.path.splitext(document_path)
            ext = ext.lower()

            # Если это PDF, сначала конвертируем его в Markdown
            processing_path = document_path
            if ext == '.pdf':
                logger.info(f"Обнаружен PDF файл, требуется конвертация")
                try:
                    processing_path = self._convert_pdf_to_markdown(document_path)
                    logger.info(f"PDF успешно конвертирован в Markdown: {processing_path}")

                    # Обновляем прогресс
                    if progress_callback:
                        progress_callback(35, 'split', 'Документ успешно конвертирован, подготовка к разделению...')
                except Exception as e:
                    logger.error(f"Ошибка при конвертации PDF: {str(e)}")
                    processing_path = document_path

                    # Обновляем прогресс с информацией об ошибке конвертации
                    if progress_callback:
                        progress_callback(35, 'split', 'Ошибка конвертации, продолжаем с исходным файлом...')

            # Если нужно, удаляем существующие данные заявки
            if delete_existing:
                deleted_count = self.qdrant_manager.delete_application(application_id)
                logger.info(f"Удалено {deleted_count} существующих документов для заявки {application_id}")

            # Обновляем прогресс
            if progress_callback:
                progress_callback(40, 'split', 'Разделение документа на фрагменты...')

            # Разделяем документ на фрагменты
            logger.info(f"Разделение документа на фрагменты: {processing_path}")
            chunks = self.splitter.load_and_process_file(processing_path, application_id)
            logger.info(f"Документ разделен на {len(chunks)} фрагментов")

            # Собираем статистику по типам фрагментов
            content_types = {}
            for chunk in chunks:
                content_type = chunk.metadata["content_type"]
                content_types[content_type] = content_types.get(content_type, 0) + 1

            # Обновляем прогресс
            if progress_callback:
                progress_callback(50, 'index', f'Начало индексации {len(chunks)} фрагментов...')

            # Индексируем фрагменты с отслеживанием прогресса
            total_chunks = len(chunks)
            batch_size = 20

            # Индексируем фрагменты пакетами
            for i in range(0, total_chunks, batch_size):
                end_idx = min(i + batch_size, total_chunks)
                batch = chunks[i:end_idx]

                # Добавляем пакет в индекс
                self.qdrant_manager.add_documents(batch)

                # Рассчитываем и обновляем прогресс
                progress = 50 + int(45 * (end_idx / total_chunks))
                logger.info(f"Индексация партии {i + 1}-{end_idx} из {total_chunks}")

                if progress_callback:
                    progress_callback(
                        progress,
                        'index',
                        f'Индексация фрагментов: {end_idx}/{total_chunks}...'
                    )

            logger.info(f"Проиндексировано {total_chunks} фрагментов")

            # Финальное обновление прогресса
            if progress_callback:
                progress_callback(95, 'complete', 'Завершение индексации...')

            # Формируем результат
            result = {
                "application_id": application_id,
                "document_path": document_path,
                "processing_path": processing_path,
                "total_chunks": total_chunks,
                "indexed_count": total_chunks,
                "content_types": content_types,
                "status": "success"
            }

            return result

        except Exception as e:
            logger.exception(f"Ошибка при индексации документа: {str(e)}")

            # Обновляем прогресс с информацией об ошибке
            if progress_callback:
                progress_callback(0, 'error', f'Ошибка индексации: {str(e)}')

            return {
                "application_id": application_id,
                "document_path": document_path,
                "error": str(e),
                "status": "error"
            }

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
                # Очищаем ресурсы после использования ререйтинга
                self.cleanup()
                return reranked_results[:limit]
            else:
                return results[:limit]
        except Exception as e:
            logger.error(f"Ошибка при поиске: {str(e)}")
            # В случае ошибки тоже освобождаем ресурсы
            if self.use_reranker:
                self.cleanup()
            return []

    def cleanup(self):
        """
        Освобождает ресурсы после использования.
        Особенно важно для освобождения памяти GPU после поиска с ререйтингом.
        """
        if self.use_reranker and hasattr(self, 'reranker'):
            logger.info("Освобождение ресурсов ререйтера...")
            try:
                # Вызываем метод cleanup у ререйтера
                if hasattr(self.reranker, 'cleanup'):
                    self.reranker.cleanup()
            except Exception as e:
                logger.error(f"Ошибка при освобождении ресурсов ререйтера: {str(e)}")