"""会话管理接口测试：创建/列表/消息/删除。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_create_and_list_conversations(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        created = client.post("/api/conversations", json={"title": "LoRA 调研"})
        assert created.status_code == 200
        conv_id = created.json()["id"]
        assert created.json()["title"] == "LoRA 调研"

        listed = client.get("/api/conversations")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == conv_id
        assert listed.json()[0]["message_count"] == 0


def test_append_and_read_messages(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        conv_id = client.post("/api/conversations", json={"title": "测试"}).json()["id"]
        first = client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"role": "user", "content": "帮我找 LoRA 论文"},
        )
        second = client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"role": "assistant", "content": "找到 3 篇"},
        )
        assert first.status_code == 200
        assert second.status_code == 200

        detail = client.get(f"/api/conversations/{conv_id}")
        assert detail.status_code == 200
        messages = detail.json()["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "帮我找 LoRA 论文"


def test_delete_conversation(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        conv_id = client.post("/api/conversations", json={"title": "待删"}).json()["id"]
        deleted = client.delete(f"/api/conversations/{conv_id}")
        assert deleted.status_code == 200
        assert client.get("/api/conversations").json() == []
        assert client.get(f"/api/conversations/{conv_id}").status_code == 404


def test_conversation_not_found_returns_404(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as client:
        assert client.get("/api/conversations/999").status_code == 404
        resp = client.post(
            "/api/conversations/999/messages",
            json={"role": "user", "content": "x"},
        )
        assert resp.status_code == 404
