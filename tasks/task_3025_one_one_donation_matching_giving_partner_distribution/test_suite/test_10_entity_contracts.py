"""Creation, listing and not-found contracts for the primary resources (PRD §2.9, §2.10, §3)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_approved_partner,
    create_season,
    declare_capacity,
    onboard_partner,
    register_claim,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
DESIGN = TEST_USERS["designer_headers"]
PLANNER = TEST_USERS["planner_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
MARKETING = TEST_USERS["marketing_headers"]


class TestPartnerCreationContract:
    """Corner/entities — what a bare onboarding payload produces."""

    def test_onboarding_opens_exactly_one_requested_round(self, api):
        """PRD §3.1: "Onboarding is inseparable from the first review. The same request that admits the partner opens its first vetting round with `round_number` 1 and an `outcome` of `REQUESTED`, sets the partner's `vetting_round` counter to 1, and moves the partner's status from `CANDIDATE` to `VETTING`."
        PRD §3.1: "The `registry_verified` flag is computed rather than accepted: it is true when `registry_id` matches the shape two uppercase letters, a hyphen, `CHR`, another hyphen and six digits, and when `ein` is nine digits."

        Design: Corner/entities/giving_partner_create_returns_declared_fields_and_opens_one_round
        """
        partner = validate_success(
            api_client.create_giving_partner(
                {
                    "legal_name": "Tau Harbor Shelter",
                    "partner_type": "HOMELESS_SHELTER",
                    "operating_region": "NORTHEAST",
                    "operating_state_code": "ME",
                    "service_radius_miles": 40,
                    "registry_id": "ME-CHR-190019",
                    "ein": "200300400",
                    "founded_year": 1968,
                    "unduplicated_recipients_per_facility": 4500,
                    "need_tier": "MODERATE",
                },
                COORD,
            ),
            201,
        )
        assert partner["status"] == "VETTING"
        assert partner["vetting_round"] == 1
        assert partner["version"] == 1
        assert partner["registry_verified"] is True
        assert partner["need_score"] == 77, "70 + 3 + min(20, 4500 // 1000)"

        rounds, _ = validate_paginated(
            api_client.list_vetting_rounds(COORD, {"partner_id": partner["id"]})
        )
        assert len(rounds) == 1
        assert rounds[0]["round_number"] == 1
        assert rounds[0]["outcome"] == "REQUESTED"

    def test_omitting_the_operating_state_is_a_shape_failure(self, api):
        """PRD §3.1: "Onboarding requires both `operating_region` and `operating_state_code` to be supplied."
        PRD §2.4: "Fourth, the request body must be well shaped — every required field present, every enumerated member declared, and every integer range respected (`ERR_INVALID_REQUEST`); a syntactically bad body against a non-existent identifier therefore still reports the not-found failure."

        Design: Corner/entities/giving_partner_create_missing_operating_state_returns_invalid_request
        """
        res = api_client.create_giving_partner(
            {
                "legal_name": "Upsilon Harbor Shelter",
                "partner_type": "HOMELESS_SHELTER",
                "operating_region": "NORTHEAST",
                "registry_id": "ME-CHR-200020",
                "ein": "200300500",
                "founded_year": 1971,
                "unduplicated_recipients_per_facility": 4000,
                "need_tier": "MODERATE",
            },
            COORD,
        )
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

        rows, _ = validate_paginated(api_client.list_giving_partners(COORD))
        assert len(rows) == 0, "nothing may be partially written"

    def test_unknown_partner_id_raises_the_partner_specific_not_found(self, api):
        """PRD §2.9: "Each resource type raises its own not-found error: `ERR_PARTNER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_DONATION_PRODUCT_LINE_NOT_FOUND`, `ERR_SALES_ORDER_NOT_FOUND`, `ERR_SALES_ORDER_LINE_NOT_FOUND` (raised when the line segment does not exist or belongs to a different order), `ERR_SEASON_NOT_FOUND` (raised for a missing season identifier or for a requested season code that names no season), `ERR_LIABILITY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_DISTRIBUTION_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_VETTING_ROUND_NOT_FOUND`, `ERR_RETURN_REQUEST_NOT_FOUND` and `ERR_CAPACITY_PROFILE_NOT_FOUND`."

        Design: Corner/entities/giving_partner_get_with_an_unknown_id_returns_partner_not_found
        """
        api_client.create_donation_product(
            {
                "product_name": "Cornerstone Everyday Sock",
                "product_kind": "ATHLETIC_SOCK",
                "design_channel": "DUAL_CHANNEL",
                "obligation_model": "AT_SALE",
                "approved_donation_ratio_units": 1,
                "retail_price_cents": 1600,
                "unit_cost_cents": 1150,
                "is_reusable": True,
            },
            DESIGN,
        )
        res = api_client.get_giving_partner(
            "00000000-0000-4000-8000-000000000001", COORD
        )
        validate_error(res, "ERR_PARTNER_NOT_FOUND", expected_status=404)


class TestProductCreationContract:
    """Corner/entities — the computed donation-suitability score."""

    def test_design_weight_is_computed_and_status_starts_draft(self, api):
        """PRD §3.4: "Donation suitability is scored, not asserted. A product's `design_weight_score` is assembled from a fabric base determined by `product_kind` (an undergarment contributes 45, an athletic sock 40, an apparel top 30 and a sleep accessory 20), plus 20 points when `is_reusable` is true, plus 10 points when `design_channel` is `DONATION_ONLY` and nothing when it is `DUAL_CHANNEL`; the total is clamped between 0 and 100."

        Design: Corner/entities/donation_product_create_computes_design_weight_and_starts_draft
        """
        product = validate_success(
            api_client.create_donation_product(
                {
                    "product_name": "Weight Probe Underlayer",
                    "product_kind": "UNDERGARMENT",
                    "design_channel": "DONATION_ONLY",
                    "obligation_model": "AT_VESTING",
                    "approved_donation_ratio_units": 1,
                    "retail_price_cents": 1600,
                    "unit_cost_cents": 1150,
                    "is_reusable": True,
                },
                DESIGN,
            ),
            201,
        )
        assert product["status"] == "DRAFT"
        assert product["design_weight_score"] == 75, "45 + 20 + 10"
        assert product["obligation_units_total"] == 0
        assert product["active_season_code"] is None

    def test_an_undeclared_design_channel_is_a_shape_failure(self, api):
        """PRD §3.4: "The `design_channel` is the central design decision: `DONATION_ONLY` describes a good designed for donation that is never listed at retail, while `DUAL_CHANNEL` describes a good sold at retail and donated one-for-one."
        PRD §2.4: "Fourth, the request body must be well shaped — every required field present, every enumerated member declared, and every integer range respected (`ERR_INVALID_REQUEST`); a syntactically bad body against a non-existent identifier therefore still reports the not-found failure."

        Design: Corner/entities/donation_product_create_with_unknown_design_channel_returns_invalid_request
        """
        res = api_client.create_donation_product(
            {
                "product_name": "Bad Channel Sock",
                "product_kind": "ATHLETIC_SOCK",
                "design_channel": "HYBRID_CHANNEL",
                "obligation_model": "AT_SALE",
                "approved_donation_ratio_units": 1,
                "retail_price_cents": 1600,
                "unit_cost_cents": 1150,
                "is_reusable": True,
            },
            DESIGN,
        )
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

        rows, _ = validate_paginated(api_client.list_donation_products(AUDITOR))
        assert len(rows) == 0


class TestSeasonAndCommercialCreationContract:
    """Corner/entities — server-minted fields and defaults."""

    def test_a_season_starts_planned_with_zeroed_aggregates(self, api):
        """PRD §3.7: "An `ImpactAuditor` opens one with a `season_code`, a `starts_at`, an `ends_at` and a `freezes_at`, and it begins `PLANNED`."

        Design: Corner/entities/impact_season_create_defaults_status_to_planned
        """
        season = validate_success(
            api_client.create_impact_season(
                {
                    "season_code": "2026-Q4",
                    "starts_at": "2026-12-01T00:00:00Z",
                    "ends_at": "2027-03-31T00:00:00Z",
                    "freezes_at": "2027-02-15T00:00:00Z",
                },
                AUDITOR,
            ),
            201,
        )
        assert season["status"] == "PLANNED"
        assert season["claim_frozen_units_total"] == 0
        assert season["total_shipped_units"] == 0
        assert season["total_received_units"] == 0
        assert season["liability_carry_in_units"] == 0
        assert season["version"] == 1

    def test_order_system_fields_are_minted_and_client_input_is_ignored(self, api):
        """PRD §3.5: "The order opens at `CREATED` with a `placed_at` stamped from the logical clock and an independent `fulfillment_status` of `PLACED`."
        PRD §2.10: "`id` is a server-minted UUID with no type prefix, so a partner id and a claim id are indistinguishable in form."

        Design: Corner/entities/sales_order_system_fields_are_minted_and_client_input_ignored
        """
        set_clock("2026-09-05T12:00:00Z")
        order = validate_success(
            api_client.create_sales_order(
                {
                    "order_number": "SO-SYS-1",
                    "channel": "RETAIL_POS",
                    "status": "REFUNDED",
                    "version": 44,
                },
                TEST_USERS["customer_service_headers"],
            ),
            201,
        )
        assert order["status"] == "CREATED"
        assert order["fulfillment_status"] == "PLACED"
        assert order["version"] == 1
        assert order["placed_at"] == "2026-09-05T12:00:00Z"
        assert "-" in order["id"]


class TestVettingRoundRepresentation:
    """Corner/entities — the append-only exception among primary resources."""

    def test_the_round_carries_no_version_and_no_updated_at(self, api):
        """PRD §2.10: "One entity is deliberately excluded from this convention: `GivingPartnerVetting` carries only `id` and `created_at`. It has neither `updated_at` nor `version`, because a vetting round is an immutable record of a single review proceeding — new evidence is recorded by writing forward within the round's declared outcome path, and a fresh round is opened rather than an old one edited."

        Design: Corner/entities/vetting_round_exposes_no_version_field
        """
        set_clock("2026-09-01T00:00:00Z")
        partner = onboard_partner()
        round_row = validate_success(
            api_client.get_vetting_round(partner["latest_vetting_round_id"], COORD), 200
        )
        assert round_row["id"] == partner["latest_vetting_round_id"]
        assert round_row.get("version") is None
        assert round_row.get("updated_at") is None
        assert round_row["created_at"]


class TestNotFoundsAndCapacityProfileParent:
    """Corner/entities — per-resource not-found identity and left-to-right resolution."""

    def test_an_unknown_liability_id_raises_the_liability_not_found(self, api):
        """PRD §2.9: "Each resource type raises its own not-found error: `ERR_PARTNER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_DONATION_PRODUCT_LINE_NOT_FOUND`, `ERR_SALES_ORDER_NOT_FOUND`, `ERR_SALES_ORDER_LINE_NOT_FOUND` (raised when the line segment does not exist or belongs to a different order), `ERR_SEASON_NOT_FOUND` (raised for a missing season identifier or for a requested season code that names no season), `ERR_LIABILITY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_DISTRIBUTION_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_VETTING_ROUND_NOT_FOUND`, `ERR_RETURN_REQUEST_NOT_FOUND` and `ERR_CAPACITY_PROFILE_NOT_FOUND`."

        Design: Corner/entities/liability_get_with_an_unknown_id_returns_liability_not_found
        """
        res = api_client.get_liability(
            "00000000-0000-4000-8000-000000000000", AUDITOR
        )
        validate_error(res, "ERR_LIABILITY_NOT_FOUND", expected_status=404)

    def test_a_capacity_profile_needs_its_partner_to_exist(self, api):
        """PRD §2.9: "Third comes existence: path identifiers are resolved left to right and the first identifier that does not resolve decides the response (`ERR_{RESOURCE}_NOT_FOUND`)."
        PRD §2.4: "Fourth, the request body must be well shaped — every required field present, every enumerated member declared, and every integer range respected (`ERR_INVALID_REQUEST`); a syntactically bad body against a non-existent identifier therefore still reports the not-found failure."

        Design: Corner/entities/capacity_profile_create_requires_an_existing_partner
        """
        res = api_client.create_capacity_profile(
            "00000000-0000-4000-8000-000000000002",
            {
                "season_code": "2026-Q3",
                "max_allocatable_units": 100,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2027-01-31T00:00:00Z",
            },
            COORD,
        )
        validate_error(res, "ERR_PARTNER_NOT_FOUND", expected_status=404)

        rows, _ = validate_paginated(api_client.list_capacity_profiles(PLANNER))
        assert len(rows) == 0


class TestAllocationListingFilter:
    """Corner/entities — filtering and the filtered total count."""

    def test_filtering_by_partner_and_kind_reports_the_filtered_total(self, api):
        """PRD §2.3: "Every paginated response carries four fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count` and `has_more`."
        PRD §2.3: "All list endpoints order their results by `created_at` in ascending order unless something more specific is stated in §3, and the collection roll-ups that report partner attribution use their own documented tie-break order rather than `created_at`."

        Design: Corner/entities/allocations_list_filters_by_partner_and_kind_and_reports_total_count
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        product = validate_success(
            api_client.create_donation_product(
                {
                    "product_name": "Listing Probe Sock",
                    "product_kind": "ATHLETIC_SOCK",
                    "design_channel": "DUAL_CHANNEL",
                    "obligation_model": "AT_SALE",
                    "approved_donation_ratio_units": 1,
                    "retail_price_cents": 1600,
                    "unit_cost_cents": 1150,
                    "is_reusable": True,
                },
                DESIGN,
            ),
            201,
        )
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        for units, tier in ((30, "CRITICAL"), (20, "HIGH")):
            current = validate_success(
                api_client.get_giving_partner(partner["id"], PLANNER), 200
            )["version"]
            validate_success(
                api_client.commit_allocation_plan(
                    season["id"],
                    {
                        "giving_partner_id": partner["id"],
                        "claim_id": claim["id"],
                        "donation_product_id": product["id"],
                        "allocated_units": units,
                        "priority_tier": tier,
                        "liquidity_cap": 10,
                        "expected_partner_version": current,
                    },
                    PLANNER,
                ),
                200,
            )

        rows, meta = validate_paginated(
            api_client.list_allocations(
                PLANNER, {"giving_partner_id": partner["id"], "allocation_kind": "ALLOCATION"}
            )
        )
        assert len(rows) == 2
        assert all(r["allocation_kind"] == "ALLOCATION" for r in rows)
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10

        received, meta_received = validate_paginated(
            api_client.list_allocations(PLANNER, {"status": "RECEIVED"})
        )
        assert len(received) == 0
        assert meta_received["total_count"] == 0