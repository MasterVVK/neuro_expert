import os
import logging
from typing import List, Dict, Any, Optional

from ppee_analyzer.vector_store import QdrantManager
from ppee_analyzer.document_processor import PPEEDocumentSplitter

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
                 ollama_url: str = "http://localhost:11434"):
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
        
        logger.info(f"QdrantAdapter инициализирован для коллекции {collection_name} на {host}:{port}")
    
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
            logger.info(f"Начало индексации документа {document_path} для заявки {application_id}")
            
            # Если нужно, удаляем существующие данные заявки
            if delete_existing:
                deleted_count = self.qdrant_manager.delete_application(application_id)
                logger.info(f"Удалено {deleted_count} существующих документов для заявки {application_id}")
            
            # Разделяем документ на фрагменты
            chunks = self.splitter.load_and_process_file(document_path, application_id)
            logger.info(f"Документ разделен на {len(chunks)} фрагментов")
            
            # Собираем статистику по типам фрагментов
            content_types = {}
            for chunk in chunks:
                content_type = chunk.metadata["content_type"]
                content_types[content_type] = content_types.get(content_type, 0) + 1
            
            # Индексируем фрагменты
            indexed_count = self.qdrant_manager.add_documents(chunks)
            logger.info(f"Проиндексировано {indexed_count} фрагментов")
            
            # Формируем результат
            result = {
                "application_id": application_id,
                "document_path": document_path,
                "total_chunks": len(chunks),
                "indexed_count": indexed_count,
                "content_types": content_types,
                "status": "success"
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при индексации документа: {str(e)}")
            return {
                "application_id": application_id,
                "document_path": document_path,
                "error": str(e),
                "status": "error"
            }
    
    def search(self, 
               application_id: str, 
               query: str, 
               limit: int = 5) -> List[Dict[str, Any]]:
        """
        Выполняет семантический поиск.
        
        Args:
            application_id: ID заявки
            query: Поисковый запрос
            limit: Количество результатов
            
        Returns:
            List[Dict[str, Any]]: Результаты поиска
        """
        try:
            logger.info(f"Выполнение поиска '{query}' для заявки {application_id}")
            
            # Выполняем поиск
            docs = self.qdrant_manager.search(
                query=query,
                filter_dict={"application_id": application_id},
                k=limit
            )
            
            # Преобразуем результаты
            results = []
            for doc in docs:
                results.append({
                    "text": doc.page_content,
                    "metadata": doc.metadata
                })
            
            logger.info(f"Найдено {len(results)} результатов")
            return results
            
        except Exception as e:
            logger.error(f"Ошибка при поиске: {str(e)}")
            return []
    
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
