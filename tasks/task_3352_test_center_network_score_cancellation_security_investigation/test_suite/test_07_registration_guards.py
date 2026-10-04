"""Registration guards: duplicate, OCC, priority masking, banned examinee."""
from test_helpers import (
    ADMIN_2_ID,
    ApiErrorId,
    CLOCK_TEST_DAY_MORNING,
    TEST_DATE_FAR,
    adjudicate_case,
    create_examinee,
    create_published_session,
    create_registration_payload,
    create_session,
    fresh_case_version,
    get_examinee,
    get_session,
    register_new_examinee,
    set_clock,
    setup_bookable_session,
    setup_exposure_case,
    validate_error,
    validate_success,
)
from test_helpers import make_examinee_headers


def test_duplicate_registration_clean_error(api):
    """PRD §3.3: "no registration may already exist for the same session and
    examinee with `booking_status` `CONFIRMED` or `WAITLISTED` (else
    `ERR_DUPLICATE_REGISTRATION`)"

    Design: Corner/validations/duplicate_registration_clean_error
    """
    ctx = setup_bookable_session(name="Center DU", total_seats=5)
    session_id = ctx["session"]["id"]
    examinee, _ = register_new_examinee(session_id, full_name="Ex DU",
                                        id_document_number="PDU1")
    version = get_session(session_id)["version"]
    resp = api.create_registration(
        session_id,
        create_registration_payload(examinee["id"], version),
        make_examinee_headers(examinee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION)
    assert get_session(session_id)["confirmed_count"] == 1, "no double booking"


def test_registration_occ_stale_version_rejected(api):
    """PRD §2.7: "Creating a registration under a session requires the request
    body to carry `expected_session_version`, holding the session `version`
    the client last observed. If the session's current `version` no longer
    matches — because another writer has registered, cancelled, or been
    promoted against the same session in the meantime, each of which
    legitimately changes the seat picture — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and no registration is created."

    Design: Corner/cross_cutting_complexity_layers/registration_occ_stale_version_rejected
    """
    ctx = setup_bookable_session(name="Center OC", total_seats=5)
    session_id = ctx["session"]["id"]
    ex1 = create_examinee(full_name="Ex O1", id_document_number="PO01")
    ex2 = create_examinee(full_name="Ex O2", id_document_number="PO02")
    stale_version = get_session(session_id)["version"]
    first = validate_success(
        api.create_registration(
            session_id,
            create_registration_payload(ex1["id"], stale_version),
            make_examinee_headers(ex1["id"]),
        ),
        201,
    )
    assert first["booking_status"] == "CONFIRMED"
    resp = api.create_registration(
        session_id,
        create_registration_payload(ex2["id"], stale_version),
        make_examinee_headers(ex2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_session(session_id)["confirmed_count"] == 1, (
        "the rejected write changed nothing"
    )


def _setup_banned_examinee(api, name):
    """Ban an examinee through a substantiated CONTENT_EXPOSURE case
    adjudicated CANCELLED after the response window expired. Returns ctx."""
    ctx = setup_exposure_case(name=name, expire_window=True)
    version = fresh_case_version(ctx["registration"]["id"])
    adjudicate_case(
        ctx["case"]["id"], "CANCELLED", "Exposure proven", version,
        admin_id=ADMIN_2_ID,
    )
    assert get_examinee(ctx["examinee"]["id"])["status"] == "BANNED"
    return ctx


def test_state_error_masks_banned_safety_error(api):
    """PRD §2.6: "Checks are evaluated in the priority order below, and a
    failure at an earlier step masks every later step"
    PRD §3.3: "The gate conditions, in the pipeline order of §2.6, are: the
    session must be `PUBLISHED` (else `ERR_SESSION_NOT_PUBLISHED`); the
    examinee must be `ACTIVE` (else `ERR_EXAMINEE_BANNED`)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_banned_registration
    """
    ctx = _setup_banned_examinee(api, "Center PP")
    # A second session at the same center, left in DRAFT; window is open
    # (clock 2026-11-10 is strictly before test_date 2026-12-12).
    session2 = create_session(ctx["center"]["id"], test_date=TEST_DATE_FAR)
    version = get_session(session2["id"])["version"]
    resp = api.create_registration(
        session2["id"],
        create_registration_payload(ctx["examinee"]["id"], version),
        make_examinee_headers(ctx["examinee"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_PUBLISHED)


def test_banned_examinee_present_but_state_error_wins(api):
    """PRD §2.6: "Checks are evaluated in the priority order below, and a
    failure at an earlier step masks every later step — for example, a missing
    header surfaces `ERR_UNAUTHENTICATED` before any other check runs, and a
    duplicate-registration conflict is reported only after authentication,
    authorization, body shape, path existence, state, compliance, referential,
    and temporal checks have all passed."
    PRD §3.3: "the session must be `PUBLISHED` (else
    `ERR_SESSION_NOT_PUBLISHED`); the examinee must be `ACTIVE` (else
    `ERR_EXAMINEE_BANNED`)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_banned_registration
    """
    ctx = _setup_banned_examinee(api, "Center PP2")
    assert get_examinee(ctx["examinee"]["id"])["status"] == "BANNED", (
        "the dual failure is genuinely present at trigger time"
    )
    session2 = create_session(ctx["center"]["id"], test_date=TEST_DATE_FAR)
    version = get_session(session2["id"])["version"]
    resp = api.create_registration(
        session2["id"],
        create_registration_payload(ctx["examinee"]["id"], version),
        make_examinee_headers(ctx["examinee"]["id"]),
    )
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_SESSION_NOT_PUBLISHED"
    assert body["data"]["error_id"] != "ERR_EXAMINEE_BANNED", (
        "state (priority 6) masks business_safety (priority 7)"
    )


def test_temporal_window_error_masks_duplicate_constraint(api):
    """PRD §2.6: "a duplicate-registration conflict is reported only after
    authentication, authorization, body shape, path existence, state,
    compliance, referential, and temporal checks have all passed."
    PRD §3.3: "the current UTC date must be strictly earlier than the
    session's `test_date` — registration closes on test day itself (else
    `ERR_REGISTRATION_WINDOW_CLOSED`)"

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_duplicate_registration
    """
    ctx = setup_bookable_session(name="Center TC", total_seats=5)
    session_id = ctx["session"]["id"]
    examinee, registration = register_new_examinee(
        session_id, full_name="Ex TC", id_document_number="PTC1"
    )
    assert registration["booking_status"] == "CONFIRMED"
    # Advance the clock onto the test date: the registration window is closed.
    set_clock(CLOCK_TEST_DAY_MORNING)
    version = get_session(session_id)["version"]
    resp = api.create_registration(
        session_id,
        create_registration_payload(examinee["id"], version),
        make_examinee_headers(examinee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED)


def test_duplicate_present_but_temporal_error_wins(api):
    """PRD §2.6: "a duplicate-registration conflict is reported only after
    authentication, authorization, body shape, path existence, state,
    compliance, referential, and temporal checks have all passed."
    PRD §3.3: "no registration may already exist for the same session and
    examinee with `booking_status` `CONFIRMED` or `WAITLISTED` (else
    `ERR_DUPLICATE_REGISTRATION`)"

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_duplicate_registration
    """
    ctx = setup_bookable_session(name="Center TC2", total_seats=5)
    session_id = ctx["session"]["id"]
    examinee, registration = register_new_examinee(
        session_id, full_name="Ex TC2", id_document_number="PTC2"
    )
    assert registration["booking_status"] == "CONFIRMED", (
        "a live CONFIRMED registration exists, so the duplicate rule also fails"
    )
    set_clock(CLOCK_TEST_DAY_MORNING)
    version = get_session(session_id)["version"]
    resp = api.create_registration(
        session_id,
        create_registration_payload(examinee["id"], version),
        make_examinee_headers(examinee["id"]),
    )
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_REGISTRATION_WINDOW_CLOSED"
    assert body["data"]["error_id"] != "ERR_DUPLICATE_REGISTRATION", (
        "temporal (priority 9) masks the uniqueness constraint (priority 10)"
    )


def test_banned_examinee_registration_safety_error(api):
    """PRD §2.6: "Registration creation rejects an examinee in `BANNED` status
    with `ERR_EXAMINEE_BANNED` (HTTP 403)"
    PRD §3.6: "existing registrations are left untouched as historical record,
    but every future registration attempt by that examinee is rejected with
    `ERR_EXAMINEE_BANNED`."

    Design: Corner/validations/banned_examinee_registration_safety_error
    """
    ctx = _setup_banned_examinee(api, "Center BN")
    session2 = create_published_session(
        ctx["center"]["id"], ctx["manager"]["id"], test_date=TEST_DATE_FAR
    )
    version = get_session(session2["id"])["version"]
    resp = api.create_registration(
        session2["id"],
        create_registration_payload(ctx["examinee"]["id"], version),
        make_examinee_headers(ctx["examinee"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EXAMINEE_BANNED)
    assert get_session(session2["id"])["confirmed_count"] == 0
