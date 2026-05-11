import asyncio
import logging
import random as rand
from typing import Any

from sic_framework.core.message_python2 import AudioRequest
from sic_framework.devices import Pepper
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

class PepperButtonSource(EventSource):
    """Bridges Pepper's physical buttons and head tactile sensor to the NarDialPy event bus.

    Registers SIC callbacks on four connectors:

    ==================  ============================
    Connector           Emitted ``source`` identifier
    ==================  ============================
    ``tactile_sensor``  ``"head_tactile"``
    ``left_bumper``     ``"left_bumper"``
    ``right_bumper``    ``"right_bumper"``
    ``back_bumper``     ``"back_bumper"``
    ==================  ============================

    Each SIC callback runs in a Redis handler thread.  Events are enqueued onto
    a thread-safe ``asyncio.Queue`` via ``loop.call_soon_threadsafe`` and
    forwarded to the session bus inside :meth:`run`.

    Only *press* events (``msg.value == 1``) produce a bus event; release events
    (``msg.value == 0``) are silently discarded.

    Parameters
    ----------
    device : Pepper
        The SIC Pepper device instance.  Its button/sensor connectors are
        accessed when :meth:`run` is called (after the session bus is live).
    interrupt_level : InterruptLevel
        Interrupt level for emitted events (default: ``BETWEEN_DIALOGS``).
    priority : int
        Bus priority for emitted events (default: 30, higher than timers at 50).
    """

    # Pepper device attribute → clean button identifier used in dialog JSON.
    _CONNECTOR_MAP: dict[str, str] = {
        "tactile_sensor": "head_tactile",
        "left_bumper":    "left_bumper",
        "right_bumper":   "right_bumper",
        "back_bumper":    "back_bumper",
    }

    def __init__(
        self,
        device: Pepper,
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
        return "PepperButtonSource"

    def _make_callback(self, button_id: str):
        """Return a SIC callback that enqueues a press event for *button_id*.

        The returned function is safe to call from a non-asyncio thread.
        """
        def _on_event(msg) -> None:
            # value == 1 → pressed; value == 0 → released (ignored)
            if getattr(msg, "value", 0) == 1 and self._loop is not None:
                event = Event(
                    priority=self._priority,
                    type="button_press",
                    source=button_id,
                    data={"button": button_id},
                    interrupt_level=self._interrupt_level,
                    resume_policy=ResumePolicy.DISCARD,
                )
                try:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
                except RuntimeError:
                    # Loop was closed between the None-check above and this call.
                    logger.debug("PepperButtonSource: loop closed before event could be enqueued")
        return _on_event

    async def run(self, bus: EventBus) -> None:
        """Receive Pepper button/touch events and forward them to *bus*.

        Registers callbacks on each sensor connector, then loops indefinitely,
        forwarding queued events to the session bus until cancelled.

        Note: ``_loop`` and ``_queue`` are assigned *before* registering callbacks
        so that any button press arriving immediately after registration is never
        silently dropped by the ``self._loop is not None`` guard in the callback.
        """
        # Assign loop and queue BEFORE registering callbacks to close the startup
        # race: a physical button press arriving right after registration must not
        # be silently dropped.
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()

        for attr, button_id in self._CONNECTOR_MAP.items():
            connector = getattr(self._device, attr)
            connector.register_callback(self._make_callback(button_id))
            logger.debug("PepperButtonSource: registered callback for %r (%s)", attr, button_id)

        try:
            while True:
                event = await self._queue.get()
                await bus.emit(event)
        except asyncio.CancelledError:
            raise
        finally:
            # SIC provides no unregister_callback API.  Nulling _loop makes the
            # still-registered callbacks silent no-ops so stale presses on the
            # physical device do not enqueue events after this source has stopped.
            self._loop = None


# ---------------------------------------------------------------------------
# Animations
# ---------------------------------------------------------------------------

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

    def get_event_sources(self) -> list:
        """Return a :class:`PepperButtonSource` for Pepper's physical buttons.

        The source bridges Pepper's tactile sensor and three bumper buttons to
        the NarDialPy event bus so dialog designers can use ``wait_for_button``
        moves with ``"head_tactile"``, ``"left_bumper"``, ``"right_bumper"``,
        or ``"back_bumper"`` as button identifiers.
        """
        return [PepperButtonSource(self._device)]
