"""NarDialPy event system — public API surface.

Import from this package rather than reaching into submodules.

Core types
----------
Event, InterruptLevel, ResumePolicy      -- in ``types.py``
EventBus                                  -- in ``bus.py``
EventSource                               -- in ``source.py``
MiniDialogCheckpoint, LLMDialogCheckpoint -- in ``checkpoint.py``

Authoring models
----------------
EventHandlerSpec, TimerSourceSpec, WebhookSourceSpec -- in ``specs.py``
AnyEventSourceSpec                                    -- in ``specs.py``
instantiate_source                                    -- in ``specs.py``

Built-in sources
----------------
TimerSource         -- in ``sources/timer.py``
WebhookSource       -- in ``sources/webhook.py``
BackgroundLLMSource -- in ``sources/background_llm.py``
"""

from nardial.events.bus import EventBus
from nardial.events.checkpoint import AnyCheckpoint, LLMDialogCheckpoint, MiniDialogCheckpoint
from nardial.events.source import EventSource
from nardial.events.sources.background_llm import BackgroundLLMSource
from nardial.events.sources.timer import TimerSource
from nardial.events.sources.webhook import WebhookSource
from nardial.events.specs import (
    AnyEventSourceSpec,
    EventHandlerSpec,
    TimerSourceSpec,
    WebhookSourceSpec,
    instantiate_source,
)
from nardial.events.types import Event, InterruptLevel, ResumePolicy

__all__ = [
    # Core types
    "Event",
    "InterruptLevel",
    "ResumePolicy",
    # Bus
    "EventBus",
    # Source ABC
    "EventSource",
    # Checkpoints
    "MiniDialogCheckpoint",
    "LLMDialogCheckpoint",
    "AnyCheckpoint",
    # Authoring models
    "EventHandlerSpec",
    "TimerSourceSpec",
    "WebhookSourceSpec",
    "AnyEventSourceSpec",
    "instantiate_source",
    # Built-in sources
    "TimerSource",
    "WebhookSource",
    "BackgroundLLMSource",
]