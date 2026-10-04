"""Proctor assignment: cross-center integrity and strict-overlap semantics."""
from test_helpers import (
    ApiErrorId,
    add_staff,
    api_client,
    create_authorized_center,
    create_center,
    create_session,
    get_session,
    validate_error,
    validate_success,
)
from test_helpers import make_center_manager_headers


def _three_same_day_sessions(center_id):
    """S1 08:00-12:00 R1, S2 12:00-14:00 R2, S3 13:00-15:00 R3 on 2026-10-10."""
    s1 = create_session(center_id, test_date="2026-10-10", start_time="08:00",
                        end_time="12:00", room_label="R1", total_seats=10)
    s2 = create_session(center_id, test_date="2026-10-10", start_time="12:00",
                        end_time="14:00", room_label="R2", total_seats=10)
    s3 = create_session(center_id, test_date="2026-10-10", start_time="13:00",
                        end_time="15:00", room_label="R3", total_seats=10)
    return s1, s2, s3


def test_proctor_adjacent_sessions_allowed(api):
    """PRD §3.2: "One proctor may not cover two sessions on the same
    `test_date` whose half-open start-to-end intervals strictly overlap —
    touching intervals, where one session ends exactly as another begins, are
    allowed — and a violating assignment fails with `ERR_PROCTOR_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/proctor_strict_overlap_adjacency_allowed
    """
    center = create_authorized_center(name="Center PO", facility_seat_capacity=60)
    manager = add_staff(center["id"], "Mgr PO", "CENTER_MANAGER", "ADVANCED")
    proctor = add_staff(center["id"], "Proc PO", "PROCTOR", "ADVANCED")
    s1, s2, _ = _three_same_day_sessions(center["id"])
    headers = make_center_manager_headers(manager["id"])
    validate_success(api.assign_proctor(s1["id"], {"staff_id": proctor["id"]},
                                        headers), 200)
    # S2 starts at 12:00, exactly when S1 ends: touching is not overlap.
    updated = validate_success(
        api.assign_proctor(s2["id"], {"staff_id": proctor["id"]}, headers), 200
    )
    assert proctor["id"] in updated["proctor_staff_ids"]


def test_proctor_strict_overlap_rejected(api):
    """PRD §3.2: "One proctor may not cover two sessions on the same
    `test_date` whose half-open start-to-end intervals strictly overlap —
    touching intervals, where one session ends exactly as another begins, are
    allowed — and a violating assignment fails with `ERR_PROCTOR_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/proctor_strict_overlap_adjacency_allowed
    """
    center = create_authorized_center(name="Center PO2", facility_seat_capacity=60)
    manager = add_staff(center["id"], "Mgr PO2", "CENTER_MANAGER", "ADVANCED")
    proctor = add_staff(center["id"], "Proc PO2", "PROCTOR", "ADVANCED")
    s1, s2, s3 = _three_same_day_sessions(center["id"])
    headers = make_center_manager_headers(manager["id"])
    validate_success(api.assign_proctor(s1["id"], {"staff_id": proctor["id"]},
                                        headers), 200)
    validate_success(api.assign_proctor(s2["id"], {"staff_id": proctor["id"]},
                                        headers), 200)
    # S3 13:00-15:00 strictly overlaps S2 12:00-14:00.
    resp = api.assign_proctor(s3["id"], {"staff_id": proctor["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_PROCTOR_OVERLAP)
    assert proctor["id"] in get_session(s2["id"])["proctor_staff_ids"]
    assert proctor["id"] not in get_session(s3["id"])["proctor_staff_ids"]


def test_proctor_from_other_center_rejected(api):
    """PRD §3.2: "the named staff member's `center_id` must equal the session's
    `center_id`, else the assignment fails with `ERR_PROCTOR_NOT_AT_CENTER`."

    Design: Corner/validations/proctor_from_other_center_rejected
    """
    center_a = create_authorized_center(name="Center OA", facility_seat_capacity=20)
    center_b = create_center(name="Center OB", facility_seat_capacity=20)
    manager = add_staff(center_a["id"], "Mgr OA", "CENTER_MANAGER", "ADVANCED")
    proctor_b = add_staff(center_b["id"], "Proc OB", "PROCTOR", "BASIC")
    session = create_session(center_a["id"], total_seats=5)
    resp = api.assign_proctor(
        session["id"],
        {"staff_id": proctor_b["id"]},
        make_center_manager_headers(manager["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROCTOR_NOT_AT_CENTER)
    assert get_session(session["id"])["proctor_staff_ids"] == []
