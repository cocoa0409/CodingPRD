"""Boundary precision: the exact points at which a limit admits or refuses."""
from test_helpers import (
    add_seat_ok, api_client, append_lesson_node, create_course_unit, get_learner,
    get_success_data, make_learner_headers, practice, register_learner, subscribe,
    validate_error,
)


def test_fifth_daily_attempt_is_admitted_and_the_sixth_is_refused(api):
    """PRD §3.4: "The available allowance is the daily grant of five hearts minus
    that count, floored at zero."
    PRD §3.4: "A non-placement attempt with no hearts left is refused with
    `ERR_HEARTS_EXHAUSTED` at HTTP 409"
    PRD §2.9: "Threshold comparisons expressed as "at least" or "at or below"
    include the boundary value itself."

    Design: Difficulty/boundary_precision_check/free_heart_allowance_exact_boundary
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    headers = make_learner_headers(learner["id"])
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)

    for hour in range(1, 5):
        practice_ok = practice(
            node["id"],
            {"learner_id": learner["id"],
             "recorded_at": f"2026-09-01T{hour:02d}:00:00Z",
             "response_ms": 9000, "correct": False},
            headers,
        )
        assert practice_ok.status_code == 201, practice_ok.text

    # The fifth incorrect attempt is admitted: four banked failures leave
    # hearts_available at exactly 1, which the inclusive boundary admits.
    fifth = get_success_data(practice(
        node["id"],
        {"learner_id": learner["id"], "recorded_at": "2026-09-01T05:00:00Z",
         "response_ms": 9000, "correct": False},
        headers,
    ))
    assert fifth["outcome"] == "ACCEPTED", (
        "four banked failures leave hearts_available at exactly 1, which the "
        f"inclusive boundary admits, got {fifth['outcome']}"
    )

    # The sixth finds the allowance fully spent and is refused.
    sixth = practice(
        node["id"],
        {"learner_id": learner["id"], "recorded_at": "2026-09-01T06:00:00Z",
         "response_ms": 9000, "correct": False},
        headers,
    )
    validate_error(sixth, "ERR_HEARTS_EXHAUSTED")

    assert get_learner(learner["id"])["hearts_available"] == 0, (
        "the daily grant of five hearts is fully spent, so the allowance floors "
        "at zero"
    )


def test_failure_allowance_refreshes_on_a_local_day_boundary(api):
    """PRD §3.4: "For a learner on a gated tier, the server counts the attempts
    inside the current local day window — from the `focus_date` to 86400 seconds
    later — that are incorrect, are not placement items, and belong to that
    learner."
    PRD §3.4: "The day window used here is the learner's local focus day derived in
    §3.3, so hearts refresh at local midnight rather than at UTC midnight."

    Design: Difficulty/boundary_precision_check/free_heart_allowance_exact_boundary
    """
    from test_helpers import fire_event, set_clock

    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    headers = make_learner_headers(learner["id"])
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)

    for hour in range(1, 3):
        practice(node["id"],
                 {"learner_id": learner["id"],
                  "recorded_at": f"2026-09-01T{hour:02d}:00:00Z",
                  "response_ms": 9000, "correct": False},
                 headers)
    assert get_learner(learner["id"])["hearts_available"] == 3

    set_clock("2026-09-02T00:00:00Z")
    fire_event("STREAK_DAY_CLOSE")

    assert get_learner(learner["id"])["hearts_available"] == 5, (
        "the previous day's failures fall outside the new local focus day, so "
        "the allowance refreshes to the full grant"
    )


def test_seat_quota_rejects_at_equality(api):
    """PRD §3.5: "adding one when `seats_used` has already reached `seats_total` is
    refused with `ERR_SEAT_QUOTA_EXCEEDED` at HTTP 409"
    PRD §3.5: "only when the subscription is `ACTIVE`, its `seats_used` is still
    below its `seats_total`"

    Design: Difficulty/boundary_precision_check/family_seat_quota_exact_boundary
    """
    owner = register_learner(display_name="Ada", local_date_offset_days=0,
                             program_tier="FREE")
    member = register_learner(display_name="Bea", local_date_offset_days=0,
                              program_tier="FREE")
    other = register_learner(display_name="Cal", local_date_offset_days=0,
                             program_tier="FREE")

    subscription = subscribe(owner["id"], "PLUS_FAMILY", seats_total=1,
                             auto_renew=True)
    seated = add_seat_ok(subscription["id"], owner["id"], member["id"],
                         subscription["version"])
    assert seated["seats_used"] == 1

    refused = api_client.update_subscription(
        subscription["id"],
        {"expected_subscription_version": seated["version"],
         "add_seat_learner_id": other["id"]},
        make_learner_headers(owner["id"]),
    )
    validate_error(refused, "ERR_SEAT_QUOTA_EXCEEDED")


def test_seat_quota_admits_the_first_seat_of_a_single_seat_plan(api):
    """PRD §3.5: "A seat begins `INVITED`. It is promoted `INVITED → ACTIVE` by a
    seat-adding subscription write, and only when the subscription is `ACTIVE`, its
    `seats_used` is still below its `seats_total`"
    PRD §3.5: "A subscription record carries `learner_id`, a `plan_code` drawn
    from `FREE`, `PLUS_FAMILY` or `CERTIFICATION_ELITE`, `seats_total` (a family
    plan's seat quota; free and single-seat plans carry 1), the derived
    `seats_used` count"

    Design: Difficulty/boundary_precision_check/family_seat_quota_exact_boundary
    """
    owner = register_learner(display_name="Ada", local_date_offset_days=0,
                             program_tier="FREE")
    member = register_learner(display_name="Bea", local_date_offset_days=0,
                              program_tier="FREE")
    subscription = subscribe(owner["id"], "PLUS_FAMILY", seats_total=1,
                             auto_renew=True)
    assert subscription["seats_total"] == 1

    seated = add_seat_ok(subscription["id"], owner["id"], member["id"],
                         subscription["version"])
    assert seated["seats_used"] == 1, (
        "seats_used 0 sits below seats_total 1, so the first seat is admitted"
    )
    assert seated["seats_used"] < seated["seats_total"] or (
        seated["seats_used"] == seated["seats_total"]
    )

    seats = get_success_data(api_client.list_subscription_memberships(
        subscription["id"], make_learner_headers(owner["id"])
    ))
    assert any(seat["member_learner_id"] == member["id"]
               and seat["status"] == "ACTIVE" for seat in seats), (
        f"the seat is minted ACTIVE, got {seats}"
    )