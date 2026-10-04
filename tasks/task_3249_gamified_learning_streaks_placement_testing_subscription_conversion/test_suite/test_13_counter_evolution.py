"""Counter evolution after practice: derived counters and read consistency."""
from test_helpers import (
    api_client, append_lesson_node, create_course_unit, get_success_data,
    make_learner_headers, practice, practice_ok, read_node, register_learner,
)


def test_failure_allowance_drops_with_each_incorrect_attempt(api):
    """PRD §3.4: "the server counts the attempts inside the current local day
    window — from the `focus_date` to 86400 seconds later — that are incorrect, are
    not placement items, and belong to that learner."
    PRD §3.4: "The available allowance is the daily grant of five hearts minus that
    count, floored at zero."

    Design: Corner/calculations/heart_allowance_recomputes_after_failed_attempts
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    headers = make_learner_headers(learner["id"])
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)

    get_success_data(practice(
        node["id"],
        {"learner_id": learner["id"], "recorded_at": "2026-09-01T01:00:00Z",
         "response_ms": 9000, "correct": False},
        headers,
    ))
    assert get_success_data(api_client.get_learner(
        learner["id"], headers
    ))["hearts_available"] == 4

    practice_ok(node["id"], learner["id"], "2026-09-01T02:00:00Z",
                response_ms=5000, correct=True)
    assert get_success_data(api_client.get_learner(
        learner["id"], headers
    ))["hearts_available"] == 4, (
        "a correctly answered attempt does not consume a heart"
    )

    get_success_data(practice(
        node["id"],
        {"learner_id": learner["id"], "recorded_at": "2026-09-01T03:00:00Z",
         "response_ms": 9000, "correct": False},
        headers,
    ))
    assert get_success_data(api_client.get_learner(
        learner["id"], headers
    ))["hearts_available"] == 3, (
        "two incorrect attempts inside the local day cost exactly two hearts"
    )


def test_energy_is_spent_only_by_accepted_attempts(api):
    """PRD §3.4: "One unit is spent only when an attempt is actually accepted, and
    spending resets `energy_anchor_at` to the current clock, which restarts the
    accrual interval."
    PRD §3.4: "A learner starts with ten units"
    PRD §3.4: "The available allowance is the daily grant of five hearts minus that
    count, floored at zero."

    Design: Corner/calculations/heart_allowance_recomputes_after_failed_attempts
    """
    from test_helpers import set_clock

    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    headers = make_learner_headers(learner["id"])
    unit = create_course_unit(total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    second = append_lesson_node(unit["id"], 2, root["id"])

    practice_ok(root["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)
    assert get_success_data(api_client.get_learner(
        learner["id"], headers
    ))["energy_units"] == 9, (
        "the accepted attempt spends exactly one of the ten starting units"
    )

    # One complete 900-second interval credits five units on top of the stored
    # nine, so the regenerated figure reads fourteen.
    set_clock("2026-09-01T00:15:00Z")
    assert get_success_data(api_client.get_learner(
        learner["id"], headers
    ))["energy_units"] == 14, (
        "a complete interval credits the five-unit regen step on top of the "
        "stored nine"
    )

    practice_ok(second["id"], learner["id"], "2026-09-01T00:15:00Z",
                response_ms=5000, correct=True)
    assert get_success_data(api_client.get_learner(
        learner["id"], headers
    ))["energy_units"] == 13, (
        "the second accepted attempt spends one of the fourteen and resets the "
        "anchor to 00:15:00"
    )

    # Fourteen minutes and fifty-nine seconds after the reset anchor no further
    # interval has completed, so the pool is unchanged: the accrual is quantised.
    set_clock("2026-09-01T00:29:59Z")
    assert get_success_data(api_client.get_learner(
        learner["id"], headers
    ))["energy_units"] == 13, (
        "899 seconds past the reset anchor credits no complete interval, so the "
        "pool stays at thirteen"
    )


def test_attempt_raises_the_node_one_rung_and_schedules_its_review(api):
    """PRD §3.1: "Each accepted, correct attempt lifts the node one rung of the
    crown ladder: `UNLOCKED → BRONZE`, then `BRONZE → SILVER`, then
    `SILVER → GOLD`."
    PRD §3.1: "Every promotion refreshes `last_reviewed_at` to the attempt's
    `recorded_at`, rebases `review_due_at` by that state's review interval"
    PRD §3.2: "an untouched or bronze node is due after one day"

    Design: Corner/endpoints/practice_side_effects_credit_xp_and_set_review_schedule
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)

    attempt = practice_ok(node["id"], learner["id"], "2026-09-01T00:00:00Z",
                          response_ms=5000, correct=True)
    assert attempt["xp_awarded"] == 11, (
        "an UNLOCKED node pays a base of ten, a 5000-millisecond answer adds the "
        "one-point speed bonus, and a fresh streak holds multiplier 1.00, so "
        "(10 + 1) * 1.00 == 11"
    )

    refreshed = read_node(node["id"], learner["id"])
    assert refreshed["state"] == "BRONZE"
    assert refreshed["review_due_at"].startswith("2026-09-02T00:00:00"), (
        "a bronze node's review interval is one day, anchored on the attempt's "
        f"recorded_at, got {refreshed['review_due_at']}"
    )


def test_accepted_attempt_xp_is_visible_on_the_next_read(api):
    """PRD §3.4: "The learner's `xp_total` is recomputed from these awards, and the
    award is recorded on the attempt as `xp_awarded`."
    PRD §2.6: "These cascades are applied within the same logical operation as the
    trigger"

    Design: Corner/consistency_model/immediate_consistency_of_xp_after_accepted_attempt
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    headers = make_learner_headers(learner["id"])
    unit = create_course_unit(total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    second = append_lesson_node(unit["id"], 2, root["id"])

    practice_ok(root["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)
    after_one = get_success_data(api_client.get_learner(learner["id"], headers))
    assert after_one["xp_total"] == 11, (
        f"the award is visible without a reconciliation pass, got "
        f"{after_one['xp_total']}"
    )

    practice_ok(second["id"], learner["id"], "2026-09-01T01:00:00Z",
                response_ms=5000, correct=True)
    after_two = get_success_data(api_client.get_learner(learner["id"], headers))
    assert after_two["xp_total"] == 22, (
        f"the second accepted attempt lifts the total to 22, got "
        f"{after_two['xp_total']}"
    )


def test_leaf_count_tracks_the_crown_state_of_the_learners_nodes(api):
    """PRD §2.6: "a `Learner`'s `leaf_count` is derived from the crown states of the
    nodes that learner holds"
    PRD §3.1: "Every promotion refreshes `last_reviewed_at` to the attempt's
    `recorded_at`, rebases `review_due_at` by that state's review interval, resets
    `decay_meter` to zero, and causes `learner.leaf_count` to be recomputed."

    Design: Corner/cross_cutting_layers/derived_leaf_count_reconciles_after_crown_advance
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    headers = make_learner_headers(learner["id"])
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)

    before = get_success_data(api_client.get_learner(learner["id"], headers))
    assert before["leaf_count"] == 0

    practice_ok(node["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)
    after = get_success_data(api_client.get_learner(learner["id"], headers))

    assert after["leaf_count"] == 1, (
        "the node reached BRONZE, so the denormalized counter tracks it, got "
        f"{after['leaf_count']}"
    )