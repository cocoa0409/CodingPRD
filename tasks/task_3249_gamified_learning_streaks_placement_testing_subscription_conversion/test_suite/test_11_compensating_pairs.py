"""Compensating pairs: the named quantity returns to its pre-call value."""
from test_helpers import (
    add_seat_ok, api_client, append_lesson_node, create_course_unit, fire_event,
    get_learner, get_success_data, make_learner_headers, practice_ok, read_node,
    register_learner, remove_seat, review, set_clock,
)


def test_decay_and_review_leave_the_learners_lifetime_xp_untouched(api):
    """PRD §3.4: "The learner's `xp_total` is recomputed from these awards, and the
    award is recorded on the attempt as `xp_awarded`."
    PRD §3.2: "A node whose `decay_level` is still below the retention floor is
    restored `DECAYED → UNLOCKED`"

    Design: Difficulty/compensating_invariant/decay_and_review_conserve_learner_xp_total
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    unit = create_course_unit(cefr_band="B1", total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    append_lesson_node(unit["id"], 2, root["id"])

    attempt = practice_ok(root["id"], learner["id"], "2026-09-01T00:00:00Z",
                          response_ms=5000, correct=True)
    assert attempt["xp_awarded"] == 11, (
        f"(10 + 1) * 1.00 rounds to 11 on a fresh streak, got "
        f"{attempt['xp_awarded']}"
    )
    after_practice = get_learner(learner["id"])
    assert after_practice["xp_total"] == 11

    set_clock("2026-09-11T00:00:00Z")
    fire_event("SKILL_DECAY")
    decayed = read_node(root["id"], learner["id"])
    assert decayed["state"] == "DECAYED"

    restored = get_success_data(review(root["id"], learner["id"],
                                       decayed["version"]))
    assert restored["state"] == "UNLOCKED"

    after_review = get_learner(learner["id"])
    assert after_review["xp_total"] == 11, (
        "the compensating review neither refunds nor double-counts a point, got "
        f"{after_review['xp_total']}"
    )


def test_decay_and_review_return_leaf_count_to_its_pre_practice_value(api):
    """PRD §3.2: "`decay_level` increments by one, `decay_meter` resets to zero, and
    `leaf_count` is recomputed for the owning learner."
    PRD §3.1: "Every promotion refreshes `last_reviewed_at` to the attempt's
    `recorded_at`, rebases `review_due_at` by that state's review interval, resets
    `decay_meter` to zero, and causes `learner.leaf_count` to be recomputed."

    Design: Difficulty/compensating_invariant/decay_and_review_conserve_learner_xp_total
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    unit = create_course_unit(cefr_band="B1", total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    append_lesson_node(unit["id"], 2, root["id"])

    assert get_learner(learner["id"])["leaf_count"] == 0

    practice_ok(root["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)
    assert get_learner(learner["id"])["leaf_count"] == 1, (
        "the node now carries a crown, so it counts as a leaf"
    )

    set_clock("2026-09-11T00:00:00Z")
    fire_event("SKILL_DECAY")
    decayed = read_node(root["id"], learner["id"])
    assert get_learner(learner["id"])["leaf_count"] == 0, (
        "a demoted node loses its crown and stops counting as a leaf"
    )

    get_success_data(review(root["id"], learner["id"], decayed["version"]))
    assert get_learner(learner["id"])["leaf_count"] == 0, (
        "the review returns the node to UNLOCKED, the pre-practice value"
    )


def test_add_then_remove_seat_restores_the_seat_count_and_the_member_budget(api):
    """PRD §3.5: "supplying `remove_seat_learner_id` moves the matching seat
    `INVITED → REMOVED` or `ACTIVE → REMOVED` and decrements `seats_used`"
    PRD §3.5: "Every form of the write recomputes `limits_removed`, the learner's
    own `hearts_available` and `energy_units`, and the same two counters for each
    member whose seat changed."

    Design: Difficulty/compensating_invariant/seat_add_and_remove_conserve_subscription_seats_used
    """
    owner = register_learner(display_name="Ada", local_date_offset_days=0,
                             program_tier="FREE")
    member = register_learner(display_name="Bea", local_date_offset_days=0,
                              program_tier="FREE")
    subscription = get_success_data(api_client.create_subscription(
        {"learner_id": owner["id"], "plan_code": "PLUS_FAMILY",
         "seats_total": 3, "auto_renew": True},
        make_learner_headers(owner["id"]),
    ))
    assert subscription["seats_used"] == 0

    seated = add_seat_ok(subscription["id"], owner["id"], member["id"],
                         subscription["version"])
    assert seated["seats_used"] == 1, (
        f"the add raises the count to one, got {seated['seats_used']}"
    )

    removed = get_success_data(remove_seat(
        subscription["id"], owner["id"], member["id"], seated["version"]
    ))
    assert removed["seats_used"] == 0, (
        "the paired removal returns the quota quantity to its pre-add value, got "
        f"{removed['seats_used']}"
    )


def test_seat_removal_marks_the_seat_removed_and_restores_the_member_allowance(api):
    """PRD §3.5: "At any point an `ACTIVE` seat can be revoked — by the subscription
    lapsing into `FREE` or `EXPIRED` or by an operator revoking it — which moves
    it `ACTIVE → REMOVED`, decrements `seats_used`, recomputes the
    member's budgets, and re-prices the member's outstanding offers."
    PRD §3.4: "The available allowance is the daily grant of five hearts minus
    that count, floored at zero."

    Design: Difficulty/compensating_invariant/seat_add_and_remove_conserve_subscription_seats_used
    """
    owner = register_learner(display_name="Ada", local_date_offset_days=0,
                             program_tier="FREE")
    member = register_learner(display_name="Bea", local_date_offset_days=0,
                              program_tier="FREE")
    subscription = get_success_data(api_client.create_subscription(
        {"learner_id": owner["id"], "plan_code": "PLUS_FAMILY",
         "seats_total": 3, "auto_renew": True},
        make_learner_headers(owner["id"]),
    ))
    seated = add_seat_ok(subscription["id"], owner["id"], member["id"],
                         subscription["version"])

    seats = get_success_data(api_client.list_subscription_memberships(
        subscription["id"], make_learner_headers(owner["id"])
    ))
    seat = [s for s in seats if s["member_learner_id"] == member["id"]][0]
    assert seat["status"] == "ACTIVE"

    remove_seat(subscription["id"], owner["id"], member["id"], seated["version"])

    refreshed = get_success_data(api_client.list_subscription_memberships(
        subscription["id"], make_learner_headers(owner["id"])
    ))
    target = [s for s in refreshed if s["id"] == seat["id"]][0]
    assert target["status"] == "REMOVED", (
        f"the revoked seat moves ACTIVE -> REMOVED, got {target['status']}"
    )
    assert get_learner(member["id"])["hearts_available"] == 5, (
        "the member's budget is recomputed back to the gated allowance"
    )