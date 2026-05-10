import asyncio
import logging
import random as rand
from typing import Any

from mini import MouthLampColor, MouthLampMode
from sic_framework.core.message_python2 import AudioRequest
from sic_framework.devices.alphamini import Alphamini, SDKAnimationType

from nardial.events.bus import EventBus
from nardial.events.source import EventSource
from nardial.providers.device import AnimationStyle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Button source (stub — Alphamini has no native hardware buttons)
# ---------------------------------------------------------------------------

class AlphaMiniButtonSource(EventSource):
    """Stub EventSource for Alphamini — no native button hardware is available.

    Alphamini does not expose physical buttons or touch sensors through the SIC
    framework.  This stub exists for API completeness and to document the
    limitation clearly.  It exits immediately when started and never emits any
    events.

    For button-like input on Alphamini, use :class:`~nardial.events.sources.webhook.WebhookSource`
    to receive HTTP POST events from an external UI or SIC web component.
    """

    @property
    def source_id(self) -> str:
        return "AlphaMiniButtonSource"

    async def run(self, bus: EventBus) -> None:
        """No-op: Alphamini has no native button hardware to monitor."""
        logger.info("AlphaMiniButtonSource: no native button hardware — exiting immediately")


_SPEAKING_ACTS = [f"speakingAct{i}" for i in range(1, 18)]
_SPEAKING_EXPRESSIONS = [f"codemao{i}" for i in range(1, 21)]


class AlphaminiAdapter:
    def __init__(self, device: Alphamini):
        self._device = device
        self._speaker = None
        self._logger = None

    def setup(self, logger: Any) -> None:
        self._logger = logger
        self._speaker = self._device.speaker
        self._logger.info("Device is ALPHAMINI")

    def get_mic(self) -> Any | None:
        return self._device.mic

    def play_audio_bytes(self, audio_bytes: bytes, sample_rate: int) -> None:
        self._speaker.request(AudioRequest(audio_bytes, sample_rate))

    def say_natively(self, text: str, language: str = "en", animated: bool = False) -> None:
        pass

    def play_animation(self, animation_name: str, run_async: bool = False) -> None:
        self._device.animate(SDKAnimationType.ACTION, animation_name, run_async=run_async)

    def play_speaking_animation(self, style: AnimationStyle) -> None:
        self._device.animate(SDKAnimationType.EXPRESSION, rand.choice(_SPEAKING_EXPRESSIONS), run_async=True)
        self._device.animate(SDKAnimationType.ACTION, rand.choice(_SPEAKING_ACTS), run_async=True)

    def play_motion_sequence(self, file_path: str) -> None:
        pass

    def set_leds(self, r: float = 0, g: float = 0, b: float = 0, name: str = "FaceLeds") -> None:
        pass

    def signal_listening(self, start: bool = True) -> None:
        if start:
            self._device.set_mouth_lamp(color=MouthLampColor.GREEN, mode=MouthLampMode.NORMAL,
                                        run_async=True)
        else:
            self._device.set_mouth_lamp(color=MouthLampColor.WHITE, mode=MouthLampMode.BREATH,
                                        breath_duration=1000, run_async=True)

    def disconnect(self) -> None:
        self._device.stop_device()

    def get_event_sources(self) -> list:
        return []
