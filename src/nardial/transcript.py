from typing import Callable, Optional


class ObservableTranscript(list):
    """Session transcript list that notifies a listener on each append."""

    def __init__(self, on_append: Optional[Callable[[dict], None]] = None):
        super().__init__()
        self._on_append = on_append

    def append(self, item):
        super().append(item)
        if self._on_append is not None:
            self._on_append(item)
