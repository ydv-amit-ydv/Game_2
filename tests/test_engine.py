#!/usr/bin/env python3
"""
Engine tests. Plain unittest, no dependencies:

    python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import (new_game, resolve, bot, generate, Order, AZURE, CRIMSON,
                    ADVANCE, ASSAULT, HOLD, SCREEN, SUPPLY, FORAGE, RECON,
                    PARLEY, RESERVE, LINE, LIGHT, HORSE, GUNS, PIONEERS,
                    validate_order_of_battle, visible, Intel, view)
from engine.constants import (CONCENTRATION_BONUS, STARVE_LOSS, SUPPLY_RANGE,
                              DRAFT_BUDGET, BRIGADE_STATS, PASSABLE, MAX_ROUNDS)
from engine.orders import validate, sanitise
from engine.resolve import supply_map
from engine.state import DEFAULT_ORDER_OF_BATTLE


def place(state, bid, rid, strength=None):
    """Put a brigade somewhere for the purpose of an experiment."""
    b = state.brigade(bid)
    b.region = rid
    if strength is not None:
        b.strength = strength
    return b


class TestMap(unittest.TestCase):

    def test_adjacency_is_symmetric(self):
        m = generate(seed=1)
        for rid in range(m.w * m.h):
            for n in m.adj(rid):
                self.assertIn(rid, m.adj(n),
                              "%d -> %d is one-way" % (rid, n))

    def test_neighbour_count(self):
        m = generate(seed=1)
        interior = m.rid(5, 3)
        self.assertEqual(len(m.adj(interior)), 6)
        corner = m.rid(0, 0)
        self.assertLess(len(m.adj(corner)), 6)

    def test_map_is_mirror_symmetric(self):
        """Neither side may ever blame the ground."""
        for seed in range(12):
            m = generate(seed=seed)
            for rid in range(m.w * m.h):
                self.assertEqual(m.terrain[rid], m.terrain[m.mirror(rid)],
                                 "seed %d: region %d breaks symmetry" % (seed, rid))

    def test_capitals_can_reach_each_other(self):
        for seed in range(25):
            m = generate(seed=seed)
            d = m.distance(m.capitals[AZURE], m.capitals[CRIMSON])
            self.assertGreater(d, 0, "seed %d has an unreachable capital" % seed)

    def test_hubs_are_passable_and_distinct(self):
        for seed in range(12):
            m = generate(seed=seed)
            self.assertEqual(len(set(m.hubs)), len(m.hubs))
            for h in m.hubs:
                self.assertIn(m.terrain[h], PASSABLE)

    def test_sight_stops_at_cover(self):
        m = generate(seed=2)
        src = m.capitals[AZURE]
        near = m.sight(src, 1)
        far = m.sight(src, 3)
        self.assertLessEqual(len(near), len(far))
        self.assertIn(src, near)


class TestDraft(unittest.TestCase):

    def test_default_order_of_battle_is_legal(self):
        ok, why = validate_order_of_battle(list(DEFAULT_ORDER_OF_BATTLE))
        self.assertTrue(ok, why)

    def test_budget_is_enforced(self):
        ok, why = validate_order_of_battle([LINE, LINE, GUNS, HORSE, PIONEERS])
        self.assertFalse(ok)
        self.assertIn("points", why)

    def test_cap_is_enforced(self):
        ok, why = validate_order_of_battle([GUNS, GUNS, LIGHT, LIGHT, LIGHT])
        self.assertFalse(ok)

    def test_wrong_size_rejected(self):
        ok, _ = validate_order_of_battle([LINE, LINE])
        self.assertFalse(ok)

    def test_cheapest_legal_army_fits(self):
        cheap = [LIGHT, LIGHT, PIONEERS, HORSE, LINE]
        ok, why = validate_order_of_battle(cheap)
        self.assertTrue(ok, why)
        self.assertLessEqual(
            sum(BRIGADE_STATS[k]["points"] for k in cheap), DRAFT_BUDGET)


class TestDeterminism(unittest.TestCase):

    def test_same_seed_same_map(self):
        self.assertEqual(generate(seed=5).terrain, generate(seed=5).terrain)

    def test_identical_matches_produce_identical_digests(self):
        runs = []
        for _ in range(3):
            s = new_game(seed=11)
            while not s.over:
                s, _ = resolve(s, bot.plan(s, AZURE) + bot.plan(s, CRIMSON))
            runs.append(s.digest())
        self.assertEqual(len(set(runs)), 1, "the engine is not deterministic")

    def test_order_arrival_sequence_is_irrelevant(self):
        """Orders that arrive in a different sequence must resolve the same."""
        base = new_game(seed=4)
        orders = bot.plan(base, AZURE) + bot.plan(base, CRIMSON)
        a, _ = resolve(base, orders)
        b, _ = resolve(base, list(reversed(orders)))
        self.assertEqual(a.digest(), b.digest())

    def test_resolve_does_not_mutate_its_input(self):
        s = new_game(seed=6)
        before = s.digest()
        resolve(s, bot.plan(s, AZURE) + bot.plan(s, CRIMSON))
        self.assertEqual(s.digest(), before)

    def test_serialisation_round_trips(self):
        from engine.state import GameState
        s = new_game(seed=9)
        s, _ = resolve(s, bot.plan(s, AZURE) + bot.plan(s, CRIMSON))
        again = GameState.from_dict(s.to_dict())
        self.assertEqual(s.digest(), again.digest())


class TestOrders(unittest.TestCase):

    def test_unreachable_target_is_rejected(self):
        s = new_game(seed=1)
        b = s.living(AZURE)[0]
        far = s.map.capitals[CRIMSON]
        ok, why = validate(s, Order(b.id, ADVANCE, far))
        self.assertFalse(ok)

    def test_only_pioneers_build_depots(self):
        s = new_game(seed=1)
        for b in s.living(AZURE):
            ok, _ = validate(s, Order(b.id, SUPPLY))
            self.assertEqual(ok, b.kind == PIONEERS)

    def test_illegal_order_becomes_hold(self):
        s = new_game(seed=1)
        b = s.living(AZURE)[0]
        final, rejected = sanitise(s, [Order(b.id, ADVANCE, 999)])
        self.assertTrue(rejected)
        self.assertEqual(
            [o.verb for o in final if o.brigade == b.id], [HOLD])

    def test_every_living_brigade_gets_exactly_one_order(self):
        s = new_game(seed=1)
        final, _ = sanitise(s, [])
        self.assertEqual(len(final), len(s.living()))
        self.assertEqual(len({o.brigade for o in final}), len(final))

    def test_last_legal_order_wins(self):
        s = new_game(seed=1)
        b = s.living(AZURE)[0]
        step = sorted(r for r in s.map.adj(b.region) if s.map.passable(r))[0]
        final, _ = sanitise(s, [Order(b.id, HOLD), Order(b.id, ADVANCE, step)])
        mine = [o for o in final if o.brigade == b.id][0]
        self.assertEqual(mine.verb, ADVANCE)


class TestSupply(unittest.TestCase):

    def test_capital_supplies_its_surroundings(self):
        s = new_game(seed=1)
        reach = supply_map(s, AZURE)
        self.assertIn(s.map.capitals[AZURE], reach)
        self.assertEqual(reach[s.map.capitals[AZURE]], 0)

    def test_supply_does_not_reach_past_its_range(self):
        s = new_game(seed=1)
        reach = supply_map(s, AZURE)
        self.assertTrue(all(d <= SUPPLY_RANGE for d in reach.values()))

    def test_enemy_brigades_sever_the_chain(self):
        s = new_game(seed=1)
        cap = s.map.capitals[AZURE]
        gate = sorted(r for r in s.map.adj(cap) if s.map.passable(r))
        before = supply_map(s, AZURE)
        for i, rid in enumerate(gate):
            if i < len(s.living(CRIMSON)):
                place(s, s.living(CRIMSON)[i].id, rid)
        after = supply_map(s, AZURE)
        self.assertLess(len(after), len(before),
                        "an enemy astride the road changed nothing")

    def test_a_depot_extends_supply(self):
        s = new_game(seed=1)
        before = supply_map(s, AZURE)
        far = max(before, key=lambda r: before[r])
        s.region(far).depot = AZURE
        after = supply_map(s, AZURE)
        self.assertGreaterEqual(len(after), len(before))

    def test_starving_costs_strength(self):
        s = new_game(seed=1)
        b = s.living(AZURE)[0]
        # strand it somewhere no supply can follow
        stranded = None
        reach = supply_map(s, AZURE)
        for rid in range(len(s.regions)):
            if s.map.passable(rid) and rid not in reach and not s.at(rid):
                stranded = rid
                break
        self.assertIsNotNone(stranded, "the map left nowhere to strand a brigade")
        place(s, b.id, stranded)
        s.region(stranded).forage = 0
        was = s.brigade(b.id).strength
        s2, ev = resolve(s, [Order(b.id, HOLD)])
        self.assertEqual(s2.brigade(b.id).strength, was - STARVE_LOSS)
        self.assertTrue(any(e["t"] == "starve" for e in ev))

    def test_forage_feeds_a_cut_off_brigade(self):
        s = new_game(seed=1)
        b = s.living(AZURE)[0]
        reach = supply_map(s, AZURE)
        stranded = next(rid for rid in range(len(s.regions))
                        if s.map.passable(rid) and rid not in reach
                        and not s.at(rid))
        place(s, b.id, stranded)
        s.region(stranded).forage = 3
        was = s.brigade(b.id).strength
        s2, ev = resolve(s, [Order(b.id, FORAGE)])
        self.assertEqual(s2.brigade(b.id).strength, was)
        self.assertTrue(any(e["t"] == "forage" for e in ev))
        self.assertEqual(s2.region(stranded).forage, 2)


class TestCombat(unittest.TestCase):

    def _duel(self, seed=1):
        """A clean two-brigade experiment on open ground."""
        s = new_game(seed=seed)
        a = s.living(AZURE)[0]
        c = s.living(CRIMSON)[0]
        # find a passable region with a passable neighbour, both empty
        for rid in range(len(s.regions)):
            if not s.map.passable(rid) or s.at(rid):
                continue
            nbs = [n for n in sorted(s.map.adj(rid))
                   if s.map.passable(n) and not s.at(n)]
            if nbs:
                return s, a, c, rid, nbs[0]
        self.fail("no clean ground on this map")

    def test_attacker_with_overwhelming_weight_wins(self):
        s, a, c, ground, approach = self._duel()
        place(s, c.id, ground, strength=2)
        place(s, a.id, approach, strength=12)
        s2, ev = resolve(s, [Order(a.id, ASSAULT, ground), Order(c.id, HOLD)])
        fight = [e for e in ev if e["t"] == "battle"]
        self.assertTrue(fight, "the two of them did not actually meet")
        self.assertEqual(fight[0]["winner"], AZURE)
        self.assertEqual(s2.brigade(a.id).region, ground)

    def test_a_hopeless_attack_is_annihilated(self):
        s, a, c, ground, approach = self._duel()
        place(s, c.id, ground, strength=12)
        place(s, a.id, approach, strength=2)
        s2, ev = resolve(s, [Order(a.id, ASSAULT, ground), Order(c.id, HOLD)])
        self.assertFalse(s2.brigade(a.id).alive)
        self.assertTrue(any(e["t"] == "broken" for e in ev))

    def test_a_weak_attack_is_repulsed(self):
        s, a, c, ground, approach = self._duel()
        place(s, c.id, ground, strength=12)
        place(s, a.id, approach, strength=8)
        s2, ev = resolve(s, [Order(a.id, ASSAULT, ground), Order(c.id, HOLD)])
        self.assertEqual(s2.brigade(a.id).region, approach,
                         "a beaten attacker must fall back where it started")
        self.assertTrue(any(e["t"] == "repulsed" for e in ev))

    def test_both_sides_take_losses(self):
        s, a, c, ground, approach = self._duel()
        place(s, c.id, ground, strength=8)
        place(s, a.id, approach, strength=12)
        s2, _ = resolve(s, [Order(a.id, ASSAULT, ground), Order(c.id, HOLD)])
        self.assertLess(s2.brigade(a.id).strength, 12)
        self.assertLess(s2.brigade(c.id).strength, 8)

    def test_concentration_is_worth_exactly_the_bonus(self):
        """Two brigades on the same ground must beat the same weight split
        across two rounds. This is the whole coordination mechanic."""
        s = new_game(seed=1)
        az = s.living(AZURE)
        c = s.living(CRIMSON)[0]
        ground = None
        for rid in range(len(s.regions)):
            if not s.map.passable(rid) or s.at(rid):
                continue
            nbs = [n for n in sorted(s.map.adj(rid))
                   if s.map.passable(n) and not s.at(n)]
            if len(nbs) >= 2:
                ground, one, two = rid, nbs[0], nbs[1]
                break
        self.assertIsNotNone(ground)

        place(s, c.id, ground, strength=6)
        place(s, az[0].id, one, strength=5)
        place(s, az[1].id, two, strength=5)
        _, ev = resolve(s, [Order(az[0].id, ASSAULT, ground),
                            Order(az[1].id, ASSAULT, ground),
                            Order(c.id, HOLD)])
        fight = [e for e in ev if e["t"] == "battle"][0]
        self.assertEqual(fight["concentration"], CONCENTRATION_BONUS)

        # the same two brigades, one of them idle: no bonus
        s2 = new_game(seed=1)
        place(s2, s2.living(CRIMSON)[0].id, ground, strength=6)
        place(s2, s2.living(AZURE)[0].id, one, strength=5)
        place(s2, s2.living(AZURE)[1].id, two, strength=5)
        _, ev2 = resolve(s2, [Order(s2.living(AZURE)[0].id, ASSAULT, ground),
                              Order(s2.living(AZURE)[1].id, HOLD),
                              Order(s2.living(CRIMSON)[0].id, HOLD)])
        fight2 = [e for e in ev2 if e["t"] == "battle"][0]
        self.assertEqual(fight2["concentration"], 0)
        self.assertGreater(fight["power"][AZURE], fight2["power"][AZURE])

    def test_entrenching_makes_a_defender_harder(self):
        s, a, c, ground, approach = self._duel()
        place(s, c.id, ground, strength=6)
        place(s, a.id, approach, strength=6)
        plain = resolve(s, [Order(a.id, ASSAULT, ground), Order(c.id, HOLD)])[1]
        plain_power = [e for e in plain if e["t"] == "battle"][0]["power"]

        s.brigade(c.id).entrenched = 3
        dug = resolve(s, [Order(a.id, ASSAULT, ground), Order(c.id, HOLD)])[1]
        dug_power = [e for e in dug if e["t"] == "battle"][0]["power"]
        self.assertGreater(dug_power[CRIMSON], plain_power[CRIMSON])

    def test_screen_turns_back_an_advance_but_not_an_assault(self):
        """You screen ground you stand beside, not ground you stand on."""
        s = new_game(seed=1)
        a = s.living(AZURE)[0]
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
        self.assertIsNotNone(ground)
        place(s, a.id, one)
        place(s, c.id, two)

        walked, ev = resolve(s, [Order(a.id, ADVANCE, ground),
                                 Order(c.id, SCREEN, ground)])
        self.assertTrue(any(e["t"] == "screened" for e in ev))
        self.assertEqual(walked.brigade(a.id).region, one,
                         "a screen must turn an advance back")

        forced, ev2 = resolve(s, [Order(a.id, ASSAULT, ground),
                                  Order(c.id, SCREEN, ground)])
        self.assertFalse(any(e["t"] == "screened" for e in ev2))
        self.assertEqual(forced.brigade(a.id).region, ground,
                         "a screen must not stop an assault")

    def test_reserve_lends_weight_to_a_neighbours_fight(self):
        s = new_game(seed=1)
        az = s.living(AZURE)
        c = s.living(CRIMSON)[0]
        ground = None
        for rid in range(len(s.regions)):
            if not s.map.passable(rid) or s.at(rid):
                continue
            nbs = [n for n in sorted(s.map.adj(rid))
                   if s.map.passable(n) and not s.at(n)]
            if len(nbs) >= 2:
                ground, one, two = rid, nbs[0], nbs[1]
                break

        # azure holds the ground, crimson attacks it, a second azure brigade
        # sits coiled next door
        place(s, az[0].id, ground, strength=6)
        place(s, az[1].id, one, strength=6)
        place(s, c.id, two, strength=10)
        alone, ev_alone = resolve(s, [Order(az[0].id, HOLD),
                                      Order(az[1].id, HOLD),
                                      Order(c.id, ASSAULT, ground)])
        coiled, ev_coiled = resolve(s, [Order(az[0].id, HOLD),
                                        Order(az[1].id, RESERVE),
                                        Order(c.id, ASSAULT, ground)])
        p_alone = [e for e in ev_alone if e["t"] == "battle"][0]["power"][AZURE]
        p_coiled = [e for e in ev_coiled if e["t"] == "battle"][0]["power"][AZURE]
        self.assertGreater(p_coiled, p_alone,
                           "a coiled brigade contributed nothing")


class TestFog(unittest.TestCase):

    def test_a_side_cannot_see_the_whole_map(self):
        s = new_game(seed=1)
        seen = visible(s, AZURE)
        self.assertLess(len(seen), len(s.regions),
                        "there is no fog at all")

    def test_you_always_see_your_own_ground(self):
        s = new_game(seed=1)
        seen = visible(s, AZURE)
        for b in s.living(AZURE):
            self.assertIn(b.region, seen)

    def test_view_hides_unseen_enemies(self):
        s = new_game(seed=1)
        v = view(s, AZURE)
        seen = set(v["visible"])
        for b in v["brigades"]:
            if not b.get("mine"):
                self.assertIn(b["region"], seen)

    def test_intel_remembers_what_the_light_has_left(self):
        s = new_game(seed=1)
        intel = Intel()
        intel.update(s, AZURE)
        remembered = set(intel.seen_round)
        for b in s.living(AZURE):          # march everyone home
            b.region = s.map.capitals[AZURE]
        still = visible(s, AZURE)
        self.assertTrue(remembered - still,
                        "nothing was remembered after the army moved on")


class TestMatch(unittest.TestCase):

    def test_every_match_ends(self):
        for seed in range(20):
            s = new_game(seed=seed)
            guard = 0
            while not s.over and guard < MAX_ROUNDS + 5:
                s, _ = resolve(s, bot.plan(s, AZURE) + bot.plan(s, CRIMSON))
                guard += 1
            self.assertTrue(s.over, "seed %d never finished" % seed)
            self.assertLessEqual(s.round, MAX_ROUNDS)
            self.assertTrue(s.verdict)

    def test_a_finished_match_stays_finished(self):
        s = new_game(seed=2)
        while not s.over:
            s, _ = resolve(s, bot.plan(s, AZURE) + bot.plan(s, CRIMSON))
        again, ev = resolve(s, [])
        self.assertEqual(again.digest(), s.digest())
        self.assertEqual(ev, [])

    def test_taking_the_enemy_capital_ends_it(self):
        s = new_game(seed=1)
        cap = s.map.capitals[CRIMSON]
        for b in s.living(CRIMSON):        # clear the defenders out
            b.alive = False
        a = s.living(AZURE)[0]
        approach = sorted(r for r in s.map.adj(cap) if s.map.passable(r))[0]
        place(s, a.id, approach, strength=12)
        s2, ev = resolve(s, [Order(a.id, ADVANCE, cap)])
        self.assertTrue(s2.over)
        self.assertEqual(s2.winner, AZURE)

    def test_brigades_never_stand_on_impassable_ground(self):
        s = new_game(seed=3)
        while not s.over:
            s, _ = resolve(s, bot.plan(s, AZURE) + bot.plan(s, CRIMSON))
            for b in s.living():
                self.assertTrue(s.map.passable(b.region),
                                "brigade %d is standing in a lake" % b.id)

    def test_strength_never_goes_negative(self):
        for seed in (1, 2, 3):
            s = new_game(seed=seed)
            while not s.over:
                s, _ = resolve(s, bot.plan(s, AZURE) + bot.plan(s, CRIMSON))
                for b in s.brigades:
                    self.assertGreaterEqual(b.strength, 0)


class TestSymmetry(unittest.TestCase):
    """The strongest claim the engine makes: on a mirror-symmetric map, two
    identical armies playing identical bots must stay a perfect reflection of
    each other for the whole campaign. Any drift is a rule that quietly
    favours a side number."""

    FLIP = {None: None, AZURE: CRIMSON, CRIMSON: AZURE}

    def _mirrored(self, s):
        m = s.map
        half = len(s.brigades) // 2
        for a in s.brigades[:half]:
            c = s.brigades[a.id + half]
            if (a.alive != c.alive or a.strength != c.strength
                    or m.mirror(a.region) != c.region):
                return "brigade %d and %d diverged" % (a.id, c.id)
        for r in s.regions:
            other = s.region(m.mirror(r.id))
            if self.FLIP[r.owner] != other.owner:
                return "region %d owner %s, mirror %d owner %s" % (
                    r.id, r.owner, other.id, other.owner)
            if self.FLIP[r.depot] != other.depot:
                return "region %d depot differs from its mirror" % r.id
            if r.works != other.works:
                return "region %d works differ from its mirror" % r.id
        return None

    def test_a_mirror_match_stays_mirrored(self):
        for seed in range(8):
            s = new_game(seed=seed)
            rnd = 0
            while not s.over:
                rnd += 1
                s, _ = resolve(s, bot.plan(s, AZURE) + bot.plan(s, CRIMSON))
                drift = self._mirrored(s)
                self.assertIsNone(
                    drift, "seed %d broke symmetry at round %d: %s"
                    % (seed, rnd, drift))

    def test_a_mirror_match_is_drawn(self):
        for seed in range(8):
            s = new_game(seed=seed)
            while not s.over:
                s, _ = resolve(s, bot.plan(s, AZURE) + bot.plan(s, CRIMSON))
            self.assertIsNone(s.winner,
                              "seed %d: a perfectly mirrored campaign was won "
                              "by side %s (%s)" % (seed, s.winner, s.verdict))


class TestBots(unittest.TestCase):

    def test_bots_only_ever_issue_legal_orders(self):
        s = new_game(seed=7)
        while not s.over:
            orders = bot.plan(s, AZURE) + bot.plan(s, CRIMSON)
            for o in orders:
                ok, why = validate(s, o)
                self.assertTrue(ok, "bot issued %r: %s" % (o, why))
            s, _ = resolve(s, orders)

    def test_bots_can_hold_a_subset_of_seats(self):
        s = new_game(seed=7)
        seats = {s.living(AZURE)[0].id, s.living(AZURE)[2].id}
        orders = bot.plan(s, AZURE, seats=seats)
        self.assertEqual({o.brigade for o in orders}, seats)

    def test_bots_plan_identically_from_identical_states(self):
        s = new_game(seed=8)
        a = [o.to_dict() for o in bot.plan(s, AZURE)]
        b = [o.to_dict() for o in bot.plan(s, AZURE)]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
