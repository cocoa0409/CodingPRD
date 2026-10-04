"""Difficulty queue — compensating invariants.

Two conserved quantities must survive a forward action and its compensation:
the fund's EVENT bucket across an event lock paired with a cancel (PRD
§3.2/§2.11), and the launch's trade budget across phase-spend patches (PRD
§3.5). Each test translates one difficulty-design instance and cites the PRD
rule it pins.
"""
from test_helpers import (
    assert_fund_invariants,
    assert_launch_budget_invariant,
    assert_promotional_event,
    assert_trade_fund,
    create_launch_with_phases,
    list_phases,
    setup_activated_plan,
    validate_success,
)


def _funded_event_scenario(api, finance_analyst_headers, manufacturer_planner_headers):
    """ACTIVATED plan (baseline 100 cases, 450 cents/unit) whose fund holds one
    posted period of 1,000,000 invoiced cents (EVENT bucket: 16,000), plus one
    PENCILED FEATURE event at 25% depth. Returns (fund_before_lock, event)."""
    scenario = setup_activated_plan()
    fund_id = scenario["fund"]["id"]
    validate_success(
        api.post_fund_accrual(
            fund_id, {"period": "2027-01", "invoiced_sales_cents": 1000000}, finance_analyst_headers
        ),
        201,
    )
    fund_pre = validate_success(api.get_fund(fund_id, finance_analyst_headers), 200)
    event = validate_success(
        api.create_event(
            scenario["plan"]["id"],
            {
                "name": "Feature A",
                "event_type": "FEATURE",
                "start_date": "2027-03-01T00:00:00Z",
                "end_date": "2027-03-10T00:00:00Z",
                "discount_depth_pct": 25,
            },
            manufacturer_planner_headers,
        ),
        201,
    )
    return fund_pre, event


def test_lock_reserves_estimate_against_event_bucket(api, finance_analyst_headers, manufacturer_planner_headers):
    """PRD §3.2: "When no forecast qualifies, the plan's own `weekly_baseline_cases` serves as the fallback baseline."
    PRD §3.2: "The estimate itself is that baseline multiplied by the plan's `avg_unit_net_price_cents`, multiplied by the event's `discount_depth_pct`, divided by 100, with a single round-half-up to a whole cent applied at the very end."
    PRD §3.2: "A successful lock moves the event `PENCILED → LOCKED`, adds the estimate to the fund's `event_reserved_cents` — which correspondingly lowers `event_available_cents` — and increments the event's `version`."
    PRD §2.11: "the event bucket's `event_available_cents` is what accrued minus what is currently reserved minus what has settled."

    With no forecast the estimate falls back to the plan baseline:
    round_half_up(100 * 450 * 25 / 100) = 11250; locking reserves it, leaving
    16000 - 11250 = 4750 available while the 16000 accrual is untouched.

    Design: Difficulty/compensating_invariant/event_lock_cancel_conserves_event_funding
    """
    fund_pre, event = _funded_event_scenario(api, finance_analyst_headers, manufacturer_planner_headers)
    assert fund_pre["event_accrued_cents"] == 16000
    assert fund_pre["event_reserved_cents"] == 0
    assert fund_pre["event_available_cents"] == 16000

    locked = validate_success(api.lock_event(event["id"], manufacturer_planner_headers), 200)
    assert_promotional_event(locked)
    assert locked["status"] == "LOCKED"
    assert locked["estimated_cost_cents"] == 11250, (
        f"plan-baseline fallback estimate must be 11250, got {locked['estimated_cost_cents']}"
    )

    fund = validate_success(api.get_fund(fund_pre["id"], finance_analyst_headers), 200)
    assert_trade_fund(fund)
    assert fund["event_reserved_cents"] == 11250
    assert fund["event_available_cents"] == 4750, (
        f"16000 - 11250 reserved must leave 4750, got {fund['event_available_cents']}"
    )
    assert fund["event_accrued_cents"] == 16000, "reservation never touches the accrual"
    assert_fund_invariants(fund)


def test_cancel_releases_reservation_byte_identical(api, finance_analyst_headers, manufacturer_planner_headers):
    """PRD §3.2: "Cancelling a `LOCKED` event releases the reservation — the event's `estimated_cost_cents` is subtracted from the fund's `event_reserved_cents`, restoring availability — before the event lands `CANCELLED` with its `version` incremented."
    PRD §2.11: "Locking a promotional event reserves its estimated cost into `event_reserved_cents`, and cancelling a locked event releases exactly that amount back."

    The lock/cancel compensating pair returns event_available_cents to exactly
    its pre-lock value; the invariant accrued == available + reserved +
    settled holds at every step.

    Design: Difficulty/compensating_invariant/event_lock_cancel_conserves_event_funding
    """
    fund_pre, event = _funded_event_scenario(api, finance_analyst_headers, manufacturer_planner_headers)

    validate_success(api.lock_event(event["id"], manufacturer_planner_headers), 200)
    fund_locked = validate_success(api.get_fund(fund_pre["id"], finance_analyst_headers), 200)
    assert_fund_invariants(fund_locked)

    cancelled = validate_success(api.cancel_event(event["id"], manufacturer_planner_headers), 200)
    assert_promotional_event(cancelled)
    assert cancelled["status"] == "CANCELLED"

    fund = validate_success(api.get_fund(fund_pre["id"], finance_analyst_headers), 200)
    assert_trade_fund(fund)
    assert fund["event_reserved_cents"] == 0
    assert fund["event_available_cents"] == fund_pre["event_available_cents"], (
        "the compensating pair must restore availability byte-identically: "
        f"{fund['event_available_cents']} != {fund_pre['event_available_cents']}"
    )
    assert fund["event_accrued_cents"] == fund_pre["event_accrued_cents"] == 16000
    assert_fund_invariants(fund)


def _launch_with_million_budget(api, manufacturer_planner_headers):
    """ACTIVATED plan plus one launch funded with 1,000,000 cents and four
    zeroed PENDING phases."""
    scenario = setup_activated_plan()
    launch, phases = create_launch_with_phases(
        scenario["plan"]["id"], total_trade_budget_cents=1000000
    )
    return launch, phases


def test_phase_spend_patch_draws_down_budget_remaining(api, manufacturer_planner_headers):
    """PRD §3.5: "The launch itself is born `PLANNING`, its `budget_remaining_cents` initialized to the full `total_trade_budget_cents`, both distribution projections at 0, and `launched_at` null."
    PRD §3.5: "A successful patch applies the field updates, returns a `GATE_FAILED` phase to `PENDING` (a `PENDING` phase simply stays `PENDING`), recomputes the launch's `budget_remaining_cents` as the total budget minus the sum of phase spends, refreshes both distribution projections, and increments the phase's `version`."

    budget_remaining starts at the full 1,000,000; patching phase 1 to a
    100,000 spend draws it down to 900,000 with the conservation invariant
    intact.

    Design: Difficulty/compensating_invariant/phase_budget_patch_conserves_total
    """
    launch, phases = _launch_with_million_budget(api, manufacturer_planner_headers)
    fresh = validate_success(api.get_launch(launch["id"], manufacturer_planner_headers), 200)
    assert fresh["budget_remaining_cents"] == 1000000
    assert_launch_budget_invariant(fresh, phases)

    patched = validate_success(
        api.patch_launch_phase(
            launch["id"], phases[0]["id"], {"trade_spend_cents": 100000}, manufacturer_planner_headers
        ),
        200,
    )
    assert patched["trade_spend_cents"] == 100000
    assert patched["status"] == "PENDING"

    after = validate_success(api.get_launch(launch["id"], manufacturer_planner_headers), 200)
    assert after["budget_remaining_cents"] == 900000, (
        f"1000000 - 100000 must leave 900000, got {after['budget_remaining_cents']}"
    )
    assert_launch_budget_invariant(after, list_phases(launch["id"]))


def test_phase_spend_repatch_conserves_total_at_each_step(api, manufacturer_planner_headers):
    """PRD §3.5: "A successful patch applies the field updates, returns a `GATE_FAILED` phase to `PENDING` (a `PENDING` phase simply stays `PENDING`), recomputes the launch's `budget_remaining_cents` as the total budget minus the sum of phase spends, refreshes both distribution projections, and increments the phase's `version`."

    Raising phase 1's spend to 100,000 and later to 400,000 leaves
    budget_remaining at 900,000 then 600,000 — total == remaining + spent
    after every write.

    Design: Difficulty/compensating_invariant/phase_budget_patch_conserves_total
    """
    launch, phases = _launch_with_million_budget(api, manufacturer_planner_headers)

    for spend, expected_remaining in ((100000, 900000), (400000, 600000)):
        validate_success(
            api.patch_launch_phase(
                launch["id"], phases[0]["id"], {"trade_spend_cents": spend}, manufacturer_planner_headers
            ),
            200,
        )
        after = validate_success(api.get_launch(launch["id"], manufacturer_planner_headers), 200)
        assert after["budget_remaining_cents"] == expected_remaining, (
            f"spend {spend} must leave {expected_remaining}, got {after['budget_remaining_cents']}"
        )
        current_phases = list_phases(launch["id"])
        assert_launch_budget_invariant(after, current_phases)
        assert after["total_trade_budget_cents"] == 1000000, (
            "the total budget is an input and must never move"
        )
