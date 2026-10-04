"""Compensating-action invariants: budget conservation and open-offer pool.

Design: Difficulty/compensating_invariant
"""
from test_helpers import (
    TEST_USERS, acquire_film_with_premiere, create_offer_payload,
    create_talent_obligation_payload, get_success_data, setup_active_campaign,
    setup_film_with_offer, validate_paginated, validate_success,
)

ACQ = TEST_USERS["acq_exec_headers"]
STRAT = TEST_USERS["awards_strat_headers"]
COORD = TEST_USERS["talent_coord_headers"]


class TestCampaignSpendThenWaiveConservesBudget:
    def test_campaign_spend_then_waive_leaves_budget_conserved(self, api):
        """PRD §3.7: "`budget_remaining_cents` is recomputed as
        `budget_total_cents` minus the sum of all `amount_cents` across the
        campaign's spends."
        PRD §3.8: "Either a `REQUESTED` or `CONFIRMED` obligation may be
        waived by an `AwardsStrategist`, transitioning it to `WAIVED`." — a
        waive is not a refund and must not change the budget.

        Design: Difficulty/compensating_invariant/campaign_spend_then_waive_leaves_budget_conserved
        """
        film, offer, deal, festival, slot = acquire_film_with_premiere()
        campaign = setup_active_campaign(
            film, deal, {"budget_total_cents": 1_000_000},
        )
        ob1 = get_success_data(api.create_talent_obligation(
            film["id"],
            create_talent_obligation_payload(campaign_id=campaign["id"]),
            COORD,
        ))
        validate_success(api.confirm_talent_obligation(film["id"], ob1["id"], COORD))

        validate_success(api.create_campaign_spend(
            campaign["id"],
            {"category": "PUBLICITY", "amount_cents": 300_000,
             "incurred_at": "2026-10-01T00:00:00Z",
             "target_category": "BEST_PICTURE"},
            STRAT,
        ), expected_status=201)

        after_spend = get_success_data(
            api.get_awards_campaign(campaign["id"], STRAT)
        )
        assert after_spend["budget_remaining_cents"] == 700_000
        assert after_spend["budget_publicity_cents"] == 300_000

        waived = validate_success(
            api.waive_talent_obligation(film["id"], ob1["id"], STRAT)
        )
        assert waived["status"] == "WAIVED"

        after_waive = get_success_data(
            api.get_awards_campaign(campaign["id"], STRAT)
        )
        # The waive does not refund: budget is unchanged from post-spend
        assert after_waive["budget_remaining_cents"] == 700_000
        assert (after_waive["budget_remaining_cents"] + 300_000
                == after_waive["budget_total_cents"])

    def test_budget_remaining_invariant_holds_across_multiple_spends(self, api):
        """PRD §3.7: "`budget_remaining_cents` is recomputed as
        `budget_total_cents` minus the sum of all `amount_cents` across the
        campaign's spends." — the conserved quantity holds at every point.

        Design: Difficulty/compensating_invariant/campaign_spend_then_waive_leaves_budget_conserved
        """
        film, offer, deal, festival, slot = acquire_film_with_premiere()
        campaign = setup_active_campaign(
            film, deal, {"budget_total_cents": 1_000_000},
        )

        total_spent = 0
        for amount, category in ((100_000, "SCREENING"), (150_000, "GUILD_MAILER")):
            validate_success(api.create_campaign_spend(
                campaign["id"],
                {"category": category, "amount_cents": amount,
                 "incurred_at": "2026-10-01T00:00:00Z"},
                STRAT,
            ), expected_status=201)
            total_spent += amount
            snap = get_success_data(
                api.get_awards_campaign(campaign["id"], STRAT)
            )
            assert snap["budget_remaining_cents"] == 1_000_000 - total_spent


class TestOfferCounterWithdrawConservesOpenPool:
    def test_offer_counter_then_withdraw_leaves_open_offer_count_conserved(self, api):
        """PRD §3.2: "The original offer transitions `OPEN → COUNTERED`, and a
        fresh offer is minted on the same film in `OPEN` status with
        `round_number` equal to the prior round plus one." — countering
        preserves the OPEN-offer count at exactly one.
        PRD §3.3: "if, after the transition, no `OPEN` offer remains on the
        film and no `EXECUTED` or `IN_RELEASE` deal exists, the film's
        `acquisition_status` collapses `UNDER_NEGOTIATION → SHOPPING`".

        Design: Difficulty/compensating_invariant/offer_counter_then_withdraw_leaves_open_offer_count_conserved
        """
        film, o1 = setup_film_with_offer()
        film_id = film["id"]

        o2 = validate_success(api.counter_offer(
            film_id, o1["id"], create_offer_payload(upfront_price_cents=6_000_000),
            ACQ,
        ), expected_status=201)

        # Counter preserves the OPEN pool: one COUNTERED out, one OPEN in
        open_rows, _ = validate_paginated(
            api.list_offers(film_id, ACQ, params={"status": "OPEN"})
        )
        countered_rows, _ = validate_paginated(
            api.list_offers(film_id, ACQ, params={"status": "COUNTERED"})
        )
        assert [o["id"] for o in open_rows] == [o2["id"]]
        assert [o["id"] for o in countered_rows] == [o1["id"]]

        film_mid = get_success_data(api.get_film(film_id, ACQ))
        assert film_mid["acquisition_status"] == "UNDER_NEGOTIATION"

        validate_success(api.withdraw_offer(film_id, o2["id"], ACQ))

        open_rows_end, _ = validate_paginated(
            api.list_offers(film_id, ACQ, params={"status": "OPEN"})
        )
        assert len(open_rows_end) == 0

        film_end = get_success_data(api.get_film(film_id, ACQ))
        # Conserved: identical to the initial state before any negotiation
        assert film_end["acquisition_status"] == "SHOPPING"

        deals, _ = validate_paginated(api.list_film_deals(film_id, ACQ))
        assert len(deals) == 0

    def test_offer_counter_reject_last_open_also_reverts_to_shopping(self, api):
        """PRD §3.3: "An `AcquisitionExec` may reject an `OPEN` offer,
        transitioning it `OPEN → REJECTED`... if, after the transition, no
        `OPEN` offer remains on the film and no `EXECUTED` or `IN_RELEASE`
        deal exists, the film's `acquisition_status` collapses
        `UNDER_NEGOTIATION → SHOPPING` and the film's `version` increments by
        1."

        Design: Difficulty/compensating_invariant/offer_counter_then_withdraw_leaves_open_offer_count_conserved
        """
        film, o1 = setup_film_with_offer()
        film_id = film["id"]

        o2 = validate_success(api.counter_offer(
            film_id, o1["id"], create_offer_payload(), ACQ,
        ), expected_status=201)
        film_mid = get_success_data(api.get_film(film_id, ACQ))
        assert film_mid["acquisition_status"] == "UNDER_NEGOTIATION"

        validate_success(api.reject_offer(film_id, o2["id"], ACQ))

        open_rows, _ = validate_paginated(
            api.list_offers(film_id, ACQ, params={"status": "OPEN"})
        )
        assert len(open_rows) == 0
        film_end = get_success_data(api.get_film(film_id, ACQ))
        assert film_end["acquisition_status"] == "SHOPPING"
