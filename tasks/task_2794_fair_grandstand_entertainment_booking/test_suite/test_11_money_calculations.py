"""Money arithmetic of the grandstand: the gate credit carved out of bundled
tickets, the chronological batch fold, the settlement waterfall with its merch
split and activation premiums, and the buying-strategy report those figures feed.
"""

import pytest
from prd_bench_local_runner.testing import validate_paginated

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_buying_strategy_report,
    assert_settlement,
    assert_settlement_preview,
)
from test_helpers.fixtures import (
    add_ticket_scale,
    buying_strategy_report,
    create_activation,
    create_artist,
    create_sponsor,
    get_activation,
    get_artist,
    get_booking,
    get_settlement,
    get_ticket_scale,
    mark_performed,
    open_settlement,
    record_sales_batch,
    set_clock,
    settlement_preview,
    setup_accepted_booking,
    setup_announced_booking,
    setup_approved_settlement,
    setup_performed_booking,
    setup_submitted_settlement,
    submit_settlement,
)
from test_helpers.test_users import SETTLEMENT_CONTROLLER_HEADERS, TALENT_BUYER_HEADERS

# The canonical grandstand price tier: reserved GOLD seats at 62.95 dollars with a
# four-dollar facility fee that never enters the artist gross.
GOLD_SCALE = {"allotment_seats": 2000, "facility_fee_cents": 400}


class TestBuyingStrategyReport:
    """The computed read that carries this year's figures into next year's buying."""

    def test_report_publishes_every_declared_figure_for_one_settled_show(self):
        """One PERFORMED show with an APPROVED settlement fixes every reported
        figure: the counts, the evenly blended diversity index, the paid
        attendance, the approved net pool, the revenue per attendee and the
        recommended ceiling, and the approval rescores the act for next year.

        "From that population, `announced_show_count` is the number of such bookings"

        Design: Corner/calculations/buying_strategy_report_computes_every_declared_figure
        """
        scenario = setup_performed_booking(
            scale_overrides=dict(GOLD_SCALE),
            sales=[{"batch_kind": "SALE", "quantity": 1800, "channel": "ONLINE"}],
        )
        settlement = setup_approved_settlement(
            scenario, merch_gross_cents=900000, merch_seller="ARTIST"
        )
        assert_settlement(settlement)

        assert settlement["adjusted_gross_cents"] == 10679468
        assert settlement["sponsorship_offset_cents"] == 0
        assert settlement["base_promoter_expense_cents"] == 2500000
        assert settlement["provisional_net_pool_cents"] == 8179468
        assert settlement["artist_payout_cents"] == 12500000
        assert settlement["production_surcharge_cents"] == 437500
        assert settlement["promoter_expense_cents"] == 2937500
        assert settlement["net_pool_cents"] == 7741968
        assert settlement["merch_hall_fee_cents"] == 180000
        assert settlement["merch_artist_share_cents"] == 720000
        assert settlement["total_artist_settlement_cents"] == 13220000

        artist = get_artist(scenario["artist"]["id"])
        assert artist["draw_score_next_year"] == pytest.approx(73.50, abs=0.01)

        report = buying_strategy_report(scenario["edition"]["id"])
        assert_buying_strategy_report(report)
        assert report["announced_show_count"] == 1
        assert report["distinct_genre_count"] == 1
        assert report["distinct_segment_count"] == 1
        assert report["genre_diversity_index"] == pytest.approx(0.1964, abs=1e-4)
        assert report["total_paid_attendance"] == 1800
        assert report["total_net_pool_cents"] == 7741968
        assert report["revenue_per_paid_attendee_cents"] == 4301
        assert report["recommended_guarantee_ceiling_cents"] == 8516165

    def test_report_excludes_held_shows_and_settlements_short_of_approval(self):
        """A show still merely held is outside the report's population, so it
        lifts neither the show count nor the variety counts, and a settlement
        sitting in PENDING_APPROVAL contributes no money at all even though its
        own net pool figure has already been computed.

        "The financial figures narrow further to settlements in status `APPROVED` only"

        Design: Corner/calculations/report_excludes_date_held_shows_and_unapproved_settlements
        """
        scenario = setup_performed_booking(
            scale_overrides=dict(GOLD_SCALE),
            sales=[{"batch_kind": "SALE", "quantity": 1800, "channel": "ONLINE"}],
        )
        settlement = setup_submitted_settlement(
            scenario, merch_gross_cents=900000, merch_seller="ARTIST"
        )

        # A second act on the same agent takes a later date on the same stage and
        # never gets past its date hold.
        second_world = dict(scenario)
        second_world["artist"] = create_artist(
            scenario["agent"]["id"],
            name="Neon Skyline",
            genre="ROCK",
            audience_segment="YOUNG_ADULT",
            base_draw_score=55.00,
        )
        second = setup_accepted_booking(
            second_world,
            offered_guarantee_cents=500000,
            backend_breakeven_cents=0,
            target_show_date="2026-08-25",
            load_in_start_utc="2026-08-25T14:00:00.000Z",
            load_out_end_utc="2026-08-25T23:00:00.000Z",
        )
        assert second["booking"]["booking_status"] == "DATE_HELD"

        report = buying_strategy_report(scenario["edition"]["id"])
        assert_buying_strategy_report(report)
        assert report["announced_show_count"] == 1
        assert report["distinct_genre_count"] == 1
        assert report["distinct_segment_count"] == 1
        assert report["genre_diversity_index"] == pytest.approx(0.1964, abs=1e-4)
        assert report["total_paid_attendance"] == 1800
        assert report["total_net_pool_cents"] == 0
        assert report["revenue_per_paid_attendee_cents"] == 0
        assert report["recommended_guarantee_ceiling_cents"] == 0

        # The excluded figures exist; they are simply not reportable yet.
        held_back = get_settlement(settlement["id"], SETTLEMENT_CONTROLLER_HEADERS)
        assert held_back["status"] == "PENDING_APPROVAL"
        assert held_back["net_pool_cents"] == 7741968
        assert get_booking(second["booking"]["id"])["booking_status"] == "DATE_HELD"


def test_gate_credit_separates_twin_general_admission_tiers_by_a_fixed_amount():
    """Two general-admission tiers priced identically differ only in whether the
    ticket includes fair gate admission, so the whole gap between their gross
    potentials is the gate credit taken off the bundled face value before the
    admission tax, and the booking's potential is the sum of the two already
    rounded tier lines.

    "First the gate credit is established for the edition: `bundle_credit_cents` is sixty percent of the edition's `gate_admission_price_cents`, rounded half up to whole cents."

    Design: Corner/calculations/bundle_credit_constant_isolated_by_twin_ga_scales
    """
    scenario = setup_accepted_booking()
    booking_id = scenario["booking"]["id"]

    bundled = add_ticket_scale(
        booking_id,
        seating_type="GENERAL_ADMISSION",
        tier_name="LAWN-BUNDLE",
        face_price_cents=3950,
        allotment_seats=2100,
        bundled_with_gate_admission=True,
        facility_fee_cents=0,
    )
    after_first_tier = get_booking(booking_id)
    assert after_first_tier["ticketing_status"] == "SCALED"

    unbundled = add_ticket_scale(
        booking_id,
        seating_type="GENERAL_ADMISSION",
        tier_name="LAWN-ONLY",
        face_price_cents=3950,
        allotment_seats=2100,
        bundled_with_gate_admission=False,
        facility_fee_cents=0,
    )

    bundled = get_ticket_scale(bundled["id"])
    unbundled = get_ticket_scale(unbundled["id"])
    assert bundled["scale_gross_potential_cents"] == 6036713
    assert unbundled["scale_gross_potential_cents"] == 7818038
    assert (
        unbundled["scale_gross_potential_cents"]
        - bundled["scale_gross_potential_cents"]
    ) == 1781325

    booking = get_booking(booking_id)
    assert booking["gross_potential_cents"] == 13854751
    assert booking["gross_potential_cents"] == 6036713 + 7818038
    # The date is still merely held, so the on-sale join has not fired.
    assert booking["booking_status"] == "DATE_HELD"
    assert booking["ticketing_status"] == "SCALED"


def test_settlement_fold_replays_batches_in_recorded_order_and_honours_the_doors_cutoff():
    """Batches written in an order that contradicts their own timestamps are
    replayed chronologically, so the final adjusted gross reflects the net of all
    three movements, while the provisional basis keeps only the movements
    recorded strictly before doors.

    "For each tier the eligible batches are folded in ascending `recorded_at_utc`, with ascending `created_at` as the tie-break and never the identifier"

    Design: Corner/calculations/out_of_order_batches_are_folded_by_recorded_at_utc
    """
    scenario = setup_announced_booking(scale_overrides=dict(GOLD_SCALE))
    booking_id = scenario["booking"]["id"]
    scale_id = scenario["ticket_scale"]["id"]

    # The show sells 300 after doors, then a further 200 in the afternoon, and
    # 100 of the afternoon units are handed back, all recorded out of sequence.
    set_clock("2026-08-22T19:00:00.000Z")
    walk_up = record_sales_batch(scale_id, "SALE", 300, "ONLINE")
    set_clock("2026-08-22T15:00:00.000Z")
    record_sales_batch(scale_id, "SALE", 200, "BOX_OFFICE")
    set_clock("2026-08-22T16:00:00.000Z")
    record_sales_batch(scale_id, "REFUND", 100, "BOX_OFFICE")

    assert walk_up["recorded_at_utc"] == "2026-08-22T19:00:00.000Z"

    final = settlement_preview(
        booking_id,
        {"basis": "FINAL", "merch_gross_cents": 0, "merch_seller": "ARTIST"},
    )
    assert_settlement_preview(final)
    assert final["basis"] == "FINAL"
    assert final["adjusted_gross_cents"] == 2373215

    provisional = settlement_preview(
        booking_id,
        {"basis": "PROVISIONAL", "merch_gross_cents": 0, "merch_seller": "ARTIST"},
    )
    assert_settlement_preview(provisional)
    assert provisional["basis"] == "PROVISIONAL"
    assert provisional["adjusted_gross_cents"] == 593304

    scale = get_ticket_scale(scale_id)
    assert scale["sold_seats"] == 400
    assert scale["available_seats"] == 1600
    assert get_booking(booking_id)["paid_attendance"] == 400


def test_merch_hall_rate_steps_at_exactly_2500_paid_attendance_and_respects_floor_then_cap():
    """The merchandise hall rate picks up its attendance bonus the moment paid
    attendance reaches two thousand five hundred, so a single extra ticket lifts
    the hall fee and lowers what the artist takes home; the same house also shows
    the unconditional minimum fee on a zero merchandise take and the ceiling on a
    large one.

    "plus a further 0.05 when the booking's `paid_attendance` is greater than or equal to 2,500"

    Design: Corner/calculations/merch_rate_step_at_exactly_2500_paid_attendance
    """
    scenario = setup_announced_booking(
        scale_overrides={"allotment_seats": 2500, "facility_fee_cents": 400}
    )
    booking_id = scenario["booking"]["id"]
    scale_id = scenario["ticket_scale"]["id"]

    record_sales_batch(scale_id, "SALE", 2499, "ONLINE")
    below = settlement_preview(
        booking_id,
        {"basis": "FINAL", "merch_gross_cents": 900000, "merch_seller": "ARTIST"},
        SETTLEMENT_CONTROLLER_HEADERS,
    )
    assert_settlement_preview(below)
    assert below["adjusted_gross_cents"] == 14826661
    assert below["net_pool_cents"] == 11889161
    assert below["merch_hall_fee_cents"] == 180000
    assert below["merch_artist_share_cents"] == 720000
    assert below["total_artist_settlement_cents"] == 13220000

    # One more ticket, and nothing else, moves the house across the bonus line.
    record_sales_batch(scale_id, "SALE", 1, "BOX_OFFICE")
    at_tier = settlement_preview(
        booking_id,
        {"basis": "FINAL", "merch_gross_cents": 900000, "merch_seller": "ARTIST"},
        SETTLEMENT_CONTROLLER_HEADERS,
    )
    assert at_tier["adjusted_gross_cents"] == 14832594
    assert at_tier["net_pool_cents"] == 11895094
    assert at_tier["merch_hall_fee_cents"] == 225000
    assert at_tier["merch_artist_share_cents"] == 675000
    assert at_tier["total_artist_settlement_cents"] == 13175000
    assert (
        below["total_artist_settlement_cents"]
        - at_tier["total_artist_settlement_cents"]
    ) == 45000

    no_merch = settlement_preview(
        booking_id,
        {"basis": "FINAL", "merch_gross_cents": 0, "merch_seller": "ARTIST"},
        SETTLEMENT_CONTROLLER_HEADERS,
    )
    assert no_merch["merch_hall_fee_cents"] == 25000
    assert no_merch["merch_artist_share_cents"] == -25000
    assert no_merch["total_artist_settlement_cents"] == 12475000

    venue_stand = settlement_preview(
        booking_id,
        {"basis": "FINAL", "merch_gross_cents": 5000000, "merch_seller": "VENUE"},
        SETTLEMENT_CONTROLLER_HEADERS,
    )
    assert venue_stand["merch_hall_fee_cents"] == 750000
    assert venue_stand["merch_artist_share_cents"] == 4250000
    assert venue_stand["total_artist_settlement_cents"] == 16750000

    assert get_booking(booking_id)["paid_attendance"] == 2500
    # A preview persists nothing, so no settlement row exists for this show.
    records, meta = validate_paginated(
        api_client.list_settlements(TALENT_BUYER_HEADERS, {"booking_id": booking_id})
    )
    assert records == []
    assert meta["total_count"] == 0


def test_activation_premium_reads_gross_potential_once_at_ten_million_boundary():
    """The high-demand premium is earned at equality with ten million cents of
    gross potential, not only above it, and because the premium is priced from a
    snapshot taken when the rights are bought, an activation sold one cent short
    of the boundary keeps its unpremiumed fee after a later tier lifts the show
    onto the boundary.

    "a further ten percent is added when the booking's `gross_potential_cents` is greater than or equal to 10,000,000 cents"

    Design: Corner/calculations/activation_premium_tier_boundary_at_ten_million_gross
    """
    scenario = setup_accepted_booking()
    booking_id = scenario["booking"]["id"]
    motors = create_sponsor(
        name="Ridgeline Motors", category="AUTOMOTIVE", exclusivity_tier="SUPPORTING"
    )
    cola = create_sponsor(
        name="Prairie Cola", category="BEVERAGE", exclusivity_tier="SUPPORTING"
    )

    add_ticket_scale(
        booking_id,
        seating_type="RESERVED",
        tier_name="PLAZA",
        face_price_cents=5101,
        allotment_seats=2079,
        bundled_with_gate_admission=False,
        facility_fee_cents=0,
    )
    assert get_booking(booking_id)["gross_potential_cents"] == 9995193

    early = create_activation(
        motors["id"],
        booking_id,
        rights="SIGNAGE",
        base_fee_cents=1000000,
        exclusivity_category="AUTOMOTIVE",
    )
    assert early["net_fee_cents"] == 1000000

    # A single extra seat carries the show's potential exactly onto the boundary.
    add_ticket_scale(
        booking_id,
        seating_type="RESERVED",
        tier_name="PLAZA-SINGLE",
        face_price_cents=5100,
        allotment_seats=1,
        bundled_with_gate_admission=False,
        facility_fee_cents=0,
    )
    assert get_booking(booking_id)["gross_potential_cents"] == 10000000

    later = create_activation(
        cola["id"],
        booking_id,
        rights="SIGNAGE",
        base_fee_cents=1000000,
        exclusivity_category="BEVERAGE",
    )
    assert later["net_fee_cents"] == 1100000

    assert get_activation(early["id"])["net_fee_cents"] == 1000000


def test_waterfall_clamps_the_pool_at_zero_while_the_reported_net_goes_negative():
    """A thin house cannot cover the flat promoter expense, so the pool handed to
    the artist split is held at zero rather than allowed below it; the versus deal
    then falls back to its guarantee, the surcharge is taken on that payout, and
    the reported net pool is left negative.

    "floored at 0 so that a loss-making show never produces a negative pool"

    Design: Corner/calculations/promoter_expense_waterfall_floors_pool_at_zero_not_below
    """
    scenario = setup_announced_booking(
        scale_overrides={
            "tier_name": "BLEACHER",
            "face_price_cents": 3770,
            "allotment_seats": 250,
            "facility_fee_cents": 0,
        },
        offered_guarantee_cents=500000,
        backend_breakeven_cents=0,
    )
    booking_id = scenario["booking"]["id"]
    record_sales_batch(scenario["ticket_scale"]["id"], "SALE", 100, "ONLINE")

    preview = settlement_preview(
        booking_id,
        {"basis": "FINAL", "merch_gross_cents": 0, "merch_seller": "ARTIST"},
        SETTLEMENT_CONTROLLER_HEADERS,
    )
    assert_settlement_preview(preview)
    assert preview["adjusted_gross_cents"] == 355323
    assert preview["sponsorship_offset_cents"] == 0
    assert preview["base_promoter_expense_cents"] == 2500000
    assert preview["provisional_net_pool_cents"] == 0
    assert preview["artist_payout_cents"] == 500000
    assert preview["production_surcharge_cents"] == 17500
    assert preview["promoter_expense_cents"] == 2517500
    assert preview["net_pool_cents"] == -17500
    assert preview["merch_hall_fee_cents"] == 25000
    assert preview["merch_artist_share_cents"] == -25000
    assert preview["total_artist_settlement_cents"] == 475000

    # Capacity potential and realised gross are independent figures.
    assert get_ticket_scale(scenario["ticket_scale"]["id"])[
        "scale_gross_potential_cents"
    ] == 888306


def test_guarantee_plus_backend_pays_additively_before_the_surcharge_is_taken():
    """A guarantee-plus-backend deal adds the artist's share of the overage on top
    of the guarantee rather than treating the guarantee as a floor, and the
    production surcharge is taken on that additive payout, which is what shows the
    deal variant was chosen before the surcharge step.

    "Under a `GUARANTEE_PLUS_BACKEND` deal the artist takes the `agreed_guarantee_cents` plus a share of the overage"

    Design: Corner/calculations/guarantee_plus_backend_beats_versus_on_the_same_pool
    """
    scenario = setup_announced_booking(
        scale_overrides=dict(GOLD_SCALE),
        deal_type="GUARANTEE_PLUS_BACKEND",
        offered_guarantee_cents=500000,
        backend_breakeven_cents=0,
    )
    booking_id = scenario["booking"]["id"]
    scale_id = scenario["ticket_scale"]["id"]

    set_clock("2026-08-22T17:00:00.000Z")
    record_sales_batch(scale_id, "SALE", 500, "ONLINE")
    set_clock("2026-08-22T19:00:00.000Z")
    record_sales_batch(scale_id, "SALE", 300, "BOX_OFFICE")

    preview = settlement_preview(
        booking_id,
        {"basis": "FINAL", "merch_gross_cents": 0, "merch_seller": "ARTIST"},
        SETTLEMENT_CONTROLLER_HEADERS,
    )
    assert_settlement_preview(preview)
    assert preview["adjusted_gross_cents"] == 4746430
    assert preview["provisional_net_pool_cents"] == 2246430
    assert preview["artist_payout_cents"] == 2409466
    assert preview["production_surcharge_cents"] == 84331
    assert preview["promoter_expense_cents"] == 2584331
    assert preview["net_pool_cents"] == 2162099
    assert preview["total_artist_settlement_cents"] == 2384466

    booking = get_booking(booking_id)
    assert booking["agreed_deal_type"] == "GUARANTEE_PLUS_BACKEND"


def test_provisional_settlement_and_final_preview_reconcile_on_one_batch_set():
    """A settlement standing on the provisional basis keeps the pre-doors count,
    while a final preview of the very same show reports the whole house; the two
    differ by exactly the post-doors batch, and asking for the preview leaves the
    stored settlement untouched.

    "It persists nothing: no settlement is created, no booking is touched, no version moves."

    Design: Corner/calculations/persisted_provisional_settlement_reconciles_against_final_preview
    """
    scenario = setup_announced_booking(
        scale_overrides=dict(GOLD_SCALE),
        deal_type="GUARANTEE_PLUS_BACKEND",
        offered_guarantee_cents=500000,
        backend_breakeven_cents=0,
    )
    booking_id = scenario["booking"]["id"]
    scale_id = scenario["ticket_scale"]["id"]

    set_clock("2026-08-22T17:00:00.000Z")
    record_sales_batch(scale_id, "SALE", 500, "ONLINE")
    set_clock("2026-08-22T19:00:00.000Z")
    record_sales_batch(scale_id, "SALE", 300, "BOX_OFFICE")

    set_clock("2026-08-22T23:00:00.000Z")
    mark_performed(booking_id)

    draft = open_settlement(
        booking_id, basis="PROVISIONAL", merch_gross_cents=0, merch_seller="ARTIST"
    )
    stored = submit_settlement(draft["id"])
    assert_settlement(stored)
    assert stored["basis"] == "PROVISIONAL"
    assert stored["adjusted_gross_cents"] == 2966519
    assert stored["provisional_net_pool_cents"] == 466519
    assert stored["artist_payout_cents"] == 896541
    assert stored["production_surcharge_cents"] == 31379
    assert stored["promoter_expense_cents"] == 2531379
    assert stored["net_pool_cents"] == 435140
    assert stored["total_artist_settlement_cents"] == 871541

    final = settlement_preview(
        booking_id,
        {"basis": "FINAL", "merch_gross_cents": 0, "merch_seller": "ARTIST"},
        SETTLEMENT_CONTROLLER_HEADERS,
    )
    assert_settlement_preview(final)
    assert final["adjusted_gross_cents"] == 4746430
    assert final["provisional_net_pool_cents"] == 2246430
    assert final["artist_payout_cents"] == 2409466
    assert final["production_surcharge_cents"] == 84331
    assert final["net_pool_cents"] == 2162099
    assert final["total_artist_settlement_cents"] == 2384466

    # The gap between the two bases is the post-doors batch and nothing else.
    assert (
        final["adjusted_gross_cents"] - stored["adjusted_gross_cents"]
    ) == 1779911

    assert get_settlement(draft["id"], SETTLEMENT_CONTROLLER_HEADERS) == stored
    assert get_booking(booking_id)["paid_attendance"] == 800
