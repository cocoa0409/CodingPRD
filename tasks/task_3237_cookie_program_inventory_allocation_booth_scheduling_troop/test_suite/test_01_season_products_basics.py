"""Entity lifecycle and envelope coverage: creation, defaults, computed fields,
missing fields, not-found, and pagination."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_cookie_product,
    assert_cookie_season,
    create_season,
    create_season_payload,
    get_season,
    make_council_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSeasonCreation:
    def test_season_create_success_and_defaults(self, api):
        """PRD §3.1: "The season is born in `DRAFT` status with its `version`
        at 1." PRD §2.5: "`purchased_units` is the sum of `quantity` over the
        season's baker purchase orders whose status is `ORDERED`,
        `PARTIALLY_DELIVERED`, or `DELIVERED`" — none exist yet, so zero.

        Design: Corner/entities/season_create_success_and_defaults
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        assert_cookie_season(season)
        read = get_season(season["id"], admin=admin)
        assert read["status"] == "DRAFT"
        assert read["version"] == 1
        assert read["initial_commit_units"] == 0
        assert read["purchased_units"] == 0

    def test_season_create_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.4: "Requests with a missing required field, a value of the
        wrong type, or an unknown enum value are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/season_create_missing_required_field_returns_invalid_request
        """
        admin = make_council_admin_headers()
        payload = create_season_payload()
        payload.pop("code")
        resp = api.create_season(payload, admin)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_season_get_not_found_returns_404(self, api):
        """PRD §2.4: "The first identifier that fails to resolve — whether a
        season, order, line, site, purchase order, transfer, location, slot,
        request, digital order, agreement, recall, account, product, or troop —
        yields `ERR_NOT_FOUND` (HTTP 404) before any other check runs."

        Design: Corner/entities/season_get_not_found_returns_404
        """
        admin = make_council_admin_headers()
        resp = api.get_season(NON_EXISTENT_UUID, admin)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestProductRules:
    def test_product_fiscal_constraint_proceeds_below_price(self, api):
        """PRD §3.1: "a `troop_proceeds_cents` that must be strictly greater
        than zero and strictly less than `unit_price_cents` — a product whose
        proceeds would meet or exceed its price is rejected with
        `ERR_FISCAL_VIOLATION`."

        Design: Corner/entities/product_fiscal_constraint_proceeds_below_price
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        resp = api.create_product(
            season["id"],
            {
                "variety_code": "BAD",
                "name": "Bad",
                "unit_price_cents": 500,
                "troop_proceeds_cents": 600,
                "allergen_tags": [],
                "packages_per_case": 1,
            },
            admin,
        )
        validate_error(resp, ApiErrorId.ERR_FISCAL_VIOLATION, 422)

    def test_product_default_packages_per_case_applied(self, api):
        """PRD §3.1: "a `packages_per_case` defaulting to 12 and always at
        least 1, which drives the case-pack constraint everywhere packages
        move."

        Design: Corner/entities/product_default_packages_per_case_applied
        """
        admin = make_council_admin_headers()
        season = create_season(admin=admin)
        raw = validate_success(
            api.create_product(
                season["id"],
                {
                    "variety_code": "TM",
                    "name": "Thin Mints",
                    "unit_price_cents": 600,
                    "troop_proceeds_cents": 100,
                    "allergen_tags": [],
                },
                admin,
            ),
            expected_status=201,
        )
        assert_cookie_product(raw)
        assert raw["packages_per_case"] == 12

    def test_computed_fields_ignore_client_input(self, api):
        """PRD §2.5: "`remaining_units` is `purchased_units` minus
        `initial_commit_units` minus `pending_commit_units`" — computed by the
        server; a fresh season with no purchases or commitments computes to 0.
        PRD §3.1: "The season is born in `DRAFT` status with its `version` at 1."

        Design: Corner/entities/computed_fields_ignore_client_input
        """
        admin = make_council_admin_headers()
        resp = api.create_season(create_season_payload(), admin)
        data = validate_success(resp, expected_status=201)
        assert data["remaining_units"] == 0
        assert data["version"] == 1


class TestPagination:
    def test_pagination_defaults_and_fields(self, api):
        """PRD §2.3: "All list endpoints accept two optional query parameters:
        `limit` and `offset`." PRD §2.2: "Pagination-related fields in `meta`
        (`limit`, `offset`, `total_count`, `has_more`) are included for list
        endpoints."

        Design: Corner/entities/pagination_defaults_and_fields
        """
        admin = make_council_admin_headers()
        for _ in range(3):
            create_season(admin=admin)
        data, meta = validate_paginated(
            api.list_seasons(admin, params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
