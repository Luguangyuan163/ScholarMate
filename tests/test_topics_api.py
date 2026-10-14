"""主题管理与论文实体接口测试。"""

from __future__ import annotations

from app.schemas.search import PaperItem
from app.services.paper_store import PaperStore


async def _seed_paper(client, title: str, doi: str, citation_count: int = 0) -> int:
    store = PaperStore(client.app.state.database)
    paper = await store.upsert(
        PaperItem(
            title=title,
            authors=["Author"],
            abstract=f"{title} abstract",
            source="crossref",
            external_id=doi,
            year=2025,
            citation_count=citation_count,
        )
    )
    return paper.id


def test_topic_crud(client):
    created = client.post(
        "/api/topics",
        json={"name": "大模型微调", "description": "参数高效微调", "keywords": ["LoRA"]},
    )
    assert created.status_code == 201
    topic_id = created.json()["id"]

    assert created.json()["keywords"] == ["LoRA"]
    assert client.post("/api/topics", json={"name": "大模型微调"}).status_code == 409

    listed = client.get("/api/topics").json()
    assert [topic["name"] for topic in listed] == ["大模型微调"]

    patched = client.patch(f"/api/topics/{topic_id}", json={"name": "参数高效微调"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "参数高效微调"
    assert client.patch("/api/topics/999", json={"name": "x"}).status_code == 404

    removed = client.delete(f"/api/topics/{topic_id}")
    assert removed.status_code == 200
    assert removed.json() == {"deleted": topic_id}
    assert client.delete(f"/api/topics/{topic_id}").status_code == 404


def test_assign_list_and_remove_topic_papers(client):
    topic_id = client.post("/api/topics", json={"name": "医学影像"}).json()["id"]
    first = client.portal.call(_seed_paper, client, "CT segmentation", "10.1000/ct", 5)
    second = client.portal.call(_seed_paper, client, "MRI denoising", "10.1000/mri", 9)

    assigned = client.post(
        f"/api/topics/{topic_id}/papers", json={"paper_ids": [first, second]}
    )
    assert assigned.json() == {"assigned": 2}
    assert client.get("/api/topics").json()[0]["paper_count"] == 2

    papers = client.get(f"/api/topics/{topic_id}/papers").json()
    assert papers["total"] == 2
    assert [item["citation_count"] for item in papers["items"]] == [9, 5]
    assert papers["items"][0]["topics"][0]["name"] == "医学影像"

    removed = client.request(
        "DELETE",
        f"/api/topics/{topic_id}/papers",
        json={"paper_ids": [first]},
    )
    assert removed.json() == {"removed": 1}
    assert client.get("/api/topics").json()[0]["paper_count"] == 1


def test_merge_topics_moves_papers(client):
    source = client.post("/api/topics", json={"name": "LoRA"}).json()["id"]
    target = client.post("/api/topics", json={"name": "参数高效微调"}).json()["id"]
    paper_id = client.portal.call(_seed_paper, client, "LoRA paper", "10.1000/lora")
    client.post(f"/api/topics/{source}/papers", json={"paper_ids": [paper_id]})

    merged = client.post(f"/api/topics/{source}/merge", json={"target_id": target})
    assert merged.status_code == 200
    assert merged.json()["moved"] == 1

    listed = {topic["name"]: topic for topic in client.get("/api/topics").json()}
    assert "LoRA" not in listed
    assert listed["参数高效微调"]["paper_count"] == 1


def test_knowledge_paper_list_filters_and_detail(client):
    topic_id = client.post("/api/topics", json={"name": "微调"}).json()["id"]
    first = client.portal.call(_seed_paper, client, "LoRA survey", "10.1000/lora", 100)
    client.portal.call(_seed_paper, client, "Veterinary CT", "10.1000/vet", 3)
    client.post(f"/api/topics/{topic_id}/papers", json={"paper_ids": [first]})

    all_papers = client.get("/api/knowledge/papers").json()
    assert all_papers["total"] == 2
    assert all_papers["items"][0]["title"] == "LoRA survey"  # 按引用量排序

    filtered = client.get("/api/knowledge/papers", params={"topic_id": topic_id}).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["id"] == first

    by_query = client.get("/api/knowledge/papers", params={"q": "Veterinary"}).json()
    assert by_query["total"] == 1

    detail = client.get(f"/api/knowledge/papers/{first}").json()
    assert detail["doi"] == "10.1000/lora"
    assert detail["topics"][0]["name"] == "微调"
    assert client.get("/api/knowledge/papers/999").status_code == 404


def test_classify_paper_by_topic_keywords(client):
    client.post("/api/topics", json={"name": "大模型微调", "keywords": ["LoRA"]})
    paper_id = client.portal.call(_seed_paper, client, "LoRA for vision", "10.1000/lora")
    other = client.portal.call(_seed_paper, client, "Veterinary CT", "10.1000/vet")

    suggestions = client.post(f"/api/knowledge/papers/{paper_id}/classify").json()
    assert [item["name"] for item in suggestions] == ["大模型微调"]

    assert client.post(f"/api/knowledge/papers/{other}/classify").json() == []
