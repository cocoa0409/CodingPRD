"""Compensating-action invariants: the lead-cost balance and household allocation."""
from test_helpers import (
    TEST_USERS,
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
    make_franchisee_operator_headers,
    offer_agreement,
    offer_territory,
    set_clock,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


def _build_pair_of_brands_for_one_franchisee():
    """A franchisee holding two ACTIVE agreements across brands MS and IL."""
    set_clock("2026-09-01T00:00:00Z")
    ms_brand = create_brand(
        brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
        royalty_rate=0.06, national_ad_fund_rate=0.01,
        min_certification_level="APPRENTICE", audit_cycle_months=12,
        cross_brand_fee_table={},
    )
    il_brand = create_brand(
        brand_code="ILE", display_name="Illume Electric", trade="ELECTRICAL",
        royalty_rate=0.06, national_ad_fund_rate=0.01,
        min_certification_level="JOURNEYMAN", audit_cycle_months=12,
        cross_brand_fee_table={},
    )
    franchisee = create_franchisee()
    ter_ms = create_territory(ms_brand["id"], franchisee_id=franchisee["id"])
    ter_il = create_territory(il_brand["id"], franchisee_id=franchisee["id"])
    agt_ms = create_agreement(franchisee["id"], ms_brand["id"], ter_ms["id"])
    agt_il = create_agreement(
        franchisee["id"], il_brand["id"], ter_il["id"], certification_level="MASTER",
    )
    for territory, agreement in ((ter_ms, agt_ms), (ter_il, agt_il)):
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
    return ms_brand, franchisee, agt_ms


class TestLeadAllocateReleaseConservation:
    def test_the_allocation_changes_the_balance_by_exactly_the_resolved_cost(self, api):
        """PRD §2.8: "The third is the franchisee's `lead_cost_balance_cents`,
        the running cost of shared-pool leads. It is increased by a lead's
        `lead_cost_cents` when the lead is allocated to that franchisee's
        agreement".
        PRD §3.6: "The lead's `estimated_value_cents` is divided by 100,000
        cents and the quotient is rounded up to a whole number of units; that
        unit count is multiplied by 250 cents to give a value surcharge."

        Design: Difficulty/compensating_invariant/lead_allocate_and_release_conserve_cost_balance
        """
        ms_brand, franchisee, agt_ms = _build_pair_of_brands_for_one_franchisee()
        lead = create_lead(
            ms_brand["id"], source="CALL_CENTER", household_income_band="BAND_2",
            estimated_value_cents=150000,
        )

        resp = api.allocate_lead(
            lead["id"], franchisee_version(franchisee["id"]), ADMIN,
            allocated_agreement_id=agt_ms["id"],
        )
        allocated = validate_success(resp, 200)

        assert allocated["status"] == "ALLOCATED"
        # BAND_2 base 4000 + ceil(150000 / 100000)=2 units * 250 = 4500 subtotal.
        # The franchisee holds two brands, below the multi-brand minimum of 3,
        # so no portfolio discount applies.
        expected = 4000 + 2 * 250
        assert allocated["lead_cost_cents"] == expected, (
            f"BAND_2 base 4000 plus a two-unit surcharge of 500 is {expected}, "
            f"got {allocated['lead_cost_cents']}"
        )

        charged = get_franchisee(franchisee["id"])
        assert charged["lead_cost_balance_cents"] == allocated["lead_cost_cents"], (
            "the balance must move by exactly the resolved lead cost, got "
            f"{charged['lead_cost_balance_cents']} against "
            f"{allocated['lead_cost_cents']}"
        )

    def test_release_returns_the_conserved_balance_to_its_starting_value(self, api):
        """PRD §3.6: "the allocation may be released only once the logical clock
        is strictly after `allocation_hold_until_iso`, so a release attempted at
        or before that instant is refused with `ERR_HOLD_WINDOW_ACTIVE`."
        PRD §3.6: "on success stamps `released_clock_iso`, decreases the
        franchisee's `lead_cost_balance_cents` by the lead's `lead_cost_cents`,
        and resets the lead's own `lead_cost_cents` to zero."

        Design: Difficulty/compensating_invariant/lead_allocate_and_release_conserve_cost_balance
        """
        ms_brand, franchisee, agt_ms = _build_pair_of_brands_for_one_franchisee()
        lead = create_lead(
            ms_brand["id"], source="CALL_CENTER", household_income_band="BAND_2",
            estimated_value_cents=150000,
        )
        resp = api.allocate_lead(
            lead["id"], franchisee_version(franchisee["id"]), ADMIN,
            allocated_agreement_id=agt_ms["id"],
        )
        cost = validate_success(resp, 200)["lead_cost_cents"]

        # The hold runs 26 logical hours from the allocation clock.
        set_clock("2026-09-02T02:00:01Z")
        resp = api.release_lead(
            lead["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        released = validate_success(resp, 200)

        assert released["status"] == "RELEASED"
        assert get_franchisee(franchisee["id"])["lead_cost_balance_cents"] == 0, (
            "the release must return the balance exactly to its pre-allocation "
            f"value of 0, having charged {cost}"
        )
        assert get_lead(lead["id"])["lead_cost_cents"] == 0, (
            "the release resets the lead's own cost field to zero"
        )


class TestTerritoryAwardReclaimConservation:
    def test_award_then_reclaim_conserves_allocated_households(self, api):
        """PRD §2.6: "On the franchisee, `allocated_households` is a maintained
        counter: it is increased by a territory's `household_count` when that
        territory is awarded and when an expansion is requested, and decreased
        when a territory is reclaimed, suspended or expired."
        PRD §3.3: "Reclaim is the terminal act of the ladder: it clears the
        holder by setting the territory's `franchisee_id` to null, resets its
        `allocated_households` to zero, and moves it to `RECLAIMED`".

        Design: Difficulty/compensating_invariant/territory_award_and_reclaim_conserve_allocated_households
        """
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        territory = create_territory(
            brand["id"], franchisee_id=franchisee["id"], household_count=30000,
        )
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        # PRD 2.5 rung 8: the award requires a matching agreement already
        # OFFERED or ACTIVE, so the offer precedes the award.
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        awarded = award_territory(territory["id"])

        assert awarded["allocated_households"] == 30000, (
            f"the territory's allocation is set to its household count at award, "
            f"got {awarded['allocated_households']}"
        )
        assert get_franchisee(franchisee["id"])["allocated_households"] == 30000, (
            "the award must raise the franchisee's counter by the household count"
        )

        activate_agreement(agreement["id"])
        api.suspend_agreement(
            agreement["id"], ADMIN,
            reason="Operator standing down ahead of a reallocation",
        )
        resp = api.reclaim_territory(territory["id"], ADMIN)
        reclaimed = validate_success(resp, 200)

        assert reclaimed["status"] == "RECLAIMED"
        assert reclaimed["allocated_households"] == 0, (
            f"the reclaim resets the territory's allocation, got "
            f"{reclaimed['allocated_households']}"
        )
        assert reclaimed["franchisee_id"] is None
        assert get_franchisee(franchisee["id"])["allocated_households"] == 0, (
            "the reclaim must return the franchisee's counter to its "
            "pre-award value of 0 — no drift"
        )

    def test_the_reclaimed_territory_leaves_the_holders_footprint(self, api):
        """PRD §2.6: "It must always reconcile to the sum of `household_count`
        across that franchisee's territories in `AWARDED`, `ACTIVE` or
        `EXPANSION_REQUESTED` status. Drift between the counter and its
        underlying rows is a defect, not a tolerated variance."

        Design: Difficulty/compensating_invariant/territory_award_and_reclaim_conserve_allocated_households
        """
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        territory = create_territory(
            brand["id"], franchisee_id=franchisee["id"], household_count=30000,
        )
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
        api.suspend_agreement(agreement["id"], ADMIN, reason="Standing down")
        api.reclaim_territory(territory["id"], ADMIN)

        rows, _ = validate_paginated(
            api.list_territories(ADMIN, {"franchisee_id": franchisee["id"]})
        )
        holding = [r for r in rows
                   if r["status"] in ("AWARDED", "ACTIVE", "EXPANSION_REQUESTED")]
        assert sum(r["household_count"] for r in holding) == 0, (
            "no territory of this franchisee may still be in a holding status"
        )
        assert get_franchisee(franchisee["id"])["allocated_households"] == 0, (
            "the counter must reconcile to the underlying rows, which now sum to 0"
        )
        assert get_territory(territory["id"])["status"] == "RECLAIMED"