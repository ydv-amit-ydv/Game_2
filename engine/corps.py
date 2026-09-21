"""
The Reserve Corps — two brigades a side that no player commands.

It exists to do two jobs with one mechanism.

**Keep a lopsided match honest.** A match decided by round four teaches
nobody anything, and a beating is not training. So the corps reads how far
its own side is ahead or behind and adjusts: pressing hard when its army is
losing, easing off and digging in when its army is winning. It never fights
its own side and it never throws a match — it leans.

**Show a learner what good command looks like.** Whatever the tilt, the
corps plays legibly: it keeps its supply, it concentrates with a neighbour
instead of attacking alone, it builds depots before it needs them. A player
who watches the RESERVE and ENGINEERS counters for one match has seen the
basic grammar of the game played correctly, without anyone lecturing them.

Every decision it makes comes back with a reason attached, so the trainer
can say *why* on screen. Nothing here is hidden: the intervention is
announced, because balancing a player cannot feel will always read as
cheating the moment they suspect it.
"""
from .constants import (ADVANCE, ASSAULT, HOLD, SCREEN, SUPPLY, FORAGE, RECON,
                        RESERVE, PIONEERS, WORKS_MAX,
                        CORPS_PRESS_AT, CORPS_EASE_AT, AZURE, CRIMSON)
from .bot import facing, _step_toward, _nearest
from .fog import visible, enemy_of
from .orders import Order, validate
from .resolve import supply_map

PRESSING, STEADY, EASING = "PRESSING", "STEADY", "EASING"


def posture(state, side):
    """Whether this side's corps presses, holds steady, or eases off."""
    tilt = state.tilt()
    mine = tilt if side == AZURE else -tilt
    if mine <= -CORPS_PRESS_AT:
        return PRESSING
    if mine >= CORPS_EASE_AT:
        return EASING
    return STEADY


def plan(state, side, seats=None):
    """Orders for this side's corps brigades, each with a stated reason.

    Returns (orders, notes) where notes is a list of
    {brigade, verb, why, posture} that the trainer surfaces verbatim."""
    face = facing(state, side)
    vis = visible(state, side)
    reach = supply_map(state, side)
    enemy = enemy_of(side)
    seen = [b for b in state.living(enemy) if b.region in vis]
    stance = posture(state, side)

    # where our own commanders are going, so the corps can arrive alongside
    friends = [b for b in state.commanded(side)]

    orders, notes = [], []
    mine = [b for b in state.corps_of(side)
            if seats is None or b.id in seats]
    for b in sorted(mine, key=lambda x: x.id):
        order, why = _one(state, b, stance, vis, reach, seen, friends, face)
        ok, _ = validate(state, order)
        if not ok:
            order, why = Order(b.id, HOLD), "held position"
        orders.append(order)
        notes.append({"brigade": b.id, "verb": order.verb,
                      "target": order.target, "why": why, "posture": stance})
    return orders, notes


def _one(state, b, stance, vis, reach, seen, friends, face):
    here = b.region
    r = state.region(here)
    adj = sorted(state.map.adj(here), key=face)
    near_enemy = [e for e in seen if e.region in set(adj) or e.region == here]

    # --- never let the demonstration starve ------------------------------
    if here not in reach:
        if r.forage > 0:
            return Order(b.id, FORAGE), "cut off, so it lives off the land"
        home, _ = _nearest(state, here, sorted(reach, key=face)
                           or [state.map.capitals[b.side]], face)
        step = _step_toward(state, b, home, face)
        if step is not None:
            return (Order(b.id, ADVANCE, step),
                    "falls back toward its own supply rather than starve")
        return Order(b.id, HOLD), "nowhere to go"

    # --- the engineers keep the whole army fed ---------------------------
    if b.kind == PIONEERS:
        if r.depot != b.side and reach.get(here, 0) >= 2:
            return (Order(b.id, SUPPLY),
                    "builds a depot here so the army can reach further")
        if r.depot == b.side and r.works < WORKS_MAX and near_enemy:
            return (Order(b.id, SUPPLY),
                    "raises fieldworks where the enemy is close")
        if stance == EASING:
            return Order(b.id, HOLD), "we are ahead, so it consolidates"
        goal = _forward_goal(state, b, friends, face)
        step = _step_toward(state, b, goal, face)
        if step is not None and not any(e.region == step for e in seen):
            return (Order(b.id, ADVANCE, step),
                    "moves up behind the line, a depot ahead of the need")
        return Order(b.id, HOLD), "stays a step behind the fighting"

    # --- easing off: we are winning, so stop pressing ---------------------
    if stance == EASING:
        if near_enemy:
            return (Order(b.id, RESERVE),
                    "we are ahead, so it waits rather than piles on")
        return Order(b.id, HOLD), "we are ahead, so it digs in and holds"

    # --- the line brigade: concentrate, never attack alone ----------------
    committed = _where_friends_are_going(state, b, friends, face)
    for target in committed:
        if target in state.map.within(here, b.stats["pace"]):
            return (Order(b.id, ASSAULT, target),
                    "arrives on the same ground as a friendly brigade, so the "
                    "two of them count as one column")

    if stance == PRESSING:
        goal = _forward_goal(state, b, friends, face)
        if goal is not None and goal in state.map.within(here, b.stats["pace"]):
            holders = [e for e in state.living()
                       if e.region == goal and e.side != b.side]
            if holders and goal != b.balk_at:
                return (Order(b.id, ASSAULT, goal),
                        "we are behind, so it goes at the objective")
            if not holders:
                return (Order(b.id, ADVANCE, goal),
                        "we are behind, so it takes ground while it is free")
        step = _step_toward(state, b, goal, face)
        if step is not None and step != here and step != b.balk_at:
            return (Order(b.id, ADVANCE, step), "pushes toward the objective")

    if near_enemy:
        return (Order(b.id, RESERVE),
                "stays coiled: anything that moves next to it gets countered "
                "at full weight")
    goal = _forward_goal(state, b, friends, face)
    step = _step_toward(state, b, goal, face)
    if step is not None and step != here and step != b.balk_at:
        return Order(b.id, ADVANCE, step), "closes up on the army"
    return Order(b.id, HOLD), "holds and entrenches"


def _where_friends_are_going(state, b, friends, face):
    """Ground a friendly brigade is standing next to and likely to contest.

    The corps cannot read anyone's orders -- it looks at the same map a
    player looks at, and infers. That is the whole coordination idea, played
    by the machine."""
    out = []
    for f in friends:
        if f.id == b.id:
            continue
        for rid in state.map.adj(f.region):
            if not state.map.passable(rid):
                continue
            hostile = [e for e in state.living()
                       if e.region == rid and e.side != b.side]
            if hostile or rid in state.map.hubs:
                out.append(rid)
    return sorted(set(out), key=face)


def _forward_goal(state, b, friends, face):
    targets = sorted((h for h in state.map.hubs
                      if state.region(h).owner != b.side), key=face)
    targets.append(state.map.capitals[enemy_of(b.side)])
    goal, _ = _nearest(state, b.region, targets, face)
    return goal
