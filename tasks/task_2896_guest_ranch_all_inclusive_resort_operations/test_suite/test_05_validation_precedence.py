"""Requests that break two rules at once and must report the ranking one.

A cancelled hold offered for confirmation breaks a state rule and a money rule;
an under-qualified rider offered the last seat of a full slot breaks a safety
rule and a capacity rule.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions
from test_helpers.api_errors import ApiErrorId
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


class TestStateGateOutranksTheDepositGate:
    """A cancelled booking reports its state, never its unpaid deposit."""

    def _cancelled_unpaid_hold(self, client):
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
        ben = build_guest(client, "Ben Adult", "1983-07-11", 190)
        cal = build_guest(client, "Cal Child", "2016-05-20", 95)
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
            arrival_date="2026-10-11",
            departure_date="2026-10-18",
        )
        assert booking["deposit_paid_cents"] == 0
        validate_success(
            client.cancel_booking(
                booking["id"], "guest never paid the deposit", RESERVATIONS_AGENT
            )
        )
        return booking

    def test_confirming_a_cancelled_unpaid_hold_reports_the_booking_state(self, client):
        """Both gates would fire, and the state gate is the one that answers.

        PRD: "Because the state gate outranks the money gate, a booking that has
        already been cancelled or checked in reports its state and not its
        deposit."

        Design: Difficulty/priority_pair_validation_conflict/booking_state_gate_at_18_beats_deposit_money_gate_at_66
        """
        booking = self._cancelled_unpaid_hold(client)
        error = validate_error(
            client.confirm_booking(booking["id"], RESERVATIONS_AGENT),
            ApiErrorId.ERR_BOOKING_STATE_INVALID.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_DEPOSIT_INSUFFICIENT.value

    def test_the_refused_confirmation_leaves_the_unpaid_deposit_untouched(self, client):
        """The cancelled hold keeps a zero deposit against its full requirement.

        PRD: "A booking cancelled while nothing had yet been collected —
        `deposit_paid_cents` at 0, `payment_status` still `AWAITING_DEPOSIT` —
        moves to `FORFEITED` with both `refunded_cents` and `forfeited_cents` at
        0, since the conserved total is itself 0."

        Design: Difficulty/priority_pair_validation_conflict/booking_state_gate_at_18_beats_deposit_money_gate_at_66
        """
        booking = self._cancelled_unpaid_hold(client)
        validate_error(
            client.confirm_booking(booking["id"], RESERVATIONS_AGENT),
            ApiErrorId.ERR_BOOKING_STATE_INVALID.value,
            409,
        )
        after = validate_success(client.get_booking(booking["id"], RESERVATIONS_AGENT))
        assert after["booking_status"] == "CANCELLED"
        assert after["payment_status"] == "FORFEITED"
        assert after["deposit_paid_cents"] == 0
        assert after["deposit_required_cents"] == 377607
        assertions.assert_cancellation_split_is_conservative(after)


class TestRiderAbilityGateOutranksTheCapacityGate:
    """A full slot a rider cannot ride reports the ability failure."""

    def _full_intermediate_hike(self, client):
        season = build_open_season(client)
        cabin = build_cabin(client, name="Aspen", bed_capacity=4)
        ann = build_ready_rider(client, "Ann Adult", "1985-04-02", 165, "INTERMEDIATE")
        ben = build_ready_rider(client, "Ben Adult", "1983-07-11", 190, "BEGINNER")
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            [
                party_member(ann["id"], "ADULT"),
                party_member(ben["id"], "ADULT"),
            ],
            package_tier_code="CLASSIC",
            arrival_date="2026-10-11",
            departure_date="2026-10-18",
        )
        slot = build_activity_slot(
            client,
            season["id"],
            activity_type="HIKE",
            starts_at="2026-10-12T15:00:00Z",
            ends_at="2026-10-12T17:00:00Z",
            terrain_grade="MEADOW",
            min_ability_rank="INTERMEDIATE",
            capacity=1,
            rider_surcharge_cents=20000,
            mount_required=False,
        )
        take_seat(client, slot["id"], booking["id"], ann["id"])
        slot = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        assert slot["seats_available"] == 0
        return booking, slot, ben

    def test_a_beginner_offered_a_full_intermediate_slot_reports_the_ability(self, client):
        """Capacity is exhausted and the rank is too low, and the rank answers.

        PRD: "A full slot that a rider is too inexperienced to ride therefore
        answers with the ability failure, never with the capacity failure."

        Design: Difficulty/priority_pair_validation_conflict/rider_ability_safety_gate_at_30_beats_slot_capacity_gate_at_57
        """
        booking, slot, ben = self._full_intermediate_hike(client)
        error = validate_error(
            client.create_reservation(
                slot["id"],
                reservation_payload(booking["id"], ben["id"], slot["version"]),
                RESERVATIONS_AGENT,
            ),
            ApiErrorId.ERR_RIDER_ABILITY_INSUFFICIENT.value,
            422,
        )
        assert error["error_id"] != ApiErrorId.ERR_SLOT_FULL.value

    def test_the_refused_seat_leaves_the_slot_holding_its_single_rider(self, client):
        """No second seat is written, so the roster is unchanged.

        PRD: "Because it is the point where four entities meet, seat creation is
        the most heavily gated write in the system, and the order in which its
        gates fire is normative — the safety gates run first, and only after
        every one of them has passed does the system look at capacity."

        Design: Difficulty/priority_pair_validation_conflict/rider_ability_safety_gate_at_30_beats_slot_capacity_gate_at_57
        """
        booking, slot, ben = self._full_intermediate_hike(client)
        validate_error(
            client.create_reservation(
                slot["id"],
                reservation_payload(booking["id"], ben["id"], slot["version"]),
                RESERVATIONS_AGENT,
            ),
            ApiErrorId.ERR_RIDER_ABILITY_INSUFFICIENT.value,
            422,
        )
        after = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        assertions.assert_slot_counters(
            after, confirmed_rider_count=1, seats_available=0
        )
        rows, meta = validate_paginated(
            client.list_reservations(RESERVATIONS_AGENT, {"slot_id": slot["id"]})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
