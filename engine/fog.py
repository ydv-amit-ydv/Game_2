"""
What each side is allowed to know.

Two rules, and they are the whole system. You see what your brigades can
see, and you remember what you saw. Memory goes stale — an enemy counter
you spotted four rounds ago is drawn where it was, not where it is, and the
client is told how old that sighting is so it can say so.
"""
from .constants import CRIMSON, AZURE, MEMORY_ROUNDS


def visible(state, side):
    """Regions this side can see into right now."""
    seen = set()
    for b in state.living(side):
        seen |= state.map.sight(b.region, b.stats["vision"])
    for r in state.regions:
        if r.owner == side or r.depot == side:
            seen.add(r.id)
    return seen


class Intel:
    """One side's running memory of the map. The server keeps one of these
    per side and updates it after every round."""

    def __init__(self):
        self.seen_round = {}        # region id -> round it was last observed
        self.sightings = {}         # region id -> [{kind, side, strength}]
        self.owner = {}             # region id -> owner as last observed

    def update(self, state, side):
        vis = visible(state, side)
        for rid in sorted(vis):
            self.seen_round[rid] = state.round
            self.owner[rid] = state.region(rid).owner
            here = [b for b in state.at(rid) if b.side != side]
            self.sightings[rid] = [
                {"kind": b.kind, "side": b.side, "strength": b.strength,
                 "commander": b.commander}
                for b in sorted(here, key=lambda x: x.id)]
        return vis

    def to_dict(self, state, side):
        """What this side may be shown.

        Two kinds of knowledge, deliberately treated differently. Who owns
        what, and what the ground is, is long-term: once learned it stays.
        Where an enemy brigade was standing is short-term, and after
        MEMORY_ROUNDS it is dropped from the display entirely -- not greyed
        out, gone. Remembering it is the player's job, and that is the
        exercise."""
        vis = visible(state, side)
        out = {"visible": sorted(vis), "regions": {}, "forgetAfter": MEMORY_ROUNDS}
        for rid, rnd in sorted(self.seen_round.items()):
            age = state.round - rnd
            lit = rid in vis
            if lit:
                # you are looking at it: report what is there, not what the
                # cache last happened to record
                sightings = [
                    {"kind": b.kind, "side": b.side, "strength": b.strength,
                     "commander": b.commander}
                    for b in sorted(state.at(rid), key=lambda x: x.id)
                    if b.side != side]
            elif age > MEMORY_ROUNDS:
                sightings = []                  # the memory has gone
            else:
                sightings = self.sightings.get(rid, [])
            out["regions"][str(rid)] = {
                "seen": rnd,
                "stale": not lit,
                "age": age,
                "fading": (not lit) and age > 0,
                "owner": self.owner.get(rid),
                "enemies": sightings,
            }
        return out


def view(state, side, intel=None):
    """The whole state as one side is entitled to see it. Enemy brigades
    outside the light are simply absent; ones remembered are marked stale."""
    vis = visible(state, side)
    out = {
        "round": state.round,
        "over": state.over,
        "winner": state.winner,
        "verdict": state.verdict,
        "side": side,
        "map": state.map.to_dict(),
        "visible": sorted(vis),
        "regions": [],
        "brigades": [],
    }
    for r in state.regions:
        known = r.id in vis or (intel and r.id in intel.seen_round)
        out["regions"].append({
            "id": r.id,
            "owner": r.owner if r.id in vis else (
                intel.owner.get(r.id) if intel else None),
            "depot": r.depot if r.id in vis else None,
            "works": r.works if r.id in vis else 0,
            "forage": r.forage if r.id in vis else None,
            "hub": r.id in state.map.hubs,
            "known": bool(known),
            "lit": r.id in vis,
        })
    for b in state.living():
        if b.side == side:
            out["brigades"].append({
                "id": b.id, "side": b.side, "kind": b.kind,
                "commander": b.commander, "strength": b.strength,
                "max": b.max_strength, "region": b.region,
                "entrenched": b.entrenched, "reserve": b.in_reserve,
                "supplied": b.supplied, "stale": False, "mine": True,
                "corps": b.corps, "balkAt": b.balk_at,
            })
        elif b.region in vis:
            out["brigades"].append({
                "id": b.id, "side": b.side, "kind": b.kind,
                "commander": b.commander, "strength": b.strength,
                "region": b.region, "stale": False, "mine": False,
                "corps": b.corps,
            })
        elif intel and b.region in intel.seen_round:
            pass                     # remembered counters come from Intel
    if intel:
        out["intel"] = intel.to_dict(state, side)
    return out


def enemy_of(side):
    return CRIMSON if side == AZURE else AZURE
