"""业务异常基类测试。"""

from __future__ import annotations

from app.core.exceptions import ExternalAPIError, PDFProcessingError, ScholarMateError


def test_exception_hierarchy():
    assert issubclass(ExternalAPIError, ScholarMateError)
    assert issubclass(PDFProcessingError, ScholarMateError)
    assert issubclass(ScholarMateError, Exception)


def test_exceptions_carry_message():
    error = ExternalAPIError("api down")
    assert str(error) == "api down"
