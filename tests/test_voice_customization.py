"""Tests for voice customization options in speech-related moves and the ElevenLabsTTS backend."""

from unittest.mock import Mock, patch, MagicMock

from moves import (
    MoveSay, MoveAskYesNo, MoveAskOpen, MoveAskOptions,
    MOVE_SAY, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS,
)
from mini_dialogs import MiniDialog
from tts.tts_conf import TTSConf
from tts.elevenlabs_tts import ElevenLabsTTS, ElevenLabsTTSRequest, SpeechResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_agent(**overrides):
    agent = Mock()
    agent.say = Mock()
    agent.ask_yes_no = Mock(return_value='yes')
    agent.ask_open = Mock(return_value='answer')
    agent.ask_options = Mock(return_value='option_a')
    agent.play_audio = Mock()
    agent.play_motion_sequence = Mock()
    agent.play_animation = Mock()
    agent.personalize = Mock(return_value=None)
    for k, v in overrides.items():
        setattr(agent, k, v)
    return agent


# ---------------------------------------------------------------------------
# TTSConf
# ---------------------------------------------------------------------------

class TestTTSConf:
    def test_defaults(self):
        conf = TTSConf()
        assert conf.voice_id is None
        assert conf.model_id is None
        assert conf.speaking_rate == 1.0
        assert conf.pitch == 0.0
        assert conf.style == 0.0

    def test_custom_values(self):
        conf = TTSConf(voice_id="v123", model_id="m456", speaking_rate=1.5, pitch=2.0, style=0.3)
        assert conf.voice_id == "v123"
        assert conf.model_id == "m456"
        assert conf.speaking_rate == 1.5
        assert conf.pitch == 2.0
        assert conf.style == 0.3


# ---------------------------------------------------------------------------
# MoveSay voice params
# ---------------------------------------------------------------------------

class TestMoveSayVoiceParams:
    def test_constructor_defaults_to_none(self):
        move = MoveSay(text="hello")
        assert move.speaking_rate is None
        assert move.pitch is None
        assert move.voice is None
        assert move.style is None

    def test_constructor_with_voice_params(self):
        move = MoveSay(text="hello", speaking_rate=1.2, pitch=-1.0, voice="en-US-Wavenet-A", style=0.5)
        assert move.speaking_rate == 1.2
        assert move.pitch == -1.0
        assert move.voice == "en-US-Wavenet-A"
        assert move.style == 0.5

    def test_from_dict_with_voice_params(self):
        data = {
            "type": MOVE_SAY,
            "text": "hello",
            "speaking_rate": 0.9,
            "pitch": 1.5,
            "voice": "en-GB-Standard-B",
            "style": 0.2,
        }
        move = MoveSay.from_dict(data)
        assert move.text == "hello"
        assert move.speaking_rate == 0.9
        assert move.pitch == 1.5
        assert move.voice == "en-GB-Standard-B"
        assert move.style == 0.2

    def test_from_dict_without_voice_params_yields_none(self):
        move = MoveSay.from_dict({"text": "hi"})
        assert move.speaking_rate is None
        assert move.pitch is None
        assert move.voice is None
        assert move.style is None


# ---------------------------------------------------------------------------
# MoveAskYesNo voice params
# ---------------------------------------------------------------------------

class TestMoveAskYesNoVoiceParams:
    def test_constructor_with_voice_params(self):
        move = MoveAskYesNo(text="Do you agree?", speaking_rate=1.1, pitch=0.5, voice="v1", style=0.1)
        assert move.speaking_rate == 1.1
        assert move.pitch == 0.5
        assert move.voice == "v1"
        assert move.style == 0.1

    def test_from_dict_with_voice_params(self):
        data = {
            "type": MOVE_ASK_YESNO,
            "text": "Do you agree?",
            "speaking_rate": 1.3,
            "pitch": -0.5,
            "voice": "v2",
            "style": 0.0,
        }
        move = MoveAskYesNo.from_dict(data)
        assert move.speaking_rate == 1.3
        assert move.pitch == -0.5
        assert move.voice == "v2"
        assert move.style == 0.0

    def test_from_dict_without_voice_params_yields_none(self):
        move = MoveAskYesNo.from_dict({"text": "ok?"})
        assert move.speaking_rate is None
        assert move.pitch is None
        assert move.voice is None
        assert move.style is None


# ---------------------------------------------------------------------------
# MoveAskOpen voice params
# ---------------------------------------------------------------------------

class TestMoveAskOpenVoiceParams:
    def test_from_dict_with_voice_params(self):
        data = {
            "type": MOVE_ASK_OPEN,
            "text": "How are you?",
            "speaking_rate": 0.8,
            "pitch": 2.0,
            "voice": "v3",
            "style": 0.9,
        }
        move = MoveAskOpen.from_dict(data)
        assert move.speaking_rate == 0.8
        assert move.pitch == 2.0
        assert move.voice == "v3"
        assert move.style == 0.9

    def test_from_dict_without_voice_params_yields_none(self):
        move = MoveAskOpen.from_dict({"text": "hi?"})
        assert move.speaking_rate is None
        assert move.pitch is None
        assert move.voice is None
        assert move.style is None


# ---------------------------------------------------------------------------
# MoveAskOptions voice params
# ---------------------------------------------------------------------------

class TestMoveAskOptionsVoiceParams:
    def test_from_dict_with_voice_params(self):
        data = {
            "type": MOVE_ASK_OPTIONS,
            "text": "Pick one",
            "options": ["a", "b"],
            "speaking_rate": 1.5,
            "pitch": -1.0,
            "voice": "v4",
            "style": 0.3,
        }
        move = MoveAskOptions.from_dict(data)
        assert move.speaking_rate == 1.5
        assert move.pitch == -1.0
        assert move.voice == "v4"
        assert move.style == 0.3

    def test_from_dict_without_voice_params_yields_none(self):
        move = MoveAskOptions.from_dict({"text": "choose", "options": ["x", "y"]})
        assert move.speaking_rate is None
        assert move.pitch is None
        assert move.voice is None
        assert move.style is None


# ---------------------------------------------------------------------------
# MiniDialog passes voice params to agent
# ---------------------------------------------------------------------------

class TestMiniDialogVoiceParamPropagation:
    def test_handle_move_say_passes_voice_params(self):
        agent = _mock_agent()
        move = {
            "type": MOVE_SAY,
            "text": "Hello",
            "speaking_rate": 1.2,
            "pitch": -1.0,
            "voice": "en-US-Wavenet-B",
            "style": 0.4,
        }
        dialog = MiniDialog(dialog_id="t1", moves=[move])
        dialog.run(agent=agent)

        agent.say.assert_called_once_with(
            "Hello",
            speaking_rate=1.2,
            pitch=-1.0,
            voice="en-US-Wavenet-B",
            style=0.4,
        )

    def test_handle_move_say_passes_none_voice_params_when_absent(self):
        agent = _mock_agent()
        move = {"type": MOVE_SAY, "text": "Hi"}
        dialog = MiniDialog(dialog_id="t2", moves=[move])
        dialog.run(agent=agent)

        agent.say.assert_called_once_with(
            "Hi",
            speaking_rate=None,
            pitch=None,
            voice=None,
            style=None,
        )

    def test_handle_move_ask_yesno_passes_voice_params(self):
        agent = _mock_agent()
        move = {
            "type": MOVE_ASK_YESNO,
            "text": "Do you like it?",
            "speaking_rate": 0.9,
            "pitch": 1.0,
            "voice": "v5",
            "style": 0.1,
        }
        dialog = MiniDialog(dialog_id="t3", moves=[move])
        dialog.run(agent=agent)

        agent.ask_yes_no.assert_called_once_with(
            "Do you like it?",
            speaking_rate=0.9,
            pitch=1.0,
            voice="v5",
            style=0.1,
        )

    def test_handle_move_ask_open_passes_voice_params(self):
        agent = _mock_agent()
        move = {
            "type": MOVE_ASK_OPEN,
            "text": "Tell me about yourself.",
            "speaking_rate": 1.1,
            "pitch": 0.0,
            "voice": "v6",
            "style": 0.2,
        }
        dialog = MiniDialog(dialog_id="t4", moves=[move])
        dialog.run(agent=agent)

        agent.ask_open.assert_called_once_with(
            "Tell me about yourself.",
            speaking_rate=1.1,
            pitch=0.0,
            voice="v6",
            style=0.2,
        )

    def test_handle_move_ask_options_passes_voice_params(self):
        agent = _mock_agent()
        move = {
            "type": MOVE_ASK_OPTIONS,
            "text": "Which do you prefer?",
            "options": ["option_a", "option_b"],
            "speaking_rate": 1.3,
            "pitch": -0.5,
            "voice": "v7",
            "style": 0.5,
        }
        dialog = MiniDialog(dialog_id="t5", moves=[move])
        dialog.run(agent=agent)

        agent.ask_options.assert_called_once_with(
            "Which do you prefer?",
            ["option_a", "option_b"],
            speaking_rate=1.3,
            pitch=-0.5,
            voice="v7",
            style=0.5,
        )


# ---------------------------------------------------------------------------
# ElevenLabsTTS
# ---------------------------------------------------------------------------

def _make_elevenlabs_tts(voice_id="test-voice", speaking_rate=1.0, **kwargs):
    """Build an ElevenLabsTTS instance with a mocked ElevenLabs client."""
    fake_audio = b"\x00\x01" * 100

    mock_client = MagicMock()
    mock_client.text_to_speech.convert.return_value = iter([fake_audio])

    with patch("elevenlabs.client.ElevenLabs", return_value=mock_client):
        tts = ElevenLabsTTS(
            elevenlabs_key="fake-key",
            voice_id=voice_id,
            speaking_rate=speaking_rate,
            **kwargs,
        )

    tts._client = mock_client
    return tts, mock_client


class TestElevenLabsTTS:
    def test_request_returns_speech_result(self):
        tts, _ = _make_elevenlabs_tts()
        with patch("elevenlabs.VoiceSettings") as MockVS:
            MockVS.return_value = MagicMock()
            result = tts.request(ElevenLabsTTSRequest(text="Hello"))

        assert isinstance(result, SpeechResult)
        assert isinstance(result.waveform, bytes)
        assert result.sample_rate == ElevenLabsTTS.DEFAULT_SAMPLE_RATE

    def test_request_uses_instance_speaking_rate_by_default(self):
        tts, mock_client = _make_elevenlabs_tts(speaking_rate=1.5)
        with patch("elevenlabs.VoiceSettings") as MockVS:
            captured = {}
            def capture(**kwargs):
                captured.update(kwargs)
                return MagicMock()
            MockVS.side_effect = capture
            tts.request(ElevenLabsTTSRequest(text="Hi"))

        assert captured.get("speed") == 1.5

    def test_request_per_call_speaking_rate_overrides_default(self):
        tts, mock_client = _make_elevenlabs_tts(speaking_rate=1.0)
        with patch("elevenlabs.VoiceSettings") as MockVS:
            captured = {}
            def capture(**kwargs):
                captured.update(kwargs)
                return MagicMock()
            MockVS.side_effect = capture
            tts.request(ElevenLabsTTSRequest(text="Hi", speaking_rate=2.0))

        assert captured.get("speed") == 2.0

    def test_request_per_call_voice_id_overrides_default(self):
        tts, mock_client = _make_elevenlabs_tts(voice_id="default-voice")
        with patch("elevenlabs.VoiceSettings", return_value=MagicMock()):
            tts.request(ElevenLabsTTSRequest(text="Hi", voice_id="override-voice"))

        call_kwargs = mock_client.text_to_speech.convert.call_args
        assert call_kwargs.kwargs.get("voice_id") == "override-voice" or call_kwargs.args[0] == "override-voice"

    def test_request_raises_when_no_voice_id(self):
        tts, _ = _make_elevenlabs_tts(voice_id=None)
        import pytest
        with pytest.raises(ValueError, match="voice_id"):
            with patch("elevenlabs.VoiceSettings", return_value=MagicMock()):
                tts.request(ElevenLabsTTSRequest(text="Hi"))

    def test_invalid_sample_rate_raises(self):
        import pytest
        with patch("elevenlabs.client.ElevenLabs"):
            with pytest.raises(ValueError, match="sample_rate"):
                ElevenLabsTTS(elevenlabs_key="k", sample_rate=99999)

    def test_import_error_when_elevenlabs_not_installed(self):
        import pytest
        import sys
        saved = sys.modules.get("elevenlabs")
        sys.modules["elevenlabs"] = None
        sys.modules["elevenlabs.client"] = None
        try:
            with pytest.raises(ImportError, match="elevenlabs"):
                ElevenLabsTTS(elevenlabs_key="k")
        finally:
            if saved is None:
                sys.modules.pop("elevenlabs", None)
                sys.modules.pop("elevenlabs.client", None)
            else:
                sys.modules["elevenlabs"] = saved
                sys.modules.pop("elevenlabs.client", None)

    def test_request_style_passed_to_voice_settings(self):
        tts, mock_client = _make_elevenlabs_tts()
        with patch("elevenlabs.VoiceSettings") as MockVS:
            captured = {}
            def capture(**kwargs):
                captured.update(kwargs)
                return MagicMock()
            MockVS.side_effect = capture
            tts.request(ElevenLabsTTSRequest(text="Hi", style=0.7))

        assert captured.get("style") == 0.7

    def test_request_uses_default_model_id(self):
        tts, mock_client = _make_elevenlabs_tts()
        with patch("elevenlabs.VoiceSettings", return_value=MagicMock()):
            tts.request(ElevenLabsTTSRequest(text="Test"))

        call_kwargs = mock_client.text_to_speech.convert.call_args
        assert call_kwargs.kwargs.get("model_id") == ElevenLabsTTS.DEFAULT_MODEL_ID

    def test_request_uses_custom_model_id(self):
        tts, mock_client = _make_elevenlabs_tts(model_id="eleven_turbo_v2")
        with patch("elevenlabs.VoiceSettings", return_value=MagicMock()):
            tts.request(ElevenLabsTTSRequest(text="Test"))

        call_kwargs = mock_client.text_to_speech.convert.call_args
        assert call_kwargs.kwargs.get("model_id") == "eleven_turbo_v2"
