"""论文库管理接口（P2 接入）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/papers", tags=["papers"])


@router.get("")
async def list_papers() -> JSONResponse:
    return JSONResponse(status_code=501, content={"detail": "论文库管理将在 P2 实现"})
