import hashlib
import os
import string
import wave
from json import dumps, load, dump


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

    @staticmethod
    def normalize_text(text: str) -> str:
        """
        Normalize text for consistent cache key generation.

        This includes lowercasing, trimming whitespace, and removing punctuation.

        Args:
            text (str): Input text.

        Returns:
            str: Normalized text.
        """
        text = text.strip().lower()
        text = text.translate(str.maketrans("", "", string.punctuation))
        return text

    def make_tts_key(self, payload: dict) -> str:
        """
        Generate a unique hash key from a caller-supplied payload dict.

        The caller is responsible for building a deterministic payload that
        captures all voice and text parameters that affect the output audio.
        Use ``normalize_text`` to canonicalize the text before including it.

        Args:
            payload (dict): Arbitrary key/value pairs describing the synthesis request.

        Returns:
            str: MD5 hex digest of the sorted JSON payload.
        """
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
        """Persist the cache index to disk as a JSON file."""
        with open(self.tts_cache_map_file, "w") as f:
            dump(self.tts_cache, f, indent=2)
