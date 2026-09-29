"""The settlement waterfall and the artist rescoring it triggers: the two deal-type
payout variants, the pinned order in which the production surcharge is derived from
the payout, and the two strategy bases that rewrite an artist's draw score."""

import pytest

from test_helpers.assertions import (
    assert_artist,
    assert_settlement,
    assert_show_booking,
    assert_sponsorship_activation,
)
from test_helpers.constants import CANONICAL_CLOCK_UTC
from test_helpers.fixtures import (
    add_rider_item,
    add_ticket_scale,
    announce_booking,
    approve_settlement,
    complete_advance,
    confirm_activation,
    create_activation,
    create_agent,
    create_artist,
    create_edition,
    create_sponsor,
    create_stage,
    get_artist,
    get_booking,
    mark_performed,
    open_settlement,
    record_sales_batch,
    rule_rider_item,
    set_clock,
    setup_accepted_booking,
    setup_announced_booking,
    setup_base_world,
    submit_settlement,
)
from test_helpers.test_users import make_talent_agent_headers

# One reserved tier of two thousand seats at 62.95 dollars face, unbundled, with a
# four-dollar facility fee the patron pays on top of face value.
RESERVED_TIER_2000 = {
    "seating_type": "RESERVED",
    "tier_name": "GOLD",
    "face_price_cents": 6295,
    "allotment_seats": 2000,
    "bundled_with_gate_admission": False,
    "facility_fee_cents": 400,
}

# The merchandise stand was staffed by the artist and took nine thousand dollars.
FINAL_ARTIST_MERCH = {
    "basis": "FINAL",
    "merch_gross_cents": 900000,
    "merch_seller": "ARTIST",
}

# The second show of the run sits three days after the first one on the same stage.
SECOND_SHOW_SCHEDULE = {
    "target_show_date": "2026-08-25",
    "load_in_start_utc": "2026-08-25T14:00:00.000Z",
    "load_out_end_utc": "2026-08-25T23:00:00.000Z",
}
SECOND_SHOW_DOORS_UTC = "2026-08-25T18:00:00.000Z"
CLOCK_AFTER_BOTH_SHOWS_UTC = "2026-08-25T23:30:00.000Z"
CLOCK_AFTER_ONE_SHOW_UTC = "2026-08-22T23:30:00.000Z"


def _sell_reserved_tier(scenario, quantity):
    """Report one online sale batch against the show's single reserved tier."""
    record_sales_batch(scenario["ticket_scale"]["id"], quantity=quantity)


def _two_shows_differing_only_in_deal_type():
    """Two shows of one edition with identical box office and opposite deal types.

    Both acts are on the same agent's roster, both sell 1800 of 2000 reserved
    seats online before doors, and both advances close with every rider line
    approved at zero cost, so the only difference between the pair is the deal
    type pinned onto each booking at acceptance.
    """
    world = setup_base_world()
    versus = setup_announced_booking(
        world, scale_overrides=RESERVED_TIER_2000, deal_type="VERSUS"
    )
    _sell_reserved_tier(versus, 1800)

    second_world = dict(world)
    second_world["artist"] = create_artist(
        world["agent"]["id"],
        name="Nine Volt Sermon",
        genre="ROCK",
        audience_segment="YOUNG_ADULT",
    )
    backend = setup_announced_booking(
        second_world,
        scale_overrides=RESERVED_TIER_2000,
        doors_time_utc=SECOND_SHOW_DOORS_UTC,
        deal_type="GUARANTEE_PLUS_BACKEND",
        **SECOND_SHOW_SCHEDULE,
    )
    _sell_reserved_tier(backend, 1800)

    set_clock(CLOCK_AFTER_BOTH_SHOWS_UTC)
    for scenario in (versus, backend):
        scenario["booking"] = mark_performed(scenario["booking"]["id"])
        draft = open_settlement(scenario["booking"]["id"], **FINAL_ARTIST_MERCH)
        scenario["settlement"] = submit_settlement(draft["id"])
    return versus, backend


class TestPayoutVariantByDealType:
    """The payout step reads the deal type pinned onto the booking at acceptance."""

    def test_versus_show_settles_to_the_guarantee_floor(self):
        """On a versus deal the artist takes the greater of the standing guarantee
        and the artist's share of the provisional net pool, so a pool of 8179468
        cents split at 0.85 loses to the 12500000-cent guarantee floor.

        "Under a `VERSUS` deal the artist takes whichever is greater of the `agreed_guarantee_cents` and the provisional net pool multiplied by `agreed_backend_split_pct` rounded half up"

        Design: Difficulty/dual_variant_calc/settlement_payout_versus_vs_guarantee_plus_backend
        """
        versus, _backend = _two_shows_differing_only_in_deal_type()

        settlement = versus["settlement"]
        assert_settlement(settlement)
        assert settlement["status"] == "PENDING_APPROVAL"
        assert settlement["adjusted_gross_cents"] == 10679468
        assert settlement["provisional_net_pool_cents"] == 8179468
        assert settlement["artist_payout_cents"] == 12500000
        assert settlement["production_surcharge_cents"] == 437500
        assert settlement["net_pool_cents"] == 7741968
        assert settlement["total_artist_settlement_cents"] == 13220000

    def test_guarantee_plus_backend_show_settles_to_guarantee_plus_overage_share(self):
        """On a guarantee-plus-backend deal the artist keeps the guarantee and adds
        its share of the pool above breakeven, so the same 8179468-cent pool pays
        1852548 cents of overage on top of the 12500000-cent guarantee.

        "Under a `GUARANTEE_PLUS_BACKEND` deal the artist takes the `agreed_guarantee_cents` plus a share of the overage"

        Design: Difficulty/dual_variant_calc/settlement_payout_versus_vs_guarantee_plus_backend
        """
        _versus, backend = _two_shows_differing_only_in_deal_type()

        settlement = backend["settlement"]
        assert_settlement(settlement)
        assert settlement["status"] == "PENDING_APPROVAL"
        assert settlement["adjusted_gross_cents"] == 10679468
        assert settlement["provisional_net_pool_cents"] == 8179468
        assert settlement["artist_payout_cents"] == 14352548
        assert settlement["production_surcharge_cents"] == 502339
        assert settlement["net_pool_cents"] == 7677129
        assert settlement["total_artist_settlement_cents"] == 15072548

    def test_identical_box_office_diverges_only_through_the_pinned_deal_type(self):
        """Two shows with byte-identical adjusted gross and provisional net pool
        settle to different payouts, and the divergence of 1852548 cents follows
        the payout down the waterfall into the surcharge and the net pool.

        "This depends on the deal type pinned onto the booking at acceptance."

        Design: Difficulty/dual_variant_calc/settlement_payout_versus_vs_guarantee_plus_backend
        """
        versus, backend = _two_shows_differing_only_in_deal_type()

        first, second = versus["settlement"], backend["settlement"]
        assert versus["booking"]["agreed_deal_type"] == "VERSUS"
        assert backend["booking"]["agreed_deal_type"] == "GUARANTEE_PLUS_BACKEND"
        assert first["adjusted_gross_cents"] == second["adjusted_gross_cents"] == 10679468
        assert (
            first["provisional_net_pool_cents"]
            == second["provisional_net_pool_cents"]
            == 8179468
        )
        assert second["artist_payout_cents"] - first["artist_payout_cents"] == 1852548
        assert first["net_pool_cents"] == 7741968
        assert second["net_pool_cents"] == 7677129
        assert first["total_artist_settlement_cents"] == 13220000
        assert second["total_artist_settlement_cents"] == 15072548


def _two_editions_on_opposite_strategy_bases():
    """One show per edition, identical in every respect but the edition's basis.

    Each edition runs the same dates on its own stage, each act carries a
    base draw score of 62.50, and each show sells 1800 of its 2000 reserved
    seats and settles on the final basis, so both settlements land on the same
    net pool and both bookings on the same sell-through.
    """
    set_clock(CANONICAL_CLOCK_UTC)
    attendance_edition = create_edition(
        name="Attendance Basis Fair", strategy_basis="ATTENDANCE_WEIGHTED"
    )
    revenue_edition = create_edition(
        year=2027, name="Revenue Basis Fair", strategy_basis="REVENUE_WEIGHTED"
    )
    attendance_stage = create_stage(attendance_edition["id"], name="Grandstand A")
    revenue_stage = create_stage(revenue_edition["id"], name="Grandstand B")
    agent = create_agent()
    agent_headers = make_talent_agent_headers(agent["user_id"])

    scenarios = []
    for edition, stage, artist_name in (
        (attendance_edition, attendance_stage, "Dust Road Revival"),
        (revenue_edition, revenue_stage, "Copper Creek Band"),
    ):
        world = {
            "edition": edition,
            "stage": stage,
            "agent": agent,
            "artist": create_artist(agent["id"], name=artist_name),
            "agent_headers": agent_headers,
        }
        scenario = setup_announced_booking(
            world, scale_overrides=RESERVED_TIER_2000, deal_type="VERSUS"
        )
        _sell_reserved_tier(scenario, 1800)
        scenarios.append(scenario)

    set_clock(CLOCK_AFTER_ONE_SHOW_UTC)
    for scenario in scenarios:
        scenario["booking"] = mark_performed(scenario["booking"]["id"])
        draft = open_settlement(scenario["booking"]["id"], **FINAL_ARTIST_MERCH)
        submitted = submit_settlement(draft["id"])
        scenario["settlement"] = approve_settlement(submitted["id"])
    return scenarios[0], scenarios[1]


class TestArtistRescoringByStrategyBasis:
    """Approving a settlement rewrites the act's carried-forward draw score."""

    def test_attendance_weighted_edition_rescores_from_sell_through(self):
        """An attendance-weighted edition blends 0.60 of the carried-in draw score
        with 40.0 times the sell-through ratio, so 1800 paid seats of a 2000-seat
        house lift a base of 62.50 to 73.50.

        "Under `ATTENDANCE_WEIGHTED` the raw score is 0.60 multiplied by the artist's `base_draw_score` plus 40.0 multiplied by the sell-through ratio"

        Design: Difficulty/dual_variant_calc/artist_draw_score_attendance_vs_revenue_weighted
        """
        attendance, _revenue = _two_editions_on_opposite_strategy_bases()

        assert attendance["edition"]["strategy_basis"] == "ATTENDANCE_WEIGHTED"
        assert attendance["settlement"]["status"] == "APPROVED"
        assert attendance["settlement"]["net_pool_cents"] == 7741968

        artist = get_artist(attendance["artist"]["id"])
        assert_artist(artist)
        assert artist["draw_score_next_year"] == pytest.approx(73.50, abs=0.01)

    def test_revenue_weighted_edition_rescores_from_net_pool_per_seat(self):
        """A revenue-weighted edition blends 0.40 of the carried-in draw score with
        the saturating per-seat revenue contribution, so the same show and the same
        7741968-cent net pool leave the act at 32.74.

        "Under `REVENUE_WEIGHTED` the raw score is 0.40 multiplied by the `base_draw_score` plus whichever is smaller of 60.0 and the net pool per seat divided by 500"

        Design: Difficulty/dual_variant_calc/artist_draw_score_attendance_vs_revenue_weighted
        """
        _attendance, revenue = _two_editions_on_opposite_strategy_bases()

        assert revenue["edition"]["strategy_basis"] == "REVENUE_WEIGHTED"
        assert revenue["settlement"]["status"] == "APPROVED"
        assert revenue["settlement"]["net_pool_cents"] == 7741968

        artist = get_artist(revenue["artist"]["id"])
        assert_artist(artist)
        assert artist["draw_score_next_year"] == pytest.approx(32.74, abs=0.01)

    def test_two_bases_diverge_while_the_carried_in_score_is_untouched(self):
        """Identical shows and identical settlements rescore differently because the
        edition selects the variant, and the rewrite lands on the next-year score
        alone: each act's carried-in 62.50 is left exactly as registered.

        "Which of the two drives the score depends on the edition's `strategy_basis`."

        Design: Difficulty/dual_variant_calc/artist_draw_score_attendance_vs_revenue_weighted
        """
        attendance, revenue = _two_editions_on_opposite_strategy_bases()

        assert (
            attendance["settlement"]["net_pool_cents"]
            == revenue["settlement"]["net_pool_cents"]
            == 7741968
        )
        attendance_artist = get_artist(attendance["artist"]["id"])
        revenue_artist = get_artist(revenue["artist"]["id"])
        assert attendance_artist["base_draw_score"] == pytest.approx(62.50, abs=0.01)
        assert revenue_artist["base_draw_score"] == pytest.approx(62.50, abs=0.01)
        assert attendance_artist["draw_score_next_year"] == pytest.approx(73.50, abs=0.01)
        assert revenue_artist["draw_score_next_year"] == pytest.approx(32.74, abs=0.01)
        assert (
            attendance_artist["draw_score_next_year"]
            != revenue_artist["draw_score_next_year"]
        )


# A two-tier price structure: reserved gold seats sold unbundled, and a bundled lawn
# tier whose face price carries the fair gate admission with it.
GOLD_TIER_1160 = {
    "seating_type": "RESERVED",
    "tier_name": "GOLD",
    "face_price_cents": 6295,
    "allotment_seats": 1160,
    "bundled_with_gate_admission": False,
    "facility_fee_cents": 400,
}
LAWN_TIER_2100 = {
    "seating_type": "GENERAL_ADMISSION",
    "tier_name": "LAWN",
    "face_price_cents": 3950,
    "allotment_seats": 2100,
    "bundled_with_gate_admission": True,
    "facility_fee_cents": 250,
}

# Hospitality the act agreed to repay out of its own earnings, and sound reinforcement
# the promoter carries itself.
HOSPITALITY_RECOUPABLE_LINE = {
    "category": "HOSPITALITY",
    "description": "Dressing room hospitality buyout",
    "requested_cost_cents": 120000,
    "is_critical": False,
    "artist_recoupable": True,
}
SOUND_PROMOTER_LINE = {
    "category": "SOUND",
    "description": "Supplemental delay towers",
    "requested_cost_cents": 450000,
    "is_critical": False,
    "artist_recoupable": False,
}


def _show_with_sponsorship_and_recoupable_rider():
    """A guarantee-plus-backend show carrying every waterfall input at once.

    Two price tiers, three approved rider lines of which one is recoupable, a
    presenting sponsor holding stage-naming rights on a high-demand house, and
    2770 paid units across the two tiers, all settled on the final basis with
    nine thousand dollars of artist-sold merchandise.
    """
    scenario = setup_accepted_booking(deal_type="GUARANTEE_PLUS_BACKEND")
    booking_id = scenario["booking"]["id"]
    advance_id = scenario["advance"]["id"]

    hospitality = add_rider_item(advance_id, **HOSPITALITY_RECOUPABLE_LINE)
    sound = add_rider_item(advance_id, **SOUND_PROMOTER_LINE)
    rule_rider_item(hospitality["id"], "APPROVED")
    rule_rider_item(sound["id"], "APPROVED")
    rule_rider_item(scenario["seed_rider_item"]["id"], "APPROVED")
    scenario["advance"] = complete_advance(advance_id)

    gold = add_ticket_scale(booking_id, **GOLD_TIER_1160)
    lawn = add_ticket_scale(booking_id, **LAWN_TIER_2100)
    scenario["gold_tier"] = gold
    scenario["lawn_tier"] = lawn

    sponsor = create_sponsor(
        name="Prairie Cola", category="BEVERAGE", exclusivity_tier="PRESENTING"
    )
    activation = create_activation(
        sponsor["id"],
        booking_id,
        rights="STAGE_NAMING",
        base_fee_cents=2000000,
        exclusivity_category="BEVERAGE",
    )
    scenario["sponsor"] = sponsor
    scenario["activation"] = confirm_activation(activation["id"])

    scenario["booking"] = announce_booking(booking_id)
    record_sales_batch(gold["id"], quantity=970)
    record_sales_batch(lawn["id"], quantity=1800)

    set_clock(CLOCK_AFTER_ONE_SHOW_UTC)
    scenario["booking"] = mark_performed(booking_id)
    draft = open_settlement(booking_id, **FINAL_ARTIST_MERCH)
    scenario["settlement"] = submit_settlement(draft["id"])
    return scenario


class TestPayoutAndSurchargeEvaluationOrder:
    """The payout is taken off the pre-surcharge pool and is never revisited."""

    def test_waterfall_inputs_are_assembled_before_the_payout_step(self):
        """The pool the payout reads is the adjusted gross of 10929371 cents plus the
        quarter-share of 2600000 cents of confirmed sponsorship, less the flat
        promoter expense and the 570000 cents of approved rider spend.

        "`provisional_net_pool_cents` is the adjusted gross plus the sponsorship offset less the base promoter expense, floored at 0"

        Design: Difficulty/combinatorial_formula/artist_payout_pinned_surcharge_evaluation_order
        """
        scenario = _show_with_sponsorship_and_recoupable_rider()

        booking = get_booking(scenario["booking"]["id"])
        assert_show_booking(booking)
        assert booking["gross_potential_cents"] == 12919037
        assert booking["recoupable_production_cost_cents"] == 120000
        assert booking["sponsorship_revenue_cents"] == 2600000
        assert booking["paid_attendance"] == 2770

        assert_sponsorship_activation(scenario["activation"])
        assert scenario["activation"]["net_fee_cents"] == 2600000

        settlement = scenario["settlement"]
        assert_settlement(settlement)
        assert settlement["adjusted_gross_cents"] == 10929371
        assert settlement["sponsorship_offset_cents"] == 650000
        assert settlement["base_promoter_expense_cents"] == 3070000
        assert settlement["provisional_net_pool_cents"] == 8509371

    def test_backend_payout_is_taken_from_the_pre_surcharge_pool(self):
        """The overage share is measured against the provisional net pool, so the
        payout reads 14632965 cents; the converged reading that re-derives the payout
        from the pool net of the surcharge, 14197634 cents, is not what settles.

        "the surcharge is derived from the payout, and the payout is **never** recomputed afterwards"

        Design: Difficulty/combinatorial_formula/artist_payout_pinned_surcharge_evaluation_order
        """
        scenario = _show_with_sponsorship_and_recoupable_rider()

        settlement = scenario["settlement"]
        assert settlement["provisional_net_pool_cents"] == 8509371
        assert settlement["artist_payout_cents"] == 14632965
        assert settlement["artist_payout_cents"] != 14197634

    def test_surcharge_and_net_pool_are_derived_from_the_settled_payout(self):
        """Three and a half percent of the settled payout is 512154 cents, which
        lands on the promoter's all-in expense line and comes out of the pool the
        promoter reports upward, leaving the act 15187965 cents in all.

        "`production_surcharge_cents` is `artist_payout_cents` multiplied by 0.035, rounded half up."

        Design: Difficulty/combinatorial_formula/artist_payout_pinned_surcharge_evaluation_order
        """
        scenario = _show_with_sponsorship_and_recoupable_rider()

        settlement = scenario["settlement"]
        assert settlement["artist_payout_cents"] == 14632965
        assert settlement["production_surcharge_cents"] == 512154
        assert settlement["promoter_expense_cents"] == 3582154
        assert settlement["net_pool_cents"] == 7997217
        assert settlement["total_artist_settlement_cents"] == 15187965
