import asyncio
import re
from threading import Thread

from nardial.providers.device import DeviceAdapter
from nardial.providers.tts import _amplify_audio, _read_wav_bytes
from nardial.tts_manager import ElevenLabsTTSConf, ElevenLabsTTS, TTSCacher


class ElevenLabsTTSProvider:
    def __init__(self, conf: ElevenLabsTTSConf, device: DeviceAdapter, api_key: str,
                 tts_cacher: TTSCacher = None):
        self._conf = conf
        self._device = device
        self._tts_cacher = tts_cacher or TTSCacher()
        self._sample_rate = 22050

        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self._tts = ElevenLabsTTS(
            elevenlabs_key=api_key,
            voice_id=conf.voice_id,
            model_id=conf.model_id,
            sample_rate=self._sample_rate,
            speaking_rate=conf.speaking_rate,
        )
        connect_future = asyncio.run_coroutine_threadsafe(self._tts.connect(), self._loop)
        try:
            connect_future.result()
            asyncio.run_coroutine_threadsafe(self._tts.speak("Initializing text to speech"), self._loop).result()
            print('ElevenLabs TTS activated')
        except Exception as e:
            print(f"Failed to connect to ElevenLabs: {e}")

    def speak(self, text: str, amplified: bool = False, always_regenerate: bool = False,
              chunk_audio: bool = True, **kwargs) -> None:
        chunks = [text] if (not chunk_audio or self._conf.model_id == 'eleven_v3') else self._split_text(text)

        for chunk in chunks:
            tts_key = self._tts_cacher.make_tts_key(chunk, self._conf)

            if not always_regenerate:
                cached_path = self._tts_cacher.load_audio_file(tts_key)
                if cached_path:
                    audio, sample_rate = _read_wav_bytes(cached_path)
                    if amplified:
                        audio = _amplify_audio(audio)
                    self._device.play_audio_bytes(audio, sample_rate)
                    continue

            audio_bytes = asyncio.run_coroutine_threadsafe(self._tts.speak(chunk), self._loop).result()

            if audio_bytes and amplified:
                audio_bytes = _amplify_audio(audio_bytes)

            if audio_bytes:
                self._device.play_audio_bytes(audio_bytes, self._sample_rate)
                self._tts_cacher.save_audio_file(tts_key, audio_bytes, self._sample_rate)

    def close(self) -> None:
        asyncio.run_coroutine_threadsafe(self._tts.disconnect(), self._loop).result()
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

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
