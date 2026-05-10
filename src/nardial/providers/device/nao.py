import asyncio
import logging
import random as rand
from typing import Any

from sic_framework.core.message_python2 import AudioRequest
from sic_framework.devices import Nao
from sic_framework.devices.common_naoqi.naoqi_leds import NaoFadeRGBRequest
from sic_framework.devices.common_naoqi.naoqi_motion import NaoqiAnimationRequest
from sic_framework.devices.common_naoqi.naoqi_motion_recorder import NaoqiMotionRecording, PlayRecording
from sic_framework.devices.common_naoqi.naoqi_text_to_speech import NaoqiTextToSpeechRequest

from nardial.events.bus import EventBus
from nardial.events.source import EventSource
from nardial.events.types import Event, InterruptLevel, ResumePolicy
from nardial.providers.device import AnimationStyle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Button source
# ---------------------------------------------------------------------------

# Mapping from NAOqi ALMemory touch/button key names to clean identifiers
# used as the ``source`` field on emitted events and in dialog JSON.
# See: http://doc.aldebaran.com/2-4/naoqi/sensors/altouch.html
_NAO_BUTTON_MAP: dict[str, str] = {
    "ChestBoard/Button":        "chest_button",
    "Head/Touch/Front":         "head_front",
    "Head/Touch/Middle":        "head_middle",
    "Head/Touch/Rear":          "head_rear",
    "LFoot/Bumper/Left":        "left_bumper_left",
    "LFoot/Bumper/Right":       "left_bumper_right",
    "RFoot/Bumper/Left":        "right_bumper_left",
    "RFoot/Bumper/Right":       "right_bumper_right",
    "Hand/Left/Back/Touch":     "left_hand",
    "Hand/Right/Back/Touch":    "right_hand",
}


class NaoButtonSource(EventSource):
    """Bridges NAO's physical buttons and touch sensors to the NarDialPy event bus.

    The SIC ``NaoqiButton`` connector fires ``NaoqiButtonMessage(value)`` whenever
    a button or touch sensor changes state.  ``value`` is a list of
    ``[naoqi_key, bool]`` pairs (True = pressed, False = released).

    Each *pressed* entry is translated to a ``"button_press"`` event with the
    ``source`` field set to the friendly name from :data:`_NAO_BUTTON_MAP`.
    Unknown NAOqi key names are passed through verbatim so the bus never drops
    events for newly-added hardware.

    The SIC callback runs in a Redis handler thread.  Events are enqueued onto a
    thread-safe ``asyncio.Queue`` via ``loop.call_soon_threadsafe`` and forwarded
    to the session bus from within :meth:`run`.

    Parameters
    ----------
    device : Nao
        The SIC NAO device instance.
    interrupt_level : InterruptLevel
        Interrupt level for emitted events (default: ``BETWEEN_DIALOGS``).
    priority : int
        Bus priority for emitted events (default: 30).
    """

    def __init__(
        self,
        device: Nao,
        *,
        interrupt_level: InterruptLevel = InterruptLevel.BETWEEN_DIALOGS,
        priority: int = 30,
    ) -> None:
        self._device = device
        self._interrupt_level = interrupt_level
        self._priority = priority
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[Event] | None = None

    @property
    def source_id(self) -> str:
        return "NaoButtonSource"

    def _on_button(self, msg) -> None:
        """SIC callback: invoked from the Redis handler thread on each touch change.

        Iterates the ``value`` list and enqueues one event per *pressed* button.
        """
        if self._loop is None:
            return
        for entry in msg.value:
            # Each entry is [naoqi_key, pressed_bool].
            if len(entry) < 2:
                continue
            naoqi_key, pressed = entry[0], entry[1]
            if not pressed:
                continue
            button_id = _NAO_BUTTON_MAP.get(naoqi_key, naoqi_key)
            event = Event(
                priority=self._priority,
                type="button_press",
                source=button_id,
                data={"button": button_id, "naoqi_key": naoqi_key},
                interrupt_level=self._interrupt_level,
                resume_policy=ResumePolicy.DISCARD,
            )
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    async def run(self, bus: EventBus) -> None:
        """Receive NAO button events and forward them to *bus*.

        Registers a single callback on the ``buttons`` connector, then loops
        indefinitely, forwarding queued events to the session bus until cancelled.
        """
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._device.buttons.register_callback(self._on_button)
        logger.debug("NaoButtonSource: registered callback on buttons connector")

        try:
            while True:
                event = await self._queue.get()
                await bus.emit(event)
        except asyncio.CancelledError:
            raise

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


class NaoAdapter:
    def __init__(self, device: Nao):
        self._device = device
        self._speaker = None
        self._logger = None

    def setup(self, logger: Any) -> None:
        self._speaker = self._device.speaker
        self._logger = logger
        self._logger.info("Device is NAO")

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

    def get_event_sources(self) -> list:
        """Return a :class:`NaoButtonSource` for NAO's physical buttons and touch sensors.

        The source bridges NAO's chest button, head touch sensors, and foot bumpers
        to the NarDialPy event bus so dialog designers can use ``wait_for_button``
        moves with friendly identifiers such as ``"chest_button"`` or ``"head_middle"``.
        """
        return [NaoButtonSource(self._device)]
