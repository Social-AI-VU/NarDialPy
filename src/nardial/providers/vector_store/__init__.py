from typing import Protocol, runtime_checkable


@runtime_checkable
class VectorStoreProvider(Protocol):
    def query(self, text: str, index_name: str | None = None, k: int = 5) -> list[str]: ...
    def ingest(self, index_name: str | None = None) -> None: ...
    def close(self) -> None: ...


__all__ = ["VectorStoreProvider"]
