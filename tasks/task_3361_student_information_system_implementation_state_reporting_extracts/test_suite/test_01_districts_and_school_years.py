"""District creation defaults and school-year window rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_district,
    create_district_payload,
    create_live_district,
    create_school_year_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_district_create_returns_defaults_and_common_fields(api, platform_admin_headers):
    """PRD §3.1: "Every district begins life in `IMPLEMENTATION`, and its `status`
    only ever moves among `IMPLEMENTATION`, `LIVE`, and `SUSPENDED`."
    PRD §2.5: "Every primary resource carries a standard set of system-managed
    fields: `id` (string): a unique, server-minted identifier formatted as a UUID,
    with no type prefix."

    Design: Corner/entities/district_create_returns_defaults_and_common_fields
    """
    reset_clock()
    res = api.create_district(
        create_district_payload(name="Lone Star ISD", state_code="TX"),
        platform_admin_headers,
    )
    assert res.status_code == 201, f"expected 201, got {res.status_code}: {res.text}"
    body = res.json()
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id"), "meta.api_request_id must be present"

    district = validate_success(res, 201)
    assert_district(district)
    assert district["status"] == "IMPLEMENTATION"
    assert isinstance(district["version"], int), "version is a system-managed integer"
    assert is_valid_uuid(district["id"])
    assert is_iso8601_timestamp(district["created_at"])
    assert is_iso8601_timestamp(district["updated_at"])


def test_school_year_create_missing_instructional_days_returns_invalid_request(
        api, platform_admin_headers, district_admin_headers):
    """PRD §2.7: "Required body fields are present, enum values fall inside their
    declared sets, and numeric ranges are sane; otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.2: "Creating a school year requires the owning `district_id`, a display
    `label` such as "2026-2027", the window endpoints `start_date` and `end_date`,
    the `instructional_days` denominator used for funding proration (a positive
    integer, conventionally 180), and the `count_date` snapshot instant used by
    count-date funding regimes."

    Design: Corner/entities/school_year_create_missing_instructional_days_returns_invalid_request
    """
    reset_clock()
    res_create = api.create_district(
        create_district_payload(), platform_admin_headers)
    district = validate_success(res_create, 201)

    payload = create_school_year_payload(district["id"])
    del payload["instructional_days"]
    res = api.create_school_year(payload, district_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    data, meta = validate_paginated(
        api.list_school_years(district_admin_headers, params={"district_id": district["id"]}))
    assert meta["total_count"] == 0, f"no year may be persisted, got {meta['total_count']}"


def test_school_year_end_before_start_returns_date_range(
        api, platform_admin_headers, district_admin_headers):
    """PRD §3.2: "The window must end after it begins — otherwise
    `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/school_year_end_before_start_returns_date_range
    """
    reset_clock()
    district = validate_success(
        api.create_district(create_district_payload(), platform_admin_headers), 201)

    payload = create_school_year_payload(
        district["id"],
        label="bad",
        start_date="2027-06-01T00:00:00Z",
        end_date="2026-08-01T00:00:00Z",
    )
    res = api.create_school_year(payload, district_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=422)

    data, meta = validate_paginated(
        api.list_school_years(district_admin_headers, params={"district_id": district["id"]}))
    assert meta["total_count"] == 0


def test_school_year_adjacent_window_is_allowed(
        api, platform_admin_headers, district_admin_headers):
    """PRD §2.10: "First, school-year windows within one district may *abut* — one
    year's `end_date` equal to the next year's `start_date` — but may never overlap;
    any true overlap is rejected with `ERR_YEAR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/school_year_half_open_adjacency_allowed
    """
    reset_clock()
    district = create_live_district()
    api.create_school_year(
        create_school_year_payload(district["id"]), district_admin_headers)

    adjacent = api.create_school_year(
        create_school_year_payload(
            district["id"],
            label="2027-2028",
            start_date="2027-06-01T00:00:00Z",
            end_date="2028-06-01T00:00:00Z",
            count_date="2027-10-01T00:00:00Z",
        ),
        district_admin_headers,
    )
    year_adj = validate_success(adjacent, 201)
    assert year_adj["start_date"] == "2027-06-01T00:00:00Z"

    data, meta = validate_paginated(
        api.list_school_years(district_admin_headers, params={"district_id": district["id"]}))
    assert meta["total_count"] == 2, \
        f"both the base year and its adjacent successor must exist, got {meta['total_count']}"


def test_school_year_true_overlap_is_rejected(
        api, platform_admin_headers, district_admin_headers):
    """PRD §2.10: "First, school-year windows within one district may *abut* — one
    year's `end_date` equal to the next year's `start_date` — but may never overlap;
    any true overlap is rejected with `ERR_YEAR_WINDOW_OVERLAP`."
    PRD §3.2: "a year whose `start_date` equals the predecessor's `end_date` tiles
    cleanly, while any genuine overlap is rejected with `ERR_YEAR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/school_year_half_open_adjacency_allowed
    """
    reset_clock()
    district = create_live_district()
    api.create_school_year(
        create_school_year_payload(district["id"]), district_admin_headers)

    overlapping = api.create_school_year(
        create_school_year_payload(
            district["id"],
            label="2027-2028-early",
            start_date="2027-05-31T00:00:00Z",
            end_date="2028-05-31T00:00:00Z",
            count_date="2027-10-01T00:00:00Z",
        ),
        district_admin_headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_YEAR_WINDOW_OVERLAP, expected_status=409)

    data, meta = validate_paginated(
        api.list_school_years(district_admin_headers, params={"district_id": district["id"]}))
    assert meta["total_count"] == 1, "the overlapping year must not be persisted"
