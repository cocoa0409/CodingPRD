"""Formulas whose factors can be combined in more than one order.

The package price rounds each party member's line before summing, and the guide
requirement takes the greatest of three independently computed floors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions
from test_helpers.factories import party_member, reservation_payload
from test_helpers.fixtures import (
    build_activity_slot,
    build_booking,
    build_cabin,
    build_guest,
    build_open_season,
    build_ready_rider,
    take_seat,
)
from test_helpers.test_users import RANCH_MANAGER, RESERVATIONS_AGENT

ARRIVAL = "2026-10-11"
DEPARTURE = "2026-10-18"


class TestPackagePriceRoundingOrder:
    """68500 * (1 - 0.375) lands on a half cent, so the order of operations shows."""

    def _party_of_two_adults_and_a_child(self, client):
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
        ben = build_guest(client, "Ben Adult", "1983-07-11", 190)
        cal = build_guest(client, "Cal Child", "2016-05-20", 95)
        members = [
            party_member(ann["id"], "ADULT"),
            party_member(ben["id"], "ADULT"),
            party_member(cal["id"], "CHILD"),
        ]
        return season, cabin, members

    def test_child_line_is_rounded_before_it_joins_the_subtotal(self, client):
        """The already-rounded member lines sum to 1258691, not to 1258688.

        PRD: "**The per-member rounding, and the fact that it happens before any
        summation, is normative**: the subtotal is the sum of the
        already-rounded member lines, and summing unrounded lines and rounding
        once at the end produces a different and incorrect figure."

        Design: Difficulty/combinatorial_formula/package_total_rounds_each_member_line_before_summing
        """
        season, cabin, members = self._party_of_two_adults_and_a_child(client)
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            members,
            package_tier_code="CLASSIC",
            arrival_date=ARRIVAL,
            departure_date=DEPARTURE,
        )
        assertions.assert_booking(booking)
        assert booking["provisional_package_total_cents"] == 1258691
        assert booking["provisional_package_total_cents"] != 1258688

    def test_seven_night_band_carries_no_discount_and_fixes_the_deposit(self, client):
        """At seven nights no stay discount masks the rounding, so the deposit is exact.

        PRD: "a stay of seven nights or fewer earns no discount, a stay of eight
        through thirteen nights earns a 5 percent discount, and a stay of
        fourteen nights or more earns an 8 percent discount"

        Design: Difficulty/combinatorial_formula/package_total_rounds_each_member_line_before_summing
        """
        season, cabin, members = self._party_of_two_adults_and_a_child(client)
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            members,
            package_tier_code="CLASSIC",
            arrival_date=ARRIVAL,
            departure_date=DEPARTURE,
        )
        assert booking["nights"] == 7
        assert booking["provisional_package_total_cents"] == 1258691
        assert booking["deposit_required_cents"] == 377607


def _two_meadow_hikes_and_a_family_of_three(client):
    """Two identical unmounted meadow hikes on consecutive days.

    The first hike carries all three riders including the ten-year-old; the
    second carries only the two adults, so the two slots differ in exactly one
    input.
    """
    season = build_open_season(client)
    cabin = build_cabin(client, name="Aspen", bed_capacity=4)
    ann = build_ready_rider(client, "Ann Adult", "1985-04-02", 165, "BEGINNER")
    ben = build_ready_rider(client, "Ben Adult", "1983-07-11", 190, "BEGINNER")
    cal = build_ready_rider(
        client,
        "Cal Child",
        "2016-05-20",
        95,
        "BEGINNER",
        guardian_guest_id=ann["id"],
    )
    booking = build_booking(
        client,
        season["id"],
        cabin["id"],
        [
            party_member(ann["id"], "ADULT"),
            party_member(ben["id"], "ADULT"),
            party_member(cal["id"], "CHILD"),
        ],
        package_tier_code="CLASSIC",
        arrival_date=ARRIVAL,
        departure_date=DEPARTURE,
    )
    hike_kwargs = dict(
        activity_type="HIKE",
        terrain_grade="MEADOW",
        min_ability_rank="BEGINNER",
        capacity=6,
        rider_surcharge_cents=0,
        mount_required=False,
    )
    slot_mix = build_activity_slot(
        client,
        season["id"],
        starts_at="2026-10-12T15:00:00Z",
        ends_at="2026-10-12T17:00:00Z",
        **hike_kwargs,
    )
    slot_adults = build_activity_slot(
        client,
        season["id"],
        starts_at="2026-10-13T15:00:00Z",
        ends_at="2026-10-13T17:00:00Z",
        **hike_kwargs,
    )
    for guest in (ann, ben, cal):
        take_seat(client, slot_mix["id"], booking["id"], guest["id"])
    take_seat(client, slot_adults["id"], booking["id"], ann["id"])

    slot_adults = get_success_data(
        client.get_activity_slot(slot_adults["id"], RANCH_MANAGER)
    )
    last_seat = validate_success(
        client.create_reservation(
            slot_adults["id"],
            reservation_payload(booking["id"], ben["id"], slot_adults["version"]),
            RESERVATIONS_AGENT,
        ),
        201,
    )
    mix = get_success_data(client.get_activity_slot(slot_mix["id"], RANCH_MANAGER))
    adults = get_success_data(
        client.get_activity_slot(slot_adults["id"], RANCH_MANAGER)
    )
    return mix, adults, last_seat


class TestGuideRequirementIsTheGreatestFloor:
    """Ability mix, terrain and minors are three floors combined by a maximum."""

    def test_one_minor_on_the_roster_lifts_the_requirement_to_two_guides(self, client):
        """Three beginner riders need one guide by ratio but two because one is a child.

        PRD: "The third is the minors requirement: a slot carrying at least one
        rider under 12 years of age demands at least 2 guides, and a slot with
        no such rider adds nothing on this account."

        Design: Difficulty/combinatorial_formula/guide_staffing_requirement_is_max_of_three_independent_floors
        """
        mix, _adults, _seat = _two_meadow_hikes_and_a_family_of_three(client)
        assertions.assert_activity_slot(mix)
        assertions.assert_slot_counters(
            mix,
            confirmed_rider_count=3,
            minor_rider_count=1,
            required_guide_count=2,
        )

    def test_an_all_adult_roster_of_the_same_size_needs_one_guide(self, client):
        """Two beginner adults on meadow ground round up to a single guide.

        PRD: "The four quotients are added together as real numbers and the
        **total** is rounded up to the next whole guide; the rounding-up happens
        once, on the sum, and never per bucket."

        Design: Difficulty/combinatorial_formula/guide_staffing_requirement_is_max_of_three_independent_floors
        """
        mix, adults, seat = _two_meadow_hikes_and_a_family_of_three(client)
        assertions.assert_activity_reservation(seat)
        assert seat["reservation_status"] == "CONFIRMED"
        assertions.assert_slot_counters(
            adults,
            confirmed_rider_count=2,
            minor_rider_count=0,
            required_guide_count=1,
        )
        assert mix["required_guide_count"] != 3
        assert adults["required_guide_count"] != 2
