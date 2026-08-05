"""ORM 模型包：导入即注册到 Base.metadata。"""

from app.models.conversation import Conversation, Message
from app.models.search_cache import SearchCache
from app.models.search_history import SearchHistory
from app.models.translation_record import TranslationRecord
from app.models.uploaded_pdf import UploadedPDF

__all__ = [
    "Conversation",
    "Message",
    "SearchCache",
    "SearchHistory",
    "TranslationRecord",
    "UploadedPDF",
]
