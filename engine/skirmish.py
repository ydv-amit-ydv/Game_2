"""
The small game.

The full campaign grew nine orders, fourteen brigades, a points draft and a
supply network, and became a game you have to study before you can play it.
This is the same engine with almost all of that taken away:

    one player, three brigades, four orders, one objective, about three
    minutes.

The objective is a sentence: **take the enemy keep before round twelve.**
Nothing else wins, nothing else needs explaining, and the one idea worth
learning — that a brigade cut off from its supply dies without anyone
fighting it — is impossible to miss because it is the only thing that can
go wrong.

Everything here is a setup, not a rule. The resolution is the same
`resolve()` the full game uses, so anything learned here transfers.
"""
from .constants import (LINE, HORSE, PIONEERS, ADVANCE, ASSAULT, HOLD, SUPPLY,
                        PLAIN, WOOD, HILL, FORD, WATER, MOUNTAIN,
                        AZURE, CRIMSON, BRIGADE_STATS, SUPPLY_RANGE,
                        STARVE_LOSS, CONCENTRATION_BONUS)
from .hexmap import HexMap
from .state import Brigade, Region, GameState

# The four orders the small game offers, in the words it offers them.
# They map straight onto the full game's verbs, so nothing has to be
# unlearned later.
ORDERS = [
    {"verb": ADVANCE, "label": "MARCH",  "needsTarget": True,
     "blurb": "Move to next-door ground. Horse moves two."},
    {"verb": ASSAULT, "label": "ATTACK", "needsTarget": True,
     "blurb": "Take ground the enemy is on. Send two at once."},
    {"verb": HOLD,    "label": "DIG IN", "needsTarget": False,
     "blurb": "Stay put, dig in, recover strength."},
    {"verb": SUPPLY,  "label": "BUILD",  "needsTarget": False,
     "blurb": "Engineers only. Depot here — feeds 3 regions around it."},
]
ORDER_BY_VERB = {o["verb"]: o for o in ORDERS}

SKIRMISH_ROUNDS = 12
SKIRMISH_W, SKIRMISH_H = 7, 5

BRIGADES = (
    (LINE, "FOOT"),          # tough, slow, does the taking
    (HORSE, "HORSE"),        # fast, fragile, gets behind them
    (PIONEERS, "ENGINEERS"), # builds the depots that keep the other two alive
)


# Everything a player needs told to them in plain words, in one place, and
# served to the client so the numbers on screen can never drift from the
# numbers the engine actually uses.
GUIDE = {
    LINE: {
        "name": "FOOT",
        "is": "Your hammer.",
        "does": "The only brigade that can take ground and still be standing "
                "on it next round.",
        "watch": "Slow. One region a round, so decide early where it is going.",
    },
    HORSE: {
        "name": "HORSE",
        "is": "Your speed.",
        "does": "Two regions a round. Gets behind them, takes empty ground, "
                "and arrives where you are not expected.",
        "watch": "Weak standing still. Do not leave it somewhere it has to "
                 "defend.",
    },
    PIONEERS: {
        "name": "ENGINEERS",
        "is": "Your range.",
        "does": "BUILD puts a depot under its feet. A depot feeds everything "
                "within 3 regions of it, so this is how your army gets "
                "further than 3 regions from home.",
        "watch": "Barely fights. Keep it behind the other two.",
    },
}


def guide(state=None):
    """Brigade cards, with the live numbers from the engine."""
    out = []
    for kind, name in BRIGADES:
        st = BRIGADE_STATS[kind]
        g = GUIDE[kind]
        out.append({
            "kind": kind, "name": g["name"], "strength": st["strength"],
            "moves": st["pace"],
            "attack": ("full" if st["punch"] >= 1.0
                       else "weak" if st["punch"] < 0.6 else "fair"),
            "defend": ("strong" if st["guard"] >= 1.2
                       else "poor" if st["guard"] <= 0.6 else "fair"),
            "is": g["is"], "does": g["does"], "watch": g["watch"],
        })
    return out


def rules():
    """The three rules, with the engine's own numbers in them."""
    return [
        {"head": "Supply keeps you alive",
         "body": "Every brigade must be within %d regions of your KEEP, or of "
                 "a DEPOT. The shaded ground on the map is where you are fed."
                 % SUPPLY_RANGE},
        {"head": "Outside it you starve",
         "body": "A brigade out of supply loses %d strength every round and "
                 "nobody has to fight it. At 0 it is gone for good."
                 % STARVE_LOSS},
        {"head": "Engineers extend the map",
         "body": "BUILD drops a depot where the engineers stand — including "
                 "outside your supply. The shaded ground grows %d regions "
                 "around it, and your army can go further." % SUPPLY_RANGE},
        {"head": "Two at once is worth +%g" % CONCENTRATION_BONUS,
         "body": "Two brigades that ATTACK the same region in the same round "
                 "arrive as one column. One alone against a dug-in defender "
                 "usually bounces off."},
        {"head": "DIG IN to recover",
         "body": "A brigade that digs in while fed recovers strength and is "
                 "much harder to shift. It is not a wasted round."},
    ]


def _terrain(seed):
    """A small, readable, mirror-symmetric board.

    Deliberately plain. Every region a new player looks at should be
    obviously passable or obviously not, with no third category to learn."""
    import random
    rnd = random.Random(seed)
    w, h = SKIRMISH_W, SKIRMISH_H
    t = [PLAIN] * (w * h)
    mid, mid_row = w // 2, h // 2

    # a river down the spine with one crossing, so supply has a throat
    for r in range(h):
        t[r * w + mid] = WATER
    t[mid_row * w + mid] = FORD
    crossing = rnd.choice([r for r in range(h) if r != mid_row])
    t[crossing * w + mid] = FORD

    # a little rough ground on the left, mirrored to the right
    for r in range(h):
        for c in range(mid):
            if t[r * w + c] != PLAIN:
                continue
            roll = rnd.random()
            if roll < 0.16:
                t[r * w + c] = WOOD
            elif roll < 0.24:
                t[r * w + c] = HILL
    for r in range(h):
        for c in range(mid):
            if t[r * w + c] in (WOOD, HILL):
                t[r * w + (w - 1 - c)] = t[r * w + c]

    # the two keeps, and clear ground around them
    for col in (0, w - 1):
        t[mid_row * w + col] = PLAIN
        for rr in (mid_row - 1, mid_row + 1):
            if 0 <= rr < h and t[rr * w + col] == MOUNTAIN:
                t[rr * w + col] = PLAIN
    return t


def new_skirmish(seed=0):
    """One player, three brigades a side, one objective."""
    w, h = SKIRMISH_W, SKIRMISH_H
    terrain = _terrain(seed)
    mid_row = h // 2
    capitals = {AZURE: mid_row * w + 0, CRIMSON: mid_row * w + (w - 1)}
    # No hubs. The keep is the only thing worth having, so there is only one
    # sentence to read before you start.
    hexmap = HexMap(w, h, terrain, capitals, [])

    regions = [Region(i, terrain[i]) for i in range(w * h)]
    brigades = []
    bid = 0
    for side in (AZURE, CRIMSON):
        cap = capitals[side]
        key = (lambda r: r) if side == AZURE else hexmap.mirror
        spots = [cap] + sorted((r for r in hexmap.adj(cap)
                                if hexmap.passable(r)), key=key)
        for i, (kind, name) in enumerate(BRIGADES):
            brigades.append(Brigade(bid, side, kind, name,
                                    spots[i % len(spots)]))
            bid += 1
        regions[cap].owner = side

    st = GameState(hexmap, brigades, regions, seed)
    st.max_rounds = SKIRMISH_ROUNDS
    for b in st.brigades:
        st.regions[b.region].owner = b.side
    return st


def objective(state, side):
    """The one line shown at the top of the screen, and the only thing a
    player needs to hold in their head."""
    enemy_cap = state.map.capitals[CRIMSON if side == AZURE else AZURE]
    d = min([state.map.distance(b.region, enemy_cap)
             for b in state.living(side)] or [-1])
    left = SKIRMISH_ROUNDS - state.round + 1
    return {
        "text": "Take the enemy keep",
        "target": enemy_cap,
        "distance": d,
        "roundsLeft": max(0, left),
        "detail": ("%d region%s away, %d round%s left"
                   % (d, "" if d == 1 else "s", left, "" if left == 1 else "s")
                   if d >= 0 else "%d rounds left" % left),
    }


# ---------------------------------------------------------------- lessons
# Three scripted positions, each one screen, each teaching exactly one thing
# and then getting out of the way. A player who finishes these has met every
# idea the small game contains.
LESSONS = [
    {
        "id": "march",
        "title": "Marching",
        "teach": "Click a brigade, pick MARCH, click where it should go. "
                 "Then COMMIT. Every order happens at once when the clock "
                 "runs out.",
        "goal": "Get any brigade onto the red keep.",
        "rounds": 6,
        "enemy": False,
    },
    {
        "id": "supply",
        "title": "Supply",
        "teach": "Your brigades must stay within 3 regions of your keep or a "
                 "depot. Outside that they lose 2 strength a round and "
                 "nobody has to fight them. Your ENGINEERS can BUILD a depot "
                 "to move that line forward.",
        "goal": "Reach the red keep without losing a brigade to starvation.",
        "rounds": 9,
        "enemy": False,
    },
    {
        "id": "together",
        "title": "Two at once",
        "teach": "Two brigades that ATTACK the same region in the same round "
                 "arrive as one column and hit for +4. One brigade alone "
                 "against a dug-in defender usually bounces.",
        "goal": "Take the defended region with two brigades in one round.",
        "rounds": 8,
        "enemy": True,
    },
]


def lesson(index, seed=0):
    """Build the position for one lesson. Returns (state, lesson)."""
    spec = LESSONS[max(0, min(index, len(LESSONS) - 1))]
    st = new_skirmish(seed)
    st.max_rounds = spec["rounds"]

    if not spec["enemy"]:
        for b in st.living(CRIMSON):        # nobody shooting back yet
            b.alive = False

    if spec["id"] == "supply":
        # push the player's brigades out so the chain is the obvious problem
        cap = st.map.capitals[AZURE]
        far = sorted(st.map.within(cap, 2), key=lambda r: -st.map.within(cap, 2)[r])
        for i, b in enumerate(st.living(AZURE)):
            if far:
                b.region = far[i % len(far)]

    if spec["id"] == "together":
        # one dug-in defender on the ground between you and the keep
        foe = st.living(CRIMSON)[0]
        for other in st.living(CRIMSON)[1:]:
            other.alive = False
        mid = st.map.rid(SKIRMISH_W // 2, SKIRMISH_H // 2)
        foe.region = mid
        foe.strength = 10
        foe.entrenched = 2
        st.region(mid).owner = CRIMSON

    return st, spec
