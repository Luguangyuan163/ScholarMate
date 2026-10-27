"""知识图谱接口的响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """图节点：论文 / 主题 / 关键词 / 检索会话。"""

    id: str
    type: str
    label: str
    size: float = 12.0
    group: str = ""
    meta: dict = {}


class GraphEdge(BaseModel):
    """图边：归属、关键词命中、会话包含、引用。"""

    source: str
    target: str
    type: str
    weight: float = 1.0


class GraphStats(BaseModel):
    total: int = 0
    shown: int = 0
    truncated: bool = False


class GraphOut(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    stats: GraphStats = GraphStats()


class GraphExpandRequest(BaseModel):
    """按需扩展某篇论文的引用关系。"""

    paper_id: int
    kinds: list[str] = Field(default_factory=lambda: ["references"])
