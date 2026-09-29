"""States that are re-entered: the dam's regulatory cycle and the permit revision loop."""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    assert_cents,
    assert_instant,
)
from test_helpers import factories as f
from test_helpers.constants import (
    CATEGORY_SEEPAGE,
    DECISION_ISSUE,
    DECISION_RETURN,
    DEFICIENCY_CLOSED_VERIFIED,
    DEFICIENCY_ESCALATED,
    DELINQUENCY_CURRENT,
    DELINQUENCY_DELINQUENT,
    ENTRY_FEE_VOID,
    ENTRY_PAYMENT_RECEIVED,
    ENTRY_PERMIT_REVIEW_FEE,
    ORDER_DEFAULTED,
    ORDER_SATISFIED,
    ORDER_TYPE_COMPLIANCE,
    PERMIT_ISSUED,
    PERMIT_RETURNED_FOR_REVISION,
    PERMIT_SUBMITTED,
    PERMIT_TYPE_CONSTRUCTION,
    PERMIT_UNDER_ENGINEERING_REVIEW,
    REG_REGISTERED,
    REG_UNDER_ENFORCEMENT,
    SAFETY_CONDITIONALLY_SATISFACTORY,
    SEVERITY_SERIOUS,
    VERIFY_SATISFIED,
)


# ---------------------------------------------------------------------------
# REGISTERED -> UNDER_ENFORCEMENT -> REGISTERED
# ---------------------------------------------------------------------------
@pytest.fixture()
def enforced_dam(program, base):
    """A dam driven under enforcement by a defaulted order, with the penalty settled."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    inspection = program.schedule_inspection(
        base.dam_id,
        base.engineer_a_id,
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T12:00:00Z",
    )
    program.set_clock("2026-08-05T13:00:00Z")
    program.submit_inspection(
        inspection["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T09:30:00Z",
        condition_rating=SAFETY_CONDITIONALLY_SATISFACTORY,
        narrative="Serviceable overall; one serious seepage defect noted.",
        deficiencies=[
            f.deficiency_item(
                category=CATEGORY_SEEPAGE,
                severity=SEVERITY_SERIOUS,
                description="Wet area with sediment transport at the downstream toe.",
            )
        ],
    )
    program.accept_inspection(inspection["id"], base.engineer_b_headers)
    deficiency = program.deficiencies_for(base.dam_id, severity=SEVERITY_SERIOUS)[0]
    order1 = program.issue_order(
        deficiency["id"],
        order_type=ORDER_TYPE_COMPLIANCE,
        requested_response_days=33,
    )
    program.set_clock("2026-09-17T13:00:00Z")
    program.sweep()
    return {"deficiency": deficiency, "order1": order1}


def test_the_dam_re_enters_registered_once_the_penalty_and_the_defect_are_cleared(
    program, base, enforced_dam
):
    """The regulatory dimension makes a full cycle back into the state it started in.

    PRD 3.4: "If at that point no deficiency on the dam remains in `ESCALATED` **and** the owner's `delinquency_status` is `CURRENT` — meaning the assessed penalty has been settled through the fee ledger — the dam's regulatory posture cycles back `UNDER_ENFORCEMENT → REGISTERED` and the dam's `version` increments for that move as well."

    Design: Difficulty/non_linear_state_machine/dam_regulatory_status_cycles_back_to_registered_while_safety_status_holds
    """
    under_enforcement = program.get_dam(base.dam_id)
    assert under_enforcement["regulatory_status"] == REG_UNDER_ENFORCEMENT
    owner = program.get_owner(base.owner_id)
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT
    assert_cents(owner["fee_balance_cents"], 163282, "fee_balance_cents")

    program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-163282,
        memo="Penalty settled in full by wire.",
    )
    order2 = program.issue_order(
        enforced_dam["deficiency"]["id"],
        order_type=ORDER_TYPE_COMPLIANCE,
        requested_response_days=33,
    )
    program.file_order_response(
        order2["id"], base.owner_id, completed_at="2026-09-17T12:00:00Z"
    )
    verified = program.verify_order(
        order2["id"], base.engineer_b_id, outcome=VERIFY_SATISFIED
    )
    assert verified["status"] == ORDER_SATISFIED
    assert verified["verified_by_user_id"] == base.engineer_b_id

    dam = program.get_dam(base.dam_id)
    assert dam["regulatory_status"] == REG_REGISTERED
    assert dam["open_deficiency_count"] == 0
    settled = program.get_owner(base.owner_id)
    assert_cents(settled["fee_balance_cents"], 0, "fee_balance_cents")
    assert settled["delinquency_status"] == DELINQUENCY_CURRENT


def test_the_safety_dimension_never_moves_with_the_regulatory_dimension(
    program, base, enforced_dam
):
    """Enforcement and remediation leave the condition rating exactly where it was.

    PRD 2.9: "No transition on the safety dimension ever touches the regulatory dimension, and no transition on the regulatory dimension ever touches the safety dimension; an operation that legitimately writes both does so through two separately specified rules."

    Design: Difficulty/non_linear_state_machine/dam_regulatory_status_cycles_back_to_registered_while_safety_status_holds
    """
    assert program.get_dam(base.dam_id)["safety_status"] == (
        SAFETY_CONDITIONALLY_SATISFACTORY
    )

    program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-163282,
        memo="Penalty settled in full by wire.",
    )
    order2 = program.issue_order(
        enforced_dam["deficiency"]["id"],
        order_type=ORDER_TYPE_COMPLIANCE,
        requested_response_days=33,
    )
    program.file_order_response(
        order2["id"], base.owner_id, completed_at="2026-09-17T12:00:00Z"
    )
    program.verify_order(order2["id"], base.engineer_b_id, outcome=VERIFY_SATISFIED)

    dam = program.get_dam(base.dam_id)
    assert dam["regulatory_status"] == REG_REGISTERED
    assert dam["safety_status"] == SAFETY_CONDITIONALLY_SATISFACTORY

    summary = program.summary(base.dam_id)
    assert summary["escalated_deficiency_count"] == 0
    # The defaulted first order keeps its assessed figure in the dam's total.
    assert_cents(
        summary["outstanding_penalty_cents"], 163282, "outstanding_penalty_cents"
    )


def test_the_deficiency_takes_the_escalated_back_to_ordered_edge(
    program, base, enforced_dam
):
    """A second order on an escalated defect drives it backwards into ORDERED.

    PRD 3.4: "Where a deficiency has been escalated by a default and staff wish to compel it again, a further order may be issued on it, moving it `ESCALATED → ORDERED`; `remediation_due_at` is replaced by the new order's `compliance_deadline_at` and `order_count` rises again."

    Design: Difficulty/non_linear_state_machine/dam_regulatory_status_cycles_back_to_registered_while_safety_status_holds
    """
    deficiency_id = enforced_dam["deficiency"]["id"]
    escalated = program.deficiencies_for(base.dam_id)[0]
    assert escalated["status"] == DEFICIENCY_ESCALATED
    assert escalated["order_count"] == 1
    assert program.get_order(enforced_dam["order1"]["id"])["status"] == ORDER_DEFAULTED

    program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-163282,
        memo="Penalty settled in full by wire.",
    )
    order2 = program.issue_order(
        deficiency_id,
        order_type=ORDER_TYPE_COMPLIANCE,
        requested_response_days=33,
    )
    program.file_order_response(
        order2["id"], base.owner_id, completed_at="2026-09-17T12:00:00Z"
    )
    program.verify_order(order2["id"], base.engineer_b_id, outcome=VERIFY_SATISFIED)

    closed = program.deficiencies_for(base.dam_id)[0]
    assert closed["status"] == DEFICIENCY_CLOSED_VERIFIED
    assert closed["order_count"] == 2
    assert_instant(closed["closed_at"], "2026-09-17T13:00:00Z", "closed_at")


# ---------------------------------------------------------------------------
# SUBMITTED -> UNDER_ENGINEERING_REVIEW -> RETURNED_FOR_REVISION -> SUBMITTED
# ---------------------------------------------------------------------------
@pytest.fixture()
def returned_permit(program, base):
    """A 40,000,000-cent CONSTRUCTION application returned for revision."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    permit = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_CONSTRUCTION,
        scope_description="New outlet works and stilling basin.",
        estimated_project_cost_cents=40_000_000,
    )
    # PRD 2.5 rung 35 guards the decision itself, not just an issuance, so the
    # 430,000-cent intake fee this very application posted has to be settled
    # before any RETURN decision can be taken on it.
    program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-430_000,
        memo="Construction application fee paid at intake.",
    )
    program.assign_permit_review(permit["id"], base.engineer_a_id)
    returned = program.decide_permit(
        permit["id"],
        base.engineer_a_id,
        decision=DECISION_RETURN,
        findings="Stilling basin hydraulics not demonstrated for the PMF.",
    )
    return returned


def test_a_returned_application_re_enters_submitted_and_loses_its_reviewer(
    program, base, returned_permit
):
    """The permit returns to its own initial state and must be assigned afresh.

    PRD 3.6: "Resubmission overwrites `scope_description` and `estimated_project_cost_cents`, increments `revision_count` by 1, and clears `review_engineer_id` back to null so the application must be assigned afresh — and that clearing is what lets a returned permit be reassigned to a different reviewer."

    Design: Difficulty/non_linear_state_machine/permit_returns_to_submitted_and_reprices_on_the_revision_cycle
    """
    assert returned_permit["status"] == PERMIT_RETURNED_FOR_REVISION
    assert_cents(returned_permit["total_fee_cents"], 430000, "total_fee_cents")

    resubmitted = program.api.resubmit_permit(
        returned_permit["id"],
        f.permit_resubmit_payload(
            scope_description="Outlet works only; stilling basin deferred to a later application.",
            estimated_project_cost_cents=8_000_000,
        ),
        base.owner_headers,
    )
    revised = validate_success(resubmitted)
    assert revised["status"] == PERMIT_SUBMITTED
    assert revised["revision_count"] == 1
    assert revised["review_engineer_id"] is None


def test_resubmission_reprices_the_schedule_and_posts_only_the_difference(
    program, base, returned_permit
):
    """A cheaper revision appends a negative FEE_VOID delta, not a new charge.

    PRD 3.6: "The full five-movement fee schedule is then re-evaluated on the revised cost and the dam's current hazard class, and only the **difference** between the new `total_fee_cents` and the previously posted total is appended to the ledger: a positive difference as a `PERMIT_REVIEW_FEE` entry, a negative difference as a `FEE_VOID` entry, and a difference of exactly zero appending nothing at all."

    Design: Difficulty/non_linear_state_machine/permit_returns_to_submitted_and_reprices_on_the_revision_cycle
    """
    revised = validate_success(
        program.api.resubmit_permit(
            returned_permit["id"],
            f.permit_resubmit_payload(
                scope_description="Outlet works only; stilling basin deferred to a later application.",
                estimated_project_cost_cents=8_000_000,
            ),
            base.owner_headers,
        )
    )
    assert_cents(revised["base_fee_cents"], 100000, "base_fee_cents")
    # 8,000,000 x 0.75 percent x the SIGNIFICANT uplift of 1.10.
    assert_cents(
        revised["engineering_review_fee_cents"], 66000, "engineering_review_fee_cents"
    )
    # The intake fee was settled, so the owner is CURRENT and pays no surcharge.
    assert_cents(
        revised["delinquency_surcharge_cents"], 0, "delinquency_surcharge_cents"
    )
    assert_cents(revised["volume_credit_cents"], 0, "volume_credit_cents")
    assert_cents(revised["total_fee_cents"], 166000, "total_fee_cents")

    rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 3
    assert rows[0]["entry_type"] == ENTRY_PERMIT_REVIEW_FEE
    assert_cents(rows[0]["amount_cents"], 430000, "amount_cents")
    assert rows[0]["sequence_no"] == 1
    assert_cents(rows[0]["balance_after_cents"], 430000, "balance_after_cents")
    assert rows[1]["entry_type"] == ENTRY_PAYMENT_RECEIVED
    assert_cents(rows[1]["amount_cents"], -430000, "amount_cents")
    assert rows[1]["sequence_no"] == 2
    assert_cents(rows[1]["balance_after_cents"], 0, "balance_after_cents")
    # Only the difference between the new and the previously posted total is appended.
    assert rows[2]["entry_type"] == ENTRY_FEE_VOID
    assert_cents(rows[2]["amount_cents"], -264000, "amount_cents")
    assert rows[2]["sequence_no"] == 3
    assert_cents(rows[2]["balance_after_cents"], -264000, "balance_after_cents")


def test_the_repriced_permit_can_be_reassigned_and_issued(
    program, base, returned_permit
):
    """Issuance of a construction permit leaves the dam's regulatory posture alone.

    PRD 3.6: "When the `permit_type` is `REMOVAL`, issuance also moves the dam `REGISTERED → REMOVAL_PERMITTED` on the regulatory dimension and increments the dam's `version` by 1 — the state has authorised the structure's removal, and from that point no new consequence assessment or construction permit may be filed against it."

    Design: Difficulty/non_linear_state_machine/permit_returns_to_submitted_and_reprices_on_the_revision_cycle
    """
    validate_success(
        program.api.resubmit_permit(
            returned_permit["id"],
            f.permit_resubmit_payload(
                scope_description="Outlet works only; stilling basin deferred to a later application.",
                estimated_project_cost_cents=8_000_000,
            ),
            base.owner_headers,
        )
    )
    assigned = program.assign_permit_review(returned_permit["id"], base.engineer_a_id)
    assert assigned["status"] == PERMIT_UNDER_ENGINEERING_REVIEW
    assert assigned["review_engineer_id"] == base.engineer_a_id

    issued = program.decide_permit(
        returned_permit["id"],
        base.engineer_a_id,
        decision=DECISION_ISSUE,
        findings="Outlet works design conforms to the state dam safety standard.",
        conditions="As-built drawings due within 90 days of completion.",
    )
    assert issued["status"] == PERMIT_ISSUED
    assert_instant(issued["issued_at"], "2026-08-01T00:00:00Z", "issued_at")
    assert issued["revision_count"] == 1
    assert_cents(issued["total_fee_cents"], 166000, "total_fee_cents")

    assert program.get_dam(base.dam_id)["regulatory_status"] == REG_REGISTERED
    owner = program.get_owner(base.owner_id)
    # The void of the cheaper revision leaves a credit with the state, which is CURRENT.
    assert_cents(owner["fee_balance_cents"], -264000, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_CURRENT
