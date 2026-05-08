import wave
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class TTSProvider(Protocol):
    def speak(self, text: str, **kwargs) -> None: ...
    def close(self) -> None: ...


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
