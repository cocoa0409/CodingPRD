"""Corner queue: rbac — denials and student-owned shared operations; plus
cross-cutting complexity layers (OCC success path, scheduled tour sync)."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_level, create_student, create_term_draft, create_instructor,
    create_section_payload, reset_clock, setup_open_term_with_section,
    enroll_with_fresh_version, confirm_enrollment, run_term_to_close,
    create_venue_slot, create_ensemble_cast_payload, create_audition_payload,
    create_touring_assignment_payload, make_student_headers, set_clock,
    get_tour, get_section,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
CD = TEST_USERS["casting_director_headers"]


def test_casting_director_cannot_open_term_enrollment():
    """PRD §2.1: "A request whose role is not authorized for the target endpoint is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/casting_director_cannot_open_term_enrollment
    """
    reset_clock()
    term = create_term_draft()
    validate_success(api_client.open_scheduling(term["id"], PD))
    resp = api_client.open_enrollment(term["id"], CD)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)


def test_registrar_cannot_evaluate_audition():
    """PRD §2.1: "A request whose role is not authorized for the target endpoint is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §2.1: "`CastingDirector` — owns auditions, ensemble casting, and touring
    assignments."

    Design: Corner/rbac/registrar_cannot_evaluate_audition
    """
    reset_clock()
    student = create_student()
    aud = validate_success(api_client.create_audition(
        create_audition_payload(student["id"], "ENSEMBLE",
                                rubric_scores={"scene_work": 5, "characters": 5,
                                               "musicality": 5, "game": 5}), CD), 201)
    resp = api_client.evaluate_audition(aud["id"], REG)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)


def _touring_setup():
    """Student s1 (principal), s2 (alumni understudy), PROPOSED tour assignment."""
    # capacity=1 so the single CONFIRMED enrollment fills the section: at
    # start-session the section advances LOCKED -> RUNNING, and at term close the
    # enrollment completes and the student becomes an alumnus (PRD §3.1/§3.3).
    ctx = setup_open_term_with_section(capacity=1)
    s1 = create_student()
    s2 = create_student()
    # s2 becomes alumni: complete a no-showcase level enrollment
    enr = enroll_with_fresh_version(s2["id"], ctx["section"]["id"])
    confirm_enrollment(enr["id"])
    run_term_to_close(ctx["section"]["id"])
    slot = create_venue_slot(venue_name="M")
    cast = validate_success(api_client.create_ensemble_cast(
        create_ensemble_cast_payload(slot["id"], cast_size=1, understudy_slots=1,
                                     source_policy="OPEN_CALL"), CD), 201)
    tour = validate_success(api_client.create_touring_assignment(
        create_touring_assignment_payload(cast["id"], s1["id"], s2["id"]), CD), 201)
    return s1, s2, cast, tour


def test_student_can_accept_own_touring_assignment():
    """PRD §3.9: "The principal — and only the principal; the acting student must be
    the `principal_student_id` — accepts (`PROPOSED → ACCEPTED`) or declines
    (`PROPOSED → DECLINED`, terminal). Acceptance sets `travel_committed` true,
    recording that travel is booked through the end-of-tour return."

    Design: Corner/rbac/student_can_accept_own_touring_assignment
    """
    s1, s2, cast, tour = _touring_setup()
    accepted = validate_success(api_client.accept_touring_assignment(
        tour["id"], make_student_headers(s1["id"])))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["travel_committed"] is True


def test_occ_enrollment_create_correct_version_succeeds():
    """PRD §2.5: "Creating an enrollment requires `expected_section_version` in the
    request body, carrying the client's last observed `version` of the target
    section."
    PRD §2.5: "Successful mutations of the parent entity increment its `version` by
    1, which is precisely what invalidates outstanding expected-version tokens."

    Design: Corner/cross_cutting_complexity_layers/occ_enrollment_create_correct_version_succeeds
    """
    ctx = setup_open_term_with_section(capacity=4)
    student = create_student()
    before_version = ctx["section"]["version"]
    enr = enroll_with_fresh_version(student["id"], ctx["section"]["id"])
    assert enr["status"] == "REGISTERED"
    section_after = get_section(ctx["section"]["id"])
    assert section_after["version"] == before_version + 1


def test_scheduled_action_touring_sync_state_progression():
    """PRD §3.9: "From `ACCEPTED`, two time-based transitions are evaluated lazily
    against the logical clock and can be polled through the sync capability: once
    the current time reaches `tour_start_utc` the assignment moves `ACCEPTED → ON_TOUR`, and once it reaches `tour_end_utc` it moves `ON_TOUR → RETURNED` (terminal) and the understudy's coverage obligation is released."

    Design: Corner/cross_cutting_complexity_layers/scheduled_action_touring_sync_state_progression
    """
    s1, s2, cast, tour = _touring_setup()
    validate_success(api_client.accept_touring_assignment(
        tour["id"], make_student_headers(s1["id"])))
    set_clock("2027-05-15T00:00:00Z")  # before tour_start 2027-06-01
    synced = validate_success(api_client.sync_touring_assignment(tour["id"], CD))
    assert synced["status"] == "ACCEPTED"
    set_clock("2027-06-05T00:00:00Z")  # between start and end
    synced = validate_success(api_client.sync_touring_assignment(tour["id"], CD))
    assert synced["status"] == "ON_TOUR"
    set_clock("2027-06-20T00:00:00Z")  # after tour_end 2027-06-15
    synced = validate_success(api_client.sync_touring_assignment(tour["id"], CD))
    assert synced["status"] == "RETURNED"
