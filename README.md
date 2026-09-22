# TIDE

**Tap a tile. Tap the one next to it. Bigger number wins.**

That is the entire game.

```bash
python3 server.py        # then open http://localhost:8000
```

Or just open `web/index.html` in a browser — it needs no server at all.

## How to play

1. **Tap one of your blue tiles.** It lights up.
2. **Tap a tile next to it.** Half your number marches over.
3. **Bigger number wins.** Send 8 at a 5 and you take it with 3 left over.
4. **Two minutes.** Most tiles at the end wins, or wipe them out early.

Your tiles tick up on their own, so the game is really one question asked
over and over: *spend now, or wait and spend more?* Grey tiles are cheap —
take them early. Attack from one big stack rather than two small ones,
because a tile only ever sends half of what it has.

That's it. No menus, no turns, no commit button, nothing hidden. The enemy
plays the same rule off the same numbers you can see.

## What's in here

| | |
|---|---|
| `web/index.html` | the game — one screen, one file |
| `web/tide.js` | the rules, kept separate so they can be tested headlessly |
| `tests/tide.test.js` | 41 tests of the arithmetic |

```bash
python3 -m unittest discover -s tests    # everything, including the JS
node tests/tide.test.js                  # just the game rules
```

Pulling the rules out of the HTML paid for itself immediately: a headless
run of 60 whole matches found one that **never ended** — a 36-tiles-to-6
position where the two sides took the same tile off each other forever.
Playing to total elimination was simply the wrong win condition, so a match
is now timed, which fixes it and gives the thing some urgency besides.

## The older, bigger games

This started as an operational wargame and got steadily simpler as it became
clear the complexity was the problem, not the presentation. Both earlier
versions still work:

- **`/skirmish.html`** — three brigades, four orders, supply lines, take the
  enemy keep in twelve rounds. Turn-based, with a coach that warns you before
  you commit and explains what killed you afterwards.
- **`/campaign.html`** — the full thing. Five brigades a side for up to ten
  players, nine orders, supply hubs, fog of war, rationed signals, and a
  Reserve Corps that leans against whoever is losing.

Both run on `engine/`, a dependency-free deterministic wargame engine with
no randomness at all: combat is arithmetic, so replays are exact. Its tests
include a mirror-match invariant — two identical armies on a mirrored map
must stay a perfect reflection every round and end level — which caught
three real bugs, each an arbitrary tie broken by the lower id.

```bash
python3 sim.py --batch 400    # bot-vs-bot balance runs for the wargame
```
