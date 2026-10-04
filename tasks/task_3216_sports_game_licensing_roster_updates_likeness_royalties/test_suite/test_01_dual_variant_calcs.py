"""Difficulty queue A, rule 1: dual_variant_calc — both instances (>=2 tests each)."""
from test_helpers import (
    FINANCE,
    LIVEOPS,
    create_active_agreement,
    create_eligible_athlete,
    create_finalized_statement,
    create_funded_wallet,
    create_live_season,
    create_open_tournament,
    create_provisional_statement,
    register_entry,
    set_clock,
    get_success_data,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_tournament_prize


class TestRoyaltyAccrualProvisionalVsFinalVariants:
    def test_provisional_includes_pending_sales(self, api):
        """PRD §3.7: "The PROVISIONAL variant runs while the period is still
        open via compute-provisional and includes pending sales: net sales use
        gross_sales_cents as reported."

        Design: Difficulty/dual_variant_calc/royalty_accrual_provisional_vs_final_variants
        """
        agreement = create_active_agreement(
            licensor_name="Pro Football League", exclusivity_scope="CATEGORY",
            royalty_rate_bps=1000, minimum_guarantee_cents=0,
            mg_recoupable=False, audit_window_days=90,
        )
        statement = create_provisional_statement(
            agreement["id"],
            gross_sales_cents=1000000, returns_cents=100000,
            pending_sales_cents=200000,
        )
        assert statement["accrued_royalty_cents"] == 90000, (
            f"PROVISIONAL must accrue on 1000000-100000=900000 base at 1000bps; "
            f"got {statement['accrued_royalty_cents']}"
        )
        assert statement["statement_status"] == "PROVISIONAL"

    def test_final_excludes_pending_sales_and_differs(self, api):
        """PRD §3.7: "The FINAL variant runs at finalize — permitted only once
        the clock date is past period_end_on, otherwise ERR_TEMPORAL_CONFLICT —
        and excludes pending sales: net sales use gross_sales_cents minus
        pending_sales_cents."

        Design: Difficulty/dual_variant_calc/royalty_accrual_provisional_vs_final_variants
        """
        agreement = create_active_agreement(
            licensor_name="Pro Football League", exclusivity_scope="CATEGORY",
            royalty_rate_bps=1000, minimum_guarantee_cents=0,
            mg_recoupable=False, audit_window_days=90,
        )
        provisional = create_provisional_statement(
            agreement["id"],
            gross_sales_cents=1000000, returns_cents=100000,
            pending_sales_cents=200000,
        )
        set_clock("2026-09-15T00:00:00Z")
        finalized = get_success_data(
            api_client.finalize_statement(provisional["id"], FINANCE)
        )
        assert provisional["accrued_royalty_cents"] == 90000
        assert finalized["accrued_royalty_cents"] == 70000, (
            f"FINAL must accrue on 1000000-200000-100000=700000 base at 1000bps; "
            f"got {finalized['accrued_royalty_cents']}"
        )
        assert finalized["statement_status"] == "FINALIZED"
        assert finalized["accrued_royalty_cents"] != provisional["accrued_royalty_cents"], (
            "the pending slice of 200000 at 1000bps must drive a 20000 delta"
        )


class TestPrizePoolProjectedVsFinalVariants:
    def _setup_program_with_refunded_entry(self, api):
        """Season LIVE; program entry_fee 1000, shares 6000/4000; 4 paid entries
        then a REFUND credit flips entry 4's fee_paid to false."""
        ctx_agreement = create_active_agreement(exclusivity_scope="NONE")
        athlete, _ = create_eligible_athlete(ctx_agreement["id"])
        season = create_live_season(ctx_agreement["id"], athlete["id"],
                                    initial_rating=90)
        program = create_open_tournament(
            season["id"],
            prize_rows=((1, 6000), (2, 4000)),
            program_label="LEAGUE_CUP_Q1",
            league_sanctioned=True,
            entry_fee_vc=1000,
            registration_opens_at="2026-08-01T00:00:00Z",
            registration_closes_at="2026-12-01T00:00:00Z",
        )
        wallets = [
            create_funded_wallet(season["id"], 5000, owner_tag=f"player-{i}")
            for i in (1, 2, 3)
        ]
        wallets.append(create_funded_wallet(season["id"], 1000, owner_tag="player-4"))
        entries = [register_entry(program["id"], w["id"]) for w in wallets]
        get_success_data(
            api_client.post_ledger_entry(
                wallets[3]["id"],
                {"direction": "CREDIT", "amount_vc": 1000, "reason_code": "REFUND",
                 "reference_id": entries[3]["id"]},
                LIVEOPS,
            )
        )
        return program, entries

    def test_projected_pool_counts_registered_but_unpaid_entries(self, api):
        """PRD §3.5: "Under the PROJECTED variant — used while registration is
        live — the pool is the sum of entry_fee_vc across entries in either
        REGISTERED or CONFIRMED status, so it optimistically includes
        registered-but-unpaid entries."

        Design: Difficulty/dual_variant_calc/prize_pool_projected_vs_final_variants
        """
        program, _ = self._setup_program_with_refunded_entry(api)
        rows, _ = __import__("test_helpers").validate_paginated(
            api_client.list_prize_rows(program["id"], LIVEOPS)
        )
        by_placement = {r["placement"]: r for r in rows}
        assert by_placement[1]["projected_amount_vc"] == 2400, (
            f"PROJECTED pool 4*1000=4000, floor(4000*6000/10000)=2400; "
            f"got {by_placement[1]['projected_amount_vc']}"
        )
        assert by_placement[2]["projected_amount_vc"] == 1600

    def test_final_pool_counts_confirmed_only_and_diverges(self, api):
        """PRD §3.5: "Under the FINAL variant — used at record-results — the
        pool counts only CONFIRMED entries." and "closing registration ...
        unpaid REGISTERED entries move to REFUNDED."

        Design: Difficulty/dual_variant_calc/prize_pool_projected_vs_final_variants
        """
        program, entries = self._setup_program_with_refunded_entry(api)
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
        rows, _ = __import__("test_helpers").validate_paginated(
            api_client.list_prize_rows(program["id"], LIVEOPS)
        )
        for row in rows:
            assert_tournament_prize(row)
        by_placement = {r["placement"]: r for r in rows}
        assert by_placement[1]["final_amount_vc"] == 1800, (
            f"FINAL pool 3*1000=3000, floor(3000*6000/10000)=1800; "
            f"got {by_placement[1]['final_amount_vc']}"
        )
        assert by_placement[2]["final_amount_vc"] == 1200
        assert by_placement[1]["projected_amount_vc"] != by_placement[1]["final_amount_vc"]

        entry4, _ = __import__("test_helpers").validate_paginated(
            api_client.list_tournament_entries(program["id"], LIVEOPS,
                                               params={"entry_status": "REFUNDED"})
        )
        assert any(e["id"] == entries[3]["id"] for e in entry4), (
            "entry 4 whose fee was refunded must be REFUNDED after close-registration"
        )
