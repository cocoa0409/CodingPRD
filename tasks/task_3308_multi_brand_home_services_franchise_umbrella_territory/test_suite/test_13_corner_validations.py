"""Validation corner claims: the trade-qualification rung and a fully cleared award."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_agreement,
    award_territory,
    create_agreement,
    create_brand,
    create_franchisee,
    create_lead,
    create_territory,
    franchisee_version,
    get_franchisee,
    get_lead,
    get_territory,
    offer_agreement,
    offer_territory,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestLeadAllocationSharedServicesGate:
    def test_an_unenrolled_receiving_franchisee_is_refused_on_the_safety_rung(self, api):
        """PRD §2.4: "A receiving franchisee whose `shared_services_enrolled` is
        false cannot be given a shared-pool lead, and such an allocation is
        refused with `ERR_SHARED_SERVICES_REQUIRED`. All three of these refusals
        carry HTTP 422."

        Design: Corner/validations/lead_allocation_shared_services_denial_for_unenrolled_franchisee
        """
        set_clock("2026-09-01T00:00:00Z")
        solo = create_franchisee(
            legal_name="Solo Trades LLC", principal_name="Marta Reyes",
            entity_type="SOLE_PROPRIETOR", shared_services_enrolled=False,
        )
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        territory = create_territory(brand["id"], franchisee_id=solo["id"])
        agreement = create_agreement(solo["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], solo["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])

        lead = create_lead(
            brand["id"], source="CALL_CENTER", household_income_band="BAND_2",
            estimated_value_cents=120000,
        )
        resp = api.allocate_lead(
            lead["id"], franchisee_version(solo["id"]), ADMIN,
            allocated_agreement_id=agreement["id"],
        )
        validate_error(resp, ApiErrorId.ERR_SHARED_SERVICES_REQUIRED)

        refused = get_lead(lead["id"])
        assert refused["status"] == "RECEIVED"
        assert refused["allocated_agreement_id"] is None
        assert get_franchisee(solo["id"])["lead_cost_balance_cents"] == 0


class TestLeadPoolEmptyFallback:
    def test_a_non_enrolled_holder_makes_the_candidate_set_empty(self, api):
        """PRD §3.6: "An agreement is eligible only if it is for the lead's
        brand, its `lifecycle_status` is `ACTIVE`, its franchisee's status is
        `ACTIVE`, that franchisee has `shared_services_enrolled` true".

        Design: Corner/validations/non_enrolled_franchisee_never_appears_in_the_recipient_ranking
        """
        set_clock("2026-09-01T00:00:00Z")
        solo = create_franchisee(
            legal_name="Solo Trades LLC", principal_name="Marta Reyes",
            entity_type="SOLE_PROPRIETOR", shared_services_enrolled=False,
        )
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        territory = create_territory(brand["id"], franchisee_id=solo["id"])
        agreement = create_agreement(solo["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], solo["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])

        lead = create_lead(
            brand["id"], source="CALL_CENTER", household_income_band="BAND_2",
            estimated_value_cents=120000,
        )
        resp = api.allocate_lead(
            lead["id"], franchisee_version(solo["id"]), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_LEAD_POOL_EMPTY)

        preview = validate_success(
            api.preview_lead_recipients(lead["id"], ADMIN), 200,
        )
        assert preview["candidate_agreement_ids"] == [], (
            "a non-enrolled holder leaves no eligible agreement, got "
            f"{preview['candidate_agreement_ids']}"
        )
        assert preview["selected_agreement_id"] is None

        refused = get_lead(lead["id"])
        assert refused["status"] == "RECEIVED"
        assert refused["allocated_agreement_id"] is None


class TestTerritoryAwardClearsEveryGate:
    def test_a_fully_cleared_award_succeeds_and_raises_the_holder_counter(self, api):
        """PRD §3.2: "The test sums `household_count` over the franchisee's
        territories already in `AWARDED`, `ACTIVE` or `EXPANSION_REQUESTED`
        status and adds the count of the territory being awarded; a total above
        250,000 is refused with `ERR_HOUSEHOLD_CAP_EXCEEDED`, so a franchisee
        sitting at exactly 250,000 cannot be awarded a further household."
        PRD §3.2: "On success the territory moves to `AWARDED`, its own
        `allocated_households` is set to its `household_count`, and the
        franchisee's `allocated_households` counter is recomputed".

        Design: Corner/validations/territory_award_succeeds_when_every_priority_5_to_11_gate_is_clear
        """
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        # An unrelated brand's live territory, so the postal check inspects
        # other brands without matching.
        other = create_brand(
            brand_code="RVR", display_name="Revive Restoration", trade="RESTORATION",
            royalty_rate=0.07, national_ad_fund_rate=0.015,
            min_certification_level="MASTER", audit_cycle_months=6,
            cross_brand_fee_table={},
        )
        create_territory(
            other["id"], territory_code="RV-01", household_count=9000,
            postal_codes=["78001"],
        )

        territory = create_territory(
            brand["id"], franchisee_id=franchisee["id"], territory_code="MS-01",
            household_count=30000, postal_codes=["75001", "75002"],
        )
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_territory(territory["id"], franchisee["id"])
        offer_agreement(agreement["id"])

        resp = api.award_territory(
            territory["id"], get_territory(territory["id"])["version"], ADMIN,
        )
        awarded = validate_success(resp, 200)

        assert awarded["status"] == "AWARDED"
        assert awarded["allocated_households"] == 30000
        assert get_franchisee(franchisee["id"])["allocated_households"] == 30000, (
            "30000 is well under the 250000 cap, so the award must pass and the "
            "counter must move"
        )

        rows, meta = validate_paginated(
            api.list_territories(ADMIN, {"brand_id": other["id"]})
        )
        assert meta["total_count"] == 1

    def test_the_award_advances_the_territory_version_by_one(self, api):
        """PRD §3.2: "The award increments the territory's `version` by one,
        which is precisely why the next writer against that territory must
        present a fresh `expected_territory_version`."

        Design: Corner/validations/territory_award_succeeds_when_every_priority_5_to_11_gate_is_clear
        """
        set_clock("2026-09-01T00:00:00Z")
        franchisee = create_franchisee()
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_territory(territory["id"], franchisee["id"])
        offer_agreement(agreement["id"])

        before = get_territory(territory["id"])["version"]
        awarded = award_territory(territory["id"], expected_version=before)
        assert awarded["version"] == before + 1, (
            f"the award must advance the version from {before} to {before + 1}, "
            f"got {awarded['version']}"
        )