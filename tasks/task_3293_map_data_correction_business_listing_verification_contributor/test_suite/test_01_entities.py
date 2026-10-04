"""Entity-surface tests: required fields, uniqueness, policy screens,
not-found, defaults, append-only shape, pagination envelope."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_contributor_grant,
    assert_region,
    create_contributor_grant_payload,
    create_contributor_payload,
    create_listing_payload,
    create_region_payload,
    make_contributor,
    make_region,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_create_region_missing_country_code_returns_invalid_request(api):
    """PRD §3.1: "A region is created by an administrator with its display
    `name`, `country_code`, `timezone`, bounding-box edges `geo_min_lat`,
    `geo_max_lat`, `geo_min_lng`, `geo_max_lng`, and optionally
    `max_active_imagery_tasks`, which defaults to 5 when omitted."
    PRD §2.6: "Only after existence come field-shape checks: required fields
    present, enum values within their declared sets, string lengths within
    bounds, a review's `rating` an integer from 1 to 5, and a grant's
    `quality_multiplier` within the inclusive range from 0.0 to 3.0, all
    surfacing `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_region_missing_required_field_returns_invalid_request
    """
    payload = create_region_payload(name="NoCountry")
    del payload["country_code"]
    resp = api.create_region(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_contributor_duplicate_email_rejected(api):
    """PRD §3.1: "Emails are unique across all contributors; a duplicate is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/contributor_duplicate_email_rejected
    """
    region = make_region(name="R")
    first = api.create_contributor(
        create_contributor_payload(
            display_name="First", email="dup@x.com", home_region_id=region["id"]
        ),
        ANON,
    )
    validate_success(first, expected_status=201)
    second = api.create_contributor(
        create_contributor_payload(
            display_name="Second", email="dup@x.com", home_region_id=region["id"]
        ),
        ANON,
    )
    validate_error(second, ApiErrorId.ERR_INVALID_REQUEST)


def test_listing_prohibited_category_rejected_at_create(api):
    """PRD §3.2: "The `category` must be one of `RESTAURANT`, `RETAIL`,
    `SERVICE`, `LODGING`, or `HEALTH`; the prohibited categories `ESCORT`,
    `WEAPONS`, and `ADULT` are rejected at creation time with
    `ERR_PROHIBITED_CATEGORY` (HTTP 422), and the same rejection applies when
    a category edit later attempts to move a listing into the prohibited set."

    Design: Corner/entities/listing_prohibited_category_rejected_at_create
    """
    region = make_region(name="R")
    resp = api.create_listing(
        create_listing_payload(region_id=region["id"], name="Bad Biz",
                               category="ESCORT"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PROHIBITED_CATEGORY)


def test_listing_geo_outside_region_rejected(api):
    """PRD §3.2: "The coordinates must fall inside the referenced region's
    bounding box — a fake-address screen that rejects out-of-region
    coordinates with `ERR_GEO_OUT_OF_REGION` (HTTP 422), applied both at
    creation and to any location or address edit."

    Design: Corner/entities/listing_geo_outside_region_rejected
    """
    region = make_region(name="R")
    resp = api.create_listing(
        create_listing_payload(region_id=region["id"], name="Far Away",
                               geo_lat=50.0, geo_lng=-87.5),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_GEO_OUT_OF_REGION)


def test_get_nonexistent_listing_returns_not_found(api):
    """PRD §2.6: "Existence checks follow: path-referenced resources are
    validated left-to-right along nested URLs — a region before a listing
    before an edit — and then body-referenced resources such as `listing_id`,
    `contributor_id`, `region_id`, `review_id`, and `supersedes_id` are
    confirmed to exist; any unknown id yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_nonexistent_listing_returns_not_found
    """
    resp = api.get_listing("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_region_default_imagery_capacity_applied(api):
    """PRD §3.1: "A region is created by an administrator with its display
    `name`, `country_code`, `timezone`, bounding-box edges `geo_min_lat`,
    `geo_max_lat`, `geo_min_lng`, `geo_max_lng`, and optionally
    `max_active_imagery_tasks`, which defaults to 5 when omitted."

    Design: Corner/entities/region_default_imagery_capacity_applied
    """
    resp = api.create_region(create_region_payload(name="DefCap"), ADMIN)
    region = validate_success(resp, expected_status=201)
    assert_region(region)
    assert region["max_active_imagery_tasks"] == 5, (
        f"default capacity must be 5, got {region['max_active_imagery_tasks']}"
    )


def test_contributor_grant_immutable_no_update_endpoint(api):
    """PRD §2.4: "Three entity types are deliberately thinner: point grants,
    review flags, and hours observations carry only `id` and `created_at` —
    both `updated_at` and `version` are absent on those records, and nothing
    on them ever needs optimistic-concurrency protection."
    PRD §3.1: "Grants begin `POSTED` and may later be `REVOKED`."

    Design: Corner/entities/contributor_grant_immutable_no_update_endpoint
    """
    region = make_region(name="R")
    contributor = make_contributor(region["id"], display_name="C", email="imm@x.com")
    resp = api.create_contributor_grant(
        create_contributor_grant_payload(
            contributor_id=contributor["id"], source_id="imm-1", base_points=7,
            note="immutability probe",
        ),
        ADMIN,
    )
    grant = validate_success(resp, expected_status=201)
    assert_contributor_grant(grant)
    assert "version" not in grant, "grant must not carry a version field"
    assert "updated_at" not in grant, "grant must not carry an updated_at field"
    assert grant["status"] == "POSTED"

    list_resp = api.list_contributor_grants(contributor["id"], ADMIN)
    grants, meta = validate_paginated(list_resp)
    assert len(grants) == 1
    assert grants[0]["id"] == grant["id"]
    assert grants[0]["status"] == "POSTED"


def test_list_pagination_defaults_applied(api):
    """PRD §2.3: "`limit` defaults to 10, must be at least 1, and may not
    exceed 100. `offset` defaults to 0. List results are always sorted by
    `created_at` ascending. The `meta` block of every list response carries
    four pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_pagination_defaults_applied
    """
    region = make_region(name="R")
    for i in (1, 2, 3):
        resp = api.create_listing(
            create_listing_payload(region_id=region["id"], name=f"P{i}",
                                   address_text=f"{i} Main St"),
            ADMIN,
        )
        validate_success(resp, expected_status=201)

    resp = api.list_listings(ADMIN)
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"
    assert len(data) == 3
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
