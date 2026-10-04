"""State-machine transitions: cycle re-entry, cascades and invalid-from errors."""
from test_helpers import (
    E,
    api_client,
    create_appointment_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    INTAKE,
    MANAGER,
    READER,
    certify,
    create_appointment,
    create_customer,
    create_jurisdiction,
    create_piercer,
    create_store,
    get_appointment,
    get_certification,
    get_success_data,
    get_store,
    set_clock,
    setup_cycle_and_lot,
    setup_customer_with_active_consent,
    setup_full_service,
    setup_in_service_appointment,
    setup_ready_appointment,
)


def test_recertification_retry_re_enters_expiring_soon(api):
    """PRD §3.9: "A failing assessment against an `EXPIRING_SOON` record moves it to
    `RECERTIFICATION_PENDING` and increments `attempted_practical_count`."
    PRD §3.9: "A record in `RECERTIFICATION_PENDING` may be re-submitted back to `EXPIRING_SOON`
    while its attempt count remains below 3."

    Design: Difficulty/non_linear_state_machine/certification_resubmission_loop_reenters_expiring_soon
    """
    set_clock("2026-09-05T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=1)
    piercer = create_piercer(store["id"])
    certification = certify(
        piercer["id"], issued_at="2025-11-01T00:00:00Z", expires_at="2026-11-01T00:00:00Z"
    )

    # Cross recertification_due_at (expires_at minus the 30-day lead) so the
    # record is EXPIRING_SOON.
    api.set_clock("2026-10-02T00:00:00Z", COMPLIANCE)
    assert get_certification(certification["id"])["status"] == "EXPIRING_SOON"

    # First failed practical: EXPIRING_SOON -> RECERTIFICATION_PENDING.
    after_first = validate_success(
        api.recertify(
            certification["id"], {"practical_assessment_passed": False},
            {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"},
        ),
        200,
    )
    assert after_first["status"] == "RECERTIFICATION_PENDING"
    assert after_first["attempted_practical_count"] == 1

    # Retry edge: RECERTIFICATION_PENDING -> EXPIRING_SOON. The re-submission
    # returns the record to EXPIRING_SOON; the count is then advanced by the next
    # failed assessment, which moves it back to RECERTIFICATION_PENDING at 2.
    resubmitted = validate_success(
        api.recertify(
            certification["id"], {"practical_assessment_passed": False},
            {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"},
        ),
        200,
    )
    assert resubmitted["status"] == "EXPIRING_SOON"
    assert resubmitted["attempted_practical_count"] == 1

    failed_again = validate_success(
        api.recertify(
            certification["id"], {"practical_assessment_passed": False},
            {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"},
        ),
        200,
    )
    assert failed_again["status"] == "RECERTIFICATION_PENDING"
    assert failed_again["attempted_practical_count"] == 2


def test_appointment_reschedule_cycle_returns_to_booked(api):
    """PRD §3.3: "Rescheduling moves a `BOOKED` or `CONFIRMED` appointment to `RESCHEDULED` using
    a new `new_slot_start_at` and `new_slot_end_at`, increments `reschedule_count` by one".
    PRD §3.3: "Re-confirming a `RESCHEDULED` appointment returns it to `BOOKED` after the new
    slot passes the piercer-adjacency check, closing the cycle
    `CONFIRMED → RESCHEDULED → BOOKED → CONFIRMED`."

    Design: Difficulty/non_linear_state_machine/appointment_reschedule_cycle_returns_to_booked
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=1)
    piercer = create_piercer(store["id"])
    certify(piercer["id"])
    customer = create_customer()
    consent = validate_success(
        api_client.create_consent(
            {
                "customer_id": customer["id"],
                "jurisdiction_id": jurisdiction["id"],
                "consent_type": "SELF",
                "identification_type": "GOVERNMENT_PHOTO_ID",
                "identification_number_masked": "****1234",
                "signed_at": "2026-08-30T00:00:00Z",
            },
            INTAKE,
        ),
        201,
    )
    validate_success(api.verify_consent(consent["id"], INTAKE), 200)

    appointment = setup_ready_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"]
    )
    assert appointment["status"] == "CONFIRMED"

    observed = get_appointment(appointment["id"])
    moved = validate_success(
        api.reschedule_appointment(
            appointment["id"],
            {
                "new_slot_start_at": "2026-09-01T11:00:00Z",
                "new_slot_end_at": "2026-09-01T11:30:00Z",
                "expected_appointment_version": observed["version"],
            },
            INTAKE,
        ),
        200,
    )
    assert moved["status"] == "RESCHEDULED"
    assert moved["reschedule_count"] == 1

    back_to_booked = validate_success(api.confirm_appointment(moved["id"], INTAKE), 200)
    assert back_to_booked["status"] == "BOOKED"
    assert back_to_booked["reschedule_count"] == 1


def test_freezing_a_store_cancels_open_appointments_only(api):
    """PRD §2.7: "Freezing drives a store in `status` `OPEN` or `RESTRICTED` to
    `compliance_posture` `FROZEN`; every appointment at that store in `BOOKED` or `CONFIRMED`
    is cascaded to `CANCELLED`".

    Design: Corner/state_machines/store_freeze_cascades_only_non_terminal_appointments
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    store_id = ctx["store"]["id"]

    completed = ctx["appointment"]
    assert completed["status"] == "COMPLETED"

    # A second appointment is still CONFIRMED when the store freezes.
    open_appointment = setup_ready_appointment(
        store_id, ctx["customer"]["id"], ctx["piercer"]["id"], ctx["jurisdiction"]["id"],
        slot_start="2026-09-01T11:00:00Z", slot_end="2026-09-01T11:30:00Z",
    )
    assert open_appointment["status"] == "CONFIRMED"

    frozen = validate_success(api.freeze_store(store_id, COMPLIANCE), 200)
    assert frozen["compliance_posture"] == "FROZEN"

    assert get_appointment(completed["id"])["status"] == "COMPLETED"
    assert get_appointment(open_appointment["id"])["status"] == "CANCELLED"


def test_closing_a_store_is_blocked_while_a_session_is_in_service(api):
    """PRD §2.7: "Closing a store requires that no appointment at that store is in `CHECKED_IN`,
    `SCREENED` or `IN_SERVICE`".
    PRD §2.12: "State validity is fourth: a target row that is not in a state from which the
    requested transition is declared yields `ERR_INVALID_STATE` (HTTP 409)".
    PRD §2.7: "Posture transitions are driven automatically and administratively."

    Design: Corner/state_machines/store_close_rejected_while_a_session_is_in_service
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    store = ctx["store"]
    # A second appointment is left mid-service on the floor.
    setup_in_service_appointment(
        store["id"], ctx["customer"]["id"], ctx["piercer"]["id"], ctx["jurisdiction"]["id"],
        slot_start="2026-09-01T13:00:00Z", slot_end="2026-09-01T13:30:00Z",
    )

    res = api.close_store(store["id"], COMPLIANCE)
    validate_error(res, E.INVALID_STATE, expected_status=409)
    assert get_store(store["id"])["status"] == "OPEN"


def test_completing_an_already_completed_appointment_is_an_invalid_state(api):
    """PRD §3.3: "`COMPLETED`, `CANCELLED`, `NO_SHOW` and `REFUSED` are terminal."
    PRD §2.12: "State validity is fourth: a target row that is not in a state from which the
    requested transition is declared yields `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/errors/second_completion_on_completed_appointment_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    assert ctx["appointment"]["status"] == "COMPLETED"

    res = api.complete_appointment(
        ctx["appointment"]["id"], {"X-User-ID": ctx["piercer"]["id"], "X-User-Role": "Piercer"}
    )
    validate_error(res, E.INVALID_STATE, expected_status=409)


def test_revoking_an_already_revoked_certification_is_an_invalid_state(api):
    """PRD §3.9: "A `ComplianceOfficer` revokes a certification by supplying a `reason_code`;
    revocation applies while the record is `VALID`, `EXPIRING_SOON` or `RECERTIFICATION_PENDING`,
    sets `status` to `REVOKED`".
    PRD §2.12: "State validity is fourth: a target row that is not in a state from which the
    requested transition is declared yields `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/revoke_certification_twice_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=1)
    piercer = create_piercer(store["id"])
    certification = certify(piercer["id"])

    first = validate_success(
        api.revoke_certification(certification["id"], {"reason_code": "PROTOCOL_BREACH"}, COMPLIANCE),
        200,
    )
    assert first["status"] == "REVOKED"

    res = api.revoke_certification(certification["id"], {"reason_code": "PROTOCOL_BREACH"}, COMPLIANCE)
    validate_error(res, E.INVALID_STATE, expected_status=409)
    assert get_certification(certification["id"])["status"] == "REVOKED"


def test_passing_recertification_returns_an_expiring_record_to_valid(api):
    """PRD §3.9: "A passing assessment against an `EXPIRING_SOON` record returns it to `VALID`,
    sets `issued_at` to the current clock instant and `expires_at` to that instant plus
    `certification_validity_months`, resets `attempted_practical_count` to 0, and recomputes
    `recertification_due_at`".

    Design: Difficulty/non_linear_state_machine/certification_resubmission_loop_reenters_expiring_soon
    """
    set_clock("2026-09-05T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=1)
    piercer = create_piercer(store["id"])
    certification = certify(
        piercer["id"], issued_at="2025-11-01T00:00:00Z", expires_at="2026-11-01T00:00:00Z"
    )
    api.set_clock("2026-10-02T00:00:00Z", COMPLIANCE)
    assert get_certification(certification["id"])["status"] == "EXPIRING_SOON"

    renewed = validate_success(
        api.recertify(
            certification["id"], {"practical_assessment_passed": True},
            {"X-User-ID": piercer["id"], "X-User-Role": "Piercer"},
        ),
        200,
    )
    assert renewed["status"] == "VALID"
    assert renewed["attempted_practical_count"] == 0
    assert renewed["issued_at"] == "2026-10-02T00:00:00Z"
    assert renewed["issued_at"] != "2025-11-01T00:00:00Z"


def test_the_third_reschedule_attempt_is_refused(api):
    """PRD §3.3: "Rescheduling moves a `BOOKED` or `CONFIRMED` appointment to `RESCHEDULED` using
    a new `new_slot_start_at` and `new_slot_end_at`, increments `reschedule_count` by one, and is
    permitted only while `reschedule_count` is below 2; a third attempt is refused with
    `ERR_RESCHEDULE_LIMIT_REACHED` and HTTP 409."

    Design: Difficulty/non_linear_state_machine/appointment_reschedule_cycle_returns_to_booked
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=1)
    piercer = create_piercer(store["id"])
    certify(piercer["id"])
    customer, _ = setup_customer_with_active_consent(jurisdiction["id"])

    appointment = setup_ready_appointment(
        store["id"], customer["id"], piercer["id"], jurisdiction["id"]
    )

    slot_offsets = ("11:00", "12:00", "13:00")
    current = appointment
    for offset in slot_offsets[:2]:
        observed = get_appointment(current["id"])
        moved = validate_success(
            api.reschedule_appointment(
                current["id"],
                {
                    "new_slot_start_at": f"2026-09-01T{offset}:00Z",
                    "new_slot_end_at": f"2026-09-01T{offset.split(':')[0]}:30:00Z",
                    "expected_appointment_version": observed["version"],
                },
                INTAKE,
            ),
            200,
        )
        assert moved["status"] == "RESCHEDULED"
        current = validate_success(api.confirm_appointment(moved["id"], INTAKE), 200)
        assert current["status"] == "BOOKED"

    assert current["reschedule_count"] == 2

    observed = get_appointment(current["id"])
    res = api.reschedule_appointment(
        current["id"],
        {
            "new_slot_start_at": "2026-09-01T14:00:00Z",
            "new_slot_end_at": "2026-09-01T14:30:00Z",
            "expected_appointment_version": observed["version"],
        },
        INTAKE,
    )
    validate_error(res, "ERR_RESCHEDULE_LIMIT_REACHED", expected_status=409)