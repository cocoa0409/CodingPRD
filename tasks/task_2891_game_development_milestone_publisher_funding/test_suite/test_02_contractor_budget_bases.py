"""The two contractor-budget bases — committed and incurred — and the exact
headroom an engagement cancellation gives back."""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_CONTRACTOR_BUDGET_EXCEEDED
from test_helpers.assertions import assert_budget_summary, assert_fields_equal
from test_helpers.fixtures import (
    approve_invoice,
    create_engagement,
    setup_single_alpha,
    submit_invoice,
)
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success


def _outsourced_alpha(api, title, budget):
    return setup_single_alpha(api, title=title, contractor_budget_cents=budget)


def test_committed_basis_counts_the_whole_commitment_of_every_live_engagement(api):
    """PRD §3.8: "A milestone's committed basis is the sum of `committed_cents`
    over every engagement of that milestone whose `status` is `PROPOSED`, `ACTIVE`,
    `SUSPENDED` or `COMPLETED` — a forward-looking figure that counts the full
    commitment of each live engagement whether or not a single invoice has ever been
    approved against it."

    Design: Difficulty/dual_variant_calc/contractor_budget_committed_basis_vs_incurred_basis
    """
    scenario = _outsourced_alpha(api, "Rift Runner", 800000)
    reg = scenario.reg
    milestone_id = scenario.m1["id"]

    engagement = create_engagement(
        reg, milestone_id, "VFX-ORBIT", 800000, "2026-08-05", "2026-09-30"
    )
    assert engagement["status"] == "ACTIVE"

    summary = validate_success(api.get_budget_summary(milestone_id, reg.dev))
    assert_budget_summary(
        summary, milestone_id,
        budget=800000, committed_basis=800000, incurred_basis=0,
        available_committed=0, overrun=0,
    )


def test_incurred_basis_sums_approved_invoices_and_reports_the_overrun(api):
    """PRD §3.8: "The complementary figure is the **incurred basis**: the sum of
    `amount_cents` over every invoice in `APPROVED` status whose engagement belongs
    to the milestone, computed without regard to the engagement's own status" — and
    "an `overrun_cents` that is the incurred basis less the budget, likewise floored
    at zero."

    Design: Difficulty/dual_variant_calc/contractor_budget_committed_basis_vs_incurred_basis
    """
    scenario = _outsourced_alpha(api, "Rift Runner", 800000)
    reg = scenario.reg
    milestone_id = scenario.m1["id"]

    engagement = create_engagement(
        reg, milestone_id, "VFX-ORBIT", 800000, "2026-08-05", "2026-09-30"
    )
    first = submit_invoice(reg, engagement["id"], "ORB-001", 600000, "2026-08-31")
    second = submit_invoice(reg, engagement["id"], "ORB-002", 400000, "2026-09-30")
    assert approve_invoice(reg, first["id"])["status"] == "APPROVED"
    assert approve_invoice(reg, second["id"])["status"] == "APPROVED"

    summary = validate_success(api.get_budget_summary(milestone_id, reg.dev))
    assert_budget_summary(
        summary, milestone_id,
        budget=800000, committed_basis=800000, incurred_basis=1000000,
        available_committed=0, overrun=200000,
    )

    engagement_now = validate_success(api.get_engagement(engagement["id"], reg.dev))
    assert_fields_equal(
        engagement_now,
        {"status": "ACTIVE", "approved_invoice_total_cents": 1000000, "committed_cents": 800000},
        "engagement",
    )


def test_cancelling_an_engagement_restores_the_budget_headroom_exactly(api):
    """PRD §3.8: cancelling "moves the engagement to `CANCELLED`, at which point it
    leaves the committed basis and restores the milestone's outsourcing headroom
    exactly."

    Design: Difficulty/compensating_invariant/engagement_cancel_returns_contractor_budget_headroom_exactly
    """
    scenario = _outsourced_alpha(api, "Ashvale", 800000)
    reg = scenario.reg
    milestone_id = scenario.m1["id"]

    create_engagement(reg, milestone_id, "FX-ALDER", 500000, "2026-08-05", "2026-09-05")
    second = create_engagement(
        reg, milestone_id, "QA-BIRCH", 300000, "2026-08-10", "2026-09-10"
    )
    assert_budget_summary(
        validate_success(api.get_budget_summary(milestone_id, reg.dev)), milestone_id,
        budget=800000, committed_basis=800000, incurred_basis=0,
        available_committed=0, overrun=0,
    )

    blocked = api.create_engagement(
        f.engagement_payload(milestone_id, "LOC-CEDAR", 300000, "2026-08-15", "2026-09-15"),
        reg.dev,
    )
    validate_error(blocked, ERR_CONTRACTOR_BUDGET_EXCEEDED, 422)

    cancelled = validate_success(
        api.cancel_engagement(second["id"], reg.dev, {"reason": "Vendor unavailable"})
    )
    assert_fields_equal(
        cancelled,
        {"status": "CANCELLED", "committed_cents": 300000},
        "cancelled engagement",
    )
    assert_budget_summary(
        validate_success(api.get_budget_summary(milestone_id, reg.dev)), milestone_id,
        budget=800000, committed_basis=500000, incurred_basis=0,
        available_committed=300000, overrun=0,
    )


def test_the_engagement_the_budget_blocked_is_admitted_after_the_cancellation(api):
    """PRD §3.8: "Admission requires that basis plus the new engagement's
    `committed_cents` to be no greater than the milestone's
    `contractor_budget_cents`; exceeding it is `ERR_CONTRACTOR_BUDGET_EXCEEDED`."

    Design: Difficulty/compensating_invariant/engagement_cancel_returns_contractor_budget_headroom_exactly
    """
    scenario = _outsourced_alpha(api, "Ashvale", 800000)
    reg = scenario.reg
    milestone_id = scenario.m1["id"]

    create_engagement(reg, milestone_id, "FX-ALDER", 500000, "2026-08-05", "2026-09-05")
    second = create_engagement(
        reg, milestone_id, "QA-BIRCH", 300000, "2026-08-10", "2026-09-10"
    )
    validate_error(
        api.create_engagement(
            f.engagement_payload(milestone_id, "LOC-CEDAR", 300000, "2026-08-15", "2026-09-15"),
            reg.dev,
        ),
        ERR_CONTRACTOR_BUDGET_EXCEEDED,
        422,
    )
    validate_success(api.cancel_engagement(second["id"], reg.dev, {}))

    retried = validate_success(
        api.create_engagement(
            f.engagement_payload(milestone_id, "LOC-CEDAR", 300000, "2026-08-15", "2026-09-15"),
            reg.dev,
        ),
        201,
    )
    assert_fields_equal(
        retried, {"status": "ACTIVE", "committed_cents": 300000}, "engagement"
    )
    assert_budget_summary(
        validate_success(api.get_budget_summary(milestone_id, reg.dev)), milestone_id,
        budget=800000, committed_basis=800000, incurred_basis=0,
        available_committed=0, overrun=0,
    )

    rows, meta = validate_paginated(
        api.list_engagements(reg.dev, {"milestone_id": milestone_id})
    )
    assert meta["total_count"] == 3, "the cancelled row is retained alongside the two live ones"
    assert len(rows) == 3
