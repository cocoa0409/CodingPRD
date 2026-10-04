"""Education programs, docents, and school group reservations: the gallery
setup buffer, hard reservation gates, docent eligibility and ownership, the
pinned creation evaluation, waitlist promotion, and the program-cancel cascade
(PRD §3.3, §2.5)."""

from test_helpers import (
    ApiErrorId,
    assign_docent,
    cancel_reservation,
    confirm_assignment,
    create_docent,
    create_museum,
    create_program,
    create_school_reservation,
    docents_required_for,
    make_docent_headers,
    make_program_coordinator_headers,
    make_public_headers,
    reset_clock,
    setup_program_with_docents,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_program_cancel_conditional_cascade_and_terminal(api):
    """PRD §3.3: "Cancelling the program itself — a `ProgramCoordinator` action moving the program `SCHEDULED` to `CANCELLED` — cascades: every `CONFIRMED` or `WAITLISTED` reservation of the program flips to `CANCELLED`, and every docent assignment still `ASSIGNED` flips to `RELEASED`, while `CONFIRMED` assignments are left untouched as a matter of record."
    PRD §3.3: "a reservation against a cancelled program fails with `ERR_PROGRAM_NOT_SCHEDULED`"

    Design: Corner/state_machines/program_cancel_conditional_cascade_and_terminal
    """
    reset_clock()
    museum = create_museum()
    program = create_program(
        museum["id"], title="Rockets Lab", gallery_code="G3", day_of_week="MON",
        start_minute=600, end_minute=660, student_capacity=30, docent_ratio=5,
        max_group_size=40, required_docent_certification="BASIC",
    )
    docent_a = create_docent(full_name="Docent A")
    docent_b = create_docent(full_name="Docent B")
    asg_a = assign_docent(program["id"], docent_a["id"], "2026-10-05")
    asg_b = assign_docent(program["id"], docent_b["id"], "2026-10-05")
    asg_a = confirm_assignment(asg_a)
    # 1 confirmed docent < ceil(10 / 5) = 2 required: the group waitlists.
    reservation = create_school_reservation(
        museum["id"], program["id"], school_name="Rockets School",
        headcount=10, visit_date="2026-10-05",
    )
    assert reservation["status"] == "WAITLISTED"
    cancelled_program = validate_success(
        api.cancel_education_program(program["id"], headers=make_program_coordinator_headers())
    )
    assert cancelled_program["status"] == "CANCELLED"
    after_a = validate_success(
        api.get_docent_assignment(asg_a["id"], headers=make_program_coordinator_headers())
    )
    assert after_a["status"] == "CONFIRMED", "the conditional cascade skips CONFIRMED assignments"
    after_b = validate_success(
        api.get_docent_assignment(asg_b["id"], headers=make_program_coordinator_headers())
    )
    assert after_b["status"] == "RELEASED"
    after_res = validate_success(
        api.get_school_reservation(reservation["id"], headers=make_program_coordinator_headers())
    )
    assert after_res["status"] == "CANCELLED"
    resp = api.create_school_reservation(
        {
            "museum_id": museum["id"], "program_id": program["id"],
            "school_name": "Late School", "headcount": 5, "visit_date": "2026-10-12",
        },
        headers=make_public_headers("teacher-l"),
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_SCHEDULED)


def test_gallery_buffer_expanded_overlap(api):
    """PRD §3.3: "Each program occupies its gallery from thirty minutes before its `start_minute` until thirty minutes after its `end_minute`, as a half-open interval. Two programs conflict when they share the same museum, the same `gallery_code`, and the same `day_of_week`, and their buffer-expanded intervals intersect; creation of the second is rejected with `ERR_GALLERY_SCHEDULE_CONFLICT`. A gap of exactly thirty minutes between sessions is allowed — the expanded intervals touch but do not overlap."

    Design: Difficulty/resource_temporal_overlap/gallery_buffer_expanded_overlap
    """
    reset_clock()
    museum = create_museum()
    prog_a = create_program(
        museum["id"], title="Folk Art Basics", gallery_code="G1", day_of_week="MON",
        start_minute=600, end_minute=660, student_capacity=30, docent_ratio=15,
        max_group_size=30, required_docent_certification="BASIC",
    )
    # A occupies [570, 690) after the buffer; B's [650, 800) intersects it
    # (a twenty-minute gap between sessions), so creation of B is rejected.
    resp_b = api.create_education_program(
        museum["id"],
        {
            "title": "Modern Masters Walk", "gallery_code": "G1", "day_of_week": "MON",
            "start_minute": 680, "end_minute": 740, "student_capacity": 30,
            "docent_ratio": 15, "max_group_size": 30,
            "required_docent_certification": "ADVANCED",
        },
        headers=make_program_coordinator_headers(),
    )
    validate_error(resp_b, ApiErrorId.ERR_GALLERY_SCHEDULE_CONFLICT)
    # C starts exactly thirty minutes after A ends: "A gap of exactly thirty
    # minutes between sessions is allowed — the expanded intervals touch but
    # do not overlap."
    prog_c = create_program(
        museum["id"], title="Sculpture Garden Studio", gallery_code="G1", day_of_week="MON",
        start_minute=690, end_minute=750, student_capacity=30, docent_ratio=15,
        max_group_size=30, required_docent_certification="BASIC",
    )
    assert prog_c["status"] == "SCHEDULED"
    assert prog_a["status"] == "SCHEDULED"


def test_group_too_large_and_day_mismatch_rejected(api):
    """PRD §3.3: "First, hard validation: a `headcount` exceeding the program's `max_group_size` is rejected with `ERR_GROUP_TOO_LARGE`, and a `visit_date` whose weekday differs from the program's `day_of_week` is rejected with `ERR_PROGRAM_DAY_MISMATCH`"

    Design: Corner/errors/group_too_large_and_day_mismatch_rejected
    """
    reset_clock()
    museum = create_museum()
    program = create_program(
        museum["id"], title="Big Tour", gallery_code="G5", day_of_week="MON",
        start_minute=600, end_minute=660, student_capacity=100, docent_ratio=10,
        max_group_size=40, required_docent_certification="BASIC",
    )
    # Oversized groups are rejected outright, never waitlisted.
    resp_size = api.create_school_reservation(
        {
            "museum_id": museum["id"], "program_id": program["id"],
            "school_name": "Oversize School", "headcount": 41, "visit_date": "2026-10-05",
        },
        headers=make_public_headers("teacher-os"),
    )
    validate_error(resp_size, ApiErrorId.ERR_GROUP_TOO_LARGE)
    # 2026-10-06 is a Tuesday; the program recurs on Mondays.
    resp_day = api.create_school_reservation(
        {
            "museum_id": museum["id"], "program_id": program["id"],
            "school_name": "Wrong Day School", "headcount": 20, "visit_date": "2026-10-06",
        },
        headers=make_public_headers("teacher-wd"),
    )
    validate_error(resp_day, ApiErrorId.ERR_PROGRAM_DAY_MISMATCH)
    _, meta = validate_paginated(
        api.list_school_reservations(
            headers=make_program_coordinator_headers(), params={"program_id": program["id"]}
        )
    )
    assert meta["total_count"] == 0, "hard rejections create no reservation rows"


def test_docent_certification_and_double_booking_rejected(api):
    """PRD §3.3: "Three eligibility gates guard assignment, all reported as `ERR_DOCENT_NOT_CERTIFIED` (HTTP 422): the docent's certification must meet the program's `required_docent_certification`, the docent must be active, and the docent must not already be assigned to another `SCHEDULED` program on the same `service_date`."

    Design: Corner/errors/docent_certification_and_double_booking_rejected
    """
    reset_clock()
    museum = create_museum()
    prog_adv = create_program(
        museum["id"], title="Advanced Ceramics", gallery_code="A1", day_of_week="MON",
        start_minute=600, end_minute=660, required_docent_certification="ADVANCED",
    )
    prog_b = create_program(
        museum["id"], title="Basic Drawing", gallery_code="B1", day_of_week="MON",
        start_minute=600, end_minute=660, required_docent_certification="BASIC",
    )
    prog_c = create_program(
        museum["id"], title="Basic Sculpture", gallery_code="C1", day_of_week="MON",
        start_minute=600, end_minute=660, required_docent_certification="BASIC",
    )
    d1 = create_docent(full_name="Docent One")   # BASIC
    d2 = create_docent(full_name="Docent Two")   # BASIC
    asg_b = assign_docent(prog_b["id"], d2["id"], "2026-10-05")
    # Certification gate: a BASIC docent cannot serve an ADVANCED-required program.
    resp_cert = api.create_docent_assignment(
        prog_adv["id"],
        {"docent_id": d1["id"], "service_date": "2026-10-05"},
        headers=make_program_coordinator_headers(),
    )
    validate_error(resp_cert, ApiErrorId.ERR_DOCENT_NOT_CERTIFIED)
    # Double-booking gate: docent Two is already assigned to program B that day.
    resp_double = api.create_docent_assignment(
        prog_c["id"],
        {"docent_id": d2["id"], "service_date": "2026-10-05"},
        headers=make_program_coordinator_headers(),
    )
    validate_error(resp_double, ApiErrorId.ERR_DOCENT_NOT_CERTIFIED)
    after_b = validate_success(
        api.get_docent_assignment(asg_b["id"], headers=make_program_coordinator_headers())
    )
    assert after_b["status"] == "ASSIGNED", "the existing assignment is unaffected"


def test_docent_confirm_other_docents_assignment_forbidden(api):
    """PRD §3.3: "Confirmation belongs to the docent alone: a `Docent` caller whose `X-User-ID` equals the assignment's `docent_id` moves the assignment `ASSIGNED` to `CONFIRMED`, provided the program is still `SCHEDULED`."
    PRD §2.1: "a `Docent` caller may confirm only their own assignment"

    Design: Corner/rbac/docent_confirm_other_docents_assignment_forbidden
    """
    reset_clock()
    museum = create_museum()
    program = create_program(museum["id"], title="Ownership Tour", gallery_code="D1")
    d1 = create_docent(full_name="Docent One")
    d2 = create_docent(full_name="Docent Two")
    asg = assign_docent(program["id"], d1["id"], "2026-10-05")
    # Docent Two attempts to confirm docent One's assignment: X-User-ID mismatch.
    resp = api.confirm_docent_assignment(asg["id"], headers=make_docent_headers(d2["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = validate_success(
        api.get_docent_assignment(asg["id"], headers=make_program_coordinator_headers())
    )
    assert after["status"] == "ASSIGNED"


def test_school_reservation_missing_required_field_returns_400(api):
    """PRD §3.3: "School group reservations are created by `Public` organizers with a `museum_id`, a `program_id`, a `school_name`, a `headcount` of at least 1, and a `visit_date`"
    PRD §2.8: "9. **Request shape** — required fields are present, enumerations and ranges are valid (slot index between 0 and 29 inclusive, dates well-formed, an end strictly after its start), and the review-kind field pairing holds (an `ACQUISITION` review carries `fund_id`, `estimated_cost_cents`, and `proposed_object_title` with a null `object_id`; a `DEACCESSION` review carries `object_id` and `disposal_method` with a null `fund_id`), else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/school_reservation_missing_required_field_returns_400
    """
    reset_clock()
    museum = create_museum()
    program = create_program(museum["id"], title="Tour", gallery_code="G2")
    # headcount omitted: the request-shape gate fails before any evaluation.
    resp = api.create_school_reservation(
        {
            "museum_id": museum["id"], "program_id": program["id"],
            "school_name": "No Count School", "visit_date": "2026-09-07",
        },
        headers=make_public_headers("teacher-x"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(
        api.list_school_reservations(
            headers=make_program_coordinator_headers(), params={"program_id": program["id"]}
        )
    )
    assert meta["total_count"] == 0, "a shape-rejected request creates no reservation row"


def test_reservation_resolution_evaluation_order(api):
    """PRD §3.3: "Third, staffing: the docents required are the `headcount` divided by `docent_ratio` rounded up, and the docents available are the assignments for the program whose `service_date` equals the `visit_date` and whose status is `CONFIRMED`."
    PRD §3.3: "The reservation lands `CONFIRMED` exactly when capacity fits, confirmed docents are at least the required number, and no earlier waitlisted reservation blocks the queue; otherwise it lands `WAITLISTED`."
    PRD §3.3: "Waitlist promotion is a strict first-in-first-out waterfall with head-of-line blocking, triggered when a confirmed reservation is cancelled or when a docent confirms an assignment for the program and date."

    Design: Difficulty/combinatorial_formula/reservation_resolution_evaluation_order
    """
    reset_clock()
    museum = create_museum()
    program = create_program(
        museum["id"], title="Innovation Lab Tour", gallery_code="G1", day_of_week="MON",
        start_minute=600, end_minute=660, student_capacity=40, docent_ratio=10,
        max_group_size=50, required_docent_certification="BASIC",
    )
    docents = [create_docent(full_name=f"Docent {n}") for n in ("One", "Two", "Three")]
    assignments = [assign_docent(program["id"], d["id"], "2026-09-07") for d in docents]
    confirm_assignment(assignments[0])
    confirm_assignment(assignments[1])
    # Capacity fits (0 + 25 <= 40) but staffing does not: ceil(25/10) = 3 > 2.
    assert docents_required_for(25, 10) == 3
    reservation = create_school_reservation(
        museum["id"], program["id"], school_name="Jefferson Middle School",
        headcount=25, visit_date="2026-09-07",
    )
    assert reservation["status"] == "WAITLISTED"
    # The third docent's confirm — not any new reservation call — promotes it.
    confirm_assignment(assignments[2])
    rows, _ = validate_paginated(
        api.list_school_reservations(
            headers=make_program_coordinator_headers(), params={"program_id": program["id"]}
        )
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[reservation["id"]]["status"] == "CONFIRMED"


def test_waitlist_fifo_head_of_line_blocking(api):
    """PRD §3.3: "Fourth, queuing: if any earlier-created `WAITLISTED` reservation already exists for the same program and date, the new reservation queues behind it."
    PRD §3.3: "The waitlisted reservations for the program and date are scanned in `created_at` ascending order — millisecond timestamps, never resource identifiers, break ties. The head of the queue is promoted to `CONFIRMED` only if it now satisfies the capacity, docent, and queue conditions above; if the head does not fit, promotion stops immediately and later entries are never skipped to. After each successful promotion the new head is re-evaluated, and the scan repeats until the head does not fit or the queue empties."

    Design: Corner/calculations/waitlist_fifo_head_of_line_blocking
    """
    reset_clock()
    built = setup_program_with_docents(
        num_docents=6, confirm=True, service_date="2026-10-05", gallery_code="G9",
        student_capacity=40, docent_ratio=5, max_group_size=40,
    )
    museum, program = built["museum"], built["program"]
    res_a = create_school_reservation(
        museum["id"], program["id"], school_name="Alpha School", headcount=30, visit_date="2026-10-05"
    )
    res_b = create_school_reservation(
        museum["id"], program["id"], school_name="Beta School", headcount=15, visit_date="2026-10-05"
    )
    res_c = create_school_reservation(
        museum["id"], program["id"], school_name="Gamma School", headcount=10, visit_date="2026-10-05"
    )
    assert res_a["status"] == "CONFIRMED"   # 30 <= 40, 6 confirmed docents >= ceil(30/5) = 6
    assert res_b["status"] == "WAITLISTED"  # 30 + 15 = 45 > 40
    assert res_c["status"] == "WAITLISTED", (
        "C fits capacity (30 + 10 <= 40) but must queue behind the earlier WAITLISTED B"
    )
    cancel_reservation(res_a)
    rows, _ = validate_paginated(
        api.list_school_reservations(
            headers=make_program_coordinator_headers(), params={"program_id": program["id"]}
        )
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[res_a["id"]]["status"] == "CANCELLED"
    # Strict FIFO: B (the head) promotes first, then the new head C.
    assert by_id[res_b["id"]]["status"] == "CONFIRMED"  # 0 + 15 <= 40, 6 >= ceil(15/5) = 3
    assert by_id[res_c["id"]]["status"] == "CONFIRMED"  # 15 + 10 = 25 <= 40, 6 >= ceil(10/5) = 2


def test_immediate_visibility_same_response(api):
    """PRD §2.5: "Consistency is immediate: every mutation is visible in the response to the very request that performed it."
    PRD §3.3: "Creation is synchronously evaluated, and the stored state is always `CONFIRMED` or `WAITLISTED` — never `REQUESTED`, which exists only transiently during evaluation."

    Design: Corner/consistency_model/immediate_visibility_same_response
    """
    reset_clock()
    built = setup_program_with_docents(
        num_docents=1, confirm=True, service_date="2026-10-05", gallery_code="E1",
        student_capacity=40, docent_ratio=10, max_group_size=40,
    )
    reservation = create_school_reservation(
        built["museum"]["id"], built["program"]["id"],
        school_name="Consistent School", headcount=10, visit_date="2026-10-05",
    )
    # The create response itself already carries the resolved status.
    assert reservation["status"] == "CONFIRMED"
    rows, _ = validate_paginated(
        api.list_school_reservations(
            headers=make_program_coordinator_headers(),
            params={"program_id": built["program"]["id"]},
        )
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[reservation["id"]]["status"] == "CONFIRMED", (
        "the re-read shows the identical value with no lag"
    )
