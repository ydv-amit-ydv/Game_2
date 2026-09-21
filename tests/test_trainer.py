#!/usr/bin/env python3
"""
The Reserve Corps, the coach, and memory decay.

These three exist to make the game train rather than drain, so the tests are
mostly about restraint: the corps must lean without cheating, the coach must
warn without deciding, and memory must actually be lost rather than quietly
kept on screen.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import (new_game, resolve, bot, corps, coach, Order, view, Intel,
                    AZURE, CRIMSON, ADVANCE, ASSAULT, HOLD, FORAGE, SUPPLY,
                    RESERVE, LINE, LIGHT, HORSE, GUNS, PIONEERS)
from engine.constants import (MEMORY_ROUNDS, CORPS_ORDER_OF_BATTLE,
                              CORPS_PRESS_AT, STARVE_LOSS)
from engine.orders import validate
from engine.resolve import supply_map


def orders_for(state, side):
    seats = {b.id for b in state.commanded(side)}
    return bot.plan(state, side, seats=seats) + corps.plan(state, side)[0]


def play(state, rounds=99):
    n = 0
    while not state.over and n < rounds:
        state, ev = resolve(state, orders_for(state, AZURE)
                            + orders_for(state, CRIMSON))
        n += 1
    return state


class TestCorpsExists(unittest.TestCase):

    def test_both_sides_get_the_same_corps(self):
        s = new_game(seed=1)
        for side in (AZURE, CRIMSON):
            kinds = [b.kind for b in s.corps_of(side)]
            self.assertEqual(kinds, list(CORPS_ORDER_OF_BATTLE))

    def test_the_corps_is_never_a_seat(self):
        s = new_game(seed=1)
        self.assertEqual(len(s.commanded(AZURE)), 5)
        self.assertEqual(len(s.corps_of(AZURE)), 2)
        for b in s.corps_of(AZURE):
            self.assertTrue(b.corps)
        for b in s.commanded(AZURE):
            self.assertFalse(b.corps)

    def test_a_match_without_a_corps_still_works(self):
        s = new_game(seed=1, corps=False)
        self.assertEqual(s.corps_of(AZURE), [])
        self.assertEqual(len(s.living(AZURE)), 5)


class TestCorpsJudgement(unittest.TestCase):

    def test_an_even_match_needs_no_intervention(self):
        s = new_game(seed=1)
        self.assertEqual(corps.posture(s, AZURE), corps.STEADY)
        self.assertEqual(corps.posture(s, CRIMSON), corps.STEADY)

    def test_it_presses_for_the_side_that_is_losing(self):
        s = new_game(seed=1)
        for r in s.regions:                      # hand Crimson the map
            if r.owner is not None:
                r.owner = CRIMSON
        for h in s.map.hubs:
            s.region(h).owner = CRIMSON
        self.assertEqual(corps.posture(s, AZURE), corps.PRESSING)
        self.assertEqual(corps.posture(s, CRIMSON), corps.EASING)

    def test_tilt_is_zero_at_the_start_and_signed_the_right_way(self):
        s = new_game(seed=1)
        self.assertAlmostEqual(s.tilt(), 0.0, places=6)
        for h in s.map.hubs:
            s.region(h).owner = AZURE
        self.assertGreater(s.tilt(), 0)

    def test_it_only_ever_issues_legal_orders(self):
        s = new_game(seed=4)
        for _ in range(12):
            if s.over:
                break
            for side in (AZURE, CRIMSON):
                for o in corps.plan(s, side)[0]:
                    ok, why = validate(s, o)
                    self.assertTrue(ok, "corps issued %r: %s" % (o, why))
            s, _ = resolve(s, orders_for(s, AZURE) + orders_for(s, CRIMSON))

    def test_every_order_comes_with_a_reason(self):
        """The corps is a teaching device. An intervention nobody can read
        is just the machine playing for you."""
        s = new_game(seed=2)
        for side in (AZURE, CRIMSON):
            orders, notes = corps.plan(s, side)
            self.assertEqual(len(orders), len(notes))
            for n in notes:
                self.assertTrue(n["why"].strip(), "an order with no reason")
                self.assertIn(n["posture"],
                              (corps.PRESSING, corps.STEADY, corps.EASING))

    def test_it_commands_only_its_own_corps(self):
        s = new_game(seed=2)
        mine = {b.id for b in s.corps_of(AZURE)}
        for o in corps.plan(s, AZURE)[0]:
            self.assertIn(o.brigade, mine)

    def test_it_is_deterministic(self):
        s = new_game(seed=3)
        a = [o.to_dict() for o in corps.plan(s, AZURE)[0]]
        b = [o.to_dict() for o in corps.plan(s, AZURE)[0]]
        self.assertEqual(a, b)

    def test_it_does_not_break_mirror_symmetry(self):
        """Both sides get the same corps, so a mirror match must still be a
        perfect reflection and still end level."""
        flip = {None: None, AZURE: CRIMSON, CRIMSON: AZURE}
        for seed in range(5):
            s = new_game(seed=seed)
            m = s.map
            half = len(s.brigades) // 2
            while not s.over:
                s, _ = resolve(s, orders_for(s, AZURE) + orders_for(s, CRIMSON))
                for a in s.brigades[:half]:
                    c = s.brigades[a.id + half]
                    self.assertEqual(
                        (a.alive, a.strength, m.mirror(a.region)),
                        (c.alive, c.strength, c.region),
                        "seed %d: the corps broke symmetry" % seed)
                for r in s.regions:
                    self.assertEqual(flip[r.owner],
                                     s.region(m.mirror(r.id)).owner)
            self.assertIsNone(s.winner, "seed %d: a mirror match was won" % seed)


class TestCoachWarns(unittest.TestCase):

    def _brigade(self, s, side, kind):
        return next(b for b in s.living(side) if b.kind == kind)

    def test_it_warns_before_you_march_out_of_supply(self):
        s = new_game(seed=1)
        b = self._brigade(s, AZURE, LINE)
        reach = supply_map(s, AZURE)
        # stand it on the edge of the chain so one step takes it outside
        edge, far = None, None
        for rid, d in sorted(reach.items()):
            for n in sorted(s.map.adj(rid)):
                if s.map.passable(n) and n not in reach and not s.at(n):
                    edge, far = rid, n
                    break
            if far is not None:
                break
        self.assertIsNotNone(far, "this map has no edge of supply to stand on")
        b.region = edge
        w = coach.warn(s, b, Order(b.id, ADVANCE, far))
        self.assertTrue(any("supply" in x["text"].lower() for x in w),
                        "no warning about leaving the chain")
        self.assertEqual(w[0]["level"], coach.RISK)

    def test_it_says_nothing_useless_about_a_sound_order(self):
        s = new_game(seed=1)
        b = self._brigade(s, AZURE, LINE)
        w = coach.warn(s, b, Order(b.id, HOLD))
        for x in w:
            self.assertNotEqual(x["level"], coach.RISK,
                                "a safe hold should not raise an alarm")

    def test_it_warns_about_walking_back_into_the_same_wall(self):
        s = new_game(seed=1)
        b = self._brigade(s, AZURE, LINE)
        target = sorted(r for r in s.map.adj(b.region) if s.map.passable(r))[0]
        b.balk_at, b.balk_for = target, 3
        w = coach.warn(s, b, Order(b.id, ADVANCE, target))
        self.assertTrue(any("threw you off" in x["text"] for x in w))

    def test_it_notices_a_brigade_attacking_alone(self):
        s = new_game(seed=1)
        a = self._brigade(s, AZURE, LINE)
        c = s.living(CRIMSON)[0]
        # put the two of them somewhere nobody else is standing
        ground = approach = None
        cap = s.map.capitals[AZURE]
        for rid in range(len(s.regions)):
            if not s.map.passable(rid) or s.map.distance(cap, rid) < 3:
                continue
            nbs = [n for n in sorted(s.map.adj(rid)) if s.map.passable(n)]
            if nbs:
                ground, approach = rid, nbs[0]
                break
        self.assertIsNotNone(ground)
        for other in s.living():                 # clear the neighbourhood
            other.region = s.map.capitals[other.side]
        a.region, a.strength = approach, 3
        c.region, c.strength = ground, 12
        w = coach.warn(s, a, Order(a.id, ASSAULT, ground))
        self.assertTrue(any("lighter" in x["text"] for x in w))

    def test_it_never_changes_the_game(self):
        s = new_game(seed=1)
        before = s.digest()
        for b in s.living(AZURE):
            coach.warn(s, b, Order(b.id, ADVANCE, s.map.adj(b.region)[0]))
            coach.warn(s, b, Order(b.id, HOLD))
        self.assertEqual(s.digest(), before)

    def test_it_returns_at_most_three_warnings(self):
        s = new_game(seed=1)
        for b in s.living(AZURE):
            for verb in (HOLD, ADVANCE, ASSAULT, FORAGE, RESERVE):
                w = coach.warn(s, b, Order(b.id, verb, s.map.adj(b.region)[0]))
                self.assertLessEqual(len(w), 3)


class TestCoachExplains(unittest.TestCase):

    def test_it_names_the_round_the_chain_broke(self):
        s = new_game(seed=1)
        b = s.living(AZURE)[0]
        reach = supply_map(s, AZURE)
        stranded = next(r for r in range(len(s.regions))
                        if s.map.passable(r) and r not in reach and not s.at(r))
        b.region = stranded
        s.region(stranded).forage = 0
        s.round = 6
        ledger = {b.id: 6}
        s.round = 9
        after, ev = resolve(s, [Order(b.id, HOLD)])
        notes = coach.explain(s, after, ev, AZURE, ledger)
        self.assertTrue(any("round 6" in n["text"] for n in notes),
                        "a starvation must name when the chain broke: %r" % notes)

    def test_it_credits_concentration_when_it_wins_the_ground(self):
        s = new_game(seed=1)
        az = s.living(AZURE)
        c = s.living(CRIMSON)[0]
        ground = one = two = None
        for rid in range(len(s.regions)):
            if not s.map.passable(rid) or s.at(rid):
                continue
            nbs = [n for n in sorted(s.map.adj(rid))
                   if s.map.passable(n) and not s.at(n)]
            if len(nbs) >= 2:
                ground, one, two = rid, nbs[0], nbs[1]
                break
        c.region, c.strength = ground, 4
        az[0].region, az[0].strength = one, 9
        az[1].region, az[1].strength = two, 9
        after, ev = resolve(s, [Order(az[0].id, ASSAULT, ground),
                                Order(az[1].id, ASSAULT, ground),
                                Order(c.id, HOLD)])
        notes = coach.explain(s, after, ev, AZURE)
        self.assertTrue(any("together" in n["text"] for n in notes),
                        "winning by concentration should be named: %r" % notes)

    def test_the_ledger_forgets_a_brigade_that_gets_fed_again(self):
        s = new_game(seed=1)
        b = s.living(AZURE)[0]
        b.supplied = False
        s.round = 4
        ledger = coach.track_supply(s, {})
        self.assertEqual(ledger.get(b.id), 4)
        b.supplied = True
        ledger = coach.track_supply(s, ledger)
        self.assertNotIn(b.id, ledger)

    def test_explaining_never_changes_the_game(self):
        s = new_game(seed=2)
        after, ev = resolve(s, orders_for(s, AZURE) + orders_for(s, CRIMSON))
        d = after.digest()
        coach.explain(s, after, ev, AZURE)
        coach.explain(s, after, ev, CRIMSON)
        self.assertEqual(after.digest(), d)


class TestMemoryDecay(unittest.TestCase):

    def test_a_sighting_is_dropped_once_it_is_old_enough(self):
        """Not greyed out -- gone. Remembering where they were is the
        exercise, so the display must stop doing it for you."""
        from engine import visible
        s = new_game(seed=1)
        scout = self_scout = next(b for b in s.living(AZURE) if b.kind == LIGHT)
        foe = s.living(CRIMSON)[0]

        # send a scout out to a region well clear of home, and stand an
        # enemy on it so there is something worth remembering
        cap = s.map.capitals[AZURE]
        far = next(rid for rid in range(len(s.regions))
                   if s.map.passable(rid) and s.map.distance(cap, rid) >= 4)
        perch = sorted(r for r in s.map.adj(far) if s.map.passable(r))[0]
        scout.region, foe.region = perch, far

        intel = Intel()
        intel.update(s, AZURE)
        self.assertTrue(intel.sightings.get(far),
                        "the scout failed to see the enemy it is standing beside")

        scout.region = cap                       # the scout comes home
        self.assertNotIn(far, visible(s, AZURE),
                         "the region must actually go dark to be forgotten")

        s.round += 1
        fresh = intel.to_dict(s, AZURE)["regions"][str(far)]
        self.assertTrue(fresh["enemies"], "a fresh memory was lost at once")
        self.assertTrue(fresh["fading"], "a remembered sighting should be marked")

        s.round += MEMORY_ROUNDS
        old = intel.to_dict(s, AZURE)["regions"][str(far)]
        self.assertEqual(old["enemies"], [],
                         "the sighting should have been forgotten by now")
        # ...but that the ground was ever seen at all is long-term knowledge
        self.assertEqual(old["seen"], fresh["seen"],
                         "when you saw it is not something you forget")
        self.assertEqual(old["owner"], intel.owner.get(far),
                         "who held it is long-term knowledge and stays")

    def test_who_owns_what_is_never_forgotten(self):
        """Terrain and ownership are long-term knowledge. Only where the
        enemy was standing decays."""
        s = new_game(seed=1)
        intel = Intel()
        intel.update(s, AZURE)
        known = dict(intel.owner)
        s.round += MEMORY_ROUNDS * 4
        out = intel.to_dict(s, AZURE)["regions"]
        for rid, owner in known.items():
            self.assertEqual(out[str(rid)]["owner"], owner)


if __name__ == "__main__":
    unittest.main(verbosity=2)
