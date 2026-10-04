"""Delivery-year creation, envelope shape, pagination, and zone hierarchy."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_delivery_year,
    create_accreditation,
    create_delivery_year,
    create_delivery_year_payload,
    create_forecast,
    create_owner,
    create_resource,
    create_resource_payload,
    create_zone,
    approve_accreditation,
    get_success_data,
    make_resource_owner_headers,
    set_clock,
    setup_delivery_year_with_forecast,
    setup_delivery_year_with_zone,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["market_admin_headers"]


class TestDeliveryYearCreation:
    def test_create_delivery_year_returns_201_with_draft_defaults(self, api):
        """PRD §3.1: "A new delivery year begins in `DRAFT` status, with
        `reliability_requirement_mw` at 0 and `forecast_version` at 0."

        Design: Corner/entities/create_delivery_year_required_fields_and_defaults
        """
        set_clock()
        resp = api.create_delivery_year(create_delivery_year_payload(), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_delivery_year(data)
        assert data["status"] == "DRAFT"
        assert data["reliability_requirement_mw"] == 0
        assert data["forecast_version"] == 0
        fetched = validate_success(api.get_delivery_year(data["id"], ADMIN))
        assert fetched["status"] == "DRAFT"
        assert fetched["reliability_requirement_mw"] == 0
        assert fetched["forecast_version"] == 0

    def test_create_delivery_year_missing_label_rejected_and_nothing_created(self, api):
        """PRD §2.6: "Request shape — missing required fields, enum violations,
        and numeric range violations (for example `reserve_margin_pct` outside
        the open interval between 0 and 1, or `credit_score` outside the closed
        interval from 0 to 1000) yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_delivery_year_missing_label_returns_invalid_request
        """
        set_clock()
        payload = create_delivery_year_payload()
        del payload["delivery_year_label"]
        resp = api.create_delivery_year(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _, meta = validate_paginated(api.list_delivery_years(ADMIN))
        assert meta["total_count"] == 0, "A rejected create must not persist anything"

    def test_get_delivery_year_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "Path existence — every path-templated resource id is
        resolved left to right; the first id that does not resolve yields
        `ERR_NOT_FOUND`, and no later segment is examined."

        Design: Corner/entities/get_delivery_year_not_found_returns_404
        """
        set_clock()
        resp = api.get_delivery_year(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestResourceCreationShape:
    def test_resource_type_outside_enum_rejected(self, api):
        """PRD §3.2: "declaring a `resource_type` of `GEN` (thermal, hydro, or
        nuclear generation), `DR` (demand response), or `EE` (energy efficiency)"
        PRD §2.6: "Request shape — missing required fields, enum violations, and
        numeric range violations (for example `reserve_margin_pct` outside the
        open interval between 0 and 1, or `credit_score` outside the closed
        interval from 0 to 1000) yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/resource_creation_enum_violation_returns_invalid_request
        """
        dy, zone = setup_delivery_year_with_zone()
        owner = create_owner()
        headers = make_resource_owner_headers(owner["id"])
        payload = create_resource_payload(
            owner["id"], zone["id"], resource_type="SOLAR_FARM", nameplate_mw=100.0,
        )
        resp = api.create_resource(payload, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestErrorEnvelope:
    def test_rejection_uses_fixed_error_envelope(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_shape_on_business_rejection
        """
        set_clock()
        resp = api.create_delivery_year({"delivery_year_label": "2029/2030"}, ADMIN)
        assert resp.status_code == 400
        body = resp.json()
        assert body.get("response_type") == "error"
        assert body["data"]["error_id"] == "ERR_INVALID_REQUEST"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert isinstance(meta.get("api_request_timestamp"), str)


class TestPagination:
    def test_list_delivery_years_limit_offset_window(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        when omitted it defaults to 10, with a minimum accepted value of 1 and
        a maximum of 100. The `offset` parameter skips a number of items and
        defaults to 0. All list endpoints sort by `created_at` ascending. The
        `meta` object of every list response carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/list_delivery_years_pagination_envelope
        """
        set_clock()
        create_delivery_year(
            label="2027/2028",
            start="2027-06-01T00:00:00Z",
            end="2028-05-31T23:59:59Z",
        )
        create_delivery_year(
            label="2028/2029",
            start="2028-06-01T00:00:00Z",
            end="2029-05-31T23:59:59Z",
        )
        create_delivery_year()

        page1, meta1 = validate_paginated(
            api.list_delivery_years(ADMIN, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_delivery_years(ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestZoneHierarchy:
    def test_nested_lda_zone_links_back_to_parent(self, api):
        """PRD §3.1: "Each zone carries a short `zone_code` (unique within its
        delivery year) and an optional `parent_zone_id`, which enables
        locational deliverability area (LDA) nesting: a zone with a null
        `parent_zone_id` is the RTO-wide root, and any nested zone must
        reference a parent in the same delivery year."

        Design: Corner/entities/zone_parent_fk_reverse_reachable_via_list
        """
        dy, rto = setup_delivery_year_with_zone(zone_code="RTO")
        lda = create_zone(dy["id"], zone_code="LDA", import_limit_mw=25.0,
                          parent_zone_id=rto["id"])
        assert lda["parent_zone_id"] == rto["id"]
        assert lda["delivery_year_id"] == dy["id"]
        zones, meta = validate_paginated(
            api.list_zones_of_delivery_year(dy["id"], ADMIN)
        )
        assert meta["total_count"] == 2


class TestAccreditationComputedFields:
    def test_factor_and_ucap_populated_by_approval(self, api):
        """PRD §3.2: "Under the class-average variant, the factor is simply the
        `class_avg_factor`; the outage rate and sample size play no role."
        PRD §3.2: "Either way, the factor is capped at 1.0 and rounded to 4
        decimal places round half up, and the accredited `ucap_mw` is the
        nameplate megawatts times the factor, rounded to 3 decimal places round
        half up."

        Design: Corner/entities/accreditation_computed_fields_ignore_client_input
        """
        dy, zone, _ = setup_delivery_year_with_forecast()
        owner = create_owner()
        resource = create_resource(owner["id"], zone["id"])
        acc = create_accreditation(resource["id"], owner["id"], dy["id"],
                                   class_avg_factor=0.85)
        approved = approve_accreditation(acc["id"])
        assert approved["accreditation_factor"] == pytest.approx(0.85, abs=1e-9)
        assert approved["ucap_mw"] == pytest.approx(85.0, abs=1e-9)
