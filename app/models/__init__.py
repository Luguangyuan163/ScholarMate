"""ORM 模型包：导入即注册到 Base.metadata。"""

from app.models.paper import Paper
from app.models.search_cache import SearchCache
from app.models.search_history import SearchHistory
from app.models.uploaded_pdf import UploadedPDF

__all__ = ["Paper", "SearchCache", "SearchHistory", "UploadedPDF"]
