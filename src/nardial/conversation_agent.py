import json
import re

from sic_framework.devices import Nao, Pepper
from sic_framework.devices.device import SICDeviceManager
from nardial.dialog_manager import DialogManager, InteractionConfig


class ConversationAgent:
    def __init__(self, device_manager: SICDeviceManager, int_config: InteractionConfig = None):
        if int_config is None:
            int_config = InteractionConfig()
        self.dialog_manager = DialogManager(device_manager=device_manager, int_config=int_config)
        self.device = device_manager

    def say(self, text):
        self.dialog_manager.say(text)

    def play_audio(self, audio_file):
        self.dialog_manager.play_audio(audio_file)

    def play_motion_sequence(self, motion_sequence_file):
        self.dialog_manager.play_motion(motion_sequence_file)

    def play_animation(self, animation_name, block=False):
        if isinstance(self.device, Pepper) or isinstance(self.device, Nao):
            try:
                self.dialog_manager.animate_naoqi(animation_name, block)
            except Exception as e:
                print(f"Failed to play animation: {animation_name}", e)

    def ask_yesno(self, question, max_attempts=1):
        attempts = 0
        while attempts < max_attempts:
            self.say(question)
            reply, intent = self.dialog_manager.listen(context={'answer_yesno': 1})

            if intent:
                print(f'context: answer_yesno, recognized_intent: {str(intent)}')
                if intent == "yesno_yes":
                    return "yes"
                elif intent == "yesno_no":
                    return "no"
                elif intent == "yesno_dontknow":
                    return "dontknow"

            attempts += 1
        return None

    def ask_open(self, question, max_attempts=2):
        attempts = 0
        while attempts < max_attempts:
            self.say(question)
            reply, _ = self.dialog_manager.listen()
            if reply:
                return reply
            attempts += 1
        return None

    def ask_options(self, question, options, max_attempts=2):
        answer = self.ask_open(question, max_attempts=max_attempts)
        if answer:
            answer_lower = answer.lower()
            for opt in options:
                if opt in answer_lower:
                    return opt
        return None

    def extract_topics_with_gpt(self, raw_topics):
        """Condense raw topics (often full sentences) into 1-2 single-word, lowercase keywords.

        Returns a de-duplicated list preserving order. Falls back to a simple local heuristic
        if the GPT response can't be parsed.
        """

        def _heuristic(lines):
            if not lines:
                return []
            stop = {
                "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those",
                "i", "you", "he", "she", "it", "we", "they", "me", "my", "mine", "your", "yours", "his", "her", "its", "our", "ours", "their", "theirs",
                "to", "in", "on", "at", "from", "for", "with", "about", "as", "of", "is", "are", "was", "were", "be", "been", "am", "do", "does", "did",
                "yes", "no", "maybe", "okay", "ok", "yeah", "yep", "nope", "uh", "um", "favorite", "favourite", "because", "thing", "things", "think"
            }
            out, seen = [], set()
            for t in lines:
                words = re.findall(r"[A-Za-z]+", str(t).lower())
                picked = [w for w in words if len(w) > 2 and w not in stop]
                if not picked and words:
                    picked = [words[0]]
                # take up to 2 keywords per input line
                for w in picked[:2]:
                    if w not in seen:
                        out.append(w);
                        seen.add(w)
            return out

        raw_topics = [str(x) for x in (raw_topics or []) if str(x).strip()]
        if not raw_topics:
            return []
        try:
            prompt = (
                "You will receive a JSON array of phrases. For each item, extract 1-2 concise English keywords "
                "(single words, lowercase). Avoid function words; these are the topics of interest of the user; prefer specific nouns (e.g., 'oak', 'garden', 'dogs', 'elephants'). "
                "Return ONLY a JSON array of unique keywords (strings), no explanations.\n"
                f"INPUT: {json.dumps(raw_topics, ensure_ascii=False)}\nOUTPUT:"
            )
            data = self.dialog_manager.request_from_gpt(system_prompt=prompt)
            if not isinstance(data, list):
                raise ValueError("GPT did not return a JSON list")
            out, seen = [], set()
            for item in data:
                if not isinstance(item, str):
                    continue
                w = re.sub(r"[^A-Za-z]+", "", item.lower())
                if len(w) > 2 and w not in seen:
                    out.append(w);
                    seen.add(w)
            return out or _heuristic(raw_topics)
        except Exception:
            return _heuristic(raw_topics)

    def ask_llm(self, user_prompt, context_messages, system_prompt):
        return self.dialog_manager.request_from_gpt(user_prompt, context_messages, system_prompt)
