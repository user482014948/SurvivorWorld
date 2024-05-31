import logging
from SurvivorWorld.text_adventure_games import games, things, actions, blocks
from SurvivorWorld.text_adventure_games.things.characters import GenerativeAgent
from SurvivorWorld.text_adventure_games.utils.build_agent import build_agent
from SurvivorWorld.text_adventure_games.utils.custom_logging import logging_setup
from SurvivorWorld.text_adventure_games.utils.custom_logging import logger

class ActionCastle(games.Game):
    def __init__(
        self,
        start_at: things.Location,
        player: things.Character,
        characters=None,
        custom_actions=None,
        world_info=None
    ):
        super().__init__(start_at, player, characters, custom_actions, world_info)
       
    def is_won(self) -> bool:
        """
        Checks whether the game has been won. For Action Castle, the game is won
        once any character is sitting on the throne (has the property is_reigning).
        """
        for name, character in self.characters.items():
            if character.get_property("is_reigning"):
                self.parser.ok(
                    "{name} is now reigns in ACTION CASTLE! {name} has won the game!".format(
                        name=character.name.title()
                    )
                )
                return True
        return False
    

class ActionCastleSurvivor(games.SurvivorGame):
    def __init__(
        self,
        start_at: things.Location,
        player: things.Character,
        characters=None,
        custom_actions=None,
        max_ticks=5,
        num_finalists=2,
        experiment_name="exp1",
        experiment_id=1
    ):
        super().__init__(start_at,
                         player, 
                         characters, 
                         custom_actions, 
                         max_ticks=max_ticks, 
                         num_finalists=num_finalists,
                         experiment_name=experiment_name,
                         experiment_id=experiment_id)


# Actions
class Unlock_Door(actions.Action):
    ACTION_NAME = "unlock door"
    ACTION_DESCRIPTION = "Unlock a door with a key"
    ACTION_ALIASES = []

    def __init__(self, game, command):
        super().__init__(game)
        self.character = self.parser.get_character(command)
        self.key = self.parser.match_item(
            "key", self.parser.get_items_in_scope(self.character)
        )
        self.door = self.parser.match_item(
            "door", self.parser.get_items_in_scope(self.character)
        )

    def check_preconditions(self) -> bool:
        """
        Preconditions:
        * There must be a door
        * The character must be at the same location as the door
        * The door must be locked
        * There must be a door
        * The character must have the key in their inventory
        """
        if not self.was_matched(self.door, "There's no door here."):
            return False
        if not self.loc_has_item(self.character.location, self.door):
            return False
        if not self.has_property(self.door, "is_locked", "The door is not locked."):
            return False
        if not self.was_matched(
            self.key, "{name} does not have the key.".format(name=self.character.name)
        ):
            return False
        if not self.is_in_inventory(self.character, self.key):
            return False
        return True

    def apply_effects(self):
        """
        Effects:
        * Unlocks the door
        """
        self.door.set_property("is_locked", False)
        description = "{character_name} unlocked the door".format(
            character_name=self.character.name
        )
        self.parser.ok(description)


class Read_Runes(actions.Action):
    """
    Reading the runes on the candle with strange runes on it will banish the
    ghost from the dungeon, and cause it to drop the crown.
    """

    ACTION_NAME = "read runes"
    ACTION_DESCRIPTION = "Read runes off of the candle"
    ACTION_ALIASES = []

    def __init__(self, game, command):
        super().__init__(game)
        self.character = self.parser.get_character(command)
        self.candle = self.parser.match_item(
            "candle", self.parser.get_items_in_scope(self.character)
        )
        self.ghost = self.parser.get_character("ghost")

    def check_preconditions(self) -> bool:
        """
        Preconditions:
        * There must be a candle with strange runes on it
        * The character must have the candle in their inventory
        * the ghost must be in this location
        * The candle must be lit
        """
        if not self.was_matched(self.candle, "You don't see runes on anything here."):
            return False
        if not self.is_in_inventory(self.character, self.candle):
            return False
        if not self.was_matched(
            self.ghost,
            "The runes seem be a banishment spell, but there is nothing to banish here.",
        ):
            return False
        if not self.at(
            self.ghost,
            self.character.location,
            "The runes seem be a banishment spell, but there is nothing to banish here.",
        ):
            return False
        if not self.has_property(
            self.candle,
            "is_lit",
            "Nothing happens. Perhaps if you light the candle first?",
        ):
            return False
        return True

    def apply_effects(self):
        """
        Effects:
        * Banishes the ghost, causing it to drop its inventory.
        """
        description = "{character_name} holds aloft the glowing candle cofered in strange runes. ".format(
            character_name=self.character.name.capitalize()
        )
        description += "The odd runes are an exorcism ritual to dispel evil spirits."
        self.parser.ok(description)

        # the ghost drops its inventory
        items = list(self.ghost.inventory.keys())
        for item_name in items:
            item = self.ghost.inventory[item_name]
            command = f"{self.ghost.name} drops {item.name}"
            drop = actions.Drop(self.game, command)
            if drop.check_preconditions():
                drop.apply_effects()

        # the ghost is banished
        self.ghost.set_property("is_banished", True)
        description = "{ghost} is banished".format(ghost=self.ghost.name)
        self.parser.ok(description)
        # remove the ghost from the scene
        self.ghost.location.remove_character(self.ghost)


class Propose(actions.Action):
    """
    Mawwige is whut bwings us togevveh today.
    """

    ACTION_NAME = "propose"
    ACTION_DESCRIPTION = "Propose marriage to someone"
    ACTION_ALIASES = []

    def __init__(self, game, command):
        super().__init__(game)
        marriage_words = ["propose", "marry"]
        self.proposer = self.parser.get_character(
            command, hint="proposer", split_words=marriage_words, position="before"
        )
        self.propositioned = self.parser.get_character(
            command, hint="propositioned", split_words=marriage_words, position="after"
        )

    def check_preconditions(self) -> bool:
        """
        Preconditions:
        * A character may not marry themselves
        * The two characters must be in the same place
        * Neither can be married yet
        * Both must be happy
        """
        if not self.was_matched(self.proposer, "They aren't here."):
            return False
        if not self.was_matched(self.propositioned, "They aren't here."):
            return False
        if self.proposer == self.propositioned:
            self.parser.fail(f"{self.proposer.name} cannot marry themself")
        if not self.at(
            self.propositioned,
            self.proposer.location,
            "{name_1} and {name_2} aren't in the same location.".format(
                name_1=self.propositioned.name, name_2=self.proposer.name
            ),
        ):
            return False
        if not self.property_equals(self.proposer, "emotional_state", "happy"):
            return False
        if not self.property_equals(self.propositioned, "emotional_state", "happy"):
            return False
        if self.has_property(
            self.proposer,
            "is_married",
            "{name} is already married".format(name=self.proposer.name),
            display_message_upon=True,
        ):
            return False
        if self.has_property(
            self.propositioned,
            "is_married",
            "{name} is already married".format(name=self.propositioned.name),
            display_message_upon=True,
        ):
            return False
        return True

    def apply_effects(self):
        """
        Effects:
        * They said "Yes!"
        * They are married.
        * If one is a royal, they are now both royals
        """
        description = "{name} says YES!".format(
            name=self.propositioned.name.capitalize()
        )
        self.parser.ok(description)
        self.proposer.set_property("is_married", True)
        self.propositioned.set_property("is_married", True)
        description = "{name_1} and {name_2} are now married.".format(
            name_1=self.propositioned.name, name_2=self.proposer.name
        )
        self.parser.ok(description)
        if self.proposer.get_property("is_royal") or self.propositioned.get_property(
            "is_royal"
        ):
            self.proposer.set_property("is_royal", True)
            self.propositioned.set_property("is_royal", True)


class Wear_Crown(actions.Action):
    ACTION_NAME = "wear crown"
    ACTION_DESCRIPTION = "Put a crown in your inventory atop your head"
    ACTION_ALIASES = []

    def __init__(self, game, command):
        super().__init__(game)
        self.character = self.parser.get_character(command)
        self.crown = self.parser.match_item(
            "crown", self.parser.get_items_in_scope(self.character)
        )

    def check_preconditions(self) -> bool:
        """
        Preconditions:
        * The crown must be in the character's inventory
        * The the character must be a royal
        """
        if not self.was_matched(self.crown, "I don't see it."):
            return False
        if not self.is_in_inventory(self.character, self.crown):
            return False
        if not self.has_property(
            self.character, "is_royal", "Only a royal may wear the crown."
        ):
            return False
        return True

    def apply_effects(self):
        """
        The character is crowned.
        """

        description = "{character_name} has been crowned as the monarch.  They may now take their rightful seat on the throne.".format(
            character_name=self.character.name.capitalize()
        )
        self.parser.ok(description)
        self.character.set_property("is_crowned", True)


class Sit_On_Throne(actions.Action):
    ACTION_NAME = "sit on throne"
    ACTION_DESCRIPTION = "Sit on the throne, if you are the crowned monarch."
    ACTION_ALIASES = []

    def __init__(self, game, command):
        super().__init__(game)
        self.character = self.parser.get_character(command)
        self.throne = self.parser.match_item(
            "throne", self.parser.get_items_in_scope(self.character)
        )

    def check_preconditions(self) -> bool:
        """
        Preconditions:
        * The character must be in same location as the throne
        * The the character must be crowned
        """
        if not self.was_matched(self.character, "The character wasn't matched."):
            return False
        if not self.was_matched(self.throne, "The throne couldn't be found."):
            return False
        if not self.at(self.throne, self.character.location, "The throne isn't here."):
            return False
        if not self.has_property(
            self.character,
            "is_crowned",
            "Only the crowned monarch may sit upon the throne",
        ):
            return False
        return True

    def apply_effects(self):
        """
        The character who sits on the throne is reigning.
        """
        self.character.set_property("is_reigning", True)
        description = (
            "{name} now sits upon the throne. The reign of {name} has begun!".format(
                name=self.character.name.title()
            )
        )
        self.parser.ok(description)


# Blocks
class Troll_Block(blocks.Block):
    """
    Blocks progress in this direction until the troll is no longer hungry, or
    leaves, or is unconscious, or dead.
    """

    def __init__(self, location: things.Location, troll: things.Character):
        super().__init__("A troll blocks your way", "A hungry troll blocks your way")
        self.location = location
        self.troll = troll

    def is_blocked(self) -> bool:
        # Conditions of block:
        # * There is a troll here
        # * The troll is alive and conscious
        # * The troll is still hungry
        if self.troll:
            if not self.location.here(self.troll):
                return False
            if self.troll.get_property("is_dead"):
                return False
            if self.troll.get_property("is_unconscious"):
                return False
            if self.troll.get_property("is_hungry"):
                return True
        return False


class Guard_Block(blocks.Block):
    """
    Blocks progress in this direction until the guard is no longer suspicious, or
    leaves, or is unconscious, or dead.
    """

    def __init__(self, location: things.Location, guard: things.Character):
        super().__init__(
            "A guard blocks your way", "The guard refuses to let you pass."
        )
        self.guard = guard
        self.location = location

    def is_blocked(self) -> bool:
        # Conditions of block:
        # * There is a guard here
        # * The guard is alive and conscious
        # * The guard is suspicious

        if self.guard:
            if not self.location.here(self.guard):
                return False
            if self.guard.get_property("is_dead"):
                return False
            if self.guard.get_property("is_unconscious"):
                return False
            if self.guard.get_property("emotional_state") != "suspicious":
                return False
            return True
        return False


class Darkness(blocks.Block):
    """
    Blocks progress in this direction unless the character has something that lights the way.
    """

    def __init__(self, location: things.Location, skeleton=False):
        super().__init__("Darkness blocks your way", "It's too dark to go that way.")
        self.location = location
        self.location.set_property("is_dark", True)

    def is_blocked(self) -> bool:
        # Conditions of block:
        # * The location is dark
        # * Unblocked if any character at the location is carrying a lit item (like a lamp or candle)

        if not self.location.get_property("is_dark"):
            return False
        for character_name in self.location.characters:
            character = self.location.characters[character_name]
            for item_name in character.inventory:
                item = character.inventory[item_name]
                if item.get_property("is_lit"):
                    return False
        return True

class Door_Block(blocks.Block):
    """
    Blocks progress in this direction until the character unlocks the door.
    """

    def __init__(self, location: things.Location, door: things.Item):
        super().__init__("A locked door blocks your way", "The door ahead is locked.")
        self.door = door
        self.location = location

    def is_blocked(self) -> bool:
        # Conditions of block:
        # * The door is locked
        if self.door:
            if not self.location.here(self.door):
                return False
            if self.door.get_property("is_locked"):
                return True
        return False

def build_game() -> games.Game:
    # Locations
    cottage = things.Location("Cottage", "You are standing in a small cottage.")
    garden_path = things.Location(
        "Garden Path",
        "You are standing on a lush garden path. There is a cottage here.",
    )
    fishing_pond = things.Location(
        "Fishing Pond", "You are at the edge of a small fishing pond."
    )
    winding_path = things.Location(
        "Winding Path",
        "You are walking along a winding path. There is a tall tree here.",
    )
    top_of_tree = things.Location(
        "Top of the Tall Tree", "You are the top of the tall tree."
    )
    fishing_pond = things.Location(
        "Fishing Pond", "You are at the edge of a small fishing pond."
    )
    drawbridge = things.Location(
        "Drawbridge",
        "You are standing on one side of a drawbridge leading to ACTION CASTLE.",
    )
    courtyard = things.Location(
        "Courtyard", "You are in the courtyard of ACTION CASTLE."
    )
    tower_stairs = things.Location(
        "Tower Stairs",
        "You are climbing the stairs to the tower. There is a locked door here.",
    )
    tower = things.Location("Tower", "You are inside a tower.")
    dungeon_stairs = things.Location(
        "Dungeon Stairs", "You are climbing the stairs down to the dungeon."
    )
    dungeon_stairs.set_property("is_dark", True)
    dungeon = things.Location(
        "Dungeon", "You are in the dungeon. There is a spooky ghost here."
    )
    feasting_hall = things.Location(
        "Great Feasting Hall", "You stand inside the Great Feasting Hall."
    )
    throne_room = things.Location(
        "Throne Room", "This is the throne room of ACTION CASTLE."
    )
    death = things.Location("The Afterlife", "You are dead. GAME OVER.")
    death.set_property("game_over", True)

    # Map of Locations
    cottage.add_connection("out", garden_path)
    garden_path.add_connection("south", fishing_pond)
    garden_path.add_connection("north", winding_path)
    winding_path.add_connection("up", top_of_tree)
    top_of_tree.add_connection("jump", death)
    winding_path.add_connection("east", drawbridge)
    drawbridge.add_connection("east", courtyard)
    courtyard.add_connection("up", tower_stairs)
    tower_stairs.add_connection("up", tower)
    courtyard.add_connection("down", dungeon_stairs)
    dungeon_stairs.add_connection("down", dungeon)
    courtyard.add_connection("east", feasting_hall)
    feasting_hall.add_connection("east", throne_room)

    # Gettable Items
    fishing_pole = things.Item(
        "pole",
        "a fishing pole",
        "A SIMPLE FISHING POLE.",
    )

    branch = things.Item(
        "branch",
        "a stout, dead branch",
        "IT LOOKS LIKE IT WOULD MAKE A GOOD CLUB.",
    )
    branch.set_property("is_weapon", True)
    branch.set_property("is_fragile", True)

    candle = things.Item(
        "candle",
        "a strange candle",
        "THE CANDLE IS COVERED IN STARGE RUNES.",
    )
    candle.set_property("is_lightable", True)
    candle.set_property("is_lit", False)
    candle.add_command_hint("light candle")
    candle.add_command_hint("read runes")

    # Map of Gettable Items
    cottage.add_item(fishing_pole)
    top_of_tree.add_item(branch)
    feasting_hall.add_item(candle)

    # Sceneary Items
    pond = things.Item(
        "pond",
        "a small fishing pond",
        "THERE ARE FISH IN THE POND.",
    )
    pond.set_property("gettable", False)
    pond.set_property("has_fish", True)
    pond.add_command_hint("catch fish")
    pond.add_command_hint("catch fish with pole")

    rosebush = things.Item(
        "rosebush",
        "a rosebush",
        "THE ROSEBUSH CONTAINS A SINGLE RED ROSE.  IT IS BEAUTIFUL.",
    )
    rosebush.set_property("gettable", False)
    rosebush.set_property("has_rose", True)
    rosebush.add_command_hint("pick rose")

    throne = things.Item("throne", "An ornate golden throne.")
    throne.set_property("gettable", False)
    throne.add_command_hint("sit on throne")

    door = things.Item("door", "a door", "THE DOOR IS SECURELY LOCKED.")
    door.set_property("gettable", False)
    door.set_property("is_locked", True)
    door.add_command_hint("unlock door")

    # Map of Scenery Items
    fishing_pond.add_item(pond)
    garden_path.add_item(rosebush)
    throne_room.add_item(throne)
    tower_stairs.add_item(door)

    # Troll
    troll = things.Character(
        name="troll",
        description="A mean troll",
        persona="I am hungry. The guard promised to feed me if I guard the drawbridge and keep people out of the castle.",
    )
    troll.set_property("is_hungry", True)
    troll.set_property("character_type", "troll")

    # Guard
    guard = things.Character(
        name="guard",
        description="A castle guard",
        persona="I am suspicious of anyone trying to enter the castle. I will prevent keep people from entering and learning the castle's dark secrets.",
    )
    guard.set_property("is_conscious", True)
    guard.set_property("emotional_state", "suspicious")
    guard.set_property("character_type", "human")

    # Guard's key
    key = things.Item("key", "a brass key", "THIS LOOKS USEFUL")
    guard.add_to_inventory(key)

    # Guard's sword
    sword = things.Item("sword", "a short sword", "A SHARP SHORT SWORD.")
    sword.set_property("is_weapon", True)
    guard.add_to_inventory(sword)

    # Princess
    princess = things.Character(
        name="princess",
        description="A princess who is beautiful and lonely. She awaits her non-gender-stereotypical soulmate.",
        persona="I am the princess. I am grieving my father's death. I feel alone.",
    )
    princess.set_property("is_royal", True)
    princess.set_property("emotional_state", "sad and lonely")
    princess.set_property("is_married", False)
    princess.set_property("character_type", "human")

    # Ghost
    ghost = things.Character(
        name="ghost",
        description="A ghost with bony, claw-like fingers and who is wearing a crown.",
        persona="I was murdered by the guard. I will haunt this castle until banished. If you linger before my apparition, I will plunge my ghostly hand inside you and stop your heart",
    )
    ghost.set_property("character_type", "ghost")
    ghost.set_property("is_dead", True)
    ghost.set_property("is_banished", False)

    # Ghost's crown
    crown = things.Item("crown", "a crown", "A CROWN FIT FOR A KING.")
    crown.add_command_hint("wear crown")
    ghost.add_to_inventory(crown)

    # Map of Characters
    drawbridge.add_character(troll)
    courtyard.add_character(guard)
    tower.add_character(princess)
    dungeon.add_character(ghost)

    # TODO Add blocks to location to:
    # * the courtyard - the guard prevents you from going East
    # * the dungeon_stairs - the darkness prevents you from going Down
    # * the tower stairs - the locked door prevents you from going Up

    troll_block = Troll_Block(drawbridge, troll)
    drawbridge.add_block("east", troll_block)
    guard_block = Guard_Block(courtyard, guard)
    courtyard.add_block("east", guard_block)
    darkness_block = Darkness(dungeon_stairs)
    dungeon_stairs.add_block("down", darkness_block)
    locked_door_block = Door_Block(tower_stairs, door)
    tower_stairs.add_block("up", locked_door_block)

    # Player
    player = things.Character(
        name="The player",
        description="You are a simple peasant destined for greatness.",
        persona="I am on an adventure.",
    )
    player.set_property("character_type", "human")

    # Player's lamp
    lamp = things.Item("lamp", "a lamp", "A LAMP.")
    lamp.set_property("is_lightable", True)
    lamp.set_property("is_lit", False)
    lamp.add_command_hint("light lamp")
    player.add_to_inventory(lamp)

    # The Game
    characters = [troll, guard, princess, ghost]
    custom_actions = [Unlock_Door, Read_Runes, Propose, Wear_Crown, Sit_On_Throne]
    
    game = ActionCastle(cottage, player, characters, custom_actions, "You are playing ACTION CASTLE, an adventure game.")
    return game

def build_mini_game(experiment_name, sim_id, make_new_characters=False, max_ticks=2) -> games.Game:
    # Locations
    camp = things.Location(
        "Camp",
        "the tribe's base camp."
    )
    cliffs = things.Location(
        "Cliffs",
        """the front of some steep cliffs.
            Climb them carefully so you don't fall.""",
    )
    beach = things.Location(
        "Beach",
        "the beach, toes in the sand. In front of you is the vast ocean."
    )
    ocean = things.Location(
        "Ocean",
        "the edge of the ocean with waves washing up around your knees.",
    )
    jungle_path = things.Location(
        "Jungle Path",
        "a jungle path towards the well.",
    )
    well = things.Location(
        "Well",
        "the water well where you can get water for your tribe.",
    )
    jungle = things.Location(
        "Jungle",
        "the deep jungle. There could be treasures lurking nearby.",
    )

    camp.add_connection("out", beach)
    beach.add_connection("north", jungle_path)
    beach.add_connection("south", ocean)
    beach.add_connection("west", cliffs)
    beach.add_connection("in", camp)
    jungle_path.add_connection("south", beach)
    jungle_path.add_connection("east", well)
    jungle_path.add_connection("north", jungle)
    well.add_connection("west", jungle_path)
    jungle.add_connection("south", jungle_path)
    ocean.add_connection("north", beach)
    cliffs.add_connection("east", beach)

    # Gettable Items
    fishing_pole = things.Item(
        "pole",
        "a fishing pole",
        "A SIMPLE FISHING POLE.",
    )
    ocean.add_item(fishing_pole)

    machete = things.Item(
        "machete",
        "a sharp machete",
        "A SHARP MACHETE USED FOR CUTTING VINES.",
    )
    camp.add_item(machete)

    # Characters
    # Troll
    troll_persona = build_agent(agent_description="A grumpy old man sitting on his porch in a rocking chair",
                                facts_new=make_new_characters,
                                archetype="Hubris")
    troll = GenerativeAgent(
        troll_persona
    )
    troll.set_property("is_hungry", True)
    troll.set_property("character_type", "troll")
    ocean.add_character(troll)

    # Mother
    mother_persona = build_agent(agent_description="A homely mother who with a powerful spirit",
                                 facts_new=make_new_characters,
                                 archetype="Mother")
    mother = GenerativeAgent(
        mother_persona
    )
    mother.set_property("emotional_state", "happy")
    mother.set_property("is_married", True)
    mother.set_property("character_type", "human")
    camp.add_character(mother)

    # Player
    player_persona = build_agent(agent_description="A young person destined for greatness, but darkness lurks within them",
                                 facts_new=make_new_characters,
                                 archetype="Villain")
    player = GenerativeAgent(
        player_persona
    )
    player.set_property("character_type", "human")
    player.set_property("immune", True)

    # Player's lamp
    lamp = things.Item("lamp", "a lamp", "A LAMP.")
    lamp.set_property("is_lightable", True)
    lamp.set_property("is_lit", False)
    lamp.add_command_hint("light lamp")
    player.add_to_inventory(lamp)

    # The Game
    # characters = [troll, mother, fourth, fifth]
    characters = [troll, mother]
    # custom_actions = [Unlock_Door, Read_Runes, Propose, Wear_Crown, Sit_On_Throne]
    game = ActionCastleSurvivor(camp, 
                                player, 
                                characters, 
                                custom_actions=None,
                                max_ticks=max_ticks)

    return game

def build_ac_mini_game(experiment_name, sim_id, make_new_characters=False, max_ticks=2) -> games.Game:
    fishing_pond = things.Location(
        "Fishing Pond", "You are at the edge of a small fishing pond."
    )

    # Gettable Items
    fishing_pole = things.Item(
        "pole",
        "a fishing pole",
        "A SIMPLE FISHING POLE.",
    )
    fishing_pond.add_item(fishing_pole)
    fishing_pond.set_property("has_fish", True)

    # Characters
    # Mother
    # mother_persona = build_agent(agent_description="A homely mother who with a powerful spirit",
    #                              facts_new=make_new_characters,
    #                              archetype="Mother")
    # mother = GenerativeAgent(
    #     mother_persona
    # )
    # mother.set_property("emotional_state", "happy")
    # mother.set_property("is_married", True)
    # mother.set_property("character_type", "human")
    # fishing_pond.add_character(mother)

    # Player
    player_persona = build_agent(agent_description="A young person destined for greatness, but darkness lurks within them",
                                 facts_new=make_new_characters,
                                 archetype="Villain")
    player = GenerativeAgent(
        player_persona
    )
    player.set_property("character_type", "human")
    player.set_property("immune", True)

    # The Game
    # characters = [troll, mother, fourth, fifth]
    # characters = [mother]
    # custom_actions = [Unlock_Door, Read_Runes, Propose, Wear_Crown, Sit_On_Throne]
    game = ActionCastleSurvivor(fishing_pond, 
                                player, 
                                # characters, 
                                custom_actions=None,
                                max_ticks=max_ticks)

    return game


def test_logging_setup(experiment_name, sim_id):
    # Logging data
    print("Creating custom logger")
    # my_logger_obj = logger.CustomLogger(experiment_name, sim_id)
    my_logger_obj = logging_setup.setup_logger(experiment_name, sim_id)
    print(my_logger_obj.get_logger())

if __name__ == "__main__":
    game = build_game()
    game.game_loop()
