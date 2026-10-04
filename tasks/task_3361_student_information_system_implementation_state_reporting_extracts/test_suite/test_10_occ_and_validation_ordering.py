"""Optimistic concurrency control on the two version-guarded creates, and the
referential-before-temporal ordering of the validation pipeline."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    close_year_for_reporting,
    create_enrollment_payload,
    create_extract,
    create_live_district,
    create_open_school_year,
    create_published_spec,
    create_rollover_run,
    create_student,
    create_student_with_enrollment,
    create_target_year_opened,
    get_district_version,
    get_year_version,
    reset_clock,
    setup_closed_year_with_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_occ_extract_create_with_stale_year_version_returns_412(
        api, state_reporter_headers):
    """PRD §2.9: "Creating a reporting extract requires the request to carry
    `expected_school_year_version`, set to the `version` of the target school year as
    the client last observed it. Extract creation itself supersedes prior extracts
    and increments the school year's `version`, so a request whose
    `expected_school_year_version` no longer matches the year entity's current
    `version` is stale — its view of the year's extract lineage is outdated — and is
    rejected with `ERR_STALE_SCHOOL_YEAR_VERSION` (HTTP 412)."

    Design: Corner/errors/occ_extract_create_with_stale_year_version_returns_412
    """
    bundle = setup_closed_year_with_enrollment()
    year_id = bundle["year"]["id"]
    spec_id = bundle["spec"]["id"]
    stale_version = bundle["year_version"]
    ex1 = create_extract(year_id, spec_id, stale_version)

    # The first create bumped the year version, so replaying the captured version is
    # stale — two strictly sequential requests, no parallelism.
    res = api.create_reporting_extract(
        {
            "school_year_id": year_id,
            "collection_spec_id": spec_id,
            "expected_school_year_version": stale_version,
        },
        state_reporter_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_SCHOOL_YEAR_VERSION, expected_status=412)

    data, meta = validate_paginated(
        api.list_reporting_extracts(
            state_reporter_headers, params={"school_year_id": year_id}))
    assert meta["total_count"] == 1, "the stale create must not supersede anything"
    ex1_after = validate_success(
        api.get_reporting_extract(ex1["id"], state_reporter_headers), 200)
    assert ex1_after["status"] == "DRAFT"


def test_occ_rollover_create_with_stale_district_version_returns_412(
        api, district_admin_headers):
    """PRD §2.9: "Creating a rollover run requires the request to carry
    `expected_district_version`, set to the `version` of the district as the client
    last observed it. Run creation supersedes pending runs and increments the
    district's `version`, so a request whose `expected_district_version` no longer
    matches the district entity's current `version` is stale and is rejected with
    `ERR_STALE_DISTRICT_VERSION` (HTTP 412)."
    PRD §3.9: "Creating a run supersedes any still-`PENDING` run of the same district
    and increments the district's `version` by one; the new run begins `PENDING`."

    Design: Corner/errors/occ_rollover_create_with_stale_district_version_returns_412
    """
    reset_clock()
    district = create_live_district()
    stale_version = district["version"]  # observed at activation
    create_published_spec()
    source_year = create_open_school_year(district["id"])
    target_year = create_target_year_opened(district["id"])
    close_year_for_reporting(source_year["id"])

    rr1 = create_rollover_run(
        district["id"], source_year["id"], target_year["id"], stale_version)

    # The first create bumped the district version; replaying the activation-time
    # version is stale.
    res = api.create_rollover_run(
        {
            "district_id": district["id"],
            "source_school_year_id": source_year["id"],
            "target_school_year_id": target_year["id"],
            "expected_district_version": stale_version,
        },
        district_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_DISTRICT_VERSION, expected_status=412)

    # Retrying with the freshly observed version succeeds and supersedes rr1.
    rr2 = create_rollover_run(
        district["id"], source_year["id"], target_year["id"],
        get_district_version(district["id"]))
    assert rr2["status"] == "PENDING"
    rr1_after = validate_success(
        api.get_rollover_run(rr1["id"], district_admin_headers), 200)
    assert rr1_after["status"] == "SUPERSEDED"


def test_enrollment_referential_error_beats_temporal_error(api, registrar_headers):
    """PRD §2.7: "Every request passes through a fixed sequence of validation stages,
    and the first failing stage determines the error returned — earlier stages mask
    later ones."
    PRD §2.8: "a reference to an entity that does not exist is rejected with
    `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/enrollment_referential_error_beats_temporal_error
    """
    reset_clock()
    district = create_live_district()
    create_published_spec()
    year = create_open_school_year(district["id"])

    # Non-existent student_id (stage 6) AND an entry_date outside the year
    # (stage 7): the referential error fires first.
    res = api.create_enrollment(
        create_enrollment_payload(
            NON_EXISTENT_UUID, year["id"], entry_date="2025-01-01T00:00:00Z"),
        registrar_headers,
    )
    validate_error(res, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND, expected_status=422)


def test_enrollment_referential_error_is_not_temporal_error(api, registrar_headers):
    """PRD §2.7: "Every request passes through a fixed sequence of validation stages,
    and the first failing stage determines the error returned — earlier stages mask
    later ones."
    PRD §3.4: "the `entry_date` must fall inside the year window, on or after
    `start_date` and strictly before `end_date` (else `ERR_ENTRY_OUTSIDE_YEAR`)".

    Design: Difficulty/priority_pair_validation_conflict/enrollment_referential_error_beats_temporal_error
    """
    reset_clock()
    district = create_live_district()
    create_published_spec()
    year = create_open_school_year(district["id"])

    res = api.create_enrollment(
        create_enrollment_payload(
            NON_EXISTENT_UUID, year["id"], entry_date="2025-01-01T00:00:00Z"),
        registrar_headers,
    )
    assert res.status_code == 422
    error_id = res.json()["data"]["error_id"]
    assert error_id == ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND.value
    assert error_id != ApiErrorId.ERR_ENTRY_OUTSIDE_YEAR.value, \
        "the stage-6 referential error masks the stage-7 temporal error"

    data, meta = validate_paginated(
        api.list_enrollments(registrar_headers, params={"school_year_id": year["id"]}))
    assert meta["total_count"] == 0, "no enrollment may be persisted"
