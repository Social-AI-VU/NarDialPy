import json

import pytest

from nardial.authoring.factory import DialogFactory
from nardial.authoring.loader import load_dialogs


def test_load_dialogs_supports_file_level_characters_with_dialogs_array(tmp_path):
    payload = {
        "characters": {
            "narrator": {
                "voice_settings": {
                    "tts_type": "elevenlabs",
                    "voice_id": "voice_a",
                    "language": "en",
                    "speaking_rate": 0.8,
                }
            }
        },
        "dialogs": [
            {
                "id": "d1",
                "type": "functional",
                "functional_type": "greeting",
                "moves": [{"type": "say", "character": "narrator", "text": "Hello"}],
            }
        ],
    }
    path = tmp_path / "dialogs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    dialogs, errors = load_dialogs(str(path))
    assert errors == []
    assert len(dialogs) == 1
    assert dialogs[0].characters["narrator"]["voice_settings"]["voice_id"] == "voice_a"
    assert dialogs[0].moves[0]["character"] == "narrator"


def test_dialog_factory_rejects_unknown_character_on_move():
    doc = {
        "id": "d1",
        "type": "functional",
        "functional_type": "greeting",
        "characters": {
            "narrator": {"voice_settings": {"tts_type": "elevenlabs", "voice_id": "voice_a"}}
        },
        "moves": [{"type": "say", "character": "missing", "text": "Hello"}],
    }
    with pytest.raises(ValueError, match="references undefined character"):
        DialogFactory.from_json(doc)
