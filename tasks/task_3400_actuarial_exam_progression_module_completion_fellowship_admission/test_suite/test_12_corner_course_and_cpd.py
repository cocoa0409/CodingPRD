"""Corner queue — professionalism course and CPD attestation.

Session booking gates and capacity, attendance verification (PRD §3.7); CPD
member gate, cycle uniqueness, verified terminal state (PRD §3.8).
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    CLOCK_SESSION_HELD,
    CPD_ATTESTED_EXACT,
    CPD_ATTESTED_SECOND,
    CPD_CYCLE_YEAR,
    CPD_CYCLE_YEAR_NEXT,
    CPD_VERIFY_EXACT,
    CPD_VERIFY_OVER,
    RAW_SCORE_AT_MARK,
    RAW_SCORE_SECOND,
    REGISTRAR,
    SESSION_CODE,
    SESSION_CODE_PAST,
    SESSION_ENDS,
    SESSION_PAST_ENDS,
    SESSION_PAST_STARTS,
    SESSION_STARTS,
    apply_for_credential,
    approve_all_vee_topics,
    book_attendance,
    create_cpd_attestation_payload,
    create_course_attendance_payload,
    get_success_data,
    make_candidate,
    make_candidate_headers,
    make_cpd,
    make_session,
    set_clock,
    setup_associate,
    setup_published_window,
    validate_error,
    validate_success,
    verify_attendance,
    verify_course_attendance_payload,
    verify_cpd,
)


def _utc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_attendance_verify_requires_held_session(api):
    """PRD §3.7: "Verification requires the attendance to be `BOOKED` and the
    session `HELD`; any other combination is rejected with
    `ERR_ATTENDANCE_NOT_VERIFIABLE`."
    PRD §3.7: "Verification stamps `verified_at` with the current logical
    clock and `verified_by` with the acting `Registrar`'s opaque operator id."
    PRD §2.4: "Professionalism course sessions whose `ends_at` has been
    reached become `HELD`."

    Design: Corner/state_machines/attendance_verify_requires_held_session
    """
    candidate = setup_associate(api)["candidate"]
    session = make_session(api, session_code=SESSION_CODE, starts_at=SESSION_STARTS,
                           ends_at=SESSION_ENDS)
    attendance = book_attendance(api, session["id"], candidate)
    assert attendance["status"] == "BOOKED"

    resp = api.verify_course_attendance(
        attendance["id"], verify_course_attendance_payload("ATTENDED"), REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_ATTENDANCE_NOT_VERIFIABLE)

    sweep = set_clock(api, CLOCK_SESSION_HELD)
    assert sweep["sessions_held"] == 1

    verified = verify_attendance(api, attendance["id"], "NO_SHOW")
    assert verified["status"] == "NO_SHOW"
    assert _utc(verified["verified_at"]) == _utc(CLOCK_SESSION_HELD)
    assert verified["verified_by"] == "registrar-1"


def test_session_booking_requires_associate_and_future_start(api):
    """PRD §3.7: "Booking is a candidate act carrying just the
    `course_session_id`, and it is stage-gated: the candidate must be `ACTIVE`
    and hold the `ASSOCIATE` or `FELLOW` tier, with a `CANDIDATE`-tier booking
    rejected with `ERR_REQUIRES_ASSOCIATE`."
    PRD §3.7: "The session must still be bookable — `SCHEDULED` with a
    `starts_at` strictly later than the current logical clock; booking a
    session already held or whose start has been reached is rejected with
    `ERR_SESSION_NOT_BOOKABLE`."

    Design: Corner/endpoints/session_booking_requires_associate_and_future_start
    """
    candidate = make_candidate(api)
    session = make_session(api, session_code=SESSION_CODE_PAST,
                           starts_at=SESSION_PAST_STARTS, ends_at=SESSION_PAST_ENDS)
    headers = make_candidate_headers(candidate["id"])
    # CANDIDATE tier: the stage gate rejects while the session is bookable.
    resp_tier = api.create_course_attendance(
        create_course_attendance_payload(session["id"]), headers)
    validate_error(resp_tier, ApiErrorId.ERR_REQUIRES_ASSOCIATE)

    setup_associate(api, candidate=candidate)
    # After ASA the clock has passed the session's starts_at.
    resp_late = api.create_course_attendance(
        create_course_attendance_payload(session["id"]), headers)
    validate_error(resp_late, ApiErrorId.ERR_SESSION_NOT_BOOKABLE)


def test_session_full_boundary(api):
    """PRD §3.7: "Capacity is a hard ceiling here, unlike examination windows:
    when `attendance_booked` has reached `capacity` — equality rejects — the
    booking is refused with `ERR_SESSION_FULL`."

    Design: Corner/endpoints/session_full_boundary
    """
    ctx = setup_published_window(api, raw_scores=(RAW_SCORE_AT_MARK, RAW_SCORE_SECOND))
    cand_a, cand_b = ctx["candidates"]
    approve_all_vee_topics(api, cand_a)
    approve_all_vee_topics(api, cand_b)
    assert apply_for_credential(api, cand_a, "ASA")["application"]["status"] == "APPROVED"
    assert apply_for_credential(api, cand_b, "ASA")["application"]["status"] == "APPROVED"

    session = make_session(api, session_code=SESSION_CODE, starts_at=SESSION_STARTS,
                           ends_at=SESSION_ENDS, capacity=1)
    booked = book_attendance(api, session["id"], cand_a)
    assert booked["status"] == "BOOKED"

    resp = api.create_course_attendance(
        create_course_attendance_payload(session["id"]),
        make_candidate_headers(cand_b["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL)

    refreshed = get_success_data(api.list_course_attendances(
        REGISTRAR, params={"course_session_id": session["id"], "status": "BOOKED"}))
    assert len(refreshed) == 1


def test_cpd_not_member_gate(api):
    """PRD §3.8: "Attestation requires `ACTIVE` standing; a `CANDIDATE`-tier
    filing is rejected with `ERR_CPD_NOT_MEMBER`."

    Design: Corner/endpoints/cpd_not_member_gate
    """
    candidate = make_candidate(api)
    resp = api.create_cpd_attestation(
        create_cpd_attestation_payload(cycle_year=CPD_CYCLE_YEAR, attested_hours=10),
        make_candidate_headers(candidate["id"]))
    validate_error(resp, ApiErrorId.ERR_CPD_NOT_MEMBER)


def test_cpd_cycle_duplicate(api):
    """PRD §3.8: "only one attestation may exist per candidate per cycle year,
    a duplicate being rejected with `ERR_CPD_CYCLE_DUPLICATE`."

    Design: Corner/endpoints/cpd_cycle_duplicate
    """
    candidate = setup_associate(api)["candidate"]
    first = make_cpd(api, candidate, cycle_year=CPD_CYCLE_YEAR,
                     attested_hours=CPD_ATTESTED_EXACT)
    assert first["status"] == "ATTESTED"

    resp = api.create_cpd_attestation(
        create_cpd_attestation_payload(cycle_year=CPD_CYCLE_YEAR,
                                       attested_hours=CPD_ATTESTED_SECOND),
        make_candidate_headers(candidate["id"]))
    validate_error(resp, ApiErrorId.ERR_CPD_CYCLE_DUPLICATE)

    other_year = validate_success(api.create_cpd_attestation(
        create_cpd_attestation_payload(cycle_year=CPD_CYCLE_YEAR_NEXT,
                                       attested_hours=CPD_ATTESTED_SECOND),
        make_candidate_headers(candidate["id"])), 201)
    assert other_year["cycle_year"] == CPD_CYCLE_YEAR_NEXT


def test_cpd_already_verified_rejects_second_verify(api):
    """PRD §3.8: "A `Registrar` verifies an attestation by recording
    `verified_hours`; the attestation must be `ATTESTED` or `SHORTFALL` —
    verifying one already `VERIFIED` is rejected with
    `ERR_CPD_NOT_VERIFIABLE`."

    Design: Corner/endpoints/cpd_already_verified_rejects_second_verify
    """
    candidate = setup_associate(api)["candidate"]
    attestation = make_cpd(api, candidate, cycle_year=CPD_CYCLE_YEAR,
                           attested_hours=CPD_ATTESTED_EXACT)
    verified = verify_cpd(api, attestation["id"], CPD_VERIFY_EXACT)
    assert verified["status"] == "VERIFIED"

    resp = api.verify_cpd_attestation(
        attestation["id"], {"verified_hours": CPD_VERIFY_OVER}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_CPD_NOT_VERIFIABLE)
