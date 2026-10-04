"""Transitive cascade chains: offer-accept cascade and expansion cascade.

Design: Difficulty/transitive_cascade
"""
from test_helpers import (
    TEST_USERS, acquire_film_with_premiere, create_offer_payload,
    get_success_data, setup_film, setup_open_release_plan, setup_territory,
    validate_paginated, validate_success,
)

ACQ = TEST_USERS["acq_exec_headers"]
ACQ2 = TEST_USERS["acq_exec_2_headers"]
DIST = TEST_USERS["dist_exec_headers"]


class TestOfferAcceptCascade:
    def test_offer_accept_cascades_to_deal_rights_posture(self, api):
        """PRD §3.3: "The accepted offer transitions `OPEN → ACCEPTED`. Every
        sibling `OPEN` offer on the same film transitions `OPEN → REJECTED`. A
        new `AcquisitionDeal` is created in `EXECUTED` status, copying
        `film_id`, `source_offer_id` (the accepted offer's `id`),
        `buyer_code`, `upfront_price_cents`, `backend_participation_pct`, and
        `prints_advertising_commit_cents` from the accepted offer."
        PRD §3.3: "For each pair in the Cartesian product of the offer's
        `requested_territory_codes` and `requested_windows`, a `RightsGrant`
        is created on the deal in `GRANTED` status."
        PRD §3.3: "If any granted window is `THEATRICAL`, the film's
        `awards_posture` promotes `INELIGIBLE → ELIGIBLE`."

        Design: Difficulty/transitive_cascade/offer_accept_cascades_to_deal_rights_posture
        """
        setup_territory(code="US")
        setup_territory(code="FR", name="France")
        film = setup_film()
        offer = get_success_data(api.create_offer(
            film["id"],
            create_offer_payload(
                requested_territory_codes=["US", "FR"],
                requested_windows=["THEATRICAL", "HOME_ENT"],
            ),
            ACQ2,
        ))
        film_now = get_success_data(api.get_film(film["id"], ACQ))
        deal = validate_success(api.accept_offer(
            film["id"], offer["id"],
            {"expected_film_version": film_now["version"]}, ACQ,
        ), expected_status=201)

        film_after = get_success_data(api.get_film(film["id"], ACQ))
        assert film_after["acquisition_status"] == "ACQUIRED"
        # Posture flip is caused by the derived THEATRICAL rights grant
        assert film_after["awards_posture"] == "ELIGIBLE"

        assert deal["status"] == "EXECUTED"
        assert deal["source_offer_id"] == offer["id"]
        assert deal["film_id"] == film["id"]

        grants, meta = validate_paginated(
            api.list_deal_rights_grants(deal["id"], ACQ)
        )
        pairs = sorted((g["territory_code"], g["window"]) for g in grants)
        assert pairs == [
            ("FR", "HOME_ENT"), ("FR", "THEATRICAL"),
            ("US", "HOME_ENT"), ("US", "THEATRICAL"),
        ]
        assert all(g["status"] == "GRANTED" for g in grants)

        offer_after = get_success_data(
            api.get_offer(film["id"], offer["id"], ACQ)
        )
        assert offer_after["status"] == "ACCEPTED"

    def test_offer_accept_rejects_sibling_open_offers(self, api):
        """PRD §3.3: "Every sibling `OPEN` offer on the same film transitions
        `OPEN → REJECTED`."
        PRD §3.3: "The film's `acquisition_status` transitions
        `UNDER_NEGOTIATION → ACQUIRED`."

        Design: Difficulty/transitive_cascade/offer_accept_cascades_to_deal_rights_posture
        """
        setup_territory(code="US")
        film = setup_film()
        offer_a = get_success_data(api.create_offer(
            film["id"], create_offer_payload(buyer_code="A24"), ACQ2,
        ))
        # Sibling offer must be OPEN simultaneously: it cannot be created via
        # counter (that consumes the original), so open a second direct offer.
        offer_b = get_success_data(api.create_offer(
            film["id"], create_offer_payload(buyer_code="NEON"), ACQ2,
        ))

        film_now = get_success_data(api.get_film(film["id"], ACQ))
        validate_success(api.accept_offer(
            film["id"], offer_a["id"],
            {"expected_film_version": film_now["version"]}, ACQ,
        ), expected_status=201)

        a_after = get_success_data(api.get_offer(film["id"], offer_a["id"], ACQ))
        b_after = get_success_data(api.get_offer(film["id"], offer_b["id"], ACQ))
        assert a_after["status"] == "ACCEPTED"
        assert b_after["status"] == "REJECTED"

        film_after = get_success_data(api.get_film(film["id"], ACQ))
        assert film_after["acquisition_status"] == "ACQUIRED"


class TestExpansionCascade:
    def test_report_market_screening_cascades_to_plan_expansion_and_film_wide(self, api):
        """PRD §3.5: "If the new `per_screen_avg_cents` is greater than or
        equal to the plan's `expansion_threshold_psa_cents`, and the plan's
        `platform_strategy` is not `WIDE_DIRECT`, and the plan is currently
        `OPENED`, then the plan transitions `OPENED → EXPANDING` and the
        triggering screening transitions `REPORTED → EXPANSION_TRIGGERED`.
        Independently, while the plan is `EXPANDING`, if the plan's
        `current_screen_count` — the sum of `screen_count` across the plan's
        non-`PULLED` market screenings — reaches 600 or more, the plan
        transitions `EXPANDING → WIDE` and the film's `release_posture`
        promotes to `WIDE`."

        Design: Difficulty/transitive_cascade/report_market_screening_cascades_to_plan_expansion_and_film_wide
        """
        film, offer, deal, festival, slot = acquire_film_with_premiere()
        plan, screenings = setup_open_release_plan(
            film, deal, target_market_codes=("NY",),
        )
        scr_ny = screenings["NY"]

        # NY weekend 1: 50,000 / 4 = 12,500 >= 10,000 -> EXPANDING
        reported = validate_success(api.report_market_screening(
            plan["id"], scr_ny["id"],
            {"screen_count": 4, "weekend_gross_cents": 50_000}, DIST,
        ))
        assert reported["per_screen_avg_cents"] == 12_500
        assert reported["status"] == "EXPANSION_TRIGGERED"

        plan_after_1 = get_success_data(api.get_release_plan(plan["id"], DIST))
        assert plan_after_1["status"] == "EXPANDING"

        # LA weekend 2: 700 screens -> cumulative 704 >= 600 -> WIDE
        scr_la = get_success_data(api.schedule_market_screening(
            plan["id"],
            {"market_code": "LA", "weekend_index": 2,
             "screen_count": 700, "weekend_gross_cents": 0},
            DIST,
        ))
        validate_success(api.report_market_screening(
            plan["id"], scr_la["id"],
            {"screen_count": 700, "weekend_gross_cents": 1_000_000}, DIST,
        ))

        plan_after_2 = get_success_data(api.get_release_plan(plan["id"], DIST))
        assert plan_after_2["status"] == "WIDE"
        assert plan_after_2["current_screen_count"] == 704
        assert plan_after_2["cumulative_gross_cents"] == 1_050_000

        film_after = get_success_data(api.get_film(film["id"], DIST))
        assert film_after["release_posture"] == "WIDE"

    def test_report_below_threshold_leaves_plan_opened(self, api):
        """PRD §3.5: "If the new `per_screen_avg_cents` is greater than or
        equal to the plan's `expansion_threshold_psa_cents`... then the plan
        transitions `OPENED → EXPANDING`" — a report below the threshold does
        not trigger the cascade, and the screening simply becomes REPORTED.
        PRD §3.5: "the parent plan's `cumulative_gross_cents` and
        `current_screen_count` are recomputed across all of the plan's
        non-`PULLED` market screenings."

        Design: Difficulty/transitive_cascade/report_market_screening_cascades_to_plan_expansion_and_film_wide
        """
        film, offer, deal, festival, slot = acquire_film_with_premiere()
        plan, screenings = setup_open_release_plan(
            film, deal, target_market_codes=("NY",),
        )
        scr_ny = screenings["NY"]

        # 30,000 / 5 = 6,000 < 10,000 threshold -> no expansion
        reported = validate_success(api.report_market_screening(
            plan["id"], scr_ny["id"],
            {"screen_count": 5, "weekend_gross_cents": 30_000}, DIST,
        ))
        assert reported["per_screen_avg_cents"] == 6_000
        assert reported["status"] == "REPORTED"

        plan_after = get_success_data(api.get_release_plan(plan["id"], DIST))
        assert plan_after["status"] == "OPENED"
        assert plan_after["current_screen_count"] == 5
        assert plan_after["cumulative_gross_cents"] == 30_000

        film_after = get_success_data(api.get_film(film["id"], DIST))
        assert film_after["release_posture"] == "PLATFORM"
