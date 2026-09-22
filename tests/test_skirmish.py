#!/usr/bin/env python3
"""
The small game.

Most of these are tests that something is *absent*. The full campaign became
unplayable by accretion, so the things that matter here are the count of
orders, the count of brigades, and the fact that there is exactly one way to
win and one sentence describing it.
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import resolve, bot, skirmish, Order, AZURE, CRIMSON
from engine.constants import ORDERS as ALL_ORDERS, MAX_ROUNDS
from engine.orders import validate

from test_server import WS, ServerCase, run       # noqa: E402
import server                                     # noqa: E402


class TestShape(unittest.TestCase):

    def test_three_brigades_a_side(self):
        s = skirmish.new_skirmish(seed=1)
        self.assertEqual(len(s.living(AZURE)), 3)
        self.assertEqual(len(s.living(CRIMSON)), 3)
        self.assertEqual(s.corps_of(AZURE), [], "no corps in the small game")

    def test_four_orders_not_nine(self):
        self.assertEqual(len(skirmish.ORDERS), 4)
        for o in skirmish.ORDERS:
            self.assertIn(o["verb"], ALL_ORDERS,
                          "a small-game order must be a real engine order")
            self.assertTrue(o["label"] and o["blurb"])

    def test_a_small_readable_board(self):
        s = skirmish.new_skirmish(seed=1)
        self.assertEqual(len(s.regions), 35)
        passable = sum(1 for i in range(len(s.regions)) if s.map.passable(i))
        self.assertGreater(passable, 24)

    def test_one_objective_and_no_hubs(self):
        s = skirmish.new_skirmish(seed=1)
        self.assertEqual(s.map.hubs, [], "hubs are a second thing to learn")
        o = skirmish.objective(s, AZURE)
        self.assertEqual(o["target"], s.map.capitals[CRIMSON])
        self.assertGreater(o["distance"], 0)
        self.assertIn("round", o["detail"])

    def test_it_is_shorter_than_the_campaign(self):
        s = skirmish.new_skirmish(seed=1)
        self.assertEqual(s.max_rounds, skirmish.SKIRMISH_ROUNDS)
        self.assertLess(s.max_rounds, MAX_ROUNDS)

    def test_the_board_is_still_symmetric(self):
        for seed in range(8):
            s = skirmish.new_skirmish(seed=seed)
            for rid in range(len(s.regions)):
                self.assertEqual(s.map.terrain[rid],
                                 s.map.terrain[s.map.mirror(rid)],
                                 "seed %d: the small board is lopsided" % seed)

    def test_the_keeps_can_reach_each_other(self):
        for seed in range(10):
            s = skirmish.new_skirmish(seed=seed)
            self.assertGreater(
                s.map.distance(s.map.capitals[AZURE], s.map.capitals[CRIMSON]),
                0, "seed %d: you cannot reach the objective" % seed)


class TestNoHubsNoFreeWin(unittest.TestCase):

    def test_an_empty_hub_list_does_not_win_the_game(self):
        """'Held every hub' is trivially true of a board with no hubs. That
        would have handed both sides victory on round two."""
        s = skirmish.new_skirmish(seed=1)
        s, _ = resolve(s, [])
        self.assertFalse(s.over, "a hubless board declared a winner at once")
        self.assertEqual(s.hub_streak[AZURE], 0)

    def test_taking_the_keep_wins_it(self):
        s = skirmish.new_skirmish(seed=1)
        keep = s.map.capitals[CRIMSON]
        for b in s.living(CRIMSON):
            b.alive = False
        a = s.living(AZURE)[0]
        a.region = sorted(r for r in s.map.adj(keep) if s.map.passable(r))[0]
        s2, _ = resolve(s, [Order(a.id, "ADVANCE", keep)])
        self.assertTrue(s2.over)
        self.assertEqual(s2.winner, AZURE)

    def test_a_whole_skirmish_finishes_inside_its_own_clock(self):
        for seed in range(6):
            s = skirmish.new_skirmish(seed=seed)
            guard = 0
            while not s.over and guard < skirmish.SKIRMISH_ROUNDS + 3:
                s, _ = resolve(s, bot.plan(s, AZURE) + bot.plan(s, CRIMSON))
                guard += 1
            self.assertTrue(s.over, "seed %d never finished" % seed)
            self.assertLessEqual(s.round, skirmish.SKIRMISH_ROUNDS)


class TestLessons(unittest.TestCase):

    def test_there_are_three_and_each_teaches_one_thing(self):
        self.assertEqual(len(skirmish.LESSONS), 3)
        for spec in skirmish.LESSONS:
            self.assertTrue(spec["teach"].strip())
            self.assertTrue(spec["goal"].strip())
            self.assertLessEqual(spec["rounds"], skirmish.SKIRMISH_ROUNDS)

    def test_the_first_two_have_nobody_shooting_back(self):
        for i in (0, 1):
            s, spec = skirmish.lesson(i)
            self.assertEqual(s.living(CRIMSON), [],
                             "lesson %d should be unopposed" % i)
            self.assertEqual(len(s.living(AZURE)), 3)

    def test_the_last_one_puts_a_dug_in_defender_in_the_way(self):
        s, spec = skirmish.lesson(2)
        foes = s.living(CRIMSON)
        self.assertEqual(len(foes), 1)
        self.assertGreater(foes[0].entrenched, 0)

    def test_a_lesson_index_out_of_range_is_clamped(self):
        for i in (-5, 99):
            s, spec = skirmish.lesson(i)
            self.assertIn(spec, skirmish.LESSONS)

    def test_every_lesson_is_playable_to_the_end(self):
        for i in range(len(skirmish.LESSONS)):
            s, spec = skirmish.lesson(i)
            guard = 0
            while not s.over and guard < spec["rounds"] + 3:
                orders = bot.plan(s, AZURE)
                for o in orders:
                    ok, why = validate(s, o)
                    self.assertTrue(ok, "lesson %d: %r %s" % (i, o, why))
                s, _ = resolve(s, orders + bot.plan(s, CRIMSON))
                guard += 1
            self.assertTrue(s.over, "lesson %d never ended" % i)


class TestExplaining(unittest.TestCase):
    """A player should never have to guess what a brigade is or what the
    supply rule says, and the numbers on screen must be the engine's."""

    def test_every_brigade_has_a_card_with_real_numbers(self):
        from engine.constants import BRIGADE_STATS
        cards = skirmish.guide()
        self.assertEqual(len(cards), 3)
        for c in cards:
            st = BRIGADE_STATS[c["kind"]]
            self.assertEqual(c["strength"], st["strength"])
            self.assertEqual(c["moves"], st["pace"])
            for field in ("name", "is", "does", "watch", "attack", "defend"):
                self.assertTrue(str(c[field]).strip(), "%s has no %s" % (c, field))

    def test_the_rules_quote_the_engine_not_a_guess(self):
        from engine.constants import (SUPPLY_RANGE, STARVE_LOSS,
                                      CONCENTRATION_BONUS)
        blob = " ".join(r["head"] + " " + r["body"] for r in skirmish.rules())
        self.assertIn(str(SUPPLY_RANGE), blob)
        self.assertIn(str(STARVE_LOSS), blob)
        self.assertIn(str(int(CONCENTRATION_BONUS)), blob)

    def test_the_rules_say_how_to_build_a_depot(self):
        blob = " ".join(r["body"].lower() for r in skirmish.rules())
        self.assertIn("build", blob)
        self.assertIn("depot", blob)

    def test_every_order_says_what_it_does(self):
        for o in skirmish.ORDERS:
            self.assertGreater(len(o["blurb"]), 20,
                               "%s needs a real explanation" % o["label"])


class TestSoloServer(ServerCase):

    def test_hosting_a_skirmish_gives_you_the_whole_side(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host", "mode": "skirmish", "name": "YOU"})
            await ws.until("joined")
            st = await ws.until("state", phase="planning")
            await ws.close()
            srv.close()
            return st
        st = run(go())
        self.assertEqual(st["mode"], "skirmish")
        self.assertEqual(len(st["yourBrigades"]), 3,
                         "one person commands the whole side")
        self.assertEqual(len(st["orderMenu"]), 4)
        self.assertIsNotNone(st["objective"])
        self.assertTrue(st["supply"], "the supply range must be drawable")

    def test_there_is_no_clock_to_wait_out(self):
        """Solo is one person against the machine. A countdown is dead time."""
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host", "mode": "skirmish"})
            await ws.until("joined")
            st = await ws.until("state", phase="planning")
            await ws.close()
            srv.close()
            return st
        st = run(go())
        self.assertFalse(st["timed"])
        self.assertEqual(st["seconds"], 0)

    def test_committing_resolves_the_round_at_once(self):
        async def go():
            srv, port = await self.boot()
            server.PLAN_SECONDS = 999      # any wait would hang this test
            ws = await WS.open(port)
            await ws.send({"t": "host", "mode": "skirmish"})
            await ws.until("joined")
            await ws.until("state", phase="planning")
            await ws.send({"t": "commit"})
            st = await ws.until("state", timeout=3, round=2)
            await ws.close()
            srv.close()
            return st
        self.assertEqual(run(go())["round"], 2)

    def test_the_client_is_told_the_brigades_and_the_rules(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host", "mode": "skirmish"})
            await ws.until("joined")
            st = await ws.until("state", phase="planning")
            await ws.close()
            srv.close()
            return st
        st = run(go())
        self.assertEqual(len(st["guide"]), 3)
        self.assertGreaterEqual(len(st["rules"]), 3)
        self.assertEqual(st["maxRoundsHere"], skirmish.SKIRMISH_ROUNDS)

    def test_the_campaign_keeps_its_clock(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host"})
            await ws.until("joined")
            await ws.until("state")
            await ws.send({"t": "start"})
            st = await ws.until("state", phase="planning")
            await ws.close()
            srv.close()
            return st
        st = run(go())
        self.assertTrue(st["timed"], "the multiplayer game still needs a clock")
        self.assertGreater(st["seconds"], 0)

    def test_it_starts_without_waiting_for_anybody(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host", "mode": "skirmish"})
            await ws.until("joined")
            st = await ws.until("state", phase="planning")
            await ws.close()
            srv.close()
            return st
        self.assertEqual(run(go())["phase"], "planning")

    def test_one_commit_seals_every_brigade(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host", "mode": "skirmish"})
            await ws.until("joined")
            first = await ws.until("state", phase="planning")
            await ws.send({"t": "commit"})
            after = await ws.until("state", timeout=10,
                                   round=first["round"] + 1)
            await ws.close()
            srv.close()
            return after
        self.assertEqual(run(go())["round"], 2)

    def test_you_cannot_order_a_brigade_that_is_not_yours(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host", "mode": "skirmish"})
            await ws.until("joined")
            st = await ws.until("state", phase="planning")
            theirs = max(b["id"] for b in st["brigades"]) + 10
            await ws.send({"t": "order", "brigade": theirs, "verb": "HOLD"})
            m = await ws.until("error")
            await ws.close()
            srv.close()
            return m
        self.assertIn("not your brigade", run(go())["why"])

    def test_a_lesson_carries_its_own_teaching_text(self):
        async def go():
            srv, port = await self.boot()
            ws = await WS.open(port)
            await ws.send({"t": "host", "mode": "skirmish", "lesson": 1})
            await ws.until("joined")
            st = await ws.until("state", phase="planning")
            await ws.close()
            srv.close()
            return st
        st = run(go())
        self.assertEqual(st["lesson"]["id"], "supply")
        # The lesson deliberately teaches supply without using the word --
        # it says what actually happens instead, which is the point.
        teach = st["lesson"]["teach"].lower()
        self.assertIn("3 regions", teach)
        self.assertIn("depot", teach)
        self.assertIn("strength a round", teach)

    def test_the_campaign_still_works_alongside_it(self):
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
        self.assertEqual(st["mode"], "campaign")
        self.assertEqual(len(st["seats"]), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
