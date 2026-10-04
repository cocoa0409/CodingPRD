"""Master data and listing coverage (design-index queue B, section entities)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    setup_facility, setup_cxl_dough_type, setup_cafe, set_clock,
    create_order, get_cafe,
    make_cafe_manager_headers,
)


class TestCafeValidation:
    def test_cafe_create_missing_credit_limit_returns_validation(self, api, planner_headers):
        """PRD §3.1: "A cafe is registered with a `name`, the `facility_id` of the
        home facility that supplies it, an `ownership_type` of `COMPANY` or
        `FRANCHISE` — a classification that drives both the transfer-pricing markup
        and the overhead burden share at settlement — and a `credit_limit_cents`
        ceiling on its outstanding receivable balance, which must be positive."
        PRD §2.7: "A malformed or out-of-range input field — a bad enum value, a
        non-positive integer where a positive one is required, an ill-formed date —
        is rejected with `ERR_VALIDATION`."

        Design: Corner/entities/cafe_create_missing_credit_limit_returns_validation
        """
        facility = setup_facility()
        resp = api.create_cafe(
            {"name": "C1", "facility_id": facility["id"], "ownership_type": "FRANCHISE"},
            planner_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_cafe_create_invalid_ownership_enum_returns_validation(self, api, planner_headers):
        """PRD §3.1: "an `ownership_type` of `COMPANY` or `FRANCHISE` — a
        classification that drives both the transfer-pricing markup and the overhead
        burden share at settlement".
        PRD §2.7: "A malformed or out-of-range input field — a bad enum value, a
        non-positive integer where a positive one is required, an ill-formed date —
        is rejected with `ERR_VALIDATION`."

        Design: Corner/entities/cafe_create_invalid_ownership_enum_returns_validation
        """
        facility = setup_facility()
        resp = api.create_cafe(
            {"name": "C1", "facility_id": facility["id"], "ownership_type": "PARTNER",
             "credit_limit_cents": 90000},
            planner_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestCafeLookup:
    def test_cafe_get_not_found(self, api, planner_headers):
        """PRD §2.6: "The request is rejected immediately with `ERR_NOT_FOUND` at
        the first path identifier that does not correspond to an existing resource,
        before any later identifier or any business rule is evaluated."

        Design: Corner/entities/cafe_get_not_found
        """
        resp = api.get_cafe(NON_EXISTENT_UUID, planner_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestDoughTypeCreation:
    def test_dough_type_creation_applies_defaults(self, api, planner_headers):
        """PRD §2.4: "`version` (integer): a system-managed integer that increments
        by exactly 1 on every mutation of the resource and underpins the optimistic
        concurrency rules in §2.9."
        PRD §3.1: "Each `DoughType` carries a globally unique `code` (for example,
        `WHITE-CONV`), a `category` of either `CONVENTIONAL` or `ARTISAN`, a
        `shelf_life_hours` value (a positive integer counting hours from the start
        of the production date until the dough expires), an `order_cutoff_local` in
        `HH:MM` form (between 00:00 and 23:59) marking the cafe-local instant on the
        day before the production date at and after which orders and amendments are
        refused, a `substitution_allowed` flag encoding the no-substitution rule,
        and a `flat_transfer_price` — the facility's base per-unit transfer price in
        dollars before any ownership markup, and also the per-unit basis on which
        donation credits are priced."

        Design: Corner/entities/dough_type_creation_applies_defaults
        """
        resp = api.create_dough_type(
            {"code": "CXL", "category": "CONVENTIONAL", "shelf_life_hours": 36,
             "order_cutoff_local": "13:00", "substitution_allowed": False,
             "flat_transfer_price": 4.00},
            planner_headers)
        data = validate_success(resp, 201)
        assert resp.json()["response_type"] == "object"
        assert data["version"] == 1
        assert "status" not in data, "DoughType has no lifecycle state"


class TestOrderListing:
    def test_order_list_pagination_envelope(self, api, planner_headers):
        """PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "List endpoints accept two query parameters. The `limit` parameter
        sets the maximum number of items returned; it defaults to 10, with a minimum
        of 1 and a maximum of 100. The `offset` parameter sets the number of items
        to skip and defaults to 0."

        Design: Corner/entities/order_list_pagination_envelope
        """
        facility = setup_facility()
        cxl = setup_cxl_dough_type()
        cafe = setup_cafe(facility["id"], "C1", "FRANCHISE", 90000)
        set_clock("2026-09-09T10:00:00Z")
        create_order(cafe, cxl, "2026-09-10", 10)
        create_order(cafe, cxl, "2026-09-11", 20)

        resp = api.list_cafe_orders(planner_headers,
                                    params={"cafe_id": cafe["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert len(data) == 1
