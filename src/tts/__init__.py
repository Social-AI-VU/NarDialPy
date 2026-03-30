"""TTS backends and configuration for NarDialPy."""

from src.tts.tts_conf import TTSConf
from src.tts.elevenlabs_tts import ElevenLabsTTS, ElevenLabsTTSRequest, SpeechResult

__all__ = [
    "TTSConf",
    "ElevenLabsTTS",
    "ElevenLabsTTSRequest",
    "SpeechResult",
]
