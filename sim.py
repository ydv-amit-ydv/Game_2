#!/usr/bin/env python3
"""
Run a whole match between bot armies and print what happened.

    python3 sim.py                    one match, round by round
    python3 sim.py --quiet            just the verdict
    python3 sim.py --seed 7           a different map and draft
    python3 sim.py --batch 200        balance check across many matches

This is the engine's proving ground. No server, no browser, no sockets — if
the game is not interesting here it will not become interesting once it has
a user interface.
"""
import argparse
import collections
import sys

from engine import (new_game, resolve, bot, match_summary, MAX_ROUNDS,
                    AZURE, CRIMSON, DEFAULT_ORDER_OF_BATTLE)
from engine.constants import SIDE_NAMES, BRIGADE_STATS, LINE, LIGHT, HORSE, GUNS, PIONEERS

# every draft here is legal: five brigades, within the caps, inside budget
DRAFTS = [
    (LINE, LINE, LIGHT, HORSE, PIONEERS),     # 16 - the book answer
    (LINE, GUNS, LIGHT, LIGHT, PIONEERS),     # 16 - a battering ram
    (LINE, HORSE, HORSE, LIGHT, PIONEERS),    # 15 - raiders
    (LINE, LINE, HORSE, HORSE, LIGHT),        # 16 - all teeth, no engineers
]


def run(seed=0, draft_a=0, draft_b=0, log=None):
    state = new_game(seed=seed, orders_of_battle={
        AZURE: DRAFTS[draft_a % len(DRAFTS)],
        CRIMSON: DRAFTS[draft_b % len(DRAFTS)],
    })
    history = []
    while not state.over:
        orders = bot.plan(state, AZURE) + bot.plan(state, CRIMSON)
        state, events = resolve(state, orders)
        history.append((state.round, events))
        if log:
            log(state, orders, events)
    return state, history


def describe(state, orders, events):
    rnd = state.round if not state.over else MAX_ROUNDS
    print("\n\033[1m── ROUND %d ──\033[0m" % (rnd - (0 if state.over else 1)))
    verbs = collections.Counter(o.verb for o in orders)
    print("   orders: " + "  ".join("%s x%d" % (v, n)
                                    for v, n in sorted(verbs.items())))
    for e in events:
        t = e["t"]
        if t == "battle":
            p = e["power"]
            conc = ("  +%g concentration" % e["concentration"]
                    if e["concentration"] else "")
            print("   ⚔  region %-3d  %s %.1f  vs  %s %.1f   →  %s wins%s"
                  % (e["region"],
                     SIDE_NAMES[e["winner"]][:6], p.get(e["winner"], 0),
                     SIDE_NAMES[e["loser"]][:6], p.get(e["loser"], 0),
                     SIDE_NAMES[e["winner"]], conc))
        elif t == "capture":
            print("   ⚑  region %-3d taken by %s" % (e["region"],
                                                     SIDE_NAMES[e["side"]]))
        elif t == "depot":
            print("   ⌂  depot built at region %d by %s"
                  % (e["region"], SIDE_NAMES[e["side"]]))
        elif t == "starve":
            print("   ☠  brigade %d starving at %d (-%d, %d left)"
                  % (e["brigade"], e["region"], e["lost"], e["left"]))
        elif t == "broken":
            print("   ✖  brigade %d broken at region %d"
                  % (e["brigade"], e["region"]))
        elif t == "victory":
            who = SIDE_NAMES.get(e["side"], "nobody")
            print("\n   \033[1m%s — %s\033[0m" % (who, e["why"]))
    print("   " + match_summary(state))


def batch(n, w=11, h=7):
    """Does either side, or any draft, have a structural edge?"""
    wins = collections.Counter()
    by_draft = collections.defaultdict(collections.Counter)
    lengths = []
    for seed in range(n):
        a, b = seed % len(DRAFTS), (seed // len(DRAFTS)) % len(DRAFTS)
        state, hist = run(seed=seed, draft_a=a, draft_b=b)
        wins[state.winner] += 1
        lengths.append(state.round)
        if state.winner is not None:
            winning = a if state.winner == AZURE else b
            by_draft[winning]["win"] += 1
        by_draft[a]["played"] += 1
        by_draft[b]["played"] += 1

    print("\n%d matches" % n)
    for side in (AZURE, CRIMSON):
        print("  %-14s %3d wins  (%4.1f%%)"
              % (SIDE_NAMES[side], wins[side], 100.0 * wins[side] / n))
    print("  %-14s %3d" % ("drawn", wins[None]))
    print("  mean length   %.1f rounds" % (sum(lengths) / len(lengths)))
    print("\n  draft                                 played   won   rate")
    for i, d in enumerate(DRAFTS):
        c = by_draft[i]
        rate = (100.0 * c["win"] / c["played"]) if c["played"] else 0.0
        print("  %-36s %5d %5d  %4.1f%%"
              % ("+".join(k[:4] for k in d), c["played"], c["win"], rate))
    return wins


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--batch", type=int, default=0,
                    help="run N matches and report the balance")
    ap.add_argument("--draft-a", type=int, default=0)
    ap.add_argument("--draft-b", type=int, default=0)
    args = ap.parse_args(argv)

    if args.batch:
        batch(args.batch)
        return 0

    state, hist = run(seed=args.seed, draft_a=args.draft_a,
                      draft_b=args.draft_b,
                      log=None if args.quiet else describe)
    if args.quiet:
        print(match_summary(state))
    print("\nfinal digest %s  (identical every run)" % state.digest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
