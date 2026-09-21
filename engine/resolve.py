"""
One round, resolved.

`resolve(state, orders) -> (new_state, events)` is a pure function. It takes
a copy of the state, never touches the original, and contains no randomness
whatsoever: two brigades of equal weight on equal ground always produce the
same result, on every machine, forever. That is what makes replays exact and
lets a bot search ahead by simply calling it.

Everything lands in the same instant. There is no turn order, and the code is
written so that no result can depend on the sequence orders arrived in:
battles are all decided against one pre-battle snapshot, then all losses are
applied, then everyone moves.
"""
from .constants import (ADVANCE, ASSAULT, HOLD, SCREEN, SUPPLY, FORAGE, RECON,
                        PARLEY, RESERVE, MOVING,
                        CONCENTRATION_BONUS, RESERVE_SUPPORT,
                        ENTRENCH_PER_HOLD, ENTRENCH_MAX, ENTRENCH_GUARD,
                        WORKS_GUARD, WORKS_MAX, TERRAIN_GUARD,
                        WINNER_LOSS_BASE, LOSER_LOSS_BASE, LOSER_LOSS_SLOPE,
                        LOSER_LOSS_MAX, BROKEN_AT, STANDOFF_LOSS, BALK_ROUNDS,
                        SUPPLY_RANGE, STARVE_LOSS, REFIT_GAIN,
                        MAX_ROUNDS, HUB_HOLD_TO_WIN, AZURE, CRIMSON)
from .orders import sanitise


# ---------------------------------------------------------------- supply
def supply_map(state, side):
    """Every region this side can push supply into: outward from the capital
    and from any depot, through passable ground the enemy is not standing on.

    Returns {region id: distance from the nearest source}."""
    enemy = CRIMSON if side == AZURE else AZURE
    blocked = {b.region for b in state.living(enemy)}

    sources = []
    cap = state.map.capitals.get(side)
    if cap is not None and cap not in blocked:
        sources.append(cap)
    for r in state.regions:
        if r.depot == side and r.id not in blocked:
            sources.append(r.id)

    reach = {}
    frontier = []
    for s in sorted(set(sources)):
        reach[s] = 0
        frontier.append(s)
    for d in range(1, SUPPLY_RANGE + 1):
        nxt = []
        for rid in frontier:
            for n in state.map.adj(rid):
                if n in reach or n in blocked or not state.map.passable(n):
                    continue
                reach[n] = d
                nxt.append(n)
        frontier = nxt
        if not frontier:
            break
    return reach


def _guard_multiplier(state, brigade):
    r = state.region(brigade.region)
    terrain = TERRAIN_GUARD.get(state.map.terrain[brigade.region], 0.0)
    return (brigade.stats["guard"]
            * (1.0 + terrain
               + ENTRENCH_GUARD * brigade.entrenched
               + WORKS_GUARD * (r.works if r.owner == brigade.side else 0)))


# ---------------------------------------------------------------- the round
def resolve(state, orders):
    s = state.copy()
    ev = []
    if s.over:
        return s, ev

    orders, rejected = sanitise(s, orders)
    om = {o.brigade: o for o in orders}
    for o, why in rejected:
        ev.append({"t": "rejected", "brigade": o.brigade, "verb": o.verb,
                   "why": why})

    # -- 1. standing orders that change nothing but the brigade itself ----
    for b in s.living():
        b.in_reserve = False
        if b.balk_for > 0:              # the memory of a repulse fades
            b.balk_for -= 1
            if b.balk_for == 0:
                b.balk_at = None
    for o in orders:
        b = s.brigade(o.brigade)
        if o.verb == RESERVE:
            b.in_reserve = True
            ev.append({"t": "reserve", "brigade": b.id, "region": b.region})
        elif o.verb == HOLD:
            if b.entrenched < ENTRENCH_MAX:
                b.entrenched += ENTRENCH_PER_HOLD
        else:
            b.entrenched = 0                    # movement undoes spadework

    # -- 2. pioneers build ------------------------------------------------
    for o in orders:
        if o.verb != SUPPLY:
            continue
        b = s.brigade(o.brigade)
        r = s.region(b.region)
        if r.depot != b.side:
            r.depot = b.side
            ev.append({"t": "depot", "brigade": b.id, "region": r.id,
                       "side": b.side})
        elif r.works < WORKS_MAX:
            r.works += 1
            ev.append({"t": "works", "brigade": b.id, "region": r.id,
                       "level": r.works})

    # -- 3. scouting, then parley, which is also simultaneous -------------
    for o in orders:
        if o.verb == RECON:
            b = s.brigade(o.brigade)
            ev.append({"t": "recon", "brigade": b.id, "region": o.target,
                       "side": b.side})

    # Every approach to a neutral region is made in the same instant. If both
    # armies court the same ground it stays neutral -- letting the first
    # order in the list take it would decide the centre hub by brigade
    # number, which is not a rule anyone agreed to.
    suitors = {}
    for o in orders:
        if o.verb == PARLEY:
            b = s.brigade(o.brigade)
            suitors.setdefault(o.target, {}).setdefault(b.side, []).append(b.id)
    for rid in sorted(suitors):
        r = s.region(rid)
        if r.owner is not None or s.at(rid):
            continue
        claims = suitors[rid]
        if len(claims) > 1:
            # Both armies sent envoys, so the region keeps its independence.
            # Each brigade remembers being rebuffed, or it will spend the
            # rest of the campaign knocking on the same door -- it cannot
            # see the rival envoy, only the closed door.
            for bids in claims.values():
                for bid in bids:
                    s.brigade(bid).balk_at = rid
                    s.brigade(bid).balk_for = BALK_ROUNDS
            ev.append({"t": "parley_contested", "region": rid,
                       "sides": sorted(claims)})
            continue
        side = next(iter(claims))
        r.owner = side
        ev.append({"t": "parley", "brigade": min(claims[side]), "region": rid,
                   "side": side})

    # -- 4. screens, then movement intents --------------------------------
    screened = {}
    for o in orders:
        if o.verb == SCREEN:
            screened.setdefault(o.target, set()).add(s.brigade(o.brigade).side)

    intent = {}
    for o in orders:
        if o.verb not in MOVING:
            continue
        b = s.brigade(o.brigade)
        blockers = screened.get(o.target, set())
        if o.verb == ADVANCE and any(x != b.side for x in blockers):
            ev.append({"t": "screened", "brigade": b.id, "region": o.target})
            continue                            # an advance is turned away
        intent[b.id] = o.target

    # -- 5. work out who meets whom, against one frozen snapshot ----------
    incoming = {}
    for bid, dest in sorted(intent.items()):
        incoming.setdefault(dest, {}).setdefault(s.brigade(bid).side, []).append(bid)

    staying = {}
    for b in s.living():
        if b.id in intent:
            continue
        staying.setdefault(b.region, {}).setdefault(b.side, []).append(b.id)

    contested = []
    for rid in sorted(set(list(incoming) + list(staying))):
        sides = set(incoming.get(rid, {})) | set(staying.get(rid, {}))
        if len(sides) > 1:
            contested.append(rid)

    # reserves lend their weight to a neighbour's fight; each one can only
    # be in one place, so it backs the lowest-numbered region it borders
    support = {}
    fighting = set()
    for rid in contested:
        for side, ids in list(incoming.get(rid, {}).items()) + \
                         list(staying.get(rid, {}).items()):
            fighting.update(ids)
    for b in sorted(s.living(), key=lambda x: x.id):
        if not b.in_reserve or b.id in fighting:
            continue
        for rid in sorted(state.map.adj(b.region)):
            if rid not in contested:
                continue
            sides = set(incoming.get(rid, {})) | set(staying.get(rid, {}))
            if b.side in sides:
                support.setdefault(rid, {}).setdefault(b.side, []).append(b.id)
                break

    # -- 6. decide every battle before applying anything ------------------
    verdicts = []
    for rid in contested:
        power = {}
        detail = {}
        for side in s.sides():
            movers = incoming.get(rid, {}).get(side, [])
            holders = staying.get(rid, {}).get(side, [])
            backers = support.get(rid, {}).get(side, [])
            if not (movers or holders or backers):
                continue
            p = 0.0
            for bid in movers:
                b = s.brigade(bid)
                p += b.strength * b.stats["punch"]
            for bid in holders:
                b = s.brigade(bid)
                p += b.strength * _guard_multiplier(s, b)
            for bid in backers:
                b = s.brigade(bid)
                p += b.strength * b.stats["punch"] * RESERVE_SUPPORT
            conc = CONCENTRATION_BONUS * max(0, len(movers) - 1)
            p += conc
            power[side] = p
            detail[side] = {"movers": movers, "holders": holders,
                            "reserves": backers, "concentration": conc,
                            "power": round(p, 2)}
        if len(power) < 2:
            continue

        ranked = sorted(power.items(), key=lambda kv: (-kv[1], kv[0]))
        (win_side, win_p), (lose_side, lose_p) = ranked[0], ranked[1]
        holders = [sd for sd in power if staying.get(rid, {}).get(sd)]

        if win_p == lose_p:
            if len(holders) == 1:
                # a dead heat goes to whoever was already standing there
                win_side = holders[0]
                lose_side = [sd for sd in power if sd != win_side][0]
                win_p, lose_p = power[win_side], power[lose_side]
            else:
                # neither of them held it and neither of them outweighed the
                # other: the ground stays contested and everybody falls back
                verdicts.append({"region": rid, "standoff": True,
                                 "frac": {sd: STANDOFF_LOSS for sd in power},
                                 "detail": detail})
                ev.append({"t": "standoff", "region": rid,
                           "power": {k: round(v, 2) for k, v in power.items()},
                           "detail": detail})
                continue

        ratio = win_p / lose_p if lose_p > 0 else 99.0
        win_frac = min(0.60, WINNER_LOSS_BASE * (lose_p / win_p)) if win_p else 0.0
        lose_frac = min(LOSER_LOSS_MAX,
                        LOSER_LOSS_BASE + LOSER_LOSS_SLOPE * (ratio - 1.0))
        verdicts.append({"region": rid, "winner": win_side, "loser": lose_side,
                         "frac": {win_side: win_frac, lose_side: lose_frac},
                         "detail": detail})
        ev.append({"t": "battle", "region": rid, "winner": win_side,
                   "loser": lose_side,
                   "power": {k: round(v, 2) for k, v in power.items()},
                   "concentration": detail[win_side]["concentration"],
                   "detail": detail})

    # -- 7. apply every loss ----------------------------------------------
    for v in verdicts:
        rid = v["region"]
        for side, frac in sorted(v["frac"].items()):
            d = v["detail"].get(side)
            if not d:
                continue
            for bid in d["movers"] + d["holders"] + d["reserves"]:
                b = s.brigade(bid)
                hit = int(round(b.strength * frac))
                # A real engagement always costs somebody something, so a
                # battle never rounds down to nothing. A stand-off is not an
                # engagement -- rounding it up to 1 put a floor under the
                # cost of contact and ground small brigades away anyway.
                if (frac > 0 and hit == 0 and b.strength > 0
                        and not v.get("standoff")):
                    hit = 1
                b.strength = max(0, b.strength - hit)
                if hit:
                    ev.append({"t": "losses", "brigade": bid, "region": rid,
                               "lost": hit, "left": b.strength})

    # -- 8. move the survivors --------------------------------------------
    # whose movers bounce: the beaten side, or everyone after a stand-off
    bounce = {}
    lost_at = {}
    won_at = {}
    for v in verdicts:
        if v.get("standoff"):
            bounce[v["region"]] = set(v["frac"])
        else:
            bounce[v["region"]] = {v["loser"]}
            lost_at[v["region"]] = v["loser"]
            won_at[v["region"]] = v["winner"]

    for bid, dest in sorted(intent.items()):
        b = s.brigade(bid)
        if not b.alive or b.strength < BROKEN_AT:
            continue
        if b.side in bounce.get(dest, ()):
            b.balk_at = dest
            b.balk_for = BALK_ROUNDS
            ev.append({"t": "repulsed", "brigade": bid, "region": dest,
                       "back": b.region})
            continue                            # bounced back to where it set off
        src = b.region
        b.region = dest
        ev.append({"t": "move", "brigade": bid, "from": src, "to": dest})

    for rid, loser in sorted(lost_at.items()):
        for bid in staying.get(rid, {}).get(loser, []):
            b = s.brigade(bid)
            if not b.alive or b.strength < BROKEN_AT:
                continue
            dest = _retreat(s, b, won_at)
            if dest is None:
                b.alive = False
                ev.append({"t": "destroyed", "brigade": bid, "region": rid,
                           "why": "nowhere to fall back to"})
            else:
                b.region = dest
                b.entrenched = 0
                ev.append({"t": "retreat", "brigade": bid, "from": rid,
                           "to": dest})

    for b in s.brigades:
        if b.alive and b.strength < BROKEN_AT:
            b.alive = False
            b.strength = 0
            ev.append({"t": "broken", "brigade": b.id, "region": b.region})

    # -- 9. who holds what -------------------------------------------------
    for r in s.regions:
        here = s.at(r.id)
        if not here:
            continue
        sides = {b.side for b in here}
        if len(sides) == 1:
            side = sides.pop()
            if r.owner != side:
                r.owner = side
                r.works = 0                     # their fieldworks, not yours
                ev.append({"t": "capture", "region": r.id, "side": side})

    # -- 10. eat, or do not ------------------------------------------------
    for side in s.sides():
        reach = supply_map(s, side)
        for b in s.living(side):
            b.supplied = b.region in reach
            if b.supplied:
                if om.get(b.id) and om[b.id].verb == HOLD:
                    b.strength = min(b.max_strength, b.strength + REFIT_GAIN)
                continue
            r = s.region(b.region)
            foraging = om.get(b.id) and om[b.id].verb == FORAGE
            if foraging and r.forage > 0:
                r.forage -= 1
                b.forage_used += 1
                if r.forage == 0:
                    r.stripped = True
                ev.append({"t": "forage", "brigade": b.id, "region": r.id,
                           "left": r.forage})
                continue
            b.strength = max(0, b.strength - STARVE_LOSS)
            ev.append({"t": "starve", "brigade": b.id, "region": b.region,
                       "lost": STARVE_LOSS, "left": b.strength})
            if b.strength < BROKEN_AT:
                b.alive = False
                ev.append({"t": "broken", "brigade": b.id, "region": b.region})

    # -- 11. is it over? ---------------------------------------------------
    _judge(s, ev)
    if not s.over:
        s.round += 1
    return s, ev


def _retreat(state, brigade, won_at):
    """Somewhere to fall back to: your own ground first, then anywhere the
    enemy is not and did not just take."""
    enemy_here = {b.region for b in state.living()
                  if b.side != brigade.side}
    options = []
    for rid in sorted(state.map.adj(brigade.region)):
        if not state.map.passable(rid):
            continue
        if rid in enemy_here:
            continue
        if won_at.get(rid) not in (None, brigade.side):
            continue
        own = state.region(rid).owner == brigade.side
        options.append((0 if own else 1, rid))
    if not options:
        return None
    options.sort()
    return options[0][1]


def _judge(state, ev):
    """Win conditions, checked in the order a commander would care about."""
    for side in state.sides():
        enemy = CRIMSON if side == AZURE else AZURE
        cap = state.map.capitals[enemy]
        if state.region(cap).owner == side:
            _finish(state, ev, side, "took the enemy capital")
            return

    # A board with no hubs on it (the small game) has no hub victory. Without
    # this guard "held every hub" is trivially true of nobody holding none.
    for side in state.sides():
        if state.map.hubs and \
                len(state.hubs_held(side)) == len(state.map.hubs):
            state.hub_streak[side] += 1
        else:
            state.hub_streak[side] = 0
    for side in state.sides():
        if state.hub_streak[side] >= HUB_HOLD_TO_WIN:
            _finish(state, ev, side, "held every supply hub for %d rounds"
                    % HUB_HOLD_TO_WIN)
            return

    alive = [side for side in state.sides() if state.living(side)]
    if len(alive) == 1:
        _finish(state, ev, alive[0], "the other army no longer exists")
        return
    if not alive:
        _finish(state, ev, None, "both armies destroyed each other")
        return

    if state.round >= state.max_rounds:
        score = {}
        for side in state.sides():
            score[side] = (len(state.hubs_held(side)),
                           len(state.regions_held(side)),
                           state.strength(side))
        ranked = sorted(score.items(), key=lambda kv: (-kv[1][0], -kv[1][1],
                                                       -kv[1][2], kv[0]))
        if ranked[0][1] == ranked[1][1]:
            _finish(state, ev, None, "the campaign ends level")
        else:
            _finish(state, ev, ranked[0][0], "ahead on hubs when time ran out")


def _finish(state, ev, winner, why):
    state.over = True
    state.winner = winner
    state.verdict = why
    ev.append({"t": "victory", "side": winner, "why": why,
               "round": state.round})
