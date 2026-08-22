"""Payload factories — one per resource, carrying only client-supplied fields."""
from .constants import TEST_CALENDAR, TEST_DEFAULTS


def create_district_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["DISTRICT_NAME"],
        "district_code": "NG-0001",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_school_payload(district_id, **overrides) -> dict:
    payload = {
        "district_id": district_id,
        "name": "Alder High",
        "school_code": "AH-01",
        "max_concurrent_seats": TEST_DEFAULTS["SCHOOL_MAX_SEATS"],
    }
    payload.update(overrides)
    return payload


def create_test_window_payload(**overrides) -> dict:
    payload = {
        "name": "Fall ELA G9-12",
        "subject": "ELA",
        "grade_band": "G9_12",
        "window_start": TEST_CALENDAR["WINDOW_START"],
        "window_end": TEST_CALENDAR["WINDOW_END"],
        "makeup_start": TEST_CALENDAR["MAKEUP_START"],
        "makeup_end": TEST_CALENDAR["MAKEUP_END"],
    }
    payload.update(overrides)
    return payload


def create_material_lot_payload(window_id, district_id, **overrides) -> dict:
    quantity = overrides.pop("quantity_shipped", TEST_DEFAULTS["LOT_QUANTITY"])
    seal_start = overrides.pop("seal_range_start", 3000)
    payload = {
        "window_id": window_id,
        "district_id": district_id,
        "lot_code": "LOT-A1",
        "quantity_shipped": quantity,
        "seal_range_start": seal_start,
        "seal_range_end": seal_start + quantity - 1,
    }
    payload.update(overrides)
    return payload


def create_custody_event_payload(event_type, quantity, **overrides) -> dict:
    payload = {
        "event_type": event_type,
        "quantity": quantity,
        "sealed_count": overrides.pop("sealed_count", quantity),
    }
    payload.update(overrides)
    return payload


def create_reconciliation_payload(declared_returned_count,
                                  declared_destroyed_count=0,
                                  broken_seal_count=0,
                                  **overrides) -> dict:
    payload = {
        "declared_returned_count": declared_returned_count,
        "declared_destroyed_count": declared_destroyed_count,
        "broken_seal_count": broken_seal_count,
    }
    payload.update(overrides)
    return payload


def create_proctor_payload(school_id, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "full_name": "Ada Proctor",
        "email": "ada@ng.gov",
    }
    payload.update(overrides)
    return payload


def create_training_completion_payload(quiz_score_pct=92.0, **overrides) -> dict:
    payload = {"module_version": "2026.1", "quiz_score_pct": quiz_score_pct}
    payload.update(overrides)
    return payload


def create_security_affidavit_payload(proctor_id, window_id,
                                      expected_proctor_version, **overrides) -> dict:
    payload = {
        "proctor_id": proctor_id,
        "window_id": window_id,
        "affidavit_version": "2026.1",
        "expected_proctor_version": expected_proctor_version,
    }
    payload.update(overrides)
    return payload


def create_session_payload(window_id, school_id, **overrides) -> dict:
    payload = {
        "window_id": window_id,
        "school_id": school_id,
        "room_code": "R101",
        "scheduled_start": TEST_CALENDAR["SESSION_START"],
        "scheduled_end": TEST_CALENDAR["SESSION_END"],
        "seat_capacity": TEST_DEFAULTS["SESSION_SEAT_CAPACITY"],
        "session_type": "INITIAL",
    }
    payload.update(overrides)
    return payload


def create_proctor_assignment_payload(proctor_id, expected_session_version,
                                      **overrides) -> dict:
    payload = {
        "proctor_id": proctor_id,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def create_registration_payload(session_id, student_state_id="S00000001",
                                grade=10, **overrides) -> dict:
    """Build a registration body.

    Passing guardian_email=None omits the optional address entirely, which is
    the shape a family with no address on file produces.
    """
    payload = {
        "session_id": session_id,
        "student_state_id": student_state_id,
        "grade": grade,
        "guardian_email": "g1@fam.example",
    }
    payload.update(overrides)
    if payload.get("guardian_email") is None:
        payload.pop("guardian_email", None)
    return payload


def create_accommodation_coding_payload(accommodation_codes, **overrides) -> dict:
    payload = {"accommodation_codes": list(accommodation_codes)}
    payload.update(overrides)
    return payload


def create_accommodation_decision_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_attendance_payload(attendance_status, **overrides) -> dict:
    payload = {"attendance_status": attendance_status}
    payload.update(overrides)
    return payload


def create_score_payload(raw_score, **overrides) -> dict:
    payload = {"raw_score": raw_score}
    payload.update(overrides)
    return payload


def create_irregularity_report_payload(session_id, category="ADMIN_ERROR",
                                       severity="MEDIUM", **overrides) -> dict:
    payload = {
        "session_id": session_id,
        "category": category,
        "severity": severity,
        "narrative": "Seating chart did not match the roster.",
    }
    payload.update(overrides)
    return payload


def create_transition_payload(to_status, **overrides) -> dict:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def create_score_appeal_payload(registration_id, reason_code="SCORING_ERROR",
                                **overrides) -> dict:
    payload = {
        "registration_id": registration_id,
        "reason_code": reason_code,
        "narrative": "Constructed-response section was scored against the wrong key.",
    }
    payload.update(overrides)
    return payload


def create_appeal_decision_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload
