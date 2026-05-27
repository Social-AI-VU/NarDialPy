import re

from sic_framework.services.elevenlabs_tts.elevenlabs_tts import (
    ElevenLabsTTS,
    ElevenLabsTTSConf,
    GetElevenLabsSpeechRequest,
)

from nardial.providers.device import DeviceAdapter
from nardial.providers.tts import TTSProvider, _amplify_audio, _read_wav_bytes
from nardial.providers.tts.cacher import TTSCacher


class ElevenLabsTTSProvider(TTSProvider):
    """TTS provider backed by the SIC ElevenLabs service with optional audio caching."""

    def __init__(self, conf: ElevenLabsTTSConf, device: DeviceAdapter,
                 tts_cacher: TTSCacher = None):
        self._conf = conf
        self._device = device
        self._tts_cacher = tts_cacher or TTSCacher()
        self._tts = ElevenLabsTTS(conf=conf)

    @staticmethod
    def _validate_and_normalize_voice_settings(voice_settings):
        if voice_settings is None:
            return {}
        if not isinstance(voice_settings, dict):
            raise ValueError("ElevenLabs voice_settings must be an object")
        allowed = {"voice_id", "speaking_rate", "model_id", "language"}
        unknown = set(voice_settings.keys()) - allowed
        if unknown:
            raise ValueError(f"Unsupported ElevenLabs voice_settings fields: {sorted(unknown)}")
        if "voice_id" in voice_settings and not isinstance(voice_settings["voice_id"], str):
            raise ValueError("ElevenLabs voice_settings.voice_id must be string")
        if "model_id" in voice_settings and not isinstance(voice_settings["model_id"], str):
            raise ValueError("ElevenLabs voice_settings.model_id must be string")
        if "speaking_rate" in voice_settings and not isinstance(voice_settings["speaking_rate"], (int, float)):
            raise ValueError("ElevenLabs voice_settings.speaking_rate must be numeric")
        if "language" in voice_settings and not isinstance(voice_settings["language"], str):
            raise ValueError("ElevenLabs voice_settings.language must be string")
        return voice_settings

    def speak(self, text: str, amplified: bool = False, always_regenerate: bool = False,
              chunk_audio: bool = True, voice_settings=None, **kwargs) -> None:
        voice_settings = self._validate_and_normalize_voice_settings(voice_settings)
        voice_id = voice_settings.get("voice_id", self._conf.voice_id)
        speaking_rate = voice_settings.get("speaking_rate", self._conf.speaking_rate)
        model_id = voice_settings.get("model_id", self._conf.model_id)
        chunks = [text] if (not chunk_audio or model_id == 'eleven_v3') else self._split_text(text)

        for chunk in chunks:
            payload = {
                "text": self._tts_cacher.normalize_text(chunk),
                "tts_service": "ELEVENLABS",
                "speaking_rate": speaking_rate,
                "voice_id": voice_id,
                "model_id": model_id,
            }
            tts_key = self._tts_cacher.make_tts_key(payload)

            if not always_regenerate:
                cached_path = self._tts_cacher.load_audio_file(tts_key)
                if cached_path:
                    audio, sample_rate = _read_wav_bytes(cached_path)
                    if amplified:
                        audio = _amplify_audio(audio)
                    self._device.play_audio_bytes(audio, sample_rate)
                    continue

            original_voice_id = self._conf.voice_id
            original_speaking_rate = self._conf.speaking_rate
            original_model_id = self._conf.model_id
            self._conf.voice_id = voice_id
            self._conf.speaking_rate = speaking_rate
            self._conf.model_id = model_id
            try:
                reply = self._tts.request(GetElevenLabsSpeechRequest(text=chunk))
            finally:
                self._conf.voice_id = original_voice_id
                self._conf.speaking_rate = original_speaking_rate
                self._conf.model_id = original_model_id
            if reply is None:
                continue

            audio_bytes = reply.waveform
            sample_rate = reply.sample_rate

            if audio_bytes and amplified:
                audio_bytes = _amplify_audio(audio_bytes)

            if audio_bytes:
                self._device.play_audio_bytes(audio_bytes, sample_rate)
                self._tts_cacher.save_audio_file(tts_key, audio_bytes, sample_rate)

    def close(self) -> None:
        self._tts.stop()

    @staticmethod
    def _split_text(text: str, max_len: int = 80, min_tail: int = 20) -> list[str]:
        text = text.strip()
        if len(text) <= max_len:
            return [text]
        chunks = []
        for sentence in re.split(r'(?<=[,.?!])(?=\s|[A-Z])', text):
            sentence = sentence.strip()
            if not sentence:
                continue
            while len(sentence) > max_len:
                chunk = sentence[:max_len]
                break_pos = max(chunk.rfind(','), chunk.rfind(' '))
                if break_pos == -1 or break_pos < max_len // 3:
                    break_pos = max_len
                if len(sentence) - break_pos < min_tail:
                    break_pos = len(sentence)
                chunks.append(sentence[:break_pos].strip())
                sentence = sentence[break_pos:].strip()
            if sentence:
                chunks.append(sentence)
        return chunks
