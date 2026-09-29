"""Validation coverage: normalization, park rate ceilings, temporal thresholds,
the funding fork and interval ordering."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_status,
)

CEILING_RATES = {
    "max_lodging_rate_cents": 23000,
    "max_meal_rate_cents": 3450,
    "max_activity_rate_cents": 10350,
}


def _count(response) -> int:
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def test_prospectus_weights_totalling_ninety_nine_are_refused(api):
    """PRD §3.2: "Five weights — `weight_experience`, `weight_operating_plan`, `weight_capital_investment`, `weight_financial_capacity` and `weight_fee_offer` — are whole percentage points, each between 0 and 100 inclusive, and their sum must be exactly 100."
    PRD §3.2: "A set of weights totalling 99 or 101 is refused with `ERR_WEIGHTS_NOT_NORMALIZED`, and that check runs ahead of every interval, concurrency and business rule in the request."
    PRD §2.9: "**Weight normalization** — the five prospectus evaluation weights total exactly 100, else `ERR_WEIGHTS_NOT_NORMALIZED` (HTTP 422)."

    Design: Corner/validations/prospectus_weights_not_summing_to_one_hundred_is_rejected
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    park = X.register_park(api)
    opportunity = X.approved_opportunity(api, park["id"])

    response = api.create_prospectus(
        F.prospectus_payload(opportunity["id"], weight_fee_offer=19), X.specialist_headers()
    )
    validate_error(response, "ERR_WEIGHTS_NOT_NORMALIZED", 422)

    assert (
        _count(
            api.list_prospectuses(
                X.award_officer_headers(), {"opportunity_id": opportunity["id"]}
            )
        )
        == 0
    )
    stored = get_success_data(
        api.get_opportunity(opportunity["id"], X.award_officer_headers())
    )
    assert_status(stored, "APPROVED_FOR_SOLICITATION")


def test_a_plan_asking_exactly_the_park_ceiling_rates_is_approved(api):
    """PRD §3.6: "For each of the three categories, the ceiling is the park's regional benchmark for that category multiplied by one and fifteen hundredths (1.15), rounded half up to whole cents: `max_lodging_rate_cents` is tested against `comparable_lodging_rate_cents`, `max_meal_rate_cents` against `comparable_meal_rate_cents`, and `max_activity_rate_cents` against `comparable_activity_rate_cents`."
    PRD §3.6: "A rate exactly at its ceiling passes; a rate one cent above it fails the whole approval with `ERR_RATE_EXCEEDS_CEILING`."
    PRD §3.6: "Approval belongs to a `ContractingOfficer` and moves the plan `SUBMITTED → APPROVED`."

    Design: Corner/validations/rate_exactly_at_the_park_ceiling_multiplier_is_approved
    """
    ctx = X.setup_active_lease(api)
    plan = X.submit_operating_plan(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        season_start="2027-03-01",
        season_end="2027-12-31",
        service_level="FULL",
        **CEILING_RATES,
    )

    response = api.approve_operating_plan(plan["id"], X.exec_officer_headers())
    validate_success(response, 200)
    approved = get_success_data(response)
    assert_status(approved, "APPROVED")
    assert_cents_equals(approved["max_lodging_rate_cents"], 23000, "max_lodging_rate_cents")
    assert_cents_equals(approved["max_meal_rate_cents"], 3450, "max_meal_rate_cents")
    assert_cents_equals(approved["max_activity_rate_cents"], 10350, "max_activity_rate_cents")


def test_a_plan_one_cent_above_the_lodging_ceiling_is_refused(api):
    """PRD §3.6: "For each of the three categories, the ceiling is the park's regional benchmark for that category multiplied by one and fifteen hundredths (1.15), rounded half up to whole cents: `max_lodging_rate_cents` is tested against `comparable_lodging_rate_cents`, `max_meal_rate_cents` against `comparable_meal_rate_cents`, and `max_activity_rate_cents` against `comparable_activity_rate_cents`."
    PRD §3.6: "A rate exactly at its ceiling passes; a rate one cent above it fails the whole approval with `ERR_RATE_EXCEEDS_CEILING`."
    PRD §3.6: "All three categories are tested, so a plan may be refused for a lodging rate even when its meal and activity rates are conservative."
    PRD §2.9: "`ERR_RATE_EXCEEDS_CEILING` (HTTP 422) — a maximum public rate above the park's benchmark ceiling."

    Design: Corner/validations/plan_rate_one_cent_above_the_park_ceiling_is_rejected
    """
    ctx = X.setup_active_lease(api)
    plan = X.submit_operating_plan(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        season_start="2027-03-01",
        season_end="2027-12-31",
        service_level="FULL",
        **dict(CEILING_RATES, max_lodging_rate_cents=23001),
    )

    response = api.approve_operating_plan(plan["id"], X.exec_officer_headers())
    validate_error(response, "ERR_RATE_EXCEEDS_CEILING", 422)

    stored = get_success_data(api.get_operating_plan(plan["id"], X.award_officer_headers()))
    assert_status(stored, "SUBMITTED")
    assert_fields(stored, {"deficiency_note": None, "max_lodging_rate_cents": 23001})


def test_reconciling_on_the_last_day_of_the_lease_year_is_refused(api):
    """PRD §3.8: "The lease must be `ACTIVE`, and the logical clock's date must be strictly after `lease_year_end`, else `ERR_RECONCILIATION_PERIOD_NOT_ELAPSED`: a lease year cannot be reconciled before it is over."
    PRD §2.9: "`ERR_RECONCILIATION_PERIOD_NOT_ELAPSED` — the clock's date must be strictly after the requested `lease_year_end` before that year may be reconciled."
    PRD §3.4: "The same arithmetic defines every lease year: the Nth lease year, counting from one, begins on the date `term_start` plus N minus one whole years and ends on the date `term_start` plus N whole years minus one day, and both endpoints are inclusive."
    PRD §5: "| `ERR_RECONCILIATION_PERIOD_NOT_ELAPSED` | 409 |"

    Design: Corner/validations/reconciliation_on_the_last_day_of_the_lease_year_is_rejected
    """
    ctx = X.setup_active_lease(api)
    X.set_clock(api, "2028-02-29T00:00:00Z")
    version_before = X.lease_version(api, ctx["lease_id"])

    response = api.create_reconciliation(
        F.reconciliation_payload(
            ctx["lease_id"],
            version_before,
            lease_year_start="2027-03-01",
            lease_year_end="2028-02-29",
        ),
        X.exec_officer_headers(),
    )
    validate_error(response, "ERR_RECONCILIATION_PERIOD_NOT_ELAPSED", 409)

    assert (
        _count(
            api.list_reconciliations(X.award_officer_headers(), {"lease_id": ctx["lease_id"]})
        )
        == 0
    )
    assert X.lease_version(api, ctx["lease_id"]) == version_before


def test_reserve_funded_approval_against_an_empty_reserve_is_refused(api):
    """PRD §3.7: "The fifth condition depends on the funding fork, and exactly one branch applies."
    PRD §3.7: "For `MAINTENANCE_RESERVE`, the request's `approved_cost_cents` must be no greater than the lease's `maintenance_reserve_balance_cents`, else `ERR_MAINTENANCE_RESERVE_INSUFFICIENT`; again equality passes."
    PRD §3.8: "The reserve is an accrual, not cash — its running balance, `maintenance_reserve_balance_cents` on the lease, is the sum of `maintenance_reserve_due_cents` over the lease's `ACCEPTED` and `RESTATED` reports less the `approved_cost_cents` of every reserve-funded improvement that has reached `APPROVED` or beyond."
    PRD §2.9: "`ERR_MAINTENANCE_RESERVE_INSUFFICIENT` (HTTP 422) — reserve-funded improvement approval past the accrued reserve."

    Design: Corner/validations/maintenance_reserve_funding_with_an_empty_reserve_is_rejected
    """
    ctx = X.setup_active_lease(api)
    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["maintenance_reserve_balance_cents"], 0, "maintenance_reserve_balance_cents"
    )
    assert_cents_equals(
        lease["capital_investment_obligation_cents"],
        30000000,
        "capital_investment_obligation_cents",
    )
    improvement = X.propose_improvement(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        description="Trailhead restroom refresh",
        funding_source="MAINTENANCE_RESERVE",
        proposed_cost_cents=500000,
        useful_life_years=10,
        construction_window_start="2027-04-01",
        construction_window_end="2027-06-01",
        ownership_at_expiration="AGENCY",
    )

    response = api.approve_improvement(
        improvement["id"], F.approve_improvement_payload(500000), X.exec_officer_headers()
    )
    validate_error(response, "ERR_MAINTENANCE_RESERVE_INSUFFICIENT", 422)

    stored = get_success_data(api.get_improvement(improvement["id"], X.award_officer_headers()))
    assert_status(stored, "PROPOSED")
    assert_fields(stored, {"approved_cost_cents": None})

    park = get_success_data(api.get_park(ctx["park_id"], X.award_officer_headers()))
    assert park["open_closure_window_count"] == 0, park["open_closure_window_count"]
    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["maintenance_reserve_balance_cents"], 0, "maintenance_reserve_balance_cents"
    )


def test_capital_funded_approval_counts_the_cost_already_committed_by_approved_work(api):
    """PRD §3.7: "For `CONCESSIONAIRE_CAPITAL`, add the lease's `capital_investment_completed_cents`, the `approved_cost_cents` already committed by this lease's improvements currently in `APPROVED`, and the `approved_cost_cents` on this request; that total must be no greater than the lease's `capital_investment_obligation_cents`, else `ERR_IMPROVEMENT_EXCEEDS_OBLIGATION`."
    PRD §3.7: "Equality passes — a project that exactly exhausts the obligation is approvable."
    PRD §3.7: "On success `approved_cost_cents` is persisted, the park's `open_closure_window_count` rises by one, and — only on the reserve-funded branch — the lease's `maintenance_reserve_balance_cents` is reduced by `approved_cost_cents` immediately, at approval rather than at completion."
    PRD §3.7: "Because the windows are half-open, an improvement whose window ends the day another's begins does not count against it."
    PRD §2.9: "`ERR_IMPROVEMENT_EXCEEDS_OBLIGATION` (HTTP 422) — capital-funded improvement approval past the obligation."

    Design: Corner/validations/improvement_approval_above_the_committed_capital_obligation_is_rejected
    """
    ctx = X.setup_active_lease(api)
    first = X.propose_improvement(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        description="Lodge wing reconstruction",
        funding_source="CONCESSIONAIRE_CAPITAL",
        proposed_cost_cents=30000000,
        useful_life_years=30,
        construction_window_start="2027-04-01",
        construction_window_end="2027-06-01",
        ownership_at_expiration="AGENCY",
    )
    X.approve_improvement(api, first["id"], 30000000)
    second = X.propose_improvement(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        description="Interpretive signage",
        funding_source="CONCESSIONAIRE_CAPITAL",
        proposed_cost_cents=1,
        useful_life_years=10,
        construction_window_start="2027-06-01",
        construction_window_end="2027-08-01",
        ownership_at_expiration="AGENCY",
    )

    response = api.approve_improvement(
        second["id"], F.approve_improvement_payload(1), X.exec_officer_headers()
    )
    validate_error(response, "ERR_IMPROVEMENT_EXCEEDS_OBLIGATION", 422)

    assert_status(
        get_success_data(api.get_improvement(second["id"], X.award_officer_headers())),
        "PROPOSED",
    )
    assert_status(
        get_success_data(api.get_improvement(first["id"], X.award_officer_headers())),
        "APPROVED",
    )
    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["capital_investment_completed_cents"], 0, "capital_investment_completed_cents"
    )
    park = get_success_data(api.get_park(ctx["park_id"], X.award_officer_headers()))
    assert park["open_closure_window_count"] == 1, park["open_closure_window_count"]


def test_a_zero_length_reporting_period_is_refused_before_any_lease_state_check(api):
    """PRD §2.8: "**Half-open intervals** — construction closure windows, gross receipts reporting periods and audit windows — run from an inclusive start to an exclusive end."
    PRD §2.8: "A half-open interval requires its start to be strictly before its end."
    PRD §2.8: "Any interval violating its own ordering requirement is rejected with `ERR_INVALID_INTERVAL` (HTTP 422)."
    PRD §2.9: "**Interval sanity** — the ordering rules of §2.8, else `ERR_INVALID_INTERVAL`. Applies to capital-improvement creation and resubmission, operating-plan creation and resubmission, gross-receipts-report creation, fee-reconciliation creation and audit-engagement creation."
    PRD §2.9: "Checks are grouped into ordered bands, evaluated strictly from the lowest band upward, and **the lowest-numbered failing check is the one reported**."

    Design: Corner/validations/report_period_with_equal_start_and_end_is_rejected
    """
    ctx = X.setup_awarded_lease(api)
    assert_status(X.read_lease(api, ctx["lease_id"]), "PENDING_EXECUTION", "contract_status")

    response = api.create_report(
        F.report_payload(
            ctx["lease_id"],
            period_start="2027-06-01",
            period_end="2027-06-01",
            lodging_receipts_cents=1000000,
            food_beverage_receipts_cents=0,
            retail_receipts_cents=0,
            activity_receipts_cents=0,
        ),
        X.concessionaire_headers(ctx["offeror_id"]),
    )
    validate_error(response, "ERR_INVALID_INTERVAL", 422)

    assert _count(api.list_reports(X.award_officer_headers(), {"lease_id": ctx["lease_id"]})) == 0
