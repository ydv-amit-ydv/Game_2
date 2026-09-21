#!/usr/bin/env python3
"""
End-to-end server tests: a real WebSocket client, over a real socket,
against a real server. No mocks, because the parts most likely to be wrong
are the handshake and the framing.

    python3 -m unittest tests.test_server -v
"""
import asyncio
import base64
import json
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("COMPACT_PLAN", "2")
os.environ.setdefault("COMPACT_RESOLVE", "1")

import server                                        # noqa: E402
from engine import AZURE, CRIMSON                    # noqa: E402


class WS:
    """The smallest WebSocket client that can play the game."""

    def __init__(self, reader, writer):
        self.r, self.w = reader, writer
        self.inbox = []

    @staticmethod
    async def open(port, path="/ws"):
        r, w = await asyncio.open_connection("127.0.0.1", port)
        key = base64.b64encode(os.urandom(16)).decode()
        w.write(("GET %s HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                 "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                 "Sec-WebSocket-Version: 13\r\n\r\n" % (path, key)).encode())
        await w.drain()
        head = await r.readuntil(b"\r\n\r\n")
        assert b"101" in head, head[:80]
        return WS(r, w)

    async def send(self, obj):
        data = json.dumps(obj).encode()
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            head = struct.pack(">BB", 0x81, 0x80 | n)
        else:
            head = struct.pack(">BBH", 0x81, 0x80 | 126, n)
        self.w.write(head + mask
                     + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))
        await self.w.drain()

    async def recv(self, timeout=5):
        head = await asyncio.wait_for(self.r.readexactly(2), timeout)
        n = head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", await self.r.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", await self.r.readexactly(8))[0]
        return json.loads((await self.r.readexactly(n)).decode())

    async def until(self, kind, timeout=8, **match):
        """Next message of this type, optionally matching some fields."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            m = await self.recv(max(0.2, deadline - loop.time()))
            self.inbox.append(m)
            if m.get("t") != kind:
                continue
            if all(m.get(k) == v for k, v in match.items()):
                return m
        raise AssertionError("never saw %s %r" % (kind, match))

    async def close(self):
        try:
            self.w.close()
        except Exception:
            pass


def run(coro):
    """Run one test's coroutine on its own loop, then put out the lights --
    room clocks are long-lived tasks and leak warnings all over the suite
    if they are simply abandoned."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


class ServerCase(unittest.TestCase):
    """Each test gets its own server on its own port."""

    async def boot(self):
        server.ROOMS.clear()
        server.PLAN_SECONDS = 2
        server.RESOLVE_SECONDS = 1
        srv = await asyncio.start_server(server.on_connect, "127.0.0.1", 0)
        return srv, srv.sockets[0].getsockname()[1]


class TestHandshake(ServerCase):

    def test_serves_the_client_over_http(self):
        async def go():
            srv, port = await self.boot()
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            await w.drain()
            head = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 5)
            length = int([x for x in head.decode().split("\r\n")
                          if x.lower().startswith("content-length")][0]
                         .split(":")[1])
            body = await asyncio.wait_for(r.readexactly(length), 5)
            w.close()
            srv.close()
            return head, body
        head, body = run(go())
        self.assertIn(b"200 OK", head)
        self.assertIn(b"text/html", head)
        self.assertIn(b"THE IRON COMPACT", body)

    def test_refuses_to_walk_out_of_the_web_directory(self):
        async def go():
            srv, port = await self.boot()
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(b"GET /../server.py HTTP/1.1\r\nHost: x\r\n\r\n")
            await w.drain()
            head = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 5)
            w.close()
            srv.close()
            return head
        self.assertIn(b"404", run(go()))

    def test_websocket_upgrade(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "ping"})
            m = await ws.until("pong")
            await ws.close()
            srv.close()
            return m
        self.assertEqual(run(go())["t"], "pong")


class TestRoom(ServerCase):

    def test_hosting_seats_you_and_bots_hold_the_rest(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host", "name": "VEGA"})
            await ws.until("joined")
            st = await ws.until("state")
            await ws.close()
            srv.close()
            return st
        st = run(go())
        self.assertIsNotNone(st["you"])
        self.assertEqual(len(st["seats"]), 10)
        bots = [s for s in st["seats"] if s["bot"]]
        self.assertEqual(len(bots), 9, "every empty seat should hold a bot")

    def test_a_second_player_can_join_by_code(self):
        async def go():
            srv, port = await self.boot()
            a = await WS.open(port)
            await a.send({"t": "host", "name": "VEGA"})
            code = (await a.until("joined"))["code"]
            b = await WS.open(port)
            await b.send({"t": "join", "code": code, "name": "BRINE"})
            st = await b.until("state")
            await a.close()
            await b.close()
            srv.close()
            return st
        st = run(go())
        named = sorted(s["name"] for s in st["seats"] if s["name"])
        self.assertEqual(named, ["BRINE", "VEGA"])

    def test_a_bad_code_is_refused(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "join", "code": "ZZZZZ"})
            m = await ws.until("error")
            await ws.close()
            srv.close()
            return m
        self.assertIn("no room", run(go())["why"])

    def test_you_cannot_sit_in_a_taken_seat(self):
        async def go():
            srv, port = await self.boot()
            a = await WS.open(port)
            await a.send({"t": "host", "name": "VEGA"})
            code = (await a.until("joined"))["code"]
            mine = (await a.until("state"))["you"]
            b = await WS.open(port)
            await b.send({"t": "join", "code": code, "name": "THIEF"})
            await b.until("state")
            await b.send({"t": "seat", "seat": mine, "name": "THIEF"})
            m = await b.until("error")
            await a.close()
            await b.close()
            srv.close()
            return m
        self.assertIn("already", run(go())["why"])


class TestPlay(ServerCase):

    def test_a_round_resolves_and_the_clock_moves_on(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host", "name": "VEGA"})
            await ws.until("joined")
            await ws.until("state")
            await ws.send({"t": "start"})
            first = await ws.until("state", phase="planning")
            await ws.send({"t": "commit"})
            after = await ws.until("state", timeout=10, round=first["round"] + 1)
            await ws.close()
            srv.close()
            return first, after
        first, after = run(go())
        self.assertEqual(first["round"], 1)
        self.assertEqual(after["round"], 2)

    def test_an_illegal_order_is_refused_not_obeyed(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host"})
            await ws.until("joined")
            await ws.until("state")
            await ws.send({"t": "start"})
            await ws.until("state", phase="planning")
            # the enemy capital is the far side of the map
            await ws.send({"t": "order", "verb": "ADVANCE", "target": 0})
            await ws.send({"t": "order", "verb": "NONSENSE"})
            m = await ws.until("error")
            await ws.close()
            srv.close()
            return m
        self.assertIn("no such order", run(go())["why"])

    def test_a_legal_order_is_remembered(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host"})
            await ws.until("joined")
            st = await ws.until("state")
            await ws.send({"t": "start"})
            st = await ws.until("state", phase="planning")
            await ws.send({"t": "order", "verb": "HOLD"})
            after = await ws.until("state")
            await ws.close()
            srv.close()
            return after
        st = run(go())
        self.assertIsNotNone(st["order"])
        self.assertEqual(st["order"]["verb"], "HOLD")

    def test_signals_are_rationed(self):
        async def go():
            srv, port = await self.boot()
            server.PLAN_SECONDS = 30            # do not let the round end on us
            ws = await WS.open(port)
            await ws.send({"t": "host"})
            await ws.until("joined")
            await ws.until("state")
            await ws.send({"t": "start"})
            await ws.until("state", phase="planning")
            for _ in range(4):
                await ws.send({"t": "signal", "kind": "ATTACK", "region": 5})
            m = await ws.until("reject")
            await ws.close()
            srv.close()
            return m
        self.assertIn("signals left", run(go())["why"])


class TestFog(ServerCase):

    def test_the_server_never_sends_what_you_cannot_see(self):
        """The fog is applied here, not in the browser. An enemy brigade
        nobody has scouted must not be sitting in the client's memory."""
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host"})
            await ws.until("joined")
            st = await ws.until("state")
            await ws.close()
            srv.close()
            return st
        st = run(go())
        visible = set(st["visible"])
        mine = st["seats"][0]["side"]
        enemies = [b for b in st["brigades"] if b["side"] != mine]
        for b in enemies:
            self.assertIn(b["region"], visible,
                          "an unseen enemy brigade was sent to the client")
        self.assertLess(len(visible), len(st["regions"]),
                        "the client was handed the whole map")

    def test_you_are_told_your_own_army_in_full(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host"})
            await ws.until("joined")
            st = await ws.until("state")
            await ws.close()
            srv.close()
            return st
        st = run(go())
        mine = [b for b in st["brigades"] if b.get("mine")]
        self.assertEqual(len(mine), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
