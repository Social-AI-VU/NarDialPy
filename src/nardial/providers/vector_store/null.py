from nardial.providers.vector_store import VectorStoreProvider


class NullVectorStoreProvider(VectorStoreProvider):
    """No-op vector store — used in tests or when RAG is disabled."""

    def query(self, text: str, index_name: str | None = None, k: int = 5) -> list[str]:
        return []

    def ingest(self, index_name: str | None = None) -> None:
        pass

    def close(self) -> None:
        pass
