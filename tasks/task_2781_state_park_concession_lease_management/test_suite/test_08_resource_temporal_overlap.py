"""Overlap arithmetic under the two coexisting interval conventions: closed
season windows on one lease, half-open closure windows aggregated per park."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_lease_state,
    assert_null,
    assert_status,
)

PLAN_RATES = {
    "max_lodging_rate_cents": 22000,
    "max_meal_rate_cents": 3400,
    "max_activity_rate_cents": 10000,
}
IMPROVEMENT_BASE = {
    "funding_source": "CONCESSIONAIRE_CAPITAL",
    "proposed_cost_cents": 5000000,
    "useful_life_years": 20,
    "ownership_at_expiration": "AGENCY",
}


def _lease_with_one_approved_season_and_two_candidates(api):
    """An approved 2027-03-01..2027-12-31 season, plus a plan that starts on its
    last day and a plan that starts the day after."""
    ctx = X.setup_active_lease(api)
    plan1 = X.submit_operating_plan(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        season_start="2027-03-01",
        season_end="2027-12-31",
        service_level="FULL",
        **PLAN_RATES,
    )
    X.approve_operating_plan(api, plan1["id"], X.exec_officer_headers())
    plan2 = X.submit_operating_plan(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        season_start="2027-12-31",
        season_end="2028-03-31",
        service_level="REDUCED",
        **PLAN_RATES,
    )
    plan3 = X.submit_operating_plan(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        season_start="2028-01-01",
        season_end="2028-03-31",
        service_level="REDUCED",
        **PLAN_RATES,
    )
    ctx.update(
        {
            "plan1_id": plan1["id"],
            "plan2_id": plan2["id"],
            "plan3_id": plan3["id"],
        }
    )
    return ctx


def _lease_with_two_approved_closure_windows(api):
    """Two approved closure windows covering 2027-05-01..2027-07-01 on the park,
    plus a candidate inside that doubly covered stretch and a candidate that
    starts on the exclusive end of the later window."""
    ctx = X.setup_active_lease(api)
    lease_id, offeror_id = ctx["lease_id"], ctx["offeror_id"]
    imp_a = X.propose_improvement(
        api,
        lease_id,
        offeror_id,
        description="Lodge roof replacement",
        construction_window_start="2027-04-01",
        construction_window_end="2027-07-01",
        **IMPROVEMENT_BASE,
    )
    X.approve_improvement(api, imp_a["id"], 5000000, X.exec_officer_headers())
    imp_b = X.propose_improvement(
        api,
        lease_id,
        offeror_id,
        description="Dining hall kitchen rebuild",
        construction_window_start="2027-05-01",
        construction_window_end="2027-08-01",
        **IMPROVEMENT_BASE,
    )
    X.approve_improvement(api, imp_b["id"], 5000000, X.exec_officer_headers())
    imp_c = X.propose_improvement(
        api,
        lease_id,
        offeror_id,
        description="Boat dock decking",
        construction_window_start="2027-06-01",
        construction_window_end="2027-09-01",
        **IMPROVEMENT_BASE,
    )
    imp_d = X.propose_improvement(
        api,
        lease_id,
        offeror_id,
        description="Trailhead comfort station",
        construction_window_start="2027-08-01",
        construction_window_end="2027-10-01",
        **IMPROVEMENT_BASE,
    )
    ctx.update(
        {
            "imp_a_id": imp_a["id"],
            "imp_b_id": imp_b["id"],
            "imp_c_id": imp_c["id"],
            "imp_d_id": imp_d["id"],
        }
    )
    return ctx


def test_season_starting_on_the_approved_season_last_day_is_a_collision(api):
    """PRD §2.8: "**Closed intervals** — operating seasons and lease years — run from an inclusive start to an inclusive end. `season_end` is the last day of the season and `lease_year_end` is the last day of the lease year. A closed interval requires its start to be at or before its end. Two closed intervals that share even a single calendar day overlap, and touching endpoints therefore do collide: a season ending 2027-09-30 and a season starting 2027-09-30 are in conflict."
    PRD §3.6: "Season collision is judged on closed intervals, so sharing even one calendar day is a collision and touching endpoints do conflict — a plan running to 2027-09-30 and a plan starting on 2027-09-30 cannot both be approved, and the second attempt earns `ERR_SEASON_OVERLAP`."
    PRD §3.6: "Plans in `SUBMITTED` or `RETURNED` do not reserve a season; only `APPROVED` ones do."

    Design: Difficulty/resource_temporal_overlap/season_closed_interval_rejects_touching_endpoint_on_same_lease
    """
    ctx = _lease_with_one_approved_season_and_two_candidates(api)

    response = api.approve_operating_plan(ctx["plan2_id"], X.exec_officer_headers())
    validate_error(response, "ERR_SEASON_OVERLAP", 409)

    plan2 = get_success_data(api.get_operating_plan(ctx["plan2_id"], X.exec_officer_headers()))
    assert_status(plan2, "SUBMITTED")
    plan1 = get_success_data(api.get_operating_plan(ctx["plan1_id"], X.exec_officer_headers()))
    assert_status(plan1, "APPROVED")


def test_season_starting_the_day_after_the_approved_season_is_approvable(api):
    """PRD §3.6: "Approval belongs to a `ContractingOfficer` and moves the plan `SUBMITTED → APPROVED`. It takes no payload and enforces three things after the plan's own status: the lease must still be `ACTIVE`; the season must not collide with another `APPROVED` season on the same lease; and every rate must sit under its ceiling."
    PRD §3.6: "Season collision is judged on closed intervals, so sharing even one calendar day is a collision and touching endpoints do conflict — a plan running to 2027-09-30 and a plan starting on 2027-09-30 cannot both be approved, and the second attempt earns `ERR_SEASON_OVERLAP`."
    PRD §3.6: "`SUPERSEDED` is the plan's only terminal state, and no request produces it directly: it arrives only as a cascade from lease expiry or from a bond-draw default."

    Design: Difficulty/resource_temporal_overlap/season_closed_interval_rejects_touching_endpoint_on_same_lease
    """
    ctx = _lease_with_one_approved_season_and_two_candidates(api)

    validate_error(
        api.approve_operating_plan(ctx["plan2_id"], X.exec_officer_headers()),
        "ERR_SEASON_OVERLAP",
        409,
    )

    response = api.approve_operating_plan(ctx["plan3_id"], X.exec_officer_headers())
    validate_success(response, 200)
    plan3 = get_success_data(response)
    assert_status(plan3, "APPROVED")

    plan1 = get_success_data(api.get_operating_plan(ctx["plan1_id"], X.exec_officer_headers()))
    assert_status(plan1, "APPROVED")
    lease = get_success_data(api.get_lease(ctx["lease_id"], X.exec_officer_headers()))
    assert_lease_state(lease, contract_status="ACTIVE")


def test_third_overlapping_closure_window_exhausts_the_park_capacity(api):
    """PRD §3.7: "Then the park's construction capacity: counting the improvements on the same `park_id` whose status is `APPROVED` and whose half-open closure window intersects the one being approved, that count must be strictly below two, else `ERR_PARK_CLOSURE_CAPACITY`."
    PRD §3.7: "A park tolerates two overlapping approved closures; a third simultaneous one would shut too much of the park at once."
    PRD §3.7: "The improvement is created in `PROPOSED`, `approved_cost_cents`, `actual_cost_cents`, `in_service_date`, `unamortized_value_cents` and `deficiency_note` all null, and `park_id` copied from the lease so that closure windows can be counted per park without walking the lease graph."

    Design: Difficulty/resource_temporal_overlap/construction_window_half_open_aggregate_capacity_on_park
    """
    ctx = _lease_with_two_approved_closure_windows(api)

    response = api.approve_improvement(
        ctx["imp_c_id"], {"approved_cost_cents": 5000000}, X.exec_officer_headers()
    )
    validate_error(response, "ERR_PARK_CLOSURE_CAPACITY", 409)

    improvement_c = get_success_data(
        api.get_improvement(ctx["imp_c_id"], X.exec_officer_headers())
    )
    assert_status(improvement_c, "PROPOSED")
    assert_null(improvement_c, "approved_cost_cents")


def test_window_starting_on_an_exclusive_end_does_not_count_as_overlap(api):
    """PRD §2.8: "**Half-open intervals** — construction closure windows, gross receipts reporting periods and audit windows — run from an inclusive start to an exclusive end. `construction_window_end` is the day the site reopens; `period_end` is the day after the last day reported; `audit_period_end` is the day after the last day audited. A half-open interval requires its start to be strictly before its end. Two half-open intervals that merely touch — one ending on the same day the next begins — are adjacent, not overlapping."
    PRD §3.7: "Because the windows are half-open, an improvement whose window ends the day another's begins does not count against it."
    PRD §3.1: "`open_closure_window_count` is the number of capital improvements on the park whose status is `APPROVED` — in other words, the number of construction closure windows the agency currently has reserved at that park. It rises by one when an improvement is approved and falls by one whenever an approved improvement leaves that status, whether because the asset was placed in service or because a lease event withdrew it."

    Design: Difficulty/resource_temporal_overlap/construction_window_half_open_aggregate_capacity_on_park
    """
    ctx = _lease_with_two_approved_closure_windows(api)

    validate_error(
        api.approve_improvement(
            ctx["imp_c_id"], {"approved_cost_cents": 5000000}, X.exec_officer_headers()
        ),
        "ERR_PARK_CLOSURE_CAPACITY",
        409,
    )

    response = api.approve_improvement(
        ctx["imp_d_id"], {"approved_cost_cents": 5000000}, X.exec_officer_headers()
    )
    validate_success(response, 200)
    improvement_d = get_success_data(response)
    assert_status(improvement_d, "APPROVED")
    assert_cents_equals(improvement_d["approved_cost_cents"], 5000000, "approved_cost_cents")

    park = get_success_data(api.get_park(ctx["park_id"], X.exec_officer_headers()))
    assert park["open_closure_window_count"] == 3, (
        "open_closure_window_count: expected 3 approved closure windows, "
        f"got {park['open_closure_window_count']}"
    )
