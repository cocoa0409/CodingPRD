"""State machines that are not simple forward chains.

A dispute can leave and re-enter UNDER_REVIEW, and a seat assignment carries
two independent status axes on one row.  Both shapes are exercised end to end.
"""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_INFO_REQUEST_LIMIT_REACHED
from test_helpers.assertions import (
    assert_cents,
    assert_points,
    assert_seat_inventory,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    ALUMNUS,
    DISPUTE_INFO_REQUESTED,
    DISPUTE_UNDER_REVIEW,
    NON_ALUMNUS,
    OCCUPANCY_ASSIGNED,
    OCCUPANCY_HELD,
    OCCUPANCY_RELEASED,
    PAYMENT_INVOICED,
    PAYMENT_PAID,
    PAYMENT_UNBILLED,
    RELEASE_DONOR_RELEASE,
    SEAT_AVAILABLE,
    SLOT_CONSUMED,
)
from test_helpers.fixtures import (
    add_received_gift,
    advance_occupancy,
    bill,
    certified_cycle,
    communicated_cycle,
    create_section_with_seats,
    file_dispute,
    pick_through_event,
    publish_and_open,
    read_dispute,
    read_donor,
    read_seat,
    read_section,
    read_slot,
    register_donor,
    set_clock,
    slot_for_donor,
)
from test_helpers.test_users import ANALYST, ANALYST_USER_ID, make_donor_headers


def _disputed_cycle(client):
    """A communicated 2026 cycle with one dispute taken under review."""
    set_clock(client, f.instant(2026, 8, 1))
    donor = register_donor(client, alumni_status=ALUMNUS)
    add_received_gift(client, donor["id"], 2000000, f.instant(2026, 3, 1))
    cycle = communicated_cycle(client, 2026)

    dispute = file_dispute(client, donor["id"], cycle["id"], 10.00)
    reviewed = validate_success(client.review_dispute(dispute["id"], headers=ANALYST))
    assert reviewed["status"] == DISPUTE_UNDER_REVIEW
    return donor, cycle, dispute


def _complete_information_round(client, dispute_id, donor_id):
    """One full request/answer loop: UNDER_REVIEW -> INFO_REQUESTED -> UNDER_REVIEW."""
    requested = validate_success(
        client.request_dispute_info(
            dispute_id, f.request_info_payload(), headers=ANALYST
        )
    )
    assert requested["status"] == DISPUTE_INFO_REQUESTED
    answered = validate_success(
        client.provide_dispute_info(
            dispute_id, f.provide_info_payload(), headers=make_donor_headers(donor_id)
        )
    )
    return answered


class TestDisputeInformationCycle:
    """The information loop is a genuine cycle with a hard round cap."""

    def test_answering_an_information_request_returns_the_dispute_to_review(
        self, client
    ):
        """Two complete loops leave the dispute back in UNDER_REVIEW.

        PRD 3.4: "This is a genuine cycle: the dispute can leave and re-enter
        `UNDER_REVIEW`, and the second completed loop exhausts the cap."

        Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_returns_to_under_review
        """
        donor, _cycle, dispute = _disputed_cycle(client)

        first = _complete_information_round(client, dispute["id"], donor["id"])
        assert first["status"] == DISPUTE_UNDER_REVIEW
        assert first["info_request_rounds"] == 1

        second = _complete_information_round(client, dispute["id"], donor["id"])
        assert second["status"] == DISPUTE_UNDER_REVIEW
        assert second["info_request_rounds"] == 2

    def test_a_third_information_request_is_refused_at_the_cap(self, client):
        """The cap of two completed rounds closes the loop for good.

        PRD 3.4: "A third attempt, on a dispute that has already completed 2
        rounds, is rejected with `ERR_INFO_REQUEST_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_returns_to_under_review
        """
        donor, _cycle, dispute = _disputed_cycle(client)
        _complete_information_round(client, dispute["id"], donor["id"])
        _complete_information_round(client, dispute["id"], donor["id"])

        refused = client.request_dispute_info(
            dispute["id"], f.request_info_payload(), headers=ANALYST
        )
        validate_error(refused, ERR_INFO_REQUEST_LIMIT_REACHED, 422)

        unchanged = read_dispute(client, dispute["id"])
        assert unchanged["status"] == DISPUTE_UNDER_REVIEW
        assert unchanged["info_request_rounds"] == 2

    def test_the_first_reviewer_remains_the_recorded_comparand(self, client):
        """reviewed_by_user_id is stamped on the first review and never moves.

        PRD 3.4: "That first reviewer's identity is the comparand the eventual
        decision is measured against, which is why it is stamped once and never
        overwritten."

        Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_returns_to_under_review
        """
        donor, _cycle, dispute = _disputed_cycle(client)
        _complete_information_round(client, dispute["id"], donor["id"])
        _complete_information_round(client, dispute["id"], donor["id"])

        worked = read_dispute(client, dispute["id"])
        assert worked["reviewed_by_user_id"] == ANALYST_USER_ID
        assert worked["decided_by_user_id"] is None

    def test_working_the_loop_moves_no_points(self, client):
        """Only a decision touches the donor's dispute adjustment.

        PRD 3.4: "The new dispute lands in `SUBMITTED` with
        `info_request_rounds` at 0, `reviewed_by_user_id`,
        `decided_by_user_id`, `granted_points_delta` and `decided_at` all
        null."

        Design: Difficulty/non_linear_state_machine/dispute_info_request_cycle_returns_to_under_review
        """
        donor, _cycle, dispute = _disputed_cycle(client)
        _complete_information_round(client, dispute["id"], donor["id"])

        scored = read_donor(client, donor["id"])
        assert_points(
            scored["dispute_adjustment_points"], "0.00", "dispute_adjustment_points"
        )
        assert read_dispute(client, dispute["id"])["granted_points_delta"] is None


def _held_seat(client):
    """One donor holding one seat in a single-seat section, freshly picked."""
    set_clock(client, f.instant(2026, 4, 1))
    section, seats = create_section_with_seats(
        client,
        [("P", 1)],
        seat_capacity=1,
        per_seat_requirement_cents=250000,
        required_points_per_seat=0.00,
    )
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    set_clock(client, f.instant(2026, 9, 1, 12))
    slot = slot_for_donor(client, event["id"], donor["id"])
    assignment = pick_through_event(client, event["id"], seats[0]["id"], donor["id"])
    return section, seats[0], donor, slot, assignment


class TestSeatAssignmentParallelAxes:
    """Occupancy and payment advance on the same row without constraining each other."""

    def test_a_row_can_be_fully_paid_while_still_only_held(self, client):
        """The money axis runs ahead of the occupancy axis.

        PRD 3.9: "A row can be `RELEASED` while still `INVOICED`, or `PAID`
        while still merely `HELD`; each axis is advanced by its own call and
        neither call reads the other axis except where this document says so
        explicitly."

        Design: Difficulty/non_linear_state_machine/seat_assignment_parallel_occupancy_and_payment_dimensions
        """
        _section, _seat, _donor, _slot, assignment = _held_seat(client)

        assert assignment["occupancy_status"] == OCCUPANCY_HELD
        assert assignment["payment_status"] == PAYMENT_UNBILLED
        assert_cents(assignment["amount_paid_cents"], 0, "amount_paid_cents")

        invoiced = bill(client, assignment["id"], PAYMENT_INVOICED)
        assert invoiced["payment_status"] == PAYMENT_INVOICED
        assert invoiced["occupancy_status"] == OCCUPANCY_HELD

        paid = bill(client, assignment["id"], PAYMENT_PAID, amount_cents=250000)
        assert paid["payment_status"] == PAYMENT_PAID
        assert paid["occupancy_status"] == OCCUPANCY_HELD
        assert_cents(paid["amount_paid_cents"], 250000, "amount_paid_cents")

    def test_occupancy_then_advances_to_assigned_and_on_to_released(self, client):
        """Confirmation and release walk the occupancy axis on their own.

        PRD 3.9: "`occupancy_status` tracks who physically holds the seat and
        runs `HELD → ASSIGNED → RELEASED`, with `RELEASED` terminal."

        Design: Difficulty/non_linear_state_machine/seat_assignment_parallel_occupancy_and_payment_dimensions
        """
        _section, seat, _donor, _slot, assignment = _held_seat(client)
        bill(client, assignment["id"], PAYMENT_INVOICED)
        bill(client, assignment["id"], PAYMENT_PAID, amount_cents=250000)

        confirmed = advance_occupancy(client, assignment["id"], OCCUPANCY_ASSIGNED)
        assert confirmed["occupancy_status"] == OCCUPANCY_ASSIGNED
        assert confirmed["payment_status"] == PAYMENT_PAID

        released = advance_occupancy(
            client,
            assignment["id"],
            OCCUPANCY_RELEASED,
            release_reason=RELEASE_DONOR_RELEASE,
        )
        assert released["occupancy_status"] == OCCUPANCY_RELEASED
        assert released["release_reason"] == RELEASE_DONOR_RELEASE
        assert released["payment_status"] == PAYMENT_PAID
        assert_cents(released["total_due_cents"], 250000, "total_due_cents")
        assert_cents(released["amount_paid_cents"], 250000, "amount_paid_cents")

    def test_release_restores_the_seat_inventory_but_not_the_money(self, client):
        """The seat returns to AVAILABLE while amount_paid_cents stands.

        PRD 3.9: "Releasing a confirmed assignment moves `ASSIGNED → RELEASED`
        and requires the row to be in `ASSIGNED` with a matching version
        stamp."

        Design: Difficulty/non_linear_state_machine/seat_assignment_parallel_occupancy_and_payment_dimensions
        """
        section, seat, _donor, _slot, assignment = _held_seat(client)
        bill(client, assignment["id"], PAYMENT_INVOICED)
        bill(client, assignment["id"], PAYMENT_PAID, amount_cents=250000)
        advance_occupancy(client, assignment["id"], OCCUPANCY_ASSIGNED)

        held_seat_row = read_seat(client, seat["id"])
        assert held_seat_row["seat_status"] != SEAT_AVAILABLE

        advance_occupancy(
            client,
            assignment["id"],
            OCCUPANCY_RELEASED,
            release_reason=RELEASE_DONOR_RELEASE,
        )

        assert read_seat(client, seat["id"])["seat_status"] == SEAT_AVAILABLE
        assert_seat_inventory(
            read_section(client, section["id"]),
            seats_available=1,
            seats_committed_count=0,
            assigned_seat_count=0,
            seat_row_count=1,
        )

    def test_releasing_a_confirmed_row_leaves_the_slot_consumed(self, client):
        """Only a release from HELD walks the slot back to FORFEITED.

        PRD 3.9: "and it walks the consuming slot from `CONSUMED` back to
        `FORFEITED`, advancing that slot's `version` by 1."

        Design: Difficulty/non_linear_state_machine/seat_assignment_parallel_occupancy_and_payment_dimensions
        """
        _section, _seat, _donor, slot, assignment = _held_seat(client)
        bill(client, assignment["id"], PAYMENT_INVOICED)
        bill(client, assignment["id"], PAYMENT_PAID, amount_cents=250000)
        advance_occupancy(client, assignment["id"], OCCUPANCY_ASSIGNED)
        advance_occupancy(
            client,
            assignment["id"],
            OCCUPANCY_RELEASED,
            release_reason=RELEASE_DONOR_RELEASE,
        )

        assert read_slot(client, slot["id"])["slot_status"] == SLOT_CONSUMED
