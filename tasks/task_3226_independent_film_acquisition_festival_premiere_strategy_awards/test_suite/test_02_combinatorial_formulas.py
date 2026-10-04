"""Combinatorial formulas: premiere cachet multi-input and spend caps.

Design: Difficulty/combinatorial_formula
"""
from test_helpers import (
    TEST_USERS, acquire_film, acquire_film_with_premiere,
    create_awards_campaign_payload, get_success_data, setup_active_campaign,
    setup_festival, setup_film, setup_premiere_slot, setup_territory,
    validate_success,
)

PROG = TEST_USERS["festival_prog_headers"]
STRAT = TEST_USERS["awards_strat_headers"]


class TestPremiereCachetMultiInput:
    def test_premiere_cachet_multi_input_tiered_embargo(self, api):
        """PRD §3.4: "The base is the prestige points of the festival's tier —
        `A_LIST` contributes 100, `B_LIST` contributes 60, and `REGIONAL`
        contributes 30. Added to the base is a section bonus — `COMPETITION`
        contributes 40, `PREMIERES` contributes 25, `MIDNIGHT` contributes 15,
        and `NEXT` contributes 10. The summed base plus bonus is then
        multiplied by an embargo multiplier chosen by the embargo delay in
        whole hours: a delay of at most 12 hours multiplies by 1.25, a delay
        strictly greater than 12 hours and at most 48 hours multiplies by 1.00,
        and a delay strictly greater than 48 hours multiplies by 0.75. The
        product is rounded half-up to an integer and stored."

        Design: Difficulty/combinatorial_formula/premiere_cachet_multi_input_tiered_embargo
        """
        film = setup_film(title="Combinatorics")
        fest_a = setup_festival(
            code="CANNES", name="Cannes", prestige_tier="A_LIST",
            start_date="2027-05-12T00:00:00Z", end_date="2027-05-23T00:00:00Z",
        )
        fest_b = setup_festival(
            code="TIFF", name="Toronto", prestige_tier="B_LIST",
            start_date="2027-09-09T00:00:00Z", end_date="2027-09-19T00:00:00Z",
        )
        fest_r = setup_festival(
            code="SXSW", name="South By Southwest", prestige_tier="REGIONAL",
            start_date="2027-03-12T00:00:00Z", end_date="2027-03-20T00:00:00Z",
        )

        # (100 + 40) * 1.25 = 175  — A_LIST / COMPETITION / 6h
        s1 = setup_premiere_slot(
            fest_a["id"], section="COMPETITION",
            screening_starts_at="2027-05-15T20:00:00Z",
            screening_ends_at="2027-05-15T22:00:00Z",
            review_embargo_lifts_at="2027-05-16T04:00:00Z",
        )
        # (100 + 25) * 1.00 = 125  — A_LIST / PREMIERES / 24h
        s2 = setup_premiere_slot(
            fest_a["id"], section="PREMIERES",
            screening_starts_at="2027-05-16T20:00:00Z",
            screening_ends_at="2027-05-16T22:00:00Z",
            review_embargo_lifts_at="2027-05-17T22:00:00Z",
        )
        # (60 + 15) * 0.75 = 56.25 -> 56 — B_LIST / MIDNIGHT / 96h
        s3 = setup_premiere_slot(
            fest_b["id"], section="MIDNIGHT",
            screening_starts_at="2027-09-12T23:00:00Z",
            screening_ends_at="2027-09-13T01:00:00Z",
            review_embargo_lifts_at="2027-09-17T01:00:00Z",
        )
        # (30 + 10) * 1.25 = 50 — REGIONAL / NEXT / 6h
        s4 = setup_premiere_slot(
            fest_r["id"], section="NEXT",
            screening_starts_at="2027-03-14T20:00:00Z",
            screening_ends_at="2027-03-14T22:00:00Z",
            review_embargo_lifts_at="2027-03-15T04:00:00Z",
        )

        held1 = validate_success(api.hold_premiere_slot(
            fest_a["id"], s1["id"], {"film_id": film["id"]}, PROG,
        ))
        held2 = validate_success(api.hold_premiere_slot(
            fest_a["id"], s2["id"], {"film_id": film["id"]}, PROG,
        ))
        held3 = validate_success(api.hold_premiere_slot(
            fest_b["id"], s3["id"], {"film_id": film["id"]}, PROG,
        ))
        held4 = validate_success(api.hold_premiere_slot(
            fest_r["id"], s4["id"], {"film_id": film["id"]}, PROG,
        ))

        assert held1["cachet_score"] == 175
        assert held2["cachet_score"] == 125
        assert held3["cachet_score"] == 56
        assert held4["cachet_score"] == 50

    def test_premiere_cachet_embargo_tier_mid_band(self, api):
        """PRD §3.4: "a delay strictly greater than 12 hours and at most 48
        hours multiplies by 1.00" — mid-band combination with B_LIST base and
        MIDNIGHT bonus.

        Design: Difficulty/combinatorial_formula/premiere_cachet_multi_input_tiered_embargo
        """
        film = setup_film(title="MidBand")
        fest = setup_festival(code="TELLURIDE", name="Telluride",
                              prestige_tier="B_LIST")
        # (60 + 15) * 1.00 = 75 — 48h delay exactly on the upper tier boundary
        slot = setup_premiere_slot(
            fest["id"], section="MIDNIGHT",
            screening_starts_at="2027-01-22T20:00:00Z",
            screening_ends_at="2027-01-22T22:00:00Z",
            review_embargo_lifts_at="2027-01-24T22:00:00Z",
        )
        held = validate_success(api.hold_premiere_slot(
            fest["id"], slot["id"], {"film_id": film["id"]}, PROG,
        ))
        assert held["cachet_score"] == 75


class TestCampaignEligibleSpendCaps:
    def test_campaign_eligible_spend_cap_constraint_propagation(self, api):
        """PRD §3.7: "Each `category` carries a cap expressed as a fraction of
        the parent campaign's `budget_total_cents`: ... `PUBLICITY` at 30
        percent... If the prior eligible sum plus the new full amount would
        exceed the cap, the eligible amount for the new spend is reduced to
        the cap minus the prior sum, floored at zero."
        PRD §3.7: "the parent campaign's `budget_screenings_cents`,
        `budget_mailers_cents`, or `budget_publicity_cents` is incremented for
        the matching category..., and `budget_remaining_cents` is recomputed
        as `budget_total_cents` minus the sum of all `amount_cents` across the
        campaign's spends."

        Design: Difficulty/combinatorial_formula/campaign_eligible_spend_cap_constraint_propagation
        """
        film, deal, festival, slot, campaign = (
            _premiered_with_campaign(api, budget_total_cents=2_000_000)
        )
        # PUBLICITY cap = 0.30 * 2,000,000 = 600,000

        spend_1 = validate_success(api.create_campaign_spend(
            campaign["id"],
            {"category": "PUBLICITY", "amount_cents": 500_000,
             "incurred_at": "2026-10-01T00:00:00Z",
             "target_category": "BEST_PICTURE"},
            STRAT,
        ), expected_status=201)
        spend_2 = validate_success(api.create_campaign_spend(
            campaign["id"],
            {"category": "PUBLICITY", "amount_cents": 200_000,
             "incurred_at": "2026-10-05T00:00:00Z",
             "target_category": "BEST_PICTURE"},
            STRAT,
        ), expected_status=201)
        spend_3 = validate_success(api.create_campaign_spend(
            campaign["id"],
            {"category": "PUBLICITY", "amount_cents": 100_000,
             "incurred_at": "2026-10-10T00:00:00Z",
             "target_category": "BEST_PICTURE"},
            STRAT,
        ), expected_status=201)

        assert spend_1["eligible_amount_cents"] == 500_000
        # Cap 600,000 - prior 500,000 -> 100,000 eligible out of 200,000
        assert spend_2["eligible_amount_cents"] == 100_000
        # Cap exhausted -> 0
        assert spend_3["eligible_amount_cents"] == 0

        campaign_after = get_success_data(
            api.get_awards_campaign(campaign["id"], STRAT)
        )
        # budget_publicity tracks full amounts, not eligible amounts
        assert campaign_after["budget_publicity_cents"] == 800_000
        assert campaign_after["budget_remaining_cents"] == 1_200_000

    def test_campaign_eligible_spend_indie_travel_disallowance(self, api):
        """PRD §3.7: "when the parent campaign's `awards_body` is
        `INDEPENDENT_SPIRIT` and the spend's `category` is `TRAVEL`, the
        eligible amount is additionally clamped to a maximum of 250,000
        dollars (25,000,000 cents)."

        Design: Difficulty/combinatorial_formula/campaign_eligible_spend_cap_constraint_propagation
        """
        film, _offer, deal, festival, slot = acquire_film_with_premiere()
        # Budget 300,000,000 cents ($3M): TRAVEL cap = 0.15 * 300M = 45M,
        # above the Indie Spirit $250k disallowance cap.
        campaign = setup_active_campaign(
            film, deal,
            {"awards_body": "INDEPENDENT_SPIRIT",
             "budget_total_cents": 300_000_000},
        )
        spend = validate_success(api.create_campaign_spend(
            campaign["id"],
            {"category": "TRAVEL", "amount_cents": 30_000_000,
             "incurred_at": "2026-10-01T00:00:00Z"},
            STRAT,
        ), expected_status=201)
        assert spend["eligible_amount_cents"] == 25_000_000


def _premiered_with_campaign(api, budget_total_cents):
    """Acquired film + booked premiere + ACTIVE OSCARS campaign."""
    film, _offer, deal, festival, slot = acquire_film_with_premiere()
    campaign = setup_active_campaign(
        film, deal, {"budget_total_cents": budget_total_cents},
    )
    return film, deal, festival, slot, campaign
