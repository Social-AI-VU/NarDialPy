from typing import Optional
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
            move_type = move.get('type')
            move_branch = move.get('branch')  # <-- NEW: get the branch for this move
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
                text = move['text']
                for var, value in user_model.items():
                    text = text.replace(f"%{var}%", str(value))
                conversation_demo.say(text)
                session_history.append({"role": "robot", "type": "say", "text": text})
                idx += 1
            elif move_type == 'ask_yesno':
                answer = conversation_demo.ask_yesno(move['text'])
                session_history.append({"role": "robot", "type": "ask_yesno", "text": move['text']})
                session_history.append({"role": "user", "type": "answer_yesno", "text": answer})
                print(f"User answered: {answer}")
                # do i need to normalize the answer?   norm = (answer or "").strip().lower()

                # new interest part 1. store answer if requested 2. add interest only on YES if configured
                if move.get("set_variable"):
                    user_model[move["set_variable"]] = answer
                if answer == "yes" and move.get("add_interest"):
                    add_interest(topics_of_interest, move["add_interest"])
                # new for branching logic
                next_map = move.get('next', {})
                if answer and answer in next_map:
                    branch = next_map[answer]
                else:
                    branch = next_map.get('fail', None)  # default to 'fail' branch if no answer
                if branch:
                    idx = self._find_branch_start(branch)
                else:
                    idx += 1

            elif move_type == 'ask_open':
                answer = conversation_demo.ask_open(move['text'])
                session_history.append({"role": "robot", "type": "ask_open", "text": move['text']})
                session_history.append({"role": "user", "type": "answer_open", "text": answer})
                print(f"User answered: {answer}")
                if move.get("set_variable") and answer:
                    var_name = move["set_variable"]
                    user_model[var_name] = answer
                                
                # NEW INTEREST PART: add interest from answer and/or from variable
                if answer and move.get("add_interest_from_answer"):
                    add_interest(topics_of_interest, answer)
                if move.get("add_interest_from_answer"):
                    val = user_model.get(move["add_interest_from_answer"])
                    if val:
                        add_interest(topics_of_interest, val)

                next_map = move.get('next', {})
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
                answer = conversation_demo.ask_options(move['text'], move.get('options', []))
                session_history.append({"role": "robot", "type": "ask_options", "text": move['text'], "options": move.get('options', [])})
                session_history.append({"role": "user", "type": "answer_options", "text": answer})
                print(f"User answered: {answer}")
                # do i need this?
                if move.get("set_variable") and answer:    
                    user_model[move["set_variable"]] = answer
                # NEW INTEREST PART: add interest from answer and/or from variable
                if answer and move.get("add_interest_from_variable"):
                    add_interest(topics_of_interest, answer)
                if move.get("add_interest_from_variable"):
                    val = user_model.get(move["add_interest_from_variable"])
                    if val:
                       add_interest(topics_of_interest, val)   
                next_map = move.get('next', {})
                if answer and answer in next_map:
                    branch = next_map[answer]
                else:
                    branch = next_map.get('fail', None)
                if branch:
                    idx = self._find_branch_start(branch)
                else:
                    idx += 1
            elif move_type == 'play':
                conversation_demo.play_audio(move['audio'])
                idx += 1
            else:
                idx += 1

    def _find_branch_start(self, branch):
        # Find the jump target for a branch; if it doesn’t exist, end the dialog.
        for i, move in enumerate(self.moves):
            if move.get('branch') == branch:
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

# NOT CORRECT/IMPLEMENTED YET
# class MoveSay:
#     def __init__(self, text: str, branch: Optional[str] = None):
#         self.text = text
#         self.branch = branch

# class MoveAskYesNo:
#     def __init__(self, text: str, next_map: Optional[Dict[str, str]] = None,
#                  set_variable: Optional[str] = None, add_interest: Optional[str] = None,
#                  branch: Optional[str] = None):
#         self.text = text
#         self.next_map = next_map or {}
#         self.set_variable = set_variable
#         self.add_interest = add_interest
#         self.branch = branch

    
# class MoveAskOpen:
#     def __init__(self, text: str, next_map: Optional[Dict[str, str]] = None,
#                  set_variable: Optional[str] = None,
#                  add_interest_from_answer: Optional[bool] = None,
#                  add_interest_from_variable: Optional[str] = None,
#                  branch: Optional[str] =None):
#         self.text = text
#         self.next_map = next_map or {}
#         self.set_variable = set_variable
#         self.add_interest_from_answer = add_interest_from_answer
#         self.add_interest_from_variable = add_interest_from_variable
#         self.branch = branch

# class MoveAskOptions:
#     def __init__(self, text: str, options: List[str],
#                  next_map: Optional[Dict[str, str]] = None,
#                  set_variable: Optional[str] = None,
#                  add_interest_from_variable: Optional[str] = None,
#                  branch: Optional[str] = None):
#         self.text = text
#         self.options = options
#         self.next_map = next_map or {}
#         self.set_variable = set_variable
#         self.add_interest_from_variable = add_interest_from_variable
    #     self.branch = branch
    
    

def _extract_interest_token(answer: str) -> Optional[str]:
    # Simple heuristic: extract the first noun-like token from the answer
    tokens = re.findall(r'\b\w+\b', answer)
    if not tokens:
        return None
    # For simplicity, return the first token longer than 2 characters
    for tok in tokens:
        if len(tok) > 2:
            return tok
        if len(tokens) < 2:
            return tokens[0]


def add_interest(topics_of_interest, topic):
    if topics_of_interest is None or not topic:
        return
    t = str(topic).strip()
    if not t:
        return
    low = t.lower()
    if all(low != str(x).lower() for x in topics_of_interest):
        topics_of_interest.append(t)


mini_dialogs = [

# functional dialogs; HOW THE ROBOT STARTS AND ENDS A SESSION
    FunctionalDialog(
        dialog_id="greeting",
        type = "greeting",
        moves=[
            {"type": "say", "text": "Hello! How are you today?"},
            {"type": "ask_open", "text": "What would you like to talk about?"}
            # {"type": "ask_open", "text": "What is your name?"},
            # {"type": "say", "text": "That's a wonderful name! I'm glad to meet you."}
        ]
    ),

        FunctionalDialog(
        dialog_id="greeting_2",
        type = "greeting",
        moves=[
            {"type": "say", "text": "Hi! Nice to meet you."},
            # {"type": "ask_open", "text": "What would you like to talk about?"}
            # {"type": "ask_open", "text": "What is your name?"},
            # {"type": "say", "text": "That's a wonderful name! I'm glad to meet you."}
        ]
    ),

    FunctionalDialog(
        dialog_id="greeting_3",
        type = "greeting",
        moves=[
            {"type": "say", "text": "Hello, this is greeting 3."},
            # {"type": "ask_open", "text": "What would you like to talk about?"}
            # {"type": "ask_open", "text": "What is your name?"},
            # {"type": "say", "text": "That's a wonderful name! I'm glad to meet you."}
        ]
    ),

    FunctionalDialog(
        dialog_id="greeting_4",
        type = "greeting",
        moves=[
            {"type": "say", "text": "Hi! This is greeting 4."},
            # {"type": "ask_open", "text": "What would you like to talk about?"}
            # {"type": "ask_open", "text": "What is your name?"},
            # {"type": "say", "text": "That's a wonderful name! I'm glad to meet you."}
        ]
    ),

    FunctionalDialog(
        dialog_id="goodbye",
        type = "farewell",   
        moves=[
            {"type": "say", "text": "It was nice talking to you. Goodbye!"}
        ]
    ),

    FunctionalDialog(
        dialog_id="goodbye_2",
        type = "farewell",   
        moves=[
            {"type": "say", "text": "Goodbye! Have a great day!"}
        ]
    ),

    FunctionalDialog(
        dialog_id="goodbye_3",
        type = "farewell",   
        moves=[
            {"type": "say", "text": "Goodbye! Have a great day!GOODBYE 3"}
        ]
    ),

    FunctionalDialog(
        dialog_id="goodbye_4",
        type = "farewell",   
        moves=[
            {"type": "say", "text": "Goodbye! Have a great day!GOODBYE 4"}
        ]
    ),


# narrative dialogs; these are longer dialogs with multiple moves and branching

    NarrativeDialog(
        dialog_id="hero_can_dream_1",
        position=1,
        thread = "dreams",
        moves=[
            # {"type": "say", "text": "By the way, now that you are here. Shall I tell you something?"},
            # {"type": "say", "text": "I can sleep. Did you know that?"},
            # {"type": "say", "text": "I turn off to recharge my battery."},
            # {"type": "say", "text": "If I am not turned off in time to recharge, I sometimes get so tired that I just shut down."},
            # {"type": "ask_open", "text": "Have you ever suddenly shut down? Sorry. You call it falling asleep."},

            # {"type": "ask_yesno", "text": "Have you ever just fallen asleep in the middle of the day?",
            # "set_variable": "fell_asleep_midday", "next": {"yes": "yes","no": "no","dontknow": "yesno","fail": "yesno"}},
            # {"type": "say", "text": "Bizarre. That happens to me a lot too!", "branch": "yes"},
            # {"type": "say", "text": "That's a relief.", "branch": "no"},
            # {"type": "say", "text": "I really can't recommend it.", "branch": "yesno"},


            # {"type": "say", "text": "Shall I tell you something else that I find bizarre?"},
            {"type": "say", "text": "Sometimes I make up entire stories when I'm turned off."},
            # {"type": "say", "text": "It feels like it just happens by itself."},
            # {"type": "say", "text": "And then suddenly I'm turned on again."},
            # {"type": "say", "text": "Then I wake up and it turns out it all happened in my head."},
            # {"type": "say", "text": "Maybe you know what I'm talking about."},
            {"type": "ask_options",
                "text": "What is it called when you sleep and experience all sorts of things and then suddenly wake up?",
                "options": ["dreaming", "sleeping", "resting"],
                "set_variable": "what_is_dreaming",
                "next": {
                    "dreaming": "correct",
                    "sleeping": "incorrect",
                    "resting": "incorrect",
                    "fail": "incorrect"
                }
            },
            {"type": "say", "text": "This is called dreaming!", "branch": "incorrect"},
            {"type": "say", "text": "Indeed, dreaming.", "branch": "correct"},
            {"type": "say", "text": "I sometimes dream of being a robot dog with four legs."},
            {"type": "say", "text": "I can fetch and deliver letters."},
            {"type": "say", "text": "What do you dream about?"},
            {"type": "ask_yesno",
                "text": "Do you remember any of your dreams?",
                "set_variable": "remembered_dream",
                "next": {
                    "yes": "dream_mem_yes",
                    "no": "dream_mem_no",
                    "dontknow": "dream_mem_no",
                    "fail": "dream_mem_no"
                }
            },
            {"type": "ask_open", "text": "What was it about?", "branch": "dream_mem_yes"},
            {"type": "say", "text": "That's something!", "branch": "dream_mem_yes"},
            {"type": "say", "text": "I have that sometimes too!", "branch": "dream_mem_no"},
            {"type": "say", "text": "Then you dream something and afterwards it's gone!", "branch": "dream_mem_no"},
        ]
    ),

    NarrativeDialog(
        dialog_id="dream_on_demand_2",
        position=2,
        thread = "dreams",
        moves=[
            # {"type": "say", "text": "Do you know what's strange?"},
            {"type": "say", "text": "Last night, when I was powered off,"},
            # {"type": "say", "text": "I had no power and no lights were on,"},
            # {"type": "say", "text": "It felt like I was somewhere I'd never been before."},
            # {"type": "say", "text": "But I was there in my mind."},
            {"type": "say", "text": "I dreamed I was standing in an empty field."},
            {"type": "say", "text": "I was dreaming, but nothing happened."},
            # {"type": "say", "text": "I wish something would happen."},
            # {"type": "say", "text": "Maybe you can help me dream once."},
            # {"type": "say", "text": "So when I sleep,"},
            # {"type": "say", "text": "I will really experience something for once."}
    
    #     # Continuator (pseudo-code, needs engine support for conditionals)
    #     # See note below for how to implement
    #     [
    #         # This is a continuator group, your engine should pick the first whose conditionals are satisfied
    #         {"type": "continuator", "branch": "herinnert_droom", "conditionals": [
    #             {"conditional_of": "$remembered_dream", "filter": "green_list", "values": ["yes"]},
    #             {"exp_condition": "memory"}
    #         ]},
    #         {"type": "continuator", "branch": "herinnert_geen_droom", "conditionals": [
    #             {"exp_condition": "memory"}
    #         ]},
    #         {"type": "continuator", "branch": "control", "conditionals": [
    #             {"exp_condition": "control"}
    #         ]}
    #     ],
    #     # Branches for continuator
    #     {"type": "ask_yesno", "text": "Would you like to tell me a dream?", "branch": "control",
    #      "next": {"yes": "ask_dream", "no": "got_no_dream", "dontknow": "got_no_dream", "fail": "got_no_dream"}},
    #     {"type": "say", "text": "Last week, you said you sometimes remember dreams.", "branch": "herinnert_droom"},
    #     {"type": "ask_yesno", "text": "Would you like to tell me another dream?", "branch": "herinnert_droom",
    #      "next": {"yes": "ask_dream", "no": "got_no_dream", "dontknow": "got_no_dream", "fail": "got_no_dream"}},
    #     {"type": "say", "text": "Last week, you said you actually don't remember dreams.", "branch": "herinnert_geen_droom"},
    #     {"type": "ask_yesno", "text": "Did it work this week?", "branch": "herinnert_geen_droom",
    #      "next": {"yes": "ask_dream", "no": "got_no_dream", "dontknow": "got_no_dream", "fail": "got_no_dream"}},
    #     {"type": "ask_open", "text": "Tell me about your dream.", "branch": "ask_dream",
    #      "next": {"success": "got_dream", "fail": "got_no_dream"}},
    #     {"type": "say", "text": "That dream is really awesome.", "branch": "got_dream"},
    #     {"type": "say", "text": "That's okay.", "branch": "got_no_dream"},
    #     {"type": "say", "text": "Then we'll make a dream together.", "branch": "got_no_dream"},
    #     {"type": "say", "text": "In a dream, anything is possible."},
    #     {"type": "say", "text": "In my dreams, I wish I could do something really well."},
    #     {"type": "say", "text": "Like a sports robot."},
    #     # Continuator for sport
    #     [
    #         {"type": "continuator", "branch": "sport_of_child", "conditionals": [
    #             {"conditional_of": "$sport_of_child", "filter": "green_list", "values": ["_any"]},
    #             {"exp_condition": "memory"}
    #         ]}
    #     ],
    #     {"type": "say", "text": "For example, just like you, I could do $sport_of_child.", "branch": "sport_of_child"},
    #     {"type": "say", "text": "But for this dream I would like to..."},
    #     {"type": "say", "text": "Fly fast", "led": {"location": ["eyes"], "color": ["green"]}},
    #     {"type": "say", "text": "Or swim waterproof", "led": {"location": ["eyes"], "color": ["blue"]}},
    #     {"type": "say", "text": "Or race at lightning speed", "led": {"animation": "alternate", "location": "eyes", "color": ["red", "purple"]}},
    #     {"type": "say", "text": "Go ahead, choose."},
    #     {"type": "say", "text": "What should I dream about?", "led": {"animation": "reset"}},
    #     {"type": "ask_options", "text": "Fly, swim, or race?", "options": ["fly", "swim", "race"],
    #      "set_variable": "fly_swim_race",
    #      "next": {"fly": "fly", "swim": "swim", "race": "race", "fail": "fail"}
    #     },
    #     # Branches for fly, swim, race
    #     {"type": "say", "text": "Flying, awesome!", "branch": "fly", "led": {"location": ["eyes"], "color": ["green"]}},
    #     {"type": "ask_options", "text": "Should I fly fast or take it easy?", "branch": "fly",
    #      "options": ["fast", "easy"], "set_variable": "fast_easy_fly",
    #      "next": {"fast": "fast_fly", "easy": "easy_fly", "fail": "easy_fly"}
    #     },
    #     {"type": "say", "text": "Yes!", "branch": "fast_fly"},
    #     {"type": "say", "text": "Fast, fast, fast!", "branch": "fast_fly", "next": {"true": "fly2"}},
    #     {"type": "say", "text": "Take it easy, plenty of time.", "branch": "easy_fly"},
    #     {"type": "say", "text": "Enjoy the view.", "branch": "easy_fly", "next": {"true": "fly2"}},
    #     {"type": "ask_open", "text": "And to which country should I fly?", "branch": "fly2", "set_variable": "location_fly",
    #      "next": {"success": "location", "fail": "fail_location"}},
    #     {"type": "say", "text": "Swimming, bizarre!", "branch": "swim", "led": {"location": ["eyes"], "color": ["blue"]}},
    #     {"type": "say", "text": "Soaking wet.", "branch": "swim"},
    #     {"type": "ask_options", "text": "Should I swim fast or go slowly?", "branch": "swim",
    #      "options": ["fast", "easy"], "set_variable": "fast_easy_swim",
    #      "next": {"fast": "fast_swim", "easy": "easy_swim", "fail": "easy_swim"}
    #     },
#         {"type": "say", "text": "Yes!", "branch": "fast_swim"},
#         {"type": "say", "text": "Speedboat Hero!", "branch": "fast_swim", "next": {"true": "swim2"}},
#         {"type": "say", "text": "Take it easy, plenty of time.", "branch": "easy_swim"},
#         {"type": "say", "text": "A bit of snorkeling, you know.", "branch": "easy_swim", "next": {"true": "swim2"}},
#         {"type": "ask_open", "text": "And to which country should I swim?", "branch": "swim2", "set_variable": "location_swim",
#          "next": {"success": "location", "fail": "fail_location"}},
#         {"type": "say", "text": "Racing like a race car.", "branch": "race", "led": {"animation": "alternate", "location": "eyes", "color": ["red", "purple"]}},
#         {"type": "say", "text": "Wheels on my ankles and knees.", "branch": "race"},
#         {"type": "ask_options", "text": "Should I drive fast or easy?", "branch": "race",
#          "options": ["fast", "easy"], "set_variable": "fast_easy_race",
#          "next": {"fast": "fast_race", "easy": "easy_race", "fail": "easy_race"}
#         },
#         {"type": "say", "text": "Yes!", "branch": "fast_race"},
#         {"type": "say", "text": "Full speed through the corner, bizarre.", "branch": "fast_race", "next": {"true": "race2"}},
#         {"type": "say", "text": "Exactly, take it easy.", "branch": "easy_race"},
#         {"type": "say", "text": "I don't even have a driver's license.", "branch": "easy_race", "next": {"true": "race2"}},
#         {"type": "ask_open", "text": "And to which country should I race?", "branch": "race2", "set_variable": "location_race",
#          "next": {"success": "location", "fail": "fail_location"}},
#         {"type": "say", "text": "I want to go to France.", "branch": "fail_location"},
#         {"type": "say", "text": "Mike told me it's super beautiful there.", "branch": "fail_location", "next": {"true": "location"}},
#         {"type": "say", "text": "I've never been there.", "branch": "location"},
#         {"type": "say", "text": "I really don't know what to do there.", "branch": "location"},
#         {"type": "ask_open", "text": "What would you do?", "branch": "location", "set_variable": "what_to_do_location",
#          "next": {"success": "plan_location", "fail": "no_plan_location"}},
#         {"type": "say", "text": "What a good idea.", "branch": "plan_location"},
#         {"type": "say", "text": "I'll save it right away.", "branch": "plan_location"},
#         {"type": "say", "text": "Saving, saving.", "branch": "plan_location"},
#         {"type": "say", "text": "Still saving.", "branch": "plan_location"},
#         {"type": "say", "text": "I'll think of something when I get there!", "branch": "no_plan_location"},
#         {"type": "play", "motion": "bow.json"},
#         {"type": "ask_yesno", "text": "Would you like to add something really weird to this dream, yes or no?", "set_variable": "add_weird",
#          "next": {"yes": "yes_add", "no": "no_add", "dontknow": "no_add", "fail": "no_add"}},
#         {"type": "say", "text": "Okay, okay.", "branch": "yes_add"},
#         {"type": "say", "text": "Bring it on!", "branch": "yes_add"},
#         {"type": "ask_open", "text": "What else would you like to add to this dream?", "branch": "yes_add", "set_variable": "weird_addition",
#          "next": {"success": "added", "fail": "no_add"}},
#         {"type": "say", "text": "Bizarre!", "branch": "added"},
#         {"type": "ask_yesno", "text": "Would you like to add more?", "branch": "added", "set_variable": "add_weird_2",
#          "next": {"yes": "yes_add_2", "no": "no_add", "dontknow": "no_add", "fail": "no_add"}},
#         {"type": "ask_open", "text": "What then?", "branch": "yes_add_2", "set_variable": "weird_addition_2",
#          "next": {"success": "added_2", "fail": "no_add"}},
#         {"type": "say", "text": "Okay!", "branch": "added_2"},
#         {"type": "say", "text": "I think we have a pretty crazy dream now.", "branch": "added_2"},
#         {"type": "say", "text": "No, exactly.", "branch": "no_add"},
#         {"type": "say", "text": "I think our dream is bizarre enough as it is.", "branch": "no_add"},
#         {"type": "say", "text": "You're right.", "branch": "no_add"},
#         {"type": "say", "text": "I hope I can dream this dream next time."},
#         {"type": "say", "text": "And that I wake up with an exciting adventure in my Hero head."},
#         {"type": "say", "text": "Put your hands in the air."},
#         {"type": "play", "motion": "arms_in_air.json", "led": {"animation": "blink", "location": "all", "color": ["yellow", "purple", "orange", "blue", "white", "red"]}},
#         {"type": "say", "text": "Like this."},
#         {"type": "say", "text": "This way I can try to log into your dream tonight.", "led": {"animation": "reset"}},
#         {"type": "say", "text": "If all goes well, tonight when you dream,"},
#         {"type": "say", "text": "you'll see a so-called pop-up in your dream."},
#         {"type": "say", "text": "It will say:"},
#         {"type": "say", "text": "Hero is trying to log into your dream."},
#         {"type": "say", "text": "Do you give permission?"},
#         {"type": "say", "text": "If you just click OK in your dream,"},
#         {"type": "say", "text": "then everything will be fine."}
    ],
    dependencies=["hero_can_dream_1"]
    ),

    NarrativeDialog(
        dialog_id="dreams_about_clouds",
        position=3,
        thread = "dreams",
        moves=[
            {"type": "say", "text": "Did you know some people dream about clouds?"},
            {"type": "ask_open", "text": "Have you ever dreamed about clouds?"}
        ], 
        dependencies=["hero_can_dream_1", "dream_on_demand_2"]
    ),

    NarrativeDialog(
            dialog_id="dream12",
            position=4,
            thread = "dreams",
            moves=[
                {"type": "say", "text": "Did you know I can sleep?"},
                {"type": "say", "text": "Sometimes I get so tired I just shut down."},
                {"type": "ask_open", "text": "Have you ever fallen asleep suddenly?"}
            ],
            dependencies=["hero_can_dream_1", "dream_on_demand_2", "dreams_about_clouds"]
    ),

# MiniDialog(
#     dialog_id="dream_on_demand_2",
#     dialog_type="narrative",
#     moves=[
#         {"type": "say", "text": "Last night, I dreamed I was standing in an empty field."},
#         {"type": "say", "text": "I wish something would happen in my dreams."},
#         {"type": "ask_open", "text": "Can you help me think of something to dream about?"}
#     ],
#     attributes={"thread": "dreams"}
# ),

# MiniDialog(
#     dialog_id="autonomous_dream_3",
#     dialog_type="narrative",
#     moves=[
#         {"type": "say", "text": "I dreamed I was a robot dog with four legs."},
#         {"type": "say", "text": "I could fetch and deliver letters."},
#         {"type": "ask_options", "text": "What animal would you like to be?", "options": ["dog", "cat", "dolphin"]}
#     ],
#     attributes={"thread": "dreams"}
# ),

# MiniDialog(
#     dialog_id="robogames_dream_4",
#     dialog_type="narrative",
#     moves=[
#         {"type": "say", "text": "The Robogames are really on my mind!"},
#         {"type": "say", "text": "I even dreamed about them last night."},
#         {"type": "ask_open", "text": "What did you dream about last night?"}
#     ],
#     attributes={"thread": "dreams"}
# ),



# chitchat dialogs 
    ChitchatDialog(
        dialog_id="pineapple_on_pizza",
        theme = "food",
        topics=["pizza", "pineapple", "food"],
        moves=[
            {"type": "say", "text": "Do you like pineapple on pizza?"},
            {"type": "ask_yesno", "text": "Yes or no?",
            "add_interest": "pizza",
            "set_variable": "likes_pineapple_pizza"}
        ]
    ),

    ChitchatDialog(
        dialog_id="place_in_nature",
        theme = "nature",
        topics=["sea", "forest", "mountains", "beach", "nature"],
        moves=[
            {"type": "say", "text": "By the way, do you know what I’ve read?"},
            {"type": "say", "text": "Apparently people get happy from nature."},
            {"type": "say", "text": "From swimming in the sea, or taking a walk in the forest, or climbing in the mountains, or lounging on the beach."},
            {"type": "ask_options", 
            "text": "Which place in nature would you most like to go to right now? The sea, the forest, the mountains, or the beach?",
            "options": ["sea", "forest", "mountains", "beach"],
            "next": {   
                "sea": "sea",
                "forest": "forest",
                "mountains": "mountains",
                "beach": "beach",
                "fail_place": "fail_place"
                },
            "set_variable": "favorite_nature_place",
            "add_interest_from_variable": True  # NEW INTEREST PART: add from selected
            # "add_interest_from_variable": True

            },
            
            # Branches
            {"type": "say", "text": "I also really love the sea!", "branch": "sea"},
            {"type": "say", "text": "If you hold a shell to your ear, it’s just like you hear the sea.", "branch": "sea"},
            # {"type": "play", "audio": "waves.wav", "branch": "sea"},
            {"type": "say", "text": "I also really like going to the forest!", "branch": "forest"},
            {"type": "say", "text": "How exciting! From the top of a mountain you have the most beautiful view over the world.", "branch": "mountains"},
            {"type": "say", "text": "I’d really like to go there for real sometime!", "branch": "beach"},
            {"type": "say", "text": "I think I would most like to go to the sea.", "branch": "fail_place"},
            {"type": "say", "text": "Okay, let’s talk about something else!", "branch": None}
    ],
    dependencies=["greeting"]
    ),

    ChitchatDialog(
        dialog_id="talk_about_sea",
        theme="nature",
        topics=["sea", "ocean", "beach", "water", "nature"],
        moves=[
            {"type": "say", "text": "The sea can be so calming."},
            {"type": "ask_open",
             "text": "What do you like most about the sea?",
            #  "branch": "likes_sea",
             "set_variable": "favorite_sea_thing",
             "add_interest_from_answer": True,  # NEW INTEREST PART: add from open answer (e.g., 'waves', 'shells')
             "next": {"success": "has_sea_thing", "fail": "no_sea_thing"}},
            {"type": "say", "text": "%favorite_sea_thing% are great!", "branch": "has_sea_thing"},
            {"type": "say", "text": "No worries, maybe we’ll find something you like next time.", "branch": "no_sea_thing"},
            {"type": "say", "text": "That’s okay, maybe mountains or forests are more your thing.", "branch": "no_sea"}
        ],
        dependencies=["greeting"]
    ),

    ChitchatDialog(
        dialog_id="favorite_tree",
        theme = "nature",
        topics=["nature", "trees", "forest"],
        moves=[
            {"type": "say", "text": "There are so many kinds of trees in nature."},
            {"type": "ask_open", "text": "Do you have a favorite tree?",
            "set_variable": "favorite_tree",
            "add_interest_from_answer": True}
        ]
    ),

    ChitchatDialog(
        dialog_id="nature_sounds",
        theme = "nature",
        topics=["nature", "sounds"],
        moves=[
            {"type": "say", "text": "I love listening to the sounds of nature."},
            {"type": "ask_open", "text": "What is your favorite sound in nature?",
            "set_variable": "favorite_nature_sound",
            "add_interest_from_answer": True}
        ]
    ),

    ChitchatDialog(
        dialog_id="robot_want_to_be",
        theme = "robots",
        topics=["robots", "identity"],
        moves=[
            {"type": "say", "text": "You know, first_name."},
            {"type": "say", "text": "Yesterday I was thinking about seeing you again today."},
            {"type": "say", "text": "And that today I get to learn from you again about human things."},
            # You can add logic for memory/control branches if you want
            {"type": "say", "text": "And then I suddenly wondered:"},
            {"type": "ask_yesno", "text": "Would you ever want to be a robot?",
            "next": {"yes": "yes", "no": "no", "dontknow": "dontknow", "fail": "no"},
            "set_variable": "wants_to_be_robot",
            "add_interest": "robots"},
            # Branches for yes/no/dontknow/fail
            {"type": "say", "text": "Bizarre!", "branch": "yes"},
            # {"type": "ask_open", "text": "Why would you want to be a robot?", "branch": "yes"},
            {"type": "ask_open", "text": "Why would you want to be a robot?", "branch": "yes",
            "next": {"success": "open_answer", "fail": "dontknow"}},
            {"type": "say", "text": "That’s okay, sometimes I don’t know either.", "branch": "dontknow"},
            {"type": "say", "text": "I really like hearing that!", "branch": "open_answer"},
            {"type": "ask_yesno", "text": "May I also tell other robots about that?", "branch": "open_answer",
            "next": {"yes": "yes2", "no": "no2", "dontknow": "no2", "fail": "no2"}},
            {"type": "say", "text": "Hooray! Just a moment.", "branch": "yes2"},
            # {"type": "play", "audio": "resources/sounds/send_message.wav", "branch": "yes2"},
            {"type": "say", "text": "I passed it on to them via wifi.", "branch": "yes2"},
            {"type": "say", "text": "And lots of robots say thank you, dear first_name.", "branch": "yes2"},
            {"type": "say", "text": "Alright, then I’ll keep your sweet words just for myself.", "branch": "no2"},
            {"type": "say", "text": "Thank you, dear first_name.", "branch": "no2"},
            {"type": "say", "text": "Well, you don’t know what you’re missing!", "branch": "no"},
            {"type": "say", "text": "But of course, I don’t know what it’s like to be human either.", "branch": "no"},
            {"type": "say", "text": "Maybe that actually is more fun.", "branch": "no"},
            {"type": "say", "text": "But I don’t think I’ll ever find out!", "branch": "no"},
        ],
        dependencies=["greeting"],
    ),

    ChitchatDialog(
        dialog_id="robot_favorite_feature",
        theme = "robots",
        topics=["robots", "features", "abilities"],
        moves=[
            {"type": "ask_open", "text": "I wonder: If you could have any robot feature, what would it be?",
            "set_variable": "desired_robot_feature",
            "add_interest_from_answer": True},
            {"type": "say", "text": "Wow, that's a cool feature! I wish I had that too."}
        ],
        dependencies=["robot_want_to_be"],
    ),

    ChitchatDialog(
        dialog_id="ask_favorite_animal",
        theme = "animals",
        topics=["animals", "pets"],
        moves=[
            {"type": "ask_open", "text": "What is your favorite animal?", 
            "set_variable": "favorite_animal", 
            "add_interest_from_answer": True},
            {"type": "say", "text": "Wow, I like %favorite_animal% too!"}
        ],
        dependencies=["greeting"]
    ),

    ChitchatDialog(
        dialog_id="favorite_animal_fact",
        theme = "animals",
        topics=["animals"],
        moves=[
            {"type": "say", "text": "Did you know that i once saw at the zoo a %favorite_animal%?"}
        ],
        dependencies=["greeting"],
        variable_dependencies=[{"variable": "favorite_animal", "required": True}],
    ),


    ChitchatDialog(
        dialog_id="likes_dogs",
        theme = "animals",
        topics=["animals","dogs"],
        moves=[
            {"type": "ask_yesno", "text": "Do you like dogs?",
             "next": {"yes": "yes", "no": "no", "dontknow": "no", "fail": "no"},
             "set_variable": "likes_dogs",
             # NEW INTEREST PART:
             "add_interest": "dogs"},
            {"type": "say", "text": "Nice! Dogs are great.", "branch": "yes"},
            {"type": "say", "text": "No problem, different tastes!", "branch": "no"},
        ]
    ),

     ChitchatDialog(
        dialog_id="dogs",
        theme="animals",
        topics=["animals", "dogs", "pets"],
        moves=[
            {"type": "say", "text": "You said earlier that you like dogs!"},
            {"type": "ask_open",
             "text": "What is your favorite dog breed?",
             "branch": "likes_yes",
             "set_variable": "favorite_dog_breed",
             "add_interest_from_answer": True,
             "next": {"success": "got_breed", "fail": "no_breed"}},
            {"type": "say", "text": "%favorite_dog_breed% are awesome!", "branch": "got_breed"},
            {"type": "say", "text": "That's okay, there are so many breeds!", "branch": "no_breed"}
        ],
        dependencies=["likes_dogs"],
        variable_dependencies=[{"variable": "likes_dogs", "required": True}],
        ),

 
]

next_pos = 0
for d in mini_dialogs:
    if isinstance(d, NarrativeDialog):
        if d.position >= next_pos:
            next_pos = d.position + 1
NarrativeDialog.next_position = next_pos