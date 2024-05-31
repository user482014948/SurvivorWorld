"""
File: agent_cognition/act.py
Description: defines how agents select an action given their perceptions and memory
"""

# Steps to choosing an action:
# 1. perceive environment (perceive) -- already put into memory
# 2. collect goals, world info, character relationships (retreive)
# 3. get a list of the currently available actions (game.actions)
# 4. Ask GPT to pick an option 
# 5. Parse and return

from typing import TYPE_CHECKING

# local imports
from src.gpt.gpt_helpers import (limit_context_length,
                                                  get_prompt_token_count,
                                                  get_token_remainder,
                                                  context_list_to_string,
                                                  GptCallHandler)
from src.utils.general import enumerate_dict_options, get_logger_extras
from .retrieve import retrieve
from src.assets.prompts import act_prompts as ap

if TYPE_CHECKING:
    from src.games import Game
    from src.things import Character


class Act:
    def __init__(self, game, character):
        self.game = game
        self.character = character
        self.gpt_handler = self._set_up_gpt()
        self.token_offset = 0
        self.offset_pad = 5
 
    def _set_up_gpt(self):
        model_params = {
            "api_key_org": "Helicone",
            "model": "gpt-4",
            "max_tokens": 100,
            "temperature": 1,
            "top_p": 1,
            "max_retries": 5
        }

        return GptCallHandler(**model_params) 
    
    # def _log_action(self, game, character, message):
    #     extras = get_logger_extras(game, character)
    #     extras["type"] = "Act"
    #     game.logger.debug(msg=message, extra=extras)

    def act(self):
        
        system_prompt, user_prompt = self.build_messages()

        # print("act system:", system_prompt, sep='\n')
        # print("-" * 50)
        # print("act user:", user_prompt, sep='\n')

        action_to_take = self.generate_action(system_prompt, user_prompt)
        
        # self._log_action(self.game, self.character, action_to_take)
        print(f"{self.character.name} chose to take action: {action_to_take}")
        return action_to_take

    def generate_action(self, system_prompt, user_prompt):
        # client = set_up_openai_client("Helicone")

        response = self.gpt_handler.generate(
            system=system_prompt,
            user=user_prompt
        )
        
        if isinstance(response, tuple):
            # This occurs when there was a Bad Request Error cause for exceeding token limit
            success, token_difference = response
            print(f"Action prompts exceeded token limit of model by {token_difference} tokens.")
            # Add this offset to the calculations of token limits and pad it 
            self.token_offset = token_difference + self.offset_pad
            self.offset_pad += 2 * self.offset_pad 
            return self.act(self.game, self.character)
        
        return response

    def build_messages(self):
        system_msg, sys_token_count = self.build_system_message()

        consumed_tokens = sys_token_count + self.token_offset
        user_msg = self.build_user_message(consumed_tokens=consumed_tokens)
        return system_msg, user_msg

    def build_system_message(self) -> str:
        """
        Build the system prompt for agent actions
        This is considered an "always included" portion of the message

        Args:
            game (_type_): _description_
            character (_type_): _description_
            game_actions (_type_): _description_

        Returns:
            str: the system prompt
            int: token count of the system prompt
        """
        system = ""

        system += self.character.get_standard_info(self.game)
        system += ap.action_system_mid
        system += ap.action_system_end
        
        game_actions = self.game.parser.actions
        # Added inverted argument because the game actions are inverted
        choices_str, _ = enumerate_dict_options(game_actions, names_only=True, inverted=True)
        system += choices_str

        sys_token_count = get_prompt_token_count(content=system, role='system', pad_reply=False)

        return system, sys_token_count

    def build_user_message(self, consumed_tokens: int):

        if hasattr(self.game, "get_basic_game_goal"):
            goal_reminder = self.game.get_basic_game_goal()
        else:
            goal_reminder = "Complete the objective of the game as quickly as you can. "    
        
        # Reiterate which characters are currently in view
        chars_in_view = self.character.get_characters_in_view(self.game)
        always_included = [
            "\nThese are select MEMORIES in ORDER from LEAST to MOST RELEVANT:\n",
            f"In this location, you see: {', '.join([c.name for c in chars_in_view])}\n",
            ap.action_incentivize_exploration,
            goal_reminder,
            "Given the above information and others present here, what would you like to do?"]
        always_included_tokens = get_prompt_token_count(content=always_included,
                                                        role="user",
                                                        pad_reply=True, 
                                                        tokenizer=self.game.parser.tokenizer)
        
        # Get available tokens using the requested model's limit as the reference point
        # All other arguments to this method are subtracted from the limit
        user_available_tokens = get_token_remainder(self.gpt_handler.model_context_limit, 
                                                    self.gpt_handler.max_tokens,
                                                    consumed_tokens,
                                                    always_included_tokens)
        imp_limit, mem_limit = self.get_user_token_limits(user_available_tokens, props=(0.33, 0.66))

        # Add the theory of mind of agents in the vicinity
        # and limit the inclusion to the token count defined in "imp_limit"
        user_messages = ""
        tok_count = 0
        try:
            impressions = self.character.impressions.get_multiple_impressions(chars_in_view)
            impressions, tok_count = limit_context_length(history=impressions,
                                                          max_tokens=imp_limit,
                                                          tokenizer=self.game.parser.tokenizer,
                                                          return_count=True)
            # Add the impressions to the user prompt
            user_messages += context_list_to_string(impressions)
        except AttributeError:
            pass

        # Retrieve ALL relevant memories to the situation
        memories_list = retrieve(self.game, self.character, query=None, n=40)  # Should we limit this too or just let it fill up?

        # This is the token count still available to fill with memories
        memory_available_tokens = get_token_remainder(user_available_tokens, tok_count)
        memories_list = limit_context_length(memories_list,
                                             max_tokens=memory_available_tokens, 
                                             tokenizer=self.game.parser.tokenizer)
        
        user_messages += always_included[0]
        user_messages += context_list_to_string(context=memories_list, sep="\n")
        
        user_messages += '\n'.join(always_included[1:])
        return user_messages

    def get_user_token_limits(self, remainder, props):
        ratio_impressions, ratio_memories = props
        remaining_tokens_impressions = int(remainder * ratio_impressions)
        remaining_tokens_memories = int(remainder * ratio_memories)

        return remaining_tokens_impressions, remaining_tokens_memories
