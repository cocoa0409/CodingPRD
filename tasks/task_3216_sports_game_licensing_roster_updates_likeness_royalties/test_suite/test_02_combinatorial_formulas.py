"""Difficulty queue A, rule 2: combinatorial_formula — both instances."""
from test_helpers import (
    FINANCE,
    LIVEOPS,
    create_active_agreement,
    create_eligible_athlete,
    create_funded_wallet,
    create_live_season,
    create_open_tournament,
    create_provisional_statement,
    register_entry,
    get_success_data,
    validate_paginated,
)
from test_helpers.api_client import api_client


class TestRoyaltyTieredFormulaModeA:
    def test_tier1_alone_when_base_below_first_cap(self, api):
        """PRD §3.7: "The base then flows through three tiers: the portion up to
        500,000,000 cents (five hundred thousand dollars) accrues at 1000 basis
        points; the portion above that cap and up to 2,000,000,000 cents (two
        million dollars) accrues at 1200 basis points; the portion above the
        second cap accrues at 1500 basis points."

        Design: Difficulty/combinatorial_formula/royalty_tiered_formula_mode_a
        """
        agreement = create_active_agreement(
            licensor_name="Hoops League", sport_category="BASKET_PRO",
            exclusivity_scope="NONE", royalty_rate_bps=1000,
            minimum_guarantee_cents=0, mg_recoupable=False,
            audit_window_days=60,
        )
        statement = create_provisional_statement(
            agreement["id"],
            gross_sales_cents=40000000, returns_cents=0, pending_sales_cents=0,
        )
        assert statement["accrued_royalty_cents"] == 4000000, (
            f"base 40M < tier1 cap => 40000000*1000/10000 = 4000000; "
            f"got {statement['accrued_royalty_cents']}"
        )

    def test_base_straddling_tier1_and_tier2(self, api):
        """PRD §3.7: "Summing the three tier contributions yields the raw
        accrual."

        Design: Difficulty/combinatorial_formula/royalty_tiered_formula_mode_a
        """
        agreement = create_active_agreement(
            licensor_name="Hoops League", sport_category="BASKET_PRO",
            exclusivity_scope="NONE", royalty_rate_bps=1000,
            minimum_guarantee_cents=0, mg_recoupable=False,
            audit_window_days=60,
        )
        statement = create_provisional_statement(
            agreement["id"],
            gross_sales_cents=250000000, returns_cents=60000000,
            pending_sales_cents=0,
        )
        # net = 190,000,000; tier1 = 50,000,000*1000/10000 = 5,000,000
        # tier2 = 140,000,000*1200/10000 = 16,800,000; tier3 = 0
        assert statement["accrued_royalty_cents"] == 21800000, (
            f"expected 5,000,000 + 16,800,000 = 21,800,000; "
            f"got {statement['accrued_royalty_cents']}"
        )


class TestPrizePoolFloorPerRowThenRemainderModeB:
    def _setup_three_entry_program(self, api):
        agreement = create_active_agreement(
            licensor_name="Futbol Intl", sport_category="SOCCER_INTL",
            exclusivity_scope="NONE",
        )
        athlete, _ = create_eligible_athlete(agreement["id"])
        season = create_live_season(
            agreement["id"], athlete["id"], initial_rating=88,
            title_code="FUTBOL26", sport_category="SOCCER_INTL",
        )
        program = create_open_tournament(
            season["id"],
            prize_rows=((1, 3333), (2, 3333), (3, 3334)),
            program_label="CUP333", league_sanctioned=True,
            entry_fee_vc=333,
            registration_opens_at="2026-08-01T00:00:00Z",
            registration_closes_at="2026-12-01T00:00:00Z",
        )
        wallets = [
            create_funded_wallet(season["id"], 1000, owner_tag=f"p{i}")
            for i in (1, 2, 3)
        ]
        entries = [register_entry(program["id"], w["id"]) for w in wallets]
        return program, entries

    def test_floor_per_row_remainder_to_first_place(self, api):
        """PRD §3.5: "prize rows are sorted by placement ascending, each row's
        raw amount is the pool multiplied by its share_bps and divided by ten
        thousand, each row is rounded down (floored) to an integer, and the
        residual — the pool minus the sum of floored rows — is assigned in
        full to the placement-1 row."

        Design: Difficulty/combinatorial_formula/prize_pool_floor_per_row_then_remainder_mode_b
        """
        program, entries = self._setup_three_entry_program(api)
        get_success_data(api_client.close_registration(program["id"], LIVEOPS))
        get_success_data(
            api_client.record_results(
                program["id"],
                {"placements": [
                    {"entry_id": entries[0]["id"], "placement": 1},
                    {"entry_id": entries[1]["id"], "placement": 2},
                    {"entry_id": entries[2]["id"], "placement": 3},
                ]},
                LIVEOPS,
            )
        )
        rows, _ = validate_paginated(
            api_client.list_prize_rows(program["id"], LIVEOPS)
        )
        by_placement = {r["placement"]: r for r in rows}
        # pool = 3*333 = 999; floor rows 332/332/333; remainder 2 -> row 1
        assert by_placement[1]["final_amount_vc"] == 334, (
            f"332 floored + 2 remainder = 334; got "
            f"{by_placement[1]['final_amount_vc']}"
        )
        assert by_placement[2]["final_amount_vc"] == 332
        assert by_placement[3]["final_amount_vc"] == 333

    def test_total_payout_equals_pool_exactly(self, api):
        """PRD §2.7: "Prize-pool allocations use a different rounding rule —
        floor per row, with the residual remainder assigned to the first-place
        row — because under-allocating the pool is preferable to inventing
        currency."

        Design: Difficulty/combinatorial_formula/prize_pool_floor_per_row_then_remainder_mode_b
        """
        program, entries = self._setup_three_entry_program(api)
        get_success_data(api_client.close_registration(program["id"], LIVEOPS))
        get_success_data(
            api_client.record_results(
                program["id"],
                {"placements": [
                    {"entry_id": entries[0]["id"], "placement": 1},
                    {"entry_id": entries[1]["id"], "placement": 2},
                    {"entry_id": entries[2]["id"], "placement": 3},
                ]},
                LIVEOPS,
            )
        )
        rows, _ = validate_paginated(
            api_client.list_prize_rows(program["id"], LIVEOPS)
        )
        total = sum(r["final_amount_vc"] for r in rows)
        assert total == 999, (
            f"floor-per-row + remainder-to-first must conserve the pool "
            f"exactly (3*333=999); got {total}"
        )
