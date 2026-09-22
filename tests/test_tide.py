#!/usr/bin/env python3
"""
Runs the browser game's rule tests.

TIDE has no Python in it -- the rules live in web/tide.js so the browser can
use them directly -- but the arithmetic still has to be proved, so the real
tests are in tests/tide.test.js and this hands them to node. That keeps one
command for the whole project.
"""
import os
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE = os.path.join(HERE, "tide.test.js")


class TestTideRules(unittest.TestCase):

    def test_the_rules_hold_up(self):
        try:
            out = subprocess.run(["node", SUITE], capture_output=True,
                                 text=True, timeout=120)
        except FileNotFoundError:
            self.skipTest("node is not installed; run tests/tide.test.js by hand")
        self.assertEqual(out.returncode, 0,
                         "\n" + out.stdout + out.stderr)
        self.assertIn("0 failed", out.stdout)
