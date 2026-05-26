from nardial.providers.device import DeviceAdapter


class NaoqiTTSProvider:
    def __init__(self, device: DeviceAdapter, language: str = "en"):
        self._device = device
        self._language = language

    def speak(self, text: str, **kwargs) -> None:
        self._device.say_natively(text, language=self._language)

    def close(self) -> None:
        pass
