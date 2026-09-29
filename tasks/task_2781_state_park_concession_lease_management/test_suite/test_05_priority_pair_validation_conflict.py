"""Requests that violate two rules at once: the lower-numbered band wins."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_lease_state,
    assert_null,
    assert_status,
    error_id_of,
)

MONTHLY_RECEIPTS = {
    "lodging_receipts_cents": 10000000,
    "food_beverage_receipts_cents": 20000000,
    "retail_receipts_cents": 8000000,
    "activity_receipts_cents": 2000000,
}
MONTHS = (
    {"period_start": "2027-04-01", "period_end": "2027-05-01"},
    {"period_start": "2027-05-01", "period_end": "2027-06-01"},
    {"period_start": "2027-06-01", "period_end": "2027-07-01"},
)


def _holdover_lease_with_three_accepted_months(api):
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    report_ids = []
    for period in MONTHS:
        report = X.file_report(
            api, ctx["lease_id"], ctx["offeror_id"], **dict(period, **MONTHLY_RECEIPTS)
        )
        X.accept_report(api, report["id"], 2150000)
        report_ids.append(report["id"])
    X.set_clock(api, "2037-03-01T00:00:00Z")
    validate_success(api.enter_holdover(ctx["lease_id"], X.exec_officer_headers()))
    ctx["report_ids"] = report_ids
    return ctx


def test_holdover_lease_state_error_outranks_the_report_period_overlap(api):
    """PRD §2.9: "Checks are grouped into ordered bands, evaluated strictly from the lowest band upward, and **the lowest-numbered failing check is the one reported**."
    PRD §2.9: "**The referenced lease's contract posture** — `ERR_LEASE_NOT_ACTIVE` when a capital improvement, operating plan, gross receipts report or fee reconciliation is filed against a lease whose `contract_status` is not `ACTIVE`, and equally when an improvement or a plan is approved; `ERR_LEASE_STATUS_INVALID` when a compliance action names a lease outside `ACTIVE` or `HOLDOVER`, or an audit engagement names a lease outside `ACTIVE`, `HOLDOVER` or `EXPIRED`."
    PRD §3.8: "And the period must not intersect another report on the same lease whose status is `SUBMITTED`, `ACCEPTED` or `RESTATED`, else `ERR_REPORT_PERIOD_OVERLAP`; because reporting periods are half-open, a period ending 2027-07-01 and a period starting 2027-07-01 are adjacent rather than overlapping and both may stand."

    Design: Difficulty/priority_pair_validation_conflict/holdover_lease_state_error_precedes_report_period_overlap
    """
    ctx = _holdover_lease_with_three_accepted_months(api)

    response = api.create_report(
        F.report_payload(
            ctx["lease_id"],
            period_start="2027-04-15",
            period_end="2027-05-15",
            **MONTHLY_RECEIPTS,
        ),
        ctx["offeror_headers"],
    )
    validate_error(response, ApiErrorId.ERR_LEASE_NOT_ACTIVE.value, 409)
    assert error_id_of(response) != ApiErrorId.ERR_REPORT_PERIOD_OVERLAP.value

    assert_lease_state(X.read_lease(api, ctx["lease_id"]), contract_status="HOLDOVER")


def test_holdover_report_rejection_writes_nothing(api):
    """PRD §2.9: "A request that violates a fiscal limit and also names a lease in the wrong state always comes back with the state error, never the fiscal one."
    PRD §2.7: "If that number does not equal the lease's current `version`, the write is rejected with `ERR_STALE_LEASE_VERSION` (HTTP 412) and nothing is created or modified."

    Design: Difficulty/priority_pair_validation_conflict/holdover_lease_state_error_precedes_report_period_overlap
    """
    ctx = _holdover_lease_with_three_accepted_months(api)

    validate_error(
        api.create_report(
            F.report_payload(
                ctx["lease_id"],
                period_start="2027-04-15",
                period_end="2027-05-15",
                **MONTHLY_RECEIPTS,
            ),
            ctx["offeror_headers"],
        ),
        ApiErrorId.ERR_LEASE_NOT_ACTIVE.value,
        409,
    )

    rows, meta = validate_paginated(
        api.list_reports(X.award_officer_headers(), {"lease_id": ctx["lease_id"]})
    )
    assert meta["total_count"] == 3, meta
    for report_id in ctx["report_ids"][:2]:
        assert_status(
            get_success_data(api.get_report(report_id, X.award_officer_headers())),
            "ACCEPTED",
        )


def _lapsed_insurance_with_oversized_improvement(api):
    ctx = X.setup_active_lease(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    validate_success(
        api.record_insurance_certificate(
            ctx["lease_id"],
            F.insurance_certificate_payload(
                insurance_expires_on="2027-05-31", carrier_name="Basin Indemnity"
            ),
            X.exec_officer_headers(),
        )
    )
    improvement = X.propose_improvement(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        description="Lodge annex expansion",
        funding_source="CONCESSIONAIRE_CAPITAL",
        proposed_cost_cents=40000000,
        useful_life_years=25,
        construction_window_start="2027-08-01",
        construction_window_end="2027-10-01",
        ownership_at_expiration="CONCESSIONAIRE",
    )
    ctx["improvement_id"] = improvement["id"]
    return ctx


def test_lapsed_insurance_outranks_the_capital_obligation_excess(api):
    """PRD §3.7: "The lease's `insurance_expires_on` must be strictly after the logical clock's date, else `ERR_INSURANCE_LAPSED`."
    PRD §3.7: "For `CONCESSIONAIRE_CAPITAL`, add the lease's `capital_investment_completed_cents`, the `approved_cost_cents` already committed by this lease's improvements currently in `APPROVED`, and the `approved_cost_cents` on this request; that total must be no greater than the lease's `capital_investment_obligation_cents`, else `ERR_IMPROVEMENT_EXCEEDS_OBLIGATION`."
    PRD §3.7: "Five conditions are evaluated in this order."

    Design: Difficulty/priority_pair_validation_conflict/insurance_safety_error_precedes_capital_obligation_excess
    """
    ctx = _lapsed_insurance_with_oversized_improvement(api)

    response = api.approve_improvement(
        ctx["improvement_id"],
        F.approve_improvement_payload(40000000),
        X.exec_officer_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INSURANCE_LAPSED.value, 409)
    assert error_id_of(response) != ApiErrorId.ERR_IMPROVEMENT_EXCEEDS_OBLIGATION.value


def test_refused_improvement_approval_leaves_improvement_park_and_lease_untouched(api):
    """PRD §3.7: "On success `approved_cost_cents` is persisted, the park's `open_closure_window_count` rises by one, and — only on the reserve-funded branch — the lease's `maintenance_reserve_balance_cents` is reduced by `approved_cost_cents` immediately, at approval rather than at completion."
    PRD §3.5: "Neither of the lease's two status dimensions moves, but the lease's `version` advances by one, which matters to any client holding an `expected_lease_version` from before the filing."

    Design: Difficulty/priority_pair_validation_conflict/insurance_safety_error_precedes_capital_obligation_excess
    """
    ctx = _lapsed_insurance_with_oversized_improvement(api)

    validate_error(
        api.approve_improvement(
            ctx["improvement_id"],
            F.approve_improvement_payload(40000000),
            X.exec_officer_headers(),
        ),
        ApiErrorId.ERR_INSURANCE_LAPSED.value,
        409,
    )

    improvement = get_success_data(
        api.get_improvement(ctx["improvement_id"], X.award_officer_headers())
    )
    assert_status(improvement, "PROPOSED")
    assert_null(improvement, "approved_cost_cents")

    park = get_success_data(api.get_park(ctx["park_id"], X.award_officer_headers()))
    assert park["open_closure_window_count"] == 0, park["open_closure_window_count"]

    lease = X.read_lease(api, ctx["lease_id"])
    assert_fields(
        lease,
        {"insurance_expires_on": "2027-05-31", "carrier_name": "Basin Indemnity"},
    )
    assert_cents_equals(
        lease["capital_investment_completed_cents"], 0, "capital_investment_completed_cents"
    )
