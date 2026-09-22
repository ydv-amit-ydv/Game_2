#!/usr/bin/env python3
"""
THE IRON COMPACT — online multiplayer server.

    python3 server.py            then open http://localhost:8000

Zero dependencies, Python 3.8+. Speaks HTTP for the client and WebSocket for
the game, both implemented here, because the whole project is meant to run
from a clone with nothing installed.

One room holds ten seats: five brigades a side. Anybody can take any empty
seat, and a bot commands every seat nobody has taken, so a match runs with
two players or ten. Rounds are on a clock: everyone plans in private, and
when the clock runs out (or every human has committed) all the orders land
in the same instant.

The server is authoritative about everything. Each client is sent only what
its own side can see -- the fog is applied here, not in the browser, so the
map a player has not scouted is not sitting in their tab waiting to be read.
"""
import asyncio
import base64
import hashlib
import json
import os
import random
import string
import struct
import sys
import time

from engine import (new_game, resolve, bot, corps, coach, skirmish, Order,
                    AZURE, CRIMSON, MAX_ROUNDS, Intel, view, validate)
from engine.resolve import supply_map
from engine.constants import (ORDERS, TARGETED, SIGNAL_KINDS,
                              SIGNALS_PER_ROUND, SIDE_NAMES, BRIGADE_STATS,
                              MEMORY_ROUNDS)

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", 8000))
HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")

# Fast on purpose. Long enough to think, short enough that most rounds are
# read rather than calculated -- which is where pattern recognition comes
# from -- and short enough that a whole campaign fits in about seven minutes,
# so you play six of them and actually improve.
PLAN_SECONDS = int(os.environ.get("COMPACT_PLAN", 25))
RESOLVE_SECONDS = int(os.environ.get("COMPACT_RESOLVE", 6))
# the small game is one person against the machine, so it can be quicker
SKIRMISH_PLAN = int(os.environ.get("COMPACT_SKIRMISH_PLAN", 20))
LOBBY_IDLE_TTL = 900
CODE_CHARS = "".join(c for c in string.ascii_uppercase + string.digits
                     if c not in "0O1IL")

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ------------------------------------------------------------------ websocket
def ws_accept(key):
    return base64.b64encode(
        hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


def ws_frame(payload, opcode=0x1):
    data = payload.encode() if isinstance(payload, str) else payload
    n = len(data)
    if n < 126:
        head = struct.pack(">BB", 0x80 | opcode, n)
    elif n < 65536:
        head = struct.pack(">BBH", 0x80 | opcode, 126, n)
    else:
        head = struct.pack(">BBQ", 0x80 | opcode, 127, n)
    return head + data


class WSError(Exception):
    pass


async def ws_read(reader):
    """One frame. Returns (opcode, bytes) or raises on a closed socket."""
    head = await reader.readexactly(2)
    b1, b2 = head[0], head[1]
    opcode = b1 & 0x0F
    masked = b2 & 0x80
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", await reader.readexactly(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", await reader.readexactly(8))[0]
    if n > 1 << 20:
        raise WSError("frame too large")
    mask = await reader.readexactly(4) if masked else None
    data = await reader.readexactly(n) if n else b""
    if mask:
        data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
    return opcode, data


# ------------------------------------------------------------------ the table
class Seat:
    __slots__ = ("index", "side", "brigade", "client", "name", "order",
                 "committed")

    def __init__(self, index, side, brigade):
        self.index = index
        self.side = side
        self.brigade = brigade
        self.client = None
        self.name = None
        self.order = None
        self.committed = False

    @property
    def is_bot(self):
        return self.client is None

    def public(self, state):
        b = state.brigade(self.brigade)
        return {"seat": self.index, "side": self.side, "brigade": self.brigade,
                "kind": b.kind, "commander": b.commander,
                "name": self.name, "bot": self.is_bot,
                "committed": self.committed, "alive": b.alive,
                "strength": b.strength, "region": b.region,
                "supplied": b.supplied, "reserve": b.in_reserve}


class Room:
    def __init__(self, code, seed=None, mode="campaign", lesson=None):
        self.code = code
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.mode = mode                      # "campaign" | "skirmish"
        self.lesson = lesson                  # index into skirmish.LESSONS
        if mode == "skirmish":
            if lesson is None:
                self.state = skirmish.new_skirmish(self.seed)
                self.spec = None
            else:
                self.state, self.spec = skirmish.lesson(lesson, self.seed)
        else:
            self.spec = None
            self.state = new_game(seed=self.seed)
        self.phase = "lobby"          # lobby | planning | resolving | over
        self.ends_at = 0.0
        # Only the commanded brigades get seats. The Reserve Corps has no
        # seat by design -- nobody may sit in it.
        self.seats = []
        for b in self.state.brigades:
            if not b.corps:
                self.seats.append(Seat(len(self.seats), b.side, b.id))
        self.intel = {AZURE: Intel(), CRIMSON: Intel()}
        for side in (AZURE, CRIMSON):
            self.intel[side].update(self.state, side)
        self.signals = []             # recent, both sides, filtered on send
        self.signal_budget = {}       # seat -> used this round
        self.last_events = []
        self.corps_notes = []         # what the Reserve Corps did, and why
        self.coach_notes = {AZURE: [], CRIMSON: []}
        self.ledger = {}              # brigade -> round it fell out of supply
        self.touched = time.time()
        self.clients = set()

    # -------------------------------------------------------------- seating
    def seat_of(self, client):
        for s in self.seats:
            if s.client is client:
                return s
        return None

    def seats_of(self, client):
        """In the small game one person commands the whole side, so a client
        can hold several seats at once."""
        return [s for s in self.seats if s.client is client]

    def solo(self):
        return self.mode == "skirmish"

    def humans(self):
        return [s for s in self.seats if s.client is not None]

    def live_humans(self):
        return [s for s in self.humans()
                if self.state.brigade(s.brigade).alive]

    def take_seat(self, client, index, name):
        if not (0 <= index < len(self.seats)):
            return None, "no such seat"
        seat = self.seats[index]
        if seat.client is not None and seat.client is not client:
            return None, "somebody is already in that seat"
        if not self.solo():
            old = self.seat_of(client)
            if old and old is not seat:
                old.client = old.name = old.order = None
                old.committed = False
        seat.client = client
        seat.name = (name or "COMMANDER")[:16]
        return seat, ""

    def take_side(self, client, side, name):
        """The small game hands one person every brigade on their side."""
        taken = []
        for s in self.seats:
            if s.side == side and s.client in (None, client):
                s.client = client
                s.name = (name or "YOU")[:16]
                taken.append(s)
        return taken

    def release(self, client):
        for seat in self.seats_of(client):
            seat.client = None
            seat.name = None
            seat.order = None
            seat.committed = False
        self.clients.discard(client)


ROOMS = {}


def gen_code():
    while True:
        code = "".join(random.choice(CODE_CHARS) for _ in range(5))
        if code not in ROOMS:
            return code


# ------------------------------------------------------------------ sending
def send(client, obj):
    client.push(json.dumps(obj, separators=(",", ":")))


def broadcast(room, obj):
    frame = json.dumps(obj, separators=(",", ":"))
    for c in list(room.clients):
        c.push(frame)


def lobby_payload(room):
    return {"t": "lobby", "code": room.code, "phase": room.phase,
            "round": room.state.round, "maxRounds": MAX_ROUNDS,
            "seats": [s.public(room.state) for s in room.seats],
            "stats": BRIGADE_STATS,
            "sides": {str(k): v for k, v in SIDE_NAMES.items()}}


def state_payload(room, seat, client=None):
    """What one seat is entitled to see. The fog is applied right here."""
    side = seat.side if seat else AZURE
    mine = ([s.brigade for s in room.seats_of(client)] if client
            else ([seat.brigade] if seat else []))
    v = view(room.state, side, room.intel[side])
    v.update({
        "t": "state",
        "code": room.code,
        "phase": room.phase,
        "seconds": max(0, int(room.ends_at - time.time())) if room.ends_at else 0,
        "you": seat.index if seat else None,
        "yourBrigade": seat.brigade if seat else None,
        "maxRounds": MAX_ROUNDS,
        "seats": [s.public(room.state) for s in room.seats],
        "hubs": room.state.map.hubs,
        "capitals": {str(k): v2 for k, v2 in room.state.map.capitals.items()},
        "mode": room.mode,
        "yourBrigades": mine,
        "orders": {str(s.brigade): (s.order.to_dict() if s.order else None)
                   for s in (room.seats_of(client) if client else [])},
        "objective": (skirmish.objective(room.state, side)
                      if room.solo() else None),
        # Which regions your army can actually be fed in. Invisible supply
        # is what made this game opaque, so it is drawn on the board.
        "supply": sorted(supply_map(room.state, side)),
        "orderMenu": skirmish.ORDERS if room.solo() else None,
        "guide": skirmish.guide() if room.solo() else None,
        "rules": skirmish.rules() if room.solo() else None,
        "timed": not room.solo(),
        "maxRoundsHere": room.state.max_rounds,
        "lesson": room.spec,
        "order": (seat.order.to_dict() if seat and seat.order else None),
        "committed": (all(s.committed for s in room.seats_of(client))
                      if client and room.seats_of(client)
                      else (seat.committed if seat else False)),
        "signals": [g for g in room.signals if g["side"] == side][-12:],
        "signalsLeft": (SIGNALS_PER_ROUND
                        - room.signal_budget.get(seat.index, 0)) if seat else 0,
        "events": room.last_events,
        "coach": room.coach_notes.get(side, []),
        "warnings": _warnings(room, client, seat),
        "corpsNotes": [n for n in room.corps_notes if n["side"] == side],
        "corpsPosture": (corps.posture(room.state, side)
                         if room.state.corps_of(side) else "NONE"),
        "tilt": round(room.state.tilt(), 3),
        "forgetAfter": MEMORY_ROUNDS,
        "brief": coach.opening_brief(room.state, side),
        "verdict": room.state.verdict,
        "winner": room.state.winner,
        "hubsHeld": {str(s): len(room.state.hubs_held(s))
                     for s in (AZURE, CRIMSON)},
        "regionsHeld": {str(s): len(room.state.regions_held(s))
                        for s in (AZURE, CRIMSON)},
    })
    return v


def _warnings(room, client, seat):
    """What the coach has to say about the orders standing right now."""
    out = []
    for s in (room.seats_of(client) if client else ([seat] if seat else [])):
        b = room.state.brigade(s.brigade)
        if not (s.order and b.alive):
            continue
        for w in coach.warn(room.state, b, s.order):
            out.append(dict(w, brigade=b.id, commander=b.commander))
    rank = {"risk": 0, "care": 1, "note": 2}
    out.sort(key=lambda w: rank.get(w["level"], 3))
    return out[:3]


def push_state(room):
    for c in list(room.clients):
        send(c, state_payload(room, room.seat_of(c), c))


# ------------------------------------------------------------------ the clock
def begin_planning(room):
    room.phase = "planning"
    # The small game is one person against the machine. There is nobody to
    # wait for, so there is no clock -- the round resolves the instant you
    # commit. A countdown here was pure dead time.
    room.ends_at = 0.0 if room.solo() else time.time() + PLAN_SECONDS
    room.signal_budget = {}
    room.corps_notes = room.corps_notes
    for s in room.seats:
        s.order = None
        s.committed = False
    push_state(room)


def run_round(room):
    """Collect every order -- human where somebody is sitting, bot where
    nobody is -- and resolve them all at once."""
    before = room.state
    orders = []
    bot_seats = {AZURE: set(), CRIMSON: set()}
    for s in room.seats:
        b = room.state.brigade(s.brigade)
        if not b.alive:
            continue
        if s.client is not None and s.order is not None:
            orders.append(s.order)
        elif s.client is not None:
            orders.append(Order(s.brigade, "HOLD"))   # they ran out of clock
        else:
            bot_seats[s.side].add(s.brigade)
    for side in (AZURE, CRIMSON):
        if bot_seats[side]:
            orders += bot.plan(room.state, side, seats=bot_seats[side])

    # the Reserve Corps, which nobody sits in. The small game has none.
    notes = []
    for side in (AZURE, CRIMSON):
        if not room.state.corps_of(side):
            continue
        c_orders, c_notes = corps.plan(room.state, side)
        orders += c_orders
        for n in c_notes:
            n["side"] = side
        notes += c_notes
    room.corps_notes = notes

    room.state, events = resolve(room.state, orders)
    room.last_events = events
    room.ledger = coach.track_supply(room.state, room.ledger)
    for side in (AZURE, CRIMSON):
        room.intel[side].update(room.state, side)
        room.coach_notes[side] = coach.explain(before, room.state, events,
                                               side, room.ledger)

    if room.state.over:
        room.phase, room.ends_at = "over", 0.0
        push_state(room)
    elif room.solo():
        begin_planning(room)          # straight on, no interval to sit through
    else:
        room.phase = "resolving"
        room.ends_at = time.time() + RESOLVE_SECONDS
        push_state(room)


async def clock(room):
    """One coroutine per room, driving the phases."""
    try:
        while True:
            await asyncio.sleep(0.25)
            room.touched = time.time() if room.clients else room.touched
            if room.phase == "lobby":
                if not room.clients and time.time() - room.touched > LOBBY_IDLE_TTL:
                    ROOMS.pop(room.code, None)
                    return
                continue
            if room.phase == "over":
                await asyncio.sleep(2)
                if not room.clients:
                    ROOMS.pop(room.code, None)
                    return
                continue

            if room.solo():
                continue        # driven entirely by the commit, not the clock

            now = time.time()
            if room.phase == "planning":
                live = room.live_humans()
                everyone_in = bool(live) and all(s.committed for s in live)
                if everyone_in or now >= room.ends_at:
                    run_round(room)
            elif room.phase == "resolving" and now >= room.ends_at:
                begin_planning(room)
    except asyncio.CancelledError:
        raise
    except Exception as exc:                      # never take the server down
        sys.stderr.write("room %s clock died: %r\n" % (room.code, exc))
        ROOMS.pop(room.code, None)


# ------------------------------------------------------------------ messages
def handle(client, msg):
    t = msg.get("t")
    room = client.room

    if t == "host":
        code = gen_code()
        seed = msg.get("seed")
        room = Room(code, seed=int(seed) if seed is not None else None,
                    mode=("skirmish" if msg.get("mode") == "skirmish"
                          else "campaign"),
                    lesson=(int(msg["lesson"]) if msg.get("lesson") is not None
                            else None))
        ROOMS[code] = room
        asyncio.ensure_future(clock(room))
        join(client, room, msg.get("name"))
        if room.solo():
            begin_planning(room)          # nothing to wait for, so start
        return

    if t == "join":
        code = (msg.get("code") or "").strip().upper()
        room = ROOMS.get(code)
        if not room:
            send(client, {"t": "error", "why": "no room with that code"})
            return
        join(client, room, msg.get("name"))
        return

    if t == "ping":                    # a keepalive needs no room
        send(client, {"t": "pong"})
        return

    if room is None:
        send(client, {"t": "error", "why": "join a room first"})
        return
    room.touched = time.time()

    if t == "seat":
        seat, why = room.take_seat(client, int(msg.get("seat", -1)),
                                   msg.get("name"))
        if not seat:
            send(client, {"t": "error", "why": why})
        broadcast(room, lobby_payload(room))
        push_state(room)

    elif t == "start":
        if room.phase == "lobby":
            begin_planning(room)

    elif t == "order":
        held = room.seats_of(client)
        if not held or room.phase != "planning":
            return
        want = msg.get("brigade")
        seat = (next((s for s in held if s.brigade == want), None)
                if want is not None else held[0])
        if seat is None:
            send(client, {"t": "error", "why": "that is not your brigade"})
            return
        if seat.committed:
            return
        verb = msg.get("verb")
        if verb not in ORDERS:
            send(client, {"t": "error", "why": "no such order"})
            return
        target = msg.get("target")
        order = Order(seat.brigade, verb,
                      int(target) if target is not None else None)
        ok, why = validate(room.state, order)
        if not ok:
            send(client, {"t": "reject", "verb": verb, "why": why,
                          "brigade": seat.brigade})
            return
        seat.order = order
        send(client, state_payload(room, seat, client))

    elif t == "commit":
        held = room.seats_of(client)
        if not held or room.phase != "planning":
            return
        for seat in held:               # commits every brigade you command
            if seat.order is None:
                seat.order = Order(seat.brigade, "HOLD")
            seat.committed = True
        if room.solo():
            run_round(room)             # resolve it now; nobody else to wait on
        else:
            push_state(room)

    elif t == "signal":
        seat = room.seat_of(client)
        if not seat or room.phase != "planning":
            return
        used = room.signal_budget.get(seat.index, 0)
        if used >= SIGNALS_PER_ROUND:
            send(client, {"t": "reject", "why": "no signals left this round"})
            return
        kind = msg.get("kind")
        region = msg.get("region")
        if kind not in SIGNAL_KINDS or region is None:
            return
        region = int(region)
        if not (0 <= region < len(room.state.regions)):
            return
        room.signal_budget[seat.index] = used + 1
        room.signals.append({"side": seat.side, "kind": kind, "region": region,
                             "from": seat.name or "?", "round": room.state.round})
        room.signals = room.signals[-40:]
        push_state(room)


def join(client, room, name):
    if client.room is not None and client.room is not room:
        client.room.release(client)
    client.room = room
    room.clients.add(client)
    room.touched = time.time()
    if room.solo():
        room.take_side(client, AZURE, name)     # you command the whole side
    else:
        free = [s for s in room.seats if s.client is None and s.side == AZURE]
        if free:
            room.take_seat(client, free[0].index, name)
    send(client, {"t": "joined", "code": room.code, "mode": room.mode})
    broadcast(room, lobby_payload(room))
    push_state(room)


# ------------------------------------------------------------------ transport
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
        ".css": "text/css", ".svg": "image/svg+xml", ".ico": "image/x-icon",
        ".json": "application/json"}


class Client:
    def __init__(self, writer):
        self.writer = writer
        self.room = None
        self.closed = False

    def push(self, text):
        if self.closed:
            return
        try:
            if self.writer.transport.is_closing():
                self.closed = True
                return
            self.writer.write(ws_frame(text))
        except Exception:
            self.closed = True


async def serve_static(writer, path):
    if path in ("/", ""):
        path = "/index.html"
    safe = os.path.normpath(path).lstrip("/\\")
    full = os.path.join(WEB, safe)
    if not full.startswith(WEB) or not os.path.isfile(full):
        writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 9\r\n"
                     b"Connection: close\r\n\r\nnot found")
        return
    with open(full, "rb") as f:
        body = f.read()
    ctype = MIME.get(os.path.splitext(full)[1], "application/octet-stream")
    writer.write(("HTTP/1.1 200 OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                  "Cache-Control: no-cache\r\nConnection: close\r\n\r\n"
                  % (ctype, len(body))).encode() + body)


async def on_connect(reader, writer):
    client = None
    try:
        request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
        head = request.decode("latin-1").split("\r\n")
        method, path = (head[0].split() + ["", ""])[:2]
        headers = {}
        for line in head[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        if headers.get("upgrade", "").lower() != "websocket":
            if method != "GET":
                writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n"
                             b"Content-Length: 0\r\nConnection: close\r\n\r\n")
            else:
                await serve_static(writer, path)
            await writer.drain()
            return

        key = headers.get("sec-websocket-key", "")
        writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                      "Connection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n"
                      % ws_accept(key)).encode())
        await writer.drain()

        client = Client(writer)
        while True:
            opcode, data = await ws_read(reader)
            if opcode == 0x8:
                break
            if opcode == 0x9:
                writer.write(ws_frame(data, 0xA))
                continue
            if opcode not in (0x1, 0x2):
                continue
            try:
                msg = json.loads(data.decode())
            except Exception:
                continue
            if isinstance(msg, dict):
                handle(client, msg)
            await writer.drain()

    except (asyncio.IncompleteReadError, ConnectionResetError,
            asyncio.TimeoutError, BrokenPipeError, WSError):
        pass
    except Exception as exc:
        sys.stderr.write("connection error: %r\n" % (exc,))
    finally:
        if client is not None:
            client.closed = True
            if client.room is not None:
                room = client.room
                room.release(client)
                if room.code in ROOMS:
                    broadcast(room, lobby_payload(room))
                    push_state(room)
        try:
            writer.close()
        except Exception:
            pass


def local_addresses():
    import socket
    out = ["http://localhost:%d" % PORT]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        out.append("http://%s:%d" % (s.getsockname()[0], PORT))
        s.close()
    except Exception:
        pass
    return out


async def main():
    if not os.path.isdir(WEB):
        sys.exit("missing %s -- the browser client lives there" % WEB)
    server = await asyncio.start_server(on_connect, HOST, PORT)
    print("\n  THE IRON COMPACT")
    for url in local_addresses():
        print("    %s" % url)
    print("\n  Host a room, share the code, and anyone on your network can take"
          "\n  a seat. Every seat nobody takes is commanded by a bot.\n")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stood down\n")
