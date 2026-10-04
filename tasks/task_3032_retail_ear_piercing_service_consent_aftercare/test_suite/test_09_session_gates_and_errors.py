"""Session-opening gates, RBAC and optimistic concurrency."""
from test_helpers import (
    E,
    NON_EXISTENT_UUID,
    api_client,
    create_certification_payload,
    create_healing_outcome_payload,
    create_incident_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    INTAKE,
    MANAGER,
    READER,
    create_jurisdiction,
    create_piercer,
    create_store,
    get_store,
    open_explicit_session,
    set_clock,
    setup_cycle_and_lot,
    setup_full_service,
    setup_screened_appointment,
    setup_store_with_certified_piercer,
)


def test_expired_cartridge_lot_is_refused_when_a_session_is_opened(api):
    """PRD §3.5: "When a lot is supplied explicitly it must be `AVAILABLE`, must be bound to a
    `SterilizationCycle` whose `status` is `PASSED` or `RELEASED`, and must have an
    `expiration_date` later than the current clock instant; failing any of the three yields
    `ERR_CARTRIDGE_LOT_UNAVAILABLE` at HTTP 422".

    Design: Corner/errors/expired_cartridge_lot_rejected_on_session_create
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(store_overrides={"piercing_room_count": 2})
    store = ctx["store"]
    jurisdiction = ctx["jurisdiction"]
    piercer = ctx["piercer"]
    customer = ctx["customer"]

    appointment = setup_screened_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"],
        slot_start="2026-09-01T15:00:00Z", slot_end="2026-09-01T15:30:00Z",
    )[0]

    # A second cycle carries a lot that already expired before the service instant.
    # A distinct autoclave unit keeps its closed cycle interval from colliding
    # with the store's existing cycle (PRD §2.7 closed-interval overlap rule).
    _, _ = setup_cycle_and_lot(
        store["id"], lot_number="L-EXPIRED", expiration_date="2026-08-01T00:00:00Z",
        autoclave_unit_id="AUTO-EXPIRED",
    )
    lot_rows = get_success_data(api_client.list_store_cartridge_lots(store["id"], READER))
    lot_rows = lot_rows if isinstance(lot_rows, list) else lot_rows.get("data", lot_rows)
    expired_lot = [l for l in lot_rows if l["expiration_date"] == "2026-08-01T00:00:00Z"][0]
    assert expired_lot["status"] == "AVAILABLE"

    res = api.create_session(
        {
            "appointment_id": appointment["id"],
            "piercer_id": piercer["id"],
            "cartridge_lot_id": expired_lot["id"],
            "site_pierced": "LOBE",
            "base_fee_cents": 4500,
            "aftercare_kit_included": True,
            "solution_lot_number": "S-1",
        },
        {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"},
    )
    validate_error(res, E.CARTRIDGE_LOT_UNAVAILABLE, expected_status=422)


def test_mandatory_aftercare_kit_is_refused_when_omitted(api):
    """PRD §3.5: "It additionally requires `aftercare_kit_included` to be true whenever the
    jurisdiction mandates an aftercare kit, which it does when the jurisdiction's
    `record_retention_years` is at least 5; a missing mandatory kit is refused with
    `ERR_AFTERCARE_KIT_REQUIRED` at HTTP 422."

    Design: Corner/errors/aftercare_kit_missing_rejected_on_session_create
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(store_overrides={"piercing_room_count": 2})
    assert ctx["jurisdiction"]["record_retention_years"] == 7

    appointment, response = open_explicit_session(
        ctx, base_fee_cents=4500, aftercare_kit_included=False, solution_lot_number="S-1"
    )
    validate_error(response, E.AFTERCARE_KIT_REQUIRED, expected_status=422)


def test_explicit_refund_above_the_computed_cap_is_refused(api):
    """PRD §3.7: "A requested amount above the computed cap is rejected with
    `ERR_REFUND_EXCEEDS_ALLOWABLE` at HTTP 422: a refund may never exceed the gross fee minus
    the retention floor of 500 cents, and may never exceed the customer's `net_fee_cents` for
    that session."

    Design: Corner/errors/explicit_refund_above_cap_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers.fixtures import file_and_resolve_incident

    ctx = setup_full_service()
    incident = file_and_resolve_incident(ctx["session"], severity="SEVERE")
    assert incident["refund_amount_cents"] > 0

    res = api.issue_refund(
        incident["id"], {"refund_destination": "CARD", "requested_refund_cents": 6000}, MANAGER
    )
    validate_error(res, E.REFUND_EXCEEDS_ALLOWABLE, expected_status=422)
    # The refused settlement applies no part of the operation: the incident
    # remains RESOLVED with its refund still pending (PRD §3.7 renders
    # settlement only on success).
    unchanged = get_success_data(api.get_incident(incident["id"], READER))
    assert unchanged["escalation_status"] == "RESOLVED"
    assert unchanged["refund_status"] == "PENDING"


def test_third_failed_recertification_attempt_is_exhausted(api):
    """PRD §3.9: "Once `attempted_practical_count` reaches exactly 3 the record is refused with
    `ERR_CERTIFICATION_RECERT_ATTEMPTS_EXHAUSTED` at HTTP 409 and moves automatically to
    `EXPIRED`."

    Design: Corner/errors/recertification_attempts_exhausted_rejected
    """
    set_clock("2026-09-05T00:00:00Z")
    jurisdiction, store, piercer, certification = setup_store_with_certified_piercer(
        store_overrides={"piercing_room_count": 1},
        certification_overrides={"issued_at": "2025-11-01T00:00:00Z", "expires_at": "2026-11-01T00:00:00Z"},
    )
    headers = {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"}

    api.set_clock("2026-10-02T00:00:00Z", COMPLIANCE)
    # A failing assessment against EXPIRING_SOON moves the record to
    # RECERTIFICATION_PENDING and increments the count; a re-submission while
    # the count is below 3 returns it to EXPIRING_SOON so the next failure can
    # consume the following attempt. Alternating the two edges exhausts the
    # three-attempt cycle.
    for expected_status in ("RECERTIFICATION_PENDING", "EXPIRING_SOON",
                           "RECERTIFICATION_PENDING", "EXPIRING_SOON",
                           "EXPIRED"):
        response = validate_success(
            api.recertify(certification["id"], {"practical_assessment_passed": False}, headers), 200
        )
        assert response["status"] == expected_status

    record = get_success_data(api.get_certification(certification["id"], READER))
    assert record["attempted_practical_count"] == 3
    assert record["status"] == "EXPIRED"

    res = api.recertify(certification["id"], {"practical_assessment_passed": False}, headers)
    validate_error(res, E.CERTIFICATION_RECERT_ATTEMPTS_EXHAUSTED, expected_status=409)


def test_recertification_submitted_by_another_piercer_is_refused(api):
    """PRD §3.9: "It is owner-restricted: a submission by a piercer other than the
    certification's owner is refused with `ERR_NOT_CERTIFICATION_OWNER` at HTTP 403."
    PRD §2.1: "a recertification submission is accepted only when the submitting caller's
    `X-User-ID` equals the certification's `piercer_id`."

    Design: Corner/errors/recertification_by_another_piercer_rejected
    """
    set_clock("2026-09-05T00:00:00Z")
    jurisdiction, store, piercer, certification = setup_store_with_certified_piercer(
        store_overrides={"piercing_room_count": 1},
        certification_overrides={"issued_at": "2025-11-01T00:00:00Z", "expires_at": "2026-11-01T00:00:00Z"},
    )
    other = create_piercer(store["id"], full_name="Other Piercer")

    api.set_clock("2026-10-02T00:00:00Z", COMPLIANCE)
    res = api.recertify(
        certification["id"], {"practical_assessment_passed": True},
        {"X-User-ID": other["id"], "X-User-Role": "Piercer"},
    )
    validate_error(res, E.NOT_CERTIFICATION_OWNER, expected_status=403)


def test_piercer_identity_must_own_the_certification_being_renewed(api):
    """PRD §2.1: "a recertification submission is accepted only when the submitting caller's
    `X-User-ID` equals the certification's `piercer_id`."
    PRD §2.1: "When `X-User-Role` is `Piercer`, `X-User-ID` is the `id` of the acting `Piercer`
    row; ownership checks on any resource that references a `Piercer` compare that resource's
    piercer reference to `X-User-ID`".

    Design: Corner/rbac/piercer_owner_identity_required_for_recertification
    """
    set_clock("2026-09-05T00:00:00Z")
    jurisdiction, store, piercer, certification = setup_store_with_certified_piercer(
        store_overrides={"piercing_room_count": 1},
        certification_overrides={"issued_at": "2025-11-01T00:00:00Z", "expires_at": "2026-11-01T00:00:00Z"},
    )
    api.set_clock("2026-10-02T00:00:00Z", COMPLIANCE)

    res = api.recertify(
        certification["id"], {"practical_assessment_passed": True},
        {"X-User-ID": NON_EXISTENT_UUID, "X-User-Role": "Piercer"},
    )
    validate_error(res, E.NOT_CERTIFICATION_OWNER, expected_status=403)


def test_incident_create_with_a_stale_session_version_is_refused(api):
    """PRD §2.9: "Filing an incident report is guarded against the session it concerns: the
    request carries `expected_session_version` and must match the target `PiercingSession`'s
    current `version`."
    PRD §2.9: "When the supplied value does not equal the parent row's current `version`, the
    request is rejected with `ERR_STALE_VERSION` and HTTP 412, and no part of the operation is
    applied."

    Design: Corner/cross_cutting/incident_create_with_stale_session_version_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    session = get_success_data(api.get_session(ctx["session"]["id"], READER))

    res = api.create_incident(
        create_incident_payload(session["id"], session["version"] - 1), COMPLIANCE
    )
    validate_error(res, E.STALE_VERSION, expected_status=412)

    data, meta = validate_paginated(api.list_session_incidents(session["id"], READER))
    assert meta["total_count"] == 0


def test_healing_outcome_create_with_the_current_version_succeeds(api):
    """PRD §2.9: "Creating a healing outcome is likewise guarded against the session it concerns
    and likewise carries `expected_session_version` and must match that `PiercingSession`'s
    current `version`."
    PRD §2.9: "When the supplied value does not equal the parent row's current `version`, the
    request is rejected with `ERR_STALE_VERSION` and HTTP 412".

    Design: Corner/cross_cutting/healing_outcome_create_with_current_version_succeeds
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    session = get_success_data(api.get_session(ctx["session"]["id"], READER))

    created = validate_success(
        api.create_healing_outcome(
            create_healing_outcome_payload(session["id"], session["version"]),
            {"X-User-ID": ctx["piercer"]["id"], "X-User-Role": "Piercer"},
        ),
        201,
    )
    assert created["status"] == "ASSESSED"
    assert created["session_id"] == session["id"]


def test_a_piercer_cannot_issue_certifications(api):
    """PRD §2.1: "`Piercer` owns anatomy screening, service execution, session creation, healing
    assessment, downgrade and re-pierce, healing-outcome downgrade and re-pierce claims, and
    recertification submission."
    PRD §2.1: "An operation attempted by a role that does not own it fails with
    `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/piercer_cannot_issue_certifications
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction, store, piercer, certification = setup_store_with_certified_piercer(
        store_overrides={"piercing_room_count": 1}
    )
    observed = get_success_data(api.get_piercer(piercer["id"], READER))

    res = api.create_certification(
        create_certification_payload(
            piercer["id"], observed["version"],
            certification_level="SENIOR", issued_at="2026-09-01T00:00:00Z", expires_at="2027-09-01T00:00:00Z",
        ),
        {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"},
    )
    validate_error(res, E.UNAUTHORIZED_ROLE, expected_status=403)


def test_an_intake_associate_cannot_open_sterilization_cycles(api):
    """PRD §2.1: "`SterilizationTechnician` owns only opening and closing sterilization cycles."
    PRD §2.1: "An operation attempted by a role that does not own it fails with
    `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/intake_associate_cannot_open_sterilization_cycles
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=1)

    res = api.create_sterilization_cycle(
        {
            "store_location_id": store["id"],
            "autoclave_unit_id": "AUTO-2",
            "protocol_code": "AUTOCLAVE-B",
            "cycle_start_at": "2026-09-01T08:00:00Z",
            "cycle_end_at": "2026-09-01T08:45:00Z",
            "temperature_celsius": 134.0,
        },
        INTAKE,
    )
    validate_error(res, E.UNAUTHORIZED_ROLE, expected_status=403)


def test_a_compliance_officer_cannot_acknowledge_a_customer_follow_up(api):
    """PRD §2.1: "`Customer` shares only the aftercare follow-up acknowledgement."
    PRD §2.1: "An operation attempted by a role that does not own it fails with
    `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/compliance_officer_cannot_acknowledge_a_customer_follow_up
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    api.set_clock("2026-09-10T00:00:00Z", COMPLIANCE)

    res = api.acknowledge_follow_up(ctx["session"]["id"], COMPLIANCE)
    validate_error(res, E.UNAUTHORIZED_ROLE, expected_status=403)