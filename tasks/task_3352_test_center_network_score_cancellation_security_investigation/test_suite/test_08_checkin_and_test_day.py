"""Test-day: check-in gating, the immutable CheckInRecord, no-show sweep, filing rights."""
from test_helpers import (
    ApiErrorId,
    CLOCK_TEST_DAY_AFTER,
    administer_session,
    assert_check_in_record,
    check_in_admit,
    get_registration,
    get_session,
    lock_session,
    register_new_examinee,
    set_clock,
    setup_bookable_session,
    validate_error,
    validate_success,
)
from test_helpers import (
    create_check_in_payload,
    create_irregularity_payload,
    make_center_manager_headers,
    make_proctor_headers,
)


def test_checkin_rejected_when_session_not_locked(api):
    """PRD §3.4: "Check-in requires the registration's `booking_status` to be
    `CONFIRMED` (else `ERR_INVALID_STATE`), its `attendance_status` to still
    be `PENDING` (else `ERR_ALREADY_CHECKED_IN`), and the session to be
    `LOCKED` (else `ERR_SESSION_NOT_LOCKED`)."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_session_locked
    """
    ctx = setup_bookable_session(name="Center XL", total_seats=5, with_proctor=True)
    session_id = ctx["session"]["id"]
    examinee, registration = register_new_examinee(
        session_id, full_name="Ex XL", id_document_number="PXL1"
    )
    set_clock("2026-10-10T07:45:00Z")
    # The session is only PUBLISHED: check-in is rejected.
    resp = api.check_in(
        registration["id"],
        create_check_in_payload("PXL1", "2027-06-01", "bio-xl"),
        make_proctor_headers(ctx["proctor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_LOCKED)
    records = validate_success(
        api.list_check_ins(registration["id"],
                           make_proctor_headers(ctx["proctor"]["id"])),
        200,
    )
    assert records == [], "no CheckInRecord is appended by the rejection"
    assert get_registration(registration["id"])["attendance_status"] == "PENDING"


def test_checkin_succeeds_after_lock(api):
    """PRD §3.4: "Check-in requires the registration's `booking_status` to be
    `CONFIRMED` (else `ERR_INVALID_STATE`), its `attendance_status` to still
    be `PENDING` (else `ERR_ALREADY_CHECKED_IN`), and the session to be
    `LOCKED` (else `ERR_SESSION_NOT_LOCKED`)."
    PRD §3.4: "The check-in moves the registration's `attendance_status` from
    `PENDING` to `ADMITTED` or `DENIED` to match the decision"

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_session_locked
    """
    ctx = setup_bookable_session(name="Center XL2", total_seats=5, with_proctor=True)
    session_id = ctx["session"]["id"]
    examinee, registration = register_new_examinee(
        session_id, full_name="Ex XL2", id_document_number="PXL2"
    )
    lock_session(session_id, ctx["manager"]["id"])
    record = validate_success(
        api.check_in(
            registration["id"],
            create_check_in_payload("PXL2", "2027-06-01", "bio-xl2"),
            make_proctor_headers(ctx["proctor"]["id"]),
        ),
        201,
    )
    assert_check_in_record(record)
    assert record["admission_decision"] == "ADMITTED"
    assert get_registration(registration["id"])["attendance_status"] == "ADMITTED"


def test_check_in_record_immutable_no_version(api):
    """PRD §2.4: "A `CheckInRecord` is an immutable evidentiary artifact: it is
    appended once and never modified, so it carries only `id` and
    `created_at`. Both `updated_at` and `version` are absent from check-in
    records."

    Design: Corner/entities/check_in_record_immutable_no_version
    """
    ctx = setup_bookable_session(name="Center IM", total_seats=5, with_proctor=True)
    session_id = ctx["session"]["id"]
    examinee, registration = register_new_examinee(
        session_id, full_name="Ex IM", id_document_number="PIM1"
    )
    lock_session(session_id, ctx["manager"]["id"])
    record = check_in_admit(registration["id"], examinee, ctx["proctor"]["id"])
    assert_check_in_record(record)
    records = validate_success(
        api.list_check_ins(registration["id"],
                           make_proctor_headers(ctx["proctor"]["id"])),
        200,
    )
    assert len(records) == 1
    assert records[0]["id"] == record["id"]
    assert_check_in_record(records[0])


def test_double_checkin_rejected_already_checked_in(api):
    """PRD §3.4: "Check-in requires the registration's `booking_status` to be
    `CONFIRMED` (else `ERR_INVALID_STATE`), its `attendance_status` to still
    be `PENDING` (else `ERR_ALREADY_CHECKED_IN`), and the session to be
    `LOCKED` (else `ERR_SESSION_NOT_LOCKED`)."

    Design: Corner/validations/double_checkin_rejected_already_checked_in
    """
    ctx = setup_bookable_session(name="Center CI", total_seats=5, with_proctor=True)
    session_id = ctx["session"]["id"]
    examinee, registration = register_new_examinee(
        session_id, full_name="Ex CI", id_document_number="PCI1"
    )
    lock_session(session_id, ctx["manager"]["id"])
    check_in_admit(registration["id"], examinee, ctx["proctor"]["id"])
    resp = api.check_in(
        registration["id"],
        create_check_in_payload("PCI1", "2027-06-01", "bio-ci"),
        make_proctor_headers(ctx["proctor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_CHECKED_IN)
    records = validate_success(
        api.list_check_ins(registration["id"],
                           make_proctor_headers(ctx["proctor"]["id"])),
        200,
    )
    assert len(records) == 1, "no second CheckInRecord appended"


def test_administer_no_show_sweep(api):
    """PRD §3.2: "Closing triggers the no-show sweep: every registration of
    the session still holding `booking_status` `CONFIRMED` with
    `attendance_status` `PENDING` — a confirmed seat whose examinee never
    checked in — is moved to `NO_SHOW`."

    Design: Corner/state_machines/administer_no_show_sweep
    """
    ctx = setup_bookable_session(name="Center NS", total_seats=5, with_proctor=True)
    session_id = ctx["session"]["id"]
    ex1, reg1 = register_new_examinee(session_id, full_name="Ex N1",
                                      id_document_number="PN01")
    ex2, reg2 = register_new_examinee(session_id, full_name="Ex N2",
                                      id_document_number="PN02")
    lock_session(session_id, ctx["manager"]["id"])
    check_in_admit(reg1["id"], ex1, ctx["proctor"]["id"])
    # E2 never checks in.
    set_clock(CLOCK_TEST_DAY_AFTER)
    administered = validate_success(
        api.administer_session(
            session_id, make_center_manager_headers(ctx["manager"]["id"])
        ),
        200,
    )
    assert administered["status"] == "ADMINISTERED"
    assert get_registration(reg1["id"])["attendance_status"] == "ADMITTED", (
        "sweep skips admitted registrations"
    )
    assert get_registration(reg2["id"])["attendance_status"] == "NO_SHOW"


def test_irregularity_by_unassigned_proctor_rejected(api):
    """PRD §3.4: "Filing is restricted to proctors actually assigned to the
    session: the caller's identifier must be an element of the session's
    `proctor_staff_ids`, else the filing is rejected with
    `ERR_PROCTOR_NOT_ASSIGNED`."

    Design: Corner/validations/irregularity_by_unassigned_proctor_rejected
    """
    ctx = setup_bookable_session(name="Center UP", total_seats=5, with_proctor=True)
    session_id = ctx["session"]["id"]
    examinee, registration = register_new_examinee(
        session_id, full_name="Ex UP", id_document_number="PUP1"
    )
    # The proctor exists at the center but is NOT assigned to the session.
    resp = api.create_irregularity_report(
        session_id,
        create_irregularity_payload(
            registration_id=registration["id"],
            category="PROHIBITED_ITEM",
            severity="HIGH",
            narrative="Phone on desk",
        ),
        make_proctor_headers(ctx["proctor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROCTOR_NOT_ASSIGNED)
    # PRD §4 restricts the list endpoint to ProgramAdmin/CenterManager/
    # ScoreAnalyst — the center manager verifies no report was persisted.
    reports = validate_success(
        api.list_irregularity_reports(registration["id"],
                                      make_center_manager_headers(ctx["manager"]["id"])),
        200,
    )
    assert reports == []
