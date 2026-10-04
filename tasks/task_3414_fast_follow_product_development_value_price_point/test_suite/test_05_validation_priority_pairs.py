"""Validation priority pairs: when one request violates two rules, the PRD's
fixed evaluation order decides which error surfaces. Each pair is also shown
with the lower-priority error firing in isolation.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    lock_plan,
    open_dossier,
    read_launch_plan,
    read_planogram_slot,
    read_product,
    set_packaging_ready,
    setup_accepted_quote_product,
    setup_compliance_gate_product,
    setup_draft_plan,
    setup_locked_plan,
    validate_error,
)

_PM = TEST_USERS["product_manager_headers"]


def test_launch_ready_from_sourcing_reports_state_not_compliance(api):
    """PRD §2.8: "When a single request violates several rules, the reported
    error is the one whose rule has the lowest priority number; the checks are
    evaluated in this fixed order. ... Seventh, state-machine from-state
    validity, including terminal-state lockdown, the from-state rules of the
    parallel packaging and sampling dimensions, and cross-entity state
    preconditions that have no more specific error (else `ERR_INVALID_STATE`).
    Eighth, the compliance gates (else `ERR_COMPLIANCE_GATE_FAILED`)."
    A LAUNCH_READY attempt from SOURCING (invalid from-state) on a product
    with no dossier surfaces ERR_INVALID_STATE, not ERR_COMPLIANCE_GATE_FAILED.

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_launch_ready
    """
    ctx = setup_accepted_quote_product()

    response = api.patch_product(ctx["product"]["id"], {"status": "LAUNCH_READY"}, _PM)

    error = validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert error["error_id"] != ApiErrorId.ERR_COMPLIANCE_GATE_FAILED.value
    assert read_product(ctx["product"]["id"])["status"] == "SOURCING"


def test_launch_ready_with_clean_state_hits_the_compliance_gate(api):
    """PRD §3.3: "Moving from `COMPLIANCE_GATE` to `LAUNCH_READY` requires two
    things together: the product's dossier must be fully compliant, else
    `ERR_COMPLIANCE_GATE_FAILED`, and the packaging dimension must have
    reached `PACK_READY` — a separate update the manager makes by setting
    `packaging_status` — else `ERR_INVALID_STATE`."
    With the from-state valid and packaging PACK_READY, a non-compliant
    dossier (all dimensions still PENDING) surfaces the safety error itself.

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_launch_ready
    """
    ctx = setup_compliance_gate_product()
    open_dossier(ctx["product"]["id"])
    set_packaging_ready(ctx["product"]["id"])

    response = api.patch_product(ctx["product"]["id"], {"status": "LAUNCH_READY"}, _PM)

    validate_error(response, ApiErrorId.ERR_COMPLIANCE_GATE_FAILED.value)
    assert read_product(ctx["product"]["id"])["status"] == "COMPLIANCE_GATE"


def test_plan_approve_reports_uncommitted_slot_before_budget(api):
    """PRD §2.8: "...slot creation requires a `LAUNCH_READY` product (else
    `ERR_PRODUCT_NOT_LAUNCH_READY`) and plan approval requires a committed
    slot (else `ERR_SLOT_NOT_COMMITTED`); ..." — evaluated before "Fiscal
    rules follow: the cost-target check (else `ERR_COST_TARGET_EXCEEDED`), the
    budget checks (else `ERR_BUDGET_EXCEEDED`), and the sampling caps (else
    `ERR_SAMPLE_OVERDRAW`)."
    Approving a locked plan whose slot is still PROPOSED and whose
    sample_budget_cents (60000) exceeds marketing_budget_cents (50000)
    surfaces ERR_SLOT_NOT_COMMITTED, not ERR_BUDGET_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/referential_error_beats_fiscal_error_on_plan_approve
    """
    ctx = setup_draft_plan(plan_overrides={"sample_budget_cents": 60000})
    lock_plan(ctx["plan"]["id"], variant="DEMAND")

    response = api.patch_launch_plan(ctx["plan"]["id"], {"status": "APPROVED"}, _PM)

    error = validate_error(response, ApiErrorId.ERR_SLOT_NOT_COMMITTED.value)
    assert error["error_id"] != ApiErrorId.ERR_BUDGET_EXCEEDED.value
    assert read_launch_plan(ctx["plan"]["id"])["status"] == "QUANTITY_LOCKED"
    assert read_planogram_slot(ctx["slot"]["id"])["status"] == "PROPOSED"


def test_plan_approve_with_committed_slot_hits_the_budget_rule(api):
    """PRD §3.8: "Approval — `QUANTITY_LOCKED` to `APPROVED` — rechecks the
    world: the slot must be `COMMITTED`, else `ERR_SLOT_NOT_COMMITTED`; the
    product's dossier must be fully compliant with a certification that has
    not lapsed, else `ERR_COMPLIANCE_GATE_FAILED`; and `sample_budget_cents`
    must not exceed `marketing_budget_cents`, else `ERR_BUDGET_EXCEEDED`."
    With the slot COMMITTED and the dossier compliant, the oversized sampling
    budget surfaces the fiscal error in isolation.

    Design: Difficulty/priority_pair_validation_conflict/referential_error_beats_fiscal_error_on_plan_approve
    """
    ctx = setup_locked_plan(plan_overrides={"sample_budget_cents": 60000})

    response = api.patch_launch_plan(ctx["plan"]["id"], {"status": "APPROVED"}, _PM)

    validate_error(response, ApiErrorId.ERR_BUDGET_EXCEEDED.value)
    assert read_launch_plan(ctx["plan"]["id"])["status"] == "QUANTITY_LOCKED"
