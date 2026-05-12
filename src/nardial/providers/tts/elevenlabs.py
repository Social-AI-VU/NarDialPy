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

    def speak(self, text: str, amplified: bool = False, always_regenerate: bool = False,
              chunk_audio: bool = True, **kwargs) -> None:
        chunks = [text] if (not chunk_audio or self._conf.model_id == 'eleven_v3') else self._split_text(text)

        for chunk in chunks:
            payload = {
                "text": self._tts_cacher.normalize_text(chunk),
                "tts_service": "ELEVENLABS",
                "speaking_rate": self._conf.speaking_rate,
                "voice_id": self._conf.voice_id,
                "model_id": self._conf.model_id,
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

            reply = self._tts.request(GetElevenLabsSpeechRequest(text=chunk))
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

    def cancel(self) -> None:
        """No-op: the SIC ElevenLabs service does not expose a mid-request cancel handle.

        True mid-speech interruption is not possible without SIC framework support.
        The IMMEDIATE interrupt will still cancel the asyncio task (stopping future
        moves and chunks), but the currently-playing audio chunk will finish on the device.
        """

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
