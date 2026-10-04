"""Calculation corner claims: the lead price band and the recipient selector."""
from test_helpers import (
    TEST_USERS,
    allocate_lead,
    create_agreement,
    create_brand,
    create_franchisee,
    create_lead,
    create_territory,
    franchisee_version,
    get_lead,
    make_franchisee_operator_headers,
    offer_agreement,
    offer_territory,
    activate_agreement,
    award_territory,
    set_clock,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestLeadCostBandAndSurcharge:
    def test_a_single_brand_franchisee_pays_the_undiscounted_subtotal(self, api):
        """PRD §3.6: "The surcharge is added to a band base — 2500 cents for
        `BAND_1`, 4000 cents for `BAND_2`, 6500 cents for `BAND_3` and 9000
        cents for `BAND_4` — and the sum is the subtotal."
        PRD §3.6: "otherwise the subtotal itself is the `lead_cost_cents`."

        Design: Corner/calculations/lead_cost_band_and_value_surcharge_exact_result
        """
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])

        lead = create_lead(
            brand["id"], source="CALL_CENTER", household_income_band="BAND_3",
            estimated_value_cents=250000,
        )
        resp = api.allocate_lead(
            lead["id"], franchisee_version(franchisee["id"]), ADMIN,
            allocated_agreement_id=agreement["id"],
        )
        allocated = validate_success(resp, 200)

        assert allocated["status"] == "ALLOCATED"
        assert allocated["lead_cost_cents"] == 7250, (
            "a BAND_3 base of 6500 plus ceil(250000 / 100000)=3 units * 250 is "
            f"7250, got {allocated['lead_cost_cents']}"
        )
        assert allocated["lead_cost_cents"] != 6163, (
            "one brand is below the portfolio-discount boundary, so the 0.85 "
            "credit must not be applied"
        )
        assert api.get_franchisee(franchisee["id"], ADMIN).json()["data"][
            "lead_cost_balance_cents"] == 7250


class TestRecipientSelectorHoldCeiling:
    def test_an_agreement_inside_its_hold_window_leaves_the_candidate_set(self, api):
        """PRD §3.6: "An agreement is eligible only if it is for the lead's
        brand, its `lifecycle_status` is `ACTIVE`, its franchisee's status is
        `ACTIVE`, that franchisee has `shared_services_enrolled` true, and the
        agreement is not currently holding a live allocation — that is, no lead
        assigned to it is in `ALLOCATED` status with an
        `allocation_hold_until_iso` still after the logical clock."
        PRD §3.6: "A `FranchiseAdmin` can also preview the ranking for a lead
        without allocating it, receiving the identifier of the agreement the
        selector would choose, the identifiers of the full candidate set, and
        the ranking keys the selection was made on."

        Design: Corner/calculations/lead_allocation_selector_skips_agreements_at_their_hold_ceiling
        """
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        ter_first = create_territory(
            brand["id"], franchisee_id=franchisee["id"], territory_code="MS-01",
        )
        ter_second = create_territory(
            brand["id"], franchisee_id=franchisee["id"], territory_code="MS-02",
        )
        agt_first = create_agreement(
            franchisee["id"], brand["id"], ter_first["id"], agreement_number="A-MS-01",
        )
        agt_second = create_agreement(
            franchisee["id"], brand["id"], ter_second["id"], agreement_number="A-MS-02",
        )
        for territory, agreement in ((ter_first, agt_first), (ter_second, agt_second)):
            offer_agreement(agreement["id"])
            offer_territory(territory["id"], franchisee["id"])
            award_territory(territory["id"])
            activate_agreement(agreement["id"])

        prior = create_lead(
            brand["id"], source="CALL_CENTER", household_income_band="BAND_1",
            estimated_value_cents=100000,
        )
        allocate_lead(
            prior["id"], franchisee["id"], allocated_agreement_id=agt_first["id"],
        )

        fresh = create_lead(
            brand["id"], source="CALL_CENTER", household_income_band="BAND_1",
            estimated_value_cents=100000,
        )
        resp = api.preview_lead_recipients(fresh["id"], ADMIN)
        preview = validate_success(resp, 200)

        assert preview["selected_agreement_id"] == agt_second["id"], (
            f"the least-loaded eligible recipient must be selected, got "
            f"{preview['selected_agreement_id']}"
        )
        assert agt_first["id"] not in preview["candidate_agreement_ids"], (
            "an agreement holding a live allocation inside its hold window is "
            "not in the candidate set"
        )

    def test_allocating_without_pinning_uses_the_selected_recipient(self, api):
        """PRD §3.6: "The request may pin the receiving side by supplying
        `allocated_agreement_id`; when it is omitted, the receiving agreement is
        chosen by the selector below."

        Design: Corner/calculations/lead_allocation_selector_skips_agreements_at_their_hold_ceiling
        """
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        ter_first = create_territory(
            brand["id"], franchisee_id=franchisee["id"], territory_code="MS-01",
        )
        ter_second = create_territory(
            brand["id"], franchisee_id=franchisee["id"], territory_code="MS-02",
        )
        agt_first = create_agreement(
            franchisee["id"], brand["id"], ter_first["id"], agreement_number="A-MS-01",
        )
        agt_second = create_agreement(
            franchisee["id"], brand["id"], ter_second["id"], agreement_number="A-MS-02",
        )
        for territory, agreement in ((ter_first, agt_first), (ter_second, agt_second)):
            offer_agreement(agreement["id"])
            offer_territory(territory["id"], franchisee["id"])
            award_territory(territory["id"])
            activate_agreement(agreement["id"])

        prior = create_lead(
            brand["id"], source="CALL_CENTER", household_income_band="BAND_1",
            estimated_value_cents=100000,
        )
        allocate_lead(
            prior["id"], franchisee["id"], allocated_agreement_id=agt_first["id"],
        )

        fresh = create_lead(
            brand["id"], source="CALL_CENTER", household_income_band="BAND_1",
            estimated_value_cents=100000,
        )
        allocated = allocate_lead(fresh["id"], franchisee["id"])
        assert allocated["allocated_agreement_id"] == agt_second["id"], (
            "the unpinned allocation must take the selector's choice, got "
            f"{allocated['allocated_agreement_id']}"
        )
        assert get_lead(fresh["id"])["status"] == "ALLOCATED"

        # The hold window is 26 logical hours from this allocation clock.
        api.set_clock("2026-09-02T02:00:01Z", ADMIN)
        api.release_lead(
            fresh["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        rows, meta = validate_paginated(
            api.list_agreements(ADMIN, {"franchisee_id": franchisee["id"]})
        )
        assert meta["total_count"] == 2