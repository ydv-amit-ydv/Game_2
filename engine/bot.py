"""
A brigade commander that isn't a person.

Bots fill empty seats, so a match runs with two players or ten. Each bot
commands exactly one brigade and can see exactly what a human in that seat
would see, which keeps the game honest.

The interesting part is that bots coordinate the same way people have to:
they cannot talk either. They read the map, notice which objective a
neighbouring brigade is already committed to, and pile onto it — which is
precisely the concentration bonus doing its job. Nothing here reaches into
another brigade's orders; it only looks at where everyone is standing.
"""
from .constants import (ADVANCE, ASSAULT, HOLD, SCREEN, SUPPLY, FORAGE, RECON,
                        PARLEY, RESERVE, PIONEERS, LIGHT, HORSE, GUNS, LINE,
                        WORKS_MAX, AZURE, CRIMSON)
from .fog import visible, enemy_of
from .orders import Order, validate
from .resolve import supply_map


def facing(state, side):
    """A region ordering that means the same thing to both armies.

    Every tie in here used to break on raw region id, which points north-west
    for Azure and south-east for Crimson. On a mirror-symmetric map that is a
    free advantage to one side, and the balance runs showed it. Crimson reads
    the board through the mirror instead, so identical positions produce
    identical decisions."""
    if side == AZURE:
        return lambda rid: rid
    return state.map.mirror


def plan(state, side, seats=None):
    """Orders for every brigade on `side` that a bot is holding.

    `seats` is the set of brigade ids the bots are playing; None means all
    of them. Brigades are planned in id order and each one records what it
    committed to, so later brigades can converge on the same ground."""
    vis = visible(state, side)
    reach = supply_map(state, side)
    enemy = enemy_of(side)
    seen_enemies = [b for b in state.living(enemy) if b.region in vis]

    face = facing(state, side)
    targets = _objectives(state, side, vis, face)
    claimed = {}                      # region id -> how many of ours are coming
    orders = []

    mine = [b for b in state.living(side)
            if seats is None or b.id in seats]
    for b in sorted(mine, key=lambda x: x.id):
        o = _one(state, b, vis, reach, seen_enemies, targets, claimed, face)
        ok, _ = validate(state, o)
        if not ok:
            o = Order(b.id, HOLD)
        if o.verb in (ADVANCE, ASSAULT):
            claimed[o.target] = claimed.get(o.target, 0) + 1
        orders.append(o)
    return orders


def _objectives(state, side, vis, face):
    """Ground worth having, best first: hubs we do not hold, then the
    enemy capital."""
    out = sorted((h for h in state.map.hubs
                  if state.region(h).owner != side), key=face)
    out.append(state.map.capitals[enemy_of(side)])
    return out


def _nearest(state, src, targets, face):
    best, best_d = None, 10 ** 9
    for t in targets:
        d = state.map.distance(src, t)
        if d < 0:
            continue
        if d < best_d or (d == best_d and best is not None
                          and face(t) < face(best)):
            best, best_d = t, d
    return best, best_d


def _step_toward(state, brigade, dest, face):
    """The neighbour that gets us closest to dest. Ties break on the
    side-relative ordering so both armies make the same choice from the
    same shape of position."""
    if dest is None:
        return None
    here = brigade.region
    options = []
    for rid in state.map.adj(here):
        if not state.map.passable(rid):
            continue
        d = state.map.distance(rid, dest)
        if d < 0:
            continue
        options.append((d, face(rid), rid))
    if not options:
        return None
    options.sort()
    return options[0][2]


def _enemies_adjacent(state, brigade, seen_enemies):
    near = set(state.map.adj(brigade.region))
    return [e for e in seen_enemies if e.region in near]


def _one(state, b, vis, reach, seen_enemies, targets, claimed, face):
    here = b.region
    r = state.region(here)
    adj = sorted(state.map.adj(here), key=face)
    enemies_here = [e for e in seen_enemies if e.region == here]
    enemies_next = _enemies_adjacent(state, b, seen_enemies)
    supplied = here in reach

    # --- starving trumps everything -------------------------------------
    if not supplied:
        if r.forage > 0:
            return Order(b.id, FORAGE)
        home, _ = _nearest(state, here, sorted(reach, key=face) or
                           [state.map.capitals[b.side]], face)
        step = _step_toward(state, b, home, face)
        if step is not None:
            return Order(b.id, ADVANCE, step)
        return Order(b.id, HOLD)

    # --- pioneers keep the army fed --------------------------------------
    if b.kind == PIONEERS:
        if r.depot != b.side and reach.get(here, 0) >= 2:
            return Order(b.id, SUPPLY)          # push the chain outward
        if r.owner == b.side and r.depot == b.side and r.works < WORKS_MAX \
                and enemies_next:
            return Order(b.id, SUPPLY)          # dig in where it matters
        goal, _ = _nearest(state, here, targets, face)
        step = _step_toward(state, b, goal, face)
        # stay one region behind the fighting
        if step is not None and not any(e.region == step for e in seen_enemies):
            return Order(b.id, ADVANCE, step)
        return Order(b.id, HOLD)

    # --- light brigades are eyes, not a line -----------------------------
    if b.kind == LIGHT:
        dark = [rid for rid in state.map.within(here, b.stats["vision"])
                if rid not in vis and state.map.passable(rid)]
        if dark and not enemies_next:
            return Order(b.id, RECON, sorted(dark, key=face)[0])
        if enemies_next and b.strength <= 4:
            goal = min(enemies_next, key=lambda e: (face(e.region), e.id)).region
            return Order(b.id, SCREEN, goal)

    # --- free ground is worth taking without a fight ---------------------
    for rid in adj:
        rr = state.region(rid)
        if rr.owner is None and rid in vis and not state.at(rid) \
                and rid in state.map.hubs:
            return Order(b.id, PARLEY, rid)

    # --- an objective within reach ---------------------------------------
    pace = b.stats["pace"]
    in_reach = state.map.within(here, pace)
    for t in targets:
        if t not in in_reach or t == here:
            continue
        holders = [e for e in state.living() if e.region == t
                   and e.side != b.side]
        friends_coming = claimed.get(t, 0)
        if not holders:
            return Order(b.id, ADVANCE, t)
        # worth assaulting if we already outweigh them, or someone else is
        # committed and we can arrive together
        theirs = sum(e.strength for e in holders)
        ours = b.strength * b.stats["punch"]
        if ours > theirs * 0.9 or friends_coming:
            return Order(b.id, ASSAULT, t)

    # --- hold what we have when the enemy is on the doorstep -------------
    if r.owner == b.side and here in state.map.hubs and enemies_next:
        return Order(b.id, HOLD)
    if enemies_here or enemies_next:
        theirs = sum(e.strength for e in (enemies_here or enemies_next))
        if b.kind in (LINE, GUNS) and b.strength * b.stats["punch"] > theirs:
            tgt = min(enemies_next or enemies_here,
                      key=lambda e: (face(e.region), e.id)).region
            if tgt in in_reach:
                return Order(b.id, ASSAULT, tgt)
        if b.kind == HORSE:
            return Order(b.id, RESERVE)         # wait for them to commit
        return Order(b.id, HOLD)

    # --- otherwise, march ------------------------------------------------
    goal, _ = _nearest(state, here, targets, face)
    step = _step_toward(state, b, goal, face)
    if step is not None and step != here:
        return Order(b.id, ADVANCE, step)
    return Order(b.id, HOLD)
