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
