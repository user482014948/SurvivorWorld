"""The Parser

The parser is the module that handles the natural language understanding in
the game. The players enter commands in text, and the parser interprets them
and performs the actions that the player intends.  This is the module with
the most potential for improvement using modern natural language processing.
The implementation that I have given below only uses simple keyword matching.
"""
from typing import TYPE_CHECKING
from collections import defaultdict
import inspect
import textwrap
import re
import json
import tiktoken
import spacy
from jellyfish import jaro_winkler_similarity, levenshtein_distance

from .things import Character
if TYPE_CHECKING:
    from .things import Item, Location
    from src.things.base import Thing
from . import actions
from .utils.general import normalize_name
from src.actions.base import ActionSequence
from .gpt.gpt_helpers import (GptCallHandler,
                              limit_context_length,
                              gpt_get_action_importance,
                              gpt_get_summary_description_of_action,
                              gpt_pick_an_option,
                              get_prompt_token_count,
                              get_token_remainder)
from .agent.memory_stream import MemoryType


class Parser:
    """
    The Parser is the class that handles the player's input.  The player
    writes commands, and the parser performs natural language understanding
    in order to interpret what the player intended, and how that intent
    is reflected in the simulated world.
    """

    def __init__(self, game, echo_commands=False):
        # A list of the commands that the player has issued,
        # and the respones given to the player.
        self.command_history = []
        self.character_histories = defaultdict(list)

        # Build default scope of actions
        self.actions = game.default_actions()

        # Build default scope of blocks
        self.blocks = game.default_blocks()

        # A pointer to the game.
        self.game = game
        self.game.parser = self
        self.perspective = "3rd"
        # Print the user's commands
        self.echo_commands = echo_commands

    def ok(self, command: str, description: str, thing: "Thing"):
        """
        Print a description of a failed command to the console and add to command history
        """
        print(Parser.wrap_text(description))
        self.add_description_to_history(description)

    def fail(self, command: str, description: str, thing: "Thing"):
        """
        Print a description of a failed command to the console
        """
        print(Parser.wrap_text(description))

    @staticmethod
    def wrap_text(text: str, width: int = 80) -> str:
        """
        Keeps text output narrow enough to easily be read
        """
        lines = text.split("\n")
        wrapped_lines = [textwrap.fill(line, width) for line in lines]
        return "\n".join(wrapped_lines)

    def add_command_to_history(self, command: str):
        """Add command strings as <USER> ChatMessages to the game history"""
        message = {"role": "user", "content": command}
        self.command_history.append(message)

    def add_description_to_history(self, description: str):
        """
        Append an evocative description of the game actions to the oracle narrative.

        Args:
            description (str): a description of the actions, outcomes, setting, etc.
        """
        message = {"role": "assistant", "content": description}
        self.command_history.append(message)

    def add_action(self, action: actions.Action):
        """
        Add an Action class to the list of actions a parser can use
        """
        self.actions[action.action_name()] = action

    def add_block(self, block):
        """
        Adds a block class to the list of blocks a parser can use. This is
        primarily useful for loading game states from a save.
        """
        self.blocks[block.__class__.__name__] = block

    def init_actions(self):
        self.actions = {}
        for member in dir(actions):
            attr = getattr(actions, member)
            if inspect.isclass(attr) and issubclass(attr, actions.Action):
                # dont include base class
                if not attr == actions.Action:
                    self.add_action(attr)

    def determine_intent(self, command: str, character: Character):
        """
        This function determines what command the player wants to do.
        Here we have implemented it with a simple keyword match. Later
        we will use AI to do more flexible matching.
        """
        # check which character is acting (defaults to the player)
        # character = self.get_character(command, character)  <-- don't need this if passing in the current character
        command = command.lower()
        if "," in command:
            # Let the player type in a comma separted sequence of commands
            return "sequence"
        elif self.get_direction(command, character.location):
            # Check for the direction intent
            return "direction"
        elif command == "look" or command == "l":
            # when the user issues a "look" command, re-describe what they see
            return "describe"
        elif "examine " in command or command.startswith("x "):
            return "examine"
        elif "take " in command or "get " in command:
            return "take"
        elif "light" in command:
            return "light"
        elif "drop " in command:
            return "drop"
        elif (
            "eat " in command
            or "eats " in command
            or "ate " in command
            or "eating " in command
        ):
            return "eat"
        elif "drink" in command:
            return "drink"
        elif "give" in command:
            return "give"
        elif "attack" in command or "hit " in command or "hits " in command:
            return "attack"
        elif "inventory" in command or command == "i":
            return "inventory"
        elif "quit" in command:
            return "quit"
        else:
            for _, action in self.actions.items():
                special_command = action.action_name()
                if special_command in command:
                    return action.action_name()
        return None

    def parse_action(self, command: str, character: Character) -> actions.Action:
        """
        Routes an action described in a command to the right action class for
        performing the action.
        """
        command = command.lower().strip()
        if command == "":
            return None
        intent = self.determine_intent(command, character)
        if intent in self.actions:
            action = self.actions[intent]
            return action(self.game, command, character)
        elif intent == "direction":
            return actions.Go(self.game, command, character)
        elif intent == "take":
            return actions.Get(self.game, command, character)
        self.fail(command, f"No action found for {command}", character)
        return None

    def parse_command(self, command: str, character: Character):
        # print("\n>", command, "\n", flush=True)
        # add this command to the history
        if self.command_repeated(command):
            print(f"Command {command} was repeated. Possibly mis-labeled as an ActionSequence.")
            return False
        Parser.add_command_to_history(self, command)
        action = self.parse_action(command, character)
        if not action:
            self.fail(command, "No action could be matched from command", character)
            return False
        elif isinstance(action, ActionSequence):
            self.fail(command, 
                      "Command parsed to multiple actions. Try simpler command that attempts ony 1 action.", 
                      character)
            return False
        else:
            return action()
        
    def command_repeated(self, command: str) -> bool:
        if len(self.command_history) == 0:
            return False
        return command == self.command_history[-1]["content"]
    
    @staticmethod
    def split_command(command: str, keyword: str) -> tuple[str, str]:
        """
        Splits the command string into two parts based on the keyword.

        Args:
        command (str): The command string to be split.
        keyword (str): The keyword to split the command string around.

        Returns:
        tuple: A tuple containing the part of the command before the keyword and the part after.
        """
        command = command.lower()
        keyword = keyword.lower()
        # Find the position of the keyword in the command
        keyword_pos = command.find(keyword)

        # If the keyword is not found, return the entire command and an empty string
        if keyword_pos == -1:
            return (command, "")

        # Split the command into two parts
        before_keyword = command[:keyword_pos]
        after_keyword = command[keyword_pos + len(keyword):]

        return (before_keyword, after_keyword)

    def get_character(self, command: str, character: Character) -> Character:
        # ST 3/10 - add character arg for sake of override in GptParser3
        """
        This method tries to match a character's name in the command.
        If no names are matched, it returns the default value.
        """
        command = command.lower()
        # matched_character_name = ""  # JD logical change
        for name in self.game.characters.keys():
            if name.lower() in command:
                return self.game.characters[name]
        return self.game.player
    
    def check_if_character_exists(self, name):
        # First O(1) check for a perfect fit
        if name in self.game.characters:
            return True, name
        # If not exact match, do the more expensive checks
        norm_name = normalize_name(name)
        if not norm_name:
            return False, None
        
        nchar = len(norm_name)
        if nchar <= 2:
            return False, None
        lev_threshold = 1 if nchar < 5 else 2 if nchar < 12 else 3
        try:
            jaro_threshold = max(0.75, ((nchar - 2) / nchar))
        except ZeroDivisionError:
            jaro_threshold = 0.8
        
        for char_name in self.game.characters:
            norm_char_name = normalize_name(char_name)
            if self.is_partial_name(norm_name, norm_char_name):
                return True, char_name
            # Ensure the length ratio doesn't exceed a certain threshold before comparing
            length_ratio = len(norm_char_name) / (len(norm_name) + 0.01)  # Avoid division by zero
            if not (0.5 < length_ratio < 2):  
                continue

            # Perform similarity checks if lengths are reasonably similar
            if jaro_winkler_similarity(norm_char_name, norm_name) > jaro_threshold:
                if levenshtein_distance(norm_char_name, norm_name) < lev_threshold:
                    return True, char_name
        return False, None

    def is_partial_name(self, candidate_name, comparison_name):
        cand_parts = candidate_name.split()
        comp_parts = comparison_name.split()
        if cand_parts[0] == comp_parts[0]:
            return True
        if cand_parts[-1] == comp_parts[-1]:
            return True
        return False

    def get_character_location(self, character: Character) -> "Location":
        return character.location

    def match_item(self, command: str, item_dict: dict[str, "Item"]) -> "Item":
        """
        Check whether the name any of the items in this dictionary match the
        command. If so, return Item, else return None.
        """
        for item_name in item_dict:
            if item_name in command:
                item = item_dict[item_name]
                return item
        return None

    def get_items_in_scope(self, character=None) -> dict[str, "Item"]:
        """
        Returns a list of items in character's location and in their inventory
        """
        if character is None:
            character = self.game.player
        items_in_scope = {}
        for item_name in character.location.items:
            items_in_scope[item_name] = character.location.items[item_name]
        for item_name in character.inventory:
            items_in_scope[item_name] = character.inventory[item_name]
        return items_in_scope

    def get_direction(self, command: str, location: "Location" = None) -> str:
        """
        Converts aliases for directions into its primary direction name.
        """
        command = command.lower()
        if command == "n" or "north" in command:
            return "north"
        if command == "s" or "south" in command:
            return "south"
        if command == "e" or "east" in command:
            return "east"
        if command == "w" or "west" in command:
            return "west"
        if command.endswith("go up"):
            return "up"
        if command.endswith("go down"):
            return "down"
        if command.endswith("go out"):
            return "out"
        if command.endswith("go in"):
            return "in"
        if location:
            for exit in location.connections.keys():
                if exit.lower() in command:
                    return exit
        return None


class GptParser(Parser):
    def __init__(self, game, echo_commands=True, verbose=False):
        super().__init__(game, echo_commands=echo_commands)
        self.verbose = verbose
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        self.nlp = spacy.load('en_core_web_sm')
        self.gpt_handler = self._set_up_gpt()
        self.max_input_tokens = self.gpt_handler.model_context_limit
        self.narrator_turn_limit = 5

    def _set_up_gpt(self):
        model_params = {
            "api_key_org": "Helicone",
            "model": "gpt-4",
            "max_tokens": 400,
            "temperature": 1,
            "top_p": 1,
            "max_retries": 5
        }

        return GptCallHandler(**model_params) 
    
    def get_handler(self):
        if self.gpt_handler:
            return self.gpt_handler
        else:
            self.gpt_handler = self._set_up_gpt()
            return self.gpt_handler

    def gpt_describe(self, 
                     system_instructions, 
                     command_history,
                     extra_description=None
                     ):
        """
        TODO: should the context for each description be more limited to focus on recent actions?
        Generate a description with GPT.  This takes two arguments:
        * The system instructions, which is the prompt that describes 
          how you'd like GPT to behave.
        * The command history - this is a list of previous user input 
          commands and game descriptions. It's given as context to GPT.
        The Parser class manages the command_history via the 
        `add_command_to_history` and `add_description_to_history` functions
        which use the ChatGPT format with commands being assigned role: user,
        and descriptions being assigned role: assistant.
        """
        
        try:
            messages = [{
                "role": "system",
                "content": system_instructions
            }]
            system_count = get_prompt_token_count(content=system_instructions,
                                                  role="system",
                                                  pad_reply=False,
                                                  tokenizer=self.tokenizer)
            # Here, the command history is being stored as a Chat Dict {"role": ..., "content":}
            available_tokens = get_token_remainder(self.max_input_tokens,
                                                   system_count,
                                                   self.gpt_handler.max_tokens)
            
            # Limit the context for the narrator to the last few turns
            narrator_context = command_history[-self.narrator_turn_limit:]
            if extra_description:
                user_description = "".join([
                    "Use the following description as additional context to fulfill your system function. ",
                    "And if the description describes a failed action, provide a helpful embellishment to a user ",
                    "that helps them to learn why their action led to an error. ",
                    f"Description: {extra_description}."
                ])
                narrator_context.append({
                    "role": "user",
                    "content": user_description
                })
            context = limit_context_length(narrator_context, available_tokens)
            messages.extend(context)
            if self.verbose:
                print(json.dumps(messages, indent=2))
            response = self.gpt_handler.generate(messages=messages)
            return response
        except Exception as e:
            return f"Something went wrong with GPT: {e}"
    
    def create_action_statement(self, command: str, description: str, character: Character):
        outcome = f"ACTOR: {character.name}; LOCATION: {character.location.name}, ACTION: {command}; OUTCOME: {description}"
        summary = gpt_get_summary_description_of_action(outcome, call_handler=self.gpt_handler, max_tokens=256)
        return summary

    def extract_keywords(self, text):
        if not text:
            return None
        custom_stopwords = {"he", "it", "i", "you", "she", "they", "we", "us", 
                            "'s", "this", "that", "these", "those", "them"}

        doc = self.nlp(text)
        keys = defaultdict(set)
        for w in doc:
            if w.text.lower() in custom_stopwords:
                continue

            if w.pos_ in ["PROPN"]:
                compounds = [j for j in w.children if j.dep_ == "compound"]
                if compounds:
                    continue
            if "subj" in w.dep_:
                exists, name = self.check_if_character_exists(w.text)
                if exists:
                    keys['characters'].add(name)
                else:
                    keys['misc_deps'].add(w.text)
            if "obj" in w.dep_:
                exists, name = self.check_if_character_exists(w.text)
                if exists:
                    keys['characters'].add(name)
                else:
                    keys['objects'].add(w.text)
        for ent in doc.ents:
            if ent.label_ in ["PERSON", "ORG", "GPE"]:
                exists, name = self.check_if_character_exists(ent.text)
                if exists:
                    keys["characters"].add(name)

        keys = {k: list(v) for k, v in keys.items()}

        return keys
    
    def summarise_and_score_action(self, description, thing, command="look", needs_summary=True, needs_score=True):
        if needs_summary:
            action_statement = self.create_action_statement(command, description, thing)
        else:
            action_statement = description
        if needs_score:
            importance_of_action = gpt_get_action_importance(action_statement,
                                                             call_handler=self.gpt_handler, 
                                                             max_tokens=10,
                                                             top_p=0.25)
        else:
            importance_of_action = 0
        keywords = self.extract_keywords(action_statement)

        return action_statement, importance_of_action, keywords
    
    def add_command_to_history(self, 
                               command, 
                               summary, 
                               keywords, 
                               character, 
                               importance, 
                               success, 
                               type):
        """
        Add a summarized command and outcome to the command history
        Then add memories to character memory

        Args:
            summary (str): a summary of an action and its outcome
            keywords (dict): keywords extracted from the summary
            character (Character): the current character
            success (bool???): the success status of the action
        """
        # This is a user or agent-supplied command so it should be logged as a ChatMessage.user
        super().add_command_to_history(command)
        character.memory.add_memory(round=self.game.round,
                                    tick=self.game.tick,
                                    description=summary.lower(), 
                                    keywords=keywords, 
                                    location=character.location.name, 
                                    success_status=success,
                                    memory_importance=importance, 
                                    memory_type=type,
                                    actor_id=character.id)
        for char in character.chars_in_view:
            char.memory.add_memory(round=self.game.round,
                                   tick=self.game.tick,
                                   description=summary.lower(), 
                                   keywords=keywords, 
                                   location=character.location.name, 
                                   success_status=success,
                                   memory_importance=importance, 
                                   memory_type=type,
                                   actor_id=character.id)

    def ok(self, command: str, description: str, thing: "Thing") -> None:
        """
        Logs a successful command and the description of its outcome.

        Args:
            command (str): the input command given by the character
            description (str): the description of the command's outcome
            character (Character): the current character

        Returns:
            None

        Example: 
            command: "Get the pole"
            description: "The troll got the pole"
            character: troll
        """
        # FIRST: we add summarize the action and send it as a memory to the appropriate characters
        if isinstance(thing, Character):
            summary_of_action, importance_of_action, action_keywords = self.summarise_and_score_action(description, 
                                                                                                       thing,
                                                                                                       command=command)
            
            # Make sure that the Narrator GPT knows about the character names 
            command = f"{thing.name}'s action: {command}"
            self.add_command_to_history(command,
                                        summary_of_action, 
                                        action_keywords, 
                                        thing,  
                                        importance_of_action,
                                        success=True, 
                                        type=MemoryType.ACTION.value)

        # system_instructions = """You are the narrator for a text adventure game. 
        # You create short, evocative descriptions of the scenes in the game.
        # Include descriptions of the items and exits available to the current player."""

        # SECOND: we describe what has happened in the console
        system_instructions = "".join(
            [
                "You are the narrator for a text adventure game. You create short, ",
                "evocative descriptions of the game. The player can be described in ",
                f"the {self.perspective} person, and you should use present tense. ",
                "If the command is 'look' then describe the game location and its characters and items. ",
                "Focus on describing the most recent events."
            ]
        )
        
        # # TODO: I'm commenting this out for now to avoid paying this each time.
        # # It also doesn't seem to add anything aside from a printing/logging a longer statement.
        # response = self.gpt_describe(system_instructions, self.command_history)
        # self.add_description_to_history(response)
        # print(self.wrap_text(response) + '\n')

    def fail(self, command: str, description: str, thing: "Thing"):
        """
        Commands that do not pass all preconditions lead to a failure.
        They are logged by this method. 
        Failed commands are still added to the global command history and 
        to the memories of characters in view.

        Args:
            command (str): The command given by a character
            description (str): a description of the outcome
            thing (things.Thing): an object of type Thing
        """
        
        # SECOND: get a description of the failure to write to the console
        system_instructions = "".join(
            [
                "You are the narrator for a text adventure game. ",
                f"{thing.name} entered a command that failed in the game. ",
                f"Try to help {thing.name} understand why the command failed. ",
                f"Do you will see the last few commands given. {thing.name} attempted the last one and failed. ",
                "Summarize why they failed using only the information provided. ",
                "Do not make up rules of the game that you don't know explicitly."
            ]
        )

        response = self.gpt_describe(system_instructions, self.command_history, extra_description=description)

        # FIRST: we add summarize the FAILED action and send it as a memory to the appropriate characters
        if isinstance(thing, Character):
            print(f"{thing.name} action failed. Adding failure memory to history.")
            # summary_of_action = self.create_action_statement(command, description, thing)
            importance_of_action = gpt_get_action_importance(response,
                                                             call_handler=self.gpt_handler, 
                                                             max_tokens=10,
                                                             top_p=0.25)
            keywords = self.extract_keywords(response)
            
            # Make sure that the Narrator GPT knows about the character names 
            command = f"{thing.name}'s action: {command}"

            # For failures, use the GPT feedback to help guide the agent.
            self.add_command_to_history(command,
                                        response, 
                                        keywords, 
                                        thing,  
                                        importance_of_action,
                                        success=False, 
                                        type=MemoryType.ACTION.value)
            
        if self.verbose:
            print("GPT's Error Description:")
        self.add_description_to_history(response)
        print(self.wrap_text(response) + '\n')

    
class GptParser2(GptParser):
    def __init__(self, game, echo_commands=True, verbose=False):
        super().__init__(game, echo_commands, verbose)
        self.refresh_command_list()

    def refresh_command_list(self):
        # Command descriptions is a dictionary that maps
        # action descriptions and aliases onto action names 
        command_descriptions = {}
        for _, action in self.actions.items():
            description = action.ACTION_DESCRIPTION
            if action.ACTION_ALIASES:
                description += " (can also be invoked with '{aliases}')".format(
                    aliases="', '".join(action.ACTION_ALIASES)
                )
            action_name = action.ACTION_NAME
            if action_name:
                command_descriptions[description] = action_name
        
        self.command_descriptions = command_descriptions
        return self
    
    def determine_intent(self, command, character: Character):
        """
        Instead of the keyword based intent determination, we'll use GPT.
        """
        instructions = "".join(
            [
                "You are the parser for a text adventure game. For a user input, say which ",
                "of the commands it most closely matches. The commands are:",
            ]
        )

        return gpt_pick_an_option(instructions, self.command_descriptions, command, self.gpt_handler, max_tokens=10)


class GptParser3(GptParser2):
    def __init__(self, game, echo_commands=True, verbose=False):
        super().__init__(game, echo_commands, verbose)

    def get_character(
        self, command: str, character: Character = None, hint: str = None, split_words=None, position=None
    ) -> Character:
        """
        This method tries to match a character's name in the command.
        If no names are matched, it defaults to `game.player`. 
        Args:
            hint: A hint about the role of character we're looking for 
                  (e.g. "giver" or "recipent")
            split_words: not needed for our GptParser
            position: not needed for our GptParser
        """ """
        This method tries to match a character's name in the command.
        If no names are matched, it defaults to the player.
        """
        if self.verbose:
            print("Matching a character with GPT.")
        character_descriptions = {}
        for name, character in self.game.characters.items():
            if character.location:
                d = "{name} - {description} (currently located in {location})"
                description = d.format(
                    name=name,
                    description=character.description,
                    location=character.location.name,
                )
            else:
                description = "{name} - {description}".format(
                    name=name, description=character.description
                )
            # if character == self.game.player:
            #     description = "The player: {description}".format(
            #         description=character.description
            #     )

            character_descriptions[description] = character

        instructions = "".join(
            [
                "You are the parser for a text adventure game. For an input command try to ",
                "match the character in the command (if no character is mentioned in the ",
                "command, then default to '{player}').".format(
                    player=self.game.player.name
                ),
            ]
        )
        if hint:
            instructions += f"\nHint: the character you are looking for is the {hint}. "
        instructions += "\n\nThe possible characters are:"

        return gpt_pick_an_option(instructions, character_descriptions, command, call_handler=self.gpt_handler, max_tokens=10)

    def match_item(
        self, command: str, item_dict: dict[str, "Item"], hint: str = None
    ) -> "Item":
        """
        Check whether the name any of the items in this dictionary match the
        command. If so, return Item, else return None.

        Args:
            item_dict: A map from item names to Items (could be a player's 
                       inventory or the items at a location)
            hint: what kind of item we're looking for
        """ """
        Check whether the name any of the items in this dictionary match the
        command. If so, return Item, else return None.
        """
        if self.verbose:
            print("Matching an item with GPT.")
        instructions = "You are the parser for a text adventure game. For an input command try to match the item in the command."
        if hint:
            instructions += f"\nHint: {hint}."
        instructions += "\n\nThe possible items are:"

        item_descriptions = {}
        for name, item in item_dict.items():
            if item.location:
                description = (
                    "{name} - {description} (currently located in {location})".format(
                        name=name,
                        description=item.description,
                        location=item.location.name,
                    )
                )
            else:
                description = "{name} - {description}".format(
                    name=name, description=item.description
                )

            item_descriptions[description] = item
        return gpt_pick_an_option(instructions, item_descriptions, command, call_handler=self.gpt_handler, max_tokens=10)

    def get_direction(self, command: str, location: "Location" = None) -> str:
        """
        Return the direction from `location.connections` which the player
        wants to travel to.
        """
        if self.verbose:
            print("Matching a direction with GPT.")
        instructions = "".join(
            [
                "You are the parser for a text adventure game. For an input command try to ",
                "match the direction in the command. Give the cloest matching one, or say ",
                "None if none match. The possible directions are:",
            ]
        )
        directions = {}
        if location:
            for direction, to_loc in location.connections.items():
                loc_description = "{name} - {description}".format(
                    name=to_loc.name, description=to_loc.description
                )
                location_name_direction = "{direction} toward {loc}".format(
                    direction=direction, loc=loc_description
                )
                directions[location_name_direction] = direction
        other_directions = {
            "'n' can mean north": "north",
            "'s' can mean south": "south",
            "'e' can mean east": "east",
            "'w' can mean west": "west",
            "'out' can mean 'go out'": "out",
            "'in' can mean 'go in'": "in",
            "'up' can mean 'go up'": "up",
            "'down' can mean 'go down'": "down",
        }
        directions.update(other_directions)
        return gpt_pick_an_option(instructions, directions, command, call_handler=self.gpt_handler, max_tokens=10)


# class GptParser3(GptParser2):
#     def __init__(self, game, echo_commands=True, verbose=False, model='gpt-4'):
#         super().__init__(game, echo_commands, verbose)
#         self.model = model

#     def extract_digit(self, text):
#         return re.findall(r"[-]?\d+", text)[0]
    
#     def get_characters_and_find_current(self, character=None):
#         current_idx = -999
#         chars = {}
#         for i, char in enumerate(list(self.game.characters)):
#             chars[i] = char
#             if character and char == character.name:
#                 current_idx = i
#         return chars, current_idx
    
#     def get_character(
#         self, command: str, character: Character = None, hint: str = None, split_words=None, position=None
#     ) -> Character:
#         """
#         This method tries to match a character's name in the command.
#         If no names are matched, it defaults to the passed character. 
#         Args:
#             hint: A hint about the role of character we're looking for 
#                   (e.g. "giver" or "recipent")
#             split_words: not needed for our GptParser
#             position: not needed for our GptParser
#         """

#         system_prompt = "Given a command, return the character who can be described as: \"{h}\". ".format(h=hint)
#         # Create an enumerated dict of the characters in the game

#         chars, curr_idx = self.get_characters_and_find_current(character)
#         if character:
#             system_prompt += f"Unless specified, assume \"{curr_idx}: {character.name}\" performs all actions.\nChoose from the following characters:\n"
#         else:
#             system_prompt += "Choose from the following characters:\n"
#         # Format the characters into a list structure for the system prompt
#         system_prompt += "{c}".format(c='\n'.join([str(i)+": "+str(c) for i, c in chars.items()]))

#         system_prompt += "\nYou must only return the single number whose corresponding character is performing the action.\n\
# If no command is given, return \"{curr_idx}: {character.name}\""
#         # if hint:
#         #     system_prompt += "As a hint, in the given command, the subject can be described as: \"{h}\". ".format(h=hint)
#         #     system_prompt += "If there are no good matches, the action is performed by the game player, so you should return 0.\n"
#         # else:
#         #     system_prompt += "If there are no good matches, the action is performed by the game player, so you should return 0.\n"

#         # create a new client
#         # client = OpenAI()

#         response = self.client.chat.completions.create(
#             model=self.model,
#             messages=[
#                 {
#                     "role": "system",
#                     "content": system_prompt
#                 },
#                 {
#                     "role": "user",
#                     "content": "Command: {c}\nThe best character match is number: ".format(c=command)
#                 },
#             ],
#             temperature=0,
#             max_tokens=10,
#             top_p=0,
#             frequency_penalty=0,
#             presence_penalty=0
#         )

#         # Will probably need to do some parsing of the output here
#         char_idx = response.choices[0].message.content
#         try: 
#             char_idx = self.extract_digit(char_idx)
#             char_idx = int(char_idx)
#         except Exception as e:
#             print("Couldn't match the following response to a number:")
#             print(char_idx)
#             print(e)

#         # print("Item system prompt: ", system_prompt)
#         print(f"GPTParse selected character: {char_idx}")
#         if char_idx not in chars:
#             print(f"no player with id {char_idx} in {str(chars)}")
#             return None
#         else:
#             name = chars[char_idx]
#             return self.game.characters[name]

#     def match_item(
#         self, command: str, item_dict: dict[str, Item], hint: str = None
#     ) -> Item:
#         """
#         Check whether the names of any of the items in this dictionary match the
#         command. If so, return Item, else return None.

#         Args:
#             item_dict: A map from item names to Items (could be a player's 
#                        inventory or the items at a location)
#             hint: what kind of item we're looking for
#         """

#         system_prompt = "Given a command, return the item that is the direct object of the action.\nChoose from the following items:\n"
#         items = {i: it for i, it in enumerate(list(item_dict.keys()))}
#         system_prompt += "{c}".format(c=''.join([str(i)+": "+str(item)+"\n" for i, item in items.items()]))
#         system_prompt += """You must only return the single number whose corresponding item best matches the given command. \
# If there are no good matches, return '-999'\n"""
#         if hint:
#             system_prompt += "As a hint, in the given command, the item can be described as:\"{h}\".\n".format(h=hint)
#         else:
#             system_prompt += "\n"
        
#         # print("Item system prompt: ", system_prompt)
#         # client = OpenAI()

#         response = self.client.chat.completions.create(
#             model=self.model,
#             messages=[
#                 {
#                     "role": "system",
#                     "content": system_prompt
#                 },
#                 {
#                     "role": "user",
#                     "content": "Command: {c}\n  The best item match is number: ".format(c=command)
#                 },
#             ],
#             temperature=0,
#             max_tokens=10,
#             top_p=0,
#             frequency_penalty=0,
#             presence_penalty=0
#         )

#         item_idx = response.choices[0].message.content
#         try:
#             item_idx = self.extract_digit(item_idx)
#             item_idx = int(item_idx)
#         except Exception as e:
#             print(e)

#         print(f"GPTParse selected item: {item_idx}")
#         if item_idx == -999:
#             return None
#         elif item_idx in items:
#             name = items[item_idx]
#             return item_dict[name]
#         else:
#             print(f'Item index {item_idx} not found in {str(items)}')

#     def get_direction(self, command: str, location: Location = None) -> str:
#         """
#         Return the direction from `location.connections` which the player
#         wants to travel to.
#         """
#         dirs = list(location.connections.keys())
#         names = [loc.name for loc in location.connections.values()]
#         connections = {i: dl for i, dl in enumerate(zip(dirs, names))}
#         print('Found connections: ', connections)

#         system_prompt = """
#         You must select the direction that best matches the description given in a command.
#         The possible directions to choose are:\n
#         """
        
#         system_prompt += "\n" + "{c}".format(c=''.join([str(i)+": "+str(d)+" or "+str(l)+"\n" for i, (d, l) in connections.items()]))
        
#         system_prompt += """\nYou must only return the single number whose corresponding direction best matches the given command.
#             If there are no good matches, return '-999'\n"""

#         # print("Direction system prompt: ", system_prompt)

#         # client = OpenAI()

#         response = self.client.chat.completions.create(
#             model=self.model,
#             messages=[
#                 {
#                     "role": "system",
#                     "content": system_prompt
#                 },
#                 {
#                     "role": "user",
#                     "content": "Command: {c}\n  The best direction match is number:  ".format(c=command)
#                 }
#             ],
#             temperature=0,
#             max_tokens=100,
#             top_p=0,
#             frequency_penalty=0,
#             presence_penalty=0
#         )

#         dir_idx = response.choices[0].message.content
#         try:
#             dir_idx = self.extract_digit(dir_idx)
#             dir_idx = int(dir_idx)
#         except Exception as e:
#             print(e)
#         print(f"GPTParse selected direction: {dir_idx}")

#         if dir_idx in connections:
#             dir_name = connections[dir_idx][0]
#             return dir_name
#         else:
#             print(f'direction id "{dir_idx}" not in location connections: {connections}')
#             return None
