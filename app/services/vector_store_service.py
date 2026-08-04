"""ChromaDB 封装（P2）：论文分块的写入、检索与删除。

chromadb 为同步库，调用方需经线程池执行。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

COLLECTION_NAME = "papers"


@dataclass
class VectorHit:
    document: str
    pdf_id: int
    name: str
    chunk_index: int
    distance: float


class VectorStoreService:
    def __init__(self, persist_dir: Path | str) -> None:
        self._persist_dir = str(persist_dir)
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            import chromadb

            client = chromadb.PersistentClient(path=self._persist_dir)
            self._collection = client.get_or_create_collection(
                name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
            )
        return self._collection

    def add_document(
        self,
        pdf_id: int,
        name: str,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> None:
        collection = self._get_collection()
        ids = [f"{pdf_id}-{index}" for index in range(len(chunks))]
        metadatas = [
            {"pdf_id": str(pdf_id), "name": name, "chunk_index": index}
            for index in range(len(chunks))
        ]
        collection.upsert(
            ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas
        )

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[VectorHit]:
        collection = self._get_collection()
        if collection.count() == 0:
            return []
        result = collection.query(query_embeddings=[query_embedding], n_results=top_k)
        return [
            VectorHit(
                document=document,
                pdf_id=int(metadata["pdf_id"]),
                name=metadata["name"],
                chunk_index=metadata["chunk_index"],
                distance=distance,
            )
            for document, metadata, distance in zip(
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
                strict=True,
            )
        ]

    def delete_document(self, pdf_id: int) -> None:
        self._get_collection().delete(where={"pdf_id": str(pdf_id)})
