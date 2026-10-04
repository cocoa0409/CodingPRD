"""Supplier lifecycle: terminal lockdown, suspend/reinstate cycle, versions (PRD §3.1, §3.2)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_supplier_payload,
    make_supplier, create_approved_supplier, run_audit, fail_supplier_audit,
    make_commitment,
)

SM = TEST_USERS["sourcing_manager_headers"]


def test_supplier_terminate_terminal_lockdown(api):
    """PRD §3.1: "Termination is available from `PROSPECT`, `APPROVED`, or `SUSPENDED` and moves the supplier to the terminal `TERMINATED` state, bumping `version` each time"
    PRD §2.6: "the requested transition must be defined for the resource's current state, failing with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/supplier_terminate_terminal_lockdown
    """
    supplier = make_supplier(name="Doomed Dairy")
    terminated = validate_success(api.terminate_supplier(supplier["id"], SM))
    assert terminated["status"] == "TERMINATED"
    resp = api.suspend_supplier(supplier["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_version_increments_on_mutation(api):
    """PRD §2.4: "`version` (integer): starts at its initial value on creation
    and increments by one on every mutation; it is the basis of optimistic
    concurrency control (§2.7)."
    PRD §3.1: "manual suspension preserves the supplier's commitments and
    certifications untouched and bumps the supplier's `version`."

    Design: Corner/cross_cutting_layers/version_increments_on_mutation
    """
    supplier = make_supplier(name="Versioned Supplier")
    v0 = supplier["version"]
    assert v0 == 1
    run_audit(supplier["id"])  # PASS verification bumps the supplier once
    v1 = get_success_data(api.get_supplier(supplier["id"], SM))["version"]
    v2 = validate_success(api.suspend_supplier(supplier["id"], SM))["version"]
    v3 = validate_success(api.reinstate_supplier(supplier["id"], SM))["version"]
    assert v2 == v1 + 1, f"suspend must bump version by exactly 1 ({v1} -> {v2})"
    assert v3 == v2 + 1, f"reinstate must bump version by exactly 1 ({v2} -> {v3})"


def test_supplier_suspend_reinstate_cycle_preserves_commitment(api):
    """PRD §3.1: "From `APPROVED`, a `SourcingManager` may suspend the supplier,
    moving it to `SUSPENDED`; manual suspension preserves the supplier's
    commitments and certifications untouched and bumps the supplier's `version`."
    PRD §3.1: "or the `SourcingManager` reinstates it manually from `SUSPENDED`
    to `APPROVED` — but manual reinstatement does not resurrect commitments that
    lapsed in the meantime."

    Design: Difficulty/non_linear_state_machine/supplier_suspend_reinstate_cycle
    """
    supplier = create_approved_supplier(name="Cocoa Collective", category="COCOA")
    commitment = make_commitment(supplier["id"], category="COCOA")

    suspended = validate_success(api.suspend_supplier(supplier["id"], SM))
    assert suspended["status"] == "SUSPENDED"

    data, _ = validate_paginated(
        api.list_commitments(supplier["id"], SM, params={"status": "ACTIVE"}))
    assert [c["id"] for c in data] == [commitment["id"]], \
        "manual suspension must leave the ACTIVE commitment untouched"

    reinstated = validate_success(api.reinstate_supplier(supplier["id"], SM))
    assert reinstated["status"] == "APPROVED"
    assert reinstated["social_criteria_score"] == 71  # 0.4*80 + 0.3*70 + 0.3*60


def test_supplier_fail_suspension_then_passing_audit_reinstates(api):
    """PRD §3.2: "On a `PASS`, a `PROSPECT` or `SUSPENDED` supplier transitions
    to `APPROVED` — this is both the only path to initial approval and the
    automatic reinstatement of a suspended supplier — and the supplier's
    `version` bumps."

    Design: Difficulty/non_linear_state_machine/supplier_suspend_reinstate_cycle
    """
    supplier = create_approved_supplier(name="Cycle Dairy")
    suspended = validate_success(api.suspend_supplier(supplier["id"], SM))
    assert suspended["status"] == "SUSPENDED"

    # A later passing audit reinstates the suspended supplier automatically.
    run_audit(supplier["id"], labor=90, environment=90, community=90, findings=0)
    after = get_success_data(api.get_supplier(supplier["id"], SM))
    assert after["status"] == "APPROVED"
    assert after["social_criteria_score"] == 90

    # And the cycle can repeat: manual suspend is defined from APPROVED again.
    re_suspended = validate_success(api.suspend_supplier(supplier["id"], SM))
    assert re_suspended["status"] == "SUSPENDED"
    reinstated = validate_success(api.reinstate_supplier(supplier["id"], SM))
    assert reinstated["status"] == "APPROVED"
    assert reinstated["social_criteria_score"] == 90
