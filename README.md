# THE IRON COMPACT

A simultaneous-turn operational wargame for 2–10 players, with bots filling
whatever seats nobody is sitting in.

Every player commands **one brigade**. Five brigades make an army. Alone you
command all five; with nine friends you command one each and the other side
does the same. There is no chat. What your army can read is where your
brigade stands, which way it is facing, and three signals a round — so
coordination is something you demonstrate rather than something you announce.

The design thesis: **battles are the last ten percent.** Anyone can order an
assault. The question is whether the brigade is fed, whether the guns came
up, whether the pioneers built the depot three rounds ago, and whether your
neighbour is still coiled in reserve or already committed.

## State of the build

| | |
|---|---|
| `engine/` | the rules — deterministic, dependency-free |
| `server.py` | online multiplayer: rooms, seats, the round clock, fog |
| `web/index.html` | the browser client |
| `sim.py` | headless match runner and balance harness |
| `tests/` | 62 tests, engine and server |

Not built yet: the order-of-battle draft (armies use a fixed book list), and
reconnecting to a seat you dropped out of.

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

1. Tune the Pioneers dependency out of being compulsory.
2. The order-of-battle draft, so armies are chosen rather than issued.
3. Reconnecting to a seat after a dropped connection.
4. A spectator view for a big screen.
