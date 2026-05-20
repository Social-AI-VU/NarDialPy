from dataclasses import dataclass


@dataclass
class RagConfig:
    """Retrieval-augmented generation settings for ``InteractionConfig``."""

    enabled: bool = False
    ingest_docs: bool = False
    input_path: str = ""
    index_name: str = ""
    embedding_model: str = ""
    chunk_chars: int = 1200
    chunk_overlap: int = 150
    override_existing: bool = False
    force_recreate_index: bool = False

    def validate(self) -> None:
        if not self.enabled:
            return
        if not isinstance(self.ingest_docs, bool):
            raise ValueError("RagConfig.ingest_docs must be a bool when enabled=True")
        if not self.embedding_model:
            raise ValueError("RagConfig.embedding_model is required when enabled=True")
        if not self.ingest_docs:
            return
        required_fields = {
            "input_path": self.input_path,
            "index_name": self.index_name,
            "embedding_model": self.embedding_model,
        }
        missing = [k for k, v in required_fields.items() if not v]
        if missing:
            raise ValueError(
                "Missing required RagConfig fields when enabled=True and ingest_docs=True: "
                + ", ".join(missing)
            )
        if not isinstance(self.chunk_chars, int) or self.chunk_chars <= 0:
            raise ValueError("RagConfig.chunk_chars must be a positive int when ingest_docs=True")
        if not isinstance(self.chunk_overlap, int) or self.chunk_overlap < 0:
            raise ValueError("RagConfig.chunk_overlap must be a non-negative int when ingest_docs=True")
        if not isinstance(self.override_existing, bool):
            raise ValueError("RagConfig.override_existing must be bool when ingest_docs=True")
        if not isinstance(self.force_recreate_index, bool):
            raise ValueError("RagConfig.force_recreate_index must be bool when ingest_docs=True")
