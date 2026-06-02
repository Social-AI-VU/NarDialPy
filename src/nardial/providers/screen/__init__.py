from typing import Protocol, runtime_checkable


@runtime_checkable
class ScreenProvider(Protocol):
    """Protocol for optional browser-based screen display providers.

    All methods are ``async`` for protocol consistency — concrete implementations
    (``NullScreenProvider``, ``SICScreenAdapter``) may call synchronous non-blocking
    APIs internally.  Every call site in the orchestrator and runtime is guarded by
    ``if screen_provider is not None``, so sessions without a screen are completely
    unaffected.

    Transcript methods
    ------------------
    ``show_transcript(text)``      — robot's spoken text; called automatically by
                                     :meth:`~nardial.interaction_orchestrator.InteractionOrchestrator.say`.
    ``show_user_transcript(text)`` — user's recognised speech; called automatically by
                                     :meth:`~nardial.interaction_orchestrator.InteractionOrchestrator.listen`
                                     whenever a non-empty transcript is returned.

    Both sides are pushed automatically so dialog authors never need to add explicit
    transcript moves.

    Display methods
    ---------------
    ``show_image``, ``show_video``, ``show_iframe``, ``show_html`` — driven by the
    corresponding JSON move types (``show_image``, ``show_video``, ``show_iframe``,
    ``show_html``).

    Input methods
    -------------
    ``show_buttons`` / ``show_text_input`` — shown automatically by
    ``wait_for_web_input`` moves before waiting for a browser event.
    ``hide_input`` — called automatically after the move resolves (match or timeout).

    Lifecycle
    ---------
    ``black()``  — blank the display (no content).
    ``close()``  — release provider resources; called from
                   :meth:`~nardial.interaction_orchestrator.InteractionOrchestrator.disconnect`.
    """

    async def show_transcript(self, text: str) -> None:
        """Display the robot's spoken text in the transcript pane."""
        ...

    async def show_user_transcript(self, text: str) -> None:
        """Display the user's recognised speech in the transcript pane."""
        ...

    async def show_image(self, src: str, caption: str = "") -> None:
        """Display an image from a local path or URL.

        Parameters
        ----------
        src : str
            Local file path (relative to the static directory) or a full URL.
        caption : str
            Optional caption text shown below the image.
        """
        ...

    async def show_video(self, src: str) -> None:
        """Display a video from a local path or an embeddable URL.

        Parameters
        ----------
        src : str
            Local file path or an embeddable URL (e.g. a YouTube embed link).
        """
        ...

    async def show_iframe(self, url: str) -> None:
        """Embed an external URL in an iframe on the screen.

        Parameters
        ----------
        url : str
            The URL to embed.
        """
        ...

    async def show_html(self, html: str) -> None:
        """Render a raw HTML snippet in the display area.

        Parameters
        ----------
        html : str
            The HTML to inject.  Dialog authors are responsible for keeping this
            trusted; the frontend renders it verbatim via ``innerHTML``.
        """
        ...

    async def show_buttons(self, options: list[str]) -> None:
        """Display a row of clickable buttons, one per option.

        Parameters
        ----------
        options : list of str
            Button labels.  Clicking one emits a ``web_input`` event on the bus
            with ``data["value"]`` set to the chosen label.
        """
        ...

    async def show_text_input(self, prompt: str = "") -> None:
        """Show a text-input field with an optional placeholder.

        Parameters
        ----------
        prompt : str
            Placeholder / hint text for the input field.
        """
        ...

    async def hide_input(self) -> None:
        """Hide the current input widget (buttons or text input)."""
        ...

    async def black(self) -> None:
        """Set the display to blank/black — no content shown."""
        ...

    async def close(self) -> None:
        """Release any resources held by the provider."""
        ...


from nardial.providers.screen.pepper_tablet import PepperTabletScreenAdapter

__all__ = ["ScreenProvider", "PepperTabletScreenAdapter"]