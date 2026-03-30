"""ElevenLabs TTS backend for NarDialPy.

Usage example::

    from os import environ
    from src.tts import ElevenLabsTTS, TTSConf

    tts_conf = TTSConf(
        voice_id="your-voice-id",
        model_id="eleven_multilingual_v2",
        speaking_rate=1.0,
    )

    tts = ElevenLabsTTS(
        elevenlabs_key=environ["ELEVENLABS_API_KEY"],
        voice_id=tts_conf.voice_id,
        model_id=tts_conf.model_id,
        sample_rate=22050,
        speaking_rate=tts_conf.speaking_rate,
    )

    result = tts.request(ElevenLabsTTSRequest(text="Hello, world!"))
    # result.waveform  -> raw PCM bytes
    # result.sample_rate -> int
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SpeechResult:
    """Audio result returned by :class:`ElevenLabsTTS`.

    The interface is intentionally duck-type compatible with the
    ``SpeechResult`` returned by the ``sic_framework`` Google TTS service so
    that either backend can be used interchangeably inside
    :class:`~src.conversation_agent.ConversationAgent`.

    Attributes:
        waveform: Raw PCM audio bytes.
        sample_rate: Sample rate of the audio in Hz.
    """

    waveform: bytes
    sample_rate: int


class ElevenLabsTTSRequest:
    """Request object for :class:`ElevenLabsTTS`.

    All voice-customization fields are optional and default to ``None``,
    meaning the :class:`ElevenLabsTTS` instance defaults take precedence.

    Attributes:
        text: Text to synthesise.
        speaking_rate: Per-request speaking-rate override (1.0 = normal).
        pitch: Per-request pitch override (ignored by ElevenLabs; kept for
            interface parity with other backends).
        voice_id: Per-request voice-ID override.
        style: Per-request style-exaggeration override [0, 1].
    """

    def __init__(
        self,
        text: str,
        speaking_rate: Optional[float] = None,
        pitch: Optional[float] = None,
        voice_id: Optional[str] = None,
        style: Optional[float] = None,
    ):
        self.text = text
        self.speaking_rate = speaking_rate
        self.pitch = pitch
        self.voice_id = voice_id
        self.style = style


class ElevenLabsTTS:
    """Text-to-speech client that wraps the ElevenLabs API.

    The class takes the same configuration parameters that are shown in the
    issue example and exposes a ``request()`` method whose return type is
    compatible with the Google TTS ``SpeechResult`` used elsewhere in the
    project.

    Args:
        elevenlabs_key: ElevenLabs API key.
        voice_id: Default ElevenLabs voice ID.  Can be overridden per request.
        model_id: ElevenLabs model ID.  Defaults to
            ``"eleven_multilingual_v2"``.
        sample_rate: Output PCM sample rate in Hz.  Must be one of
            ``{8000, 16000, 22050, 24000, 32000, 44100, 48000}``.
        speaking_rate: Default speaking rate (1.0 = normal).  Can be
            overridden per request via :class:`ElevenLabsTTSRequest`.

    Raises:
        ImportError: If the ``elevenlabs`` package is not installed.
        ValueError: If *sample_rate* is not supported.
    """

    DEFAULT_MODEL_ID = "eleven_multilingual_v2"
    DEFAULT_SAMPLE_RATE = 22050
    SUPPORTED_SAMPLE_RATES = frozenset({8000, 16000, 22050, 24000, 32000, 44100, 48000})

    def __init__(
        self,
        elevenlabs_key: str,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        speaking_rate: float = 1.0,
    ):
        try:
            from elevenlabs.client import ElevenLabs as _ElevenLabsClient
        except ImportError as exc:
            raise ImportError(
                "The 'elevenlabs' package is required to use ElevenLabsTTS. "
                "Install it with:  pip install elevenlabs"
            ) from exc

        if sample_rate not in self.SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f"sample_rate {sample_rate} is not supported by the ElevenLabs PCM output format. "
                f"Choose one of: {sorted(self.SUPPORTED_SAMPLE_RATES)}"
            )

        self._client = _ElevenLabsClient(api_key=elevenlabs_key)
        self._voice_id = voice_id
        self._model_id = model_id or self.DEFAULT_MODEL_ID
        self._sample_rate = sample_rate
        self._speaking_rate = speaking_rate

    def request(self, request: ElevenLabsTTSRequest) -> SpeechResult:
        """Synthesise speech and return a :class:`SpeechResult`.

        Voice-customization values present on *request* take precedence over
        the instance defaults set at construction time.

        Args:
            request: A :class:`ElevenLabsTTSRequest` describing the text to
                synthesise and optional per-request voice overrides.

        Returns:
            A :class:`SpeechResult` containing raw PCM *waveform* bytes and
            the *sample_rate*.

        Raises:
            ValueError: If no voice ID is available (neither set at
                construction time nor provided on the request).
        """
        from elevenlabs import VoiceSettings

        voice_id = request.voice_id or self._voice_id
        if not voice_id:
            raise ValueError(
                "A voice_id must be provided either when constructing "
                "ElevenLabsTTS or on the individual ElevenLabsTTSRequest."
            )

        speaking_rate = (
            request.speaking_rate
            if request.speaking_rate is not None
            else self._speaking_rate
        )
        style = request.style

        voice_settings = VoiceSettings(
            stability=0.5,
            similarity_boost=0.75,
            speed=speaking_rate,
            style=style,
        )

        output_format = f"pcm_{self._sample_rate}"
        audio_bytes = b"".join(
            self._client.text_to_speech.convert(
                voice_id=voice_id,
                text=request.text,
                model_id=self._model_id,
                voice_settings=voice_settings,
                output_format=output_format,
            )
        )

        return SpeechResult(waveform=audio_bytes, sample_rate=self._sample_rate)
