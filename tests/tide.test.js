/* Headless tests for TIDE's rules. No browser, no DOM.
 *
 *     node tests/tide.test.js
 *
 * The Python suite shells out to this, so `python3 -m unittest discover -s
 * tests` runs it too and there is still one command for everything.
 */
'use strict';
const path = require('path');
const T = require(path.join(__dirname, '..', 'web', 'tide.js'));

let passed = 0, failed = 0;
function ok(name, cond, extra) {
  if (cond) { passed++; return; }
  failed++;
  console.error('  FAIL  ' + name + (extra ? '\n        ' + extra : ''));
}
function eq(name, got, want) {
  ok(name, got === want, 'got ' + JSON.stringify(got) +
                         ', wanted ' + JSON.stringify(want));
}
/* A reproducible board, so a failure can be looked at again. */
function seeded(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
}
const board = (spec) => spec.map(x => ({ owner: x[0], n: x[1], pop: 0 }));

/* ---------------------------------------------------------- the board */
(function theBoard() {
  const b = T.newBoard(seeded(7));
  eq('a board is 7 x 6', b.length, 42);
  const c = T.counts(b);
  eq('you start with one tile', c.you, 1);
  eq('the enemy starts with one tile', c.foe, 1);
  eq('everything else is free', c.free, 40);

  ok('nobody starts next to anybody',
     !T.neighbours(T.idx(0, T.ROWS - 1)).includes(T.idx(T.COLS - 1, 0)));

  // symmetric adjacency, or the board is subtly unfair
  let oneWay = 0;
  for (let i = 0; i < 42; i++)
    for (const j of T.neighbours(i))
      if (!T.neighbours(j).includes(i)) oneWay++;
  eq('adjacency is two-way everywhere', oneWay, 0);

  eq('an interior tile has six neighbours', T.neighbours(T.idx(3, 3)).length, 6);
  ok('a corner has fewer', T.neighbours(0).length < 6);

  // every tile must be reachable, or part of the board can never be taken
  const seen = new Set([0]); const q = [0];
  while (q.length) for (const n of T.neighbours(q.pop()))
    if (!seen.has(n)) { seen.add(n); q.push(n); }
  eq('every tile is reachable from every other', seen.size, 42);
})();

/* ---------------------------------------------------- the single rule */
(function theRule() {
  const A = 0, B = 1;   // two adjacent tiles: idx(0,0) and its neighbour
  const to = T.neighbours(0)[0];

  let b = T.newBoard(seeded(1));
  b[0] = { owner: T.YOU, n: 8, pop: 0 };
  b[to] = { owner: T.FOE, n: 5, pop: 0 };
  let r = T.send(b, 0, to);
  eq('sending half of 8 is 4', r.kind, 'repulsed');
  eq('the attacker keeps the other half', b[0].n, 4);
  eq('4 against 5 leaves 1 defending', b[to].n, 1);
  eq('and the tile does not change hands', b[to].owner, T.FOE);

  b = T.newBoard(seeded(1));
  b[0] = { owner: T.YOU, n: 16, pop: 0 };
  b[to] = { owner: T.FOE, n: 5, pop: 0 };
  r = T.send(b, 0, to);
  eq('8 against 5 takes it', r.kind, 'capture');
  eq('with the difference left standing', b[to].n, 3);
  eq('and it is yours now', b[to].owner, T.YOU);
  eq('the source still has its half', b[0].n, 8);

  b = T.newBoard(seeded(1));
  b[0] = { owner: T.YOU, n: 10, pop: 0 };
  b[to] = { owner: T.FOE, n: 5, pop: 0 };
  r = T.send(b, 0, to);
  eq('equal numbers do not take the tile', r.kind, 'repulsed');
  eq('a tie leaves the defender on zero', b[to].n, 0);
  eq('still theirs, but one more will do it', b[to].owner, T.FOE);

  b = T.newBoard(seeded(1));
  b[0] = { owner: T.YOU, n: 9, pop: 0 };
  b[to] = { owner: T.YOU, n: 2, pop: 0 };
  r = T.send(b, 0, to);
  eq('sending to your own tile reinforces it', r.kind, 'reinforce');
  eq('the numbers add up', b[to].n, 6);

  b = T.newBoard(seeded(1));
  b[0] = { owner: T.YOU, n: 1, pop: 0 };
  ok('a tile of 1 cannot send anything', T.send(b, 0, to) === null);

  b = T.newBoard(seeded(1));
  b[0] = { owner: T.YOU, n: 20, pop: 0 };
  const far = 41;
  ok('you cannot send to a tile that is not adjacent',
     T.send(b, 0, far) === null);

  // no move may create or destroy troops beyond what the rule says
  b = T.newBoard(seeded(3));
  b[0] = { owner: T.YOU, n: 12, pop: 0 };
  b[to] = { owner: T.FOE, n: 4, pop: 0 };
  const before = b[0].n + b[to].n;
  T.send(b, 0, to);
  ok('an attack never invents troops', b[0].n + b[to].n <= before,
     'before ' + before + ', after ' + (b[0].n + b[to].n));
})();

/* ------------------------------------------------------------- growth */
(function growth() {
  const b = board([[T.YOU, 3], [T.FOE, 3], [T.NEUTRAL, 3], [T.YOU, T.CAP]]);
  T.grow(b);
  eq('your tiles tick up', b[0].n, 4);
  eq('so do theirs, at the same rate', b[1].n, 4);
  eq('free tiles never grow', b[2].n, 3);
  eq('growth stops at the cap', b[3].n, T.CAP);
})();

/* -------------------------------------------------------- the enemy AI */
(function theEnemy() {
  let b = T.newBoard(seeded(11));
  const m = T.bestMove(b, T.FOE, seeded(2));
  ok('the enemy finds a move from its one tile', m !== null);
  if (m) {
    eq('it only ever moves its own tiles', b[m.from].owner, T.FOE);
    ok('and only to a neighbour', T.neighbours(m.from).includes(m.to));
  }

  // it must not attack where it would lose: that is the rule, not mercy
  b = T.newBoard(seeded(5));
  for (let i = 0; i < b.length; i++) b[i] = { owner: T.NEUTRAL, n: 30, pop: 0 };
  b[0] = { owner: T.FOE, n: 4, pop: 0 };
  ok('with nothing it can beat, it does not throw troops away',
     T.bestMove(b, T.FOE, seeded(1)) === null);

  // both sides get the identical function: check it is genuinely symmetric
  b = T.newBoard(seeded(9));
  const mirror = b.map(t => ({
    owner: t.owner === T.YOU ? T.FOE : t.owner === T.FOE ? T.YOU : T.NEUTRAL,
    n: t.n, pop: 0 }));
  const a1 = T.bestMove(b, T.FOE, seeded(4));
  const a2 = T.bestMove(mirror, T.YOU, seeded(4));
  ok('the same position gives the same move whichever side holds it',
     JSON.stringify(a1) === JSON.stringify(a2),
     JSON.stringify(a1) + ' vs ' + JSON.stringify(a2));
})();

/* -------------------------------------------------- whole games finish */
(function wholeGames() {
  // A match is 120s; the enemy acts about every 1.15s, so a real game is
  // a little over a hundred moves a side. Run that many ticks.
  const TICKS = 110;
  let wins = 0, losses = 0, draws = 0, unfinished = 0, early = 0;
  for (let g = 0; g < 80; g++) {
    const rng = seeded(1000 + g);
    const b = T.newBoard(rng);
    let out;
    for (let t = 0; t <= TICKS; t++) {
      if (t % 3 === 0) T.grow(b);
      // both seats played by the same routine, so the result reads on the
      // rules rather than on how well I wrote one side
      for (const side of [T.YOU, T.FOE]) {
        const m = T.bestMove(b, side, rng);
        if (m) T.send(b, m.from, m.to);
      }
      out = T.verdict(b, t >= TICKS);
      if (out !== undefined) { if (t < TICKS) early++; break; }
    }
    if (out === undefined) unfinished++;
    else if (out === T.YOU) wins++;
    else if (out === T.FOE) losses++;
    else draws++;
  }
  eq('every match reaches a result inside its clock', unfinished, 0);
  ok('and neither seat wins them all', wins > 0 && losses > 0,
     wins + ' / ' + losses + ' (' + draws + ' drawn, ' + early + ' ended early)');
})();

(function theClock() {
  const b = [{owner: T.YOU, n: 5}, {owner: T.FOE, n: 5}, {owner: T.NEUTRAL, n: 1}];
  ok('while the clock runs there is no result',
     T.verdict(b, false) === undefined);
  eq('level on tiles when time runs out is a draw', T.verdict(b, true), null);

  b[2] = {owner: T.YOU, n: 1};
  eq('most tiles takes it when time runs out', T.verdict(b, true), T.YOU);

  const wiped = [{owner: T.YOU, n: 5}, {owner: T.NEUTRAL, n: 1}];
  eq('wiping them out ends it early', T.verdict(wiped, false), T.YOU);
})();

/* ----------------------------------------------- nothing goes negative */
(function invariants() {
  const rng = seeded(77);
  const b = T.newBoard(rng);
  for (let t = 0; t < 600; t++) {
    if (t % 3 === 0) T.grow(b);
    for (const side of [T.YOU, T.FOE]) {
      const m = T.bestMove(b, side, rng);
      if (m) T.send(b, m.from, m.to);
    }
    for (let i = 0; i < b.length; i++) {
      if (b[i].n < 0) { ok('a tile went negative at tick ' + t, false); return; }
      if (b[i].n > T.STACK_CAP) {
        ok('a tile passed the stack cap at tick ' + t, false); return;
      }
    }
    if (T.counts(b).you === 0 || T.counts(b).foe === 0) break;
  }
  ok('numbers stay sane for a whole game', true);
})();

console.log(passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
