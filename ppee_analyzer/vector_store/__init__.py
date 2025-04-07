"""
Модуль для работы с векторной базой данных Qdrant
"""

from .qdrant_manager import QdrantManager
from .ollama_embeddings import OllamaEmbeddings

__all__ = ['QdrantManager', 'OllamaEmbeddings']