from typing import Optional
from typing import Dict, Any, List
import re


class MiniDialog:
    def __init__(self, dialog_id, moves, dependencies=None, variable_dependencies=None):
        """
        dialog_id: str, unique identifier (e.g. 'pineapple_on_pizza')
        moves: list of dicts, each representing a dialog move
        attributes: dict, extra attributes depending on dialog type
        """
        self.dialog_id = dialog_id
        self.moves = moves
        self.dependencies = dependencies or []
        self.variable_dependencies = variable_dependencies or []

    # Helper to read either dict-style or attribute-style moves (supports MoveSay objects)
    @staticmethod
    def _get(move, key, default=None):
        try:
            if isinstance(move, dict):
                return move.get(key, default)
            # Fallback to attribute access for move objects
            return getattr(move, key, default)
        except Exception:
            return default

    @staticmethod  
    def _extract_interest_token(answer: str) -> Optional[str]:  
        # Simple heuristic: extract the first noun-like token from the answer  
        tokens = re.findall(r'\b\w+\b', answer)  
        if not tokens:  
            return None  
        for tok in tokens:  
            if len(tok) > 2:  
                return tok  
        if len(tokens) < 2:  
            return tokens[0]  

    @staticmethod  
    def add_interest(topics_of_interest, topic):  
        if topics_of_interest is None or not topic:  
            return  
        t = str(topic).strip()  
        if not t:  
            return  
        low = t.lower()  
        if all(low != str(x).lower() for x in topics_of_interest):  
            topics_of_interest.append(t)  

    @staticmethod
    def extract_open_value(answer: str) -> str:
        """
        General-purpose cleaner for open answers used with set_variable.
        Heuristics (language-agnostic):
        - If quoted text is present, return the first quoted segment.
        - Otherwise, return the last alphabetic token (e.g., 'zebra' from 'my favorite animal is a zebra').
        - Fallback to trimmed original answer if nothing matches.
        """
        if not answer:
            return ""
        text = str(answer).strip()
        # Prefer explicitly quoted content
        m = re.search(r'["\']([^"\']+)["\']', text)
        if m:
            return m.group(1).strip()
        # Fallback: pick the last alphabetic-ish token
        tokens = re.findall(r"[A-Za-z][A-Za-z\-']+", text)
        if tokens:
            return tokens[-1]
        return text

    def run(self, conversation_demo, session_history=None, user_model=None, topics_of_interest=None): 
        # Execute mini dialogs, sending speech/asks to the device and logging events.
        idx = 0
        branch = None
        if session_history is None:
            session_history = []
        if user_model is None:
            user_model = {}
        while idx < len(self.moves):
            move = self.moves[idx]
            move_type = self._get(move, 'type')
            move_branch = self._get(move, 'branch')  # <-- NEW: get the branch for this move
            if move_branch is not None:
                if move_branch == branch:
                    pass  
                else:
                    idx += 1
                    continue
            if branch is not None:
                if move_branch == branch:
                    pass  
                elif move_branch is None:
                    branch = None
                else:
                    idx += 1
                    continue 
            #If we're in a branch, only process moves with the same branch or None, wrap-up

            if move_type == 'say':
                text = self._get(move, 'text')
                for var, value in user_model.items():
                    text = text.replace(f"%{var}%", str(value))
                conversation_demo.say(text)
                session_history.append({"role": "robot", "type": "say", "text": text})
                idx += 1
            elif move_type == 'ask_yesno':
                answer = conversation_demo.ask_yesno(self._get(move, 'text'))
                session_history.append({"role": "robot", "type": "ask_yesno", "text": self._get(move, 'text')})
                session_history.append({"role": "user", "type": "answer_yesno", "text": answer})
                print(f"User answered: {answer}")
                # do i need to normalize the answer?   norm = (answer or "").strip().lower()

                # new interest part 1. store answer if requested 2. add interest only on YES if configured
                if self._get(move, "set_variable"):
                    user_model[self._get(move, "set_variable")] = answer
                if answer == "yes" and self._get(move, "add_interest"):  
                    self.add_interest(topics_of_interest, self._get(move, "add_interest"))  
                # new for branching logic
                next_map = self._get(move, 'next', {}) or {}
                if answer and answer in next_map:
                    branch = next_map[answer]
                else:
                    branch = next_map.get('fail', None)  # default to 'fail' branch if no answer
                if branch:
                    idx = self._find_branch_start(branch)
                else:
                    idx += 1
            elif move_type == 'ask_open':
                answer = conversation_demo.ask_open(self._get(move, 'text'))
                session_history.append({"role": "robot", "type": "ask_open", "text": self._get(move, 'text')})
                session_history.append({"role": "user", "type": "answer_open", "text": answer})
                print(f"User answered: {answer}")
                if self._get(move, "set_variable") and answer:
                    var_name = self._get(move, "set_variable")
                    user_model[var_name] = self.extract_open_value(answer)
                # Optional automatic personalized follow-up
                if self._get(move, "personalize_followup"):
                    try:
                        age_val = user_model.get('user_age', user_model.get('age', 9))
                        follow = conversation_demo.personalize(robot_input=self._get(move, 'text'), user_age=age_val, user_input=(answer or ""), language="en")
                        if follow:
                            conversation_demo.say(follow)
                            session_history.append({"role": "robot", "type": "personalize", "text": follow, "source_question": self._get(move, 'text')})
                    except Exception as e:
                        # Log but do not break dialog flow
                        session_history.append({"role": "system", "type": "error", "stage": "personalize_followup", "error": str(e)})
                                
                # NEW INTEREST PART: add interest from answer and/or from variable
                if answer and self._get(move, "add_interest_from_answer"):  
                    self.add_interest(topics_of_interest, answer)  
                if self._get(move, "add_interest_from_variable"):  
                    val = user_model.get(self._get(move, "add_interest_from_variable"))  
                    if val:  
                        self.add_interest(topics_of_interest, val)  

                next_map = self._get(move, 'next', {}) or {}
                if next_map:  # Only change branch if next mapping is specified
                    if answer:
                        branch = next_map.get("success", None)
                    else:
                        branch = next_map.get("fail", None)
                    if branch:
                        idx = self._find_branch_start(branch)
                    else:
                        idx += 1
                else:
                    # No next mapping - just continue to next move (preserve current branch)
                    idx += 1
            elif move_type == 'ask_options':
                answer = conversation_demo.ask_options(self._get(move, 'text'), self._get(move, 'options', []) or [])
                session_history.append({"role": "robot", "type": "ask_options", "text": self._get(move, 'text'), "options": self._get(move, 'options', []) or []})
                session_history.append({"role": "user", "type": "answer_options", "text": answer})
                print(f"User answered: {answer}")
                # do i need this?
                if self._get(move, "set_variable") and answer:    
                    user_model[self._get(move, "set_variable")] = answer
                # NEW INTEREST PART: add interest from answer and/or from variable
                if answer and self._get(move, "add_interest_from_variable"):  
                    self.add_interest(topics_of_interest, answer)  
                if self._get(move, "add_interest_from_variable"):  
                    val = user_model.get(self._get(move, "add_interest_from_variable"))  
                    if val:  
                       self.add_interest(topics_of_interest, val)  
                next_map = self._get(move, 'next', {}) or {}
                if answer and answer in next_map:
                    branch = next_map[answer]
                else:
                    branch = next_map.get('fail', None)
                if branch:
                    idx = self._find_branch_start(branch)
                else:
                    idx += 1
            elif move_type == 'play':
                conversation_demo.play_audio(self._get(move, 'audio'))
                idx += 1
            else:
                idx += 1

    def _find_branch_start(self, branch):
        # Find the jump target for a branch; if it doesn’t exist, end the dialog.
        for i, move in enumerate(self.moves):
            if self._get(move, 'branch') == branch:
                return i
        return len(self.moves)  # End if not found


class FunctionalDialog(MiniDialog):
    def __init__(self, dialog_id, moves, type, dependencies=None):
        # Functional dialogs are utility blocks such as greeting and farewell.
        super().__init__(dialog_id, moves, dependencies)
        self.type = type


class NarrativeDialog(MiniDialog):
    def __init__(self, dialog_id, moves, thread, position, dependencies=None, variable_dependencies=None):
        # Narrative dialogs belong to a thread and have an explicit position (order).
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.thread = thread
        self.position = position  


class ChitchatDialog(MiniDialog):  
    def __init__(self, dialog_id, moves, theme,  topics=None, dependencies=None, variable_dependencies=None):
        # Chitchat dialogs are short, theme-based interactions that can be biased by topics.
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.theme = theme
        self.topics = topics or []



