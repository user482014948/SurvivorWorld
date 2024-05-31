"""
File: agent_cognition/act.py
Description: defines how agents select an action given their perceptions and memory
"""

from __future__ import annotations
from typing import TYPE_CHECKING
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

# local imports
if TYPE_CHECKING:
    from src.games import Game
    from src.things.characters import Character
from src.utils.general import (combine_dicts_helper,
                                                get_text_embedding)

# initially focus on the people that are around the current character

# memory ranking:
# recency: gamma^(curr_idx - retreived idx) --> will need to do linear conversion (similar to min/max scaling) to [0,1]
# importance: interpreted by GPT --> rescale to [0, 1]
# Relevance: cosine similarity --> Could probably just take the absolute value here since it is [-1, 1]

# What is the query for the action selection?
# goals, surroundings, num ticks left to vote?
# Goals should be generated based on the game information and decomposed into a series of sub-tasks

# what is the query for dialogue?
# initial is the dialogue command, subsequent is the last piece of dialogue

def retrieve(game: "Game", character: "Character", query: str = None, n: int = -1, include_idx=False):
    # TODO: refine the inputs used to assess keywords for memory retrieval
    # TODO: WHAT IS THE QUERY STRING FOR RELEVANCY (COS SIM)?
    """
    Using character goals, current perceptions, and possibly additional inputs,
    parse these for keywords, get a list of memory nodes based on the keywords,
    then calculate the retrieval score for each and return a ranked list of memories 

    Args:
        game (Game): game instance
        character (Character): a character instance
        query (str, optional): Keeping input query string optional for now but this would be
                               a non-memory input that we want to use as a retrieval seed. Defaults to None.
        n (int): the number of relevant memories to return. Defaults to -1.
        include_idx (bool): if True returns memory index numbers along with the memory descriptions
    """
    seach_keys = gather_keywords_for_search(game, character, query)
    memory_node_ids = get_relevant_memory_ids(seach_keys, character)
    if len(memory_node_ids) == 0:
        return None

    # TODO: how many should be returned? default = all
    ranked_memory_ids = rank_nodes(character, memory_node_ids, query)

    # If specified positive integer, then take up to that many
    # We take the negative index through to the end because the nodes are in ascending order of relevancy
    if n > 0:
        ranked_memory_ids = ranked_memory_ids[-n:]

    # NOTE: currently a list of strings
    if not include_idx:
        return [f"{character.memory.observations[t[0]].node_description}\n" for t in ranked_memory_ids]
    else:
        # return [f"{mem_id}. {mem_desc}\n" for mem_id, mem_desc in enum_nodes]
        return [f"{t[0]}. {character.memory.observations[t[0]].node_description}" for t in ranked_memory_ids]

def rank_nodes(character, node_ids, query):
    """
    Wrapper for the component scores that sum to define total node score

    Args:
        character (Character): the current character
        node_ids (list): list of relevant node ids

    Returns:
        List[tuple]: (node_id, score)
    """
    recency = calculate_node_recency(character, node_ids)
    importance = calculate_node_importance(character, node_ids)
    relevance = calculate_node_relevance(character, node_ids, query)

    # scale the raw scores based on their weights 
    # These are all 1 at the moment
    recency = character.memory.recency_alpha * recency
    importance = character.memory.importance_alpha * importance
    relevance = character.memory.relevance_alpha * relevance
    total_score = recency + importance + relevance

    node_scores = zip(node_ids, list(total_score))

    ranked_memory_ids = sorted(node_scores, key=lambda x: x[1])

    return ranked_memory_ids

def calculate_node_recency(character, memory_ids):
    """
    Calculate the recency score of each memory using an exponential decay assumption.

    Args:
        character (Character): the current character
        memory_ids (list): a list of relevant memories

    Returns:
        np.array: a scaled list of recency scores for each node
    """
    # The most recent node is the last index, which is also stored as the number of observations made
    latest_node = character.memory.num_observations
    # Take the difference between this max index and each relevant node id
    # This is the "age" of the memory
    recency = [character.memory.gamma ** (latest_node - i) for i in memory_ids]
    recency_sc = minmax_normalize(recency, 0, 1)
    return recency_sc

def calculate_node_importance(character, memory_ids):
    """
    Get the importance scores of the relevant ids.

    Args:
        character (Character): the current character
        memory_ids (list): a list of relevant memories

    Returns:
        np.array: a scaled list of importance scores for each node
    """
    importances = [character.memory.observations[i].node_importance for i in memory_ids]
    importances_sc = minmax_normalize(importances, 0, 1)
    return importances_sc

def calculate_node_relevance(character, memory_ids, query):
    """
    Get the relevance scores of the relevant ids using cosine similarity

    Args:
        character (Character): the current character
        memory_ids (list): a list of relevant memories

    Returns:
        np.array: a scaled list of relevance scores for each node
    """
    memory_embeddings = [character.memory.get_embedding(i) for i in memory_ids]
    if query:
        # if a query is passed, only this will be used to rank node relevance
        query_embedding = get_text_embedding(query).reshape(1, -1)
        relevances = cosine_similarity(memory_embeddings, query_embedding).flatten()
    else:
        # if no query is passed, then the default queries will be used: 
        # persona, goals
        # Take the max relevance of all of these
        default_embeddings = character.memory.get_query_embeddings()
        raw_relevance = cosine_similarity(memory_embeddings, default_embeddings)
        relevances = np.max(raw_relevance, axis=1)
    
    relevances_sc = minmax_normalize(relevances, 0, 1)
    return relevances_sc

def get_relevant_memory_ids(seach_keys, character):
    """
    For each seach keyword obtain the cached memory node ids.

    Args:
        seach_keys (Dict[List]): lists of keywords by type
        character (Character): the current character

    Returns:
        list: a list of memory node ids
    """
    memory_ids = []
    for kw_type, search_words in seach_keys.items():
        for w in search_words:
            node_ids = character.memory.keyword_nodes[kw_type][w]
            memory_ids.extend(node_ids)

    return list(set(memory_ids))
    
def gather_keywords_for_search(game, character, query):
    # gather memories from which keywords will be extracted
    retrieval_kwds = {}
    # 1. last n memories by default - this is like "short term memory"
    for node in character.memory.observations[-character.memory.lookback:]:
        node_kwds = game.parser.extract_keywords(node.node_description)  # a dict
        if node_kwds:
            retrieval_kwds = combine_dicts_helper(existing=retrieval_kwds, new=node_kwds)

    # 2. goals
    # TODO: need to confirm how goals are stored and if any parsing needs to done to pass them as a string  
    prev_round = max(0, game.round - 1)
    try:
        current_goals = character.goals.get_goals(round=prev_round, as_str=True)
    except AttributeError:
        current_goals = None
    
    if current_goals:
        goal_kwds = game.parser.extract_keywords(current_goals)
        if goal_kwds:
            retrieval_kwds = combine_dicts_helper(retrieval_kwds, goal_kwds)

    # 3. Other keywords
    if query:
        query_kwds = game.parser.extract_keywords(query)
        if query_kwds:
            retrieval_kwds = combine_dicts_helper(retrieval_kwds, query_kwds)

    # TODO: any more? ADD HERE

    return retrieval_kwds

def minmax_normalize(lst, target_min: int, target_max: int):
    """
    Normalize a list of numeric values to sit between a specified min/max value
    while also maintaining the relative proportions of values in the original range.

    Args:
        lst (list): a list of numeric values; typically floats
        target_min (int): new range minimum
        target_max (int): new range maximum

    Returns:
        np.array: range normalized values
    """
    
    try:
        min_val = min(lst)
        max_val = max(lst)
    except TypeError:
        try:
            min_val = np.nanmin(lst)
            max_val = np.nanmax(lst)
        except TypeError:
            fixed_list = [x if x else 0 for x in lst]
            min_val = np.nanmin(fixed_list)
            max_val = np.nanmax(fixed_list)
    range_val = max_val - min_val
    # If there is no variance in the values, they will not contribute to the score
    if range_val == 0:
        out = [0.5] * len(lst)
        return out
    try:
        out = [((x - min_val) * (target_max - target_min) / range_val + target_min) for x in lst]
    except TypeError:
        # If there are None values if this list for some reason, replace them with the midpoint value.
        mid_val = (max_val + min_val) / 2
        tmp = [x if x else mid_val for x in lst]
        out = [((x - min_val) * (target_max - target_min) / range_val + target_min) for x in tmp]
    return np.array(out)

# def cosine_similarity(x, query):
#     """
#     Get the (normalized) cosine similarity between two vectors

#     Args:
#         x (np.array): vector of interest
#         query (np.array): reference vector 

#     Returns:
#         float: the similarity between vectors
#     """
#     return np.dot(x, query) / (np.norm(x) * np.norm(query))
