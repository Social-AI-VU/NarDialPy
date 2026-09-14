import json
import os

from nardial.authoring.loader import load_dialog_registry
from nardial.dialog_registry import DialogRegistry
from nardial.mini_dialogs import ChitchatDialog, DialogType, FunctionalDialog, NarrativeDialog


def make_chitchat(dialog_id, topics):
    return ChitchatDialog(dialog_id=dialog_id, moves=[], topics=topics)


def make_narrative(dialog_id, thread, position):
    return NarrativeDialog(dialog_id=dialog_id, moves=[], thread=thread, position=position)


def make_functional(dialog_id, functional_type):
    return FunctionalDialog(dialog_id=dialog_id, moves=[], type=functional_type)


def test_build_indexes_by_id_and_type():
    pizza = make_chitchat("pizza_chat", topics=["pizza"])
    thread_step = make_narrative("thread_1_step_1", thread="thread_1", position=1)

    registry = DialogRegistry.build([pizza, thread_step])

    assert registry.get_by_id("pizza_chat") is pizza
    assert registry.get_by_id("missing") is None
    assert registry.get_by_type(DialogType.CHITCHAT) == [pizza]
    assert registry.get_by_type(DialogType.NARRATIVE) == [thread_step]
    assert registry.get_by_type(DialogType.LLM_BASED) == []


def test_get_by_attr_matches_multi_topic_dialogs():
    pizza_and_pasta = make_chitchat("food_chat", topics=["pizza", "pasta"])
    only_pasta = make_chitchat("pasta_chat", topics=["pasta"])
    unrelated = make_chitchat("weather_chat", topics=["weather"])

    registry = DialogRegistry.build([pizza_and_pasta, only_pasta, unrelated])

    assert registry.get_by_attr("topics", "pizza") == [pizza_and_pasta]
    assert set(registry.get_by_attr("topics", "pasta")) == {pizza_and_pasta, only_pasta}
    assert registry.get_by_attr("topics", "missing") == []


def test_get_by_attr_functional_type_uses_property():
    greeting = make_functional("greeting_1", functional_type="greeting")
    farewell = make_functional("farewell_1", functional_type="farewell")

    registry = DialogRegistry.build([greeting, farewell])

    assert registry.get_by_attr("functional_type", "greeting") == [greeting]
    assert registry.get_by_attr("functional_type", "farewell") == [farewell]
    assert greeting.is_greeting_dialog() is True
    assert greeting.is_farewell_dialog() is False
    assert farewell.is_farewell_dialog() is True


def test_build_skips_duplicate_dialog_ids(caplog):
    first = make_chitchat("dup", topics=["a"])
    second = make_chitchat("dup", topics=["b"])

    registry = DialogRegistry.build([first, second])

    assert registry.get_by_id("dup") is first
    assert registry.get_by_attr("topics", "b") == []


def _write_dialog_file(directory, filename, doc):
    with open(os.path.join(directory, filename), "w", encoding="utf-8") as f:
        json.dump(doc, f)


def test_load_dialog_registry_from_directory_with_malformed_file(tmp_path):
    good_doc = {
        "id": "greeting_1",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [{"type": "say", "text": "Hello!"}],
    }
    _write_dialog_file(tmp_path, "greeting.json", good_doc)
    _write_dialog_file(tmp_path, "broken.json", {"id": "broken", "type": "not_a_real_type", "moves": []})

    registry, errors = load_dialog_registry(str(tmp_path))

    assert isinstance(registry, DialogRegistry)
    assert registry.get_by_id("greeting_1") is not None
    assert len(errors) == 1
    assert "broken.json" in errors[0]
