from nardial.authoring.factory import DialogFactory


def test_validate_doc_accepts_characters_and_move_character():
    doc = {
        "id": "scene_intro",
        "type": "functional",
        "functional_type": "greeting",
        "characters": {
            "narrator": {"voice_settings": {"voice_id": "v1", "language": "en"}},
        },
        "moves": [{"type": "say", "text": "Hello", "character": "narrator"}],
    }

    assert DialogFactory.validate_doc(doc) == []


def test_validate_doc_accepts_say_options_move():
    doc = {
        "id": "scene_intro",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [{"type": "say_options", "options": ["Hello", "Hi there"]}],
    }

    assert DialogFactory.validate_doc(doc) == []


def test_validate_doc_rejects_unknown_move_character():
    doc = {
        "id": "scene_intro",
        "type": "functional",
        "functional_type": "greeting",
        "characters": {
            "narrator": {"voice_settings": {"voice_id": "v1"}},
        },
        "moves": [{"type": "say", "text": "Hello", "character": "guide"}],
    }

    errors = DialogFactory.validate_doc(doc)
    assert any("unknown character 'guide'" in e for e in errors)


def test_validate_doc_rejects_invalid_say_options_move():
    doc = {
        "id": "scene_intro",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [{"type": "say_options", "options": []}],
    }

    errors = DialogFactory.validate_doc(doc)
    assert any("options must be a non-empty list of strings for say_options" in e for e in errors)


def test_validate_doc_rejects_invalid_character_voice_settings():
    doc = {
        "id": "scene_intro",
        "type": "functional",
        "functional_type": "greeting",
        "characters": {
            "narrator": {"voice_settings": "invalid"},
        },
        "moves": [{"type": "say", "text": "Hello"}],
    }

    errors = DialogFactory.validate_doc(doc)
    assert any("characters.narrator.voice_settings must be an object" in e for e in errors)


def test_validate_doc_requires_character_voice_settings():
    doc = {
        "id": "scene_intro",
        "type": "functional",
        "functional_type": "greeting",
        "characters": {
            "narrator": {},
        },
        "moves": [{"type": "say", "text": "Hello"}],
    }

    errors = DialogFactory.validate_doc(doc)
    assert any("characters.narrator.voice_settings is required" in e for e in errors)


def test_roundtrip_preserves_characters():
    doc = {
        "id": "scene_intro",
        "type": "functional",
        "functional_type": "greeting",
        "characters": {
            "narrator": {"voice_settings": {"voice_id": "v1"}},
        },
        "moves": [{"type": "say", "text": "Hello", "character": "narrator"}],
    }

    dialog = DialogFactory.from_json(doc)
    serialized = DialogFactory.to_json(dialog)
    assert serialized["characters"] == doc["characters"]
