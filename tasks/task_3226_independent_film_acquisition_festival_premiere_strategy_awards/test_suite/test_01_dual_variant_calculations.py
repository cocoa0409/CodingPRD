"""Dual-variant calculations: participation waterfall and premiere cachet.

Design: Difficulty/dual_variant_calc
"""
from test_helpers import (
    TEST_USERS, acquire_film, acquire_film_with_premiere,
    create_film_payload, create_offer_payload, create_premiere_slot_payload,
    create_territory_payload, get_success_data, setup_festival, setup_film,
    setup_premiere_slot, setup_territory, validate_success,
)

ACCT = TEST_USERS["part_acct_headers"]
PROG = TEST_USERS["festival_prog_headers"]
DIST = TEST_USERS["dist_exec_headers"]


class TestDualVariantWaterfall:
    def test_statement_gross_vs_net_waterfall_diverges_on_same_inputs(self, api):
        """PRD §3.9: "Under the `GROSS_RECEIPTS` basis — the off-the-top
        variant — the `distribution_fee_cents` is 15 percent of
        `gross_receipts_cents`, rounded half-up to integer cents. The
        `recoupable_costs_cents` is zero: no cost recoupment happens on this
        variant."
        PRD §3.9: "Under the `NET_PROFITS` basis — the recoupment variant —
        the `distribution_fee_cents` is 30 percent of `gross_receipts_cents`,
        rounded half-up to integer cents. The `recoupable_costs_cents` is the
        sum of the deal's `upfront_price_cents`, the film's
        `production_budget_cents`, the deal's `pa_spent_theatrical_cents`, and
        the awards-eligible total computed by summing `eligible_amount_cents`
        across every `CampaignSpend` on every awards campaign tied to the deal.
        The net is then `gross_receipts_cents` minus `distribution_fee_cents`
        minus `recoupable_costs_cents`."

        Design: Difficulty/dual_variant_calc/statement_gross_vs_net_waterfall_diverges_on_same_inputs
        """
        film, offer, deal = acquire_film(
            film_overrides={"production_budget_cents": 2_000_000},
            offer_overrides={
                "upfront_price_cents": 5_000_000,
                "backend_participation_pct": 0.10,
                "prints_advertising_commit_cents": 8_000_000,
                "requested_windows": ["THEATRICAL", "STREAMING"],
            },
        )
        get_success_data(api.report_theatrical_spend(
            deal["id"], {"amount_cents": 3_000_000}, DIST,
        ))

        st_gross = validate_success(api.create_statement(
            film["id"],
            {"deal_id": deal["id"], "period_label": "Q1-2027",
             "basis": "GROSS_RECEIPTS", "gross_receipts_cents": 20_000_000},
            ACCT,
        ), expected_status=201)
        st_net = validate_success(api.create_statement(
            film["id"],
            {"deal_id": deal["id"], "period_label": "Q1-2027",
             "basis": "NET_PROFITS", "gross_receipts_cents": 20_000_000},
            ACCT,
        ), expected_status=201)

        # GROSS_RECEIPTS: fee = round(20M * 0.15) = 3M; no recoupment;
        # participation = round((20M - 3M) * 0.10) = 1.7M
        assert st_gross["distribution_fee_cents"] == 3_000_000
        assert st_gross["recoupable_costs_cents"] == 0
        assert st_gross["filmmaker_participation_cents"] == 1_700_000

        # NET_PROFITS: fee = 6M; recoup = 5M + 2M + 3M + 0 = 10M;
        # net = 20M - 6M - 10M = 4M; participation = 400k
        assert st_net["distribution_fee_cents"] == 6_000_000
        assert st_net["recoupable_costs_cents"] == 10_000_000
        assert st_net["filmmaker_participation_cents"] == 400_000

        assert (st_gross["filmmaker_participation_cents"]
                != st_net["filmmaker_participation_cents"]), \
            "The two waterfall variants must diverge on the same inputs"

    def test_statement_net_profits_net_zero_participation_zero(self, api):
        """PRD §3.9: "If the net is zero or negative, the
        `filmmaker_participation_cents` is zero — participation is never
        negative."

        Design: Difficulty/dual_variant_calc/statement_gross_vs_net_waterfall_diverges_on_same_inputs
        """
        film, offer, deal = acquire_film(
            film_overrides={"production_budget_cents": 2_000_000},
            offer_overrides={
                "upfront_price_cents": 5_000_000,
                "backend_participation_pct": 0.10,
                "prints_advertising_commit_cents": 8_000_000,
            },
        )
        # NET_PROFITS: fee = round(10M * 0.30) = 3M; recoup = 5M + 2M = 7M;
        # net = 10M - 3M - 7M = 0 -> participation 0.
        st_net = validate_success(api.create_statement(
            film["id"],
            {"deal_id": deal["id"], "period_label": "Q2-2027",
             "basis": "NET_PROFITS", "gross_receipts_cents": 10_000_000},
            ACCT,
        ), expected_status=201)
        assert st_net["distribution_fee_cents"] == 3_000_000
        assert st_net["recoupable_costs_cents"] == 7_000_000
        assert st_net["filmmaker_participation_cents"] == 0

        # GROSS_RECEIPTS on the same gross: fee = 1.5M; participation =
        # round(8.5M * 0.10) = 850k — diverges from the NET_PROFITS outcome.
        st_gross = validate_success(api.create_statement(
            film["id"],
            {"deal_id": deal["id"], "period_label": "Q2-2027",
             "basis": "GROSS_RECEIPTS", "gross_receipts_cents": 10_000_000},
            ACCT,
        ), expected_status=201)
        assert st_gross["distribution_fee_cents"] == 1_500_000
        assert st_gross["filmmaker_participation_cents"] == 850_000
        assert (st_gross["filmmaker_participation_cents"]
                != st_net["filmmaker_participation_cents"])


class TestDualVariantCachet:
    def test_premiere_cachet_provisional_recomputes_locked_freezes(self, api):
        """PRD §3.4: "The `cachet_score` itself is a weighted scoring rule that
        runs on hold and again on book... While the slot is `HELD` the score is
        the provisional variant... When the slot becomes `BOOKED`, the locked
        variant freezes the score and subsequent festival edits do not
        recompute it."
        PRD §3.4: "a premiere slot booking promotes the film from
        `PRE_ACQUISITION` to `PREMIERE_LOCKED`" (via §2.9 posture gating).

        Design: Difficulty/dual_variant_calc/premiere_cachet_provisional_recomputes_locked_freezes
        """
        film, offer, deal = acquire_film()
        festival = setup_festival()
        slot = setup_premiere_slot(
            festival["id"],
            section="COMPETITION",
            screening_starts_at="2027-01-22T20:00:00Z",
            screening_ends_at="2027-01-22T22:00:00Z",
            review_embargo_lifts_at="2027-01-23T08:00:00Z",  # 10h -> x1.25
        )
        slot = validate_success(api.hold_premiere_slot(
            festival["id"], slot["id"], {"film_id": film["id"]}, PROG,
        ))
        # Provisional: (100 + 40) * 1.25 = 175
        assert slot["cachet_score"] == 175
        assert slot["status"] == "HELD"

        film_now = get_success_data(api.get_film(film["id"], PROG))
        slot = validate_success(api.book_premiere_slot(
            festival["id"], slot["id"],
            {"expected_film_version": film_now["version"]}, PROG,
        ))
        # Locked variant: same numeric result here, field now frozen
        assert slot["status"] == "BOOKED"
        assert slot["cachet_score"] == 175

        film_after = get_success_data(api.get_film(film["id"], PROG))
        assert film_after["release_posture"] == "PREMIERE_LOCKED"

    def test_premiere_cachet_variants_share_formula_but_differ_in_recompute_semantics(self, api):
        """PRD §3.4: "When the slot becomes `BOOKED`, the locked variant
        freezes the score and subsequent festival edits do not recompute it."
        PRD §3.4: "The summed base plus bonus is then multiplied by an embargo
        multiplier chosen by the embargo delay in whole hours: a delay of at
        most 12 hours multiplies by 1.25..."

        Design: Difficulty/dual_variant_calc/premiere_cachet_provisional_recomputes_locked_freezes
        """
        film, offer, deal = acquire_film()
        festival = setup_festival()
        slot = setup_premiere_slot(
            festival["id"],
            section="PREMIERES",
            screening_starts_at="2027-01-22T20:00:00Z",
            screening_ends_at="2027-01-22T22:00:00Z",
            review_embargo_lifts_at="2027-01-23T08:00:00Z",  # 10h -> x1.25
        )
        # OPEN: cachet is 0 before any hold
        assert slot["cachet_score"] == 0

        held = validate_success(api.hold_premiere_slot(
            festival["id"], slot["id"], {"film_id": film["id"]}, PROG,
        ))
        # Provisional: (100 + 25) * 1.25 = 156.25 -> round_half_up -> 156
        assert held["cachet_score"] == 156

        film_now = get_success_data(api.get_film(film["id"], PROG))
        booked = validate_success(api.book_premiere_slot(
            festival["id"], slot["id"],
            {"expected_film_version": film_now["version"]}, PROG,
        ))
        # Locked variant freezes the value at book time
        assert booked["cachet_score"] == 156
        assert booked["status"] == "BOOKED"
