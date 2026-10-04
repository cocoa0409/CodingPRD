"""Experience-award calculations: the tier split and the streak multiplier ladder."""
from test_helpers import (
    append_lesson_node, create_course_unit, fire_event, practice_ok,
    register_learner, set_clock, subscribe,
)


def _unit_with_two_nodes(band="A1"):
    unit = create_course_unit(cefr_band=band, total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    second = append_lesson_node(unit["id"], 2, root["id"])
    return unit, root, second


def _qualify_two_days(node_id, learner_id, recorded_at="2026-09-01T00:00:00Z"):
    """Book one accepted attempt on each of two consecutive local days so
    ``current_length`` stands at 2 before the measured attempt, then roll the
    local day forward once more.  PRD §3.4's worked example prices a node lifted
    out of `UNLOCKED` on a 2-day streak, so the streak must already sit at two
    when the measured attempt is booked."""
    practice_ok(node_id, learner_id, recorded_at, response_ms=5000, correct=True)
    set_clock("2026-09-02T00:00:00Z")
    fire_event("STREAK_DAY_CLOSE")
    practice_ok(node_id, learner_id, "2026-09-02T01:00:00Z", response_ms=5000,
                correct=True)
    set_clock("2026-09-03T00:00:00Z")
    fire_event("STREAK_DAY_CLOSE")


def test_practice_xp_uses_standard_multiplier_for_paid_learner(api):
    """PRD §3.4: "The sum is then scaled by the learner's streak multiplier, read
    from `current_length` as it stood before this attempt was applied: 1.50 when
    the streak is at least 100 days, 1.25 when it is at least 10, 1.10 when it is
    at least 2, and 1.00 below that."
    PRD §3.4: "a node lifted out of `UNLOCKED` on a 2-day streak with a
    2500-millisecond answer awards 14 experience points to a paying learner"

    Design: Difficulty/dual_variant_calc/xp_award_streak_multiplier_tier_split
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    subscribe(learner["id"], "PLUS_FAMILY", seats_total=4, auto_renew=True)

    _unit, root, second = _unit_with_two_nodes()
    _qualify_two_days(root["id"], learner["id"])

    attempt = practice_ok(second["id"], learner["id"], "2026-09-03T09:00:00Z",
                          response_ms=2500, correct=True)

    assert attempt["xp_awarded"] == 14, (
        f"(10 + 3) * 1.10 rounds half up to 14 for a paying learner on a 2-day "
        f"streak, got {attempt['xp_awarded']}"
    )
    assert attempt["outcome"] == "ACCEPTED"


def test_practice_xp_keeps_neutral_multiplier_for_free_learner(api):
    """PRD §3.4: "Free learners are capped at the neutral 1.00 multiplier no
    matter how long their streak, so a node lifted out of `UNLOCKED` on a 2-day
    streak with a 2500-millisecond answer awards 14 experience points to a paying
    learner but 13 to a free one."

    Design: Difficulty/dual_variant_calc/xp_award_streak_multiplier_tier_split
    """
    paid = register_learner(display_name="Ada", local_date_offset_days=0,
                            program_tier="FREE")
    subscribe(paid["id"], "PLUS_FAMILY", seats_total=4, auto_renew=True)
    free = register_learner(display_name="Bea", local_date_offset_days=0,
                            program_tier="FREE")

    _pu, paid_root, paid_second = _unit_with_two_nodes()
    _fu, free_root, free_second = _unit_with_two_nodes()

    _qualify_two_days(paid_root["id"], paid["id"])
    _qualify_two_days(free_root["id"], free["id"])

    paid_attempt = practice_ok(paid_second["id"], paid["id"],
                               "2026-09-03T09:00:00Z", response_ms=2500,
                               correct=True)
    free_attempt = practice_ok(free_second["id"], free["id"],
                               "2026-09-03T09:00:00Z", response_ms=2500,
                               correct=True)

    assert paid_attempt["xp_awarded"] == 14
    assert free_attempt["xp_awarded"] == 13, (
        "a FREE learner is capped at the neutral 1.00 multiplier, so "
        f"(10 + 3) * 1.00 == 13, got {free_attempt['xp_awarded']}"
    )


def test_practice_xp_multiplier_steps_with_streak_length(api):
    """PRD §3.4: "The sum is then scaled by the learner's streak multiplier, read
    from `current_length` as it stood before this attempt was applied: 1.50 when
    the streak is at least 100 days, 1.25 when it is at least 10, 1.10 when it is
    at least 2, and 1.00 below that. The product is rounded half up to a whole
    number of experience points."

    Design: Difficulty/dual_variant_calc/xp_award_streak_multiplier_tier_split
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    subscribe(learner["id"], "PLUS_FAMILY", seats_total=4, auto_renew=True)

    _unit, root, second = _unit_with_two_nodes()

    # Streak 0: multiplier 1.00.
    first = practice_ok(root["id"], learner["id"], "2026-09-01T00:00:00Z",
                        response_ms=2500, correct=True)
    assert first["xp_awarded"] == 13, (
        f"a fresh streak holds multiplier 1.00, so (10 + 3) * 1.00 == 13, "
        f"got {first['xp_awarded']}"
    )

    # Streak 1 -> 2: the extension is applied, so the next attempt reads 1.10.
    set_clock("2026-09-02T00:00:00Z")
    fire_event("STREAK_DAY_CLOSE")
    practice_ok(root["id"], learner["id"], "2026-09-02T09:00:00Z",
                response_ms=5000, correct=True)

    third = practice_ok(second["id"], learner["id"], "2026-09-02T10:00:00Z",
                        response_ms=2500, correct=True)
    assert third["xp_awarded"] == 14, (
        f"(10 + 3) * 1.10 rounds half up to 14 once the streak stands at two "
        f"days, got {third['xp_awarded']}"
    )
    assert third["outcome"] == "ACCEPTED"