# THE IRON COMPACT

**You command three brigades. Take the enemy keep before round twelve.**

That is the whole game. Three minutes, one screen, four orders.

```bash
python3 server.py          # then open http://localhost:8000
```

Press **TEACH ME** for three short lessons, or **JUST PLAY**.

**There is no clock.** Solo is you against the machine, so nothing waits:
click a brigade, pick an order, click where you mean it, press **GO**, and
the round resolves at once — yours and the enemy's together.

## Your three brigades

| | Strength | Moves | Attack | Defend | What it is for |
|---|---|---|---|---|---|
| **FOOT** | 12 | 1 | full | strong | Your hammer. The only brigade that can take ground and still be standing on it next round. |
| **HORSE** | 7 | 2 | fair | poor | Your speed. Two regions a round — gets behind them and takes empty ground. Never leave it somewhere it has to defend. |
| **ENGINEERS** | 5 | 1 | weak | fair | Your range. BUILD puts a depot under its feet, and a depot feeds 3 regions around it. |

## The rules, with the actual numbers

1. **Supply keeps you alive.** Every brigade must be within **3 regions** of
   your KEEP or of a DEPOT. The **shaded green ground** on the map is exactly
   where you are fed.
2. **Outside it you starve.** A brigade out of supply loses **2 strength**
   every round and nobody has to fight it. At 0 it is gone for good. *This is
   what kills people.*
3. **Engineers extend the map.** BUILD drops a depot where they stand —
   including outside your supply. The shaded ground grows 3 regions around
   it, and the army can go further. Leapfrogging depots forward is the whole
   strategy.
4. **Two at once is worth +4.** Two brigades attacking the same region in the
   same round arrive as one column. One alone against a dug-in defender
   usually bounces.
5. **DIG IN is not a wasted round.** Fed and dug in, a brigade recovers
   strength and is much harder to shift.

Four orders: **MARCH**, **ATTACK**, **DIG IN**, **BUILD** (engineers only).
Keys 1–4, Tab switches brigade, Enter is GO. Every one of these numbers is
served to the browser from `engine/constants.py`, so what the screen says and
what the engine does cannot drift apart.

## The full campaign

The small game above is the front door. The original 5-a-side campaign —
nine orders, seven brigades, supply hubs, a points draft, rationed signals,
and up to ten players — is still there at **`/campaign.html`**.

It is a much bigger game and it takes real study. It grew that way by
accretion over this project, and the small game exists because it had become
something you have to learn before you can play it. Everything the small game
teaches transfers: it runs on the same engine and the same `resolve()`.

| | |
|---|---|
| `engine/skirmish.py` | the small game: 3 brigades, 4 orders, one objective |
| `engine/coach.py` | the trainer: warns before, explains after |
| `engine/corps.py` | the Reserve Corps (campaign only) |
| `web/index.html` | the small game's client |
| `web/campaign.html` | the full campaign's client |
| `tests/` | 106 tests |

## What it is meant to train

Brain drain is high load with no learning — unclear causality, fatal
mistakes, no visible progress. Training is load pitched just above your
current ability with fast, legible feedback. Six faculties, each with a
mechanic behind it rather than a claim:

| Faculty | What trains it |
|---|---|
| **Short-term memory** | An enemy you spotted fades and then **vanishes** after 3 rounds. Remembering where they went is your job. |
| **Long-term memory** | Ownership and terrain are never forgotten. Map shapes and opponent habits recur. |
| **Short-term strategy** | One order under a 25-second clock. |
| **Long-term strategy** | Depots and supply chains that pay off six rounds later. |
| **Planning** | Supply reaches three regions. Everything you do is bounded by a chain you laid earlier. |
| **Pattern recognition** | The clock is short on purpose. Most rounds must be read, not calculated — which is exactly how the reading gets good. |

Causality is the load-bearing part. Losing a brigade in round nine because a
road was cut in round six is the single most common way this game goes
opaque, so the room keeps a ledger and the coach names the round it started.

## Play it

```bash
python3 server.py
```

Then open **http://localhost:8000**. Press *HOST A ROOM*, then *BEGIN THE
CAMPAIGN* — you are playing immediately, commanding one brigade with bots
holding the other nine seats.

To play with other people, share the five-letter room code. Anyone on the
same network opens the address the server prints on startup, types the code,
and clicks an open seat. Every seat nobody takes stays under a bot, so you
never need a particular number of people to start.

Each round you pick one of the nine orders (keys `1`–`9`), click the region
you mean, and press *COMMIT* (or `Enter`). When the clock runs out — or
every human has committed — all the orders land at once. `Esc` clears a
half-made order.

```bash
PORT=9000 COMPACT_PLAN=90 python3 server.py    # a longer planning window
python3 sim.py                                  # bots only, in the terminal
python3 sim.py --batch 400                      # balance across many matches
python3 -m unittest discover -s tests           # the whole suite
```

No dependencies. Python 3.8+.

## The Reserve Corps

Two brigades a side that **nobody may sit in**. Both armies get the same
corps, so it can never be an advantage in itself — what it *does* with them
is where the balancing happens.

It reads how far its own side is ahead or behind and leans: **PRESSING**
when its army is losing, **EASING** when its army is winning, **STEADY**
when the match is even. It leans; it does not throw matches. A side
handicapped to 65% strength goes from winning **8.3%** of matches to
**30.8%** — enough to make a bad start survivable, not enough to hand
anyone a win they did not earn.

It is also a teaching device. Whatever the tilt, it plays legibly — keeps
its supply, concentrates with a neighbour rather than attacking alone,
builds depots before they are needed — and **every order it gives comes back
with a reason attached**, printed on screen. Watching RESERVE and ENGINEERS
for one match shows you the grammar of the game played correctly.

The intervention is always visible. Hidden rubber-banding reads as cheating
the moment a player suspects it, so the posture and the reason are both on
the left rail.

An unintended benefit worth recording: the corps carries the engineers, and
that **fixed the compulsory-Pioneers problem**. Draft win rates went from
`62 / 47 / 40 / 2` to `29 / 40 / 29 / 52` — a spread of 56 points down to
21, and all four drafts viable.

## The trainer

`engine/coach.py`. It warns, it never decides — a trainer that plays the
game for you trains nothing.

**Before you commit** it reads the order and says what it will cost: that
the ground is outside your supply, that guns eat 3 a round and this is how
artillery is usually lost, that you are lighter than what is holding the
region and a second brigade is worth +4, that this ground already threw you
off once. At most three warnings, worst first.

**After the round** it explains what happened and when it started — *"Kestrel
is gone. It had been out of supply since round 6."*

Both are read-only over the state; `tests/test_trainer.py` asserts the coach
never changes the game.

## The engine

Everything turns on one function:

```python
new_state, events = resolve(state, orders)
```

It is pure — it copies the state, never mutates the original — and it
contains **no randomness at all**. Combat is arithmetic. Two brigades of
equal weight on equal ground always produce the same outcome, on every
machine, forever. That buys three things: exact replays, a bot that can look
ahead by simply calling `resolve`, and a `digest()` that lets two processes
prove they agree.

Everything lands in the same instant. Battles are all decided against one
frozen pre-battle snapshot, then all losses are applied, then everyone
moves — so no result can depend on the sequence orders arrived in.

```
engine/
  constants.py   every tunable number, so balance is a data change
  hexmap.py      odd-q hex grid, symmetric map generation
  state.py       brigades, regions, the draft, serialisation
  orders.py      the nine orders and their validation
  resolve.py     the round
  fog.py         what each side may know, and what it remembers
  bot.py         a brigade commander that isn't a person
```

## The nine orders

| Order | Supply | What it does |
|---|---|---|
| ADVANCE | 1 | Move to a neighbouring region. |
| ASSAULT | 3 | Take defended ground. You commit before you see what they committed. |
| HOLD | 0 | Dig in. Strong, and you go nowhere. Refits you if supplied. |
| SCREEN | 1 | Deny the ground without a battle. Turns back an advance, not an assault. |
| SUPPLY | 2 | Pioneers only: build a depot, or raise fieldworks. |
| FORAGE | 0 | Feed off the land when the chain is cut. The region remembers. |
| RECON | 1 | Buy vision. Push the fog back. |
| PARLEY | 2 | Court a neutral region. Simultaneous — court the same ground and neither of you gets it. |
| RESERVE | 0 | Commit nothing, and counter-attack at full weight beside any neighbour who is attacked. |

An illegal order becomes HOLD. A commander who writes nonsense stands still;
they do not crash the war.

## The brigades

| | Strength | Pace | Vision | Appetite | Punch | Guard | Points |
|---|---|---|---|---|---|---|---|
| **Line** | 12 | 1 | 1 | 2 | 1.00 | 1.25 | 4 |
| **Light** | 6 | 2 | 3 | 1 | 0.60 | 0.80 | 2 |
| **Horse** | 7 | 2 | 2 | 2 | 0.90 | 0.50 | 3 |
| **Guns** | 8 | 1 | 1 | 3 | 1.60 | 0.70 | 5 |
| **Pioneers** | 5 | 1 | 1 | 1 | 0.40 | 1.00 | 3 |

Sixteen points, five brigades, at most two of any kind and only one Guns or
Pioneers. What you leave out is the hole they will find.

## Concentration

Two brigades that assault the same region in the same round arrive as one
column and add a flat **+4**. Nobody declares anything and nobody needs to
speak — the bonus is paid for by the orders themselves. It is the whole
coordination mechanic, and bots take part in it natively by watching which
ground a neighbouring brigade has already committed to.

## Supply

Supply flows three regions outward from your capital and from any depot,
through passable ground **the enemy is not standing on**. A brigade outside
that reach loses 2 strength a round unless it forages, and a region only
feeds an army so many times before it is stripped.

This is why Horse exists. Getting behind a line and standing on the road is
worth more than most battles.

## What the simulator says

400 bot-vs-bot matches, every draft against every draft:

```
AZURE PACT     148 wins  (37.0%)
CRIMSON HOST   152 wins  (38.0%)
drawn          100                  <- exactly the 100 mirror pairings
mean length    14.4 rounds

draft                          played   won   rate
LINE+LINE+LIGH+HORS+PION          200   125  62.5%
LINE+GUNS+LIGH+LIGH+PION          200    94  47.0%
LINE+HORS+HORS+LIGH+PION          200    79  39.5%
LINE+LINE+HORS+HORS+LIGH          200     2   1.0%   <- no engineers
```

The last row is the design thesis proving itself: an army of nothing but
teeth, with no one to build depots, wins one match in a hundred.

**Known balance problem.** One percent is too strong a verdict. It makes
Pioneers compulsory, which turns a five-slot draft into a four-slot one.
Either foraging needs to be a more viable way of life or Pioneers needs to
cost more. That is a tuning pass in `constants.py`, and it is the next
balance job.

## Symmetry

Maps are generated mirror-symmetric, so neither side can ever blame the
ground — and `tests/test_engine.py` asserts something stronger: a mirror
match (identical armies, identical bots) must stay a *perfect reflection*
every round and end drawn. Any drift means a rule is quietly favouring a
side number.

Building that test found three real bugs, all the same shape — an arbitrary
tie broken by the lower id:

1. The two armies did not even muster on mirrored ground, because both
   sorted their deployment by raw region id.
2. The bots broke every tie by raw region id, which points north-west for
   one army and south-east for the other.
3. Dead heats — a battle of exactly equal weight, and two armies courting the
   same neutral region — were awarded to the lower side number. The centre
   hub sits *on* the axis of symmetry, so that one rule was quietly deciding
   whole campaigns.

Equal weight now means a stand-off: contested ground, nobody takes it. Side
bias went from 45/55 to 37/38 with every draw accounted for.

## The server

Zero dependencies means the HTTP and WebSocket protocols are both implemented
in `server.py` — handshake, framing, masking and all — so the project runs
from a clone with nothing installed.

The server is authoritative about everything, and **the fog is applied on the
server**, not in the browser. A region you have not scouted is not sitting in
your tab waiting to be read out of memory by anyone who opens the console.
`tests/test_server.py` asserts exactly that, over a real socket.

## Next

1. Play the small game and see whether four orders is still three too many.
2. A skill profile, so progress across the six faculties is visible.
3. Reconnecting to a seat after a dropped connection.
4. The order-of-battle draft, for the campaign.
