"""Edges where one clock day or one rider changes the answer.

The thirty-day refund band is probed on both sides of its edge, and the guide
requirement is probed on the step from an empty roster to a single rider.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions
from test_helpers.factories import party_member, payment_payload, reservation_payload
from test_helpers.fixtures import (
    assign_guide,
    build_activity_slot,
    build_active_guide,
    build_booking,
    build_cabin,
    build_guest,
    build_open_season,
    build_ready_rider,
    confirm_booking,
    open_slot,
    set_clock_to,
)
from test_helpers.test_users import RANCH_MANAGER, RESERVATIONS_AGENT

DEPOSIT_CENTS = 377607


def _two_parties_holding_two_cabins(client):
    """Two confirmed 7-night stays arriving 2026-10-11 in two different cabins."""
    season = build_open_season(client)
    cabin_a = build_cabin(client, name="Aspen", bed_capacity=4)
    cabin_b = build_cabin(client, name="Birch", bed_capacity=4)
    ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
    ben = build_guest(client, "Ben Adult", "1983-07-11", 190)
    cal = build_guest(client, "Cal Child", "2016-05-20", 95)
    dee = build_guest(client, "Dee Adult", "1990-01-15", 175)
    eli = build_guest(client, "Eli Adult", "1988-06-05", 180)
    fay = build_guest(client, "Fay Child", "2015-03-03", 90)

    bookings = []
    for cabin, members in (
        (
            cabin_a,
            [
                party_member(ann["id"], "ADULT"),
                party_member(ben["id"], "ADULT"),
                party_member(cal["id"], "CHILD"),
            ],
        ),
        (
            cabin_b,
            [
                party_member(dee["id"], "ADULT"),
                party_member(eli["id"], "ADULT"),
                party_member(fay["id"], "CHILD"),
            ],
        ),
    ):
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            members,
            package_tier_code="CLASSIC",
            arrival_date="2026-10-11",
            departure_date="2026-10-18",
        )
        get_success_data(
            client.post_payment(
                booking["id"],
                payment_payload(DEPOSIT_CENTS, "DEPOSIT"),
                RESERVATIONS_AGENT,
            )
        )
        bookings.append(confirm_booking(client, booking["id"]))
    return bookings[0], bookings[1]


class TestRefundBandAtThirtyDaysOut:
    """Thirty days out still earns a quarter back; twenty-nine days out earns none."""

    def test_cancelling_exactly_thirty_days_out_keeps_the_quarter_refund(self, client):
        """The party that walks away on the edge day is inside the band.

        PRD: "and selects the refund fraction from the first matching band: 1.00
        when that figure is 90 days or more, 0.50 when it is 60 days or more,
        0.25 when it is 30 days or more, and 0.00 otherwise."

        Design: Difficulty/boundary_precision_check/cancellation_refund_band_at_exactly_thirty_days_before_arrival
        """
        booking_a, _booking_b = _two_parties_holding_two_cabins(client)
        set_clock_to(client, "2026-09-11T18:00:00Z")
        cancelled = validate_success(
            client.cancel_booking(
                booking_a["id"], "cancelled exactly thirty days out", RESERVATIONS_AGENT
            )
        )
        assertions.assert_booking(cancelled)
        assert float(cancelled["cancellation_refund_pct"]) == 0.25
        assert cancelled["refunded_cents"] == 94402
        assert cancelled["forfeited_cents"] == 283205
        assert cancelled["payment_status"] == "PARTIALLY_REFUNDED"
        assertions.assert_cancellation_split_is_conservative(cancelled)
        assert cancelled["refunded_cents"] + cancelled["forfeited_cents"] == DEPOSIT_CENTS

    def test_cancelling_a_day_later_forfeits_the_whole_deposit(self, client):
        """One clock day past the edge the band collapses to nothing.

        PRD: "The money dimension then lands on its terminal value: a fraction of
        1.00 moves `payment_status` from `DEPOSIT_PAID` to `REFUNDED`; a fraction
        strictly between 0 and 1 moves it to `PARTIALLY_REFUNDED`; a fraction of
        0.00 moves it to `FORFEITED`."

        Design: Difficulty/boundary_precision_check/cancellation_refund_band_at_exactly_thirty_days_before_arrival
        """
        booking_a, booking_b = _two_parties_holding_two_cabins(client)
        set_clock_to(client, "2026-09-11T18:00:00Z")
        validate_success(
            client.cancel_booking(
                booking_a["id"], "cancelled exactly thirty days out", RESERVATIONS_AGENT
            )
        )
        set_clock_to(client, "2026-09-12T18:00:00Z")
        cancelled = validate_success(
            client.cancel_booking(
                booking_b["id"], "cancelled twenty-nine days out", RESERVATIONS_AGENT
            )
        )
        assert float(cancelled["cancellation_refund_pct"]) == 0.00
        assert cancelled["refunded_cents"] == 0
        assert cancelled["forfeited_cents"] == DEPOSIT_CENTS
        assert cancelled["payment_status"] == "FORFEITED"
        assertions.assert_cancellation_split_is_conservative(cancelled)
        assert cancelled["refunded_cents"] + cancelled["forfeited_cents"] == DEPOSIT_CENTS


def _empty_steep_hike_with_one_guide(client):
    """A steep hike opened with one guide and not a single rider yet."""
    season = build_open_season(client)
    cabin = build_cabin(client, name="Aspen", bed_capacity=4)
    ann = build_ready_rider(client, "Ann Adult", "1985-04-02", 165, "BEGINNER")
    booking = build_booking(
        client,
        season["id"],
        cabin["id"],
        [party_member(ann["id"], "ADULT")],
        package_tier_code="CLASSIC",
        arrival_date="2026-10-11",
        departure_date="2026-10-18",
    )
    guide = build_active_guide(
        client,
        season["id"],
        full_name="Gus Guide",
        certifications=["WILDERNESS_FIRST_AID", "EQUINE_HANDLER"],
    )
    slot = build_activity_slot(
        client,
        season["id"],
        activity_type="HIKE",
        starts_at="2026-10-12T15:00:00Z",
        ends_at="2026-10-12T17:00:00Z",
        terrain_grade="STEEP",
        min_ability_rank="BEGINNER",
        capacity=6,
        rider_surcharge_cents=0,
        mount_required=False,
    )
    assign_guide(client, slot["id"], guide["id"], "LEAD")
    opened = open_slot(client, slot["id"])
    return booking, ann, opened


class TestGuideRequirementOnTheEmptyRiderSet:
    """A steep slot needs two guides only once it carries a rider."""

    def test_a_steep_slot_with_no_riders_opens_needing_no_guides(self, client):
        """The empty roster overrides the steep ground's own floor.

        PRD: "`required_guide_count` is the greatest of those three — except that
        a slot with no confirmed riders at all requires exactly 0 guides, not the
        terrain floor."

        Design: Difficulty/boundary_precision_check/guide_requirement_is_zero_on_the_empty_confirmed_rider_set
        """
        _booking, _rider, opened = _empty_steep_hike_with_one_guide(client)
        assertions.assert_activity_slot(opened)
        assert opened["required_guide_count"] == 0
        assertions.assert_readiness_posture(opened, "STAFFED_READY")
        assert opened["slot_status"] == "OPEN"

    def test_the_first_rider_raises_the_requirement_to_the_steep_floor(self, client):
        """One beginner on steep ground demands two guides, not one.

        PRD: "The second is the terrain requirement: a slot whose `terrain_grade`
        is `STEEP` or `RIVER_CROSSING` demands at least 2 guides, and any other
        terrain demands at least 1."

        Design: Difficulty/boundary_precision_check/guide_requirement_is_zero_on_the_empty_confirmed_rider_set
        """
        booking, rider, opened = _empty_steep_hike_with_one_guide(client)
        validate_success(
            client.create_reservation(
                opened["id"],
                reservation_payload(booking["id"], rider["id"], opened["version"]),
                RESERVATIONS_AGENT,
            ),
            201,
        )
        slot = validate_success(client.get_activity_slot(opened["id"], RANCH_MANAGER))
        assertions.assert_slot_counters(
            slot,
            confirmed_rider_count=1,
            required_guide_count=2,
            assigned_guide_count=1,
        )

    def test_the_raised_requirement_pushes_the_slot_onto_an_understaffed_hold(self, client):
        """Selling the first seat takes the steep hike off the sale board.

        PRD: "Any event that leaves the recomputed posture at `UNDERSTAFFED` or
        `MOUNT_SHORT` — a new seat that raises `required_guide_count` or leaves a
        rider unmounted, a guide release, a staff separation, a horse taken out
        of service, a waiver revocation — pushes an `OPEN` slot onto `HOLD` in
        the same request."

        Design: Difficulty/boundary_precision_check/guide_requirement_is_zero_on_the_empty_confirmed_rider_set
        """
        booking, rider, opened = _empty_steep_hike_with_one_guide(client)
        validate_success(
            client.create_reservation(
                opened["id"],
                reservation_payload(booking["id"], rider["id"], opened["version"]),
                RESERVATIONS_AGENT,
            ),
            201,
        )
        slot = validate_success(client.get_activity_slot(opened["id"], RANCH_MANAGER))
        assertions.assert_readiness_posture(slot, "UNDERSTAFFED")
        assert slot["slot_status"] == "HOLD"
        assert slot["hold_reason"] == "UNDERSTAFFED"
