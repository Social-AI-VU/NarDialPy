from nardial.providers.tts import TTSProvider


class NullTTSProvider(TTSProvider):
    """No-audio TTS provider — prints spoken text to the terminal instead of producing audio."""

    def speak(self, text: str, **kwargs) -> None:
        print(f"Robot: {text}")

    def close(self) -> None:
        pass

    def cancel(self) -> None:
        pass
