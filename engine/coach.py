"""
The trainer layer.

Two jobs, both aimed at the same thing: making cause and effect visible.

**Before you commit**, it reads the order you are about to give and says what
it will cost you next round — that your guns will be out of supply, that you
are walking back into ground that already threw you off, that you are going
in alone when a neighbour is going to the same place. It warns. It never
decides, and it never picks for you. A trainer that plays the game for you
trains nothing.

**After the round**, it explains what actually happened and, where it can,
*when it started*. Losing a brigade in round nine because a road was cut in
round six is the single most common way this game is opaque, and an opaque
game is a drain rather than a training. So the room keeps a small ledger of
when each brigade fell out of supply, and the coach reaches back into it.

Nothing here changes the rules. Every function is read-only over the state.
"""
from .constants import (ADVANCE, ASSAULT, HOLD, SCREEN, SUPPLY, FORAGE, RECON,
                        PARLEY, RESERVE, MOVING, PIONEERS, GUNS, HORSE, LIGHT,
                        STARVE_LOSS, CONCENTRATION_BONUS, SIDE_NAMES,
                        AZURE, CRIMSON)
from .fog import visible, enemy_of
from .resolve import supply_map

# severity, lowest first -- the client colours them
NOTE, CARE, RISK = "note", "care", "risk"


def warn(state, brigade, order, side=None):
    """What this order is likely to cost. Returns [{level, text}], worst
    first. Empty means the coach has nothing useful to add, which is the
    normal case for a sound order."""
    side = brigade.side if side is None else side
    out = []
    reach = supply_map(state, side)
    vis = visible(state, side)
    enemy = enemy_of(side)
    seen = [b for b in state.living(enemy) if b.region in vis]
    dest = order.target if order.verb in MOVING else brigade.region

    # --- supply, which is what actually kills brigades -------------------
    if order.verb in MOVING and dest is not None:
        if dest not in reach:
            out.append({"level": RISK, "text":
                        "That ground is outside your supply. %s loses %d "
                        "strength a round out there unless it forages."
                        % (brigade.kind.title(), STARVE_LOSS)})
        elif reach.get(dest, 0) >= 3:
            out.append({"level": CARE, "text":
                        "That is the far edge of your supply. One region "
                        "further and the chain snaps."})
    if brigade.region not in reach and order.verb not in (FORAGE,) \
            and order.verb not in MOVING:
        r = state.region(brigade.region)
        if r.forage > 0:
            out.append({"level": RISK, "text":
                        "You are cut off and standing still. FORAGE would "
                        "feed you this round; holding costs %d." % STARVE_LOSS})
        else:
            out.append({"level": RISK, "text":
                        "You are cut off and this ground is stripped bare. "
                        "Move toward your own supply or starve."})

    # --- the guns are a special case, and new players always lose them ---
    if brigade.kind == GUNS and order.verb in MOVING and dest is not None:
        if reach.get(dest) is None:
            out.append({"level": RISK, "text":
                        "Guns eat 3 supply a round. Taking them out of the "
                        "chain is how artillery is usually lost."})

    # --- walking back into the same wall ---------------------------------
    # Being thrown off is a fact, so this always fires. Whether a neighbour
    # happens to be beside the same ground only changes how loudly.
    if order.verb in MOVING and dest == brigade.balk_at:
        friends = _friends_heading_for(state, brigade, dest)
        if friends:
            out.append({"level": CARE, "text":
                        "That ground threw you off already. %s is beside it "
                        "too -- going in together is what changes the answer."
                        % friends[0].commander})
        else:
            out.append({"level": RISK, "text":
                        "That ground threw you off already. Going back alone "
                        "gets the same answer -- take somebody with you."})

    # --- attacking alone when the bonus is right there -------------------
    if order.verb == ASSAULT and dest is not None:
        holders = [e for e in state.living()
                   if e.region == dest and e.side != brigade.side]
        theirs = sum(e.strength for e in holders)
        ours = brigade.strength * brigade.stats["punch"]
        friends = _friends_heading_for(state, brigade, dest)
        # Being outweighed is arithmetic, not a guess, so it is always said.
        if holders and ours < theirs:
            out.append({"level": RISK, "text":
                        "You are lighter than what is holding it (%.0f "
                        "against %d). A second brigade on the same ground is "
                        "worth +%g." % (ours, theirs, CONCENTRATION_BONUS)})
        if holders and friends:
            out.append({"level": NOTE, "text":
                        "%s is beside that ground too. Arriving together is "
                        "worth +%g." % (friends[0].commander,
                                        CONCENTRATION_BONUS)})

    # --- using a brigade against its nature ------------------------------
    if order.verb == ASSAULT and brigade.kind in (LIGHT, PIONEERS):
        out.append({"level": CARE, "text":
                    "%s hits at %g of its weight. It screens and scouts far "
                    "better than it attacks." % (brigade.kind.title(),
                                                 brigade.stats["punch"])})
    if order.verb == HOLD and brigade.kind == HORSE and _enemy_near(
            state, brigade, seen):
        out.append({"level": CARE, "text":
                    "Horse defends at half weight. RESERVE lets it counter "
                    "at full weight instead of being caught standing."})

    # --- doing nothing while the map moves -------------------------------
    if order.verb == HOLD and not _enemy_near(state, brigade, seen) \
            and brigade.strength >= brigade.max_strength:
        out.append({"level": NOTE, "text":
                    "Nothing is near you and you are at full strength. "
                    "Holding here spends a round for nothing."})

    order_rank = {RISK: 0, CARE: 1, NOTE: 2}
    out.sort(key=lambda w: order_rank[w["level"]])
    return out[:3]


def _friends_heading_for(state, brigade, dest):
    """Friendly brigades standing next to the same ground. The coach can
    only see what the player can see, so this is proximity, not orders."""
    if dest is None:
        return []
    near = set(state.map.adj(dest)) | {dest}
    return [b for b in state.living(brigade.side)
            if b.id != brigade.id and b.region in near]


def _enemy_near(state, brigade, seen):
    near = set(state.map.adj(brigade.region)) | {brigade.region}
    return any(e.region in near for e in seen)


# ---------------------------------------------------------------- after
def explain(before, after, events, side, ledger=None):
    """Plain language for what just happened to this side, worst first.

    `ledger` is the room's record of {brigade id: round it lost supply},
    which is what lets a starvation in round nine name the road that was
    cut in round six."""
    out = []
    mine = {b.id for b in before.brigades if b.side == side}

    for e in events:
        if e["t"] == "battle" and side in (e["winner"], e["loser"]):
            won = e["winner"] == side
            conc = e.get("concentration") or 0
            if won and conc:
                out.append({"level": NOTE, "text":
                            "You carried region %d because two brigades "
                            "arrived on it together -- that was +%g of the "
                            "%.0f you brought."
                            % (e["region"], conc, e["power"].get(side, 0))})
            elif won:
                out.append({"level": NOTE, "text":
                            "You carried region %d, %.0f against %.0f."
                            % (e["region"], e["power"].get(side, 0),
                               e["power"].get(enemy_of(side), 0))})
            else:
                theirs = e["power"].get(enemy_of(side), 0)
                ours = e["power"].get(side, 0)
                gap = theirs - ours
                tail = (" A second brigade on that ground would have been "
                        "worth +%g." % CONCENTRATION_BONUS
                        if gap < CONCENTRATION_BONUS * 1.5 else "")
                out.append({"level": CARE, "text":
                            "You were thrown off region %d, %.0f against "
                            "%.0f.%s" % (e["region"], ours, theirs, tail)})

        elif e["t"] == "standoff":
            out.append({"level": NOTE, "text":
                        "Region %d was a dead heat, so nobody took it. Equal "
                        "weight never wins ground." % e["region"]})

        elif e["t"] == "starve" and e["brigade"] in mine:
            b = after.brigade(e["brigade"])
            since = (ledger or {}).get(e["brigade"])
            when = (" The chain to it broke in round %d." % since
                    if since and since < before.round else "")
            out.append({"level": RISK, "text":
                        "%s is starving at region %d, down to %d.%s"
                        % (b.commander, e["region"], e["left"], when)})

        elif e["t"] == "broken" and e["brigade"] in mine:
            b = after.brigade(e["brigade"])
            since = (ledger or {}).get(e["brigade"])
            why = (" It had been out of supply since round %d." % since
                   if since else "")
            out.append({"level": RISK, "text":
                        "%s is gone.%s" % (b.commander, why)})

        elif e["t"] == "depot" and e["side"] == side:
            out.append({"level": NOTE, "text":
                        "A depot at region %d -- your army reaches three "
                        "regions further from it now." % e["region"]})

        elif e["t"] == "parley_contested":
            out.append({"level": NOTE, "text":
                        "Both armies courted region %d, so it stayed neutral. "
                        "Courting contested ground wastes the round."
                        % e["region"]})

    rank = {RISK: 0, CARE: 1, NOTE: 2}
    out.sort(key=lambda w: rank[w["level"]])
    return out[:5]


def track_supply(state, ledger):
    """Update the room's ledger of when each brigade fell out of supply.
    Call once per round, after resolving."""
    ledger = dict(ledger or {})
    for b in state.brigades:
        if not b.alive:
            continue
        if b.supplied:
            ledger.pop(b.id, None)
        else:
            ledger.setdefault(b.id, state.round)
    return ledger


def opening_brief(state, side):
    """The one thing worth saying before a match starts."""
    hubs = len(state.map.hubs)
    return ("Three hubs decide this: hold every one of them for two rounds "
            "and it is over. Your supply reaches three regions from your "
            "capital and from any depot the engineers build, and a brigade "
            "outside it loses %d strength a round. Two brigades that attack "
            "the same ground in the same round count as one column."
            % STARVE_LOSS) if hubs else ""
