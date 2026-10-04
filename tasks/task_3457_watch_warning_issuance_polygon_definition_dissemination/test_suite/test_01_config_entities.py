"""Configuration-entity claims: offices, zones, product drafting schema.

Covers creation defaults, computed-field freezing, field-combination rules,
existence checks, duplicate agreements, and the product listing envelope.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_forecast_office,
    assert_product,
    create_neighbor_agreement,
    create_office,
    create_storm,
    create_watch_draft,
    list_products,
    set_clock,
    setup_office_with_zone,
    validate_created,
    validate_error,
    validate_paginated,
    validate_success,
    CLOCK_START_ISO,
)


class TestOfficeCreation:
    def test_office_create_returns_defaults_and_system_fields(self, api, platform_admin_headers):
        """PRD §3.1: "an optional `area_method` selecting the polygon area
        algorithm, defaulting to `PLANAR`. Two office fields are computed and
        never accepted as input: `performance_band`, which begins at
        `SATISFACTORY` and is re-derived from each new verification snapshot
        (§3.8), and `last_statistic_at`, the logical timestamp of the office's
        most recent snapshot, null until one is computed."
        PRD §4: "Operations that create a new resource return a `201 Created`
        status code; operations that modify an existing resource, respond to
        it, or drive a state transition return `200 OK`."

        Design: Corner/entities/office_create_returns_defaults_and_system_fields
        """
        set_clock(api, CLOCK_START_ISO)
        resp = api.create_office(
            {"office_code": "KCRN", "name": "Corner Office", "region": "WEST"},
            platform_admin_headers,
        )
        office = validate_created(resp)
        assert_forecast_office(office)
        assert office["area_method"] == "PLANAR", "area_method defaults to PLANAR"
        assert office["performance_band"] == "SATISFACTORY"
        assert office["last_statistic_at"] is None
        assert office["version"] == 1

    def test_zone_create_with_unknown_office_returns_office_not_found(self, api, platform_admin_headers):
        """PRD §2.8: "Fifth, existence: path identifiers are validated left to
        right, then body foreign keys — office, zone, storm, product, channel,
        record — with the corresponding not-found error"

        Design: Corner/entities/zone_create_with_unknown_office_returns_office_not_found
        """
        set_clock(api, CLOCK_START_ISO)
        resp = api.create_zone(
            {
                "zone_code": "ZNF1",
                "name": "Nowhere Zone",
                "office_id": NON_EXISTENT_UUID,
                "lat_min": 0.0,
                "lat_max": 0.1,
                "lon_min": 0.0,
                "lon_max": 0.1,
                "surveyed_area_sq_km": 123.21,
                "population_tier": "LOW",
                "coastal": False,
            },
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OFFICE_NOT_FOUND)

    def test_duplicate_neighbor_agreement_rejected(self, api, platform_admin_headers):
        """PRD §3.1: "The office pair is unique without regard to order: if any
        agreement already joins two offices, creating a second one for the same
        pair, in either ordering of the fields, is rejected with
        `ERR_DUPLICATE_AGREEMENT`."

        Design: Corner/errors/duplicate_neighbor_agreement_rejected
        """
        office_a = create_office(api)
        office_b = create_office(api)
        create_neighbor_agreement(
            api, office_a["id"], office_b["id"], ["SEVERE_THUNDERSTORM"],
            coordination_timeout_minutes=15,
        )
        resp = api.create_neighbor_agreement(
            {
                "office_a_id": office_b["id"],
                "office_b_id": office_a["id"],
                "hazard_types": ["HURRICANE"],
                "coordination_timeout_minutes": 30,
            },
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_AGREEMENT)
        rows, meta = validate_paginated(
            api.list_office_neighbor_agreements(office_a["id"], platform_admin_headers)
        )
        assert len(rows) == 1, "the rejected duplicate added no agreement row"


class TestProductDrafting:
    def test_product_get_roundtrips_stored_fields(self, api, verification_analyst_headers):
        """PRD §3.4: "For a zone-based product, `resolved_zone_ids` is simply a
        copy of `zone_ids`."
        PRD §3.4: "Newly created products sit in `DRAFT` with
        `verified_event_count` at zero and `verification_status` `UNVERIFIED`;
        `issued_at`, `cancelled_at`, `superseded_at`, and `expired_at` are all
        null."
        PRD §3.4: "Impact tagging runs at creation — any client-supplied tag is
        ignored — and again at issuance from the linked storm's then-current
        readings, treating readings as zero or false when no storm is linked."

        Design: Corner/entities/product_get_roundtrips_stored_fields
        """
        bundle = setup_office_with_zone(api, zone_overrides={"population_tier": "MEDIUM"})
        draft = create_watch_draft(
            api,
            bundle.office,
            bundle.headers,
            [bundle.zone["id"]],
            hazard_type="WINTER_STORM",
            effective_from="2026-09-02T00:00:00Z",
            expires_at="2026-09-02T12:00:00Z",
        )
        resp = api.get_product(draft["id"], verification_analyst_headers)
        product = validate_success(resp)
        assert_product(product)
        assert product["product_level"] == "WATCH"
        assert product["hazard_type"] == "WINTER_STORM"
        assert product["status"] == "DRAFT"
        assert product["version"] == 1
        assert product["zone_ids"] == [bundle.zone["id"]]
        assert product["resolved_zone_ids"] == [bundle.zone["id"]]
        assert product["coordination_required"] is False, (
            "own-CWA zone, non-HURRICANE hazard: the required-office set is empty"
        )
        assert product["supersedes_product_id"] is None
        assert product["issued_at"] is None
        assert product["damage_threat"] == "NONE", "no storm linked: readings read as zero/false"
        assert product["wea_360"] is False

    def test_products_list_paginates_and_filters(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        the number of items to skip and defaults to 0."
        PRD §3.4: "Products may be browsed through a filterable listing
        accepting `issuing_office_id`, `storm_event_id`,
        `supersedes_product_id`, `status`, and `hazard_type` alongside the
        standard pagination parameters."

        Design: Corner/entities/products_list_paginates_and_filters
        """
        bundle = setup_office_with_zone(api)
        for hazard, start, end in (
            ("WINTER_STORM", "2026-09-02T00:00:00Z", "2026-09-02T06:00:00Z"),
            ("WINTER_STORM", "2026-09-02T06:00:00Z", "2026-09-02T12:00:00Z"),
            ("SEVERE_THUNDERSTORM", "2026-09-02T00:00:00Z", "2026-09-02T06:00:00Z"),
        ):
            create_watch_draft(
                api, bundle.office, bundle.headers, [bundle.zone["id"]],
                hazard_type=hazard, effective_from=start, expires_at=end,
            )

        rows, meta = validate_paginated(
            api.list_products(
                bundle.headers,
                {"issuing_office_id": bundle.office["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(rows) == 2 and meta["total_count"] == 3 and meta["has_more"] is True

        rows, meta = validate_paginated(
            api.list_products(
                bundle.headers,
                {"issuing_office_id": bundle.office["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(rows) == 1 and meta["total_count"] == 3 and meta["has_more"] is False

        rows, meta = validate_paginated(
            api.list_products(
                bundle.headers,
                {"issuing_office_id": bundle.office["id"], "hazard_type": "WINTER_STORM"},
            )
        )
        assert len(rows) == 2
        rows, meta = validate_paginated(
            api.list_products(
                bundle.headers,
                {"issuing_office_id": bundle.office["id"], "hazard_type": "SEVERE_THUNDERSTORM"},
            )
        )
        assert len(rows) == 1
        rows, meta = validate_paginated(
            api.list_products(
                bundle.headers,
                {"issuing_office_id": bundle.office["id"], "status": "ISSUED"},
            )
        )
        assert len(rows) == 0, "all three products are DRAFT"

        rows, meta = validate_paginated(
            api.list_products(bundle.headers, {"issuing_office_id": bundle.office["id"]})
        )
        assert meta["limit"] == 10 and meta["offset"] == 0, "envelope defaults"
        assert len(rows) == 3

    def test_product_get_with_unknown_id_returns_not_found(self, api, verification_analyst_headers):
        """PRD §2.8: "Fifth, existence: path identifiers are validated left to
        right, then body foreign keys — office, zone, storm, product, channel,
        record — with the corresponding not-found error (`ERR_PRODUCT_NOT_FOUND`,
        `ERR_STORM_EVENT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_OFFICE_NOT_FOUND`,
        `ERR_CHANNEL_NOT_FOUND`, `ERR_COORDINATION_REQUEST_NOT_FOUND`,
        `ERR_VERIFICATION_EVENT_NOT_FOUND`, `ERR_EMERGENCY_ACTION_NOT_FOUND`,
        `ERR_DISSEMINATION_RECORD_NOT_FOUND`)."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/product_get_with_unknown_id_returns_not_found
        """
        set_clock(api, CLOCK_START_ISO)
        resp = api.get_product(NON_EXISTENT_UUID, verification_analyst_headers)
        err = validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)
        assert err["error_id"] == "ERR_PRODUCT_NOT_FOUND"
        assert err["message"], "the error envelope carries a non-empty message"

    def test_product_create_missing_expires_at_returns_invalid_request(self, api):
        """PRD §3.4: "Drafting a product requires `product_level`,
        `hazard_type`, the `issuing_office_id`, and an `expires_at`"
        PRD §2.8: "Fourth, request schema: required fields present, enum values
        valid, a polygon carrying between 3 and 12 vertices, and no forbidden
        field combinations — unknown fields are ignored — else
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/product_create_missing_expires_at_returns_invalid_request
        """
        bundle = setup_office_with_zone(api)
        resp = api.create_product(
            {
                "product_level": "WATCH",
                "hazard_type": "WINTER_STORM",
                "issuing_office_id": bundle.office["id"],
                "zone_ids": [bundle.zone["id"]],
            },
            bundle.headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert list_products(api, bundle.headers, issuing_office_id=bundle.office["id"]) == []

    def test_product_create_computed_field_input_ignored(self, api):
        """PRD §2.8: "Fourth, request schema: required fields present, enum
        values valid, a polygon carrying between 3 and 12 vertices, and no
        forbidden field combinations — unknown fields are ignored — else
        `ERR_INVALID_REQUEST`."
        PRD §3.4: "Newly created products sit in `DRAFT` with
        `verified_event_count` at zero and `verification_status` `UNVERIFIED`"
        PRD §3.4: "Impact tagging runs at creation — any client-supplied tag is
        ignored"

        Design: Corner/entities/product_create_computed_field_input_ignored
        """
        bundle = setup_office_with_zone(api, zone_overrides={"population_tier": "URBAN"})
        resp = api.create_product(
            {
                "product_level": "WATCH",
                "hazard_type": "WINTER_STORM",
                "issuing_office_id": bundle.office["id"],
                "zone_ids": [bundle.zone["id"]],
                "expires_at": "2026-09-02T12:00:00Z",
                "status": "ISSUED",
                "damage_threat": "CATASTROPHIC",
                "verified_event_count": 99,
            },
            bundle.headers,
        )
        product = validate_created(resp)
        assert product["status"] == "DRAFT", "client-supplied ISSUED ignored"
        assert product["damage_threat"] == "NONE", "client-supplied CATASTROPHIC ignored"
        assert product["wea_360"] is False
        assert product["verified_event_count"] == 0
        assert product["verification_status"] == "UNVERIFIED"

    def test_watch_create_with_polygon_returns_invalid_request(self, api):
        """PRD §3.4: "An `OUTLOOK` or `WATCH` is zone-based: it requires a
        non-empty `zone_ids` list and forbids a polygon outright."
        PRD §3.4: "A `WARNING` is storm-based: it requires a `polygon` and a
        linked `storm_event_id`."
        PRD §3.4: "A request that violates these required-and-forbidden
        combinations, or whose polygon falls outside the 3-to-12-vertex
        envelope, is rejected with `ERR_INVALID_REQUEST`"

        Design: Corner/entities/watch_create_with_polygon_returns_invalid_request
        """
        bundle = setup_office_with_zone(api)
        storm = create_storm(
            api, bundle.office["id"], bundle.headers, "SEVERE_THUNDERSTORM", max_wind_mph=60
        )
        triangle = {
            "vertices": [
                {"lat": 0.0, "lon": 0.0},
                {"lat": 0.0, "lon": 0.1},
                {"lat": 0.1, "lon": 0.1},
            ]
        }
        resp = api.create_product(
            {
                "product_level": "WATCH",
                "hazard_type": "SEVERE_THUNDERSTORM",
                "issuing_office_id": bundle.office["id"],
                "polygon": triangle,
                "expires_at": "2026-09-02T12:00:00Z",
            },
            bundle.headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        resp = api.create_product(
            {
                "product_level": "WARNING",
                "hazard_type": "SEVERE_THUNDERSTORM",
                "issuing_office_id": bundle.office["id"],
                "storm_event_id": storm["id"],
                "zone_ids": [bundle.zone["id"]],
                "expires_at": "2026-09-01T00:45:00Z",
            },
            bundle.headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert list_products(api, bundle.headers, issuing_office_id=bundle.office["id"]) == []
