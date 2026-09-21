"""
The ground everyone fights over.

Flat-top hexes in odd-q offset coordinates: columns run left to right and
odd columns are pushed half a hex down, which is exactly the layout the
gameplay mockup draws.

Maps are generated mirror-symmetric about the vertical axis. Neither side
should ever be able to blame the ground, so whatever Azure gets on the left,
Crimson gets on the right.
"""
import random

from .constants import (PLAIN, WOOD, HILL, FORD, MOUNTAIN, WATER, PASSABLE,
                        TERRAIN_BLOCKS_SIGHT, HUBS)

# odd-q offset neighbours, in a fixed order so that every traversal in the
# engine visits regions in the same sequence on every machine
NEIGHBOURS_EVEN = ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1))
NEIGHBOURS_ODD = ((0, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0))


class HexMap:
    """Terrain, adjacency and the fixed landmarks. Never mutated in play."""

    def __init__(self, w, h, terrain, capitals, hubs):
        self.w = w
        self.h = h
        self.terrain = terrain          # list[str], indexed by region id
        self.capitals = capitals        # {side: region id}
        self.hubs = hubs                # [region id]
        self._adj = [self._compute_adj(i) for i in range(w * h)]

    # ------------------------------------------------------------ geometry
    def rid(self, col, row):
        return row * self.w + col

    def colrow(self, rid):
        return rid % self.w, rid // self.w

    def inside(self, col, row):
        return 0 <= col < self.w and 0 <= row < self.h

    def _compute_adj(self, rid):
        col, row = self.colrow(rid)
        table = NEIGHBOURS_ODD if col % 2 else NEIGHBOURS_EVEN
        out = []
        for dc, dr in table:
            c, r = col + dc, row + dr
            if self.inside(c, r):
                out.append(self.rid(c, r))
        return tuple(out)

    def adj(self, rid):
        return self._adj[rid]

    def passable(self, rid):
        return self.terrain[rid] in PASSABLE

    def blocks_sight(self, rid):
        return self.terrain[rid] in TERRAIN_BLOCKS_SIGHT

    def mirror(self, rid):
        """The region's opposite number across the map's axis of symmetry."""
        col, row = self.colrow(rid)
        return self.rid(self.w - 1 - col, row)

    # ------------------------------------------------------------ traversal
    def within(self, src, steps, blocked=()):
        """Region ids reachable from src in `steps` moves through passable
        ground, excluding anything in `blocked`. Returns {rid: distance}."""
        seen = {src: 0}
        frontier = [src]
        for d in range(1, steps + 1):
            nxt = []
            for rid in frontier:
                for n in self.adj(rid):
                    if n in seen or not self.passable(n) or n in blocked:
                        continue
                    seen[n] = d
                    nxt.append(n)
            frontier = nxt
            if not frontier:
                break
        return seen

    def sight(self, src, vision):
        """What a brigade at src can see. Woods and hills stop the eye at
        their own edge: you see into them but never past them."""
        seen = {src}
        frontier = [src]
        for _ in range(vision):
            nxt = []
            for rid in frontier:
                for n in self.adj(rid):
                    if n in seen:
                        continue
                    seen.add(n)
                    if not self.blocks_sight(n) and self.passable(n):
                        nxt.append(n)
            frontier = nxt
            if not frontier:
                break
        return seen

    def distance(self, a, b):
        """Walking distance through passable ground, or -1 if unreachable."""
        if a == b:
            return 0
        seen = {a}
        frontier = [a]
        d = 0
        while frontier:
            d += 1
            nxt = []
            for rid in frontier:
                for n in self.adj(rid):
                    if n in seen:
                        continue
                    if n == b:
                        return d
                    if not self.passable(n):
                        continue
                    seen.add(n)
                    nxt.append(n)
            frontier = nxt
        return -1

    # ------------------------------------------------------------ plumbing
    def to_dict(self):
        return {"w": self.w, "h": self.h, "terrain": list(self.terrain),
                "capitals": {str(k): v for k, v in self.capitals.items()},
                "hubs": list(self.hubs)}

    @staticmethod
    def from_dict(d):
        return HexMap(d["w"], d["h"], list(d["terrain"]),
                      {int(k): v for k, v in d["capitals"].items()},
                      list(d["hubs"]))


# ------------------------------------------------------------------ making one
def generate(seed=0, w=11, h=7):
    """Build a symmetric map. The left half is rolled, then reflected."""
    rnd = random.Random(seed)
    n = w * h
    terrain = [PLAIN] * n

    def rid(c, r):
        return r * w + c

    mid = w // 2
    mid_row = h // 2

    # 1. A river down the spine, braiding wider on some rows, with fords
    #    where an army can cross. It sits on the axis of symmetry and
    #    widens evenly either side, so it mirrors itself.
    river = []
    for r in range(h):
        wide = 0 < r < h - 1 and rnd.random() < 0.30
        cols = (mid - 1, mid, mid + 1) if wide else (mid,)
        row_cells = [rid(c, r) for c in cols]
        river.append(row_cells)
        for i in row_cells:
            terrain[i] = WATER
    # at least three crossings, always including the middle row
    crossings = {mid_row}
    while len(crossings) < 3:
        crossings.add(rnd.randrange(h))
    for r in sorted(crossings):
        for i in river[r]:
            terrain[i] = FORD

    # 2. rough ground on the left half only, then mirrored
    for r in range(h):
        for c in range(mid):
            i = rid(c, r)
            if terrain[i] != PLAIN:
                continue
            roll = rnd.random()
            if roll < 0.14:
                terrain[i] = WOOD
            elif roll < 0.22:
                terrain[i] = HILL
            elif roll < 0.27:
                terrain[i] = MOUNTAIN

    for r in range(h):
        for c in range(mid):
            i, j = rid(c, r), rid(w - 1 - c, r)
            if terrain[i] in (WOOD, HILL, MOUNTAIN):
                terrain[j] = terrain[i]

    # 3. capitals, on clear ground at either end of the middle row
    capitals = {}
    for side, col in ((0, 1), (1, w - 2)):
        i = rid(col, mid_row)
        terrain[i] = PLAIN
        capitals[side] = i
        for nb_c, nb_r in ((col, mid_row - 1), (col, mid_row + 1)):
            if 0 <= nb_r < h and terrain[rid(nb_c, nb_r)] == MOUNTAIN:
                terrain[rid(nb_c, nb_r)] = PLAIN

    # 4. three hubs: the centre crossing, and a mirrored pair
    hubs = [rid(mid, mid_row)]
    pool = [rid(c, r) for r in range(h) for c in range(mid + 1, w - 2)
            if terrain[rid(c, r)] in (PLAIN, WOOD, HILL)
            and rid(c, r) not in hubs
            and abs(r - mid_row) >= 1]
    pool.sort()
    if pool:
        pick = pool[rnd.randrange(len(pool))]
        hubs.append(pick)
        mirrored = rid(w - 1 - (pick % w), pick // w)
        if mirrored not in hubs:
            hubs.append(mirrored)
    while len(hubs) < HUBS:                     # degenerate maps only
        cand = rnd.randrange(n)
        if terrain[cand] in PASSABLE and cand not in hubs:
            hubs.append(cand)
    hubs = sorted(hubs[:HUBS])
    for i in hubs:
        if terrain[i] == WATER:
            terrain[i] = FORD

    m = HexMap(w, h, terrain, capitals, hubs)
    _open_up(m)
    return m


def _open_up(m):
    """Guarantee the two capitals can actually reach each other. Any
    mountain that stands between them gets quarried out."""
    a, b = m.capitals[0], m.capitals[1]
    guard = 0
    while m.distance(a, b) < 0 and guard < 200:
        guard += 1
        # walk the straight line between the capitals and clear the first
        # impassable region on it
        ac, ar = m.colrow(a)
        bc, br = m.colrow(b)
        cleared = False
        for step in range(1, abs(bc - ac) + 1):
            c = ac + step * (1 if bc > ac else -1)
            r = ar + round((br - ar) * step / max(abs(bc - ac), 1))
            i = m.rid(c, r)
            if not m.passable(i):
                opened = FORD if m.terrain[i] == WATER else PLAIN
                m.terrain[i] = opened
                # whatever we quarry out, we quarry out on both sides
                m.terrain[m.mirror(i)] = opened
                cleared = True
                break
        if not cleared:
            break
