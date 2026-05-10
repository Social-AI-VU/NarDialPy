from __future__ import annotations

import json
import os
from collections.abc import MutableMapping
from datetime import datetime, timezone
from typing import Any

# Attempt to import the SIC Redis datastore message classes and client used by the demo.
# The proxy will hide these details and gracefully fall back to in-memory behavior when unavailable.
try:
    from sic_framework.services.datastore.redis_datastore import (
        SetUsermodelValuesRequest,
        GetUsermodelRequest,
        DeleteUsermodelValuesRequest,
        DeleteUserRequest,
        UsermodelKeyValuesMessage,
        RedisDatastoreConf,
        RedisDatastore,
    )
    from sic_framework import SICSuccessMessage
    _HAS_REDIS_DS = True
except Exception:
    SetUsermodelValuesRequest = None
    GetUsermodelRequest = None
    DeleteUsermodelValuesRequest = None
    DeleteUserRequest = None
    UsermodelKeyValuesMessage = None
    SICSuccessMessage = None
    RedisDatastoreConf = None
    RedisDatastore = None
    _HAS_REDIS_DS = False

# Reserved keys used internally to persist continuity data alongside regular user-model values.
_KEY_COMPLETED_DIALOGS = "_completed_dialogs"
_KEY_TOPICS_OF_INTEREST = "_topics_of_interest"
_KEY_LAST_UPDATED = "_last_updated"


class UserModel(MutableMapping):
    """
    Mapping proxy that routes CRUD operations to a Redis datastore with an in-memory cache.

    Inheriting from ``MutableMapping`` provides ``__contains__``, ``keys``, ``items``,
    ``values``, ``get``, ``pop``, ``popitem``, ``clear``, and ``setdefault`` for free.
    The abstract methods (``__getitem__``, ``__setitem__``, ``__delitem__``, ``__iter__``,
    ``__len__``) are implemented here and delegate to the Redis datastore when available,
    falling back to the in-memory cache otherwise.

    The ``update`` method is overridden to batch-write to Redis in a single request
    rather than using individual ``__setitem__`` calls.

    Behavior:
    - If the SIC Redis client is available, connect to the default RedisDatastore.
    - If no datastore can be used, remain in pure in-memory mode.
    """

    def __init__(self, *, participant_id: str | None = None):
        self._cache: dict[str, Any] = {}
        self._pid = participant_id
        self._datastore = None

        # Attempt to create a default RedisDatastore.
        # Connection parameters are read from environment variables so that
        # deployments can override them without touching source code.
        # Matching the variable names already documented in the project .env file.
        if _HAS_REDIS_DS and RedisDatastoreConf and RedisDatastore:
            try:
                conf = RedisDatastoreConf(
                    host=os.environ.get("DB_IP", "127.0.0.1"),
                    port=int(os.environ.get("DB_PORT", "6379")),
                    password=os.environ.get("DB_PASS", "changemeplease"),
                    namespace="usermodel",
                    version="v1",
                    developer_id=0,
                )
                self._datastore = RedisDatastore(conf=conf)
            except Exception:
                # If any error occurs, fall back to in-memory only.
                self._datastore = None

    def set_participant(self, participant_id: str | None):
        self._pid = participant_id
        if self._datastore and self._pid:
            try:
                self._ensure_loaded()
            except Exception:
                pass

    def _ensure_loaded(self) -> None:
        # If we have a datastore and a participant id, try to load the full user model from Redis.
        if not self._datastore or not self._pid or not GetUsermodelRequest:
            return
        try:
            resp = self._datastore.request(GetUsermodelRequest(user_id=self._pid))
            keyvalues = getattr(resp, "keyvalues", None)
            if isinstance(keyvalues, dict):
                self._cache = {
                    k: self._decode_value(v)
                    for k, v in keyvalues.items()
                }
        except Exception:
            # On any failure, silently keep the current cache (fallback behavior)
            return

    @staticmethod
    def _encode_value(value: Any) -> Any:
        """
        Redis hash fields accept scalar values.
        Encode complex Python values as tagged JSON strings.
        """
        if isinstance(value, bool):
            # Must precede the int check: bool is a subclass of int.
            return "true" if value else "false"
        if isinstance(value, (str, int, float)) or value is None:
            return value
        try:
            return "__json__:" + json.dumps(value, ensure_ascii=False)
        except Exception:
            # Last-resort fallback keeps write path robust.
            return str(value)

    @staticmethod
    def _decode_value(value: Any) -> Any:
        """
        Decode values previously encoded by _encode_value.
        """
        if isinstance(value, str) and value.startswith("__json__:"):
            raw = value[len("__json__:"):]
            try:
                return json.loads(raw)
            except Exception:
                return value
        return value

    # ---- continuity helpers (completed_dialogs, topics_of_interest, metadata) ----

    def get_completed_dialogs(self) -> list[str]:
        """Return the list of completed dialog IDs stored for this participant."""
        self._ensure_loaded()
        return list(self._cache.get(_KEY_COMPLETED_DIALOGS) or [])

    def set_completed_dialogs(self, dialog_ids: list[str]) -> None:
        """Persist the completed dialog IDs for this participant."""
        self[_KEY_COMPLETED_DIALOGS] = list(dialog_ids)

    def get_topics_of_interest(self) -> list[str]:
        """Return the list of topics of interest stored for this participant."""
        self._ensure_loaded()
        return list(self._cache.get(_KEY_TOPICS_OF_INTEREST) or [])

    def set_topics_of_interest(self, topics: list[str]) -> None:
        """Persist the topics of interest for this participant."""
        self[_KEY_TOPICS_OF_INTEREST] = list(topics)

    def save_continuity(self, completed_dialogs: list[str], topics_of_interest: list[str]) -> None:
        """Persist all continuity fields (completed_dialogs, topics, metadata) in one write."""
        self.update({
            _KEY_COMPLETED_DIALOGS: list(completed_dialogs),
            _KEY_TOPICS_OF_INTEREST: list(topics_of_interest),
            _KEY_LAST_UPDATED: datetime.now(timezone.utc).isoformat(),
        })

    # Mapping protocol
    def __getitem__(self, key: str) -> Any:
        if key in self._cache:
            return self._cache[key]
        # try to refresh from datastore once
        self._ensure_loaded()
        return self._cache[key]

    def __setitem__(self, key: str, value: Any) -> None:
        # write-through to datastore when available, otherwise update local cache
        if self._datastore and self._pid and SetUsermodelValuesRequest:
            try:
                kv = {key: self._encode_value(value)}
                self._datastore.request(SetUsermodelValuesRequest(user_id=self._pid, keyvalues=kv))
                # On success or failure, update cache as best-effort
                self._cache[key] = value
            except Exception:
                self._cache[key] = value
        else:
            self._cache[key] = value

    def update(self, mapping: dict[str, Any] | None = None, **kwargs) -> None:
        items = dict(mapping or {})
        items.update(kwargs)
        if not items:
            return
        if self._datastore and self._pid and SetUsermodelValuesRequest:
            try:
                encoded_items = {
                    k: self._encode_value(v)
                    for k, v in items.items()
                }
                self._datastore.request(SetUsermodelValuesRequest(user_id=self._pid, keyvalues=encoded_items))
                self._cache.update(items)
            except Exception:
                self._cache.update(items)
        else:
            self._cache.update(items)

    def as_dict(self) -> dict[str, Any]:
        self._ensure_loaded()
        return dict(self._cache)

    def __delitem__(self, key: str) -> None:
        if self._datastore and self._pid and DeleteUsermodelValuesRequest:
            try:
                self._datastore.request(DeleteUsermodelValuesRequest(user_id=self._pid, keys=[key]))
                self._cache.pop(key, None)
            except Exception:
                self._cache.pop(key, None)
        else:
            self._cache.pop(key, None)

    def clear_remote(self) -> None:
        # Delete the entire user from datastore if available
        if self._datastore and self._pid and DeleteUserRequest:
            try:
                self._datastore.request(DeleteUserRequest(user_id=self._pid))
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
        return f"UserModel(pid={self._pid}, cache={self._cache})"
