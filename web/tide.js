/* ------------------------------------------------------------------ *
 * TIDE — the rules.
 *
 * Deliberately kept out of index.html and free of any browser thing, so
 * the arithmetic can be tested headlessly in node. There is exactly one
 * rule here and it fits in a sentence:
 *
 *     a tile sends half its number to a neighbour; the bigger number wins.
 *
 * Both sides play it. Nothing is hidden, nothing is random except the
 * opening scatter, and the enemy gets no allowance the player does not.
 * ------------------------------------------------------------------ */
(function (root) {
  'use strict';

  const COLS = 7, ROWS = 6;
  /* A match is timed. Playing to total elimination sounds cleaner but
     two even sides settle into taking the same tile off each other
     forever -- a 36-to-6 position was found running for thousands of
     ticks without ending. A clock also gives the thing urgency, which
     is most of why a raid is fun. */
  const MATCH_MS = 120000;
  const CAP = 24;               // a tile stops growing here
  const STACK_CAP = CAP * 2;    // ...but you may pile troops above it
  const NEUTRAL = -1, YOU = 0, FOE = 1;

  const idx = (c, r) => r * COLS + c;

  /* Flat-top hexes, odd columns pushed down. */
  function neighbours(i) {
    const c = i % COLS, r = (i / COLS) | 0;
    const d = (c & 1)
      ? [[0, -1], [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0]]
      : [[0, -1], [1, -1], [1, 0], [0, 1], [-1, 0], [-1, -1]];
    const out = [];
    for (const [dc, dr] of d) {
      const nc = c + dc, nr = r + dr;
      if (nc >= 0 && nc < COLS && nr >= 0 && nr < ROWS) out.push(idx(nc, nr));
    }
    return out;
  }

  /* You start bottom-left, the enemy top-right. `rng` is injectable so a
     test can lay out a board it knows. */
  function newBoard(rng) {
    rng = rng || Math.random;
    const tiles = [];
    for (let i = 0; i < COLS * ROWS; i++)
      tiles.push({ owner: NEUTRAL, n: 1 + Math.floor(rng() * 3), pop: 0 });
    tiles[idx(0, ROWS - 1)] = { owner: YOU, n: 10, pop: 0 };
    tiles[idx(COLS - 1, 0)] = { owner: FOE, n: 10, pop: 0 };
    return tiles;
  }

  /* The whole game. Returns what happened, for the floating numbers. */
  function send(tiles, from, to) {
    const a = tiles[from], b = tiles[to];
    if (a.n < 2) return null;
    if (!neighbours(from).includes(to)) return null;

    const moving = Math.floor(a.n / 2);
    a.n -= moving;

    if (b.owner === a.owner) {
      b.n = Math.min(STACK_CAP, b.n + moving);
      return { kind: 'reinforce', at: to, owner: a.owner, amount: moving };
    }
    if (moving > b.n) {
      const from_owner = b.owner;
      b.owner = a.owner;
      b.n = moving - b.n;
      b.pop = 1;
      return { kind: 'capture', at: to, owner: a.owner, from: from_owner,
               amount: b.n };
    }
    b.n -= moving;
    return { kind: 'repulsed', at: to, owner: b.owner, amount: moving };
  }

  function grow(tiles) {
    for (const t of tiles)
      if (t.owner !== NEUTRAL && t.n < CAP) t.n++;
  }

  function counts(tiles) {
    let you = 0, foe = 0, free = 0;
    for (const t of tiles) {
      if (t.owner === YOU) you++;
      else if (t.owner === FOE) foe++;
      else free++;
    }
    return { you, foe, free };
  }

  /* The enemy reads the same board you do and applies the same rule.
     It takes the cheapest capture available, preferring to take from the
     player; with nothing to hit it feeds its own front line. */
  function bestMove(tiles, side, rng) {
    rng = rng || Math.random;
    const other = side === YOU ? FOE : YOU;
    let best = null;
    for (let i = 0; i < tiles.length; i++) {
      const a = tiles[i];
      if (a.owner !== side || a.n < 2) continue;
      const moving = Math.floor(a.n / 2);
      for (const j of neighbours(i)) {
        const b = tiles[j];
        if (b.owner === side || moving <= b.n) continue;
        const score = (b.owner === other ? 40 : 0) + (moving - b.n) - b.n * 2;
        if (!best || score > best.score) best = { from: i, to: j, score };
      }
    }
    if (best) return best;

    const front = [];
    for (let i = 0; i < tiles.length; i++) {
      if (tiles[i].owner !== side || tiles[i].n < 4) continue;
      for (const j of neighbours(i))
        if (tiles[j].owner === side &&
            neighbours(j).some(k => tiles[k].owner !== side))
          front.push({ from: i, to: j, score: 0 });
    }
    if (!front.length) return null;
    return front[Math.floor(rng() * front.length)];
  }

  /* Who has won, or undefined while it is still going.
     Wiping the other side out ends it at once; otherwise the clock does,
     and most tiles takes it. */
  function verdict(tiles, timeUp) {
    const c = counts(tiles);
    if (c.foe === 0 && c.you > 0) return YOU;
    if (c.you === 0 && c.foe > 0) return FOE;
    if (c.you === 0 && c.foe === 0) return null;
    if (!timeUp) return undefined;
    if (c.you === c.foe) return null;
    return c.you > c.foe ? YOU : FOE;
  }

  const API = { COLS, ROWS, CAP, STACK_CAP, MATCH_MS, NEUTRAL, YOU, FOE,
                idx, neighbours, newBoard, send, grow, counts, bestMove,
                verdict };

  if (typeof module === 'object' && module.exports) module.exports = API;
  else root.TIDE = API;
})(typeof self !== 'undefined' ? self : this);
