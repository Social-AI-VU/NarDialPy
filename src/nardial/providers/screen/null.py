import logging

logger = logging.getLogger(__name__)


class NullScreenProvider:
    """No-op screen provider — logs what would be shown instead of driving a browser.

    Use this in development sessions, unit tests, or robot-only runs without a
    connected display.  Every method is ``async`` to satisfy the
    :class:`~nardial.providers.screen.ScreenProvider` protocol via structural typing,
    but none perform any I/O.
    """

    async def show_transcript(self, text: str) -> None:
        logger.debug("[NullScreen] robot: %s", text)

    async def show_user_transcript(self, text: str) -> None:
        logger.debug("[NullScreen] user: %s", text)

    async def show_image(self, src: str, caption: str = "") -> None:
        logger.debug("[NullScreen] show_image src=%r caption=%r", src, caption)

    async def show_video(self, src: str) -> None:
        logger.debug("[NullScreen] show_video src=%r", src)

    async def show_iframe(self, url: str) -> None:
        logger.debug("[NullScreen] show_iframe url=%r", url)

    async def show_html(self, html: str) -> None:
        logger.debug("[NullScreen] show_html %d chars", len(html))

    async def show_buttons(self, options: list[str]) -> None:
        logger.debug("[NullScreen] show_buttons %r", options)

    async def show_text_input(self, prompt: str = "") -> None:
        logger.debug("[NullScreen] show_text_input prompt=%r", prompt)

    async def hide_input(self) -> None:
        logger.debug("[NullScreen] hide_input")

    async def black(self) -> None:
        logger.debug("[NullScreen] black")

    async def close(self) -> None:
        logger.debug("[NullScreen] close")
