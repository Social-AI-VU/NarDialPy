import asyncio
import random as rand
from typing import Any

from sic_framework.core.message_python2 import AudioRequest

from nardial.providers.device import AnimationStyle

from sic_framework.devices.reachy_mini import ReachyMiniDevice


# _SPEAKING_ACTS =
# _SPEAKING_EXPRESSIONS =


class ReachyMiniAdapter:
    def __init__(self, device: ReachyMiniDevice):
        self._device = device
        self._speaker = None
        self._logger = None

    def setup(self, logger: Any) -> None:
        self._logger = logger
        self._speaker = self._device.speakers
        self._logger.info("Device is REACHYMINI")

    def get_mic(self) -> Any | None:
        return self._device.mic

    def play_audio_bytes(self, audio_bytes: bytes, sample_rate: int) -> None:
        self._speaker.request(AudioRequest(audio_bytes, sample_rate))

    def say_natively(self, text: str, language: str = "en", animated: bool = False) -> None:
        pass

    def play_animation(self, animation_name: str, run_async: bool = False) -> None:
        pass

    def play_speaking_animation(self, style: AnimationStyle) -> None:
        pass

    def play_motion_sequence(self, file_path: str) -> None:
        pass

    def set_leds(self, r: float = 0, g: float = 0, b: float = 0, name: str = "FaceLeds") -> None:
        pass

    def signal_listening(self, start: bool = True) -> None:
        pass

    def disconnect(self) -> None:
        self._device.stop_device()
