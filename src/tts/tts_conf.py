from dataclasses import dataclass
from typing import Optional


@dataclass
class TTSConf:
    """Default voice configuration for a TTS backend.

    These values serve as agent-level defaults and can be overridden per
    individual speech move via the move's own voice parameters.

    Attributes:
        voice_id: Voice identifier used by the TTS provider (e.g. an
            ElevenLabs voice ID or a Google TTS voice name).
        model_id: Model identifier used by the TTS provider (e.g. an
            ElevenLabs model ID).  ``None`` means use the provider default.
        speaking_rate: Playback speed relative to normal (1.0).  Values below
            1.0 slow the speech down; values above 1.0 speed it up.
        pitch: Pitch adjustment in semitones (where supported by the
            provider).  0.0 means no change.
        style: Style-exaggeration level in the range [0, 1] (where supported
            by the provider).  0.0 means no style exaggeration.
    """

    voice_id: Optional[str] = None
    model_id: Optional[str] = None
    speaking_rate: float = 1.0
    pitch: float = 0.0
    style: float = 0.0
