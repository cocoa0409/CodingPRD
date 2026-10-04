"""Skill decay: the grace-window day count and the due-date interval."""
from test_helpers import (
    append_lesson_node, create_course_unit, fire_event, practice_ok, read_node,
    register_learner, set_clock,
)


def _bronze_node_reviewed_on_september_first():
    """Ada holds a BRONZE node whose last review is 2026-09-01T00:00:00Z.

    Returns ``(learner, unit, node, dependent)``; ``node`` is the crowned node
    the decay sweep will evaluate, and ``dependent`` is the still-UNLOCKED node
    chained behind it.
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    unit = create_course_unit(total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    second = append_lesson_node(unit["id"], 2, root["id"])
    practice_ok(root["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)
    return learner, unit, root, second


def test_decay_sweep_expires_review_due_date_after_one_day_for_bronze_node(api):
    """PRD §3.2: "the node's next due date is derived from its crown state — an
    untouched or bronze node is due after one day, a silver node after two, a gold
    node after three, and a legendary node after five"
    PRD §3.2: "When a node's `decay_meter` has reached the five-point ceiling and
    the clock is at or past its `review_due_at`, the node is demoted to `DECAYED`"

    Design: Difficulty/combinatorial_formula/skill_decay_review_interval_nested_rounding
    """
    learner, _unit, node, _dependent = _bronze_node_reviewed_on_september_first()
    before = read_node(node["id"], learner["id"])
    assert before["state"] == "BRONZE"
    assert before["review_due_at"].startswith("2026-09-02T00:00:00"), (
        "a bronze node is due one day after its review, anchored on the attempt's "
        f"recorded_at, got {before['review_due_at']}"
    )

    # The clock has passed both the one-day due date and the ten-day ceiling, so
    # the sweep demotes the node.
    set_clock("2026-09-11T00:00:00Z")
    fire_event("SKILL_DECAY")
    after = read_node(node["id"], learner["id"])

    assert after["state"] == "DECAYED", (
        "the BRONZE node's due date is one day after its review and its meter "
        f"reaches the ceiling at the same sweep, got {after['state']}"
    )
    assert after["decay_meter"] == 0, (
        f"a demotion resets the meter to zero, got {after['decay_meter']}"
    )
    assert after["decay_level"] == 1, (
        f"a demotion increments decay_level by one, got {after['decay_level']}"
    )


def test_decay_meter_accrues_one_point_per_two_complete_days(api):
    """PRD §3.2: "the node accrues one decay point for every two complete days
    since that review, and the meter is capped at five points"
    PRD §3.2: "When a node's `decay_meter` has reached the five-point ceiling and
    the clock is at or past its `review_due_at`, the node is demoted to `DECAYED`"

    Design: Difficulty/combinatorial_formula/skill_decay_review_interval_nested_rounding
    """
    learner, _unit, node, _dependent = _bronze_node_reviewed_on_september_first()
    before = read_node(node["id"], learner["id"])
    assert before["state"] == "BRONZE"
    assert before["last_reviewed_at"].startswith("2026-09-01T00:00:00")

    # Nine complete days since the review earn four points at one point per two
    # days, one short of the five-point ceiling.
    set_clock("2026-09-10T00:00:00Z")
    fire_event("SKILL_DECAY")

    refreshed = read_node(node["id"], learner["id"])
    assert refreshed["decay_meter"] == 4, (
        "nine complete days since the review earn four decay points, one short of "
        f"the five-point ceiling, got {refreshed['decay_meter']}"
    )
    assert refreshed["state"] == "BRONZE", (
        "the meter sits one point below the five-point ceiling, so the node has "
        f"not been demoted, got {refreshed['state']}"
    )

    # The tenth day adds the fifth point, which reaches the ceiling at the same
    # time as the node's due date.
    set_clock("2026-09-11T00:00:00Z")
    fire_event("SKILL_DECAY")
    demoted = read_node(node["id"], learner["id"])

    assert demoted["decay_meter"] == 0, (
        f"a demotion resets the meter to zero, got {demoted['decay_meter']}"
    )
    assert demoted["state"] == "DECAYED", (
        "ten complete days add the fifth point, which reaches the ceiling at the "
        f"same time as the node's due date, got {demoted['state']}"
    )
    assert demoted["decay_level"] == 1, (
        f"a demotion increments decay_level by one, got {demoted['decay_level']}"
    )