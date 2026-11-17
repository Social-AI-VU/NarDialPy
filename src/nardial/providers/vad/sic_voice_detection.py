from typing import Any, Callable

from sic_framework.services.voice_detection.voice_detection import VoiceDetection, VoiceDetectionConf


class SICVoiceDetectionProvider:
    """VAD provider backed by the SIC Voice Detection service (Silero VAD).

    Requires ``pip install "nardial[vad]"`` and the service running (``run-voice-detection``).
    The service judges speech over a rolling one-second window, so it reports the end of
    speech somewhat later than it happens; ``vad_silence_delay`` comes on top of that.
    """

    def __init__(self, mic: Any, conf: VoiceDetectionConf | None = None, ip: str = "localhost"):
        self._vad = VoiceDetection(ip=ip, conf=conf or VoiceDetectionConf(), input_source=mic)
        self._on_change: Callable[[bool], None] | None = None
        self._vad.register_callback(self._on_message)

    def start(self, on_change: Callable[[bool], None]) -> None:
        self._on_change = on_change

    def stop(self) -> None:
        self._on_change = None

    def close(self) -> None:
        # The SIC application stops the service component when it exits.
        self._on_change = None

    def _on_message(self, message) -> None:
        on_change = self._on_change
        if on_change is not None and hasattr(message, "is_speaking"):
            on_change(bool(message.is_speaking))
