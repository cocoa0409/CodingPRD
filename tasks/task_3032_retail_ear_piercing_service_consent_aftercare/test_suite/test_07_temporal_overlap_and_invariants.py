"""Interval semantics and the conserved quantities maintained across compensating actions."""
from test_helpers import (
    E,
    api_client,
    create_cartridge_lot_payload,
    create_sterilization_cycle_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    INTAKE,
    MANAGER,
    READER,
    TECHNICIAN,
    certify,
    create_jurisdiction,
    create_piercer,
    create_store,
    get_lot,
    get_store,
    get_success_data,
    set_clock,
    setup_customer_with_active_consent,
    setup_in_service_saga,
    setup_ready_appointment,
    get_appointment,
)


def test_adjacent_appointment_slots_are_admitted(api):
    """PRD §3.3: "Slot geometry follows a half-open convention: the occupied interval is
    `[slot_start_at, slot_end_at)`."
    PRD §3.3: "Adjacency is permitted — an appointment starting at the exact instant another's
    slot ends is fine — and every supplied slot bound is truncated by flooring to the containing
    minute before comparison, so sub-minute differences are invisible."

    Design: Difficulty/resource_temporal_overlap/piercer_adjacency_admitted_on_half_open_slots
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=2)
    piercer = create_piercer(store["id"])
    certify(piercer["id"])
    customer, _ = setup_customer_with_active_consent(jurisdiction["id"])

    first = setup_ready_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"],
        slot_start="2026-09-01T09:00:00Z", slot_end="2026-09-01T09:30:00Z",
    )
    assert first["status"] == "CONFIRMED"

    second = setup_ready_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"],
        slot_start="2026-09-01T09:30:00Z", slot_end="2026-09-01T10:00:00Z",
    )
    assert second["status"] == "CONFIRMED"


def test_adjacent_autoclave_cycles_are_rejected_on_closed_intervals(api):
    """PRD §2.7: "The cycle occupies the closed interval from `cycle_start_at` to
    `cycle_end_at`, both endpoints inclusive."
    PRD §2.7: "Two cycles on the same autoclave unit whose closed intervals merely touch — one
    ending at the exact instant the next begins — do still overlap and are rejected, because
    both endpoints of the interval are inclusive".

    Design: Difficulty/resource_temporal_overlap/autoclave_adjacency_rejected_on_closed_cycle_intervals
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=1)

    first = validate_success(
        api.create_sterilization_cycle(
            create_sterilization_cycle_payload(
                store["id"],
                autoclave_unit_id="AUTO-1",
                cycle_start_at="2026-09-01T08:00:00Z",
                cycle_end_at="2026-09-01T08:45:00Z",
            ),
            TECHNICIAN,
        ),
        201,
    )
    assert first["status"] == "IN_PROGRESS"

    res = api.create_sterilization_cycle(
        create_sterilization_cycle_payload(
            store["id"],
            autoclave_unit_id="AUTO-1",
            cycle_start_at="2026-09-01T08:45:00Z",
            cycle_end_at="2026-09-01T09:30:00Z",
        ),
        TECHNICIAN,
    )
    validate_error(res, E.AUTOCLAVE_CYCLE_OVERLAP, expected_status=409)


def test_cartridge_units_are_conserved_across_quarantine_and_release(api):
    """PRD §2.7: "Its availability is governed by the calculation `cartridge_lot_availability`:
    `units_available` equals `units_received` minus `units_consumed` minus `units_quarantined`,
    floored at 0."
    PRD §2.7: "When its bound cycle enters `RELEASED` or `PASSED` and the lot's `expiration_date`
    is later than the current clock instant, the lot returns to `AVAILABLE` with `units_available`
    set to `units_quarantined` and `units_quarantined` reset to 0."

    Design: Difficulty/compensating_invariant/cartridge_unit_balance_conserved_across_quarantine_and_release
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=2)

    cycle = validate_success(
        api.create_sterilization_cycle(
            create_sterilization_cycle_payload(store["id"], autoclave_unit_id="AUTO-1"), TECHNICIAN
        ),
        201,
    )
    store_version = get_store(store["id"])["version"]
    lot = validate_success(
        api.create_cartridge_lot(
            create_cartridge_lot_payload(store["id"], cycle["id"], store_version, units_received=50),
            MANAGER,
        ),
        201,
    )
    validate_success(
        api.complete_sterilization_cycle(
            cycle["id"], {"temperature_celsius": 135.0, "biological_indicator_passed": True}, TECHNICIAN
        ),
        200,
    )
    validate_success(api.quarantine_sterilization_cycle(cycle["id"], COMPLIANCE), 200)

    quarantined = get_lot(lot["id"])
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["units_quarantined"] == 50
    assert quarantined["units_available"] == 0

    validate_success(api.release_sterilization_cycle(cycle["id"], COMPLIANCE), 200)

    released = get_lot(lot["id"])
    assert released["status"] == "AVAILABLE"
    assert released["units_available"] == 50
    assert released["units_quarantined"] == 0
    assert released["units_consumed"] == 0
    assert (
        released["units_available"] + released["units_consumed"] + released["units_quarantined"]
        == released["units_received"]
    )


def test_customer_balance_is_conserved_across_refund_settlement_and_reopen(api):
    """PRD §3.7: "the customer's `refunded_cents` increases by `refund_amount_cents`, and the
    customer's `retained_cents` increases by the session's `net_fee_cents` minus
    `refund_amount_cents`".
    PRD §3.7: "a `RESOLVED` incident may be reopened by a `ComplianceOfficer` supplying a
    `reopen_reason`, provided `reported_at` is within the reopen window".

    Design: Difficulty/compensating_invariant/refund_charge_balance_conserved_across_issue_and_reopen
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers.fixtures import file_and_resolve_incident, get_customer, get_incident, setup_full_service

    ctx = setup_full_service()
    session = ctx["session"]
    incident = file_and_resolve_incident(session, severity="SEVERE")

    # PRD §3.7 ties reopening to the `RESOLVED` status, so the round trip must
    # reopen before settlement, re-triage, re-resolve, and only then settle.
    reopened = validate_success(
        api.reopen_incident(
            incident["id"],
            {"reopen_reason": "Customer reports recurrence within the reopen window."},
            COMPLIANCE,
        ),
        200,
    )
    assert reopened["escalation_status"] == "REOPENED"

    retriaged = validate_success(api.triage_incident(incident["id"], COMPLIANCE), 200)
    assert retriaged["escalation_status"] == "TRIAGED"

    resolved_again = validate_success(
        api.escalate_incident(incident["id"], COMPLIANCE), 200
    )
    assert resolved_again["escalation_status"] == "ESCALATED"
    resolved_again = validate_success(
        api.resolve_incident(
            incident["id"], {"resolution_note": "Medical review complete."}, COMPLIANCE
        ),
        200,
    )
    assert resolved_again["escalation_status"] == "RESOLVED"

    settled = validate_success(
        api.issue_refund(incident["id"], {"refund_destination": "CARD"}, MANAGER), 200
    )
    assert settled["refund_status"] == "SETTLED"

    customer = get_customer(ctx["customer"]["id"])
    net_fee = session["net_fee_cents"]
    assert customer["refunded_cents"] + customer["retained_cents"] == net_fee
    assert customer["retained_cents"] == net_fee - customer["refunded_cents"]
    assert get_incident(incident["id"])["escalation_status"] == "REFUND_ISSUED"


def test_aborting_mid_service_compensates_the_piercer_session_slot(api):
    """PRD §3.5: "A `Piercer` aborting mid-procedure moves the appointment from `IN_SERVICE` to
    `CANCELLED`, decrements the piercer's `assigned_session_count`, moves the session's
    `service_status` to `ABORTED`, and quarantines the consumed cartridge by adding one to
    `units_quarantined` and subtracting one from `units_available`".

    Design: Corner/consistency_model/session_abort_compensates_the_piercer_session_slot
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_in_service_saga(store_overrides={"piercing_room_count": 1})
    assert get_success_data(api.get_piercer(ctx["piercer"]["id"], READER))["assigned_session_count"] == 1

    aborted = validate_success(
        api.abort_appointment(
            ctx["appointment"]["id"],
            {"X-User-ID": ctx["piercer"]["id"], "X-User-Role": "Piercer"},
        ),
        200,
    )
    assert aborted["status"] == "CANCELLED"

    piercer = get_success_data(api.get_piercer(ctx["piercer"]["id"], READER))
    assert piercer["assigned_session_count"] == 0

    session = get_success_data(api.get_session(ctx["session"]["id"], READER))
    assert session["service_status"] == "ABORTED"
    assert session["healing_status"] == "HEALING"


def test_quarantine_scope_snapshots_the_bound_lots_available_stock(api):
    """PRD §2.7: "Quarantine exposure is measured when quarantine is applied by the calculation
    `quarantine_unit_exposure`: `quarantine_scope_units` is the sum of `units_available` over
    every `CartridgeLot` whose `sterilization_cycle_id` equals the quarantined cycle's `id` at
    that instant."

    Design: Corner/calculations/quarantine_scope_snapshots_bound_lot_stock
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers.fixtures import setup_full_service

    ctx = setup_full_service(store_overrides={"piercing_room_count": 1})
    lot_id = ctx["lot"]["id"]
    cycle_id = ctx["cycle"]["id"]
    assert ctx["lot"]["units_received"] == 50

    # The completed service drew two units: one when the session opened and one
    # more when it completed (PRD §3.5).
    before = get_lot(lot_id)
    assert before["units_consumed"] == 2
    assert before["units_available"] == 48

    quarantined = validate_success(
        api.quarantine_sterilization_cycle(cycle_id, COMPLIANCE), 200
    )
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["quarantine_scope_units"] == before["units_available"]
    assert quarantined["quarantine_scope_units"] == 48
    assert get_lot(lot_id)["status"] == "QUARANTINED"


def test_starting_a_second_session_while_one_is_live_is_refused(api):
    """PRD §3.4: "Finally the piercer's `assigned_session_count` must be 0, because a piercer
    may hold at most one session in `service_status` `IN_PROGRESS` across all stores, and a
    second concurrent session is refused with `ERR_PIERCER_SESSION_IN_PROGRESS` at HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/start_service_blocked_by_restricted_store_posture
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_in_service_saga(store_overrides={"piercing_room_count": 2})
    store_id = ctx["store"]["id"]
    pid = ctx["piercer"]["id"]

    # A second appointment is screened while the first session is still open.
    second = setup_ready_appointment(
        store_id, ctx["customer"]["id"], pid, ctx["jurisdiction"]["id"],
        slot_start="2026-09-01T14:00:00Z", slot_end="2026-09-01T14:30:00Z",
    )
    api.set_clock("2026-09-01T14:00:00Z", COMPLIANCE)
    api.set_clock("2026-09-01T14:00:00Z", COMPLIANCE)
    validate_success(api.check_in_appointment(second["id"], INTAKE), 200)
    observed = get_appointment(second["id"])
    validate_success(
        api.screen_appointment(
            second["id"],
            {
                "anatomy_sites_examined": ["LOBE"],
                "contraindication_codes": [],
                "expected_appointment_version": observed["version"],
            },
            {"X-User-ID": pid, "X-User-Role": "Piercer"},
        ),
        200,
    )

    res = api.start_service(second["id"], {"X-User-ID": pid, "X-User-Role": "Piercer"})
    validate_error(res, E.PIERCER_SESSION_IN_PROGRESS, expected_status=409)


def test_autoclave_unit_capacity_is_reserved_across_operating_cycles(api):
    """PRD §2.7: "A cycle starts `IN_PROGRESS` and may be closed as `PASSED` only when
    `temperature_celsius` is at least 134.0, `biological_indicator_passed` is true, and the
    closed cycle interval does not overlap another cycle on the same `autoclave_unit_id`".
    PRD §2.7: "A cycle closes as `FAILED` when `temperature_celsius` is below 134.0 or
    `biological_indicator_passed` is false".

    Design: Difficulty/resource_temporal_overlap/autoclave_adjacency_rejected_on_closed_cycle_intervals
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=1)

    first = validate_success(
        api.create_sterilization_cycle(
            create_sterilization_cycle_payload(
                store["id"],
                autoclave_unit_id="AUTO-1",
                cycle_start_at="2026-09-01T08:00:00Z",
                cycle_end_at="2026-09-01T08:45:00Z",
            ),
            TECHNICIAN,
        ),
        201,
    )
    # A disjoint interval on the same unit is admitted.
    other_unit = validate_success(
        api.create_sterilization_cycle(
            create_sterilization_cycle_payload(
                store["id"],
                autoclave_unit_id="AUTO-2",
                cycle_start_at="2026-09-01T08:00:00Z",
                cycle_end_at="2026-09-01T08:45:00Z",
            ),
            TECHNICIAN,
        ),
        201,
    )
    second = validate_success(
        api.create_sterilization_cycle(
            create_sterilization_cycle_payload(
                store["id"],
                autoclave_unit_id="AUTO-1",
                cycle_start_at="2026-09-01T09:00:00Z",
                cycle_end_at="2026-09-01T09:45:00Z",
            ),
            TECHNICIAN,
        ),
        201,
    )

    validate_success(
        api.complete_sterilization_cycle(
            first["id"], {"temperature_celsius": 135.0, "biological_indicator_passed": True}, TECHNICIAN
        ),
        200,
    )
    validate_success(
        api.complete_sterilization_cycle(
            second["id"], {"temperature_celsius": 124.0, "biological_indicator_passed": False}, TECHNICIAN
        ),
        200,
    )

    statuses = {
        first["id"]: get_success_data(api.get_sterilization_cycle(first["id"], READER))["status"],
        other_unit["id"]: get_success_data(api.get_sterilization_cycle(other_unit["id"], READER))["status"],
        second["id"]: get_success_data(api.get_sterilization_cycle(second["id"], READER))["status"],
    }
    assert statuses[first["id"]] == "PASSED"
    assert statuses[other_unit["id"]] == "IN_PROGRESS"
    assert statuses[second["id"]] == "FAILED"


def test_adjacent_slots_for_different_piercers_never_collide(api):
    """PRD §3.3: "Two appointments that are not `CANCELLED` may not overlap for the same
    `store_location_id` and the same `piercer_id`; the refusal is `ERR_SLOT_OVERLAP` with
    HTTP 409."
    PRD §3.3: "Separately, the store's physical capacity is enforced: the number of
    non-`CANCELLED` appointments at the same `store_location_id` whose half-open slots contain a
    common instant may not exceed that store's `piercing_room_count`".

    Design: Difficulty/resource_temporal_overlap/piercer_adjacency_admitted_on_half_open_slots
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=2)
    first_piercer = create_piercer(store["id"], full_name="First Piercer")
    certify(first_piercer["id"])
    second_piercer = create_piercer(store["id"], full_name="Second Piercer")
    certify(second_piercer["id"])
    customer, _ = setup_customer_with_active_consent(jurisdiction["id"])

    for piercer in (first_piercer, second_piercer):
        appointment = setup_ready_appointment(
            store["id"], customer["id"], piercer["id"], jurisdiction["id"],
            slot_start="2026-09-01T09:00:00Z", slot_end="2026-09-01T09:30:00Z",
        )
        assert appointment["status"] == "CONFIRMED"


def test_quarantine_release_preserves_the_unit_ledger_after_consumption(api):
    """PRD §2.7: "When its bound cycle enters `RELEASED` or `PASSED` and the lot's
    `expiration_date` is later than the current clock instant, the lot returns to `AVAILABLE`
    with `units_available` set to `units_quarantined` and `units_quarantined` reset to 0."
    PRD §2.7: "`units_available` equals `units_received` minus `units_consumed` minus
    `units_quarantined`, floored at 0."

    Design: Difficulty/compensating_invariant/cartridge_unit_balance_conserved_across_quarantine_and_release
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers.fixtures import setup_full_service

    ctx = setup_full_service(store_overrides={"piercing_room_count": 1})
    lot_id = ctx["lot"]["id"]
    cycle_id = ctx["cycle"]["id"]

    consumed_before = get_lot(lot_id)["units_consumed"]
    assert consumed_before > 0

    validate_success(api.quarantine_sterilization_cycle(cycle_id, COMPLIANCE), 200)
    quarantined = get_lot(lot_id)
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["units_available"] == 0

    validate_success(api.release_sterilization_cycle(cycle_id, COMPLIANCE), 200)
    released = get_lot(lot_id)

    assert released["status"] == "AVAILABLE"
    assert released["units_quarantined"] == 0
    assert released["units_consumed"] == consumed_before
    assert (
        released["units_available"] + released["units_consumed"] + released["units_quarantined"]
        == released["units_received"]
    )


def test_settlement_then_reopen_does_not_drift_the_customer_ledger(api):
    """PRD §3.7: "On success `escalation_status` becomes `REFUND_ISSUED` and `refund_status`
    becomes `SETTLED`; the customer's `refunded_cents` increases by `refund_amount_cents`, and
    the customer's `retained_cents` increases by the session's `net_fee_cents` minus
    `refund_amount_cents`."
    PRD §3.7: "increases the owning store's `open_incident_count` once per affected session".

    Design: Difficulty/compensating_invariant/refund_charge_balance_conserved_across_issue_and_reopen
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers.fixtures import file_and_resolve_incident, get_customer, setup_full_service

    ctx = setup_full_service()
    incident = file_and_resolve_incident(ctx["session"], severity="MODERATE")
    net_fee = ctx["session"]["net_fee_cents"]

    # PRD §3.7 ties reopening to `RESOLVED`, so reopen (and re-triage) before
    # settling: the `RESOLVED`/`REOPENED`/`TRIAGED` cycle then closes back onto a
    # settlement without disturbing the customer ledger.
    validate_success(
        api.reopen_incident(
            incident["id"], {"reopen_reason": "Recurrence reported."}, COMPLIANCE
        ),
        200,
    )
    retriaged = validate_success(api.triage_incident(incident["id"], COMPLIANCE), 200)
    assert retriaged["escalation_status"] == "TRIAGED"

    resolved_again = validate_success(
        api.resolve_incident(
            incident["id"], {"resolution_note": "Recurrence reviewed."}, COMPLIANCE
        ),
        200,
    )
    assert resolved_again["escalation_status"] == "RESOLVED"

    validate_success(
        api.issue_refund(incident["id"], {"refund_destination": "CARD"}, MANAGER), 200
    )
    settled_customer = get_customer(ctx["customer"]["id"])
    assert settled_customer["refunded_cents"] + settled_customer["retained_cents"] == net_fee

    after = get_customer(ctx["customer"]["id"])
    assert after["refunded_cents"] + after["retained_cents"] == net_fee
    # No monetary drift occurred across the settlement/reopen round trip.
    assert after["refunded_cents"] == settled_customer["refunded_cents"]