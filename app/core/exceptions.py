"""业务异常基类与通用异常。"""

from __future__ import annotations


class ScholarMateError(Exception):
    """业务异常基类。"""


class ExternalAPIError(ScholarMateError):
    """外部 API（arXiv / S2 / LLM）调用失败。"""


class PDFProcessingError(ScholarMateError):
    """PDF 提取或分块失败。"""
