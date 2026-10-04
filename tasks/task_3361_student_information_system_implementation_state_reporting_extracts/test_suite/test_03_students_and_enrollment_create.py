"""Student registration, enrollment creation, and list pagination."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_enrollment,
    create_district_payload,
    create_enrollment_payload,
    create_live_district,
    create_open_school_year,
    create_published_spec,
    create_student,
    create_student_payload,
    create_student_with_enrollment,
    get_student,
    reset_clock,
    setup_base,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_students_list_paginates_with_total_count_and_has_more(
        api, platform_admin_headers, registrar_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter
    specifies how many items to skip and defaults to 0."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/students_list_paginates_with_total_count_and_has_more
    """
    reset_clock()
    district = validate_success(
        api.create_district(create_district_payload(), platform_admin_headers), 201)
    create_student(district["id"], student_number="S001")
    create_student(district["id"], student_number="S002", first_name="Bo",
                   last_name="Reyes", birth_date="2013-09-09T00:00:00Z",
                   entry_grade_level="KG")
    create_student(district["id"], student_number="S003", first_name="Cid",
                   last_name="Mira", birth_date="2012-01-15T00:00:00Z",
                   entry_grade_level="10")

    page1, meta1 = validate_paginated(
        api.list_students(registrar_headers,
                          params={"district_id": district["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_students(registrar_headers,
                          params={"district_id": district["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    page_all, meta_all = validate_paginated(
        api.list_students(registrar_headers, params={"district_id": district["id"]}))
    assert len(page_all) == 3, "the default limit of 10 returns all three rows"
    assert meta_all["has_more"] is False


def test_enrollment_create_with_invalid_grade_enum_returns_invalid_request(
        api, registrar_headers):
    """PRD §2.7: "Required body fields are present, enum values fall inside their
    declared sets, and numeric ranges are sane; otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.4: "the student's `grade_level` for that year (the same `KG`-through-`12`
    set)".

    Design: Corner/entities/enrollment_create_with_invalid_grade_enum_returns_invalid_request
    """
    reset_clock()
    district = create_live_district()
    year = create_open_school_year(district["id"])
    student = create_student(district["id"])

    res = api.create_enrollment(
        create_enrollment_payload(student["id"], year["id"], grade_level="13"),
        registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    data, meta = validate_paginated(
        api.list_enrollments(registrar_headers, params={"student_id": student["id"]}))
    assert meta["total_count"] == 0


def test_enrollment_create_with_unknown_school_year_returns_referential_error(
        api, registrar_headers):
    """PRD §2.8: "a reference to an entity that does not exist is rejected with
    `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 422)".

    Design: Corner/entities/enrollment_create_with_unknown_school_year_returns_referential_error
    """
    reset_clock()
    district = create_live_district()
    student = create_student(district["id"])

    res = api.create_enrollment(
        create_enrollment_payload(student["id"], NON_EXISTENT_UUID),
        registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND, expected_status=422)


def test_enrollment_create_cross_district_reference_returns_mismatch(
        api, platform_admin_headers, registrar_headers):
    """PRD §2.8: "a body that stitches together entities from different districts is
    rejected with `ERR_DISTRICT_MISMATCH` (HTTP 422) — this covers a student enrolled
    into another district's school year".

    Design: Corner/entities/enrollment_create_cross_district_reference_returns_mismatch
    """
    reset_clock()
    district_tx = create_live_district(name="Lone Star ISD", state_code="TX")
    year_tx = create_open_school_year(district_tx["id"])
    district_nm = create_live_district(name="Desert Vista USD", state_code="NM")
    student_nm = create_student(
        district_nm["id"], student_number="S200", first_name="Dee", last_name="Tsosie",
        birth_date="2011-07-07T00:00:00Z", entry_grade_level="09")

    res = api.create_enrollment(
        create_enrollment_payload(student_nm["id"], year_tx["id"]),
        registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_DISTRICT_MISMATCH, expected_status=422)

    data, meta = validate_paginated(
        api.list_enrollments(registrar_headers, params={"student_id": student_nm["id"]}))
    assert meta["total_count"] == 0


def test_enrollment_create_initializes_parallel_dimensions(api, registrar_headers):
    """PRD §3.4: "A new enrollment starts with `lifecycle` `ACTIVE` and
    `absence_posture` `CLEAR`, with `exit_date` null, `prior_segment_days` zero,
    `absence_weight_sum` zero, and `absence_rate` 0.0; its `membership_days`,
    `fte_adm`, and `fte_count_date` are computed immediately."
    PRD §3.4: "The student's first `ACTIVE` enrollment moves the student from
    `PRE_REGISTERED` to `ENROLLED`."

    Design: Corner/state_machines/enrollment_create_initializes_parallel_dimensions
    """
    district, spec, year = setup_base()
    student = create_student(district["id"])
    assert student["status"] == "PRE_REGISTERED"

    created = validate_success(
        api.create_enrollment(
            create_enrollment_payload(student["id"], year["id"]), registrar_headers),
        201,
    )
    enrollment = validate_success(
        api.get_enrollment(created["id"], registrar_headers), 200)
    assert_enrollment(enrollment)
    assert enrollment["lifecycle"] == "ACTIVE"
    assert enrollment["absence_posture"] == "CLEAR"
    assert enrollment["exit_date"] is None
    assert enrollment["prior_segment_days"] == 0
    assert enrollment["absence_weight_sum"] == 0.0
    assert enrollment["absence_rate"] == 0.0
    # Full-year entry at 2026-08-01 spans the whole half-open window: 304 days.
    assert enrollment["membership_days"] == 304
    assert enrollment["fte_adm"] == pytest.approx(1.0, abs=1e-9)
    assert enrollment["fte_count_date"] == pytest.approx(1.0, abs=1e-9)

    assert get_student(student["id"])["status"] == "ENROLLED"


def test_enrollment_create_response_carries_computed_fields(api, registrar_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD §3.4: "its `membership_days`, `fte_adm`, and `fte_count_date` are computed
    immediately."

    Design: Corner/consistency_model/enrollment_create_response_carries_computed_fields
    """
    district, spec, year = setup_base()
    student = create_student(district["id"])

    res = api.create_enrollment(
        create_enrollment_payload(student["id"], year["id"]), registrar_headers)
    enrollment = validate_success(res, 201)
    # The create response itself carries the computed fields — no re-fetch needed.
    assert enrollment["membership_days"] == 304
    assert enrollment["fte_adm"] == pytest.approx(1.0, abs=1e-9)
    assert enrollment["fte_count_date"] == pytest.approx(1.0, abs=1e-9)
    assert enrollment["absence_posture"] == "CLEAR"

    assert get_student(student["id"])["status"] == "ENROLLED"
