from os import environ
from pathlib import Path

from sic_framework.services.datastore.redis_datastore import (
    RedisDatastoreConf,
    RedisDatastore,
    IngestVectorDocsRequest,
    QueryVectorDBRequest,
    VectorDBResultsMessage,
)


class RedisVectorStoreProvider:
    def __init__(
        self,
        embedding_model: str,
        openai_api_key: str | None = None,
        host: str = "127.0.0.1",
        port: int = 6379,
        password: str = "changemeplease",
        namespace: str = "nardial_rag",
        version: str = "v1",
        developer_id: int = 0,
        index_name: str = "",
        ingest_docs: bool = False,
        input_path: str = "",
        chunk_chars: int = 1200,
        chunk_overlap: int = 150,
        override_existing: bool = False,
        force_recreate_index: bool = False,
    ):
        self._openai_api_key = openai_api_key or environ.get("OPENAI_API_KEY", "")
        self._embedding_model = embedding_model
        self._index_name = index_name
        self._input_path = input_path
        self._chunk_chars = chunk_chars
        self._chunk_overlap = chunk_overlap
        self._override_existing = override_existing
        self._force_recreate_index = force_recreate_index

        redis_conf = RedisDatastoreConf(
            host=host,
            port=port,
            password=password,
            namespace=namespace,
            version=version,
            developer_id=developer_id,
        )
        self._datastore = RedisDatastore(conf=redis_conf)

        if ingest_docs:
            self.ingest()

    def query(self, text: str, index_name: str | None = None, k: int = 5) -> list[str]:
        query_index = index_name or self._index_name
        if not query_index:
            raise ValueError("RedisVectorStoreProvider.query requires an index name")

        result = self._datastore.request(
            QueryVectorDBRequest(
                index_name=query_index,
                query_text=text,
                openai_api_key=self._openai_api_key,
                k=k,
                partition="default",
                embedding_model=self._embedding_model,
            )
        )

        if not isinstance(result, VectorDBResultsMessage):
            return []

        snippets = []
        for idx, item in enumerate(result.payload.get("results", []), start=1):
            content = (item.get("content") or "").strip()
            if not content:
                continue
            source = Path(item.get("doc_path") or "unknown").name
            snippets.append(f"[{idx}] {source}\n{content}")
        return snippets

    def ingest(self, index_name: str | None = None) -> None:
        ingest_index = index_name or self._index_name
        if not ingest_index:
            raise ValueError("RedisVectorStoreProvider.ingest requires an index name")

        result = self._datastore.request(
            IngestVectorDocsRequest(
                input_path=self._input_path,
                openai_api_key=self._openai_api_key,
                index_name=ingest_index,
                partition="default",
                chunk_chars=self._chunk_chars,
                chunk_overlap=self._chunk_overlap,
                embedding_model=self._embedding_model,
                override_existing=self._override_existing,
                force_recreate_index=self._force_recreate_index,
            )
        )
        if not (isinstance(result, VectorDBResultsMessage) and result.payload.get("ok")):
            raise RuntimeError(f"RAG ingestion returned an unexpected response: {result}")

    def close(self) -> None:
        pass
