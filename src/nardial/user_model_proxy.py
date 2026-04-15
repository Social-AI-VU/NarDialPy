from typing import Any, Dict, Optional

# Attempt to import the SIC Redis datastore message classes and client used by the demo.
# The proxy will hide these details and gracefully fall back to in-memory behavior when unavailable.
try:
    from sic_framework.services.datastore.redis_datastore import (
        SetUsermodelValuesRequest,
        GetUsermodelRequest,
        DeleteUsermodelValuesRequest,
        DeleteUserRequest,
        UsermodelKeyValuesMessage,
        SICSuccessMessage,
        RedisDatastoreConf,
        RedisDatastore,
    )
    _HAS_REDIS_DS = True
except Exception:
    _HAS_REDIS_DS = False


class UserModelProxy:
    """
    Minimal dict-like proxy that routes CRUD operations to a Redis datastore.
    It keeps a small in-memory cache (snapshot) to retain compatibility with code expecting a mapping.

    Behavior:
    - If the SIC Redis client is available, connect to the default RedisDatastore.
    - If no datastore can be used, remain in pure in-memory mode.
    """

    def __init__(self, *, participant_id: Optional[str] = None):
        self._cache: Dict[str, Any] = {}
        self._pid = participant_id
        self._datastore = None

        # Attempt to create a default RedisDatastore.
        if _HAS_REDIS_DS:
            try:
                conf = RedisDatastoreConf(
                    host="127.0.0.1",
                    port=6379,
                    password="changemeplease",
                    namespace="usermodel",
                    version="v1",
                    developer_id=0,
                )
                self._datastore = RedisDatastore(conf=conf)
            except Exception:
                # If any error occurs, fall back to in-memory only.
                self._datastore = None

    def set_participant(self, participant_id: Optional[str]):
        self._pid = participant_id
        if self._datastore and self._pid:
            try:
                self._ensure_loaded()
            except Exception:
                pass

    def _ensure_loaded(self) -> None:
        # If we have a datastore and a participant id, try to load the full user model from Redis.
        if not self._datastore or not self._pid:
            return
        try:
            resp = self._datastore.request(GetUsermodelRequest(user_id=self._pid))
            if isinstance(resp, UsermodelKeyValuesMessage):
                # overwrite local cache with canonical values
                self._cache = dict(resp.keyvalues or {})
        except Exception:
            # On any failure, silently keep the current cache (fallback behavior)
            return

    # Mapping protocol
    def __getitem__(self, key: str) -> Any:
        if key in self._cache:
            return self._cache[key]
        # try to refresh from datastore once
        self._ensure_loaded()
        return self._cache[key]

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self.__getitem__(key)
        except Exception:
            return default

    def __setitem__(self, key: str, value: Any) -> None:
        # write-through to datastore when available, otherwise update local cache
        if self._datastore and self._pid:
            try:
                kv = {key: value}
                resp = self._datastore.request(SetUsermodelValuesRequest(user_id=self._pid, keyvalues=kv))
                # On success or failure, update cache as best-effort
                self._cache[key] = value
            except Exception:
                self._cache[key] = value
        else:
            self._cache[key] = value

    def update(self, mapping: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        items = dict(mapping or {})
        items.update(kwargs)
        if not items:
            return
        if self._datastore and self._pid:
            try:
                resp = self._datastore.request(SetUsermodelValuesRequest(user_id=self._pid, keyvalues=items))
                self._cache.update(items)
            except Exception:
                self._cache.update(items)
        else:
            self._cache.update(items)

    def keys(self):
        self._ensure_loaded()
        return self._cache.keys()

    def items(self):
        self._ensure_loaded()
        return self._cache.items()

    def as_dict(self) -> Dict[str, Any]:
        self._ensure_loaded()
        return dict(self._cache)

    def __delitem__(self, key: str) -> None:
        if self._datastore and self._pid:
            try:
                resp = self._datastore.request(DeleteUsermodelValuesRequest(user_id=self._pid, keys=[key]))
                self._cache.pop(key, None)
            except Exception:
                self._cache.pop(key, None)
        else:
            self._cache.pop(key, None)

    def clear_remote(self) -> None:
        # Delete the entire user from datastore if available
        if self._datastore and self._pid:
            try:
                resp = self._datastore.request(DeleteUserRequest(user_id=self._pid))
                if isinstance(resp, SICSuccessMessage):
                    self._cache.clear()
            except Exception:
                pass
        else:
            self._cache.clear()

    def __iter__(self):
        self._ensure_loaded()
        return iter(self._cache)

    def __len__(self):
        self._ensure_loaded()
        return len(self._cache)

    def __repr__(self):
        return f"UserModelProxy(pid={self._pid}, cache={self._cache})"
