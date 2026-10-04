"""Capstone events: uniqueness, capacity, role assignment, completion (PRD §3.7)."""
from test_helpers import (
    COORDINATOR,
    ApiErrorId,
    TUESDAYS_4,
    add_roster,
    add_session,
    api_client,
    base_world,
    capstone_event_payload,
    get_capstone,
    get_delivery,
    get_student,
    make_capstone,
    make_delivery,
    plan_delivery,
    planned_delivery,
    record_session_delivery,
    schedule_delivery,
    transition_capstone,
    transition_delivery,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_duplicate_capstone_rejected(api):
    """PRD §3.7: "a delivery may carry at most one non-CANCELLED capstone event
    — a live duplicate is `ERR_DUPLICATE_CAPSTONE`. The event starts PLANNED."

    Design: Corner/validations/corner_duplicate_capstone_rejected
    """
    world = base_world(
        program_code="JA-TOWNC", capstone_required=True, capstone_facility="SIMULATED_TOWN"
    )
    delivery = planned_delivery(world, enrolled_count=10)
    first = make_capstone(delivery["id"], event_date="2026-10-13")
    assert first["status"] == "PLANNED"

    resp = api_client.create_capstone_event(
        capstone_event_payload(delivery["id"], event_date="2026-10-14"), COORDINATOR
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CAPSTONE)
    rows, _ = validate_paginated(
        api_client.list_capstone_events(COORDINATOR, params={"delivery_id": delivery["id"]})
    )
    assert len(rows) == 1


def test_role_assignment_missing_student_rejected(api):
    """PRD §3.7: "The delivery's roster size must equal its `enrolled_count`,
    the assignments must cover every roster student exactly once, each
    assignment's role must belong to the facility's role catalog, and each
    `rotation_group` must lie within 1 through `rotation_slot_count`; any
    violation is `ERR_ROLE_ASSIGNMENT_INVALID`."

    Design: Corner/validations/corner_role_assignment_missing_student_rejected
    """
    world = base_world(
        program_code="JA-TOWNR", capstone_required=True, capstone_facility="SIMULATED_TOWN",
        assemble=20,
    )
    # 4-student roster while DRAFT, matching enrolled_count 4
    delivery = make_delivery(world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=4)
    students = add_roster(delivery["id"], 4)
    assert len(students) == 4
    plan_delivery(delivery["id"])
    for date in TUESDAYS_4:
        add_session(delivery["id"], world["volunteer"]["id"], date, confirm=True)
    schedule_delivery(delivery["id"])
    capstone = make_capstone(delivery["id"], event_date="2026-10-13", rotation_slot_count=2)
    ready = transition_capstone(capstone["id"], "CONFIRM")
    assert ready["status"] == "READY"

    assignments = [
        {"student_id": students[0]["id"], "role": "MAYOR", "rotation_group": 1},
        {"student_id": students[1]["id"], "role": "BANKER", "rotation_group": 1},
        {"student_id": students[2]["id"], "role": "SHOPKEEPER", "rotation_group": 2},
    ]
    resp = api_client.transition_capstone_event(
        capstone["id"], {"action": "ASSIGN_ROLES", "assignments": assignments}, COORDINATOR
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_ASSIGNMENT_INVALID)
    after = get_capstone(capstone["id"])
    assert after["status"] == "READY"
    assert after["assigned_student_count"] == 0
    assert get_student(students[0]["id"])["capstone_role"] is None, "no partial assignment persists"


def test_delivery_complete_requires_completed_capstone(api):
    """PRD §3.4: "From IN_PROGRESS, COMPLETE requires every session of the
    delivery DELIVERED, else `ERR_SESSIONS_INCOMPLETE`, and — when the
    snapshotted program's `capstone_required` is set — the delivery's capstone
    event COMPLETED, else `ERR_CAPSTONE_REQUIRED`; completion recomputes the
    agreement's `deliveries_completed_count`."

    Design: Corner/validations/corner_delivery_complete_requires_completed_capstone
    """
    world = base_world(
        program_code="JA-TOWNC", capstone_required=True, capstone_facility="SIMULATED_TOWN",
        assemble=20,
    )
    delivery = make_delivery(world["agreement"]["id"], world["volunteer"]["id"], enrolled_count=4)
    plan_delivery(delivery["id"])
    sessions = [add_session(delivery["id"], world["volunteer"]["id"], d, confirm=True) for d in TUESDAYS_4]
    schedule_delivery(delivery["id"])
    capstone = make_capstone(delivery["id"], event_date="2026-10-13")
    ready = transition_capstone(capstone["id"], "CONFIRM")
    assert ready["status"] == "READY"
    for session, date in zip(sessions, TUESDAYS_4):
        record_session_delivery(session["id"], date)
    assert get_delivery(delivery["id"])["status"] == "IN_PROGRESS"

    resp = api_client.transition_delivery(delivery["id"], {"action": "COMPLETE"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_CAPSTONE_REQUIRED)
    assert get_delivery(delivery["id"])["status"] == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Difficulty: SIMULATED_TOWN exact-capacity + buffer edge (two tests)
# ---------------------------------------------------------------------------

def _town_cluster():
    """Four PLANNED deliveries (30/30/30/10 enrolled) with capstones at
    SIMULATED_TOWN on 2026-10-13: A [09:00-12:00], B [13:00-15:00],
    C [12:30-14:30], D [13:00-15:00]."""
    world = base_world(
        program_code="JA-TOWN", capstone_required=True, capstone_facility="SIMULATED_TOWN",
        min_students=10, max_students=60,
    )
    deliveries = {}
    for label, enrolled in (("A", 30), ("B", 30), ("C", 30), ("D", 10)):
        deliveries[label] = planned_delivery(
            world, enrolled_count=enrolled, classroom_label=f"Room {label}"
        )
    caps = {
        "A": make_capstone(deliveries["A"]["id"], event_date="2026-10-13", start_minutes=540, end_minutes=720, rotation_slot_count=3),
        "B": make_capstone(deliveries["B"]["id"], event_date="2026-10-13", start_minutes=780, end_minutes=900, rotation_slot_count=3),
        "C": make_capstone(deliveries["C"]["id"], event_date="2026-10-13", start_minutes=750, end_minutes=870, rotation_slot_count=3),
        "D": make_capstone(deliveries["D"]["id"], event_date="2026-10-13", start_minutes=780, end_minutes=900, rotation_slot_count=2),
    }
    return caps


def test_facility_confirm_buffer_edge_and_exact_capacity_allowed(api):
    """PRD §3.7: "intersection means the other event starts before the
    candidate's buffered end and the candidate starts before the other's
    buffered end, so an event beginning exactly at another's end plus the
    buffer does not conflict. The candidate delivery's `enrolled_count` plus
    the enrollments of all conflicting events' deliveries must not exceed the
    facility's seat capacity — 60 seats at SIMULATED_TOWN, 90 at FINANCE_PARK —
    with a total exactly equal to capacity allowed and anything greater
    rejected as `ERR_FACILITY_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/facility_confirm_exact_capacity_and_buffer_edge
    """
    caps = _town_cluster()
    cap_a = transition_capstone(caps["A"]["id"], "CONFIRM")
    assert cap_a["status"] == "READY", "30 <= 60"
    cap_b = transition_capstone(caps["B"]["id"], "CONFIRM")
    assert cap_b["status"] == "READY", "starts at A.end + 30 buffer: no conflict"
    cap_c = transition_capstone(caps["C"]["id"], "CONFIRM")
    assert cap_c["status"] == "READY", "conflicts only with B; cluster 30+30 == 60 == capacity"


def test_facility_confirm_cluster_over_capacity_rejected(api):
    """PRD §3.7: "The candidate delivery's `enrolled_count` plus the
    enrollments of all conflicting events' deliveries must not exceed the
    facility's seat capacity — 60 seats at SIMULATED_TOWN, 90 at FINANCE_PARK
    — with a total exactly equal to capacity allowed and anything greater
    rejected as `ERR_FACILITY_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/facility_confirm_exact_capacity_and_buffer_edge
    """
    caps = _town_cluster()
    transition_capstone(caps["A"]["id"], "CONFIRM")
    transition_capstone(caps["B"]["id"], "CONFIRM")
    transition_capstone(caps["C"]["id"], "CONFIRM")
    resp = api_client.transition_capstone_event(caps["D"]["id"], {"action": "CONFIRM"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED)  # 30+30+10 == 70 > 60
    assert get_capstone(caps["D"]["id"])["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Difficulty: FINANCE_PARK buffered aggregate (two tests)
# ---------------------------------------------------------------------------

def _park_cluster():
    """Three PLANNED deliveries (50/50/30 enrolled) with capstones at
    FINANCE_PARK on 2026-10-20: E1 [09:00-12:00], E2 [12:30-14:30],
    E3 [12:00-13:00]."""
    world = base_world(
        program_code="JA-PARK", capstone_required=True, capstone_facility="FINANCE_PARK",
        min_students=10, max_students=60,
    )
    deliveries = {}
    for label, enrolled in (("1", 50), ("2", 50), ("3", 30)):
        deliveries[label] = planned_delivery(
            world, enrolled_count=enrolled, classroom_label=f"Room 1{label}"
        )
    caps = {
        "E1": make_capstone(deliveries["1"]["id"], facility="FINANCE_PARK", event_date="2026-10-20", start_minutes=540, end_minutes=720, rotation_slot_count=4),
        "E2": make_capstone(deliveries["2"]["id"], facility="FINANCE_PARK", event_date="2026-10-20", start_minutes=750, end_minutes=870, rotation_slot_count=4),
        "E3": make_capstone(deliveries["3"]["id"], facility="FINANCE_PARK", event_date="2026-10-20", start_minutes=720, end_minutes=780, rotation_slot_count=3),
    }
    return caps


def test_facility_buffered_adjacency_not_a_conflict(api):
    """PRD §3.7: "Every event occupies an effective interval from its
    `start_minutes` to 30 minutes past its `end_minutes`, the turnover buffer.
    ... an event beginning exactly at another's end plus the buffer does not
    conflict."

    Design: Difficulty/resource_temporal_overlap/facility_buffered_overlap_aggregates_capacity
    """
    caps = _park_cluster()
    e1 = transition_capstone(caps["E1"]["id"], "CONFIRM")
    assert e1["status"] == "READY", "50 <= 90"
    e2 = transition_capstone(caps["E2"]["id"], "CONFIRM")
    assert e2["status"] == "READY", (
        "750 == E1.end 720 + 30 buffer: if it conflicted, 50+50 == 100 > 90 would reject"
    )


def test_facility_buffered_cluster_aggregate_rejected(api):
    """PRD §3.7: "Conflicting events are those at the same facility on the same
    `event_date` with status READY, ROLES_ASSIGNED, or COMPLETED whose
    effective intervals intersect the candidate's ... with a total exactly
    equal to capacity allowed and anything greater rejected as
    `ERR_FACILITY_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/facility_buffered_overlap_aggregates_capacity
    """
    caps = _park_cluster()
    transition_capstone(caps["E1"]["id"], "CONFIRM")
    transition_capstone(caps["E2"]["id"], "CONFIRM")
    resp = api_client.transition_capstone_event(caps["E3"]["id"], {"action": "CONFIRM"}, COORDINATOR)
    # E3 [720,780) sits inside both buffered intervals; 50+50+30 == 130 > 90
    validate_error(resp, ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED)
    assert get_capstone(caps["E3"]["id"])["status"] == "PLANNED"
