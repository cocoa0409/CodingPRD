"""Depth probes over cyclic state machines, transitive cascades, validation
priority pairs, cross-entity gates, aggregate/overlap resources, and
compensating invariants."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_jurisdiction_ledger_invariant,
    begin_campaign_testing,
    campaign_transition_payload,
    certify_campaign,
    certify_la_test,
    classify_modification_recertification,
    complete_work_order,
    create_campaign,
    create_election_definition,
    create_equipment_unit,
    create_jurisdiction,
    create_la_test,
    create_official,
    create_procurement,
    create_procurement_payload,
    create_test_laboratory,
    create_unit_with_battery_cycles,
    create_voting_system,
    create_work_order,
    create_work_order_payload,
    deploy_unit,
    election_definition_transition_payload,
    equipment_unit_transition_payload,
    file_deficiencies,
    file_findings,
    get_campaign,
    get_certificate,
    get_election_definition,
    get_equipment_unit,
    get_jurisdiction,
    get_procurement,
    make_election_official_headers,
    make_lab_agent_headers,
    open_audit,
    procurement_transition_payload,
    propose_modification,
    record_acceptance_test,
    resubmit_campaign,
    set_clock,
    setup_certified_jurisdiction,
    setup_certified_system,
    setup_election_definition,
    setup_procurement,
    start_work_order,
    store_layout,
    transition_audit,
    transition_certificate,
    transition_election_definition,
    transition_equipment_unit,
    transition_procurement,
    transfer_custody,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


def _get_la_test(api, definition_id, la_test_id):
    data = validate_success(
        api.list_la_tests(definition_id, TEST_USERS["auditor_headers"])
    )
    matches = [t for t in data if t["id"] == la_test_id]
    assert len(matches) == 1, f"L&A test {la_test_id} not found in {data!r}"
    return matches[0]


def _get_unit_work_order(api, unit_id, work_order_id):
    data = validate_success(
        api.list_unit_work_orders(unit_id, TEST_USERS["auditor_headers"])
    )
    matches = [w for w in data if w["id"] == work_order_id]
    assert len(matches) == 1, f"work order {work_order_id} not found in {data!r}"
    return matches[0]


def test_campaign_resubmission_cycle_increments_count(api):
    """PRD §3.2: "A successful resubmission zeroes all three open counters,
    increments `resubmission_count` by 1, restamps `last_submitted_at` from
    the logical clock, and recomputes both conformity variants. The
    deficiency–resubmission cycle may repeat without bound."
    PRD §2.5: "`version` is an integer that increments by 1 on every mutation
    of the resource — field writes, state transitions, and cascade-driven
    changes alike."

    Design: Difficulty/non_linear_state_machine/campaign_resubmission_cycle_increments_count
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab = create_test_laboratory()
    campaign = create_campaign(system["id"], lab["id"])
    version_at_create = campaign["version"]

    begin_campaign_testing(campaign["id"], lab["id"])
    file_deficiencies(campaign["id"], lab["id"], 0, 0, 1)
    resubmit_campaign(campaign["id"], 0, 0, 1)
    begin_campaign_testing(campaign["id"], lab["id"])
    file_deficiencies(campaign["id"], lab["id"], 0, 2, 0)
    resubmit_campaign(campaign["id"], 0, 2, 0)

    data = get_campaign(campaign["id"])
    assert data["status"] == "SUBMITTED", "two full deficiency/resubmission loops"
    assert data["resubmission_count"] == 2
    assert data["open_critical_count"] == 0
    assert data["open_major_count"] == 0
    assert data["open_minor_count"] == 0
    assert data["version"] == version_at_create + 6, "six transitions, +1 each"


def test_equipment_parallel_dimensions_evolve_independently(api):
    """PRD §3.7: "The unit carries **two parallel state dimensions** that
    evolve independently (§2.9)."
    PRD §2.9: "Tamper evidence latches: a transfer recorded with
    `seal_intact` false flips the unit's `custody_status` to `UNSEALED`, and
    the unit returns to `SECURED` only when a `RESEAL` work order completes."
    PRD §3.8: "A `RESEAL` order requires the unit's custody to be `UNSEALED`
    (completing one while `SECURED` is `ERR_INVALID_STATE`) and restores
    `custody_status` to `SECURED`."

    Design: Difficulty/non_linear_state_machine/equipment_parallel_dimensions_evolve_independently
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    unit = create_equipment_unit(
        base["jurisdiction"]["id"], base["system"]["id"], off1, serial_number="SN-P1"
    )
    deploy_unit(unit["id"], off1)

    transfer_custody(unit["id"], off1, off2, seal_number="SEAL-P1-A", seal_intact=False)
    mid = get_equipment_unit(unit["id"])
    assert mid["operational_status"] == "IN_SERVICE", "custody transfer leaves the operational dimension alone"
    assert mid["custody_status"] == "UNSEALED"
    assert mid["current_custodian_id"] == off2

    wo = create_work_order(
        unit["id"], off2,
        work_type="RESEAL",
        scheduled_start="2026-09-02T00:00:00Z",
        scheduled_end="2026-09-03T00:00:00Z",
    )
    start_work_order(wo["id"], off2)
    during = get_equipment_unit(unit["id"])
    assert during["operational_status"] == "IN_MAINTENANCE"
    assert during["custody_status"] == "UNSEALED", "work-order start does not touch custody"

    complete_work_order(wo["id"], off2, resolution_note="resealed with SEAL-P1-B")
    end = get_equipment_unit(unit["id"])
    assert end["operational_status"] == "IN_SERVICE", "pre-maintenance status restored"
    assert end["custody_status"] == "SECURED", "RESEAL completion clears the latch"
    assert end["current_custodian_id"] == off2, "custodian identity untouched by maintenance"


def test_recert_classification_cascades_cert_suspend_definition_revert_la_challenge(api):
    """PRD §3.9: "Only after the lead time is stored does a
    `RECERTIFICATION_PENDING` classification fire its three-hop cascade:
    first, every `ACTIVE` certificate of the system moves to `SUSPENDED`;
    second, every election definition whose procurement pins one of those
    certificates and which is `PROGRAMMED` or `LA_PASSED` reverts to `DRAFT`
    with `status_reason` `CERTIFICATE_SUSPENDED`, and every procurement
    pinning one of those certificates that is `DELIVERED` or
    `ACCEPTANCE_TESTING` sets `cert_hold` true (which blocks its acceptance
    per §3.4); third, every logic-and-accuracy test of a reverted definition
    still in `CONDUCTED` moves to `CHALLENGED`."

    Design: Difficulty/transitive_cascade/recert_classification_cascades_cert_suspend_definition_revert_la_challenge
    """
    base = setup_election_definition("LA_PASSED")
    off1 = base["officials"][0]["id"]
    ed_id = base["definition"]["id"]
    certified_test = base["la_test"]
    conducted_test = create_la_test(
        ed_id, off1,
        expected_tallies={"PRES": 12000, "SEN": 8000},
        scanned_tallies={"PRES": 12010, "SEN": 8000},
    )
    mod = propose_modification(
        base["system"]["id"],
        description="EMS UI refresh",
        component_codes=["ELECTION_MANAGEMENT_UI"],
    )

    classify_modification_recertification(mod["id"])

    cert = get_certificate(base["certificate"]["id"])
    assert cert["status"] == "SUSPENDED", "hop 1"
    definition = get_election_definition(ed_id)
    assert definition["status"] == "DRAFT", "hop 2"
    assert definition["status_reason"] == "CERTIFICATE_SUSPENDED"
    challenged = _get_la_test(api, ed_id, conducted_test["id"])
    assert challenged["status"] == "CHALLENGED", "hop 3"
    untouched = _get_la_test(api, ed_id, certified_test["id"])
    assert untouched["status"] == "CERTIFIED", "terminal-state tests are not cascaded"
    procurement = get_procurement(base["procurement"]["id"])
    assert procurement["cert_hold"] is False, (
        "ACCEPTED procurements are outside the {DELIVERED, ACCEPTANCE_TESTING} hold set"
    )


def test_audit_escalation_quarantines_units_and_aborts_work_orders(api):
    """PRD §3.10: "`CLOSED_ESCALATED` requires at least one critical finding
    ... and triggers the platform's heaviest cascade: every equipment unit
    whose `jurisdiction_id` matches the audited definition's jurisdiction and
    whose `voting_system_id` matches the definition's procurement's voting
    system, with `operational_status` `IN_SERVICE`, `IN_STORAGE`, or
    `IN_MAINTENANCE`, moves to `QUARANTINED`; and every `SCHEDULED` or
    `IN_PROGRESS` work order of each quarantined unit moves to `ABORTED` — an
    `IN_PROGRESS` abort leaving its unit `QUARANTINED` with
    `pre_maintenance_status` cleared, per §3.8."

    Design: Difficulty/transitive_cascade/audit_escalation_quarantines_units_and_aborts_work_orders
    """
    base = setup_election_definition("CANVASSING")
    off1 = base["officials"][0]["id"]
    jur_id = base["jurisdiction"]["id"]
    sys_id = base["system"]["id"]
    ed_id = base["definition"]["id"]
    u5 = create_equipment_unit(jur_id, sys_id, off1, serial_number="SN-U5")
    deploy_unit(u5["id"], off1)
    wo5 = create_work_order(
        u5["id"], off1,
        work_type="PREVENTIVE",
        scheduled_start="2026-11-10T00:00:00Z",
        scheduled_end="2026-11-12T00:00:00Z",
    )
    u6 = create_equipment_unit(jur_id, sys_id, off1, serial_number="SN-U6")
    audit = open_audit(ed_id, audit_type="RISK_LIMITING")
    file_findings(audit["id"], 1, 0, 2)

    closed = transition_audit(audit["id"], "CLOSED_ESCALATED")
    assert closed["status"] == "CLOSED_ESCALATED"
    assert get_equipment_unit(u5["id"])["operational_status"] == "QUARANTINED", "hop 1"
    assert get_equipment_unit(u6["id"])["operational_status"] == "QUARANTINED", "hop 1"
    wo5_after = _get_unit_work_order(api, u5["id"], wo5["id"])
    assert wo5_after["status"] == "ABORTED", "hop 2, caused by hop 1's quarantine"
    assert get_equipment_unit(u5["id"])["custody_status"] == "SECURED", (
        "escalation touches only the operational dimension"
    )


def test_scope_mismatch_referential_beats_budget_fiscal(api):
    """PRD §2.7: "When several checks could fail on the same request, the
    failure with the lowest priority number wins — the earlier rejection
    masks the later ones."
    PRD §3.4: "the certificate's scope must cover the jurisdiction — a
    `FEDERAL` certificate covers every state, while a `STATE` certificate's
    `state_code` must equal the jurisdiction's `state_code`
    (`ERR_CERTIFICATE_SCOPE_MISMATCH`)".
    PRD §2.7: "20. **Fiscal checks last** — a procurement's
    `total_price_cents` must not exceed the jurisdiction's `available_cents`
    (`ERR_BUDGET_EXCEEDED`, 402); ... Fiscal sufficiency is deliberately
    evaluated only after every existence, authorization, state, and business
    check has passed."

    Design: Difficulty/priority_pair_validation_conflict/scope_mismatch_referential_beats_budget_fiscal
    """
    base = setup_certified_system(state_code="TX")  # STATE/TX certificate
    jurisdiction = create_jurisdiction(
        name="Tiny County", state_code="CA", budget_total_cents=1000
    )
    official = create_official(jurisdiction["id"])
    resp = api.create_procurement(
        create_procurement_payload(
            jurisdiction["id"],
            base["system"]["id"],
            base["certificate"]["id"],
            quantity=10,
            unit_price_cents=2_500_000,
        ),
        make_election_official_headers(official["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_SCOPE_MISMATCH)
    assert resp.json()["data"]["error_id"] != "ERR_BUDGET_EXCEEDED", (
        "referential (priority 19) masks fiscal (priority 20) even though "
        "25,000,000 cents exceeds the 1,000-cent budget"
    )


def test_invalid_state_beats_battery_safety(api):
    """PRD §2.7: "When several checks could fail on the same request, the
    failure with the lowest priority number wins — the earlier rejection
    masks the later ones."
    PRD §2.7: "8. **State machine legality** — the target's state machine
    must permit the requested transition from its current state; terminal
    rows reject every further transition, and a `to_state` naming a real
    state that is unreachable from the current state fails here with
    `ERR_INVALID_STATE` (409)."
    PRD §2.7: "12. **Battery ceiling** — deploying a unit requires
    `battery_cycles` below 500, with exactly 500 rejected; otherwise
    `ERR_BATTERY_CYCLE_LIMIT` (422)."
    PRD §3.7: "While a unit is `QUARANTINED`, custody transfers, deploy/store
    transitions, and work-order creation are all rejected with
    `ERR_UNIT_QUARANTINED`."

    Precedence note: §2.7 fixes the pipeline order (state legality 8 beats
    battery ceiling 12), while §3.7 and priority 10 name the quarantine gate
    for deploy/store against a `QUARANTINED` unit; PRD does not resolve which
    of those two earlier checks reports this exact request, so both are
    accepted. What PRD pins is that the battery ceiling (priority 12) is
    masked by either of them.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_battery_safety
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    unit = create_unit_with_battery_cycles(
        base["jurisdiction"]["id"], base["system"]["id"], off1, 500,
        serial_number="SN-Q1",
    )
    transition_equipment_unit(
        unit["id"], "QUARANTINED", TEST_USERS["certification_authority_headers"]
    )
    assert get_equipment_unit(unit["id"])["battery_cycles"] == 500

    resp = api.transition_equipment_unit(
        unit["id"],
        equipment_unit_transition_payload("IN_SERVICE"),
        make_election_official_headers(off1),
    )
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_UNIT_QUARANTINED],
    )
    assert resp.json()["data"]["error_id"] != "ERR_BATTERY_CYCLE_LIMIT", (
        "an earlier check (state legality priority 8, or the quarantine gate "
        "of priority 10 / section 3.7) masks the battery ceiling "
        "(priority 12): QUARANTINED has no IN_SERVICE transition"
    )


def test_procurement_acceptance_blocked_when_certificate_suspended(api):
    """PRD §3.4: "`DELIVERED` → `ACCEPTANCE_TESTING` begins the acceptance
    battery, and at that moment the pinned certificate must be `ACTIVE`
    (`ERR_CERTIFICATE_NOT_ACTIVE`)."
    PRD §3.3: "Throughout the platform, any guard that requires an `ACTIVE`
    certificate — starting acceptance testing, accepting a procurement,
    locking an election definition, or placing a procurement — fails with
    `ERR_CERTIFICATE_NOT_ACTIVE` against a certificate in any other state."
    PRD §3.4: "A placed procurement pins the certificate's `version` at that
    instant into `certificate_version_pinned`, which is never rewritten".

    Design: Difficulty/cross_entity_state_dependency/procurement_acceptance_blocked_when_certificate_suspended
    """
    base = setup_procurement("DELIVERED")
    off1 = base["officials"][0]["id"]
    cert = base["certificate"]
    proc_id = base["procurement"]["id"]
    transition_certificate(cert["id"], "SUSPENDED", reason="state review")

    resp = api.transition_procurement(
        proc_id,
        procurement_transition_payload("ACCEPTANCE_TESTING"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_ACTIVE)

    transition_certificate(cert["id"], "ACTIVE")
    transition_procurement(proc_id, "ACCEPTANCE_TESTING", off1)
    procurement = get_procurement(proc_id)
    assert procurement["status"] == "ACCEPTANCE_TESTING"
    assert procurement["certificate_version_pinned"] == cert["version"], (
        "the pin records the placement-time version; it does not freeze the status check"
    )


def test_definition_lock_blocked_until_procurement_accepted(api):
    """PRD §3.5: "Locking (`LA_PASSED` → `LOCKED`) is the point of no return
    before election day. It requires the procurement to be `ACCEPTED`
    (`ERR_PROCUREMENT_NOT_ACCEPTED`), the certificate pinned by that
    procurement to be `ACTIVE` (`ERR_CERTIFICATE_NOT_ACTIVE`), and a freeze
    window: the `election_date` must be at least 14 days after the current
    logical date (`ERR_ELECTION_FREEZE_WINDOW`)."

    Design: Difficulty/cross_entity_state_dependency/definition_lock_blocked_until_procurement_accepted
    """
    base = setup_procurement("ACCEPTANCE_TESTING")
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    proc_id = base["procurement"]["id"]
    definition = create_election_definition(
        base["jurisdiction"]["id"], proc_id, acting_official_id=off1
    )
    store_layout(definition["id"], off1)
    transition_election_definition(definition["id"], "PROGRAMMED", off1)
    la_test = create_la_test(definition["id"], off1)
    certify_la_test(la_test["id"], off2)
    transition_election_definition(definition["id"], "LA_PASSED", off1)

    resp = api.transition_election_definition(
        definition["id"],
        election_definition_transition_payload("LOCKED"),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_PROCUREMENT_NOT_ACCEPTED)

    record_acceptance_test(proc_id, off1, test_type="HARDWARE_DIAGNOSTIC")
    record_acceptance_test(proc_id, off1, test_type="BALLOT_SCAN_CALIBRATION")
    transition_procurement(proc_id, "ACCEPTED", off1)
    locked = transition_election_definition(definition["id"], "LOCKED", off1)
    assert locked["status"] == "LOCKED", (
        "completing acceptance on the sibling procurement unlocks the transition"
    )


def test_work_order_half_open_overlap_adjacency_allowed(api):
    """PRD §3.8: "Scheduling is rejected when the half-open window intersects
    another `SCHEDULED` or `IN_PROGRESS` order on the same unit
    (`ERR_WORK_ORDER_OVERLAP`); adjacency — one window's end equal to the
    other's start — is allowed."

    Design: Difficulty/resource_temporal_overlap/work_order_half_open_overlap_adjacency_allowed
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    unit = create_equipment_unit(
        base["jurisdiction"]["id"], base["system"]["id"], off1, serial_number="SN-W1"
    )
    create_work_order(
        unit["id"], off1,
        work_type="PREVENTIVE",
        scheduled_start="2026-09-10T00:00:00Z",
        scheduled_end="2026-09-12T00:00:00Z",
    )

    resp = api.create_work_order(
        create_work_order_payload(
            unit["id"],
            work_type="REPAIR",
            scheduled_start="2026-09-11T00:00:00Z",
            scheduled_end="2026-09-13T00:00:00Z",
        ),
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_OVERLAP)

    resp = api.create_work_order(
        create_work_order_payload(
            unit["id"],
            work_type="REPAIR",
            scheduled_start="2026-09-12T00:00:00Z",
            scheduled_end="2026-09-14T00:00:00Z",
        ),
        make_election_official_headers(off1),
    )
    adjacent = validate_success(resp, 201)
    assert adjacent["status"] == "SCHEDULED", (
        "half-open intervals treat end == start as non-overlapping"
    )


def test_lab_capacity_aggregate_count_blocks_third_campaign(api):
    """PRD §3.2: "the laboratory's aggregate capacity must have room — the
    number of that laboratory's campaigns currently `IN_TEST` must be
    strictly below its `max_concurrent_campaigns`, otherwise
    `ERR_LAB_CAPACITY_EXCEEDED`. Capacity is aggregate across all of the
    laboratory's campaigns, not per system."

    Design: Difficulty/resource_temporal_overlap/lab_capacity_aggregate_count_blocks_third_campaign
    """
    set_clock("2026-09-01T00:00:00Z")
    lab = create_test_laboratory(lab_name="Capacity Lab", max_concurrent_campaigns=2)
    systems = [
        create_voting_system(vendor_name=f"Vendor{i}", model_name=f"M{i}")
        for i in (1, 2, 3)
    ]
    campaigns = [create_campaign(s["id"], lab["id"]) for s in systems]
    begin_campaign_testing(campaigns[0]["id"], lab["id"])
    begin_campaign_testing(campaigns[1]["id"], lab["id"])

    resp = api.transition_certification_campaign(
        campaigns[2]["id"],
        campaign_transition_payload("IN_TEST"),
        make_lab_agent_headers(lab["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LAB_CAPACITY_EXCEEDED)

    certify_campaign(campaigns[0]["id"])
    third = begin_campaign_testing(campaigns[2]["id"], lab["id"])
    assert third["status"] == "IN_TEST", (
        "certification freed one aggregate slot, so the third begin succeeds"
    )


def test_budget_place_then_cancel_restores_ledger(api):
    """PRD §2.8: "At every observable instant the invariant holds:
    `budget_total_cents` equals `available_cents` plus `encumbered_cents`
    plus `spent_cents`."
    PRD §2.8: "A placement followed by its own cancellation must restore the
    exact pre-placement pair of `available_cents` and `encumbered_cents` —
    zero drift is tolerated."

    Design: Difficulty/compensating_invariant/budget_place_then_cancel_restores_ledger
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    jur_id = base["jurisdiction"]["id"]
    procurement = create_procurement(
        jur_id, base["system"]["id"], base["certificate"]["id"],
        acting_official_id=off1, quantity=10, unit_price_cents=2_500_000,
    )

    mid = get_jurisdiction(jur_id)
    assert mid["available_cents"] == 75_000_000
    assert mid["encumbered_cents"] == 25_000_000
    assert mid["spent_cents"] == 0
    assert_jurisdiction_ledger_invariant(mid)

    transition_procurement(procurement["id"], "CANCELLED", off1)
    end = get_jurisdiction(jur_id)
    assert end["available_cents"] == 100_000_000, "exact restoration, zero drift"
    assert end["encumbered_cents"] == 0
    assert end["spent_cents"] == 0
    assert_jurisdiction_ledger_invariant(end)
    assert get_procurement(procurement["id"])["status"] == "CANCELLED"


def test_custody_round_trip_restores_single_custodian(api):
    """PRD §2.9: "Every equipment unit has exactly one `current_custodian_id`
    at all times, set from `initial_custodian_id` at registration and moved
    atomically by custody transfers. Transfers are intra-jurisdiction only:
    a transfer never changes a jurisdiction's unit count."
    PRD §2.9: "A transfer from official A to official B followed by its
    compensating transfer from B back to A, both with intact seals, must
    leave `current_custodian_id` restored to A and `custody_status` `SECURED`
    throughout — again, zero drift."

    Design: Difficulty/compensating_invariant/custody_round_trip_restores_single_custodian
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    jur_id = base["jurisdiction"]["id"]
    unit = create_equipment_unit(
        jur_id, base["system"]["id"], off1, serial_number="SN-C1"
    )

    transfer_custody(unit["id"], off1, off2, seal_number="SEAL-C1-A", seal_intact=True)
    mid = get_equipment_unit(unit["id"])
    assert mid["current_custodian_id"] == off2
    assert mid["custody_status"] == "SECURED"

    transfer_custody(unit["id"], off2, off1, seal_number="SEAL-C1-B", seal_intact=True)
    end = get_equipment_unit(unit["id"])
    assert end["current_custodian_id"] == off1, "compensating transfer restores custodian A"
    assert end["custody_status"] == "SECURED"

    units, meta = validate_paginated(
        api.list_equipment_units(
            TEST_USERS["auditor_headers"], params={"jurisdiction_id": jur_id}
        )
    )
    assert meta["total_count"] == 1, "a transfer never changes a jurisdiction's unit count"
