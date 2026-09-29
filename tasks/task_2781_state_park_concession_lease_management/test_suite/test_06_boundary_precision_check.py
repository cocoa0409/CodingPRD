"""Inclusive thresholds tested on the boundary value itself and one step below."""
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
    assert_null,
    assert_pct_equals,
    assert_status,
)
from test_helpers.test_users import concessionaire_headers

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


def _solicitation_with_two_offerors(api):
    """An ISSUED prospectus whose `minimum_franchise_fee_pct` is 4.00 and two
    eligible offerors able to answer it."""
    ctx = X.setup_issued_prospectus(api)
    second = X.register_offeror(
        api,
        legal_name="Basin Outfitters Inc",
        contact_email="bids@basinoutfitters.example",
        bond_capacity_cents=40000000,
    )
    ctx["offeror_b_id"] = second["id"]
    ctx["offeror_b_headers"] = concessionaire_headers(second["id"])
    return ctx


def test_offer_at_exactly_the_minimum_franchise_fee_is_responsive(api):
    """PRD §3.3: "Only then are the two fiscal floors applied: `offered_franchise_fee_pct` must be at least `minimum_franchise_fee_pct`, with equality passing — a proposal offering exactly the minimum is responsive — else `ERR_FEE_BELOW_MINIMUM`; and `proposed_annual_guarantee_cents` must be at least `minimum_annual_guarantee_cents`, again with equality passing, else `ERR_GUARANTEE_BELOW_MINIMUM`."
    PRD §3.3: "A new proposal is `SUBMITTED`, with `revision_round` at 0, `evaluation_count` at 0 and `composite_score` null."

    Design: Difficulty/boundary_precision_check/proposal_at_exact_minimum_franchise_fee_is_responsive
    """
    ctx = _solicitation_with_two_offerors(api)

    response = api.create_proposal(
        F.proposal_payload(
            ctx["prospectus_id"], ctx["offeror_id"], offered_franchise_fee_pct=4.00
        ),
        ctx["offeror_headers"],
    )
    validate_success(response, 201)
    proposal = get_success_data(response)

    assert_pct_equals(
        proposal["offered_franchise_fee_pct"], "4.00", "offered_franchise_fee_pct"
    )
    assert_status(proposal, "SUBMITTED")
    assert proposal["revision_round"] == 0, proposal["revision_round"]
    assert proposal["evaluation_count"] == 0, proposal["evaluation_count"]
    assert_null(proposal, "composite_score")


def test_offer_one_hundredth_below_the_minimum_is_refused(api):
    """PRD §3.3: "Only then are the two fiscal floors applied: `offered_franchise_fee_pct` must be at least `minimum_franchise_fee_pct`, with equality passing — a proposal offering exactly the minimum is responsive — else `ERR_FEE_BELOW_MINIMUM`; and `proposed_annual_guarantee_cents` must be at least `minimum_annual_guarantee_cents`, again with equality passing, else `ERR_GUARANTEE_BELOW_MINIMUM`."
    PRD §2.9: "42. `ERR_FEE_BELOW_MINIMUM` (HTTP 422) — on proposal submission and resubmission."

    Design: Difficulty/boundary_precision_check/proposal_at_exact_minimum_franchise_fee_is_responsive
    """
    ctx = _solicitation_with_two_offerors(api)
    X.submit_proposal(
        api, ctx["prospectus_id"], ctx["offeror_id"], offered_franchise_fee_pct=4.00
    )

    response = api.create_proposal(
        F.proposal_payload(
            ctx["prospectus_id"],
            ctx["offeror_b_id"],
            offered_franchise_fee_pct=3.99,
            experience_years=9,
            financial_capacity_ratio=1.40,
        ),
        ctx["offeror_b_headers"],
    )
    validate_error(response, ApiErrorId.ERR_FEE_BELOW_MINIMUM.value, 422)

    _rows, meta = validate_paginated(
        api.list_proposals(
            X.specialist_headers(), {"prospectus_id": ctx["prospectus_id"]}
        )
    )
    assert meta["total_count"] == 1, meta


def _two_audits_in_fieldwork(api):
    """Three accepted months, then two engagements frozen on different windows:
    one covering all three months (120,000,000), one covering the first two
    (80,000,000)."""
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    report_ids = []
    for period in MONTHS:
        report = X.file_report(
            api, ctx["lease_id"], ctx["offeror_id"], **dict(period, **MONTHLY_RECEIPTS)
        )
        X.accept_report(api, report["id"], 2150000)
        report_ids.append(report["id"])

    audit_a = X.open_audit(
        api,
        ctx["lease_id"],
        audit_period_start="2027-04-01",
        audit_period_end="2027-07-01",
        scope_note="Full-season point-of-sale reconciliation.",
    )
    X.begin_fieldwork(api, audit_a["id"])
    audit_b = X.open_audit(
        api,
        ctx["lease_id"],
        audit_period_start="2027-04-01",
        audit_period_end="2027-06-01",
        scope_note="Spring sample of lodging folios.",
    )
    X.begin_fieldwork(api, audit_b["id"])
    ctx.update(
        {"report_ids": report_ids, "audit_a_id": audit_a["id"], "audit_b_id": audit_b["id"]}
    )
    return ctx


def test_underreport_pct_at_exactly_five_percent_sets_the_penalty_flag(api):
    """PRD §3.8: "`penalty_applies` is true when `underreport_pct` is at or above five percent; five percent exactly does trigger it."
    PRD §3.8: "Beginning fieldwork moves it `OPENED → FIELDWORK` and freezes the baseline: `reported_gross_receipts_cents` becomes the sum of `total_receipts_cents` over the lease's `ACCEPTED` reports whose half-open periods lie inside the audit window."

    Design: Difficulty/boundary_precision_check/underreport_pct_at_exact_threshold_triggers_penalty_flag
    """
    ctx = _two_audits_in_fieldwork(api)

    response = api.issue_findings(
        ctx["audit_a_id"],
        F.issue_findings_payload(
            126000000,
            finding_note="Unrecorded folios equal to exactly five percent of reported receipts.",
        ),
        X.auditor_headers(),
    )
    validate_success(response, 200)
    audit = get_success_data(response)

    assert_cents_equals(
        audit["reported_gross_receipts_cents"], 120000000, "reported_gross_receipts_cents"
    )
    assert_pct_equals(audit["underreport_pct"], "5.00", "underreport_pct")
    assert audit["penalty_applies"] is True
    assert_status(audit, "FINDINGS_ISSUED")


def test_underreport_pct_just_under_five_percent_leaves_the_flag_clear(api):
    """PRD §3.8: "`underreport_pct` is zero when the frozen reported figure is zero; otherwise it is the adjusted figure less the reported figure, multiplied by one hundred, divided by the reported figure, and rounded half up to two decimal places — so an adjustment upward yields a positive percentage and one downward a negative percentage."
    PRD §3.8: "Nothing is restated at this stage."

    Design: Difficulty/boundary_precision_check/underreport_pct_at_exact_threshold_triggers_penalty_flag
    """
    ctx = _two_audits_in_fieldwork(api)

    response = api.issue_findings(
        ctx["audit_b_id"],
        F.issue_findings_payload(
            83920000, finding_note="Spring sample variance just under the penalty threshold."
        ),
        X.auditor_headers(),
    )
    validate_success(response, 200)
    audit = get_success_data(response)

    assert_cents_equals(
        audit["reported_gross_receipts_cents"], 80000000, "reported_gross_receipts_cents"
    )
    assert_pct_equals(audit["underreport_pct"], "4.90", "underreport_pct")
    assert audit["penalty_applies"] is False
    assert_status(audit, "FINDINGS_ISSUED")

    assert_status(
        get_success_data(api.get_report(ctx["report_ids"][0], X.award_officer_headers())),
        "ACCEPTED",
    )
    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 0, "outstanding_fee_balance_cents"
    )
