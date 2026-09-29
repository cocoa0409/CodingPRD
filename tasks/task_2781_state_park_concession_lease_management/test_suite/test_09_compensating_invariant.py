"""Compensating operations that must restore a conserved quantity exactly: the
bond's penal-sum identity across a draw and a full reinstatement, and the
lease's fee ledger across an audit restatement and its withdrawal."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_lease_state,
    assert_null,
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


def _partially_drawn_bond(api):
    """An officer-issued operating-standard notice whose cure period lapsed, then
    a 1,000,000 draw that leaves the bond above its sufficiency floor."""
    ctx = X.setup_active_lease(api)
    action = X.issue_compliance_action(
        api,
        ctx["lease_id"],
        X.exec_officer_headers(),
        action_type="OPERATING_STANDARD",
        deficiency_note="Posted lodging rates exceeded the approved schedule during spring weekends.",
        cure_deadline="2027-03-04T00:00:00Z",
    )
    X.set_clock(api, "2027-03-05T00:00:00Z")
    X.order_bond_draw(api, action["id"], 1000000, X.exec_officer_headers())
    bond = get_success_data(api.get_bond(ctx["bond_id"], X.exec_officer_headers()))
    assert_status(bond, "PARTIALLY_DRAWN")
    ctx.update({"action_id": action["id"]})
    return ctx


def _finalized_audit(api):
    """The canonical lease year: three accepted months worth 120,000,000, a
    1,300,000 reconciliation, and a finalized audit that restates the window to
    132,000,000 and mints a 2,486,000 replacement invoice."""
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
    X.finalize_audit(api, audit["id"])
    ctx.update({"report_ids": report_ids, "recon_id": recon["id"], "audit_id": audit["id"]})
    return ctx


def _audit_minted_reconciliation(api, lease_id, audit_id):
    rows, _meta = validate_paginated(
        api.list_reconciliations(
            X.award_officer_headers(), {"lease_id": lease_id, "audit_engagement_id": audit_id}
        )
    )
    assert len(rows) == 1, f"expected one audit-minted reconciliation, got {len(rows)}"
    return rows[0]


def test_full_reinstatement_restores_the_bond_balance_identity(api):
    """PRD §3.9: "The surety can restore drawn capacity. A reinstatement names a `reinstatement_amount_cents` that must be strictly positive and no greater than the bond's current `drawn_total_cents`, else `ERR_REINSTATEMENT_EXCEEDS_DRAWN`."
    PRD §3.9: "`available_balance_cents` rises and `drawn_total_cents` falls by that amount, `penal_sum_cents` again untouched."
    PRD §3.9: "A **full** reinstatement — one whose amount equals `drawn_total_cents`, bringing it to zero — returns the bond to `ACTIVE` from either `PARTIALLY_DRAWN` or `INSUFFICIENT`; a **partial** one leaves the bond in `PARTIALLY_DRAWN` as a self-loop."
    PRD §3.9: "**Hop two** moves the money on the bond: `available_balance_cents` falls by the drawn amount and `drawn_total_cents` rises by the same amount, while `penal_sum_cents` never changes — the penal sum is the face value of the instrument, not a running balance."

    Design: Difficulty/compensating_invariant/bond_penal_sum_conserved_across_draw_then_full_reinstatement
    """
    ctx = _partially_drawn_bond(api)

    response = api.reinstate_bond(
        ctx["bond_id"],
        F.reinstate_bond_payload(1000000),
        X.concessionaire_headers(ctx["offeror_id"]),
    )
    validate_success(response, 200)
    bond = get_success_data(response)

    assert_status(bond, "ACTIVE")
    assert_cents_equals(bond["available_balance_cents"], 3000000, "available_balance_cents")
    assert_cents_equals(bond["drawn_total_cents"], 0, "drawn_total_cents")
    assert_cents_equals(bond["penal_sum_cents"], 3000000, "penal_sum_cents")
    assert_cents_equals(bond["required_amount_cents"], 3000000, "required_amount_cents")
    assert bond["available_balance_cents"] + bond["drawn_total_cents"] == bond[
        "penal_sum_cents"
    ], (
        "the balance and the drawn total must always add back to the penal sum, got "
        f"{bond['available_balance_cents']} + {bond['drawn_total_cents']} vs "
        f"{bond['penal_sum_cents']}"
    )


def test_restoring_the_bond_leaves_the_notice_and_the_deficiency_standing(api):
    """PRD §3.9: "Critically, restoring the bond does not restore the lease: a lease already in `DEFAULT` and `TERMINATED_DEFAULT` stays there, both dimensions unchanged, no matter how completely the bond is made whole."
    PRD §3.9: "**Hop one** persists `draw_amount_cents` on the action."
    PRD §3.9: "When the officer accepts a cure, moving the action `NOTICE_ISSUED → CURE_ACCEPTED` and persisting a `cure_note`, the lease returns `DEFICIENT → COMPLIANT` only if no other compliance action on that lease is still in `NOTICE_ISSUED`; if one is, the action closes but the lease stays deficient and its `version` does not move."
    PRD §3.9: "Note also what deficiency does *not* do: a `DEFICIENT` lease is still `ACTIVE`, so it may still file reports, submit operating plans, propose improvements and be reconciled."

    Design: Difficulty/compensating_invariant/bond_penal_sum_conserved_across_draw_then_full_reinstatement
    """
    ctx = _partially_drawn_bond(api)

    validate_success(
        api.reinstate_bond(
            ctx["bond_id"],
            F.reinstate_bond_payload(1000000),
            X.concessionaire_headers(ctx["offeror_id"]),
        ),
        200,
    )

    action = get_success_data(
        api.get_compliance_action(ctx["action_id"], X.exec_officer_headers())
    )
    assert_status(action, "BOND_DRAW_ORDERED")
    assert_cents_equals(action["draw_amount_cents"], 1000000, "draw_amount_cents")

    lease = get_success_data(api.get_lease(ctx["lease_id"], X.exec_officer_headers()))
    assert_lease_state(lease, contract_status="ACTIVE", compliance_status="DEFICIENT")
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 0, "outstanding_fee_balance_cents"
    )


def test_withdrawing_findings_unwinds_the_restatement_in_reverse_order(api):
    """PRD §3.8: "An auditor may withdraw final findings, moving `FINAL → WITHDRAWN`, provided the reconciliation the audit minted is still `PENDING_PAYMENT`; once the concessionaire has paid it, the findings are locked and the attempt fails with `ERR_AUDIT_ALREADY_SETTLED`."
    PRD §3.8: "The reconciliation the audit minted moves `PENDING_PAYMENT → VOIDED`."
    PRD §3.8: "The reconciliation it had superseded moves `SUPERSEDED → PENDING_PAYMENT` with its `superseded_by_id` reset to null, so the original invoice is live again."
    PRD §3.8: "Every `RESTATED` report inside the audit window returns to `ACCEPTED` with `restated_receipts_cents` reset to null."

    Design: Difficulty/compensating_invariant/lease_fee_ledger_conserved_when_audit_findings_are_withdrawn
    """
    ctx = _finalized_audit(api)
    replacement_id = _audit_minted_reconciliation(api, ctx["lease_id"], ctx["audit_id"])["id"]

    response = api.withdraw_findings(
        ctx["audit_id"],
        F.withdraw_findings_payload(
            withdrawal_basis=(
                "Point-of-sale extract double-counted transfers between the lodge "
                "and marina tills."
            )
        ),
        X.auditor_headers(),
    )
    validate_success(response, 200)
    assert_status(get_success_data(response), "WITHDRAWN")

    for report_id in ctx["report_ids"]:
        report = get_success_data(api.get_report(report_id, X.award_officer_headers()))
        assert_status(report, "ACCEPTED")
        assert_null(report, "restated_receipts_cents")

    original = get_success_data(
        api.get_reconciliation(ctx["recon_id"], X.award_officer_headers())
    )
    assert_status(original, "PENDING_PAYMENT")
    assert_null(original, "superseded_by_id")
    assert_cents_equals(
        original["annual_gross_receipts_cents"], 120000000, "annual_gross_receipts_cents"
    )
    assert_cents_equals(original["annual_fee_due_cents"], 7750000, "annual_fee_due_cents")
    assert_cents_equals(
        original["additional_fee_due_cents"], 1300000, "additional_fee_due_cents"
    )

    voided = get_success_data(
        api.get_reconciliation(replacement_id, X.award_officer_headers())
    )
    assert_status(voided, "VOIDED")


def test_withdrawal_returns_the_lease_ledger_to_its_pre_audit_figure(api):
    """PRD §3.8: "Every compliance action whose `origin` is `SYSTEM_ISSUED`, whose status is still `NOTICE_ISSUED` and whose `reconciliation_id` points at the voided row moves to `RESCINDED`."
    PRD §3.8: "The lease's `outstanding_fee_balance_cents` is recomputed, and its `compliance_status` returns `DEFICIENT → COMPLIANT` — but only when no compliance action on that lease remains in `NOTICE_ISSUED`; an officer-issued notice for an unrelated deficiency keeps the lease deficient."
    PRD §3.8: "The lease's `outstanding_fee_balance_cents` — the sum of `additional_fee_due_cents` over the lease's reconciliations still in `PENDING_PAYMENT` — is recomputed, and the lease's `version` advances by one."
    PRD §3.8: "The supplied `withdrawal_basis` is persisted and every affected row advances its `version` by one."

    Design: Difficulty/compensating_invariant/lease_fee_ledger_conserved_when_audit_findings_are_withdrawn
    """
    ctx = _finalized_audit(api)

    validate_success(
        api.withdraw_findings(
            ctx["audit_id"],
            F.withdraw_findings_payload(
                withdrawal_basis=(
                    "Point-of-sale extract double-counted transfers between the lodge "
                    "and marina tills."
                )
            ),
            X.auditor_headers(),
        ),
        200,
    )

    lease = get_success_data(api.get_lease(ctx["lease_id"], X.exec_officer_headers()))
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 1300000, "outstanding_fee_balance_cents"
    )
    assert_lease_state(lease, contract_status="ACTIVE", compliance_status="COMPLIANT")

    actions, _meta = validate_paginated(
        api.list_compliance_actions(X.exec_officer_headers(), {"lease_id": ctx["lease_id"]})
    )
    system_issued = [row for row in actions if row.get("origin") == "SYSTEM_ISSUED"]
    assert len(system_issued) == 1, (
        f"expected one system-issued notice on the lease, got {len(system_issued)}"
    )
    assert_status(system_issued[0], "RESCINDED")
    assert not [row for row in actions if row.get("status") == "NOTICE_ISSUED"], (
        "no compliance action on the lease may remain in NOTICE_ISSUED after withdrawal"
    )
