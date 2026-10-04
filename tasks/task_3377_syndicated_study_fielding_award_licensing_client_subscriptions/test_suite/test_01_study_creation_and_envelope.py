"""Study creation defaults, response envelope, pagination, and registry errors (PRD §2.2-§2.5, §3.1)."""
from test_helpers import (
    CLOCK_DEFAULT,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_brand,
    assert_study,
    create_study,
    create_study_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_study_applies_defaults_and_initial_state(api, study_admin_headers):
    """PRD §3.1: "New studies are born in `DRAFT` status with `active_methodology_id`
    null and `published_at` null."
    PRD §2.4: "a `version` integer that starts at 1 and is incremented by 1 on
    every mutation of that resource."
    PRD §2.5: "The server maintains a logical clock that drives every temporal rule
    in the system — embargo evaluation, license expiry, subscription windows, and
    all recorded instants such as `submitted_at`, `activated_at`, and `published_at`."

    Design: Corner/entities/create_study_applies_defaults_and_initial_state
    """
    set_clock(CLOCK_DEFAULT)
    created = validate_success(
        api.create_study(create_study_payload(), study_admin_headers), expected_status=201
    )
    assert_study(created)
    fetched = validate_success(api.get_study(created["id"], study_admin_headers))
    assert fetched["status"] == "DRAFT", f"expected DRAFT, got {fetched['status']}"
    assert fetched["version"] == 1, f"expected version 1, got {fetched['version']}"
    assert fetched["active_methodology_id"] is None
    assert fetched["published_at"] is None
    assert fetched["created_at"].startswith("2026-09-01T00:00:00"), (
        f"created_at must be stamped from the logical clock default, got {fetched['created_at']}"
    )


def test_study_missing_required_field_returns_invalid_request(api, study_admin_headers):
    """PRD §2.8: "a missing required field, a wrong-typed field, an empty `factors`
    array on methodology create, `ends_at` not strictly later than `starts_at`,
    `target_completes` below 1, or `min_sample_per_brand` below 1 yields
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "A study program begins when a `StudyAdmin` creates a study with a
    unique `code` ... the `significance_alpha` used to document the two-tailed
    significance level, and the `embargo_lift_at` instant before which results may
    not be published."

    Design: Corner/entities/study_missing_required_field_returns_invalid_request
    """
    set_clock(CLOCK_DEFAULT)
    payload = create_study_payload()
    del payload["embargo_lift_at"]
    resp = api.create_study(payload, study_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    # No study is created: listing stays empty.
    rows, meta = validate_paginated(api.list_studies(study_admin_headers))
    assert meta["total_count"] == 0, f"expected no studies, got {meta['total_count']}"


def test_system_fields_input_ignored_on_brand_create(api, study_admin_headers):
    """PRD §2.4: "Every persisted resource carries an `id` that is a server-minted
    UUID with no type prefix."
    PRD §2.4: "a `version` integer that starts at 1 and is incremented by 1 on
    every mutation of that resource."
    PRD §2.5: "Before any administrative call sets it, the logical clock reads
    exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time."

    Design: Corner/entities/system_fields_input_ignored_on_brand_create
    """
    set_clock(CLOCK_DEFAULT)
    payload = {
        "name": "BrandA",
        "industry_code": "AUTO",
        "id": "00000000-0000-0000-0000-000000000000",
        "version": 99,
        "created_at": "1999-01-01T00:00:00Z",
    }
    created = validate_success(api.create_brand(payload, study_admin_headers), expected_status=201)
    assert_brand(created)
    assert created["id"] != "00000000-0000-0000-0000-000000000000", (
        "client-supplied id must be ignored; the server mints its own"
    )
    assert created["version"] == 1, f"client-supplied version 99 must be ignored, got {created['version']}"
    assert created["created_at"].startswith("2026-09-01T00:00:00"), (
        f"client-supplied created_at must be ignored, got {created['created_at']}"
    )


def test_get_nonexistent_study_returns_not_found(api, study_admin_headers):
    """PRD §2.8: "Existence — every identifier resolves. Path identifiers are
    validated left to right along the URL, then body foreign keys ... failure
    yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_nonexistent_study_returns_not_found
    """
    set_clock(CLOCK_DEFAULT)
    resp = api.get_study(NON_EXISTENT_UUID, study_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_studies_pagination_envelope(api, study_admin_headers):
    """PRD §2.3: "All list endpoints accept the optional query parameters `limit`
    and `offset`. The `limit` parameter defaults to 10, with a minimum accepted
    value of 1 and a maximum accepted value of 100; the `offset` parameter
    defaults to 0."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the response `meta` object, alongside the
    standard request metadata."

    Design: Corner/endpoints/list_studies_pagination_envelope
    """
    set_clock(CLOCK_DEFAULT)
    create_study(code="VDS-2025", name="2025 Vehicle Dependability", cycle_year=2025,
                 min_sample_per_brand=1, embargo_lift_at="2025-10-15T00:00:00Z",
                 set_default_clock=False)
    create_study(code="VDS-2026", min_sample_per_brand=1, set_default_clock=False)

    page1, meta1 = validate_paginated(api.list_studies(study_admin_headers, params={"limit": 1}))
    assert len(page1) == 1, f"page 1 must carry exactly 1 row, got {len(page1)}"
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_studies(study_admin_headers, params={"limit": 1, "offset": 1})
    )
    assert len(page2) == 1, f"page 2 must carry exactly 1 row, got {len(page2)}"
    assert meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"], "page 2 must return the other study"


def test_error_envelope_shape_on_not_found(api, study_admin_headers):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/error_envelope_shape_on_not_found
    """
    set_clock(CLOCK_DEFAULT)
    resp = api.get_study(NON_EXISTENT_UUID, study_admin_headers)
    body = resp.json()
    assert body.get("response_type") == "error", f"response_type must be 'error', got {body.get('response_type')}"
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"], (
        "error data.message must be a non-empty string"
    )
    assert body.get("meta", {}).get("api_request_id"), "meta.api_request_id must be present"


def test_duplicate_study_code_returns_409(api, study_admin_headers):
    """PRD §3.1: "Creating a study whose `code` collides with an existing study is
    rejected with `ERR_DUPLICATE_STUDY_CODE`."

    Design: Corner/errors/duplicate_study_code_returns_409
    """
    first = create_study(code="VDS-2026", min_sample_per_brand=1)
    resp = api.create_study(
        create_study_payload(
            code="VDS-2026", name="Duplicate", min_sample_per_brand=5,
            embargo_lift_at="2026-11-01T00:00:00Z",
        ),
        study_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_STUDY_CODE)
    # The original study is untouched.
    fetched = validate_success(api.get_study(first["id"], study_admin_headers))
    assert fetched["name"] == "2026 Vehicle Dependability"
    assert fetched["status"] == "DRAFT"
