"""
Модуль для конвертации PDF документов в формат Markdown
"""

from .docling_converter import DoclingPDFConverter
from .splitter import PPEEDocumentSplitter
from .pdf_converter import PDFToMarkdownConverter

# Импортируем семантический разделитель
try:
    from ..semantic_chunker import SemanticDocumentSplitter
    SEMANTIC_SPLITTER_AVAILABLE = True
except ImportError:
    SEMANTIC_SPLITTER_AVAILABLE = False

# Экспортируем все публичные классы
__all__ = [
    'PPEEDocumentSplitter',
    'PDFToMarkdownConverter',
    'DoclingPDFConverter'
]

# Добавляем семантический разделитель, если доступен
if SEMANTIC_SPLITTER_AVAILABLE:
    __all__.append('SemanticDocumentSplitter')