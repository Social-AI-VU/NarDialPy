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

    @staticmethod
    def _validate_and_normalize_voice_settings(voice_settings):
        if voice_settings is None:
            return {}
        if not isinstance(voice_settings, dict):
            raise ValueError("Google TTS voice_settings must be an object")
        allowed = {"speaking_rate", "voice_name", "gender", "google_tts_voice_name", "google_tts_voice_gender", "language"}
        unknown = set(voice_settings.keys()) - allowed
        if unknown:
            raise ValueError(f"Unsupported Google TTS voice_settings fields: {sorted(unknown)}")
        if "speaking_rate" in voice_settings and not isinstance(voice_settings["speaking_rate"], (int, float)):
            raise ValueError("Google TTS voice_settings.speaking_rate must be numeric")
        for key in ("voice_name", "gender", "google_tts_voice_name", "google_tts_voice_gender", "language"):
            if key in voice_settings and not isinstance(voice_settings[key], str):
                raise ValueError(f"Google TTS voice_settings.{key} must be string")
        return voice_settings

    def speak(self, text: str, amplified: bool = False, always_regenerate: bool = False, voice_settings=None, **kwargs) -> None:
        voice_settings = self._validate_and_normalize_voice_settings(voice_settings)
        speaking_rate = voice_settings.get("speaking_rate", self._conf.speaking_rate)
        voice_name = voice_settings.get("voice_name", voice_settings.get("google_tts_voice_name", self._conf.google_tts_voice_name))
        voice_gender = voice_settings.get("gender", voice_settings.get("google_tts_voice_gender", self._conf.google_tts_voice_gender))
        payload = {
            "text": self._tts_cacher.normalize_text(text),
            "tts_service": "GOOGLE",
            "speaking_rate": speaking_rate,
            "voice_name": voice_name,
            "voice_gender": voice_gender,
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
            voice_name=voice_name,
            ssml_gender=voice_gender,
            speaking_rate=speaking_rate,
        ))
        audio_bytes = reply.waveform
        sample_rate = reply.sample_rate

        if audio_bytes and amplified:
            audio_bytes = _amplify_audio(audio_bytes)

        self._device.play_audio_bytes(audio_bytes, sample_rate)
        self._tts_cacher.save_audio_file(tts_key, audio_bytes, sample_rate)

    def close(self) -> None:
        pass
