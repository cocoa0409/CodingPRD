"""Sponsorship activation pricing and the booking a rights package hangs off:
the three independent fee premiums, the hard ceiling thirty percent above base
that clamps them, and the show states in which a confirmation is admitted.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_show_booking, assert_sponsorship_activation
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.factories import build_activation_payload
from test_helpers.test_users import SPONSORSHIP_DIRECTOR_HEADERS

# The grandstand show is scaled well past the high-demand gross threshold, the
# pavilion show deliberately far below it.
GRANDSTAND_GROSS_POTENTIAL_CENTS = 12_919_037
PAVILION_GROSS_POTENTIAL_CENTS = 888_306

CLAMPED_NET_FEE_CENTS = 2_600_000
UNCLAMPED_ARITHMETIC_CENTS = 2_800_000
STAGE_NAMING_ONLY_NET_FEE_CENTS = 1_250_000
NO_PREMIUM_NET_FEE_CENTS = 1_000_000

PERFORMANCE_CLOCK_UTC = "2026-08-22T23:30:00.000Z"
UNITS_SOLD_ONLINE = 1800


def _buy_rights(sponsor_id, booking_id, **overrides):
    """Buy a rights package, echoing the booking version read a moment ago."""
    payload = build_activation_payload(
        sponsor_id, booking_id, fixtures.booking_version(booking_id), **overrides
    )
    return validate_success(
        api_client.create_sponsorship_activation(payload, SPONSORSHIP_DIRECTOR_HEADERS),
        expected_status=201,
    )


def _two_show_world():
    """One edition carrying a richly scaled grandstand show and a modestly
    scaled pavilion show, plus a presenting and a supporting sponsor.

    Stage-naming rights are singular per stage per edition, so putting the two
    shows on two different stages lets the package be sold on each.
    """
    world = fixtures.setup_base_world(edition_overrides={"name": "Premium Clamp Fair"})
    pavilion = fixtures.create_stage(
        world["edition"]["id"],
        name="Pavilion",
        reserved_seat_capacity=500,
        ga_capacity=500,
        changeover_buffer_minutes=60,
        slot_soft_cap=4,
    )
    quartet = fixtures.create_artist(
        world["agent"]["id"],
        name="Marsh Street Quartet",
        genre="COMEDY",
        audience_segment="ADULT_45_PLUS",
        base_draw_score=40.00,
    )

    grandstand_show = fixtures.setup_accepted_booking(world)
    fixtures.add_ticket_scale(
        grandstand_show["booking"]["id"],
        seating_type="RESERVED",
        tier_name="GOLD",
        face_price_cents=6295,
        allotment_seats=1160,
        bundled_with_gate_admission=False,
        facility_fee_cents=400,
    )
    fixtures.add_ticket_scale(
        grandstand_show["booking"]["id"],
        seating_type="GENERAL_ADMISSION",
        tier_name="LAWN",
        face_price_cents=3950,
        allotment_seats=2100,
        bundled_with_gate_admission=True,
        facility_fee_cents=250,
    )

    pavilion_world = dict(world)
    pavilion_world["stage"] = pavilion
    pavilion_world["artist"] = quartet
    pavilion_show = fixtures.setup_accepted_booking(
        pavilion_world,
        offered_guarantee_cents=500_000,
        backend_split_pct=0.0000,
        backend_breakeven_cents=0,
        radius_miles=50,
        radius_days_before=7,
        radius_days_after=7,
        target_show_date="2026-08-25",
        load_in_start_utc="2026-08-25T15:00:00.000Z",
        load_out_end_utc="2026-08-25T22:00:00.000Z",
    )
    fixtures.add_ticket_scale(
        pavilion_show["booking"]["id"],
        seating_type="GENERAL_ADMISSION",
        tier_name="LAWN",
        face_price_cents=3770,
        allotment_seats=250,
        bundled_with_gate_admission=False,
        facility_fee_cents=0,
    )

    return {
        "edition": world["edition"],
        "grandstand_booking": fixtures.get_booking(grandstand_show["booking"]["id"]),
        "pavilion_booking": fixtures.get_booking(pavilion_show["booking"]["id"]),
        "presenting_sponsor": fixtures.create_sponsor(
            name="Prairie Cola", category="BEVERAGE", exclusivity_tier="PRESENTING"
        ),
        "supporting_sponsor": fixtures.create_sponsor(
            name="Valley Mutual", category="FINANCIAL", exclusivity_tier="SUPPORTING"
        ),
    }


class TestActivationFeePremiums:
    """The same base fee priced on three different premium combinations."""

    def test_all_three_premiums_together_are_clamped_to_thirty_percent_above_base(self):
        """Stage-naming rights on a high-gross show bought by a presenting sponsor
        earn all three premium increments at once, and the fee that would follow
        from adding them up is cut back to the hard ceiling above base fee.

        "The second figure is a hard ceiling at thirty percent above base, so an activation that would otherwise earn all three premiums is clamped."

        Design: Difficulty/combinatorial_formula/activation_net_fee_nested_min_three_premiums
        """
        world = _two_show_world()

        activation = _buy_rights(
            world["presenting_sponsor"]["id"],
            world["grandstand_booking"]["id"],
            rights="STAGE_NAMING",
            base_fee_cents=2_000_000,
            exclusivity_category="BEVERAGE",
        )

        assert_sponsorship_activation(activation)
        assert activation["net_fee_cents"] == CLAMPED_NET_FEE_CENTS
        assert activation["net_fee_cents"] != UNCLAMPED_ARITHMETIC_CENTS

    def test_stage_naming_alone_on_a_low_gross_show_prices_below_the_ceiling(self):
        """A supporting sponsor buying stage-naming rights on a show whose gross
        potential sits far below the high-demand threshold earns the naming
        increment only, and that fee stays under the ceiling.

        "twenty-five percent is added when the `rights` package is `STAGE_NAMING`"

        Design: Difficulty/combinatorial_formula/activation_net_fee_nested_min_three_premiums
        """
        world = _two_show_world()

        activation = _buy_rights(
            world["supporting_sponsor"]["id"],
            world["pavilion_booking"]["id"],
            rights="STAGE_NAMING",
            base_fee_cents=1_000_000,
            exclusivity_category="FINANCIAL",
        )

        assert_sponsorship_activation(activation)
        assert activation["net_fee_cents"] == STAGE_NAMING_ONLY_NET_FEE_CENTS

    def test_signage_for_a_supporting_sponsor_earns_no_premium_at_all(self):
        """Signage on the same low-gross show for the same supporting sponsor
        triggers none of the three increments, so the fee is exactly the
        pre-premium base fee that was bought.

        "A premium percentage starts at zero and accumulates three independent increments"

        Design: Difficulty/combinatorial_formula/activation_net_fee_nested_min_three_premiums
        """
        world = _two_show_world()

        activation = _buy_rights(
            world["supporting_sponsor"]["id"],
            world["pavilion_booking"]["id"],
            rights="SIGNAGE",
            base_fee_cents=1_000_000,
            exclusivity_category="AUTOMOTIVE",
        )

        assert_sponsorship_activation(activation)
        assert activation["net_fee_cents"] == NO_PREMIUM_NET_FEE_CENTS

    def test_each_show_carries_the_gross_potential_the_premium_is_read_from(self):
        """The high-demand increment is read off the show's gross potential, which
        is assembled tier by tier: the grandstand show clears the threshold while
        the single-tier pavilion show is nowhere near it.

        "The booking's `gross_potential_cents` is then the sum of `scale_gross_potential_cents` across every one of its tiers"

        Design: Difficulty/combinatorial_formula/activation_net_fee_nested_min_three_premiums
        """
        world = _two_show_world()

        grandstand = world["grandstand_booking"]
        pavilion = world["pavilion_booking"]
        assert_show_booking(grandstand)
        assert_show_booking(pavilion)
        assert grandstand["gross_potential_cents"] == GRANDSTAND_GROSS_POTENTIAL_CENTS
        assert pavilion["gross_potential_cents"] == PAVILION_GROSS_POTENTIAL_CENTS

    def test_priced_but_unconfirmed_activations_add_nothing_to_the_shows(self):
        """All three rights packages are bought and left unconfirmed, so each one
        carries its own priced fee while neither show's sponsorship revenue moves
        off zero.

        "it deliberately does not move the booking's `sponsorship_revenue_cents`, because a merely proposed activation contributes nothing to the show's pool"

        Design: Difficulty/combinatorial_formula/activation_net_fee_nested_min_three_premiums
        """
        world = _two_show_world()

        clamped = _buy_rights(
            world["presenting_sponsor"]["id"],
            world["grandstand_booking"]["id"],
            rights="STAGE_NAMING",
            base_fee_cents=2_000_000,
            exclusivity_category="BEVERAGE",
        )
        naming_only = _buy_rights(
            world["supporting_sponsor"]["id"],
            world["pavilion_booking"]["id"],
            rights="STAGE_NAMING",
            base_fee_cents=1_000_000,
            exclusivity_category="FINANCIAL",
        )
        no_premium = _buy_rights(
            world["supporting_sponsor"]["id"],
            world["pavilion_booking"]["id"],
            rights="SIGNAGE",
            base_fee_cents=1_000_000,
            exclusivity_category="AUTOMOTIVE",
        )

        for activation in (clamped, naming_only, no_premium):
            assert fixtures.get_activation(activation["id"])["status"] == "PROPOSED"

        grandstand = fixtures.get_booking(world["grandstand_booking"]["id"])
        pavilion = fixtures.get_booking(world["pavilion_booking"]["id"])
        assert grandstand["sponsorship_revenue_cents"] == 0
        assert pavilion["sponsorship_revenue_cents"] == 0


def _performed_show_with_two_activations():
    """A show carried all the way to performed, carrying one activation confirmed
    while it was still announced and a second one left merely proposed.

    Both packages are bought for the same sponsor, so no trade-category
    exclusivity clash is possible between them.
    """
    world = fixtures.setup_base_world(
        edition_overrides={"name": "Activation Gate Fair"}
    )
    scenario = fixtures.setup_accepted_booking(world)
    fixtures.prepare_completed_advance(scenario, description="House lighting package")

    booking_id = scenario["booking"]["id"]
    ticket_scale = fixtures.add_ticket_scale(
        booking_id,
        seating_type="RESERVED",
        tier_name="GOLD",
        face_price_cents=6295,
        allotment_seats=2000,
        bundled_with_gate_admission=False,
        facility_fee_cents=400,
    )
    fixtures.announce_booking(booking_id, TEST_DEFAULTS["DOORS_TIME_UTC"])
    fixtures.record_sales_batch(
        ticket_scale["id"], "SALE", UNITS_SOLD_ONLINE, "ONLINE"
    )

    sponsor = fixtures.create_sponsor(
        name="Valley Mutual", category="FINANCIAL", exclusivity_tier="SUPPORTING"
    )
    confirmed = _buy_rights(
        sponsor["id"],
        booking_id,
        rights="SIGNAGE",
        base_fee_cents=1_000_000,
        exclusivity_category="FINANCIAL",
    )
    fixtures.confirm_activation(confirmed["id"])
    proposed = _buy_rights(
        sponsor["id"],
        booking_id,
        rights="SAMPLING",
        base_fee_cents=400_000,
        exclusivity_category="AGRIBUSINESS",
    )

    fixtures.set_clock(PERFORMANCE_CLOCK_UTC)
    booking = fixtures.mark_performed(booking_id)
    return {
        "booking": booking,
        "ticket_scale": ticket_scale,
        "confirmed_activation": fixtures.get_activation(confirmed["id"]),
        "proposed_activation": fixtures.get_activation(proposed["id"]),
    }


class TestConfirmationDependsOnTheShowState:
    """An activation in a perfectly legal proposed state, refused because the
    show it hangs off has already been played.
    """

    def test_confirming_a_proposed_activation_on_a_performed_show_is_refused(self):
        """Confirmation is admitted only while the show is still held or announced,
        so once the show has been marked performed the very same confirm request
        that would have worked earlier is refused on the show's contractual state.

        "requires the booking to be in `DATE_HELD` or `ANNOUNCED`"

        Design: Difficulty/cross_entity_state_dependency/activation_confirm_blocked_once_show_has_performed
        """
        world = _performed_show_with_two_activations()
        assert world["booking"]["booking_status"] == "PERFORMED"

        validate_error(
            api_client.confirm_sponsorship_activation(
                world["proposed_activation"]["id"], SPONSORSHIP_DIRECTOR_HEADERS
            ),
            ApiErrorId.ERR_INVALID_BOOKING_STATE.value,
        )

    def test_refused_confirmation_leaves_the_activation_and_the_pool_untouched(self):
        """The refusal writes nothing: the package stays proposed with the fee it
        was priced at and no make-good credit, and the show's sponsorship revenue
        is exactly what it was before the attempt.

        "Show booking's contractual state admits the action (`ERR_INVALID_BOOKING_STATE`, 409)"

        Design: Difficulty/cross_entity_state_dependency/activation_confirm_blocked_once_show_has_performed
        """
        world = _performed_show_with_two_activations()
        priced_fee_cents = world["proposed_activation"]["net_fee_cents"]
        revenue_before = world["booking"]["sponsorship_revenue_cents"]

        validate_error(
            api_client.confirm_sponsorship_activation(
                world["proposed_activation"]["id"], SPONSORSHIP_DIRECTOR_HEADERS
            ),
            ApiErrorId.ERR_INVALID_BOOKING_STATE.value,
        )

        refused = fixtures.get_activation(world["proposed_activation"]["id"])
        assert refused["status"] == "PROPOSED"
        assert refused["net_fee_cents"] == priced_fee_cents
        assert refused["make_good_credit_cents"] == 0
        booking = fixtures.get_booking(world["booking"]["id"])
        assert booking["sponsorship_revenue_cents"] == revenue_before

    def test_the_sister_activation_confirmed_in_time_is_pulled_to_fulfilled(self):
        """The package confirmed while the show was still announced was carried
        forward by the performance, and the show's sponsorship revenue still counts
        its fee because both live statuses contribute to that pool.

        "every sponsorship activation on the booking whose status reads `CONFIRMED` advances to `FULFILLED`"

        Design: Difficulty/cross_entity_state_dependency/activation_confirm_blocked_once_show_has_performed
        """
        world = _performed_show_with_two_activations()

        fulfilled = fixtures.get_activation(world["confirmed_activation"]["id"])
        assert_sponsorship_activation(fulfilled)
        assert fulfilled["status"] == "FULFILLED"
        assert fulfilled["make_good_credit_cents"] == 0

        booking = fixtures.get_booking(world["booking"]["id"])
        assert booking["sponsorship_revenue_cents"] == fulfilled["net_fee_cents"]

    def test_the_performance_closed_the_box_office_and_every_price_tier(self):
        """Marking the show performed closed the box-office dimension, closed the
        one price tier the show carried, and left the show's paid attendance at the
        units the box office had reported.

        "every price tier of the booking has its `status` set to `CLOSED`"

        Design: Difficulty/cross_entity_state_dependency/activation_confirm_blocked_once_show_has_performed
        """
        world = _performed_show_with_two_activations()

        booking = fixtures.get_booking(world["booking"]["id"])
        assert booking["booking_status"] == "PERFORMED"
        assert booking["ticketing_status"] == "SALES_CLOSED"
        assert booking["paid_attendance"] == UNITS_SOLD_ONLINE

        ticket_scale = fixtures.get_ticket_scale(world["ticket_scale"]["id"])
        assert ticket_scale["status"] == "CLOSED"
