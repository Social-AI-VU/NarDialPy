from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class VADProvider(Protocol):
    """Voice activity detection, used to stop listening shortly after the user stops speaking.

    The orchestrator calls :meth:`start` when a listen with ``vad_endpointing`` begins and
    :meth:`stop` when it ends. In between, the provider calls ``on_change(is_speaking)``
    (from any thread) whenever speech starts or stops.
    """

    def start(self, on_change: Callable[[bool], None]) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


__all__ = ["VADProvider"]
