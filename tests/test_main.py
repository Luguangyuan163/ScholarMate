"""应用工厂测试：健康检查与首页。"""

from __future__ import annotations


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "app": "ScholarMate"}


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ScholarMate" in resp.text


def test_agent_page(client):
    resp = client.get("/agent")
    assert resp.status_code == 200
    assert "Agent" in resp.text


def test_translate_page(client):
    resp = client.get("/translate")
    assert resp.status_code == 200
    assert "PDF 翻译" in resp.text


def test_papers_page(client):
    resp = client.get("/papers")
    assert resp.status_code == 200
    assert "论文库" in resp.text
