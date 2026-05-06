"""Tests for TTSCacher — disk-based TTS audio cache."""
import os
import wave
import pytest

from nardial.providers.tts.cacher import TTSCacher


# ── helpers ───────────────────────────────────────────────────────────────────

def make_cacher(tmp_path):
    """Return a TTSCacher rooted at a temp directory."""
    return TTSCacher(
        tts_cache_dir=str(tmp_path / "tts_cache"),
        tts_cache_map_file_name="map.json",
    )


def minimal_audio_bytes() -> bytes:
    """16-bit PCM silence — just enough frames for a valid WAV."""
    return b"\x00\x00" * 100


# ── normalize_text ────────────────────────────────────────────────────────────

class TestNormalizeText:
    def test_lowercases_input(self):
        assert TTSCacher.normalize_text("Hello World") == "hello world"

    def test_strips_leading_and_trailing_whitespace(self):
        assert TTSCacher.normalize_text("  hi  ") == "hi"

    def test_removes_punctuation(self):
        result = TTSCacher.normalize_text("Hello, world!")
        assert "," not in result
        assert "!" not in result
        assert result == "hello world"

    def test_preserves_internal_whitespace(self):
        assert TTSCacher.normalize_text("hello world") == "hello world"

    def test_empty_string_returns_empty(self):
        assert TTSCacher.normalize_text("") == ""

    def test_punctuation_only_returns_empty(self):
        assert TTSCacher.normalize_text("...!!!") == ""


# ── make_tts_key ──────────────────────────────────────────────────────────────

class TestMakeTtsKey:
    def test_returns_hex_string(self, tmp_path):
        c = make_cacher(tmp_path)
        key = c.make_tts_key({"text": "hello", "voice": "en-US"})
        assert isinstance(key, str)
        assert len(key) == 32  # MD5 hex digest

    def test_same_payload_produces_same_key(self, tmp_path):
        c = make_cacher(tmp_path)
        p = {"text": "hello", "lang": "en"}
        assert c.make_tts_key(p) == c.make_tts_key(p)

    def test_different_payloads_produce_different_keys(self, tmp_path):
        c = make_cacher(tmp_path)
        k1 = c.make_tts_key({"text": "hello"})
        k2 = c.make_tts_key({"text": "goodbye"})
        assert k1 != k2

    def test_key_is_stable_regardless_of_dict_insertion_order(self, tmp_path):
        c = make_cacher(tmp_path)
        k1 = c.make_tts_key({"a": 1, "b": 2})
        k2 = c.make_tts_key({"b": 2, "a": 1})
        assert k1 == k2


# ── save_audio_file / load_audio_file ─────────────────────────────────────────

class TestSaveLoadRoundTrip:
    def test_saved_file_exists_on_disk(self, tmp_path):
        c = make_cacher(tmp_path)
        key = c.make_tts_key({"text": "hi"})
        c.save_audio_file(key, minimal_audio_bytes(), sample_rate=22050)
        path = c.load_audio_file(key)
        assert path is not None
        assert os.path.exists(path)

    def test_loaded_path_is_a_wav_file(self, tmp_path):
        c = make_cacher(tmp_path)
        key = c.make_tts_key({"text": "test"})
        c.save_audio_file(key, minimal_audio_bytes(), sample_rate=16000)
        path = c.load_audio_file(key)
        # wave.open will raise if the file is not a valid WAV
        with wave.open(path, "rb") as wf:
            assert wf.getframerate() == 16000

    def test_cached_file_uses_subfolder_partitioning(self, tmp_path):
        c = make_cacher(tmp_path)
        key = c.make_tts_key({"text": "partitioned"})
        c.save_audio_file(key, minimal_audio_bytes(), sample_rate=22050)
        path = c.load_audio_file(key)
        # Default subfolder_depth=2 → first 2 chars of key form a subfolder
        assert os.path.basename(os.path.dirname(path)) == key[:2]


class TestLoadMissingKey:
    def test_unknown_key_returns_none(self, tmp_path):
        c = make_cacher(tmp_path)
        assert c.load_audio_file("nonexistent_key") is None

    def test_stale_cache_entry_returns_none(self, tmp_path):
        """Cache map references a file that was deleted externally."""
        c = make_cacher(tmp_path)
        key = c.make_tts_key({"text": "stale"})
        c.save_audio_file(key, minimal_audio_bytes(), sample_rate=22050)
        # Delete the file directly
        os.remove(c.tts_cache[key])
        assert c.load_audio_file(key) is None

    def test_stale_entry_removed_from_cache(self, tmp_path):
        """After a stale-miss, the key is pruned from the in-memory index."""
        c = make_cacher(tmp_path)
        key = c.make_tts_key({"text": "pruned"})
        c.save_audio_file(key, minimal_audio_bytes(), sample_rate=22050)
        os.remove(c.tts_cache[key])
        c.load_audio_file(key)
        assert key not in c.tts_cache


# ── cache map persistence ─────────────────────────────────────────────────────

class TestCacheMapPersistence:
    def test_new_instance_loads_entries_saved_by_prior_instance(self, tmp_path):
        c1 = make_cacher(tmp_path)
        key = c1.make_tts_key({"text": "persist"})
        c1.save_audio_file(key, minimal_audio_bytes(), sample_rate=22050)

        # Recreate the cacher from the same directory
        c2 = make_cacher(tmp_path)
        path = c2.load_audio_file(key)
        assert path is not None
        assert os.path.exists(path)

    def test_cache_dir_created_on_first_save(self, tmp_path):
        cache_dir = str(tmp_path / "new_cache_dir")
        c = TTSCacher(tts_cache_dir=cache_dir)
        key = c.make_tts_key({"text": "init"})
        c.save_audio_file(key, minimal_audio_bytes(), sample_rate=22050)
        assert os.path.isdir(cache_dir)

    def test_empty_cache_on_fresh_start(self, tmp_path):
        c = make_cacher(tmp_path)
        assert c.tts_cache == {}
