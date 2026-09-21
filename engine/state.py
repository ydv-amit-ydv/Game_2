"""
Game state, and the order of battle that starts one.

The state is a plain data structure with no behaviour beyond copying and
serialising itself. Everything that changes it lives in resolve.py, so that
a round is always a pure function of (state, orders).
"""
import copy
import hashlib
import json

from .constants import (BRIGADE_STATS, DRAFT_BUDGET, DRAFT_BRIGADES, DRAFT_CAP,
                        KINDS, LINE, LIGHT, HORSE, GUNS, PIONEERS,
                        TERRAIN_FORAGE, AZURE, CRIMSON, MAX_ROUNDS,
                        CORPS_ORDER_OF_BATTLE, TILT_HUB, TILT_REGION,
                        TILT_STRENGTH)
from .hexmap import HexMap, generate


class Brigade:
    __slots__ = ("id", "side", "kind", "commander", "strength", "max_strength",
                 "region", "entrenched", "in_reserve", "supplied",
                 "forage_used", "alive", "balk_at", "balk_for", "corps")

    def __init__(self, bid, side, kind, commander, region, corps=False):
        st = BRIGADE_STATS[kind]
        self.id = bid
        self.side = side
        self.kind = kind
        self.commander = commander
        self.strength = st["strength"]
        self.max_strength = st["strength"]
        self.region = region
        self.entrenched = 0
        self.in_reserve = False
        self.supplied = True
        self.forage_used = 0
        self.alive = True
        # ground that threw this brigade back, and how long it remembers.
        # Without this a commander marches into the same wall every round
        # until the brigade is gone.
        self.balk_at = None
        self.balk_for = 0
        self.corps = corps

    @property
    def stats(self):
        return BRIGADE_STATS[self.kind]

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    @staticmethod
    def from_dict(d):
        b = Brigade.__new__(Brigade)
        for k in Brigade.__slots__:
            setattr(b, k, d[k])
        return b

    def __repr__(self):
        state = "" if self.alive else " BROKEN"
        return ("<%s %s %s str=%d r=%d%s>"
                % (self.commander, self.kind, self.side, self.strength,
                   self.region, state))


class Region:
    __slots__ = ("id", "owner", "depot", "works", "forage", "stripped")

    def __init__(self, rid, terrain):
        self.id = rid
        self.owner = None
        self.depot = None          # side that keeps a depot here
        self.works = 0             # pioneer fieldworks
        self.forage = TERRAIN_FORAGE.get(terrain, 0)
        self.stripped = False

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    @staticmethod
    def from_dict(d):
        r = Region.__new__(Region)
        for k in Region.__slots__:
            setattr(r, k, d[k])
        return r


class GameState:
    def __init__(self, hexmap, brigades, regions, seed=0):
        self.map = hexmap
        self.brigades = brigades          # list[Brigade], index == id
        self.regions = regions            # list[Region], index == region id
        self.seed = seed
        self.round = 1
        self.over = False
        self.winner = None
        self.verdict = ""
        self.hub_streak = {AZURE: 0, CRIMSON: 0}
        self.max_rounds = MAX_ROUNDS

    # ------------------------------------------------------------ lookups
    def brigade(self, bid):
        return self.brigades[bid]

    def region(self, rid):
        return self.regions[rid]

    def living(self, side=None):
        return [b for b in self.brigades
                if b.alive and (side is None or b.side == side)]

    def at(self, rid, side=None):
        return [b for b in self.brigades
                if b.alive and b.region == rid
                and (side is None or b.side == side)]

    def sides(self):
        return (AZURE, CRIMSON)

    def hubs_held(self, side):
        return [h for h in self.map.hubs if self.regions[h].owner == side]

    def regions_held(self, side):
        return [r for r in self.regions if r.owner == side]

    def strength(self, side):
        return sum(b.strength for b in self.living(side))

    def corps_of(self, side):
        return [b for b in self.living(side) if b.corps]

    def commanded(self, side):
        """Brigades a player (or a seat bot) holds -- everything but the corps."""
        return [b for b in self.living(side) if not b.corps]

    def tilt(self):
        """Who is ahead, and by how much, from -1 (Crimson) to +1 (Azure).

        The Reserve Corps reads this to decide whether to press or ease off,
        so it is deliberately simple and deliberately public: a player can
        work out the same number from what is on screen."""
        score = {}
        for side in self.sides():
            score[side] = (TILT_HUB * len(self.hubs_held(side))
                           + TILT_REGION * len(self.regions_held(side))
                           + TILT_STRENGTH * self.strength(side))
        total = score[AZURE] + score[CRIMSON]
        if total <= 0:
            return 0.0
        return (score[AZURE] - score[CRIMSON]) / total

    # ------------------------------------------------------------ plumbing
    def copy(self):
        s = GameState.__new__(GameState)
        s.map = self.map                          # immutable, shared by design
        s.brigades = [copy.copy(b) for b in self.brigades]
        s.regions = [copy.copy(r) for r in self.regions]
        s.seed = self.seed
        s.round = self.round
        s.over = self.over
        s.winner = self.winner
        s.verdict = self.verdict
        s.hub_streak = dict(self.hub_streak)
        s.max_rounds = self.max_rounds
        return s

    def to_dict(self):
        return {
            "map": self.map.to_dict(),
            "brigades": [b.to_dict() for b in self.brigades],
            "regions": [r.to_dict() for r in self.regions],
            "seed": self.seed, "round": self.round, "over": self.over,
            "winner": self.winner, "verdict": self.verdict,
            "hub_streak": {str(k): v for k, v in self.hub_streak.items()},
            "max_rounds": self.max_rounds,
        }

    @staticmethod
    def from_dict(d):
        s = GameState.__new__(GameState)
        s.map = HexMap.from_dict(d["map"])
        s.brigades = [Brigade.from_dict(x) for x in d["brigades"]]
        s.regions = [Region.from_dict(x) for x in d["regions"]]
        s.seed = d["seed"]
        s.round = d["round"]
        s.over = d["over"]
        s.winner = d["winner"]
        s.verdict = d["verdict"]
        s.hub_streak = {int(k): v for k, v in d["hub_streak"].items()}
        s.max_rounds = d.get("max_rounds", MAX_ROUNDS)
        return s

    def digest(self):
        """A stable fingerprint of the whole state. Two engines that agree
        on this agree on everything."""
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ------------------------------------------------------------------ setup
DEFAULT_ORDER_OF_BATTLE = (LINE, LINE, LIGHT, HORSE, PIONEERS)

COMMANDER_NAMES = {
    AZURE: ("VEGA", "BRINE", "MARROW", "KESTREL", "PIKE"),
    CRIMSON: ("HALLOW", "TOLL", "SPAR", "RIME", "GALL"),
}
CORPS_NAMES = ("RESERVE", "ENGINEERS")


def validate_order_of_battle(kinds):
    """Is this a legal draft? Returns (ok, reason)."""
    if len(kinds) != DRAFT_BRIGADES:
        return False, "an order of battle is %d brigades" % DRAFT_BRIGADES
    for k in kinds:
        if k not in KINDS:
            return False, "no such brigade: %s" % k
    for k in set(kinds):
        if kinds.count(k) > DRAFT_CAP[k]:
            return False, "at most %d %s" % (DRAFT_CAP[k], k)
    cost = sum(BRIGADE_STATS[k]["points"] for k in kinds)
    if cost > DRAFT_BUDGET:
        return False, "costs %d of %d points" % (cost, DRAFT_BUDGET)
    return True, ""


def new_game(seed=0, w=11, h=7, orders_of_battle=None, names=None, corps=True):
    """Lay out a fresh match. `orders_of_battle` is {side: [kind, ...]}.

    With `corps`, each side also fields the two-brigade Reserve Corps that
    the system commands. Both sides get the same one, so it never tilts the
    ground -- what it does with them is where the balancing happens."""
    hexmap = generate(seed, w, h)
    regions = [Region(i, hexmap.terrain[i]) for i in range(w * h)]

    oob = orders_of_battle or {}
    brigades = []
    bid = 0
    for side in (AZURE, CRIMSON):
        kinds = list(oob.get(side, DEFAULT_ORDER_OF_BATTLE))
        ok, why = validate_order_of_battle(kinds)
        if not ok:
            raise ValueError("side %d: %s" % (side, why))
        cap = hexmap.capitals[side]
        # Brigades muster at the capital and spill into whatever ground
        # around it will hold them. Crimson orders its muster ground by the
        # mirror of the region id, so brigade i of each army stands on
        # exactly the ground brigade i of the other army stands on,
        # reflected. Sorting both by raw id would quietly hand one side a
        # better opening.
        key = (lambda r: r) if side == AZURE else hexmap.mirror
        spots = [cap] + sorted((r for r in hexmap.adj(cap)
                                if hexmap.passable(r)), key=key)
        side_names = (names or {}).get(side) or COMMANDER_NAMES[side]
        for i, kind in enumerate(kinds):
            brigades.append(Brigade(bid, side, kind,
                                    side_names[i % len(side_names)],
                                    spots[i % len(spots)]))
            bid += 1
        if corps:
            for j, kind in enumerate(CORPS_ORDER_OF_BATTLE):
                brigades.append(Brigade(bid, side, kind, CORPS_NAMES[j],
                                        spots[(len(kinds) + j) % len(spots)],
                                        corps=True))
                bid += 1
        regions[cap].owner = side
        for r in hexmap.adj(cap):
            if hexmap.passable(r):
                regions[r].owner = side

    st = GameState(hexmap, brigades, regions, seed)
    for b in st.brigades:                       # muster ground is held ground
        st.regions[b.region].owner = b.side
    return st


def match_summary(state):
    """A one-line account of where a finished (or unfinished) match stands."""
    bits = []
    for side in (AZURE, CRIMSON):
        bits.append("%s: %d hubs, %d regions, %d strength"
                    % (side, len(state.hubs_held(side)),
                       len(state.regions_held(side)), state.strength(side)))
    tail = state.verdict or ("round %d of %d" % (state.round, MAX_ROUNDS))
    return " | ".join(bits) + " | " + tail
