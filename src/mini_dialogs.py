class MiniDialog:
    def __init__(self, dialog_id, dialog_type, moves, attributes=None, dependencies=None, variable_dependencies=None):
        """
        dialog_id: str, unique identifier (e.g. 'pineapple_on_pizza')
        dialog_type: str, one of 'narrative', 'chitchat', 'functional'
        moves: list of dicts, each representing a dialog move
        attributes: dict, extra attributes depending on dialog type
        """
        self.dialog_id = dialog_id
        self.dialog_type = dialog_type
        self.moves = moves
        self.attributes = attributes or {}
        self.dependencies = dependencies or []
        self.variable_dependencies = variable_dependencies or []

    # def run(self, conversation_demo): # WEEK 1
    #     for move in self.moves:
    #         if move['type'] == 'say':
    #             conversation_demo.say(move['text'])
    #         elif move['type'] == 'ask_yesno':
    #             answer = conversation_demo.ask_yesno(move['text'])
    #             print(f"User answered: {answer}")
    #         elif move['type'] == 'ask_open':
    #             answer = conversation_demo.ask_open(move['text'])
    #             print(f"User answered: {answer}")


    def run(self, conversation_demo, session_history=None, user_model=None): 
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
                if "set_variable" in move and answer:
                    var_name = move["set_variable"]
                    user_model[var_name] = answer
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
        for i, move in enumerate(self.moves):
            if move.get('branch') == branch:
                return i
        return len(self.moves)  # End if not found



mini_dialogs = [
    MiniDialog(
        dialog_id="greeting",
        dialog_type="functional",
        moves=[
            {"type": "say", "text": "Hello! How are you today?"},
            {"type": "ask_open", "text": "What would you like to talk about?"}
            # {"type": "ask_open", "text": "What is your name?"},
            # {"type": "say", "text": "That's a wonderful name! I'm glad to meet you."}
        ]
    ),

    MiniDialog(
        dialog_id="pineapple_on_pizza",
        dialog_type="chitchat",
        moves=[
            {"type": "say", "text": "Do you like pineapple on pizza?"},
            {"type": "ask_yesno", "text": "Yes or no?"}
        ],
        attributes={"theme": "food"}
    ),

    MiniDialog(
        dialog_id="hero_can_dream_1",
        dialog_type="narrative",
        moves=[
            {"type": "say", "text": "By the way, now that you are here. Shall I tell you something?"},
            {"type": "say", "text": "I can sleep. Did you know that?"},
            {"type": "say", "text": "I turn off to recharge my battery."},
            {"type": "say", "text": "If I am not turned off in time to recharge, I sometimes get so tired that I just shut down."},
            {"type": "ask_open", "text": "Have you ever suddenly shut down? Sorry. You call it falling asleep."},

            {"type": "ask_yesno", "text": "Have you ever just fallen asleep in the middle of the day?",
            "set_variable": "fell_asleep_midday", "next": {"yes": "yes","no": "no","dontknow": "yesno","fail": "yesno"}},
            {"type": "say", "text": "Bizarre. That happens to me a lot too!", "branch": "yes"},
            {"type": "say", "text": "That's a relief.", "branch": "no"},
            {"type": "say", "text": "I really can't recommend it.", "branch": "yesno"},


            {"type": "say", "text": "Shall I tell you something else that I find bizarre?"},
            {"type": "say", "text": "Sometimes I make up entire stories when I'm turned off."},
            {"type": "say", "text": "It feels like it just happens by itself."},
            {"type": "say", "text": "And then suddenly I'm turned on again."},
            {"type": "say", "text": "Then I wake up and it turns out it all happened in my head."},
            {"type": "say", "text": "Maybe you know what I'm talking about."},
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
            {"type": "say", "text": "Indeed, dreaming. Bizarre.", "branch": "correct"},
            {"type": "say", "text": "A dream."},
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
        ],
        attributes={"thread": "dreams"} 
),

    MiniDialog(
        dialog_id="dreams_about_clouds_1",
        dialog_type="narrative",
        moves=[
            {"type": "say", "text": "Did you know some people dream about clouds?"},
            {"type": "ask_open", "text": "Have you ever dreamed about clouds?"}
        ], 
        attributes={"thread": "dreams"}
    ),
MiniDialog(
    dialog_id="hero_can_dream_1",
    dialog_type="narrative",
    moves=[
        {"type": "say", "text": "Did you know I can sleep?"},
        {"type": "say", "text": "Sometimes I get so tired I just shut down."},
        {"type": "ask_open", "text": "Have you ever fallen asleep suddenly?"}
    ],
    attributes={"thread": "dreams"}
),

MiniDialog(
    dialog_id="dream_on_demand_2",
    dialog_type="narrative",
    moves=[
        {"type": "say", "text": "Last night, I dreamed I was standing in an empty field."},
        {"type": "say", "text": "I wish something would happen in my dreams."},
        {"type": "ask_open", "text": "Can you help me think of something to dream about?"}
    ],
    attributes={"thread": "dreams"}
),

MiniDialog(
    dialog_id="autonomous_dream_3",
    dialog_type="narrative",
    moves=[
        {"type": "say", "text": "I dreamed I was a robot dog with four legs."},
        {"type": "say", "text": "I could fetch and deliver letters."},
        {"type": "ask_options", "text": "What animal would you like to be?", "options": ["dog", "cat", "dolphin"]}
    ],
    attributes={"thread": "dreams"}
),

MiniDialog(
    dialog_id="robogames_dream_4",
    dialog_type="narrative",
    moves=[
        {"type": "say", "text": "The Robogames are really on my mind!"},
        {"type": "say", "text": "I even dreamed about them last night."},
        {"type": "ask_open", "text": "What did you dream about last night?"}
    ],
    attributes={"thread": "dreams"}
),

    MiniDialog(
        dialog_id="place_in_nature",
        dialog_type="chitchat",
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
                }
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
    dependencies=["greeting"],
    attributes={"theme": "nature"}
),

    MiniDialog(
    dialog_id="favorite_tree",
    dialog_type="chitchat",
    moves=[
        {"type": "say", "text": "There are so many kinds of trees in nature."},
        {"type": "ask_open", "text": "Do you have a favorite tree?"}
    ],
    attributes={"theme": "nature"}
),

MiniDialog(
    dialog_id="nature_sounds",
    dialog_type="chitchat",
    moves=[
        {"type": "say", "text": "I love listening to the sounds of nature."},
        {"type": "ask_open", "text": "What is your favorite sound in nature?"}
    ],
    attributes={"theme": "nature"}
),

    MiniDialog(
        dialog_id="robot_want_to_be",
        dialog_type="chitchat",
        moves=[
            {"type": "say", "text": "You know, %first_name%."},
            {"type": "say", "text": "Yesterday I was thinking about seeing you again today."},
            {"type": "say", "text": "And that today I get to learn from you again about human things."},
            # You can add logic for memory/control branches if you want
            {"type": "say", "text": "And then I suddenly wondered:"},
            {"type": "ask_yesno", "text": "Would you ever want to be a robot?",
            "next": {"yes": "yes", "no": "no", "dontknow": "dontknow", "fail": "no"}},
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
            {"type": "say", "text": "And lots of robots say thank you, dear %first_name%.", "branch": "yes2"},
            {"type": "say", "text": "Alright, then I’ll keep your sweet words just for myself.", "branch": "no2"},
            {"type": "say", "text": "Thank you, dear %first_name%.", "branch": "no2"},
            {"type": "say", "text": "Well, you don’t know what you’re missing!", "branch": "no"},
            {"type": "say", "text": "But of course, I don’t know what it’s like to be human either.", "branch": "no"},
            {"type": "say", "text": "Maybe that actually is more fun.", "branch": "no"},
            {"type": "say", "text": "But I don’t think I’ll ever find out!", "branch": "no"},
        ],
        dependencies=["greeting"],
        attributes={"theme": "robots"}

    ),
    
    MiniDialog(
        dialog_id="robot_favorite_feature",
        dialog_type="chitchat",
        moves=[
            {"type": "ask_open", "text": "I wonder: If you could have any robot feature, what would it be?"},
            {"type": "say", "text": "Wow, that's a cool feature! I wish I had that too."}
        ],
        dependencies=["robot_want_to_be"],
        attributes={"theme": "robots"}  
    ),

    MiniDialog(
    dialog_id="ask_favorite_animal",
    dialog_type="chitchat",
    moves=[
        {"type": "ask_open", "text": "What is your favorite animal?", "set_variable": "favorite_animal"},
        {"type": "say", "text": "Wow, I like %favorite_animal% too!"}
    ],
    dependencies=["greeting"],
    attributes={"theme": "animals"}
    ),

    MiniDialog(
    dialog_id="favorite_animal_fact",
    dialog_type="chitchat",
    moves=[
        {"type": "say", "text": "Did you know that i once saw at the zoo a %favorite_animal%? It was so big and strong!"}
    ],
    dependencies=["greeting"],
    variable_dependencies=[{"variable": "favorite_animal", "required": True}],
    attributes={"theme": "animals"}
    ),



    MiniDialog(
        dialog_id="goodbye",   
        dialog_type="functional",
        moves=[
            {"type": "say", "text": "It was nice talking to you. Goodbye!"}
        ]
    )
 
]
