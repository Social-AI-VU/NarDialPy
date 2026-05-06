"""Tests for dialog-level agent/TTS configuration (multi-agent support)."""
import pytest
from unittest.mock import Mock, patch

from nardial.tts_manager import (
    DialogAgentConfig,
    GoogleTTSConf,
    ElevenLabsTTSConf,
    NaoqiTTSConf,
)
from nardial.mini_dialogs import (
    MiniDialog,
    FunctionalDialog,
    NarrativeDialog,
    ChitchatDialog,
    LLMDialog,
)
from nardial.authoring.factory import DialogFactory


# ---------------------------------------------------------------------------
# DialogAgentConfig.to_tts_conf() tests
# ---------------------------------------------------------------------------

class TestDialogAgentConfigToTTSConf:
    def test_overrides_voice_id_for_elevenlabs(self):
        base = ElevenLabsTTSConf(voice_id="base_voice", model_id="eleven_flash_v2_5")
        cfg = DialogAgentConfig(voice_id="dialog_voice")
        result = cfg.to_tts_conf(base)
        assert isinstance(result, ElevenLabsTTSConf)
        assert result.voice_id == "dialog_voice"
        assert result.model_id == "eleven_flash_v2_5"

    def test_overrides_speaking_rate_for_elevenlabs(self):
        base = ElevenLabsTTSConf(voice_id="v1", speaking_rate=None)
        cfg = DialogAgentConfig(speaking_rate=1.1)
        result = cfg.to_tts_conf(base)
        assert isinstance(result, ElevenLabsTTSConf)
        assert result.speaking_rate == pytest.approx(1.1)
        assert result.voice_id == "v1"

    def test_inherits_base_when_no_override_elevenlabs(self):
        base = ElevenLabsTTSConf(voice_id="base_voice", model_id="eleven_flash_v2_5")
        cfg = DialogAgentConfig()  # nothing set
        result = cfg.to_tts_conf(base)
        assert isinstance(result, ElevenLabsTTSConf)
        assert result.voice_id == "base_voice"

    def test_overrides_voice_name_for_google(self):
        base = GoogleTTSConf(google_tts_voice_name="en-US-Standard-C", speaking_rate=1.0)
        cfg = DialogAgentConfig(voice_id="nl-NL-Standard-A")
        result = cfg.to_tts_conf(base)
        assert isinstance(result, GoogleTTSConf)
        assert result.google_tts_voice_name == "nl-NL-Standard-A"
        assert result.speaking_rate == pytest.approx(1.0)
        assert result.google_tts_voice_gender == base.google_tts_voice_gender

    def test_overrides_speaking_rate_for_google(self):
        base = GoogleTTSConf(speaking_rate=1.0)
        cfg = DialogAgentConfig(speaking_rate=0.8)
        result = cfg.to_tts_conf(base)
        assert isinstance(result, GoogleTTSConf)
        assert result.speaking_rate == pytest.approx(0.8)

    def test_overrides_language_for_naoqi(self):
        base = NaoqiTTSConf(language="English")
        cfg = DialogAgentConfig(language="Dutch")
        result = cfg.to_tts_conf(base)
        assert isinstance(result, NaoqiTTSConf)
        assert result.language == "Dutch"

    def test_inherits_language_for_naoqi_when_not_set(self):
        base = NaoqiTTSConf(language="English")
        cfg = DialogAgentConfig()
        result = cfg.to_tts_conf(base)
        assert isinstance(result, NaoqiTTSConf)
        assert result.language == "English"

    def test_unknown_base_conf_returned_unchanged(self):
        from nardial.tts_manager import TTSConf
        base = TTSConf()
        cfg = DialogAgentConfig(voice_id="some_voice")
        result = cfg.to_tts_conf(base)
        assert result is base

    def test_tts_type_overrides_base_conf_type(self):
        """tts_type=google on a dialog should produce GoogleTTSConf even when base is ElevenLabs."""
        base = ElevenLabsTTSConf(voice_id="base_voice", model_id="eleven_flash_v2_5")
        cfg = DialogAgentConfig(tts_type="google", voice_id="nl-NL-Standard-A")
        result = cfg.to_tts_conf(base)
        assert isinstance(result, GoogleTTSConf)
        assert result.google_tts_voice_name == "nl-NL-Standard-A"

    def test_tts_type_elevenlabs_explicit(self):
        """tts_type=elevenlabs produces ElevenLabsTTSConf even when base is Google."""
        base = GoogleTTSConf(google_tts_voice_name="en-US-Standard-C")
        cfg = DialogAgentConfig(tts_type="elevenlabs", voice_id="funny_voice")
        result = cfg.to_tts_conf(base)
        assert isinstance(result, ElevenLabsTTSConf)
        assert result.voice_id == "funny_voice"

    def test_tts_type_naoqi_explicit(self):
        """tts_type=naoqi produces NaoqiTTSConf even when base is ElevenLabs."""
        base = ElevenLabsTTSConf(voice_id="base_voice")
        cfg = DialogAgentConfig(tts_type="naoqi", language="Dutch")
        result = cfg.to_tts_conf(base)
        assert isinstance(result, NaoqiTTSConf)
        assert result.language == "Dutch"


# ---------------------------------------------------------------------------
# DialogFactory parsing tests
# ---------------------------------------------------------------------------

class TestDialogFactoryParsesAgentConfig:
    def _minimal_functional(self, agent=None):
        doc = {
            "id": "test_dialog",
            "type": "functional",
            "functional_type": "greeting",
            "moves": [{"type": "say", "text": "Hi!"}],
        }
        if agent is not None:
            doc["agent"] = agent
        return doc

    def test_no_agent_config_when_absent(self):
        doc = self._minimal_functional()
        dialog = DialogFactory.from_json(doc)
        assert dialog.agent_config is None

    def test_parses_voice_id(self):
        doc = self._minimal_functional(agent={"voice_id": "abc123"})
        dialog = DialogFactory.from_json(doc)
        assert dialog.agent_config is not None
        assert dialog.agent_config.voice_id == "abc123"

    def test_parses_speaking_rate(self):
        doc = self._minimal_functional(agent={"speaking_rate": 0.9})
        dialog = DialogFactory.from_json(doc)
        assert dialog.agent_config is not None
        assert dialog.agent_config.speaking_rate == pytest.approx(0.9)

    def test_parses_language(self):
        doc = self._minimal_functional(agent={"language": "nl"})
        dialog = DialogFactory.from_json(doc)
        assert dialog.agent_config is not None
        assert dialog.agent_config.language == "nl"

    def test_parses_tts_type(self):
        doc = self._minimal_functional(agent={"tts_type": "google", "voice_id": "v1"})
        dialog = DialogFactory.from_json(doc)
        assert dialog.agent_config is not None
        assert dialog.agent_config.tts_type == "google"
        assert dialog.agent_config.voice_id == "v1"

    def test_parses_all_fields_together(self):
        doc = self._minimal_functional(agent={"tts_type": "naoqi", "voice_id": "v1", "speaking_rate": 1.2, "language": "en"})
        dialog = DialogFactory.from_json(doc)
        cfg = dialog.agent_config
        assert cfg is not None
        assert cfg.tts_type == "naoqi"
        assert cfg.voice_id == "v1"
        assert cfg.speaking_rate == pytest.approx(1.2)
        assert cfg.language == "en"

    def test_validates_agent_must_be_object(self):
        doc = self._minimal_functional()
        doc["agent"] = "elevenlabs"
        errors = DialogFactory.validate_doc(doc)
        assert any("agent" in e for e in errors)

    def test_validates_tts_type_must_be_known(self):
        doc = self._minimal_functional(agent={"tts_type": "unknown_service"})
        errors = DialogFactory.validate_doc(doc)
        assert any("tts_type" in e for e in errors)

    def test_validates_voice_id_must_be_string(self):
        doc = self._minimal_functional(agent={"voice_id": 42})
        errors = DialogFactory.validate_doc(doc)
        assert any("voice_id" in e for e in errors)

    def test_validates_speaking_rate_must_be_number(self):
        doc = self._minimal_functional(agent={"speaking_rate": "fast"})
        errors = DialogFactory.validate_doc(doc)
        assert any("speaking_rate" in e for e in errors)

    def test_validates_language_must_be_string(self):
        doc = self._minimal_functional(agent={"language": 99})
        errors = DialogFactory.validate_doc(doc)
        assert any("language" in e for e in errors)

    def test_narrative_dialog_carries_agent_config(self):
        doc = {
            "id": "narr1",
            "type": "narrative",
            "thread": "story",
            "position": 1,
            "agent": {"voice_id": "narr_voice"},
            "moves": [{"type": "say", "text": "Once upon a time."}],
        }
        dialog = DialogFactory.from_json(doc)
        assert isinstance(dialog, NarrativeDialog)
        assert dialog.agent_config is not None
        assert dialog.agent_config.voice_id == "narr_voice"

    def test_chitchat_dialog_carries_agent_config(self):
        doc = {
            "id": "chat1",
            "type": "chitchat",
            "theme": "robots",
            "agent": {"speaking_rate": 1.3},
            "moves": [{"type": "say", "text": "Beep boop."}],
        }
        dialog = DialogFactory.from_json(doc)
        assert isinstance(dialog, ChitchatDialog)
        assert dialog.agent_config is not None
        assert dialog.agent_config.speaking_rate == pytest.approx(1.3)


# ---------------------------------------------------------------------------
# to_json round-trip tests
# ---------------------------------------------------------------------------

class TestDialogFactoryToJsonRoundTrip:
    def test_round_trip_with_agent_config(self):
        doc = {
            "id": "g1",
            "type": "functional",
            "functional_type": "greeting",
            "agent": {"tts_type": "elevenlabs", "voice_id": "robot_voice", "speaking_rate": 0.95},
            "moves": [{"type": "say", "text": "Hello!"}],
        }
        dialog = DialogFactory.from_json(doc)
        out = DialogFactory.to_json(dialog)
        assert "agent" in out
        assert out["agent"]["tts_type"] == "elevenlabs"
        assert out["agent"]["voice_id"] == "robot_voice"
        assert out["agent"]["speaking_rate"] == pytest.approx(0.95)
        assert "language" not in out["agent"]  # was not set, should not appear

    def test_round_trip_without_agent_config(self):
        doc = {
            "id": "g2",
            "type": "functional",
            "functional_type": "greeting",
            "moves": [{"type": "say", "text": "Hi!"}],
        }
        dialog = DialogFactory.from_json(doc)
        out = DialogFactory.to_json(dialog)
        assert "agent" not in out


# ---------------------------------------------------------------------------
# SessionManager integration test
# ---------------------------------------------------------------------------

class TestSessionManagerAppliesAgentConfig:
    """Verify the dialog-level agent config switching logic used by SessionManager.

    These tests exercise the logic in isolation using simple stubs – they do not
    import SessionManager itself because that requires sic_framework which is not
    available in this environment.  The actual SessionManager.run() behaviour is
    covered by integration tests that run against a full stack.
    """

    def _run_dialog_with_agent(self, dialog, agent, base_tts_conf):
        """Simulate the per-dialog TTS-switching logic from SessionManager.run()."""
        if dialog.agent_config is not None:
            dialog_tts_conf = dialog.agent_config.to_tts_conf(base_tts_conf)
            agent.apply_tts_conf(dialog_tts_conf)
        elif agent.orchestrator.tts_conf is not base_tts_conf:
            agent.apply_tts_conf(base_tts_conf)

    def test_apply_tts_conf_called_when_dialog_has_agent_config(self):
        base_conf = GoogleTTSConf(google_tts_voice_name="en-US-Standard-C")
        dialog_conf = DialogAgentConfig(voice_id="nl-NL-Standard-A")

        agent = Mock()
        agent.orchestrator = Mock()
        agent.orchestrator.tts_conf = base_conf

        dialog = MiniDialog(dialog_id="d1", moves=[], agent_config=dialog_conf)
        self._run_dialog_with_agent(dialog, agent, base_conf)

        agent.apply_tts_conf.assert_called_once()
        applied = agent.apply_tts_conf.call_args[0][0]
        assert isinstance(applied, GoogleTTSConf)
        assert applied.google_tts_voice_name == "nl-NL-Standard-A"

    def test_apply_tts_conf_not_called_when_no_agent_config_and_conf_unchanged(self):
        base_conf = GoogleTTSConf()
        agent = Mock()
        agent.orchestrator = Mock()
        agent.orchestrator.tts_conf = base_conf

        dialog = MiniDialog(dialog_id="d1", moves=[])  # no agent_config
        self._run_dialog_with_agent(dialog, agent, base_conf)

        agent.apply_tts_conf.assert_not_called()

    def test_baseline_restored_after_dialog_with_agent_config(self):
        base_conf = GoogleTTSConf(google_tts_voice_name="en-US-Standard-C")
        dialog_conf = DialogAgentConfig(voice_id="nl-NL-Standard-A")

        applied_confs = []

        agent = Mock()
        agent.orchestrator = Mock()
        agent.orchestrator.tts_conf = base_conf

        def _apply(conf):
            applied_confs.append(conf)
            agent.orchestrator.tts_conf = conf

        agent.apply_tts_conf.side_effect = _apply

        # Dialog 1: has agent_config -> switches voice
        d1 = MiniDialog(dialog_id="d1", moves=[], agent_config=dialog_conf)
        self._run_dialog_with_agent(d1, agent, base_conf)

        # Dialog 2: no agent_config, but tts_conf was changed -> restore base
        d2 = MiniDialog(dialog_id="d2", moves=[])
        self._run_dialog_with_agent(d2, agent, base_conf)

        assert len(applied_confs) == 2
        assert applied_confs[0].google_tts_voice_name == "nl-NL-Standard-A"
        assert applied_confs[1] is base_conf

    def test_elevenlabs_voice_overridden_by_agent_config(self):
        base_conf = ElevenLabsTTSConf(voice_id="base_voice", model_id="eleven_flash_v2_5")
        dialog_conf = DialogAgentConfig(voice_id="funny_robot_voice")

        agent = Mock()
        agent.orchestrator = Mock()
        agent.orchestrator.tts_conf = base_conf

        dialog = MiniDialog(dialog_id="d1", moves=[], agent_config=dialog_conf)
        self._run_dialog_with_agent(dialog, agent, base_conf)

        agent.apply_tts_conf.assert_called_once()
        applied = agent.apply_tts_conf.call_args[0][0]
        assert isinstance(applied, ElevenLabsTTSConf)
        assert applied.voice_id == "funny_robot_voice"
        assert applied.model_id == "eleven_flash_v2_5"
