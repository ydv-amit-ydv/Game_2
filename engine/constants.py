"""
Tunable numbers for THE IRON COMPACT.

Everything the designer might want to argue about lives here, so that
balance is a data change rather than a code change. Nothing in this file
imports anything from the rest of the engine.
"""

# ---------------------------------------------------------------- brigades
LINE, LIGHT, HORSE, GUNS, PIONEERS = "LINE", "LIGHT", "HORSE", "GUNS", "PIONEERS"
KINDS = (LINE, LIGHT, HORSE, GUNS, PIONEERS)

# strength   how many men it starts with, and the ceiling it recovers toward
# pace       regions it may cross in one round
# vision     how far it sees through the fog
# appetite   supply drawn per round; a hungry brigade is a liability
# punch      multiplier when it is the one attacking
# guard      multiplier when it is the one being attacked
# points     cost in the order-of-battle draft
BRIGADE_STATS = {
    LINE:     {"strength": 12, "pace": 1, "vision": 1, "appetite": 2,
               "punch": 1.00, "guard": 1.25, "points": 4},
    LIGHT:    {"strength": 6,  "pace": 2, "vision": 3, "appetite": 1,
               "punch": 0.60, "guard": 0.80, "points": 2},
    HORSE:    {"strength": 7,  "pace": 2, "vision": 2, "appetite": 2,
               "punch": 0.90, "guard": 0.50, "points": 3},
    GUNS:     {"strength": 8,  "pace": 1, "vision": 1, "appetite": 3,
               "punch": 1.60, "guard": 0.70, "points": 5},
    PIONEERS: {"strength": 5,  "pace": 1, "vision": 1, "appetite": 1,
               "punch": 0.40, "guard": 1.00, "points": 3},
}

DRAFT_BUDGET = 16
DRAFT_BRIGADES = 5
# at most this many of one kind in a single order of battle
DRAFT_CAP = {LINE: 2, LIGHT: 2, HORSE: 2, GUNS: 1, PIONEERS: 1}

# ---------------------------------------------------------------- terrain
PLAIN, WOOD, HILL, FORD, MOUNTAIN, WATER = (
    "PLAIN", "WOOD", "HILL", "FORD", "MOUNTAIN", "WATER")

PASSABLE = (PLAIN, WOOD, HILL, FORD)

# what the ground is worth to whoever is standing on it
TERRAIN_GUARD = {PLAIN: 0.00, WOOD: 0.15, HILL: 0.30, FORD: 0.10}
# how much it costs to see past, and to forage in
TERRAIN_FORAGE = {PLAIN: 3, WOOD: 2, HILL: 1, FORD: 2}
# woods and hills block line of sight into the next region
TERRAIN_BLOCKS_SIGHT = (WOOD, HILL, MOUNTAIN)

# ---------------------------------------------------------------- orders
ADVANCE, ASSAULT, HOLD, SCREEN, SUPPLY, FORAGE, RECON, PARLEY, RESERVE = (
    "ADVANCE", "ASSAULT", "HOLD", "SCREEN", "SUPPLY", "FORAGE", "RECON",
    "PARLEY", "RESERVE")

ORDERS = (ADVANCE, ASSAULT, HOLD, SCREEN, SUPPLY, FORAGE, RECON, PARLEY,
          RESERVE)

# orders that name a region
TARGETED = (ADVANCE, ASSAULT, SCREEN, RECON, PARLEY)
# orders that move the brigade
MOVING = (ADVANCE, ASSAULT)

# supply drawn on top of appetite, per order
ORDER_SUPPLY_COST = {
    ADVANCE: 1, ASSAULT: 3, HOLD: 0, SCREEN: 1, SUPPLY: 2,
    FORAGE: 0, RECON: 1, PARLEY: 2, RESERVE: 0,
}

# ---------------------------------------------------------------- combat
# Two brigades on the same ground in the same round arrive as one column.
# This is the whole coordination mechanic: it is paid for by the orders
# themselves, never by anyone announcing anything.
CONCENTRATION_BONUS = 4.0

ENTRENCH_PER_HOLD = 1
ENTRENCH_MAX = 3
ENTRENCH_GUARD = 0.12          # per level

WORKS_GUARD = 0.20             # per level of pioneer fieldworks
WORKS_MAX = 2

# a coiled brigade lends its full attacking weight to a neighbour's defence
RESERVE_SUPPORT = 1.00

# losses, as a fraction of the strength brought to the field
WINNER_LOSS_BASE = 0.20
LOSER_LOSS_BASE = 0.38
LOSER_LOSS_SLOPE = 0.22
LOSER_LOSS_MAX = 0.85

# Two forces of exactly equal weight meeting on ground neither of them
# held leave it contested and empty. Awarding a dead heat to anyone means
# awarding it by side number, and the centre hub sits on the map's axis of
# symmetry, so that one arbitrary rule decided whole campaigns.
# Kept deliberately cheap. A stand-off changes nothing on the map, so
# billing both sides heavily for it turns a locked position into a mutual
# suicide pact: neither army can take the ground, and both bleed out
# probing it. Contact should cost something, not everything.
STANDOFF_LOSS = 0.05

# How long a brigade remembers being thrown off a piece of ground. It will
# not walk back into it unaided within this many rounds -- it needs another
# brigade alongside, which is what concentration is for.
BALK_ROUNDS = 4

# a brigade below this is broken and leaves the field for good
BROKEN_AT = 1

# ---------------------------------------------------------------- supply
SUPPLY_RANGE = 3               # regions from a capital or depot
DEPOT_BUILD_ROUNDS = 1         # pioneers only
STARVE_LOSS = 2                # strength lost per round out of supply
FORAGE_ROUNDS = 2              # rounds a region will feed a brigade
REFIT_GAIN = 1                 # strength recovered by HOLD while supplied

# ---------------------------------------------------------------- signals
SIGNALS_PER_ROUND = 3
SIGNAL_KINDS = ("ATTACK", "DEFEND", "DANGER", "NEED")

# ---------------------------------------------------------------- victory
MAX_ROUNDS = 15
HUBS = 3
HUB_HOLD_TO_WIN = 2            # consecutive rounds holding every hub

# ---------------------------------------------------------------- sides
AZURE, CRIMSON = 0, 1
SIDE_NAMES = {AZURE: "AZURE PACT", CRIMSON: "CRIMSON HOST"}
