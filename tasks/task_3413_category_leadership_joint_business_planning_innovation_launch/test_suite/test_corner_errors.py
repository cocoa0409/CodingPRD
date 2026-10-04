"""Corner queue — error reachability: fiscal, temporal, and uniqueness errors
proven triggerable on their own (not merely as priority-conflict losers).

Each test translates one non-stub corner-design `errors` instance and cites
the PRD sentence that pins the asserted rule.
"""
from test_helpers import (
    ApiErrorId,
    create_launch_with_phases,
    create_penciled_event,
    create_review_payload,
    gate_all_phases,
    get_fund,
    post_accrual,
    setup_activated_plan,
    setup_review_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_event_lock_beyond_event_bucket_refused_insufficient_funds(
    api, manufacturer_planner_headers
):
    """PRD §3.2: "When no forecast qualifies, the plan's own `weekly_baseline_cases` serves as the fallback baseline."
    PRD §3.2: "The estimate itself is that baseline multiplied by the plan's `avg_unit_net_price_cents`, multiplied by the event's `discount_depth_pct`, divided by 100, with a single round-half-up to a whole cent applied at the very end."
    PRD §3.2: "The result is persisted as the event's `estimated_cost_cents` and immediately stress-tested against the fund: if it exceeds the plan fund's `event_available_cents` at that instant, the lock is refused with `ERR_INSUFFICIENT_FUNDS` (HTTP 422)."
    PRD §3.2: "A successful lock moves the event `PENCILED → LOCKED`, adds the estimate to the fund's `event_reserved_cents` — which correspondingly lowers `event_available_cents` — and increments the event's `version`."

    On an ACTIVATED plan (the state check passes) the fiscal rule is reachable
    alone: baseline 1000 × 450 × 25% = 112500 against an event bucket of 1600.
    The refused lock leaves the event PENCILED and nothing reserved.

    Design: Corner/errors/err_insufficient_funds_triggerable
    """
    scenario = setup_activated_plan(weekly_baseline_cases=1000)
    plan_id = scenario["plan"]["id"]
    fund_id = scenario["fund"]["id"]
    # Period credit 4000 -> EDLP share 2400, EVENT share (remainder) 1600.
    post_accrual(fund_id, "2027-01", 100000)
    event = create_penciled_event(plan_id, name="Big Feature", discount_depth_pct=25)

    validate_error(api.lock_event(event["id"], manufacturer_planner_headers),
                   ApiErrorId.ERR_INSUFFICIENT_FUNDS)

    events, _ = validate_paginated(api.list_events(plan_id, manufacturer_planner_headers))
    reloaded = [e for e in events if e["id"] == event["id"]]
    assert len(reloaded) == 1
    assert reloaded[0]["status"] == "PENCILED", (
        f"a refused lock must not transition the event, got {reloaded[0]['status']}"
    )
    assert get_fund(fund_id)["event_reserved_cents"] == 0, (
        "a refused lock must not move money into event_reserved_cents"
    )


def test_fully_gated_launch_before_launch_date_refused(api, manufacturer_planner_headers):
    """PRD §3.5: "Only then does the temporal check apply: the logical clock must have reached the `launch_date`, else the attempt fails with `ERR_LAUNCH_DATE_NOT_REACHED` (HTTP 422)."
    PRD §2.9: "Executing a launch checks the phase gates before it checks the calendar: a launch with an unpassed gate reports `ERR_PHASE_GATES_INCOMPLETE` even if its date has also not arrived, and only a fully gated launch can ever see `ERR_LAUNCH_DATE_NOT_REACHED`."
    PRD §2.4: "Before any operator has touched it, the logical clock reads exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time on its own."

    All four phases GATE_PASSED and the clock untouched at 2026-09-01 against a
    2027-06-01 launch date: the temporal error fires on its own.

    Design: Corner/errors/err_launch_date_not_reached_triggerable
    """
    scenario = setup_activated_plan()
    launch, phases = create_launch_with_phases(
        scenario["plan"]["id"], launch_date="2027-06-01T00:00:00Z"
    )
    gate_all_phases(launch["id"], phases)

    validate_error(
        api.execute_launch(launch["id"], manufacturer_planner_headers),
        ApiErrorId.ERR_LAUNCH_DATE_NOT_REACHED,
    )

    reloaded = validate_success(api.get_launch(launch["id"], manufacturer_planner_headers), 200)
    assert reloaded["status"] == "PLANNING", (
        f"a refused launch must not transition the launch, got {reloaded['status']}"
    )


def test_second_review_for_same_launch_refused(api, manufacturer_planner_headers):
    """PRD §3.9: "Uniqueness: at most one review may ever exist for a launch, and a second attempt fails with `ERR_REVIEW_ALREADY_EXISTS` (HTTP 409)."

    With the first review already OPEN, a second create for the same launch —
    well-formed and past the timing gate — fails `ERR_REVIEW_ALREADY_EXISTS`.

    Design: Corner/errors/err_review_already_exists_triggerable
    """
    scenario = setup_review_scenario()
    launch_id = scenario["launch"]["id"]

    validate_error(
        api.create_performance_review(
            launch_id,
            create_review_payload(
                period_start="2027-06-01T00:00:00Z",
                actual_sales_cents=100,
                distribution_achieved_pct=10,
            ),
            manufacturer_planner_headers,
        ),
        ApiErrorId.ERR_REVIEW_ALREADY_EXISTS,
    )
