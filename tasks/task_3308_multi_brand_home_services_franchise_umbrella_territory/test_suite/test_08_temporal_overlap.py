"""Resource temporal overlap: live postal sets and half-open statement periods."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_agreement,
    award_territory,
    create_agreement,
    create_brand,
    create_franchisee,
    create_territory,
    get_territory,
    issue_statement,
    offer_agreement,
    offer_territory,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestPostalCodeLiveSetOverlap:
    def _brand_with_one_live_territory(self):
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        territory = create_territory(
            brand["id"], franchisee_id=franchisee["id"], territory_code="MS-01",
            household_count=30000, postal_codes=["75001", "75002"],
            expansion_right_households=40000,
        )
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
        return brand, franchisee, territory

    def test_a_single_shared_postal_code_collides(self, api):
        """PRD §2.6: "no postal code may belong to two territories of the same
        brand unless one of them is `RECLAIMED`; a would-be overlap is refused
        with `ERR_TERRITORY_POSTAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/postal_code_live_set_overlap_on_territory_creation
        """
        brand, _, _ = self._brand_with_one_live_territory()

        resp = api.create_territory(
            {
                "territory_code": "MS-02",
                "brand_id": brand["id"],
                "household_count": 12000,
                "postal_codes": ["75002", "75009"],
                "expansion_right_households": 20000,
                "protected": True,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_POSTAL_OVERLAP)

    def test_a_disjoint_set_is_accepted_and_the_live_set_is_unchanged(self, api):
        """PRD §2.6: "The `postal_codes` array must be non-empty, and no postal
        code may belong to two territories of the same brand unless one of them
        is `RECLAIMED`; a would-be overlap is refused with
        `ERR_TERRITORY_POSTAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/postal_code_live_set_overlap_on_territory_creation
        """
        brand, _, territory = self._brand_with_one_live_territory()

        resp = api.create_territory(
            {
                "territory_code": "MS-03",
                "brand_id": brand["id"],
                "household_count": 12000,
                "postal_codes": ["75009", "75010"],
                "expansion_right_households": 20000,
                "protected": True,
            },
            ADMIN,
        )
        created = validate_success(resp, 201)
        assert created["postal_codes"] == ["75009", "75010"], (
            f"a disjoint set must be stored as supplied, got {created['postal_codes']}"
        )

        resp = api.list_territories(ADMIN, {"brand_id": brand["id"], "status": "DEFINED"})
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, (
            f"the rejected MS-02 must not exist; only MS-03 is DEFINED, got "
            f"{meta['total_count']}"
        )

        live = get_territory(territory["id"])
        assert live["postal_codes"] == ["75001", "75002"], (
            f"the live territory's protected area must be untouched, got "
            f"{live['postal_codes']}"
        )


class TestStatementPeriodHalfOpenOverlap:
    def _active_agreement(self):
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(
            franchisee["id"], brand["id"], territory["id"], royalty_rate_override=0.06,
        )
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
        return agreement

    def test_adjacency_at_a_shared_endpoint_is_legal(self, api):
        """PRD §3.10: "a `period_end` at or before the `period_start` is
        refused with `ERR_INVALID_PERIOD`. The period must also not overlap a
        statement for the same agreement that has not been voided, and an
        overlap is refused with `ERR_STATEMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/statement_period_half_open_overlap_on_posting
        """
        agreement = self._active_agreement()

        first = validate_success(api.create_statement(
            {
                "agreement_id": agreement["id"],
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2026-09-15T00:00:00Z",
                "gross_revenue_cents": 500000,
            },
            ADMIN,
        ), 201)
        assert first["period_start"] == "2026-09-01T00:00:00Z"
        assert first["period_end"] == "2026-09-15T00:00:00Z"

        adjacent = validate_success(api.create_statement(
            {
                "agreement_id": agreement["id"],
                "period_start": "2026-09-15T00:00:00Z",
                "period_end": "2026-10-01T00:00:00Z",
                "gross_revenue_cents": 500000,
            },
            ADMIN,
        ), 201)
        assert adjacent["period_start"] == "2026-09-15T00:00:00Z", (
            "a window that shares only its endpoint with the first must be "
            "accepted because the period is half-open"
        )

    def test_an_interior_collision_is_refused(self, api):
        """PRD §3.10: "The period must also not overlap a statement for the same
        agreement that has not been voided, and an overlap is refused with
        `ERR_STATEMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/statement_period_half_open_overlap_on_posting
        """
        agreement = self._active_agreement()
        api.create_statement(
            {
                "agreement_id": agreement["id"],
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2026-09-15T00:00:00Z",
                "gross_revenue_cents": 500000,
            },
            ADMIN,
        )

        resp = api.create_statement(
            {
                "agreement_id": agreement["id"],
                "period_start": "2026-09-10T00:00:00Z",
                "period_end": "2026-09-20T00:00:00Z",
                "gross_revenue_cents": 100000,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP)

        listing = validate_paginated(
            api.list_statements(ADMIN, {"agreement_id": agreement["id"]})
        )
        assert listing[1]["total_count"] == 1, (
            f"only the accepted posting must exist, got {listing[1]['total_count']}"
        )

    def test_a_voided_statement_no_longer_reserves_its_window(self, api):
        """PRD §3.10: "The period must also not overlap a statement for the same
        agreement that has not been voided" — voiding frees the window again.

        Design: Difficulty/resource_temporal_overlap/statement_period_half_open_overlap_on_posting
        """
        agreement = self._active_agreement()
        statement = validate_success(api.create_statement(
            {
                "agreement_id": agreement["id"],
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2026-09-15T00:00:00Z",
                "gross_revenue_cents": 500000,
            },
            ADMIN,
        ), 201)
        issue_statement(statement["id"])
        api.void_statement(statement["id"], ADMIN)

        resp = api.create_statement(
            {
                "agreement_id": agreement["id"],
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2026-09-15T00:00:00Z",
                "gross_revenue_cents": 500000,
            },
            ADMIN,
        )
        reissued = validate_success(resp, 201)
        assert reissued["status"] == "DRAFT", (
            "a voided statement no longer reserves its window, so the period may "
            f"be posted again, got {reissued['status']}"
        )