from src.things.characters import Character
from . import base
from .things import Drop
from . import preconditions as P
from src.managers import Dialogue


class Talk(base.Action):
    ACTION_NAME = "talk to"
    ACTION_DESCRIPTION = "Start a dialogue with someone"
    ACTION_ALIASES = ["talk with", "chat with", "speak with", "go talk to", "start a conversation with"]

    def __init__(
        self,
        game,
        command: str,
        character: Character
    ):
        super().__init__(game)
        self.command = command
        # self.character = character
        talk_words = ["talk", "chat", "dialogue", "speak"]
        command_before_word = ""
        command_after_word = command
        for word in talk_words:
            if word in command:
                parts = command.split(word, 1)
                command_after_word = parts[1]
                break
        self.starter = character
        self.talked_to = self.parser.get_character(command_after_word, character=None)
        self.participants = [self.starter, self.talked_to]

    def check_preconditions(self) -> bool:
        """
        Preconditions:
        * There must be a starter and a talked_to
        * They must be in the same location
        * Talked-to character must be available to talk (TODO)
        """
        if self.talked_to is None:
            description = f"The character {self.starter.name} tried talking to couldn't be found."
            self.parser.fail(self.command, description, self.starter)
            return False
        if self.talked_to == self.starter.get_last_dialogue_target():
            description = f"{self.starter.name} just spoke with {self.talked_to.name} last turn. You must wait a while to talk to them again."
            self.parser.fail(self.command, description, self.starter)
            return False
        if not self.was_matched(self.starter, self.starter):
            description = "The character starting the dialogue couldn't be found."
            self.parser.fail(self.command, description, self.starter)
            return False
        if not self.was_matched(self.starter, self.talked_to):
            description = f"{self.talked_to.name} could not be found."
            self.parser.fail(self.command, description, self.starter)
            return False
        if not self.starter.location.here(self.talked_to):
            description = f"{self.starter.name} tried to talk to {self.talked_to.name} but {self.talked_to.name} is NOT found at {self.starter.location}"
            self.parser.fail(self.command, description, self.starter)
            return False
        return True

    def apply_effects(self):
        """
        Effects:
        ** Starts a dialogue
        """
        dialogue = Dialogue(self.game, self.participants, self.command)
        dialogue_history = dialogue.dialogue_loop()

        # Add the target of the dialogue to the starter
        self.starter.set_dialogue_participant(self.talked_to)
        self.talked_to.set_dialogue_participant(self.starter)

        self.parser.ok(self.command, dialogue_history, self.starter)
        return True
