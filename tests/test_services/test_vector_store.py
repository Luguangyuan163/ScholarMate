"""向量库测试：写入、检索、删除（真实 ChromaDB，临时目录）。"""

from __future__ import annotations

from app.services.vector_store_service import VectorStoreService


def test_add_and_search(tmp_path):
    store = VectorStoreService(persist_dir=tmp_path / "chroma")
    store.add_document(
        pdf_id=1,
        name="Paper A",
        chunks=["LoRA fine-tuning is efficient.", "Second chunk."],
        embeddings=[[0.1] * 8, [0.2] * 8],
    )
    hits = store.search([0.1] * 8, top_k=5)
    assert len(hits) >= 1
    assert hits[0].pdf_id == 1
    assert hits[0].name == "Paper A"
    assert hits[0].document


def test_search_empty(tmp_path):
    store = VectorStoreService(persist_dir=tmp_path / "chroma2")
    assert store.search([0.1] * 8) == []


def test_delete_document(tmp_path):
    store = VectorStoreService(persist_dir=tmp_path / "chroma3")
    store.add_document(pdf_id=7, name="B", chunks=["text"], embeddings=[[0.1] * 8])
    store.delete_document(7)
    assert store.search([0.1] * 8) == []
