from typing import Any

from sic_framework.core.message_python2 import AudioMessage
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
    stop_grace_seconds : float, optional
        Seconds a pause or skip waits for the transcript after listening is stopped.
        Defaults to 30.0 because Whisper transcribes after recording stops (~10 s with
        large-v3-turbo on CPU); a smaller model can use less.
    """

    def __init__(self, conf: LocalWhisperConf = None, mic: Any = None,
                 stop_grace_seconds: float = 30.0):
        self._whisper = LocalWhisper(ip="localhost", conf=conf or LocalWhisperConf(), input_source=mic)
        self.stop_grace_seconds = stop_grace_seconds

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
        # The service has no stop message, but an empty audio chunk ends speech_recognition's
        # listen loop ("end of stream"), so what was heard so far is still transcribed. Sent twice:
        # once to end "waiting for speech", once to end the phrase. Leftovers are cleared by the
        # service at the start of the next listen.
        for _ in range(2):
            try:
                self._whisper.send_message(AudioMessage(b"", sample_rate=16000))
            except Exception as e:
                print("LocalWhisper stop listening failed:", e)
