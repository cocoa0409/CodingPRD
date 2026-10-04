"""Failed-audit cascade: center suspension cancels sessions and registrations."""
from test_helpers import (
    ApiErrorId,
    CASCADE_AUDIT_FINDINGS,
    CASCADE_AUDIT_SCORE,
    add_staff,
    api_client,
    complete_audit,
    create_authorized_center,
    create_published_session,
    get_center,
    get_registration,
    get_session,
    register_new_examinee,
    schedule_audit,
    validate_error,
)
from test_helpers import make_center_manager_headers


def _setup_published_with_registration(name="Center FC"):
    """AUTHORIZED center, PUBLISHED session, one CONFIRMED registration."""
    center = create_authorized_center(name=name, facility_seat_capacity=20)
    manager = add_staff(center["id"], "Mgr", "CENTER_MANAGER", "ADVANCED")
    session = create_published_session(center["id"], manager["id"], total_seats=5)
    examinee, registration = register_new_examinee(
        session["id"], full_name="Ex FC", id_document_number="PFC1"
    )
    return center, manager, session, examinee, registration


def test_failed_audit_cascade_suspends_center_and_cancels_session(api):
    """PRD §3.1: "A `FAILED` audit on an `AUTHORIZED` center is the severe
    path: the center transitions to `SUSPENDED`, `last_audit_outcome` becomes
    `FAILED`, and a three-hop cascade runs. First, every session of that center
    still in `DRAFT` or `PUBLISHED` status is cancelled outright."
    PRD §3.1: "Third, each cancelled session's `confirmed_count` and
    `waitlist_count` are recomputed — both become zero after the second hop —
    and each cancelled session's `version` increments by 1."

    Design: Difficulty/transitive_cascade/failed_audit_cascade_depth3
    """
    center, manager, session, examinee, registration = (
        _setup_published_with_registration()
    )
    audit2 = schedule_audit(center["id"], scheduled_date="2026-10-20",
                            audit_type="UNANNOUNCED")
    completed = complete_audit(audit2["id"], CASCADE_AUDIT_FINDINGS)
    assert completed["compliance_score"] == CASCADE_AUDIT_SCORE, (
        "100 - round_half_up(1.5*26) == 61 -> FAILED"
    )
    assert completed["outcome"] == "FAILED"
    center = get_center(center["id"])
    assert center["authorization_status"] == "SUSPENDED", "hop 1"
    session = get_session(session["id"])
    assert session["status"] == "CANCELLED", "hop 2: caused by the suspension"
    assert session["confirmed_count"] == 0
    assert session["waitlist_count"] == 0


def test_failed_audit_cascade_cancels_registrations(api):
    """PRD §3.1: "Second, for each session cancelled in the first hop, every
    registration whose `booking_status` is `CONFIRMED` or `WAITLISTED` has its
    `booking_status` moved to `CANCELLED`, while `attendance_status` is left
    untouched as historical record."

    Design: Difficulty/transitive_cascade/failed_audit_cascade_depth3
    """
    center, manager, session, examinee, registration = (
        _setup_published_with_registration()
    )
    assert registration["booking_status"] == "CONFIRMED"
    audit2 = schedule_audit(center["id"], scheduled_date="2026-10-20",
                            audit_type="UNANNOUNCED")
    complete_audit(audit2["id"], CASCADE_AUDIT_FINDINGS)
    registration = get_registration(registration["id"])
    assert registration["booking_status"] == "CANCELLED", (
        "hop 3: caused by the session cancellation"
    )
    assert registration["attendance_status"] == "PENDING", (
        "attendance dimension untouched by the cascade"
    )


def test_cancelled_session_lockdown_publish_rejected(api):
    """PRD §2.6: "Every other from-state violation (a double completion of an
    audit, cancelling a `COMPLETED` registration, responding on an
    already-responded case, and so on) yields `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.2: "The only way a session reaches `CANCELLED` is the failed-audit
    cascade of §3.1, which can strike a session in `DRAFT` or `PUBLISHED`."

    Design: Corner/state_machines/cancelled_session_lockdown_publish_rejected
    """
    center, manager, session, examinee, registration = (
        _setup_published_with_registration(name="Center TL")
    )
    audit2 = schedule_audit(center["id"], scheduled_date="2026-10-20",
                            audit_type="UNANNOUNCED")
    complete_audit(audit2["id"], CASCADE_AUDIT_FINDINGS)
    session = get_session(session["id"])
    assert session["status"] == "CANCELLED", "cascade must have fired first"
    resp = api_client.publish_session(
        session["id"], make_center_manager_headers(manager["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_session(session["id"])["status"] == "CANCELLED"
