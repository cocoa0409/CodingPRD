"""Registration, configuration, and response-envelope tests.

Covers manufacturer registration defaults, standard-edition status derivation,
the half-open edition-window overlap rules, unknown-id lookups, invalid enum
rejection, and the fixed error envelope shape.
"""

from test_helpers import (
    ApiErrorId,
    BASE_CLOCK_ISO,
    assert_manufacturer,
    assert_standard,
    canonical_instant,
    create_standard,
    manufacturer_payload,
    protocol_spec,
    set_clock,
    standard_payload,
    validate_error,
    validate_success,
)

# A well-formed UUID that no factory is registered under.
NONEXISTENT_FACTORY_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_manufacturer_create_returns_declared_fields_and_active_status(api, admin_headers):
    """PRD §3.1: "A manufacturer is registered in `ACTIVE` status with a null
    `suspension_reason`."
    PRD §2.5: "At startup the logical clock stands at exactly
    2026-09-01T00:00:00Z, and it never falls back to the host's wall clock."

    Design: Corner/entities/manufacturer_create_returns_declared_fields_and_active_status
    """
    set_clock(api, BASE_CLOCK_ISO)
    response = api.create_manufacturer(
        manufacturer_payload(
            legal_name="Acme Devices LLC",
            home_jurisdiction_code="US-OSHA",
            annual_revenue_tier="SMALL",
        ),
        admin_headers,
    )
    data = validate_success(response, 201)
    assert_manufacturer(data)
    assert data["legal_name"] == "Acme Devices LLC"
    assert data["home_jurisdiction_code"] == "US-OSHA"
    assert data["annual_revenue_tier"] == "SMALL"
    assert data["status"] == "ACTIVE"
    assert data["suspension_reason"] is None
    assert data["version"] == 1
    assert canonical_instant(data["created_at"]) == canonical_instant(BASE_CLOCK_ISO), (
        f"created_at must come from the logical clock, got {data['created_at']!r}"
    )
    meta = response.json()["meta"]
    assert meta.get("api_request_id"), "meta.api_request_id must be present"
    assert meta.get("api_request_timestamp"), "meta.api_request_timestamp must be present"


def test_standard_status_computed_from_effectiveness_window(api, admin_headers):
    """PRD §2.6: "A standard's `status` is derived from the logical clock against
    this window: before `effective_from` the edition is `UPCOMING`; at or after
    `effective_from` and before `effective_to` it is `ACTIVE`; at or after
    `effective_to` it is `RETIRED`."

    Design: Corner/entities/standard_status_computed_from_effectiveness_window
    """
    set_clock(api, BASE_CLOCK_ISO)
    # Window already open (2026-01-01) and open-ended -> ACTIVE.
    active = create_standard(api)
    assert_standard(active)
    assert active["status"] == "ACTIVE"
    # Window opens in the future -> UPCOMING.
    future = create_standard(
        api,
        standard_code="UL-3103",
        edition_label="Ed. 1",
        effective_from="2027-01-01T00:00:00Z",
        construction_requirements=["enclosure"],
        test_protocols=[protocol_spec("P-1", pass_threshold=10)],
    )
    assert_standard(future)
    assert future["status"] == "UPCOMING"


def test_standard_edition_window_adjacency_allowed_overlap_rejected(api, admin_headers):
    """PRD §2.6: "Because both comparisons are strict, adjacency is legal — one
    edition's `effective_to` may equal another edition's `effective_from`, and
    two such touching windows do not overlap."
    PRD §2.6: "if the new edition's `effective_from` falls before the existing
    edition's end (treating an open-ended edition as never ending) and the
    existing edition's `effective_from` falls before the new edition's end
    (likewise), the registration is rejected with `ERR_STANDARD_EDITION_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/standard_edition_half_open_window_adjacency
    """
    set_clock(api, BASE_CLOCK_ISO)
    create_standard(
        api,
        standard_code="UL-60335",
        edition_label="Ed. 5",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
        construction_requirements=["enclosure"],
        test_protocols=[protocol_spec("P-1", pass_threshold=10)],
    )
    # Adjacency: the successor starts exactly when Ed. 5 ends -> legal.
    successor = create_standard(
        api,
        standard_code="UL-60335",
        edition_label="Ed. 6",
        effective_from="2027-01-01T00:00:00Z",
        construction_requirements=["enclosure"],
        test_protocols=[protocol_spec("P-1", pass_threshold=10)],
    )
    assert_standard(successor)
    # One day earlier overlaps Ed. 5's window -> rejected.
    overlap = api.create_standard(
        standard_payload(
            standard_code="UL-60335",
            edition_label="Ed. 5.1",
            effective_from="2026-12-31T00:00:00Z",
            construction_requirements=["enclosure"],
            test_protocols=[protocol_spec("P-1", pass_threshold=10)],
        ),
        admin_headers,
    )
    validate_error(overlap, ApiErrorId.ERR_STANDARD_EDITION_OVERLAP)


def test_standard_edition_overlap_scoped_to_same_category_and_code(api, admin_headers):
    """PRD §2.6: "Editions of the same standard share the pair of
    `category_code` and `standard_code`, and their effectiveness windows must
    never overlap."

    Design: Difficulty/resource_temporal_overlap/standard_edition_half_open_window_adjacency
    """
    set_clock(api, BASE_CLOCK_ISO)
    create_standard(
        api,
        standard_code="UL-60335",
        edition_label="Ed. 5",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
        construction_requirements=["enclosure"],
        test_protocols=[protocol_spec("P-1", pass_threshold=10)],
    )
    # A different standard_code in the same category may overlap freely.
    other = create_standard(
        api,
        standard_code="UL-9999",
        edition_label="Ed. 1",
        effective_from="2026-06-01T00:00:00Z",
        construction_requirements=["enclosure"],
        test_protocols=[protocol_spec("P-1", pass_threshold=10)],
    )
    assert_standard(other)
    assert other["standard_code"] == "UL-9999"


def test_factory_get_for_nonexistent_id_returns_not_found(api, officer_headers):
    """PRD §2.8: "Path references are validated left to right, and the first
    identifier that does not correspond to an existing resource yields
    `ERR_NOT_FOUND` (HTTP 404) for that resource before later segments are
    examined."

    Design: Corner/entities/factory_get_for_nonexistent_id_returns_not_found
    """
    set_clock(api, BASE_CLOCK_ISO)
    response = api.get_factory(NONEXISTENT_FACTORY_ID, officer_headers)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_manufacturer_invalid_revenue_tier_enum_returns_invalid_request(api, admin_headers):
    """PRD §3.1: "Registration records the `legal_name`, the
    `home_jurisdiction_code` where the manufacturer is domiciled, and an
    `annual_revenue_tier` of `MICRO`, `SMALL`, `STANDARD`, or `ENTERPRISE`"
    PRD §2.8: "Separately from this pipeline, a request that is missing a
    required field, carries a value of the wrong type, or supplies an invalid
    enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/manufacturer_invalid_revenue_tier_enum_returns_invalid_request
    """
    set_clock(api, BASE_CLOCK_ISO)
    response = api.create_manufacturer(
        manufacturer_payload(legal_name="Bad Tier Co", annual_revenue_tier="HUGE"),
        admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_error_envelope_shape_on_validation_failure(api, admin_headers):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/errors/error_envelope_shape_on_validation_failure
    """
    set_clock(api, BASE_CLOCK_ISO)
    response = api.create_manufacturer(
        manufacturer_payload(legal_name="Bad Tier Co", annual_revenue_tier="HUGE"),
        admin_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    body = response.json()
    assert body["response_type"] == "error"
    assert error["error_id"] == "ERR_INVALID_REQUEST"
    assert isinstance(error["message"], str) and error["message"].strip(), (
        "data.message must be a non-empty string"
    )
    meta = body["meta"]
    assert meta.get("api_request_id"), "meta.api_request_id must be present"
    assert meta.get("api_request_timestamp"), "meta.api_request_timestamp must be present"
