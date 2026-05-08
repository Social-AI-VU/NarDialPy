import asyncio
import random as rand
from typing import Any

from sic_framework.core.message_python2 import AudioRequest
from sic_framework.devices import Pepper
from sic_framework.devices.common_naoqi.naoqi_leds import NaoFadeRGBRequest
from sic_framework.devices.common_naoqi.naoqi_motion import NaoqiAnimationRequest
from sic_framework.devices.common_naoqi.naoqi_motion_recorder import NaoqiMotionRecording, PlayRecording
from sic_framework.devices.common_naoqi.naoqi_text_to_speech import NaoqiTextToSpeechRequest

from nardial.providers.device import AnimationStyle

_EXPRESSIVE_ANIMATIONS = [
    "animations/Stand/Emotions/Positive/Happy_4",
    "animations/Stand/Emotions/Positive/Peaceful_1",
    "animations/Stand/Gestures/But_1",
    "animations/Stand/Gestures/CalmDown_6",
    "animations/Stand/Gestures/Enthusiastic_4",
    "animations/Stand/Gestures/Everything_3",
    "animations/Stand/Gestures/Everything_4",
    "animations/Stand/Gestures/Explain_1",
    "animations/Stand/Gestures/Explain_10",
    "animations/Stand/Gestures/Explain_11",
    "animations/Stand/Gestures/Far_1",
    "animations/Stand/Gestures/Far_2",
    "animations/Stand/Gestures/Far_3",
    "animations/Stand/Gestures/ShowSky_1",
    "animations/Stand/Gestures/ShowSky_5",
    "animations/Stand/Gestures/ShowSky_7",
    "animations/Stand/Gestures/ShowSky_8",
    "animations/Stand/Gestures/IDontKnow_1",
    "animations/Stand/Gestures/IDontKnow_2",
    "animations/Stand/Gestures/No_1",
    "animations/Stand/Gestures/No_2",
    "animations/Stand/Gestures/No_9",
    "animations/Stand/Gestures/Yes_1",
    "animations/Stand/Gestures/Yes_2",
]

_EXPLANATORY_ANIMATIONS = [
    "animations/Stand/Gestures/Everything_2",
    "animations/Stand/Gestures/Explain_1",
    "animations/Stand/Gestures/Explain_10",
    "animations/Stand/Gestures/Explain_2",
    "animations/Stand/Gestures/Explain_4",
    "animations/Stand/Gestures/Explain_5",
    "animations/Stand/Gestures/Give_3",
    "animations/Stand/Gestures/Give_5",
    "animations/Stand/Gestures/IDontKnow_1",
    "animations/Stand/Gestures/IDontKnow_2",
    "animations/Stand/Gestures/Me_1",
    "animations/Stand/Gestures/Me_4",
    "animations/Stand/Gestures/No_1",
    "animations/Stand/Gestures/No_2",
    "animations/Stand/Gestures/No_9",
    "animations/Stand/Gestures/ShowFloor_3",
    "animations/Stand/Gestures/ShowFloor_4",
    "animations/Stand/Gestures/ShowSky_6",
    "animations/Stand/Gestures/Thinking_1",
    "animations/Stand/Gestures/Thinking_3",
    "animations/Stand/Gestures/Thinking_6",
    "animations/Stand/Gestures/Yes_1",
    "animations/Stand/Gestures/Yes_2",
    "animations/Stand/Gestures/YouKnowWhat_2",
    "animations/Stand/Gestures/You_1",
]


class PepperAdapter:
    def __init__(self, device: Pepper):
        self._device = device
        self._speaker = None
        self._logger = None

    def setup(self, logger: Any) -> None:
        self._speaker = self._device.speaker
        self._logger = logger
        self._logger.info("Device is PEPPER")

    def get_mic(self) -> Any | None:
        return self._device.mic

    def play_audio_bytes(self, audio_bytes: bytes, sample_rate: int) -> None:
        self._speaker.request(AudioRequest(audio_bytes, sample_rate))

    def say_natively(self, text: str, language: str = "en", animated: bool = False) -> None:
        self._device.tts.request(NaoqiTextToSpeechRequest(text, animated=animated, language=language))

    def play_animation(self, animation_name: str, run_async: bool = False) -> None:
        try:
            self._device.motion.request(NaoqiAnimationRequest(animation_name), block=not run_async)
        except Exception as e:
            self._logger.error(f"Failed to play animation: {animation_name}", exc_info=e)

    def play_speaking_animation(self, style: AnimationStyle) -> None:
        animations = _EXPRESSIVE_ANIMATIONS if style == AnimationStyle.EXPRESSIVE else _EXPLANATORY_ANIMATIONS
        self._device.motion.request(NaoqiAnimationRequest(rand.choice(animations)), block=False)

    def play_motion_sequence(self, file_path: str) -> None:
        try:
            recording = NaoqiMotionRecording.load(file_path)
            self._device.motion_record.request(PlayRecording(recording))
        except Exception as e:
            self._logger.error(f"Failed to play motion sequence: {file_path}", exc_info=e)

    def set_leds(self, r: float = 0, g: float = 0, b: float = 0, name: str = "FaceLeds") -> None:
        self._device.leds.request(NaoFadeRGBRequest(name, r, g, b, 0))

    def signal_listening(self, start: bool = True) -> None:
        if start:
            self.set_leds(g=1)
        else:
            self.set_leds()

    def disconnect(self) -> None:
        pass
