"""arXiv 服务测试：Atom 解析与查询参数构造（httpx 客户端使用替身）。"""

from __future__ import annotations

from app.services.arxiv_service import ArxivService, _build_params, _parse_feed

ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2106.09685v2</id>
    <published>2021-06-17T17:31:31Z</published>
    <title>LoRA: Low-Rank Adaptation of Large Language Models</title>
    <summary>We propose Low-Rank Adaptation.</summary>
    <author><name>Edward J. Hu</name></author>
  </entry>
</feed>
"""


class FakeResponse:
    status_code = 200
    text = ATOM_XML

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self) -> None:
        self.last_params = None

    async def get(self, url, params=None):
        self.last_params = params
        return FakeResponse()


def test_parse_feed():
    items = _parse_feed(ATOM_XML)
    assert len(items) == 1
    item = items[0]
    assert item.title == "LoRA: Low-Rank Adaptation of Large Language Models"
    assert item.authors == ["Edward J. Hu"]
    assert item.year == 2021
    assert item.external_id == "2106.09685v2"


async def test_search_calls_arxiv_with_query():
    client = FakeClient()
    service = ArxivService(client=client)
    items = await service.search("LoRA", max_results=5)
    assert items[0].source == "arxiv"
    assert "LoRA" in client.last_params["search_query"]
    assert client.last_params["max_results"] == 5


def test_build_params_year_filter():
    params = _build_params("LoRA", 10, 2024, 2024)
    assert "submittedDate:[202401010000 TO 202412312359]" in params["search_query"]
