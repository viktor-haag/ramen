import random

from app.runner.spacing import StartSpacer


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def spacer(clock: Clock, value: float) -> StartSpacer:
    rng = random.Random()
    rng.uniform = lambda lo, hi: value  # deterministic gap
    return StartSpacer(rng=rng, clock=clock)


def test_first_start_is_immediate_then_spaced():
    clock = Clock()
    s = spacer(clock, 4.0)
    assert s.delay("a", (2.0, 6.0)) == 0.0
    assert s.delay("a", (2.0, 6.0)) == 4.0
    assert s.delay("a", (2.0, 6.0)) == 8.0


def test_sources_are_independent():
    clock = Clock()
    s = spacer(clock, 4.0)
    s.delay("a", (2.0, 6.0))
    assert s.delay("b", (2.0, 6.0)) == 0.0


def test_gap_counts_from_previous_start_not_from_now():
    clock = Clock()
    s = spacer(clock, 4.0)
    s.delay("a", (2.0, 6.0))
    clock.now += 3.0
    assert s.delay("a", (2.0, 6.0)) == 1.0
    clock.now += 60.0
    assert s.delay("a", (2.0, 6.0)) == 0.0


def test_zero_gap_and_invalid_ranges():
    clock = Clock()
    s = StartSpacer(clock=clock)
    assert [s.delay("z", (0.0, 0.0)) for _ in range(3)] == [0.0, 0.0, 0.0]
    s2 = StartSpacer(clock=clock)
    s2.delay("n", (-5.0, -1.0))  # negative bounds clamp to 0
    assert s2.delay("n", (-5.0, -1.0)) == 0.0


def test_real_rng_stays_within_bounds():
    clock = Clock()
    s = StartSpacer(clock=clock)
    s.delay("a", (2.0, 6.0))
    gaps = []
    prev = 0.0
    for _ in range(50):
        d = s.delay("a", (2.0, 6.0))
        gaps.append(d - prev)
        prev = d
    assert all(2.0 <= g <= 6.0 for g in gaps)


def test_plugin_info_carries_spacing():
    from pathlib import Path

    from app.plugins.loader import discover_plugins

    infos = discover_plugins([Path(__file__).parent / "fake_plugins"])
    assert infos["crash"].start_spacing == (2.0, 6.0)  # Extractor default
    assert infos["good"].start_spacing == (0.0, 0.0)  # class override
