import asyncio
import base64
import logging
import os
import hashlib
import struct
import time
import wave
import websockets
from enum import Enum
from json import dumps, loads, load, dump

from nardial.utils import normalize_text_for_cache_key


def _trim_trailing_pcm(pcm: bytes, *, threshold: int = 500, pad_samples: int = 220) -> bytes:
    """Drop trailing near-silence from 16-bit mono PCM (reduces end-of-utterance glitches)."""
    sample_count = len(pcm) // 2
    if sample_count <= 0:
        return pcm
    samples = struct.unpack(f"<{sample_count}h", pcm[: sample_count * 2])
    last = sample_count - 1
    while last >= 0 and abs(samples[last]) < threshold:
        last -= 1
    if last < 0:
        return pcm
    end = min(sample_count, last + 1 + pad_samples)
    return struct.pack(f"<{end}h", *samples[:end])


def postprocess_elevenlabs_pcm(pcm: bytes, sample_rate: int) -> bytes:
    """Trim near-silent tail and fade out — use for playback and cached audio."""
    if not pcm:
        return pcm
    return _fade_out_pcm_tail(_trim_trailing_pcm(pcm), sample_rate)


def _fade_out_pcm_tail(pcm: bytes, sample_rate: int, fade_ms: int = 12) -> bytes:
    """Short linear fade on the last few milliseconds to avoid an abrupt PCM cutoff."""
    sample_count = len(pcm) // 2
    if sample_count <= 0:
        return pcm
    fade_samples = min(sample_count, max(1, int(sample_rate * fade_ms / 1000)))
    samples = list(struct.unpack(f"<{sample_count}h", pcm[: sample_count * 2]))
    start = sample_count - fade_samples
    for i in range(fade_samples):
        factor = 1.0 - (i / fade_samples)
        samples[start + i] = int(samples[start + i] * factor)
    return struct.pack(f"<{sample_count}h", *samples)


class TTSService(Enum):
    """
        Enumeration of supported Text-to-Speech (TTS) services.

        Attributes:
            GOOGLE: Google Cloud Text-to-Speech service.
            ELEVENLABS: ElevenLabs streaming TTS service.
    """
    GOOGLE = 1
    ELEVENLABS = 2


class TTSConf:
    """
        Base configuration class for Text-to-Speech services.

        This class serves as a parent for specific TTS configuration types.
    """
    def __init__(self):
        pass


class GoogleTTSConf(TTSConf):
    """
        Configuration for Google Text-to-Speech.

        Args:
            speaking_rate (float): Speed of speech (1.0 = normal).
            google_tts_voice_name (str): Voice name identifier.
            google_tts_voice_gender (str): Voice gender (e.g., 'MALE', 'FEMALE').
    """

    def __init__(self, speaking_rate=1.0, google_tts_voice_name="nl-NL-Standard-D", google_tts_voice_gender="FEMALE"):
        super().__init__()
        self.speaking_rate = speaking_rate
        self.google_tts_voice_name = google_tts_voice_name
        self.google_tts_voice_gender = google_tts_voice_gender


class ElevenLabsTTSConf(TTSConf):
    """
        Configuration for ElevenLabs Text-to-Speech.

        Args:
            speaking_rate (Optional[float]): Optional speaking speed override.
            voice_id (str): Voice identifier in ElevenLabs.
            model_id (str): Model identifier used for synthesis.
    """
    def __init__(self, speaking_rate=None, voice_id='yO6w2xlECAQRFP6pX7Hw', model_id='eleven_flash_v2_5'):
        super().__init__()
        self.speaking_rate = None if speaking_rate == 1.0 else speaking_rate
        self.voice_id = voice_id
        self.model_id = model_id


class NaoqiTTSConf(TTSConf):
    """
        Configuration for NAOqi Text-to-Speech.

        Args:
            language (str): Language used by the NAOqi TTS engine.
    """
    def __init__(self, language="English"):
        super().__init__()
        self.language = language


class ElevenLabsTTS:
    """
        Asynchronous client for streaming speech synthesis using ElevenLabs.

        This class manages a WebSocket connection to the ElevenLabs API
        and streams audio responses for given text input.

        Args:
            elevenlabs_key (str): API key for ElevenLabs.
            voice_id (str): Voice identifier.
            model_id (str): Model identifier.
            sample_rate (int): Audio sample rate (Hz).
            speaking_rate (Optional[float]): Speech speed multiplier.
            stability (float): Voice stability parameter.
    """
    def __init__(self, elevenlabs_key, voice_id, model_id, sample_rate=22050, speaking_rate=None, stability=0.5):
        self.elevenlabs_key = elevenlabs_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.sample_rate = sample_rate
        self.websocket = None
        self.speaking_rate = max(0.7, min(speaking_rate, 1.2)) if speaking_rate else speaking_rate
        self.stability = stability
        # Development logging
        self.logger = logging.getLogger("droomrobot")

    async def connect(self):
        """
                Establish a WebSocket connection to the ElevenLabs streaming API
                and send initial voice configuration.
        """
        uri = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream-input"
            f"?model_id={self.model_id}"
            f"&output_format=pcm_{self.sample_rate}"
            f"&inactivity_timeout=180"
            f"&auto_mode=false"
        )
        self.websocket = await websockets.connect(uri)

        voice_settings = {
            "stability": self.stability,
            "similarity_boost": 0.8,
            "use_speaker_boost": False,
            # Lower thresholds than ElevenLabs default so short interview lines flush cleanly.
            "chunk_length_schedule": [80, 120, 200, 260],
        }
        if self.speaking_rate is not None:
            voice_settings["speed"] = self.speaking_rate

        # Required priming message (API); audio from this is discarded before each utterance.
        await self.websocket.send(dumps({
            "text": " ",
            "voice_settings": voice_settings,
            "auto_mode": False,
            "xi_api_key": self.elevenlabs_key,
        }))
        await self._discard_incoming_messages(max_wait_s=1.5)

    async def disconnect(self):
        """
                Gracefully close the WebSocket connection to the TTS service.
        """
        if self.websocket:
            try:
                await self.websocket.send(dumps({"text": ""}))  # end marker
                await self.websocket.close()
            except Exception as e:
                self.logger.error(f"[TTS] Error while closing websocket: {e}")
            finally:
                self.websocket = None

    async def ping_connection(self):
        """
        Check whether the current WebSocket connection is still alive.

        Returns:
            bool: True if the connection is active, False otherwise.
        """
        if not self.websocket:
            return False
        try:
            await self.websocket.ping()
            return True
        except Exception:
            return False

    async def _ensure_connected(self) -> None:
        """Open or reopen the stream-input socket (ElevenLabs often closes it after each utterance)."""
        if self.websocket and await self.ping_connection():
            return
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None
        self.logger.debug("[TTS] Connecting to ElevenLabs stream-input websocket.")
        await self.connect()

    def _release_connection_after_utterance(self) -> None:
        """Drop the socket after a completed utterance so the next speak starts clean."""
        self.websocket = None

    async def _discard_incoming_messages(self, max_wait_s: float = 0.5) -> None:
        """Drop websocket messages (e.g. priming audio) without collecting them."""
        if not self.websocket:
            return
        deadline = time.monotonic() + max_wait_s
        discarded = 0
        while time.monotonic() < deadline:
            try:
                await asyncio.wait_for(self.websocket.recv(), timeout=0.12)
                discarded += 1
            except asyncio.TimeoutError:
                break
            except websockets.exceptions.ConnectionClosed:
                break
        if discarded:
            self.logger.debug("[TTS] Discarded %s websocket message(s).", discarded)

    async def speak(self, text, recv_timeout_s: float = 30.0):
        """
        Send text to the ElevenLabs stream-input API and return full PCM audio.

        The API streams many JSON messages per utterance: zero or more with an
        ``audio`` field (base64 PCM fragments), then one with ``isFinal: true``.
        All audio chunks are collected before returning so playback is not cut off.

        Args:
            text (str): Input text to synthesize.
            recv_timeout_s (float): Per-message receive timeout while waiting for chunks.

        Returns:
            Optional[bytes]: Concatenated raw PCM bytes, or None on failure / empty audio.
        """
        text = (text or "").strip()
        if not text:
            return None

        await self._ensure_connected()
        await self._discard_incoming_messages(max_wait_s=0.4)

        utterance = text if text.endswith(" ") else f"{text} "

        chunks = []
        try:
            await self.websocket.send(dumps({"text": utterance}))
            # Flush buffered text (required for lines shorter than chunk_length_schedule).
            await self.websocket.send(dumps({"text": " ", "flush": True}))

            while True:
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=recv_timeout_s)
                    data = loads(message)

                    audio_b64 = data.get("audio")
                    if audio_b64:
                        chunks.append(base64.b64decode(audio_b64))

                    if data.get("isFinal") or data.get("is_final"):
                        await self._discard_incoming_messages(max_wait_s=0.25)
                        break
                except asyncio.TimeoutError:
                    self.logger.error("[TTS] Timed out waiting for ElevenLabs audio (isFinal not received).")
                    return None
                except websockets.exceptions.ConnectionClosedOK:
                    break
                except websockets.exceptions.ConnectionClosedError as e:
                    self.logger.error(f"[TTS] WebSocket closed with error: {e}")
                    return self._postprocess_pcm(b"".join(chunks)) if chunks else None
                except Exception as e:
                    self.logger.error(f"[TTS] Other failure in elevenlabs tts: {e}")
                    return self._postprocess_pcm(b"".join(chunks)) if chunks else None
        finally:
            self._release_connection_after_utterance()

        pcm = b"".join(chunks)
        if not pcm:
            self.logger.error("[TTS] ElevenLabs returned isFinal with no audio.")
            return None
        return self._postprocess_pcm(pcm)

    def _postprocess_pcm(self, pcm: bytes) -> bytes:
        return postprocess_elevenlabs_pcm(pcm, self.sample_rate)


class TTSCacher:
    """
        Caching utility for storing and retrieving synthesized TTS audio.

        Audio files are cached on disk and indexed using a hash key derived
        from the input text and TTS configuration.
    """

    def __init__(self, tts_cache_dir='tts_cache', tts_cache_map_file_name='tts_cache_map.json', subfolder_depth=2):
        """
                Initialize the TTS cache.

                Args:
                    tts_cache_dir (str): Directory where audio files are stored.
                    tts_cache_map_file_name (str): JSON file mapping keys to file paths.
                    subfolder_depth (int): Number of characters used for subfolder partitioning.
        """
        self.tts_cache_dir = tts_cache_dir
        self.tts_cache_map_file = os.path.join(tts_cache_dir, tts_cache_map_file_name)
        self.subfolder_depth = subfolder_depth

        self.tts_cache = self._load_cache()

    def make_tts_key(self, text: str, voice_conf: TTSConf) -> str:
        """
        Generate a unique hash key based on input text and TTS configuration.

        Args:
            text (str): Input text.
            voice_conf (TTSConf): TTS configuration object.

        Returns:
            str: MD5 hash key representing the input combination.

        Raises:
            ValueError: If the provided TTS configuration is unsupported.
        """
        if isinstance(voice_conf, GoogleTTSConf):
            payload = {
                "text": normalize_text_for_cache_key(text),
                'tts_service': "GOOGLE",
                "speaking_rate": voice_conf.speaking_rate,
                "setting_1": voice_conf.google_tts_voice_name,
                "setting_2": voice_conf.google_tts_voice_gender,
            }
        elif isinstance(voice_conf, ElevenLabsTTSConf):
            payload = {
                "text": normalize_text_for_cache_key(text),
                'tts_service': "ELEVENLABS",
                "speaking_rate": voice_conf.speaking_rate,
                "setting_1": voice_conf.model_id,
                "setting_2": voice_conf.voice_id,
            }
        else:
            raise ValueError(f'Voice Conf {voice_conf} is not supported.')

        # Sort keys to ensure deterministic JSON
        canonical = dumps(payload, sort_keys=True)
        return hashlib.md5(canonical.encode("utf-8")).hexdigest()

    def save_audio_file(self, tts_key: str, audio_bytes: bytes, sample_rate: int, sample_width: int = 2, channels: int = 1):
        """
                Save synthesized audio to disk and update the cache index.

                Args:
                    tts_key (str): Unique cache key.
                    audio_bytes (bytes): Raw audio data.
                    sample_rate (int): Audio sample rate.
                    sample_width (int): Bytes per sample (default: 2 for 16-bit audio).
                    channels (int): Number of audio channels.
        """
        subfolder = os.path.join(self.tts_cache_dir, tts_key[:self.subfolder_depth])
        os.makedirs(subfolder, exist_ok=True)
        filename = os.path.join(subfolder, f"{tts_key}.wav")

        with wave.open(filename, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)  # 2 bytes = 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_bytes)

        self.tts_cache[tts_key] = filename
        self._save_cache()

    def load_audio_file(self, tts_key):
        """
                Retrieve a cached audio file path if it exists.

                Args:
                    tts_key (str): Cache key.

                Returns:
                    Optional[str]: Path to the cached audio file, or None if not found.
        """
        if tts_key in self.tts_cache:
            # Cached audio exists, play it
            audio_file = self.tts_cache[tts_key]
            if os.path.exists(audio_file):
                return audio_file
            else:
                del self.tts_cache[tts_key]
        return None

    def _load_cache(self) -> dict:
        """
                Load the cache index from disk.

                Returns:
                    dict: Mapping of TTS keys to file paths.
        """
        if os.path.exists(self.tts_cache_map_file):
            with open(self.tts_cache_map_file, "r") as f:
                return load(f)
        return {}

    def _save_cache(self):
        """
                Persist the cache index to disk as a JSON file.
        """
        with open(self.tts_cache_map_file, "w") as f:
            dump(self.tts_cache, f, indent=2)