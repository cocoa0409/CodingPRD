"""Transitive cascades from sterilization failure and incident escalation."""
from test_helpers import (
    E,
    api_client,
    create_sterilization_cycle_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    INTAKE,
    MANAGER,
    READER,
    TECHNICIAN,
    certify,
    create_appointment,
    create_jurisdiction,
    create_piercer,
    create_store,
    file_and_triage_incident,
    get_appointment,
    get_lot,
    get_piercer,
    get_store,
    get_success_data,
    set_clock,
    setup_customer_with_active_consent,
    setup_cycle_and_lot,
    setup_full_service,
    setup_ready_appointment,
    setup_store_with_certified_piercer,
    setup_store_with_failed_cycle,
)


def _second_cycle(store_id, store_version, autoclave_unit_id, lot_number):
    """Open a second sterilization cycle on its own autoclave unit and bind a lot to it."""
    cycle = get_success_data(
        api_client.create_sterilization_cycle(
            create_sterilization_cycle_payload(
                store_id,
                autoclave_unit_id=autoclave_unit_id,
                cycle_start_at="2026-08-31T08:00:00Z",
                cycle_end_at="2026-08-31T08:45:00Z",
            ),
            TECHNICIAN,
        )
    )
    lot = get_success_data(
        api_client.create_cartridge_lot(
            {
                "store_location_id": store_id,
                "sterilization_cycle_id": cycle["id"],
                "lot_number": lot_number,
                "site_type": "LOBE",
                "units_received": 50,
                "expiration_date": "2027-01-01T00:00:00Z",
                "expected_store_version": store_version,
            },
            MANAGER,
        )
    )
    return cycle, lot


def test_sterilization_failure_cascades_store_piercer_and_inventory(api):
    """PRD §2.7: "A cycle closes as `FAILED` when `temperature_celsius` is below 134.0 or
    `biological_indicator_passed` is false, and the failure propagates in a four-step chain:
    every bound `CartridgeLot` becomes `QUARANTINED`; for each such lot the owning store's
    `open_incident_count` increases by one and that store's posture is recomputed; every
    `Piercer` whose `home_store_id` equals the lot's store and whose `status` is `ACTIVE`
    loses 20 points from `eligibility_score`".

    Design: Difficulty/transitive_cascade/sterilization_failure_cascade_to_customer_flag
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(store_overrides={"piercing_room_count": 1})
    store_id = ctx["store"]["id"]
    piercer_id = ctx["piercer"]["id"]

    assert ctx["store"]["open_incident_count"] == 0
    assert get_piercer(piercer_id)["eligibility_score"] == 100

    store_version = get_store(store_id)["version"]
    cycle, lot = _second_cycle(store_id, store_version, "AUTO-2", "L-FAIL")
    assert lot["status"] == "AVAILABLE"

    failed = validate_success(
        api.complete_sterilization_cycle(
            cycle["id"], {"temperature_celsius": 124.0, "biological_indicator_passed": False},
            TECHNICIAN,
        ),
        200,
    )

    assert failed["status"] == "FAILED"
    assert get_lot(lot["id"])["status"] == "QUARANTINED"
    assert get_store(store_id)["open_incident_count"] == 1
    assert get_piercer(piercer_id)["eligibility_score"] == 80


def test_incident_escalation_cascade_restricts_store_and_cancels_siblings(api):
    """PRD §3.7: "Triage is also the origin of a three-step chain: a triaged incident that is
    then escalated cascades the linked session's `healing_status` to `FAILED`, increases the
    owning store's `open_incident_count` once per affected session, recomputes that store's
    posture, and — when the recomputed posture becomes `RESTRICTED` — cancels every appointment
    at that store whose status is `BOOKED` or `CONFIRMED`."

    Design: Difficulty/transitive_cascade/incident_escalation_cascade_to_sibling_appointment_cancellation
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(store_overrides={"piercing_room_count": 2})
    store_id = ctx["store"]["id"]

    # Two unrelated MINOR incidents put the store one incident away from restriction.
    for day in ("2026-09-05T00:00:00Z", "2026-09-06T00:00:00Z"):
        file_and_triage_incident(ctx["session"], severity="MINOR", reported_at=day)
    near_threshold = get_store(store_id)
    assert near_threshold["open_incident_count"] == 2
    assert near_threshold["compliance_posture"] == "OPEN"

    # A sibling appointment is open at the store before the third incident lands.
    sibling = setup_ready_appointment(
        store_id, ctx["customer"]["id"], ctx["piercer"]["id"], ctx["jurisdiction"]["id"],
        slot_start="2026-09-01T14:00:00Z", slot_end="2026-09-01T14:30:00Z",
    )
    assert sibling["status"] == "CONFIRMED"

    severe = file_and_triage_incident(
        ctx["session"], severity="SEVERE", reported_at="2026-09-10T00:00:00Z"
    )
    escalated = validate_success(api.escalate_incident(severe["id"], COMPLIANCE), 200)
    assert escalated["escalation_status"] == "ESCALATED"

    from test_helpers.fixtures import get_session
    assert get_session(ctx["session"]["id"])["healing_status"] == "FAILED"

    restricted = get_store(store_id)
    assert restricted["open_incident_count"] == 3
    assert restricted["compliance_posture"] == "RESTRICTED"
    assert get_appointment(sibling["id"])["status"] == "CANCELLED"


def test_starting_service_is_refused_at_a_restricted_store(api):
    """PRD §3.4: "Next the store's `compliance_posture` must be `OPEN`, otherwise
    `ERR_STORE_POSTURE_BLOCKS_SERVICE` at HTTP 409."
    PRD §2.7: "While a store's posture is `RESTRICTED` or `FROZEN`, that store may not begin a
    new service; the refusal is `ERR_STORE_POSTURE_BLOCKS_SERVICE` with HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/start_service_blocked_by_restricted_store_posture
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(store_overrides={"piercing_room_count": 1})
    store_id = ctx["store"]["id"]
    pid = ctx["piercer"]["id"]

    # A failed cycle restricts the store, which then blocks any new service there.
    store_version = get_store(store_id)["version"]
    cycle, _ = _second_cycle(store_id, store_version, "AUTO-3", "L-RESTRICT")
    validate_success(
        api.complete_sterilization_cycle(
            cycle["id"], {"temperature_celsius": 124.0, "biological_indicator_passed": False},
            TECHNICIAN,
        ),
        200,
    )

    appointment = setup_ready_appointment(
        store_id, ctx["customer"]["id"], pid, ctx["jurisdiction"]["id"],
        slot_start="2026-09-01T14:00:00Z", slot_end="2026-09-01T14:30:00Z",
    )
    api.set_clock("2026-09-01T14:00:00Z", COMPLIANCE)
    validate_success(api.check_in_appointment(appointment["id"], INTAKE), 200)
    observed = get_appointment(appointment["id"])
    # `/screen` moves the appointment to SCREENED and runs the evaluator as part
    # of the same step (PRD §3.4), so no separate evaluation is needed.
    validate_success(
        api.screen_appointment(
            appointment["id"],
            {
                "anatomy_sites_examined": ["LOBE"],
                "contraindication_codes": [],
                "expected_appointment_version": observed["version"],
            },
            {"X-User-ID": pid, "X-User-Role": "Piercer"},
        ),
        200,
    )

    assert get_store(store_id)["compliance_posture"] == "RESTRICTED"

    res = api.start_service(appointment["id"], {"X-User-ID": pid, "X-User-Role": "Piercer"})
    validate_error(res, E.STORE_POSTURE_BLOCKS_SERVICE, expected_status=409)
    assert get_appointment(appointment["id"])["status"] == "SCREENED"


def test_starting_service_is_refused_when_the_certification_has_expired(api):
    """PRD §3.4: "Next the assigned piercer's `status` must be `ACTIVE` and the governing
    certification resolved through `active_certification_id` must have `status` `VALID`,
    otherwise `ERR_PIERCER_NOT_CERTIFIED` at HTTP 422."
    PRD §2.10: "A certification whose `status` is `EXPIRING_SOON` and whose clock passes
    `expires_at` also moves automatically to `EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/session_open_blocked_by_certification_expiry
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction, store, piercer, certification = setup_store_with_certified_piercer(
        store_overrides={"piercing_room_count": 1},
        certification_overrides={"issued_at": "2025-08-15T00:00:00Z", "expires_at": "2026-08-15T00:00:00Z"},
    )
    customer, _ = setup_customer_with_active_consent(jurisdiction["id"])
    appointment = setup_ready_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"]
    )
    api.set_clock("2026-09-01T09:00:00Z", COMPLIANCE)
    validate_success(api.check_in_appointment(appointment["id"], INTAKE), 200)
    observed = get_appointment(appointment["id"])
    validate_success(
        api.screen_appointment(
            appointment["id"],
            {
                "anatomy_sites_examined": ["LOBE"],
                "contraindication_codes": [],
                "expected_appointment_version": observed["version"],
            },
            {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"},
        ),
        200,
    )
    assert get_success_data(api.get_certification(certification["id"], READER))["status"] == "EXPIRED"

    res = api.start_service(
        appointment["id"], {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"}
    )
    validate_error(res, E.PIERCER_NOT_CERTIFIED, expected_status=422)
    assert get_appointment(appointment["id"])["status"] == "SCREENED"


def test_open_incident_count_reconciles_after_an_escalation(api):
    """PRD §2.7: "this count is the store's `open_incident_count`".
    PRD §2.7: "Posture is recomputed whenever any incident escalation status changes at the
    store, whenever any sterilization cycle status changes at the store, and whenever a
    cartridge lot is registered against the store."

    Design: Corner/cross_cutting/store_open_incident_count_reconciles_after_escalation
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_store_with_failed_cycle(store_overrides={"piercing_room_count": 2})
    store_id = ctx["store"]["id"]
    # The failed cycle already contributed one open incident.
    assert ctx["store"]["open_incident_count"] == 1

    escalate = file_and_triage_incident(
        ctx["session"], severity="SEVERE", reported_at="2026-09-10T00:00:00Z"
    )
    validate_success(api.escalate_incident(escalate["id"], COMPLIANCE), 200)

    reconciled = get_store(store_id)
    assert reconciled["open_incident_count"] == 2

    # The store's incident listing returns the incident rows reachable through
    # its sessions, of which there is exactly one here (PRD §2.7 counts the
    # failed cycle's lot exposure into `open_incident_count`, but it is not an
    # IncidentReport row and so does not appear in the listing).
    data, meta = validate_paginated(api.list_store_incidents(store_id, READER))
    assert meta["total_count"] == 1
    assert len(data) == 1


def test_every_active_piercer_of_the_owning_store_loses_twenty_points(api):
    """PRD §2.7: "every `Piercer` whose `home_store_id` equals the lot's store and whose `status`
    is `ACTIVE` loses 20 points from `eligibility_score`".
    PRD §2.10: "The score starts from a base of 100 (`BASE_SCORE`)."

    Design: Difficulty/transitive_cascade/sterilization_failure_cascade_to_customer_flag
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(store_overrides={"piercing_room_count": 1})
    store_id = ctx["store"]["id"]

    # Two more ACTIVE piercers at the same store, and one rostered elsewhere.
    second = create_piercer(store_id, full_name="Second Piercer")
    certify(second["id"])
    other_store = create_store(ctx["jurisdiction"]["id"], name="Springfield", piercing_room_count=1)
    outsider = create_piercer(other_store["id"], full_name="Outsider Piercer")
    certify(outsider["id"])

    assert get_piercer(ctx["piercer"]["id"])["eligibility_score"] == 100
    assert get_piercer(second["id"])["eligibility_score"] == 100
    assert get_piercer(outsider["id"])["eligibility_score"] == 100

    store_version = get_store(store_id)["version"]
    cycle, _ = _second_cycle(store_id, store_version, "AUTO-4", "L-DROP")
    validate_success(
        api.complete_sterilization_cycle(
            cycle["id"], {"temperature_celsius": 124.0, "biological_indicator_passed": False},
            TECHNICIAN,
        ),
        200,
    )

    assert get_piercer(ctx["piercer"]["id"])["eligibility_score"] == 80
    assert get_piercer(second["id"])["eligibility_score"] == 80
    # A piercer rostered to another store is untouched by this cascade.
    assert get_piercer(outsider["id"])["eligibility_score"] == 100


def test_only_severe_incidents_may_be_escalated(api):
    """PRD §3.7: "A `TRIAGED` incident may be escalated further by a `ComplianceOfficer` only
    when its `severity` is `SEVERE` or `MEDICAL_EMERGENCY`, which moves `escalation_status` to
    `ESCALATED` and runs the cascade above."
    PRD §3.7: "A `TRIAGED` incident may instead be resolved directly, but only when its
    `severity` is `MINOR` or `MODERATE`, which moves `escalation_status` to `RESOLVED`".

    Design: Difficulty/transitive_cascade/incident_escalation_cascade_to_sibling_appointment_cancellation
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    mild = file_and_triage_incident(ctx["session"], severity="MINOR", reported_at="2026-09-10T00:00:00Z")
    assert mild["escalation_status"] == "TRIAGED"

    res = api.escalate_incident(mild["id"], COMPLIANCE)
    validate_error(res, E.INVALID_STATE, expected_status=409)

    from test_helpers.fixtures import get_incident
    assert get_incident(mild["id"])["escalation_status"] == "TRIAGED"
    # The store posture was not disturbed by the refused escalation.
    assert get_store(ctx["store"]["id"])["open_incident_count"] == 1


def test_a_frozen_store_also_blocks_starting_service(api):
    """PRD §2.7: "While a store's posture is `RESTRICTED` or `FROZEN`, that store may not begin
    a new service; the refusal is `ERR_STORE_POSTURE_BLOCKS_SERVICE` with HTTP 409."
    PRD §2.7: "Freezing drives a store in `status` `OPEN` or `RESTRICTED` to `compliance_posture`
    `FROZEN`".

    Design: Difficulty/cross_entity_state_dependency/start_service_blocked_by_restricted_store_posture
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(store_overrides={"piercing_room_count": 2})
    store_id = ctx["store"]["id"]
    pid = ctx["piercer"]["id"]
    headers = {"X-User-ID": pid, "X-User-Role": "Piercer"}

    # Build a screenable appointment before the freeze cancels anything open.
    # The clock advances to 14:00 to open its check-in window, so the slot sits
    # later still and does not trip the automatic NO_SHOW boundary.
    appointment = setup_ready_appointment(
        store_id, ctx["customer"]["id"], pid, ctx["jurisdiction"]["id"],
        slot_start="2026-09-01T16:00:00Z", slot_end="2026-09-01T16:30:00Z",
    )
    api.set_clock("2026-09-01T16:00:00Z", COMPLIANCE)
    validate_success(api.check_in_appointment(appointment["id"], INTAKE), 200)
    observed = get_appointment(appointment["id"])
    validate_success(
        api.screen_appointment(
            appointment["id"],
            {
                "anatomy_sites_examined": ["LOBE"],
                "contraindication_codes": [],
                "expected_appointment_version": observed["version"],
            },
            headers,
        ),
        200,
    )

    frozen = validate_success(api.freeze_store(store_id, COMPLIANCE), 200)
    assert frozen["compliance_posture"] == "FROZEN"

    res = api.start_service(appointment["id"], headers)
    validate_error(res, E.STORE_POSTURE_BLOCKS_SERVICE, expected_status=409)


def test_opening_a_session_explicitly_is_blocked_at_a_restricted_store(api):
    """PRD §3.5: "Opening a session is gated by the same store-posture rule that guards
    start-of-service: a store whose `compliance_posture` is `RESTRICTED` or `FROZEN` cannot open
    a new session, and the refusal is `ERR_STORE_POSTURE_BLOCKS_SERVICE` at HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/session_open_blocked_by_certification_expiry
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(store_overrides={"piercing_room_count": 2})
    store_id = ctx["store"]["id"]

    store_version = get_store(store_id)["version"]
    cycle, _ = _second_cycle(store_id, store_version, "AUTO-5", "L-BLOCK")
    validate_success(
        api.complete_sterilization_cycle(
            cycle["id"], {"temperature_celsius": 124.0, "biological_indicator_passed": False},
            TECHNICIAN,
        ),
        200,
    )
    assert get_store(store_id)["compliance_posture"] == "RESTRICTED"

    from test_helpers.fixtures import open_explicit_session
    appointment, response = open_explicit_session(
        ctx, slot_start="2026-09-01T15:00:00Z", slot_end="2026-09-01T15:30:00Z"
    )
    validate_error(response, E.STORE_POSTURE_BLOCKS_SERVICE, expected_status=409)