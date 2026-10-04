"""Support transition SLA gates and maintenance agreement lifecycle."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, get_success_data, reset_clock,
    setup_executed_go_live, setup_steady_state_support, ticket_payload,
    validate_error, validate_paginated,
)


def test_sla_breach_strict_greater_than_boundary():
    """PRD §3.12: "the service-level allowances are one day for `SEV1`, five
    days for `SEV2`, and twenty days for `SEV3`, in whole days, and a ticket's
    `breached_sla` is true when the gap from `raised_on` to `resolved_on`
    strictly exceeds its severity's allowance." PRD §3.12: "Leaving `WARRANTY`
    for `STABILIZATION` requires the logical clock date to be later than
    `warranty_end_on` and `open_sev1_count` to be zero."

    Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_than_boundary
    """
    ctx = setup_executed_go_live(planned_date="2026-12-01")
    st = ctx["support_transition"]
    support = TEST_USERS["support_manager"]
    reset_clock("2026-12-02T00:00:00Z")
    t1 = get_success_data(api_client.create_ticket(
        st["id"], ticket_payload(severity="SEV2", summary="t1"), support))
    t2 = get_success_data(api_client.create_ticket(
        st["id"], ticket_payload(severity="SEV2", summary="t2"), support))
    reset_clock("2026-12-07T00:00:00Z")  # exactly 5 days later
    r1 = get_success_data(api_client.resolve_ticket(
        t1["id"], {"resolution": "RESOLVED"}, support))
    assert r1["breached_sla"] is False
    reset_clock("2026-12-08T00:00:00Z")  # 6 days later
    r2 = get_success_data(api_client.resolve_ticket(
        t2["id"], {"resolution": "RESOLVED"}, support))
    assert r2["breached_sla"] is True
    reset_clock("2027-03-02T00:00:00Z")  # past warranty end 2027-03-01
    advanced = get_success_data(api_client.advance_support_transition(st["id"], support))
    assert advanced["status"] == "STABILIZATION"
    assert advanced["sla_breach_count"] == 1
    assert advanced["open_sev1_count"] == 0


def test_sla_breach_allowance_allows_two_blocks_three():
    """PRD §3.12: "Leaving `STABILIZATION` for `STEADY_STATE` requires
    `open_sev1_count` to be zero and `sla_breach_count` to be at most two — the
    breach allowance; reaching `STEADY_STATE` opens the gate for the contract's
    maintenance agreement to be activated."

    Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_than_boundary
    """
    ctx = setup_executed_go_live(planned_date="2026-12-01")
    st = ctx["support_transition"]
    support = TEST_USERS["support_manager"]
    reset_clock("2026-12-02T00:00:00Z")
    tickets = [
        get_success_data(api_client.create_ticket(
            st["id"], ticket_payload(severity="SEV2", summary=f"t{i}"), support))
        for i in range(3)
    ]
    # resolve all three 6 days later: each breaches (6 > 5)
    reset_clock("2026-12-08T00:00:00Z")
    for t in tickets:
        r = get_success_data(api_client.resolve_ticket(
            t["id"], {"resolution": "RESOLVED"}, support))
        assert r["breached_sla"] is True
    reset_clock("2027-03-02T00:00:00Z")
    advanced = get_success_data(api_client.advance_support_transition(st["id"], support))
    assert advanced["status"] == "STABILIZATION"
    assert advanced["sla_breach_count"] == 3
    resp = api_client.advance_support_transition(st["id"], support)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api_client.get_support_transition(st["id"], support))
    assert current["status"] == "STABILIZATION"


def test_maintenance_activation_requires_steady_state_support():
    """PRD §3.13: "Activation (`DRAFT → ACTIVE`) requires the contract's
    support transition to be in `STEADY_STATE`". PRD §2.6: "Only then are state
    preconditions evaluated (`ERR_INVALID_STATE`, HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/maintenance_activation_requires_steady_state_support
    """
    ctx = setup_executed_go_live(planned_date="2026-12-01")
    ma = get_success_data(api_client.create_maintenance_agreement(
        ctx["contract"]["id"],
        {"annual_fee_cents": 12_000_000, "coverage_start_on": "2027-03-02"},
        TEST_USERS["finance_officer"]))
    resp = api_client.activate_agreement(ma["id"], TEST_USERS["finance_officer"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api_client.get_maintenance_agreement(
        ma["id"], TEST_USERS["finance_officer"]))
    assert current["status"] == "DRAFT"


def test_maintenance_activation_succeeds_at_steady_state():
    """PRD §3.13: "Activation (`DRAFT → ACTIVE`) requires the contract's
    support transition to be in `STEADY_STATE`, requires coverage continuity —
    `coverage_start_on` must be exactly the day after the support transition's
    `warranty_end_on`". PRD §3.13: "On activation the escalated fee is computed
    per the maintenance escalator: at `renewal_index` zero the
    `escalated_fee_cents` equals the `annual_fee_cents` exactly."

    Design: Difficulty/cross_entity_state_dependency/maintenance_activation_requires_steady_state_support
    """
    ctx = setup_steady_state_support(planned_date="2026-12-01")
    ma = get_success_data(api_client.create_maintenance_agreement(
        ctx["contract"]["id"],
        {"annual_fee_cents": 12_000_000, "coverage_start_on": "2027-03-02"},
        TEST_USERS["finance_officer"]))
    activated = get_success_data(api_client.activate_agreement(
        ma["id"], TEST_USERS["finance_officer"]))
    assert activated["status"] == "ACTIVE"
    assert activated["escalated_fee_cents"] == 12_000_000
    assert activated["renewal_index"] == 0


def test_coverage_gap_blocks_maintenance_activation():
    """PRD §3.13: "requires coverage continuity — `coverage_start_on` must be
    exactly the day after the support transition's `warranty_end_on`, with any
    gap or overlap rejected as `ERR_COVERAGE_GAP` (HTTP 422)".

    Design: Corner/errors/coverage_gap_blocks_maintenance_activation
    """
    ctx = setup_steady_state_support(planned_date="2026-12-01")
    ma_gap = get_success_data(api_client.create_maintenance_agreement(
        ctx["contract"]["id"],
        {"annual_fee_cents": 12_000_000, "coverage_start_on": "2027-03-03"},
        TEST_USERS["finance_officer"]))
    resp = api_client.activate_agreement(ma_gap["id"], TEST_USERS["finance_officer"])
    validate_error(resp, ApiErrorId.ERR_COVERAGE_GAP)
    ma_ok = get_success_data(api_client.create_maintenance_agreement(
        ctx["contract"]["id"],
        {"annual_fee_cents": 12_000_000, "coverage_start_on": "2027-03-02"},
        TEST_USERS["finance_officer"]))
    activated = get_success_data(api_client.activate_agreement(
        ma_ok["id"], TEST_USERS["finance_officer"]))
    assert activated["status"] == "ACTIVE"


def test_maintenance_escalation_compounded_per_renewal():
    """PRD §3.13: "The escalated fee at a given renewal index is the
    `annual_fee_cents` compounded by three percent per renewal — that is, the
    base fee multiplied by 1.03 raised to the power of the renewal index — with
    the product rounded half-up to a whole cent exactly once at the end, never
    per year." PRD §3.13: "Renewal creates a successor agreement in `DRAFT`
    whose `renewal_index` is the current agreement's plus one and whose
    `escalated_fee_cents` is recomputed, while the current agreement closes as
    `RENEWED`".

    Design: Corner/calculations/maintenance_escalation_compounded_per_renewal
    """
    ctx = setup_steady_state_support(planned_date="2026-12-01")
    ma = get_success_data(api_client.create_maintenance_agreement(
        ctx["contract"]["id"],
        {"annual_fee_cents": 12_000_000, "coverage_start_on": "2027-03-02"},
        TEST_USERS["finance_officer"]))
    activated = get_success_data(api_client.activate_agreement(
        ma["id"], TEST_USERS["finance_officer"]))
    assert activated["escalated_fee_cents"] == 12_000_000
    assert activated["renewal_index"] == 0
    renewed = get_success_data(api_client.renew_agreement(
        ma["id"], {"expected_agreement_version": activated["version"]},
        TEST_USERS["finance_officer"]))
    assert renewed["status"] == "RENEWED"
    rows, _meta = validate_paginated(api_client.list_maintenance_agreements(
        ctx["contract"]["id"], TEST_USERS["finance_officer"]))
    successors = [r for r in rows if r["id"] != ma["id"]]
    assert len(successors) == 1
    successor = successors[0]
    assert successor["status"] == "DRAFT"
    assert successor["renewal_index"] == 1
    assert successor["escalated_fee_cents"] == 12_360_000


def test_occ_stale_agreement_version_on_renew():
    """PRD §2.7: "Renewing a maintenance agreement likewise requires
    `expected_agreement_version` matching the current `version` of the
    agreement being renewed; a mismatch is rejected with `ERR_STALE_VERSION`
    (HTTP 412)". PRD §3.13: "Suspension toggles the agreement `ACTIVE →
    SUSPENDED`, and calling the same operation on a suspended agreement
    reinstates it `SUSPENDED → ACTIVE`; each call increments the agreement's
    `version`."

    Design: Corner/cross_cutting_layers/occ_stale_agreement_version_on_renew
    """
    ctx = setup_steady_state_support(planned_date="2026-12-01")
    ma = get_success_data(api_client.create_maintenance_agreement(
        ctx["contract"]["id"],
        {"annual_fee_cents": 12_000_000, "coverage_start_on": "2027-03-02"},
        TEST_USERS["finance_officer"]))
    activated = get_success_data(api_client.activate_agreement(
        ma["id"], TEST_USERS["finance_officer"]))
    observed_version = activated["version"]
    # suspend + reinstate round trip bumps version twice
    get_success_data(api_client.suspend_agreement(ma["id"], TEST_USERS["finance_officer"]))
    reinstated = get_success_data(api_client.suspend_agreement(
        ma["id"], TEST_USERS["finance_officer"]))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["version"] == observed_version + 2
    resp = api_client.renew_agreement(
        ma["id"], {"expected_agreement_version": observed_version},
        TEST_USERS["finance_officer"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    current = get_success_data(api_client.get_maintenance_agreement(
        ma["id"], TEST_USERS["finance_officer"]))
    assert current["status"] == "ACTIVE"
