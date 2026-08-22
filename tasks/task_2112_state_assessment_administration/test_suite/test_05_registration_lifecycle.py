"""The three independent state dimensions a registration carries, and the
duplicate-seating and make-up linkage rules that guard new seats."""
from test_helpers import (
    ApiErrorId,
    add_proctor,
    advance_window_to_scoring,
    assign_proctor_to_session,
    close_out_lot,
    close_the_room,
    code_accommodations,
    complete_training,
    create_accommodation_coding_payload,
    create_attendance_payload,
    create_registration_payload,
    create_session,
    create_window,
    decide_accommodations,
    deliver_lot_to_school,
    file_report,
    make_officer_headers,
    make_proctor_headers,
    make_school_coordinator_headers,
    move_session,
    move_window,
    open_the_room,
    read_session,
    record_attendance,
    record_score,
    register_student,
    setup_makeup_ready_program,
    setup_program,
    setup_program_with_certified_proctor,
    setup_staffed_session,
    ship_lot,
    sign_affidavit,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_coding_moves_only_the_accommodation_axis_of_a_registration(api):
    """PRD §3.4: "A new registration starts with `attendance_status` `PENDING`,
    `accommodation_status` `NONE`, `score_status` `NOT_SCORED`,
    `report_delivery_status` `NOT_QUEUED`, an empty `accommodation_codes` list,
    `seats_required` 1, and null values for `accommodation_decision_note`,
    `raw_score`, `report_suppressed_reason`, and `report_delivered_at`."
    PRD §3.4: "If any submitted code is specialized-tier, the registration moves
    to `REQUESTED` and waits for the district — the school that codes may never
    approve."

    Design: Difficulty/non_linear_state_machine/registration_three_state_dimensions_advance_independently
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-0006", school_code="FH-01", lot_code="LOT-F1",
        seal_start=8000,
        window_overrides={"min_participation_pct": 50.0})
    deliver_lot_to_school(ctx)
    built = setup_staffed_session(
        ctx, room_code="R101", seat_capacity=25,
        students=[{"student_state_id": "S00000001", "grade": 12}],
        schedule=False)
    registration = built["registrations"][0]
    assert registration["attendance_status"] == "PENDING"
    assert registration["accommodation_status"] == "NONE"
    assert registration["score_status"] == "NOT_SCORED"

    coded = validate_success(api.code_accommodations(
        registration["id"], create_accommodation_coding_payload(["READ_ALOUD"]),
        make_school_coordinator_headers(ctx["school"]["id"])))

    assert coded["accommodation_status"] == "REQUESTED"
    assert coded["attendance_status"] == "PENDING", (
        "the attendance axis is untouched by a coding call")
    assert coded["score_status"] == "NOT_SCORED", (
        "the scoring axis is untouched by a coding call")
    assert coded["accommodation_codes"] == ["READ_ALOUD"]


def test_accommodation_axis_freezes_while_attendance_and_score_keep_moving(api):
    """PRD §3.4: "Coding is only accepted while the owning session is `DRAFT` or
    `SCHEDULED`, and otherwise fails with
    `ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS`."
    PRD §3.6: "The submitted `attendance_status` is one of `PRESENT`, `ABSENT`,
    or `EXCUSED`, moving the registration from `PENDING` along
    `PENDING → PRESENT`, `PENDING → ABSENT`, or `PENDING → EXCUSED` and
    incrementing its `version`."
    PRD §3.8: "The `raw_score` is written, `score_status` becomes `SCORED`, and
    the registration's `version` increments."

    Design: Difficulty/non_linear_state_machine/registration_three_state_dimensions_advance_independently
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-0006", school_code="FH-01", lot_code="LOT-F1",
        seal_start=8000,
        window_overrides={"min_participation_pct": 50.0})
    deliver_lot_to_school(ctx)
    built = setup_staffed_session(
        ctx, room_code="R101", seat_capacity=25,
        students=[{"student_state_id": "S00000001", "grade": 12}],
        schedule=False)
    registration = built["registrations"][0]
    code_accommodations(registration["id"], ["READ_ALOUD"], ctx["school"]["id"])
    decide_accommodations(registration["id"], "APPROVE", ctx["district"]["id"],
                          note="IEP on file.")
    session = move_session(built["session"]["id"], "SCHEDULED",
                           school_id=ctx["school"]["id"])
    session = open_the_room(ctx, session, 4)

    frozen = api.code_accommodations(
        registration["id"], create_accommodation_coding_payload(["SMALL_GROUP"]),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(frozen,
                   ApiErrorId.ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS.value, 409)

    present = validate_success(api.record_attendance(
        registration["id"], create_attendance_payload("PRESENT"),
        make_proctor_headers(ctx["proctor"]["id"])))
    assert present["attendance_status"] == "PRESENT", (
        "the attendance axis keeps moving while the accommodation axis is frozen")

    close_the_room(ctx, session, 4)
    close_out_lot(ctx)
    advance_window_to_scoring(ctx)
    scored = record_score(registration["id"], 77)

    assert scored["score_status"] == "SCORED"
    assert scored["raw_score"] == 77
    assert scored["attendance_status"] == "PRESENT"
    assert scored["accommodation_status"] == "APPROVED"
    assert scored["accommodation_codes"] == ["READ_ALOUD"]
    assert scored["report_delivery_status"] == "NOT_QUEUED"


def test_a_student_may_hold_only_one_initial_seat_in_a_window(api):
    """PRD §3.4: "Duplicate seating is prevented on two axes at once: a student
    may hold at most one initial registration per window — counting only
    registrations whose `makeup_of_registration_id` is null and whose
    `attendance_status` is not `WITHDRAWN` — and any given original registration
    may be replaced by at most one make-up seat. Either collision is
    `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/validations/duplicate_initial_registration_for_the_same_student_is_rejected
    """
    ctx = setup_program(district_code="NG-1029", school_code="OS-01",
                        lot_code="LOT-V1", seal_start=4500)
    session_a = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R101", seat_capacity=20)
    session_b = create_session(ctx["window"]["id"], ctx["school"]["id"],
                               room_code="R102", seat_capacity=20,
                               scheduled_start="2026-09-09T09:00:00Z",
                               scheduled_end="2026-09-09T12:00:00Z")
    register_student(session_a["id"], ctx["school"]["id"],
                     student_state_id="S00000001")

    collision = api.create_registration(
        create_registration_payload(session_b["id"],
                                    student_state_id="S00000001", grade=10),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(collision, ApiErrorId.ERR_DUPLICATE_REGISTRATION.value, 409)

    accepted = validate_success(api.create_registration(
        create_registration_payload(session_b["id"],
                                    student_state_id="S00000002", grade=10,
                                    guardian_email="g2@fam.example"),
        make_school_coordinator_headers(ctx["school"]["id"])), expected_status=201)
    assert accepted["student_state_id"] == "S00000002"

    data, meta = validate_paginated(api.list_registrations(
        make_officer_headers(), params={"session_id": session_b["id"]}))
    assert meta["total_count"] == 1
    assert read_session(session_b["id"])["seats_consumed"] == 1


def test_makeup_seat_may_not_be_run_by_the_original_proctor(api):
    """PRD §3.4: "The segregation-of-duties gate is evaluated first: if both the
    make-up session and the session that held the original registration have a
    `proctor_id`, those two proctors must differ, or the request is rejected
    with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.11: "And a make-up seat may never be proctored by the proctor who ran
    the session the student originally missed."

    Design: Corner/validations/makeup_registration_enforces_segregation_eligibility_and_single_use
    """
    ctx = setup_makeup_ready_program()
    absent_seat = ctx["registrations"][0]
    assert absent_seat["attendance_status"] == "ABSENT"

    same_proctor = api.create_registration(
        create_registration_payload(
            ctx["session_b"]["id"], student_state_id="S00000001", grade=10,
            makeup_of_registration_id=absent_seat["id"]),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(same_proctor, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 422)

    makeup = validate_success(api.create_registration(
        create_registration_payload(
            ctx["session_c"]["id"], student_state_id="S00000001", grade=10,
            makeup_of_registration_id=absent_seat["id"]),
        make_school_coordinator_headers(ctx["school"]["id"])), expected_status=201)
    assert makeup["makeup_of_registration_id"] == absent_seat["id"]
    assert makeup["attendance_status"] == "PENDING"
    assert makeup["session_id"] == ctx["session_c"]["id"]


def test_makeup_linkage_requires_an_eligible_original_used_only_once(api):
    """PRD §3.4: "Only then is linkage eligibility tested: the original
    registration must carry the same `student_state_id`, must sit inside the
    same test window, must either have an `attendance_status` of `ABSENT` or
    `EXCUSED` or have a `score_status` of `INVALIDATED`, and the target session
    must have `session_type` `MAKEUP`. Any failure among those is
    `ERR_MAKEUP_NOT_ELIGIBLE`."
    PRD §3.4: "Duplicate seating is prevented on two axes at once: a student may
    hold at most one initial registration per window — counting only
    registrations whose `makeup_of_registration_id` is null and whose
    `attendance_status` is not `WITHDRAWN` — and any given original registration
    may be replaced by at most one make-up seat. Either collision is
    `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/validations/makeup_registration_enforces_segregation_eligibility_and_single_use
    """
    ctx = setup_makeup_ready_program()
    absent_seat, present_seat = ctx["registrations"]
    validate_success(api.create_registration(
        create_registration_payload(
            ctx["session_c"]["id"], student_state_id="S00000001", grade=10,
            makeup_of_registration_id=absent_seat["id"]),
        make_school_coordinator_headers(ctx["school"]["id"])), expected_status=201)

    not_eligible = api.create_registration(
        create_registration_payload(
            ctx["session_c"]["id"], student_state_id="S00000002", grade=10,
            guardian_email="g2@fam.example",
            makeup_of_registration_id=present_seat["id"]),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(not_eligible, ApiErrorId.ERR_MAKEUP_NOT_ELIGIBLE.value, 422)

    second_makeup = api.create_registration(
        create_registration_payload(
            ctx["session_c"]["id"], student_state_id="S00000001", grade=10,
            makeup_of_registration_id=absent_seat["id"]),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(second_makeup, ApiErrorId.ERR_DUPLICATE_REGISTRATION.value, 409)

    data, meta = validate_paginated(api.list_registrations(
        make_officer_headers(),
        params={"makeup_of_registration_id": absent_seat["id"]}))
    assert meta["total_count"] == 1, "an original may be replaced only once"


def test_newly_created_rows_sit_in_their_declared_initial_states(api):
    """PRD §3.5: "A shipped lot begins in `SHIPPED` with all four of its custody
    buckets — `quantity_at_district`, `quantity_at_school`,
    `quantity_in_sessions`, and `quantity_destroyed` — at 0,
    `chain_accounted_count` at 0, `missing_count` and `seal_broken_count` and
    `replacement_charge_cents` at 0, `charge_reversed` false, and
    `declared_accounted_count`, `chain_vs_declared_delta`, and `reconciled_at`
    all null."
    PRD §3.4: "A new registration starts with `attendance_status` `PENDING`,
    `accommodation_status` `NONE`, `score_status` `NOT_SCORED`,
    `report_delivery_status` `NOT_QUEUED`, an empty `accommodation_codes` list,
    `seats_required` 1, and null values for `accommodation_decision_note`,
    `raw_score`, `report_suppressed_reason`, and `report_delivered_at`."
    PRD §3.7: "The filed report begins in `DRAFT` with `system_generated` false,
    `return_count` 0, `material_lot_id` and `disposition` and `adjudicated_at`
    null, and `reporter_proctor_id` taken from the filer's `X-User-ID`."
    PRD §3.2: "**`PLANNED → CANCELLED`** abandons a window before it ever opens,
    and is permitted only while no session exists in the window at all."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    ctx = setup_program(district_code="NG-1008", school_code="TH-01",
                        open_the_window=False, ship_a_lot=False)
    abandoned = move_window(ctx["window"]["id"], "CANCELLED")
    assert abandoned["status"] == "CANCELLED"

    window_two = create_window(name="Fall ELA G9-12 rev")
    proctor = add_proctor(ctx["school"]["id"])
    proctor = complete_training(proctor["id"], ctx["school"]["id"], 92.0)
    affidavit = sign_affidavit(proctor["id"], window_two["id"],
                               expected_proctor_version=proctor["version"])
    assert affidavit["status"] == "ACTIVE"

    lot = ship_lot(window_two["id"], ctx["district"]["id"], lot_code="LOT-Z4",
                   quantity_shipped=10, seal_range_start=2500)
    assert lot["status"] == "SHIPPED"
    assert lot["quantity_at_district"] == 0
    assert lot["quantity_at_school"] == 0
    assert lot["quantity_in_sessions"] == 0
    assert lot["quantity_destroyed"] == 0
    assert lot["chain_accounted_count"] == 0
    assert lot["charge_reversed"] is False
    assert lot["declared_accounted_count"] is None
    assert lot["reconciled_at"] is None

    move_window(window_two["id"], "OPEN")
    session = create_session(window_two["id"], ctx["school"]["id"],
                             room_code="R101", seat_capacity=20)
    assert session["status"] == "DRAFT"
    session = assign_proctor_to_session(session, proctor["id"],
                                        ctx["school"]["id"])

    registration = register_student(session["id"], ctx["school"]["id"],
                                    student_state_id="S00000001")
    assert registration["attendance_status"] == "PENDING"
    assert registration["accommodation_status"] == "NONE"
    assert registration["score_status"] == "NOT_SCORED"
    assert registration["report_delivery_status"] == "NOT_QUEUED"
    assert registration["accommodation_codes"] == []
    assert registration["seats_required"] == 1
    assert registration["raw_score"] is None

    report = file_report(session["id"], proctor["id"], category="TECH_FAILURE",
                         severity="LOW",
                         narrative="One workstation rebooted during setup.")
    assert report["status"] == "DRAFT"
    assert report["return_count"] == 0
    assert report["system_generated"] is False
    assert report["reporter_proctor_id"] == proctor["id"]
    assert report["disposition"] is None
    assert report["adjudicated_at"] is None
