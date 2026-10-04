"""Practicum placements: catalog-pinned targets, host eligibility, window
validity, half-open overlap semantics, supervisor capacity and activity, and
the logging freeze at HOURS_COMPLETE.
"""

from test_helpers import (
    SUPERVISOR_MAX_ACTIVE_PLACEMENTS,
    ApiErrorId,
    create_active_catalog,
    create_placement,
    create_practicum_placement_payload,
    create_program,
    create_school,
    enroll_learner,
    log_hours,
    log_hours_payload,
    make_adult_learner_headers,
    make_program_director_headers,
    make_reviewer_headers,
    read_learner,
    read_placement,
    reset_clock,
    revoke_credential,
    setup_affiliate_host_school,
    setup_credentialed_teacher,
    setup_supervisor_with_mentees,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_placement_create_pins_target_hours_from_active_catalog(api):
    """PRD section 3.4: "At creation the placement copies the learner's
    `age_level` (immutable thereafter) and pins its `target_hours` from the
    `ACTIVE` catalog's `practicum_min_hours_by_level` for that level". PRD
    section 3.4: "The new placement's `hours_logged` starts at zero, and its
    creation advances the learner from `ENROLLED` to `IN_PRACTICUM`."

    Design: Corner/entities/placement_create_pins_target_hours_from_active_catalog
    """
    reset_clock()
    create_active_catalog()
    program = create_program(name="Pin TEP")
    learner = enroll_learner(program["id"], full_name="Pin Learner")
    host = setup_affiliate_host_school()

    placement = create_placement(learner["id"], host.school["id"], program["id"])
    assert placement["target_hours"] == 540
    assert placement["hours_logged"] == 0
    assert placement["status"] == "ACTIVE"
    assert placement["age_level"] == "EARLY_CHILDHOOD"
    assert read_learner(learner["id"])["status"] == "IN_PRACTICUM"


def test_applicant_host_school_ineligible_for_practicum(api):
    """PRD section 3.4: "The host school's membership level must be
    `AFFILIATE`, `MEMBER` or `ACCREDITED`; an `APPLICANT` host fails with
    `ERR_HOST_SCHOOL_INELIGIBLE` (HTTP 422)."

    Design: Corner/validations/applicant_host_school_ineligible_for_practicum
    """
    reset_clock()
    create_active_catalog()
    program = create_program(name="Host TEP")
    learner = enroll_learner(program["id"], full_name="Host Learner")
    applicant_host = create_school(name="Applicant Host", display_name="Applicant Host School")

    rejected = api.create_practicum_placement(
        create_practicum_placement_payload(learner["id"], applicant_host["id"]),
        headers=make_program_director_headers(program["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_HOST_SCHOOL_INELIGIBLE)

    rows, meta = validate_paginated(
        api.list_practicum_placements(
            headers=make_program_director_headers(program["id"]),
            params={"learner_id": learner["id"]},
        )
    )
    assert rows == [] and meta["total_count"] == 0
    assert read_learner(learner["id"])["status"] == "ENROLLED"


def test_placement_window_invalid_on_create_and_on_log_date(api):
    """PRD section 3.4: "The window must make sense against the logical clock:
    `end_date` strictly after `start_date` and strictly after the current
    logical date, else `ERR_PLACEMENT_WINDOW_INVALID` (HTTP 422)." PRD section
    3.4: "a `work_date` that must fall inside the placement window from
    `start_date` through `end_date`, failing outside it with
    `ERR_PLACEMENT_WINDOW_INVALID` (HTTP 422)".

    Design: Corner/validations/placement_window_invalid_on_create_and_on_log_date
    """
    reset_clock()
    create_active_catalog()
    program = create_program(name="Win TEP")
    learner = enroll_learner(program["id"], full_name="Win Learner")
    host = setup_affiliate_host_school()

    empty_window = api.create_practicum_placement(
        create_practicum_placement_payload(
            learner["id"], host.school["id"], start_date="2026-09-15", end_date="2026-09-15"
        ),
        headers=make_program_director_headers(program["id"]),
    )
    validate_error(empty_window, ApiErrorId.ERR_PLACEMENT_WINDOW_INVALID)

    placement = create_placement(learner["id"], host.school["id"], program["id"])
    late_log = api.log_placement_hours(
        placement["id"],
        log_hours_payload(8, "2027-03-16"),
        headers=make_adult_learner_headers(learner["id"]),
    )
    validate_error(late_log, ApiErrorId.ERR_PLACEMENT_WINDOW_INVALID)
    assert read_placement(placement["id"])["hours_logged"] == 0


def test_supervisor_capacity_three_allowed_fourth_rejected(api):
    """PRD section 3.4: "the credential must be supervising fewer than 3 other
    `ACTIVE` placements — exactly 3 supervised placements is allowed, and a
    fourth is rejected with `ERR_SUPERVISOR_CAPACITY_EXCEEDED` (HTTP 422)".

    Design: Corner/validations/supervisor_capacity_three_allowed_fourth_rejected
    """
    reset_clock()
    staged = setup_supervisor_with_mentees(mentee_count=3)
    supervisor = staged.supervisor
    for placement in staged.placements:
        assert placement["status"] == "ACTIVE"

    fourth_mentee = enroll_learner(supervisor.program["id"], full_name="Mentee Four")
    overflow = api.create_practicum_placement(
        create_practicum_placement_payload(
            fourth_mentee["id"],
            supervisor.host.school["id"],
            supervisor_credential_id=supervisor.credential["id"],
            start_date="2027-04-01",
            end_date="2027-10-01",
        ),
        headers=make_program_director_headers(supervisor.program["id"]),
    )
    validate_error(overflow, ApiErrorId.ERR_SUPERVISOR_CAPACITY_EXCEEDED)

    rows, meta = validate_paginated(
        api.list_practicum_placements(
            headers=make_program_director_headers(supervisor.program["id"]),
            params={"supervisor_credential_id": supervisor.credential["id"]},
        )
    )
    assert len(rows) == SUPERVISOR_MAX_ACTIVE_PLACEMENTS
    assert meta["total_count"] == SUPERVISOR_MAX_ACTIVE_PLACEMENTS


def test_inactive_supervisor_credential_rejected(api):
    """PRD section 3.4: "the credential must be `ACTIVE`, failing with
    `ERR_SUPERVISOR_CREDENTIAL_INACTIVE` (HTTP 409) when lapsed, expired or
    revoked".

    Design: Corner/validations/inactive_supervisor_credential_rejected
    """
    reset_clock()
    supervisor = setup_credentialed_teacher(learner_name="Sup ToBe")
    revoke_credential(
        supervisor.credential["id"],
        reviewer_headers=make_reviewer_headers("rev-mira"),
        reason="Code of ethics violation",
    )
    mentee = enroll_learner(supervisor.program["id"], full_name="Mentee X")

    rejected = api.create_practicum_placement(
        create_practicum_placement_payload(
            mentee["id"],
            supervisor.host.school["id"],
            supervisor_credential_id=supervisor.credential["id"],
            start_date="2027-04-01",
            end_date="2027-10-01",
        ),
        headers=make_program_director_headers(supervisor.program["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_SUPERVISOR_CREDENTIAL_INACTIVE)

    rows, _ = validate_paginated(
        api.list_practicum_placements(
            headers=make_program_director_headers(supervisor.program["id"]),
            params={"learner_id": mentee["id"]},
        )
    )
    assert rows == []


def test_placement_log_hours_after_hours_complete_rejected(api):
    """PRD section 3.4: "Logging is accepted only while the placement is
    `ACTIVE`; a placement that has already completed, been verified or been
    cancelled rejects further logging with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/placement_log_hours_after_hours_complete_rejected
    """
    reset_clock()
    create_active_catalog()
    program = create_program(name="Freeze TEP")
    learner = enroll_learner(program["id"], full_name="Freeze Learner")
    host = setup_affiliate_host_school()
    placement = create_placement(learner["id"], host.school["id"], program["id"])
    completed = log_hours(placement["id"], learner["id"], 540)
    assert completed["status"] == "HOURS_COMPLETE"

    rejected = api.log_placement_hours(
        placement["id"],
        log_hours_payload(4, "2026-12-05"),
        headers=make_adult_learner_headers(learner["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)
    assert read_placement(placement["id"])["hours_logged"] == 540


def test_learner_placement_true_overlap_rejected(api):
    """PRD section 3.4: "One learner holds at most one date-overlapping
    placement in `ACTIVE` or `HOURS_COMPLETE`: windows are treated as half-open
    — the start date inclusive, the end date exclusive — so one placement's
    `end_date` may equal another's `start_date` without conflict, while a true
    intersection fails with `ERR_PLACEMENT_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/learner_practicum_half_open_overlap_adjacency_allowed
    """
    reset_clock()
    create_active_catalog()
    program = create_program(name="Overlap TEP")
    learner = enroll_learner(program["id"], full_name="Overlap Learner")
    host = setup_affiliate_host_school()
    create_placement(learner["id"], host.school["id"], program["id"])

    overlapping = api.create_practicum_placement(
        create_practicum_placement_payload(
            learner["id"],
            host.school["id"],
            start_date="2027-01-10",
            end_date="2027-06-10",
        ),
        headers=make_program_director_headers(program["id"]),
    )
    validate_error(overlapping, ApiErrorId.ERR_PLACEMENT_WINDOW_OVERLAP)


def test_learner_placement_adjacent_window_allowed(api):
    """PRD section 3.4: "windows are treated as half-open — the start date
    inclusive, the end date exclusive — so one placement's `end_date` may equal
    another's `start_date` without conflict".

    Design: Difficulty/resource_temporal_overlap/learner_practicum_half_open_overlap_adjacency_allowed
    """
    reset_clock()
    create_active_catalog()
    program = create_program(name="Overlap TEP")
    learner = enroll_learner(program["id"], full_name="Overlap Learner")
    host = setup_affiliate_host_school()
    first = create_placement(learner["id"], host.school["id"], program["id"])

    adjacent = api.create_practicum_placement(
        create_practicum_placement_payload(
            learner["id"],
            host.school["id"],
            start_date=first["end_date"],
            end_date="2027-09-15",
        ),
        headers=make_program_director_headers(program["id"]),
    )
    created = validate_success(adjacent, 201)
    assert created["status"] == "ACTIVE"
    assert created["target_hours"] == 540, "pinned from the ACTIVE catalog"
    assert created["start_date"] == "2027-03-15"
