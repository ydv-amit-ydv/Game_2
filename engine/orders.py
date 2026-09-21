"""
The nine things a brigade commander may do with a round.

An order is validated against the state the commander could actually see
when they wrote it, so validation never leaks information: it checks reach,
terrain and the brigade's own condition, never what is standing on the
target region.
"""
from .constants import (ADVANCE, ASSAULT, HOLD, SCREEN, SUPPLY, FORAGE, RECON,
                        PARLEY, RESERVE, ORDERS, TARGETED, MOVING, PIONEERS,
                        ORDER_SUPPLY_COST)


class Order:
    __slots__ = ("brigade", "verb", "target")

    def __init__(self, brigade, verb, target=None):
        self.brigade = brigade
        self.verb = verb
        self.target = target

    def to_dict(self):
        return {"brigade": self.brigade, "verb": self.verb,
                "target": self.target}

    @staticmethod
    def from_dict(d):
        return Order(d["brigade"], d["verb"], d.get("target"))

    def __repr__(self):
        return ("<%s b%d%s>" % (self.verb, self.brigade,
                                " -> %s" % self.target
                                if self.target is not None else ""))


def supply_cost(order, brigade):
    return ORDER_SUPPLY_COST[order.verb] + brigade.stats["appetite"]


def validate(state, order):
    """(ok, reason). A rejected order becomes HOLD rather than an error:
    a commander who writes nonsense stands still, they do not crash the war."""
    if order.verb not in ORDERS:
        return False, "no such order"

    if not (0 <= order.brigade < len(state.brigades)):
        return False, "no such brigade"
    b = state.brigade(order.brigade)
    if not b.alive:
        return False, "brigade is broken"

    if order.verb in TARGETED:
        t = order.target
        if t is None or not (0 <= t < len(state.regions)):
            return False, "that order needs a region"
        if not state.map.passable(t):
            return False, "cannot cross that ground"
        if t == b.region:
            return False, "already there"

    if order.verb in MOVING:
        reach = state.map.within(b.region, b.stats["pace"])
        if order.target not in reach:
            return False, "out of reach this round"

    if order.verb == SCREEN or order.verb == RECON:
        # you screen and scout what you can touch, not what you can imagine
        span = b.stats["pace"] if order.verb == SCREEN else b.stats["vision"]
        if order.target not in state.map.within(b.region, span):
            return False, "too far to reach"

    if order.verb == SUPPLY and b.kind != PIONEERS:
        return False, "only pioneers build depots"

    if order.verb == PARLEY:
        r = state.region(order.target)
        if r.owner is not None:
            return False, "that region already has a master"
        if order.target not in state.map.within(b.region, 1):
            return False, "parley is conducted face to face"

    if order.verb == FORAGE:
        r = state.region(b.region)
        if r.forage <= 0:
            return False, "nothing left to eat here"

    return True, ""


def sanitise(state, orders):
    """Turn whatever arrived over the wire into exactly one legal order per
    living brigade, in brigade-id sequence. This is what makes resolution
    deterministic no matter what order the packets turned up in."""
    by_brigade = {}
    rejected = []
    for o in orders:
        if not (0 <= o.brigade < len(state.brigades)):
            continue
        ok, why = validate(state, o)
        if ok:
            by_brigade[o.brigade] = o          # last legal order wins
        else:
            rejected.append((o, why))

    final = []
    for b in state.brigades:
        if not b.alive:
            continue
        final.append(by_brigade.get(b.id, Order(b.id, HOLD)))
    return final, rejected
