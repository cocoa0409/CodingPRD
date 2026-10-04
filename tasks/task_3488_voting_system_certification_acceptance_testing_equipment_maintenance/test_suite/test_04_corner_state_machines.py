"""Breadth probes over state-machine legality, terminal lockdown, transition
side effects, and cascade-down behavior."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_jurisdiction_ledger_invariant,
    begin_campaign_testing,
    campaign_transition_payload,
    certify_campaign,
    certify_la_test,
    complete_work_order,
    create_campaign,
    create_election_definition,
    create_equipment_unit,
    create_la_test,
    create_procurement,
    create_test_laboratory,
    create_voting_system,
    create_work_order,
    deploy_unit,
    get_campaign,
    get_certificate,
    get_certificate_for_campaign,
    get_election_definition,
    get_equipment_unit,
    get_jurisdiction,
    get_procurement,
    get_voting_system,
    make_election_official_headers,
    make_lab_agent_headers,
    record_usage,
    set_clock,
    setup_certified_jurisdiction,
    setup_election_definition,
    setup_procurement,
    start_work_order,
    store_layout,
    store_unit,
    transition_certificate,
    transition_election_definition,
    transition_equipment_unit,
    transition_la_test,
    validate_error,
    validate_success,
    withdraw_campaign,
)

AUTHORITY = TEST_USERS["certification_authority_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _get_la_test(api, definition_id, la_test_id):
    data = validate_success(api.list_la_tests(definition_id, AUDITOR))
    matches = [t for t in data if t["id"] == la_test_id]
    assert len(matches) == 1, f"L&A test {la_test_id} not found in {data!r}"
    return matches[0]


def _get_unit_work_order(api, unit_id, work_order_id):
    data = validate_success(api.list_unit_work_orders(unit_id, AUDITOR))
    matches = [w for w in data if w["id"] == work_order_id]
    assert len(matches) == 1, f"work order {work_order_id} not found in {data!r}"
    return matches[0]


def test_withdrawn_campaign_locks_all_transitions(api):
    """PRD §3.2: "The vendor may withdraw from `SUBMITTED` or
    `DEFICIENCIES_FILED` (`WITHDRAWN`) without precondition. Both stamp
    `completed_at`. `CERTIFIED`, `DENIED`, and `WITHDRAWN` are all terminal."
    PRD §2.7: "8. **State machine legality** — the target's state machine
    must permit the requested transition from its current state; terminal
    rows reject every further transition, and a `to_state` naming a real
    state that is unreachable from the current state fails here with
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/withdrawn_campaign_locks_all_transitions
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab = create_test_laboratory()
    campaign = create_campaign(system["id"], lab["id"])
    withdraw_campaign(campaign["id"])

    resp = api.transition_certification_campaign(
        campaign["id"],
        campaign_transition_payload("IN_TEST"),
        make_lab_agent_headers(lab["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    data = get_campaign(campaign["id"])
    assert data["status"] == "WITHDRAWN"
    assert data["completed_at"] is not None


def test_certify_mints_certificate_and_fields_system(api):
    """PRD §3.3: "its `scope` is `STATE` when the campaign carried a
    `state_code` and `FEDERAL` otherwise, its `state_code` and
    `guidelines_baseline` are copied from the campaign, and `issued_at` is
    stamped from the logical clock. `expires_at` is exactly 730 days after
    `issued_at`. Certificates are born `ACTIVE`."
    PRD §3.2: "if this is the system's first active certificate, the voting
    system itself is promoted from `REGISTERED` to `FIELDED` with a version
    increment."

    Design: Corner/state_machines/certify_mints_certificate_and_fields_system
    """
    set_clock("2026-09-01T00:00:00Z")
    system = create_voting_system()
    lab = create_test_laboratory()
    campaign = create_campaign(
        system["id"], lab["id"], guidelines_baseline="VVSG_2_0", state_code="CA"
    )
    begin_campaign_testing(campaign["id"], lab["id"])
    certify_campaign(campaign["id"])

    cert = get_certificate_for_campaign(campaign["id"])
    assert cert["scope"] == "STATE"
    assert cert["state_code"] == "CA"
    assert cert["guidelines_baseline"] == "VVSG_2_0"
    assert cert["status"] == "ACTIVE"
    assert cert["issued_at"].startswith("2026-09-01")
    assert cert["expires_at"].startswith("2028-08-31"), (
        f"expires_at is exactly 730 days after issued_at, got {cert['expires_at']!r}"
    )
    assert cert["voting_system_id"] == system["id"]
    assert cert["campaign_id"] == campaign["id"]
    assert get_voting_system(system["id"])["status"] == "FIELDED"


def test_non_listed_transitions_rejected(api):
    """PRD §2.7: "8. **State machine legality** — the target's state machine
    must permit the requested transition from its current state; terminal
    rows reject every further transition, and a `to_state` naming a real
    state that is unreachable from the current state fails here with
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/non_listed_transitions_rejected
    """
    base = setup_procurement("ACCEPTED")
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    jur_id = base["jurisdiction"]["id"]
    ed1 = create_election_definition(jur_id, base["procurement"]["id"],
                                     acting_official_id=off1)
    store_layout(ed1["id"], off1)
    transition_election_definition(ed1["id"], "PROGRAMMED", off1)
    la_test = create_la_test(ed1["id"], off1)
    certify_la_test(la_test["id"], off2)
    ed2 = create_election_definition(jur_id, base["procurement"]["id"],
                                     acting_official_id=off1,
                                     name="2026 Backup", precinct_count=1)
    proc2 = create_procurement(
        jur_id, base["system"]["id"], base["certificate"]["id"],
        acting_official_id=off1, quantity=1, unit_price_cents=1000,
    )

    resp = api.transition_election_definition(
        ed2["id"], {"to_state": "LOCKED"}, make_election_official_headers(off1)
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api.transition_procurement(
        proc2["id"], {"to_state": "ACCEPTED"}, make_election_official_headers(off1)
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api.transition_la_test(
        la_test["id"], {"to_state": "CHALLENGED"}, make_election_official_headers(off2)
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert get_election_definition(ed2["id"])["status"] == "DRAFT"
    assert get_procurement(proc2["id"])["status"] == "PLACED"
    assert _get_la_test(api, ed1["id"], la_test["id"])["status"] == "CERTIFIED"


def test_closed_election_definition_locks_transitions(api):
    """PRD §3.5: "Closing (`CANVASSING` → `CLOSED`) requires every
    post-election audit of the definition to be terminal — `CLOSED_CONFIRMED`
    or `CLOSED_ESCALATED` — otherwise `ERR_AUDIT_OPEN` (§3.10)."
    PRD §2.7: "8. **State machine legality** — the target's state machine
    must permit the requested transition from its current state; terminal
    rows reject every further transition, and a `to_state` naming a real
    state that is unreachable from the current state fails here with
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/closed_election_definition_locks_transitions
    """
    base = setup_election_definition("CANVASSING")
    off1 = base["officials"][0]["id"]
    ed_id = base["definition"]["id"]

    closed = transition_election_definition(ed_id, "CLOSED", off1)
    assert closed["status"] == "CLOSED", "the audit set is empty, so nothing blocks"

    resp = api.transition_election_definition(
        ed_id, {"to_state": "CANCELLED", "reason": "late cancel"},
        make_election_official_headers(off1),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_election_definition(ed_id)["status"] == "CLOSED"


def test_la_retest_loop_recomputes_and_clears_certifier(api):
    """PRD §3.6: "A challenged test is reopened (`CHALLENGED` → `CONDUCTED`)
    with fresh `scanned_tallies` whose key set equals `expected_tallies`
    (`ERR_INVALID_TALLIES`); reopening recomputes `total_discrepancy`,
    `discrepancy_bp`, and `result` from the new tallies and clears
    `certified_by` to null. The retest loop may repeat until certification."

    Design: Corner/state_machines/la_retest_loop_recomputes_and_clears_certifier
    """
    base = setup_election_definition("PROGRAMMED")
    off1 = base["officials"][0]["id"]
    off2 = base["officials"][1]["id"]
    ed_id = base["definition"]["id"]
    la_test = create_la_test(
        ed_id, off1,
        expected_tallies={"PRES": 12000, "SEN": 8000},
        scanned_tallies={"PRES": 12000, "SEN": 7500},
    )
    assert la_test["result"] == "FAIL", "discrepancy 500 -> 500*10000 > 50*20000"

    transition_la_test(la_test["id"], "CHALLENGED", off2)
    reopened = transition_la_test(
        la_test["id"], "CONDUCTED", off1,
        scanned_tallies={"PRES": 12000, "SEN": 8000},
    )
    assert reopened["status"] == "CONDUCTED"
    assert reopened["result"] == "PASS"
    assert reopened["total_discrepancy"] == 0
    assert reopened["certified_by"] is None


def test_certificate_revoke_cancels_procurements_and_releases_budget(api):
    """PRD §3.3: "Moving a certificate to `REVOKED` from either `ACTIVE` or
    `SUSPENDED` (with a `reason`) cancels every procurement pinning that
    certificate that is still in `PLACED`, `DELIVERED`, or
    `ACCEPTANCE_TESTING`: each such procurement becomes `CANCELLED` with
    `status_reason` set to `CERTIFICATE_REVOKED`, and each cancellation
    releases its encumbrance per §2.8 (`encumbered_cents` down by the
    procurement's `total_price_cents`, `available_cents` up by the same
    amount, jurisdiction `version` incremented once per affected jurisdiction
    per procurement release)."

    Design: Corner/state_machines/certificate_revoke_cancels_procurements_and_releases_budget
    """
    base = setup_procurement("PLACED")
    cert_id = base["certificate"]["id"]
    proc_id = base["procurement"]["id"]
    jur_id = base["jurisdiction"]["id"]

    transition_certificate(cert_id, "REVOKED", reason="state decertification")
    assert get_certificate(cert_id)["status"] == "REVOKED"
    procurement = get_procurement(proc_id)
    assert procurement["status"] == "CANCELLED"
    assert procurement["status_reason"] == "CERTIFICATE_REVOKED"
    jurisdiction = get_jurisdiction(jur_id)
    assert jurisdiction["available_cents"] == 100_000_000
    assert jurisdiction["encumbered_cents"] == 0
    assert jurisdiction["spent_cents"] == 0
    assert_jurisdiction_ledger_invariant(jurisdiction)


def test_unit_retire_aborts_open_work_orders(api):
    """PRD §3.7: "Retirement (`IN_SERVICE` or `IN_STORAGE` → `RETIRED`) is a
    jurisdiction official's act requiring `custody_status` `SECURED`
    (`ERR_UNIT_UNSEALED`), and it likewise aborts all open work orders of the
    unit."
    PRD §3.8: "`COMPLETED` and `ABORTED` are terminal."

    Design: Corner/state_machines/unit_retire_aborts_open_work_orders
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    unit = create_equipment_unit(
        base["jurisdiction"]["id"], base["system"]["id"], off1, serial_number="SN-1001"
    )
    wo = create_work_order(unit["id"], off1, work_type="PREVENTIVE")

    transition_equipment_unit(
        unit["id"], "RETIRED", make_election_official_headers(off1)
    )
    assert get_equipment_unit(unit["id"])["operational_status"] == "RETIRED"
    wo_after = _get_unit_work_order(api, unit["id"], wo["id"])
    assert wo_after["status"] == "ABORTED", "cascade aborts the open order"

    resp = api.transition_work_order(
        wo["id"], {"to_state": "IN_PROGRESS"}, make_election_official_headers(off1)
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_store_outside_band_records_excursion_but_succeeds(api):
    """PRD §3.7: "Storing (`IN_SERVICE` → `IN_STORAGE`) requires the payload
    pair `storage_temperature_c` and `storage_humidity_pct`
    (`ERR_INVALID_REQUEST` when absent); a temperature outside 10 to 35
    degrees Celsius or a humidity outside 20 to 70 percent increments
    `storage_excursion_count` by 1, but the store transition still succeeds."

    Design: Corner/state_machines/store_outside_band_records_excursion_but_succeeds
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    unit = create_equipment_unit(
        base["jurisdiction"]["id"], base["system"]["id"], off1, serial_number="SN-1001"
    )
    deploy_unit(unit["id"], off1)

    stored = store_unit(unit["id"], off1, storage_temperature_c=45,
                        storage_humidity_pct=40)
    assert stored["operational_status"] == "IN_STORAGE", "the store still succeeds"
    assert stored["storage_excursion_count"] == 1, "45C is outside 10..35"

    deploy_unit(unit["id"], off1)
    stored = store_unit(unit["id"], off1, storage_temperature_c=20,
                        storage_humidity_pct=40)
    assert stored["storage_excursion_count"] == 1, (
        "an in-band store does not increment the counter further"
    )


def test_work_order_completion_applies_typed_effects(api):
    """PRD §3.8: "A `BATTERY_REPLACEMENT` resets `battery_cycles` to 0. A
    `PREVENTIVE` order resets `storage_excursion_count` to 0."
    PRD §3.8: "In all cases the unit's `operational_status` is restored from
    `pre_maintenance_status` and `pre_maintenance_status` is cleared to null."

    Design: Corner/state_machines/work_order_completion_applies_typed_effects
    """
    base = setup_certified_jurisdiction()
    off1 = base["officials"][0]["id"]
    jur_id = base["jurisdiction"]["id"]
    sys_id = base["system"]["id"]
    unit_a = create_equipment_unit(jur_id, sys_id, off1, serial_number="SN-1001")
    deploy_unit(unit_a["id"], off1)
    record_usage(unit_a["id"], off1, 120)
    unit_b = create_equipment_unit(jur_id, sys_id, off1, serial_number="SN-1002")
    deploy_unit(unit_b["id"], off1)
    store_unit(unit_b["id"], off1, storage_temperature_c=50, storage_humidity_pct=40)

    wo_a = create_work_order(unit_a["id"], off1, work_type="BATTERY_REPLACEMENT")
    start_work_order(wo_a["id"], off1)
    wo_b = create_work_order(unit_b["id"], off1, work_type="PREVENTIVE")
    start_work_order(wo_b["id"], off1)

    complete_work_order(wo_a["id"], off1, resolution_note="battery pack swapped")
    complete_work_order(wo_b["id"], off1, resolution_note="storage audit")

    unit_a = get_equipment_unit(unit_a["id"])
    assert unit_a["battery_cycles"] == 0, "BATTERY_REPLACEMENT reset"
    assert unit_a["operational_status"] == "IN_SERVICE", "pre-maintenance status restored"
    assert unit_a["pre_maintenance_status"] is None
    unit_b = get_equipment_unit(unit_b["id"])
    assert unit_b["storage_excursion_count"] == 0, "PREVENTIVE reset"
    assert unit_b["operational_status"] == "IN_STORAGE"
    assert unit_b["pre_maintenance_status"] is None
