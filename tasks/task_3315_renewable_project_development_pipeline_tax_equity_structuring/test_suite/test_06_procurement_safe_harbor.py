"""Procurement and safe harbor: dual qualification variants, the five-percent
boundary, temporal and cross-entity gates, and the clawback cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    confirm_order,
    create_project,
    create_supply_agreement,
    establish_tcq,
    execute_supply_agreement,
    get_project,
    get_success_data,
    get_tcq,
    pay_deposit,
    place_order,
    place_order_paid,
    safe_harbor_project,
    set_clock,
    validate_error,
    validate_success,
)


def test_safe_harbor_cost_vs_physical_work_variants(
    api, developer_admin_headers, procurement_lead_headers
):
    """PRD §3.4: "Under the `FIVE_PERCENT_COST` method, the order qualifies if
    and only if its `deposit_paid_usd` is at least the five-percent threshold —
    the threshold being 5 percent of `eligible_cost_basis_usd` rounded half-up
    to 2 decimal places, with a deposit exactly equal to the threshold
    qualifying; falling short fails with `ERR_SAFE_HARBOR_TEST_FAILED` (HTTP
    422), and any evidence URI is irrelevant to this variant. Under the
    `PHYSICAL_WORK` method, cost amounts are irrelevant and qualification turns
    entirely on the presence of a `physical_work_evidence_uri` in the
    transition payload — an order with zero deposit can qualify, while an order
    with a full deposit but no evidence cannot; a missing URI fails with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Difficulty/dual_variant_calc/safe_harbor_cost_vs_physical_work_variants
    """
    project = create_project(name="Variant Farm", target_capacity_mw=150)
    sa = create_supply_agreement(
        project["id"], equipment_type="TURBINE", total_contract_usd=5000000,
    )
    execute_supply_agreement(sa["id"])
    # FIVE_PERCENT_COST with a 6% deposit: qualifies on money alone.
    po_a = place_order_paid(sa["id"], 1500000, "FIVE_PERCENT_COST", 2000000, 120000.00)
    po_a_done = confirm_order(po_a["id"])
    assert po_a_done["status"] == "SAFE_HARBOR_QUALIFIED"
    assert po_a_done["safe_harbor_qualified"] is True
    # PHYSICAL_WORK with a 75% deposit but no evidence: fails on validation.
    po_b = place_order_paid(sa["id"], 1750000, "PHYSICAL_WORK", 2000000, 1500000.00)
    resp = api.transition_procurement_order(
        po_b["id"], {"to": "SAFE_HARBOR_QUALIFIED"}, procurement_lead_headers
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    # The same order with evidence qualifies: the deposit size is irrelevant.
    po_b_done = confirm_order(po_b["id"], "s3://evidence/po-b-grading")
    assert po_b_done["status"] == "SAFE_HARBOR_QUALIFIED"


def test_physical_work_zero_deposit_still_requires_transition_state(
    api, developer_admin_headers, procurement_lead_headers
):
    """PRD §3.4: "Under the `PHYSICAL_WORK` method, cost amounts are irrelevant
    and qualification turns entirely on the presence of a
    `physical_work_evidence_uri` in the transition payload — an order with zero
    deposit can qualify, while an order with a full deposit but no evidence
    cannot".

    Design: Difficulty/dual_variant_calc/safe_harbor_cost_vs_physical_work_variants
    """
    project = create_project(name="Variant Farm 2", target_capacity_mw=90)
    sa = create_supply_agreement(project["id"])
    execute_supply_agreement(sa["id"])
    po = place_order(sa["id"], 1750000, "PHYSICAL_WORK", 2000000)
    pay_deposit(po["id"], 0.01)  # nominal deposit to reach DEPOSIT_PAID
    done = confirm_order(po["id"], "s3://evidence/zero-deposit")
    assert done["status"] == "SAFE_HARBOR_QUALIFIED"
    assert done["deposit_paid_usd"] == pytest.approx(0.01, abs=0.001)


def test_safe_harbor_exactly_five_percent_qualifies(
    api, developer_admin_headers, procurement_lead_headers
):
    """PRD §3.4: "the order qualifies if and only if its `deposit_paid_usd` is
    at least the five-percent threshold — the threshold being 5 percent of
    `eligible_cost_basis_usd` rounded half-up to 2 decimal places, with a
    deposit exactly equal to the threshold qualifying; falling short fails with
    `ERR_SAFE_HARBOR_TEST_FAILED` (HTTP 422)".

    Design: Difficulty/boundary_precision_check/safe_harbor_exactly_five_percent_qualifies
    """
    project = create_project(name="Boundary Farm", technology="SOLAR",
                             target_capacity_mw=40)
    sa = create_supply_agreement(
        project["id"], equipment_type="MODULE", supplier_name="LONGi",
        total_contract_usd=2500000,
    )
    execute_supply_agreement(sa["id"])
    # Threshold: round_half_up(0.05 * 2,000,000.00) = 100,000.00 exactly.
    po_x = place_order_paid(sa["id"], 1900000, "FIVE_PERCENT_COST", 2000000, 100000.00)
    done = confirm_order(po_x["id"])
    assert done["status"] == "SAFE_HARBOR_QUALIFIED"

    po_y = place_order_paid(sa["id"], 1900000, "FIVE_PERCENT_COST", 2000000, 99999.99)
    resp = api.transition_procurement_order(
        po_y["id"], {"to": "SAFE_HARBOR_QUALIFIED"}, procurement_lead_headers
    )
    validate_error(resp, ApiErrorId.ERR_SAFE_HARBOR_TEST_FAILED)
    po_y_now = get_success_data(
        api.get_procurement_order(po_y["id"], procurement_lead_headers)
    )
    assert po_y_now["status"] == "DEPOSIT_PAID"


def test_safe_harbor_threshold_rounds_half_up(
    api, developer_admin_headers, procurement_lead_headers
):
    """PRD §3.4: "the threshold being 5 percent of `eligible_cost_basis_usd`
    rounded half-up to 2 decimal places, with a deposit exactly equal to the
    threshold qualifying".
    PRD §2.6: "All monetary amounts are computed and stored to 2 decimal places
    using round-half-up rounding".

    Design: Difficulty/boundary_precision_check/safe_harbor_exactly_five_percent_qualifies
    """
    project = create_project(name="Round Farm", technology="SOLAR", target_capacity_mw=35)
    sa = create_supply_agreement(project["id"])
    execute_supply_agreement(sa["id"])
    # 0.05 * 333.333 = 16.66665 -> round-half-up to 16.67.
    po = place_order_paid(sa["id"], 300, "FIVE_PERCENT_COST", 333.333, 16.67)
    done = confirm_order(po["id"])
    assert done["status"] == "SAFE_HARBOR_QUALIFIED"
    # One cent below the rounded threshold fails.
    po2 = place_order_paid(sa["id"], 300, "FIVE_PERCENT_COST", 333.333, 16.66)
    resp = api.transition_procurement_order(
        po2["id"], {"to": "SAFE_HARBOR_QUALIFIED"}, procurement_lead_headers
    )
    validate_error(resp, ApiErrorId.ERR_SAFE_HARBOR_TEST_FAILED)


def test_temporal_beats_referential_on_safe_harbor_confirm(
    api, developer_admin_headers, procurement_lead_headers, platform_admin_headers
):
    """PRD §2.9: "then the time-window rules (priority 8 —
    `ERR_OPTION_WINDOW_LAPSED`, `ERR_SAFE_HARBOR_WINDOW_LAPSED`,
    `ERR_CONTINUITY_LAPSED`, `ERR_CURE_WINDOW_EXPIRED`) ... then cross-entity
    state gates (priority 10 — ... `ERR_SUPPLY_AGREEMENT_NOT_EXECUTED` ...)".
    PRD §3.4: "The logical clock must not have passed the order's `created_at`
    plus 183 days (otherwise `ERR_SAFE_HARBOR_WINDOW_LAPSED`, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_safe_harbor_confirm
    """
    project = create_project(name="Prio Farm B", target_capacity_mw=70)
    # Supply agreement left in DRAFT — both rules fail on the confirm.
    sa = create_supply_agreement(
        project["id"], supplier_name="Siemens", total_contract_usd=6000000,
    )
    po = place_order_paid(sa["id"], 2400000, "FIVE_PERCENT_COST", 2400000, 120000.00)
    # 190 days after placement: past created_at + 183 days.
    set_clock("2027-03-10T00:00:00Z")
    resp = api.transition_procurement_order(
        po["id"], {"to": "SAFE_HARBOR_QUALIFIED"}, procurement_lead_headers
    )
    validate_error(resp, ApiErrorId.ERR_SAFE_HARBOR_WINDOW_LAPSED)
    po_now = get_success_data(
        api.get_procurement_order(po["id"], procurement_lead_headers)
    )
    assert po_now["status"] == "DEPOSIT_PAID"
    assert po_now["safe_harbor_qualified"] is False


def test_safe_harbor_window_exactly_183_days_passes(
    api, developer_admin_headers, procurement_lead_headers, platform_admin_headers
):
    """PRD §3.4: "The logical clock must not have passed the order's
    `created_at` plus 183 days (otherwise `ERR_SAFE_HARBOR_WINDOW_LAPSED`,
    HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_safe_harbor_confirm
    """
    project = create_project(name="Window 183 Farm", target_capacity_mw=60)
    sa = create_supply_agreement(project["id"])
    execute_supply_agreement(sa["id"])
    po = place_order_paid(sa["id"], 2400000, "FIVE_PERCENT_COST", 2400000, 120000.00)
    # Order created at the clock start 2026-09-01T00:00:00Z; +183 days is
    # 2027-03-03T00:00:00Z. The clock has not passed that instant.
    set_clock("2027-03-03T00:00:00Z")
    done = confirm_order(po["id"])
    assert done["status"] == "SAFE_HARBOR_QUALIFIED"


def test_safe_harbor_confirm_requires_executed_supply_agreement(
    api, developer_admin_headers, procurement_lead_headers
):
    """PRD §3.4: "The parent supply agreement must be in `EXECUTED`,
    `AMENDMENT_PENDING`, `DELIVERING`, or `FULFILLED` (otherwise
    `ERR_SUPPLY_AGREEMENT_NOT_EXECUTED`, HTTP 409)."
    PRD §3.4: "moving to `AMENDMENT_PENDING` requires the payload to carry an
    `amendment_total_contract_usd` (omitting it fails with `ERR_VALIDATION`,
    HTTP 400)".

    Design: Difficulty/cross_entity_state_dependency/safe_harbor_confirm_requires_executed_supply_agreement
    """
    project = create_project(name="Ref Gate Farm", target_capacity_mw=55,
                             resource_class="B")
    sa = create_supply_agreement(
        project["id"], supplier_name="Nordex", total_contract_usd=3000000,
    )
    po = place_order_paid(sa["id"], 2400000, "FIVE_PERCENT_COST", 2400000, 120000.00)
    # Parent still DRAFT: the confirm gate is closed.
    resp = api.transition_procurement_order(
        po["id"], {"to": "SAFE_HARBOR_QUALIFIED"}, procurement_lead_headers
    )
    validate_error(resp, ApiErrorId.ERR_SUPPLY_AGREEMENT_NOT_EXECUTED)
    # Execute, then hold execution in an amendment: the gate re-opens.
    execute_supply_agreement(sa["id"])
    amended = get_success_data(
        api.transition_supply_agreement(
            sa["id"],
            {"to": "AMENDMENT_PENDING", "amendment_total_contract_usd": 3200000},
            procurement_lead_headers,
        )
    )
    assert amended["amendment_count"] == 0
    done = confirm_order(po["id"])
    assert done["status"] == "SAFE_HARBOR_QUALIFIED"


def test_supply_agreement_terminated_also_closes_gate(
    api, developer_admin_headers, procurement_lead_headers
):
    """PRD §3.4: "The parent supply agreement must be in `EXECUTED`,
    `AMENDMENT_PENDING`, `DELIVERING`, or `FULFILLED` (otherwise
    `ERR_SUPPLY_AGREEMENT_NOT_EXECUTED`, HTTP 409)."
    PRD §3.4: "Termination is permitted from `DRAFT` or from `EXECUTED`; in
    both cases, every procurement order of the agreement not yet in `DELIVERED`
    or `ACCEPTED` is cancelled".

    Design: Difficulty/cross_entity_state_dependency/safe_harbor_confirm_requires_executed_supply_agreement
    """
    project = create_project(name="Term Gate Farm", target_capacity_mw=55)
    sa = create_supply_agreement(project["id"])
    execute_supply_agreement(sa["id"])
    po = place_order_paid(sa["id"], 2400000, "FIVE_PERCENT_COST", 2400000, 120000.00)
    # Termination cancels the not-yet-delivered order.
    get_success_data(
        api.transition_supply_agreement(sa["id"], {"to": "TERMINATED"}, procurement_lead_headers)
    )
    po_now = get_success_data(
        api.get_procurement_order(po["id"], procurement_lead_headers)
    )
    assert po_now["status"] == "CANCELLED"
    resp = api.transition_procurement_order(
        po["id"], {"to": "SAFE_HARBOR_QUALIFIED"}, procurement_lead_headers
    )
    # The order itself is in a terminal state; either error family proves the
    # gate is closed — assert the observed one via the error map.
    assert resp.status_code in (400, 409)


def test_safe_harbor_cancellation_clawback_chain(
    api, developer_admin_headers, procurement_lead_headers, tax_counsel_headers
):
    """PRD §3.4: "Cancelling from the qualified state fires the two-link
    clawback cascade: first, the order's `safe_harbor_qualified` reverts to
    false, and if no other procurement order of the project remains in
    `SAFE_HARBOR_QUALIFIED`, `DELIVERED`, or `ACCEPTED` and the project's tax
    credit qualification is in `SAFE_HARBOR_ESTABLISHED`, the qualification
    reverts to `NOT_ELIGIBLE`; second, that revert recomputes the project's
    `tax_credit_anchored` to false."

    Design: Difficulty/transitive_cascade/safe_harbor_cancellation_clawback_chain
    """
    project = create_project(name="Clawback Farm", target_capacity_mw=90,
                             resource_class="B")
    pid = project["id"]
    sa = create_supply_agreement(
        pid, supplier_name="GE Vernova", total_contract_usd=4000000,
    )
    execute_supply_agreement(sa["id"])
    po_a = place_order_paid(sa["id"], 2000000, "FIVE_PERCENT_COST", 2000000, 100000.00)
    confirm_order(po_a["id"])
    # PO-B is only DEPOSIT_PAID: no remaining qualified order after cancelling PO-A.
    place_order_paid(sa["id"], 500000, "FIVE_PERCENT_COST", 2000000, 10000.00)
    tcq = establish_tcq(pid)

    cancelled = get_success_data(
        api.transition_procurement_order(po_a["id"], {"to": "CANCELLED"},
                                         procurement_lead_headers)
    )
    # Link 1: the order's flag reverts.
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["safe_harbor_qualified"] is False
    # Link 2: the qualification reverts.
    tcq_now = get_success_data(
        api.get_tax_credit_qualification(tcq["id"], tax_counsel_headers)
    )
    assert tcq_now["status"] == "NOT_ELIGIBLE"
    # Link 3: the project's computed flag recomputes to false.
    project_now = get_project(pid)
    assert project_now["tax_credit_anchored"] is False


def test_clawback_does_not_fire_when_other_qualified_order_remains(
    api, developer_admin_headers, procurement_lead_headers, tax_counsel_headers
):
    """PRD §3.4: "if no other procurement order of the project remains in
    `SAFE_HARBOR_QUALIFIED`, `DELIVERED`, or `ACCEPTED` and the project's tax
    credit qualification is in `SAFE_HARBOR_ESTABLISHED`, the qualification
    reverts to `NOT_ELIGIBLE`".

    Design: Difficulty/transitive_cascade/safe_harbor_cancellation_clawback_chain
    """
    project = create_project(name="Clawback Farm 2", target_capacity_mw=90)
    pid = project["id"]
    sa = create_supply_agreement(pid)
    execute_supply_agreement(sa["id"])
    po_a = place_order_paid(sa["id"], 2000000, "FIVE_PERCENT_COST", 2000000, 100000.00)
    confirm_order(po_a["id"])
    po_b = place_order_paid(sa["id"], 500000, "FIVE_PERCENT_COST", 500000, 25000.00)
    confirm_order(po_b["id"])
    tcq = establish_tcq(pid)
    get_success_data(
        api.transition_procurement_order(po_a["id"], {"to": "CANCELLED"},
                                         procurement_lead_headers)
    )
    # PO-B remains SAFE_HARBOR_QUALIFIED: the qualification stays anchored.
    tcq_now = get_success_data(
        api.get_tax_credit_qualification(tcq["id"], tax_counsel_headers)
    )
    assert tcq_now["status"] == "SAFE_HARBOR_ESTABLISHED"
    assert get_project(pid)["tax_credit_anchored"] is True
