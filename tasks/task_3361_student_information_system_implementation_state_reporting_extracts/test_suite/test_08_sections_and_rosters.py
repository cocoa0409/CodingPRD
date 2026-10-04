"""Sections: creation defaults, commit gates, buffered overlap, roster capacity
and the add/drop compensating invariant."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_section,
    create_course,
    create_live_district,
    create_open_school_year,
    create_published_spec,
    create_school_year,
    create_section,
    create_section_payload,
    create_student_with_enrollment,
    open_school_year,
    reset_clock,
    roster_add,
    setup_base,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_section_create_roster_count_input_ignored(api, registrar_headers):
    """PRD §3.3: "New sections begin `DRAFT` with `roster_count` at zero; that count
    is computed from active roster links, and any client-supplied value for it is
    ignored."

    Design: Corner/entities/section_create_roster_count_input_ignored
    """
    reset_clock()
    district = create_live_district()
    year = create_open_school_year(district["id"])
    course = create_course(district["id"])

    payload = create_section_payload(course["id"], year["id"])
    payload["roster_count"] = 99
    res = api.create_section(payload, registrar_headers)
    section = validate_success(res, 201)
    assert_section(section)
    assert section["roster_count"] == 0, \
        "the client-supplied roster_count of 99 must be ignored"
    assert section["status"] == "DRAFT"


def test_section_get_with_unknown_id_returns_not_found(api, registrar_headers):
    """PRD §2.8: "the first identifier that does not resolve to an existing resource
    determines the response: ... `ERR_SECTION_NOT_FOUND` ..., each an HTTP 404."

    Design: Corner/entities/section_get_with_unknown_id_returns_not_found
    """
    reset_clock()
    res = api.get_section(NON_EXISTENT_UUID, registrar_headers)
    validate_error(res, ApiErrorId.ERR_SECTION_NOT_FOUND, expected_status=404)


def test_section_cancel_clears_roster_and_blocks_further_adds(api, registrar_headers):
    """PRD §3.3: "Cancellation moves a `DRAFT` or `COMMITTED` section to `CANCELLED`
    (from any other state, `ERR_SECTION_NOT_CANCELLABLE`) and clears the roster:
    every active roster link is removed and `roster_count` returns to zero."
    PRD §3.3: "Adding an enrollment to a roster requires the section to be `DRAFT` or
    `COMMITTED` (else `ERR_SECTION_NOT_ROSTERABLE`)".

    Design: Corner/state_machines/section_cancel_clears_roster_and_blocks_further_adds
    """
    district, spec, year = setup_base()
    course = create_course(district["id"])
    section = create_section(course["id"], year["id"])
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    roster_add(section["id"], enrollment["id"])

    cancelled = validate_success(api.cancel_section(section["id"], registrar_headers), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["roster_count"] == 0

    roster, meta = validate_paginated(
        api.get_section_roster(section["id"], registrar_headers))
    assert roster == [], "cancel removes every active roster link"

    res = api.roster_add(section["id"], {"enrollment_id": enrollment["id"]},
                         registrar_headers)
    validate_error(res, ApiErrorId.ERR_SECTION_NOT_ROSTERABLE, expected_status=409)


def test_sections_list_filters_by_room_and_status(api, registrar_headers):
    """PRD §2.3: "In addition to the pagination pair, each list endpoint accepts the
    documented filter query parameters for its resource — for example `district_id`,
    `state_code`, `status`, `student_id`, `school_year_id`, `course_id`,
    `teacher_ref`, `room`, `lifecycle`, `absence_posture`, `enrollment_id`,
    `collection_spec_id`, `supersedes_extract_id`, `platform`,
    `source_school_year_id`, or `target_school_year_id` — as enumerated per endpoint
    in §4."

    Design: Corner/endpoints/sections_list_filters_by_room_and_status
    """
    district, spec, year = setup_base()
    course = create_course(district["id"])
    sec_a = create_section(course["id"], year["id"], teacher_ref="T1", room="R1",
                           period_start_min=480, period_end_min=540)
    validate_success(api.commit_section(sec_a["id"], registrar_headers), 200)
    sec_b = create_section(course["id"], year["id"], teacher_ref="T2", room="R1",
                           period_start_min=650, period_end_min=710)
    sec_c = create_section(course["id"], year["id"], teacher_ref="T3", room="R2",
                           period_start_min=480, period_end_min=540)

    data, meta = validate_paginated(
        api.list_sections(registrar_headers, params={
            "school_year_id": year["id"], "room": "R1", "status": "DRAFT"}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in data] == [sec_b["id"]]

    _, meta_r1 = validate_paginated(
        api.list_sections(registrar_headers, params={
            "school_year_id": year["id"], "room": "R1"}))
    assert meta_r1["total_count"] == 2

    _, meta_draft = validate_paginated(
        api.list_sections(registrar_headers, params={
            "school_year_id": year["id"], "status": "DRAFT"}))
    assert meta_draft["total_count"] == 2

    data_t3, meta_t3 = validate_paginated(
        api.list_sections(registrar_headers, params={
            "school_year_id": year["id"], "teacher_ref": "T3"}))
    assert meta_t3["total_count"] == 1
    assert [row["id"] for row in data_t3] == [sec_c["id"]]


def test_section_commit_rejected_while_year_planning(api, registrar_headers):
    """PRD §3.3: "the section must be `DRAFT` (else `ERR_SECTION_NOT_DRAFT`); its
    school year must be `OPEN` (else `ERR_YEAR_NOT_OPEN`)".

    Design: Difficulty/cross_entity_state_dependency/section_commit_requires_open_school_year
    """
    reset_clock()
    district = create_live_district()
    create_published_spec()
    year = create_school_year(district["id"])  # stays PLANNING
    course = create_course(district["id"])
    section = create_section(course["id"], year["id"], teacher_ref="T1")

    res = api.commit_section(section["id"], registrar_headers)
    validate_error(res, ApiErrorId.ERR_YEAR_NOT_OPEN, expected_status=409)

    after = validate_success(api.get_section(section["id"], registrar_headers), 200)
    assert after["status"] == "DRAFT", "the rejected commit must leave the section DRAFT"


def test_section_commit_succeeds_after_year_opens(api, registrar_headers,
                                                  district_admin_headers):
    """PRD §3.3: "Committing a section — moving it `DRAFT` → `COMMITTED` — is the
    schedule's gate, and its checks run in pipeline order: the section must be
    `DRAFT` (else `ERR_SECTION_NOT_DRAFT`); its school year must be `OPEN` (else
    `ERR_YEAR_NOT_OPEN`)".

    Design: Difficulty/cross_entity_state_dependency/section_commit_requires_open_school_year
    """
    reset_clock()
    district = create_live_district()
    create_published_spec()
    year = create_school_year(district["id"])  # stays PLANNING
    course = create_course(district["id"])
    section = create_section(course["id"], year["id"], teacher_ref="T1")

    blocked = api.commit_section(section["id"], registrar_headers)
    validate_error(blocked, ApiErrorId.ERR_YEAR_NOT_OPEN, expected_status=409)

    open_school_year(year["id"])
    committed = validate_success(api.commit_section(section["id"], registrar_headers), 200)
    assert committed["status"] == "COMMITTED"


def test_section_exact_room_adjacency_rejected(api, registrar_headers):
    """PRD §3.3: "The buffered-overlap check compares the candidate against every
    `COMMITTED` section of the same school year that shares its `room` or its
    `teacher_ref`: if the two meeting windows overlap, abut exactly, or are separated
    by less than ten minutes, the commit is rejected with `ERR_SECTION_TIME_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/section_room_buffer_rejects_exact_adjacency
    """
    district, spec, year = setup_base()
    course = create_course(district["id"])
    sec_a = create_section(course["id"], year["id"], teacher_ref="T1", room="R1",
                           period_start_min=480, period_end_min=540)
    validate_success(api.commit_section(sec_a["id"], registrar_headers), 200)

    adjacent = create_section(course["id"], year["id"], teacher_ref="T2", room="R1",
                              period_start_min=540, period_end_min=600)
    res = api.commit_section(adjacent["id"], registrar_headers)
    validate_error(res, ApiErrorId.ERR_SECTION_TIME_OVERLAP, expected_status=409)

    after = validate_success(api.get_section(adjacent["id"], registrar_headers), 200)
    assert after["status"] == "DRAFT", "a rejected commit leaves the candidate DRAFT"


def test_section_ten_minute_gap_commits(api, registrar_headers):
    """PRD §3.3: "Only a gap of ten minutes or more clears — recall from §2.10 that
    year windows allow exact adjacency but section windows do not."

    Design: Difficulty/resource_temporal_overlap/section_room_buffer_rejects_exact_adjacency
    """
    district, spec, year = setup_base()
    course = create_course(district["id"])
    sec_a = create_section(course["id"], year["id"], teacher_ref="T1", room="R1",
                           period_start_min=480, period_end_min=540)
    validate_success(api.commit_section(sec_a["id"], registrar_headers), 200)

    adjacent = create_section(course["id"], year["id"], teacher_ref="T2", room="R1",
                              period_start_min=540, period_end_min=600)
    validate_error(api.commit_section(adjacent["id"], registrar_headers),
                   ApiErrorId.ERR_SECTION_TIME_OVERLAP, expected_status=409)

    spaced = create_section(course["id"], year["id"], teacher_ref="T3", room="R1",
                            period_start_min=550, period_end_min=610)
    committed = validate_success(api.commit_section(spaced["id"], registrar_headers), 200)
    assert committed["status"] == "COMMITTED", \
        "a gap of exactly ten minutes satisfies the buffered-overlap rule"


def _setup_capacity_section(api, capacity):
    """Base + course + DRAFT section with the given capacity. Returns (district,
    year, section)."""
    district, spec, year = setup_base()
    course = create_course(district["id"])
    section = create_section(course["id"], year["id"], capacity=capacity)
    return district, year, section


def _create_enrollment_n(district_id, year_id, n):
    """Create the Nth student/enrollment pair of a test. Returns the enrollment."""
    student, enrollment = create_student_with_enrollment(
        district_id, year_id,
        student_overrides={"student_number": f"S{n:03d}"},
        enrollment_overrides={"grade_level": "09"},
    )
    return enrollment


def test_roster_add_reaching_exact_capacity_succeeds(api, registrar_headers):
    """PRD §3.3: "only then is the seat check applied — when `roster_count` has
    already reached `capacity`, the addition is rejected with
    `ERR_CAPACITY_EXCEEDED`, the equality boundary included: a full section is full."

    Design: Difficulty/boundary_precision_check/roster_capacity_full_rejects_next_add
    """
    district, year, section = _setup_capacity_section(api, 2)
    en1 = _create_enrollment_n(district["id"], year["id"], 1)
    en2 = _create_enrollment_n(district["id"], year["id"], 2)

    first = validate_success(
        api.roster_add(section["id"], {"enrollment_id": en1["id"]}, registrar_headers),
        201)
    assert first["roster_count"] == 1
    second = validate_success(
        api.roster_add(section["id"], {"enrollment_id": en2["id"]}, registrar_headers),
        201)
    assert second["roster_count"] == 2, \
        "the add reaching exactly capacity succeeds — the boundary rejects only beyond it"


def test_roster_add_beyond_capacity_rejected(api, registrar_headers):
    """PRD §3.3: "only then is the seat check applied — when `roster_count` has
    already reached `capacity`, the addition is rejected with
    `ERR_CAPACITY_EXCEEDED`, the equality boundary included: a full section is full.
    A successful add creates the link and increments `roster_count` by one."

    Design: Difficulty/boundary_precision_check/roster_capacity_full_rejects_next_add
    """
    district, year, section = _setup_capacity_section(api, 2)
    en1 = _create_enrollment_n(district["id"], year["id"], 1)
    en2 = _create_enrollment_n(district["id"], year["id"], 2)
    en3 = _create_enrollment_n(district["id"], year["id"], 3)
    roster_add(section["id"], en1["id"])
    roster_add(section["id"], en2["id"])

    res = api.roster_add(section["id"], {"enrollment_id": en3["id"]}, registrar_headers)
    validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=409)

    after = validate_success(api.get_section(section["id"], registrar_headers), 200)
    assert after["roster_count"] == 2, "the rejected add must not move roster_count"


def test_roster_add_drop_pair_conserves_seat_count(api, registrar_headers):
    """PRD §3.3: "Dropping removes the active link — where none exists,
    `ERR_ROSTER_NOT_FOUND` — and decrements the count. Adding and then dropping the
    same enrollment leaves `roster_count` exactly as it was before the pair, a
    compensating invariant the roster listing reflects by exposing only currently
    active links."

    Design: Difficulty/compensating_invariant/roster_add_drop_conserves_seat_count
    """
    district, year, section = _setup_capacity_section(api, 1)
    en1 = _create_enrollment_n(district["id"], year["id"], 1)
    en2 = _create_enrollment_n(district["id"], year["id"], 2)
    added = roster_add(section["id"], en1["id"])
    assert added["roster_count"] == 1

    dropped = validate_success(
        api.roster_drop(section["id"], {"enrollment_id": en1["id"]}, registrar_headers),
        200)
    assert dropped["roster_count"] == 0, \
        "the add/drop pair leaves roster_count exactly at its pre-add value"

    # The freed seat accepts a different enrollment.
    readded = validate_success(
        api.roster_add(section["id"], {"enrollment_id": en2["id"]}, registrar_headers),
        201)
    assert readded["roster_count"] == 1


def test_roster_listing_exposes_only_active_links(api, registrar_headers):
    """PRD §3.3: "Adding and then dropping the same enrollment leaves `roster_count`
    exactly as it was before the pair, a compensating invariant the roster listing
    reflects by exposing only currently active links."

    Design: Difficulty/compensating_invariant/roster_add_drop_conserves_seat_count
    """
    district, year, section = _setup_capacity_section(api, 1)
    en1 = _create_enrollment_n(district["id"], year["id"], 1)
    en2 = _create_enrollment_n(district["id"], year["id"], 2)
    roster_add(section["id"], en1["id"])
    validate_success(
        api.roster_drop(section["id"], {"enrollment_id": en1["id"]}, registrar_headers),
        200)
    roster_add(section["id"], en2["id"])

    roster, meta = validate_paginated(
        api.get_section_roster(section["id"], registrar_headers))
    assert meta["total_count"] == 1
    assert [row["id"] for row in roster] == [en2["id"]], \
        "the dropped enrollment must not appear among active roster links"
