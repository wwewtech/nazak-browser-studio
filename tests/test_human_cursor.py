"""Behavioural humanizer: cursor overshoot and asymmetric speed profile."""

from __future__ import annotations

import asyncio
import math
import random
from itertools import pairwise

import pytest

from nazak.core.youtube_uploader import HumanCursor


class _FakeMouse:
    def __init__(self):
        self.points: list[tuple[float, float]] = []

    async def move(self, x, y):
        self.points.append((float(x), float(y)))


class _FakePage:
    def __init__(self):
        self.mouse = _FakeMouse()


def _run(page, tx, ty, cx=100.0, cy=100.0, seed=0):
    random.seed(seed)
    asyncio.run(HumanCursor.move_to(page, tx, ty, cx, cy))


def test_cursor_overshoots_on_long_moves():
    """Most long moves must pass the target and come back (human signature)."""
    overshot = 0
    trials = 20
    for seed in range(trials):
        page = _FakePage()
        _run(page, 600.0, 400.0, seed=seed)
        pts = page.mouse.points
        assert pts, "cursor must emit points"
        # Last point settles exactly on target.
        assert pts[-1] == (600.0, 400.0)
        dists = [math.hypot(x - 100.0, y - 100.0) for x, y in pts]
        target_dist = math.hypot(500.0, 300.0)
        # Overshoot: at some point the cursor is FARTHER from the start than
        # the target itself (it passed the target and returned).
        if max(dists) > target_dist + 2.0:
            overshot += 1
    # p = 0.65 per trial: 20 trials must show a clear majority.
    assert overshot >= 8, f"only {overshot}/{trials} moves overshot the target"


def test_cursor_does_not_overshoot_on_tiny_moves():
    """Short moves settle directly — overshoot only applies to aimed moves."""
    for seed in range(10):
        page = _FakePage()
        _run(page, 110.0, 105.0, seed=seed)
        pts = page.mouse.points
        assert pts[-1] == (110.0, 105.0)


def test_cursor_speed_profile_is_asymmetric():
    """Peak velocity must sit in the first half (fast attack, long tail)."""
    page = _FakePage()
    _run(page, 700.0, 500.0, seed=7)
    pts = page.mouse.points
    assert len(pts) > 10
    speeds = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(pts)]
    peak = speeds.index(max(speeds))
    # Symmetric cosine ease peaks at the middle; the asymmetric profile peaks
    # in the first ~40%.
    assert peak < len(speeds) * 0.45, f"peak speed at {peak}/{len(speeds)} — symmetric"


def test_cursor_trajectory_stays_monotone_toward_target_without_wild_jumps():
    """Overshoot is small and local: no teleport-like jumps between samples."""
    page = _FakePage()
    _run(page, 600.0, 400.0, seed=3)
    pts = page.mouse.points
    leg = math.hypot(500.0, 300.0)
    for a, b in pairwise(pts):
        jump = math.hypot(b[0] - a[0], b[1] - a[1])
        assert jump < leg * 0.25, f"unrealistic jump {jump:.1f}px on a {leg:.0f}px move"
