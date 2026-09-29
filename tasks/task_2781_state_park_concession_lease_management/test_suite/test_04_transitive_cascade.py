"""Depth-four cascades: audit finalization through to a system notice, and a
bond draw through to default and asset unwind."""
from prd_bench_local_runner.testing import get_success_data, validate_paginated, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_lease_state,
    assert_pct_equals,
    assert_status,
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


def _audit_findings_issued(api):
    """Three accepted months, a year-1 reconciliation of 1,300,000 and an audit
    holding findings that lift the window's receipts from 120m to 132m."""
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    report_ids = []
    for period in MONTHS:
        report = X.file_report(
            api, ctx["lease_id"], ctx["offeror_id"], **dict(period, **MONTHLY_RECEIPTS)
        )
        X.accept_report(api, report["id"], 2150000)
        report_ids.append(report["id"])

    X.set_clock(api, "2028-03-05T00:00:00Z")
    recon = X.create_reconciliation(
        api, ctx["lease_id"], lease_year_start="2027-03-01", lease_year_end="2028-02-29"
    )

    audit = X.open_audit(
        api,
        ctx["lease_id"],
        audit_period_start="2027-04-01",
        audit_period_end="2027-07-01",
        scope_note="Point-of-sale reconciliation for the 2027 lodging season.",
    )
    X.begin_fieldwork(api, audit["id"])
    X.issue_findings(
        api,
        audit["id"],
        132000000,
        finding_note="Unrecorded lodging folios and marina slip rentals.",
    )
    X.set_clock(api, "2028-06-30T00:00:00Z")
    ctx.update({"report_ids": report_ids, "recon_id": recon["id"], "audit_id": audit["id"]})
    return ctx


def _replacement_reconciliation(api, lease_id, audit_id):
    response = api.list_reconciliations(
        X.award_officer_headers(), {"lease_id": lease_id, "audit_engagement_id": audit_id}
    )
    rows, _meta = validate_paginated(response)
    assert len(rows) == 1, f"expected one audit-minted reconciliation, got {len(rows)}"
    return rows[0]


def test_audit_finalize_restates_reports_and_mints_the_replacement_invoice(api):
    """PRD §3.8: "**Hop one:** every `ACCEPTED` report whose half-open period lies inside the audit window moves `ACCEPTED → RESTATED` and receives its share of the adjusted total as `restated_receipts_cents`."
    PRD §3.8: "The allocation is proportional and exact: taking the covered reports in order of `period_start` ascending then `created_at` ascending, every report except the last gets the adjusted total multiplied by that report's own `total_receipts_cents`, divided by the frozen reported total, rounded half up to whole cents; the last report in that order absorbs whatever remains, so that the restated figures sum to `adjusted_gross_receipts_cents` exactly."
    PRD §3.8: "**Hop two:** because those periods have been restated, the lease year's `PENDING_PAYMENT` reconciliation moves to `SUPERSEDED` and a replacement is minted, carrying `audit_engagement_id` pointing at this audit and `annual_gross_receipts_cents` equal to the adjusted figure, re-run through the same tier ladder, guarantee floor and remittance comparison as any other reconciliation."
    PRD §3.8: "`penalty_cents` is ten percent of the replacement row's own `base_delta_cents`, rounded half up, but only when `penalty_applies` is true and that delta is strictly positive; otherwise it is zero."
    PRD §3.8: "`interest_cents` is simple interest at one percent per month: the replacement row's `base_delta_cents` multiplied by one percent and then by the number of whole calendar months from the superseded reconciliation's `due_date` to the logical clock's date, rounded half up — that month count is zero when the clock is at or before the old `due_date`, and the interest is zero whenever the delta is not strictly positive."

    Design: Difficulty/transitive_cascade/audit_finalize_cascades_restatement_reconciliation_balance_and_notice
    """
    ctx = _audit_findings_issued(api)

    response = api.finalize_audit(ctx["audit_id"], X.auditor_headers())
    validate_success(response, 200)
    audit = get_success_data(response)
    assert_status(audit, "FINAL")
    assert_cents_equals(
        audit["reported_gross_receipts_cents"], 120000000, "reported_gross_receipts_cents"
    )
    assert_cents_equals(
        audit["adjusted_gross_receipts_cents"], 132000000, "adjusted_gross_receipts_cents"
    )
    assert_pct_equals(audit["underreport_pct"], "10.00", "underreport_pct")
    assert audit["penalty_applies"] is True

    for report_id in ctx["report_ids"]:
        report = get_success_data(api.get_report(report_id, X.award_officer_headers()))
        assert_status(report, "RESTATED")
        assert_cents_equals(
            report["restated_receipts_cents"], 44000000, "restated_receipts_cents"
        )

    superseded = get_success_data(
        api.get_reconciliation(ctx["recon_id"], X.award_officer_headers())
    )
    assert_status(superseded, "SUPERSEDED")

    replacement = _replacement_reconciliation(api, ctx["lease_id"], ctx["audit_id"])
    assert superseded["superseded_by_id"] == replacement["id"]
    assert_cents_equals(
        replacement["annual_gross_receipts_cents"], 132000000, "annual_gross_receipts_cents"
    )
    assert_cents_equals(replacement["annual_fee_due_cents"], 8650000, "annual_fee_due_cents")
    assert_cents_equals(replacement["remitted_total_cents"], 6450000, "remitted_total_cents")
    assert_cents_equals(replacement["base_delta_cents"], 2200000, "base_delta_cents")
    assert_cents_equals(replacement["penalty_cents"], 220000, "penalty_cents")
    assert_cents_equals(replacement["interest_cents"], 66000, "interest_cents")
    assert_cents_equals(
        replacement["additional_fee_due_cents"], 2486000, "additional_fee_due_cents"
    )
    assert_status(replacement, "PENDING_PAYMENT")


def test_audit_finalize_balance_over_the_threshold_mints_a_system_notice(api):
    """PRD §3.8: "**Hop three:** because a new `PENDING_PAYMENT` row now exists, the lease's `outstanding_fee_balance_cents` is recomputed."
    PRD §3.8: "**Hop four:** because that recomputed balance exceeds twenty thousand dollars, the lease's `compliance_status` moves `COMPLIANT → DEFICIENT` and a compliance action is minted for it automatically, with `origin` `SYSTEM_ISSUED`, `action_type` `FEE_DELINQUENCY`, `reconciliation_id` pointing at the replacement row, and a `cure_deadline` thirty days after the logical clock."

    Design: Difficulty/transitive_cascade/audit_finalize_cascades_restatement_reconciliation_balance_and_notice
    """
    ctx = _audit_findings_issued(api)
    X.finalize_audit(api, ctx["audit_id"])

    replacement = _replacement_reconciliation(api, ctx["lease_id"], ctx["audit_id"])

    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 2486000, "outstanding_fee_balance_cents"
    )
    assert_lease_state(lease, contract_status="ACTIVE", compliance_status="DEFICIENT")

    rows, _meta = validate_paginated(
        api.list_compliance_actions(
            X.award_officer_headers(),
            {"lease_id": ctx["lease_id"], "origin": "SYSTEM_ISSUED"},
        )
    )
    assert len(rows) == 1, f"expected exactly one system notice, got {len(rows)}"
    notice = rows[0]
    assert_fields(
        notice,
        {
            "origin": "SYSTEM_ISSUED",
            "action_type": "FEE_DELINQUENCY",
            "status": "NOTICE_ISSUED",
            "reconciliation_id": replacement["id"],
            "cure_deadline": "2028-07-30T00:00:00Z",
        },
    )


def _lease_with_approved_improvement_and_ripe_notice(api):
    """An ACTIVE, DEFICIENT lease holding one APPROVED improvement and one
    notice whose cure period has already lapsed."""
    ctx = X.setup_lease_with_season(api)
    improvement = X.propose_improvement(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        description="Marina dock resurfacing",
        funding_source="CONCESSIONAIRE_CAPITAL",
        proposed_cost_cents=5000000,
        useful_life_years=15,
        construction_window_start="2027-04-01",
        construction_window_end="2027-06-16",
        ownership_at_expiration="AGENCY",
    )
    X.approve_improvement(api, improvement["id"], 5000000)
    action = X.issue_compliance_action(
        api,
        ctx["lease_id"],
        action_type="OPERATING_STANDARD",
        deficiency_note="Season service level not maintained at the approved FULL standard.",
        cure_deadline="2027-03-04T00:00:00Z",
    )
    X.set_clock(api, "2027-03-05T00:00:00Z")
    ctx.update({"improvement_id": improvement["id"], "action_id": action["id"]})
    return ctx


def test_bond_draw_below_the_sufficiency_floor_defaults_and_terminates_the_lease(api):
    """PRD §3.9: "**Hop one** persists `draw_amount_cents` on the action."
    PRD §3.9: "**Hop two** moves the money on the bond: `available_balance_cents` falls by the drawn amount and `drawn_total_cents` rises by the same amount, while `penal_sum_cents` never changes — the penal sum is the face value of the instrument, not a running balance."
    PRD §3.9: "Where the bond lands depends on a sufficiency floor: half of `required_amount_cents`, rounded half up to whole cents."
    PRD §3.9: "**Hop three** fires only on `INSUFFICIENT`: the lease's `compliance_status` moves `DEFICIENT → DEFAULT` and, at the same time, its `contract_status` moves from `ACTIVE` or `HOLDOVER` to `TERMINATED_DEFAULT`."

    Design: Difficulty/transitive_cascade/bond_draw_cascades_default_termination_and_asset_unwind
    """
    ctx = _lease_with_approved_improvement_and_ripe_notice(api)

    response = api.order_bond_draw(
        ctx["action_id"], F.order_bond_draw_payload(1600000), X.exec_officer_headers()
    )
    validate_success(response, 200)
    action = get_success_data(response)
    assert_status(action, "BOND_DRAW_ORDERED")
    assert_cents_equals(action["draw_amount_cents"], 1600000, "draw_amount_cents")

    bond = get_success_data(api.get_bond(ctx["bond_id"], X.award_officer_headers()))
    assert_cents_equals(bond["available_balance_cents"], 1400000, "available_balance_cents")
    assert_cents_equals(bond["drawn_total_cents"], 1600000, "drawn_total_cents")
    assert_cents_equals(bond["penal_sum_cents"], 3000000, "penal_sum_cents")
    assert_cents_equals(bond["required_amount_cents"], 3000000, "required_amount_cents")
    assert_status(bond, "INSUFFICIENT")

    lease = X.read_lease(api, ctx["lease_id"])
    assert_lease_state(
        lease, contract_status="TERMINATED_DEFAULT", compliance_status="DEFAULT"
    )


def test_bond_draw_default_unwinds_live_plans_improvements_and_park_slots(api):
    """PRD §3.9: "**Hop four** cleans up after the termination: every operating plan on the lease in `SUBMITTED`, `RETURNED` or `APPROVED` moves to `SUPERSEDED`, and every capital improvement in `PROPOSED`, `RETURNED` or `APPROVED` moves to `WITHDRAWN`, with the park's `open_closure_window_count` decremented once for each row that was `APPROVED` — the same closure-capacity bookkeeping as §3.7, now unwound in bulk."
    PRD §3.9: "Separately, and regardless of where the bond landed, if the action carries a `reconciliation_id` and `draw_amount_cents` exactly equals that reconciliation's `additional_fee_due_cents`, the draw is treated as payment: that reconciliation moves `PENDING_PAYMENT → SETTLED` and the lease's `outstanding_fee_balance_cents` is recomputed."

    Design: Difficulty/transitive_cascade/bond_draw_cascades_default_termination_and_asset_unwind
    """
    ctx = _lease_with_approved_improvement_and_ripe_notice(api)
    X.order_bond_draw(api, ctx["action_id"], 1600000, X.exec_officer_headers())

    plan = get_success_data(
        api.get_operating_plan(ctx["plan_id"], X.award_officer_headers())
    )
    assert_status(plan, "SUPERSEDED")

    improvement = get_success_data(
        api.get_improvement(ctx["improvement_id"], X.award_officer_headers())
    )
    assert_status(improvement, "WITHDRAWN")

    park = get_success_data(api.get_park(ctx["park_id"], X.award_officer_headers()))
    assert park["open_closure_window_count"] == 0, park["open_closure_window_count"]

    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 0, "outstanding_fee_balance_cents"
    )
    assert_cents_equals(
        lease["capital_investment_completed_cents"], 0, "capital_investment_completed_cents"
    )
