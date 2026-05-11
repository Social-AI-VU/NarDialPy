import wave
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class TTSProvider(Protocol):
    def speak(self, text: str, **kwargs) -> None: ...
    def close(self) -> None: ...
    def cancel(self) -> None:
        """Attempt to interrupt an in-progress ``speak`` call.

        Called by :class:`~nardial.interaction_orchestrator.InteractionOrchestrator`
        when an IMMEDIATE interrupt cancels the running dialog task.

        **Current limitation**: the SIC framework does not expose a mid-request
        cancel handle for any TTS service.  All concrete implementations are
        therefore no-ops: the asyncio task is cancelled (preventing future moves
        from running), but any audio already submitted to the device will play
        to its natural end.  True mid-speech interruption requires SIC support.
        """


def _read_wav_bytes(path: str) -> tuple[bytes, int]:
    with wave.open(path, 'rb') as wf:
        if wf.getsampwidth() != 2:
            raise ValueError(f"WAV file {path} is not 16-bit audio")
        return wf.readframes(wf.getnframes()), wf.getframerate()


def _amplify_audio(waveform_bytes: bytes, compression_strength: float = 2.0, target_level: float = 0.9) -> bytes:
    audio_data = np.frombuffer(waveform_bytes, dtype=np.int16)
    audio_float = audio_data.astype(np.float32) / 32767.0
    max_val = np.max(np.abs(audio_float))
    audio_normalized = audio_float / max_val if max_val > 0 else audio_float
    sign = np.sign(audio_normalized)
    magnitude = np.abs(audio_normalized)
    compressed = sign * np.log1p(magnitude * compression_strength) / np.log1p(compression_strength)
    final_max = np.max(np.abs(compressed))
    if final_max > 0:
        compressed = compressed / final_max * target_level
    return (compressed * 32767).astype(np.int16).tobytes()
