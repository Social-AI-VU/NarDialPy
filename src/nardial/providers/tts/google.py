import json

from sic_framework.services.google_tts.google_tts import GetSpeechRequest, Text2Speech, Text2SpeechConf

from nardial.providers.device import DeviceAdapter
from nardial.providers.tts import TTSProvider, _amplify_audio, _read_wav_bytes
from nardial.providers.tts.cacher import TTSCacher


class GoogleTTSConf:
    """
    Configuration for Google Text-to-Speech.

    Args:
        speaking_rate (float): Speed of speech (1.0 = normal).
        google_tts_voice_name (str): Voice name identifier.
        google_tts_voice_gender (str): Voice gender (e.g., 'MALE', 'FEMALE').
    """
    def __init__(self, speaking_rate=1.0, google_tts_voice_name="nl-NL-Standard-D", google_tts_voice_gender="FEMALE"):
        self.speaking_rate = speaking_rate
        self.google_tts_voice_name = google_tts_voice_name
        self.google_tts_voice_gender = google_tts_voice_gender


class GoogleTTSProvider(TTSProvider):
    def __init__(self, conf: GoogleTTSConf, device: DeviceAdapter, keyfile_path: str,
                 tts_cacher: TTSCacher = None):
        self._conf = conf
        self._device = device
        self._tts_cacher = tts_cacher or TTSCacher()

        google_tts_conf = Text2SpeechConf(
            keyfile_json=json.load(open(keyfile_path)),
            speaking_rate=conf.speaking_rate,
        )
        self._tts = Text2Speech(conf=google_tts_conf)
        init_reply = self._tts.request(GetSpeechRequest(
            text="I am initializing",
            voice_name=conf.google_tts_voice_name,
            ssml_gender=conf.google_tts_voice_gender,
        ))
        self._sample_rate = init_reply.sample_rate
        print('Google TTS activated')

    def speak(self, text: str, amplified: bool = False, always_regenerate: bool = False, **kwargs) -> None:
        payload = {
            "text": self._tts_cacher.normalize_text(text),
            "tts_service": "GOOGLE",
            "speaking_rate": self._conf.speaking_rate,
            "voice_name": self._conf.google_tts_voice_name,
            "voice_gender": self._conf.google_tts_voice_gender,
        }
        tts_key = self._tts_cacher.make_tts_key(payload)
        cached_path = self._tts_cacher.load_audio_file(tts_key)

        if not always_regenerate and cached_path:
            audio, sample_rate = _read_wav_bytes(cached_path)
            if amplified:
                audio = _amplify_audio(audio)
            self._device.play_audio_bytes(audio, sample_rate)
            return

        reply = self._tts.request(GetSpeechRequest(
            text=text,
            voice_name=self._conf.google_tts_voice_name,
            ssml_gender=self._conf.google_tts_voice_gender,
            speaking_rate=self._conf.speaking_rate,
        ))
        audio_bytes = reply.waveform
        sample_rate = reply.sample_rate

        if audio_bytes and amplified:
            audio_bytes = _amplify_audio(audio_bytes)

        self._device.play_audio_bytes(audio_bytes, sample_rate)
        self._tts_cacher.save_audio_file(tts_key, audio_bytes, sample_rate)

    def close(self) -> None:
        pass
