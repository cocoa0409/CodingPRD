"""Repair pricing: the tiered schedule and its whole-gem precision."""
from test_helpers import scene_broken_streak_with_length


def _break_a_seventeen_day_streak():
    """A learner whose streak stood at 17 qualified days before it broke."""
    return scene_broken_streak_with_length(length=17, gems=40)


def test_repair_price_of_a_seventeen_day_streak_is_whole_gems(api):
    """PRD §3.3: "The ladder position is derived from the length at break: divide it
    by thirty, truncate toward zero, and cap the index at four. The five rates
    indexed that way are 1, 2, 4, 6 and 8 gems."
    PRD §3.3: "A bonus then accrues on the remainder within the band — the length at
    break taken modulo thirty, multiplied by a per-day rate of 0.05 gems and rounded
    half up."
    PRD §2.9: "All counters in this system are integers and are never stored
    fractionally."

    Design: Corner/calculations/repair_price_precision_uses_whole_gems
    """
    scene = _break_a_seventeen_day_streak()
    streak = scene["streak"]

    assert streak["status"] == "BROKEN"
    assert streak["repair_cost_gems"] == 2, (
        "a seventeen-day break sits in the first band (rate 1, remainder 17 at "
        "0.05 gems per day rounded half up to 1), so the price is 2 whole gems, "
        f"got {streak['repair_cost_gems']}"
    )
    assert isinstance(streak["repair_cost_gems"], int)


def test_repair_price_segments_on_the_streak_length_at_break(api):
    """PRD §3.3: "The ladder position is derived from the length at break: divide it
    by thirty, truncate toward zero, and cap the index at four."
    PRD §3.3: "Lifetime streak days never enter the price — only the length at the
    moment of the break."

    Design: Corner/calculations/repair_price_precision_uses_whole_gems
    """
    short = scene_broken_streak_with_length(length=2, gems=40)
    long_break = scene_broken_streak_with_length(length=31, gems=60)

    assert short["streak"]["repair_cost_gems"] == 1, (
        "a two-day break takes the first rate of 1 gem with a length bonus of "
        f"round_half_up(2 * 0.05) == 0, got "
        f"{short['streak']['repair_cost_gems']}"
    )
    assert long_break["streak"]["repair_cost_gems"] == 2, (
        "a thirty-one-day break divides by thirty to ladder index 1, so its tier "
        "rate is 2 gems and the remainder of 1 day at 0.05 rounds to 0, giving a "
        f"price of 2 whole gems, got "
        f"{long_break['streak']['repair_cost_gems']}"
    )