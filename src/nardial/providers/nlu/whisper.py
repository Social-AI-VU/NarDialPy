from typing import Any

from sic_framework.services.local_whisper_stt.local_whisper import (
    LocalWhisper,
    LocalWhisperConf,
    GetTranscript,
)

from nardial.providers.nlu import NLUResult


class LocalWhisperNLUProvider:
    """NLU provider backed by the SIC LocalWhisper STT service.

    Runs Whisper large-v3-turbo locally — no internet or API key required.
    Uses mlx-whisper on Mac and faster-whisper on Windows/Linux.

    Usage::

        whisper = LocalWhisperNLUProvider(
            conf=LocalWhisperConf(language="en"),
            mic=device.get_mic(),
        )
        agent = ConversationAgent(..., nlu_provider=whisper)

    Parameters
    ----------
    conf : LocalWhisperConf, optional
        Service configuration (model size, language, task, etc.).
        Defaults to ``LocalWhisperConf()`` (large-v3-turbo, auto-detect language).
    mic : SIC microphone component, optional
        The robot/desktop microphone to stream audio from.
        Obtain via ``device.get_mic()``.
    """

    def __init__(self, conf: LocalWhisperConf = None, mic: Any = None):
        self._whisper = LocalWhisper(ip="localhost", conf=conf or LocalWhisperConf())
        if mic is not None:
            self._whisper.connect(mic)

    def listen(self, context: str | None = None, timeout: float = 10.0) -> NLUResult:
        try:
            # timeout: seconds to wait for speech to start (passed to VAD)
            # The outer SIC network timeout is timeout + 60 to cover transcription time.
            reply = self._whisper.request(
                GetTranscript(timeout=timeout),
                timeout=timeout + 60,
            )
            transcript = reply.transcript.strip() if reply and reply.transcript else ""
            return NLUResult(transcript=transcript, intent=None)
        except Exception as e:
            print("LocalWhisper error:", e)
            return NLUResult(transcript="", intent=None)

    def cancel(self) -> None:
        pass
