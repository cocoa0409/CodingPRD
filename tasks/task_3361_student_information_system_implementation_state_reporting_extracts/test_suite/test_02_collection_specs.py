"""State collection spec lifecycle: publish cascade, RBAC, and the extract gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    close_year_for_reporting,
    create_live_district,
    create_open_school_year,
    create_published_spec,
    create_spec,
    create_spec_payload,
    create_student_with_enrollment,
    get_spec,
    get_year_version,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_spec_publish_auto_retires_prior_published_spec(api, platform_admin_headers):
    """PRD §3.2: "Publication is exclusive: at most one spec per `state_code` may be
    `PUBLISHED` at a time, so publishing a spec automatically retires any other
    `PUBLISHED` spec for the same state, and the newly published spec's `version`
    increments by one."

    Design: Corner/state_machines/spec_publish_auto_retires_prior_published_spec
    """
    reset_clock()
    spec1 = create_published_spec()
    spec2 = validate_success(
        api.create_collection_spec(
            create_spec_payload(
                funding_method="COUNT_DATE",
                attendance_code_map={
                    "U": {"state_code": "S_ABS_U", "absence_weight": 1.0,
                          "is_excused": False}},
                discipline_code_map={
                    "FIGHT": {"state_offense_code": "S_OFF_29", "severity_base": 25}},
                program_code_map={
                    "EL": {"state_program_code": "S_PRG_EL", "weight_factor": 1.2}},
                submission_window_closes_at="2027-08-15T00:00:00Z",
            ),
            platform_admin_headers),
        201,
    )
    assert spec2["status"] == "DRAFT"

    published2 = validate_success(
        api.publish_collection_spec(spec2["id"], platform_admin_headers), 200)
    assert published2["status"] == "PUBLISHED"

    spec1_after = get_spec(spec1["id"])
    assert spec1_after["status"] == "RETIRED", \
        "the prior PUBLISHED spec must be auto-retired by the publish cascade"

    data, meta = validate_paginated(
        api.list_collection_specs(
            platform_admin_headers, params={"state_code": "TX", "status": "PUBLISHED"}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in data] == [spec2["id"]]


def test_registrar_cannot_publish_spec_returns_forbidden(
        api, platform_admin_headers, registrar_headers):
    """PRD §2.1: "Write surfaces are disjoint across the four operator roles. A
    `PlatformAdmin` — the vendor implementation and operations team — owns districts,
    state collection specs, and the logical clock."
    PRD §2.1: "A well-identified caller whose role is not permitted for the target
    endpoint is rejected with `ERR_FORBIDDEN`."

    Design: Corner/validations/registrar_cannot_publish_spec_returns_forbidden
    """
    reset_clock()
    spec = create_spec()
    res = api.publish_collection_spec(spec["id"], registrar_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    spec_after = get_spec(spec["id"])
    assert spec_after["status"] == "DRAFT", "a forbidden publish must not change state"


def test_extract_create_with_draft_spec_is_rejected(
        api, state_reporter_headers):
    """PRD §3.7: "The school year must be `CLOSED_FOR_REPORTING`; the spec must be
    `PUBLISHED` (else `ERR_SPEC_NOT_PUBLISHED`) and its `state_code` must match the
    state of the year's district (else `ERR_DISTRICT_MISMATCH`)."

    Design: Difficulty/cross_entity_state_dependency/extract_create_requires_published_spec
    """
    reset_clock()
    district = create_live_district()
    spec = create_spec()  # left DRAFT
    year = create_open_school_year(district["id"])
    create_student_with_enrollment(district["id"], year["id"])
    closed_year = close_year_for_reporting(year["id"])

    res = api.create_reporting_extract(
        {
            "school_year_id": year["id"],
            "collection_spec_id": spec["id"],
            "expected_school_year_version": closed_year["version"],
        },
        state_reporter_headers,
    )
    validate_error(res, ApiErrorId.ERR_SPEC_NOT_PUBLISHED, expected_status=409)

    data, meta = validate_paginated(
        api.list_reporting_extracts(
            state_reporter_headers, params={"school_year_id": year["id"]}))
    assert meta["total_count"] == 0, "no extract may be persisted against a DRAFT spec"


def test_extract_create_succeeds_after_spec_publish(
        api, state_reporter_headers, platform_admin_headers):
    """PRD §3.7: "The school year must be `CLOSED_FOR_REPORTING`; the spec must be
    `PUBLISHED` (else `ERR_SPEC_NOT_PUBLISHED`) and its `state_code` must match the
    state of the year's district (else `ERR_DISTRICT_MISMATCH`)."

    Design: Difficulty/cross_entity_state_dependency/extract_create_requires_published_spec
    """
    reset_clock()
    district = create_live_district()
    spec = create_spec()  # left DRAFT
    year = create_open_school_year(district["id"])
    create_student_with_enrollment(district["id"], year["id"])
    close_year_for_reporting(year["id"])

    blocked = api.create_reporting_extract(
        {
            "school_year_id": year["id"],
            "collection_spec_id": spec["id"],
            "expected_school_year_version": get_year_version(year["id"]),
        },
        state_reporter_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_SPEC_NOT_PUBLISHED, expected_status=409)

    validate_success(api.publish_collection_spec(spec["id"], platform_admin_headers), 200)
    retry = api.create_reporting_extract(
        {
            "school_year_id": year["id"],
            "collection_spec_id": spec["id"],
            "expected_school_year_version": get_year_version(year["id"]),
        },
        state_reporter_headers,
    )
    extract = validate_success(retry, 201)
    assert extract["status"] == "DRAFT"
    assert extract["collection_spec_id"] == spec["id"]
