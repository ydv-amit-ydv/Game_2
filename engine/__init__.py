"""
THE IRON COMPACT — engine.

A deterministic, dependency-free operational wargame engine. The whole thing
turns on one function:

    new_state, events = resolve(state, orders)

It is pure, it contains no randomness, and it is the only code in the project
allowed to change a game state. The server calls it once a round; a bot calls
it to look ahead; a replay calls it to reproduce a match exactly.
"""
from .constants import (KINDS, ORDERS, LINE, LIGHT, HORSE, GUNS, PIONEERS,
                        ADVANCE, ASSAULT, HOLD, SCREEN, SUPPLY, FORAGE, RECON,
                        PARLEY, RESERVE, AZURE, CRIMSON, MAX_ROUNDS)
from .hexmap import HexMap, generate
from .state import (GameState, Brigade, Region, new_game, match_summary,
                    validate_order_of_battle, DEFAULT_ORDER_OF_BATTLE)
from .orders import Order, sanitise, validate
from .resolve import resolve, supply_map
from .fog import visible, view, Intel, enemy_of
from . import bot
from . import corps
from . import coach

__all__ = [
    "KINDS", "ORDERS", "LINE", "LIGHT", "HORSE", "GUNS", "PIONEERS",
    "ADVANCE", "ASSAULT", "HOLD", "SCREEN", "SUPPLY", "FORAGE", "RECON",
    "PARLEY", "RESERVE", "AZURE", "CRIMSON", "MAX_ROUNDS",
    "HexMap", "generate", "GameState", "Brigade", "Region", "new_game",
    "match_summary", "validate_order_of_battle", "DEFAULT_ORDER_OF_BATTLE",
    "Order", "sanitise", "validate", "resolve", "supply_map",
    "visible", "view", "Intel", "enemy_of", "bot", "corps", "coach",
]
