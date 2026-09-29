"""Compensating actions that must restore an aggregate exactly, not roughly.

Reversing an approved point transfer has to put the donor pair's
certified-points total back where it started, and releasing a held seat has to
put the section's seat-inventory quadruple back where it started.
"""

from decimal import Decimal

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_donor_points,
    assert_instant,
    assert_points,
    assert_seat_inventory,
    validate_success,
)
from test_helpers.constants import (
    BASIS_DEATH,
    DONOR_DECEASED,
    NON_ALUMNUS,
    OCCUPANCY_RELEASED,
    RELEASE_DONOR_RELEASE,
    SEAT_AVAILABLE,
    SLOT_FORFEITED,
    TRANSFER_REVERSED,
)
from test_helpers.fixtures import (
    add_received_gift,
    advance_occupancy,
    certified_cycle,
    change_status,
    create_section_with_seats,
    publish_and_open,
    read_assignment,
    read_donor,
    read_event,
    read_seat,
    read_section,
    read_slot,
    register_donor,
    request_transfer_ok,
    set_clock,
    slot_for_donor,
)
from test_helpers.test_users import CERTIFIER, OFFICER, make_donor_headers

REVERSAL_REASON = "Estate settlement reversed the designation."


def _requested_death_transfer(client):
    """A REQUESTED 40.00-point DEATH transfer between a 67.50 and a 60.00 donor."""
    set_clock(client, f.instant(2026, 4, 1))
    source = register_donor(client, alumni_status=NON_ALUMNUS)
    recipient = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, source["id"], 5000000, f.instant(2026, 3, 1))
    add_received_gift(client, recipient["id"], 4500000, f.instant(2026, 3, 1))
    certified_cycle(client, 2026)

    change_status(client, source, DONOR_DECEASED, f.instant(2026, 7, 1))
    transfer = request_transfer_ok(
        client, source["id"], recipient["id"], BASIS_DEATH, 40.00
    )
    return source, recipient, transfer


def _pair_total(client, source, recipient):
    left = Decimal(str(read_donor(client, source["id"])["certified_points"]))
    right = Decimal(str(read_donor(client, recipient["id"])["certified_points"]))
    return left + right


class TestTransferReversalConservesThePairTotal:
    """Approve then reverse restores both donors to the cent."""

    def test_the_pair_total_survives_the_approval(self, client):
        """Moving 40.00 across the pair redistributes but does not create points.

        PRD 3.4: "On success it adds `points_amount` to the recipient's
        `transferred_points_in` and the same amount to the source's
        `transferred_points_out`, recomputes `certified_points` for both donors,
        and stamps `approved_by_user_id` with the certifier's `X-User-ID`."

        Design: Difficulty/compensating_invariant/transfer_approve_then_reverse_conserves_certified_points_sum
        """
        source, recipient, transfer = _requested_death_transfer(client)

        assert_donor_points(
            read_donor(client, source["id"]), certified_points="67.50", label="source"
        )
        assert_donor_points(
            read_donor(client, recipient["id"]),
            certified_points="60.00",
            label="recipient",
        )
        before = _pair_total(client, source, recipient)

        validate_success(
            client.approve_point_transfer(transfer["id"], headers=CERTIFIER)
        )

        assert_donor_points(
            read_donor(client, source["id"]), certified_points="27.50", label="source"
        )
        assert_donor_points(
            read_donor(client, recipient["id"]),
            certified_points="100.00",
            label="recipient",
        )
        assert _pair_total(client, source, recipient) == before

    def test_the_reversal_restores_both_donors_exactly(self, client):
        """The compensating edge returns each donor to its pre-transfer figure.

        PRD 3.4: "It subtracts `points_amount` from the recipient's
        `transferred_points_in` and from the source's `transferred_points_out`,
        recomputes `certified_points` for both donors — restoring the
        pre-transfer total across the pair **exactly**, which is the invariant
        the compensating design exists to guarantee — restores
        `eligibility_status` to `ELIGIBLE` on every seat assignment whose donor
        once again meets that row's `required_points`, recomputes
        `underwater_seat_count` and `pricing_posture` on the affected sections,
        stamps `reversed_at` with the current logical clock instant, records the
        supplied reason as `decision_note`, and advances the transfer's
        `version` and both donors' `version` values by 1."

        Design: Difficulty/compensating_invariant/transfer_approve_then_reverse_conserves_certified_points_sum
        """
        source, recipient, transfer = _requested_death_transfer(client)
        before = _pair_total(client, source, recipient)

        client.approve_point_transfer(transfer["id"], headers=CERTIFIER)
        validate_success(
            client.reverse_point_transfer(
                transfer["id"], f.reverse_transfer_payload(), headers=CERTIFIER
            )
        )

        assert_donor_points(
            read_donor(client, source["id"]),
            certified_points="67.50",
            transferred_points_out="0.00",
            transferred_points_in="0.00",
            label="source",
        )
        assert_donor_points(
            read_donor(client, recipient["id"]),
            certified_points="60.00",
            transferred_points_in="0.00",
            transferred_points_out="0.00",
            label="recipient",
        )
        assert _pair_total(client, source, recipient) == before

    def test_the_base_points_were_never_re_derived(self, client):
        """Neither the transfer nor its reversal touches certified_base_points.

        PRD 3.3: "`certified_base_points` is never re-derived outside a
        recalculation run, which is precisely why moving a donor to `DECEASED`
        does not retroactively strip the alumni bonus out of a cycle that has
        already been certified."

        Design: Difficulty/compensating_invariant/transfer_approve_then_reverse_conserves_certified_points_sum
        """
        source, recipient, transfer = _requested_death_transfer(client)

        client.approve_point_transfer(transfer["id"], headers=CERTIFIER)
        client.reverse_point_transfer(
            transfer["id"], f.reverse_transfer_payload(), headers=CERTIFIER
        )

        assert_donor_points(
            read_donor(client, source["id"]),
            certified_base_points="67.50",
            label="source",
        )
        assert_donor_points(
            read_donor(client, recipient["id"]),
            certified_base_points="60.00",
            label="recipient",
        )

    def test_the_reversed_transfer_keeps_its_amount_and_records_the_reason(self, client):
        """REVERSED is history: the amount stays and the reason is stored.

        PRD 3.4: "`REVERSED` is terminal; a reversed transfer is history, not a
        request that can be re-approved."

        Design: Difficulty/compensating_invariant/transfer_approve_then_reverse_conserves_certified_points_sum
        """
        _source, _recipient, transfer = _requested_death_transfer(client)

        client.approve_point_transfer(transfer["id"], headers=CERTIFIER)
        reversed_row = validate_success(
            client.reverse_point_transfer(
                transfer["id"], f.reverse_transfer_payload(), headers=CERTIFIER
            )
        )

        assert reversed_row["status"] == TRANSFER_REVERSED
        assert_points(
            reversed_row["points_amount"], "40.00", "transfer.points_amount"
        )
        assert reversed_row["decision_note"] == REVERSAL_REASON
        assert_instant(reversed_row["reversed_at"], "2026-04-01T00:00:00.000Z")


def _held_seat_in_a_three_seat_section(client):
    """One donor holding J/1 in a three-seat section, plus the pre-pick reading."""
    set_clock(client, f.instant(2026, 4, 1))
    section, seats = create_section_with_seats(
        client,
        [("J", 1), ("J", 2), ("J", 3)],
        seat_capacity=3,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    slot = slot_for_donor(client, event["id"], donor["id"])

    before = read_section(client, section["id"])
    set_clock(client, f.instant(2026, 9, 1, 12))
    assignment = validate_success(
        client.pick_seat(
            slot["id"],
            f.pick_payload(seats[0]["id"], read_seat(client, seats[0]["id"])["version"]),
            headers=make_donor_headers(donor["id"]),
        ),
        201,
    )
    return section, seats[0], event, slot, assignment, before


class TestSeatReleaseRestoresTheSectionInventory:
    """A pick and its release are a compensating pair on the seat quadruple."""

    def test_the_pick_shifts_one_seat_from_available_to_committed(self, client):
        """3/0/0/3 becomes 2/1/0/3 and the sum invariant still holds.

        PRD 3.9: "On success the seat moves `AVAILABLE → HELD`, one seat shifts
        out of the section's `seats_available` and into its
        `seats_committed_count`, the event's `scheduled_slot_count` decrements,
        and the `version` of the seat, the section and the slot each advance by
        1."

        Design: Difficulty/compensating_invariant/pick_then_release_conserves_section_seat_inventory
        """
        section, _seat, _event, _slot, _assignment, before = (
            _held_seat_in_a_three_seat_section(client)
        )

        assert_seat_inventory(
            before,
            seats_available=3,
            seats_committed_count=0,
            decommissioned_seat_count=0,
            seat_row_count=3,
            label="section before the pick",
        )
        assert_seat_inventory(
            read_section(client, section["id"]),
            seats_available=2,
            seats_committed_count=1,
            decommissioned_seat_count=0,
            seat_row_count=3,
            label="section after the pick",
        )

    def test_the_release_restores_the_quadruple_exactly(self, client):
        """Releasing the hold returns every counter to its pre-pick value.

        PRD 3.9: "It sets `release_reason` from the payload, defaulting to
        `DONOR_RELEASE` when the caller supplies none; it returns the seat from
        `HELD` to `AVAILABLE` and restores the
        section's seat inventory counters to their pre-pick values, moving one
        seat from `seats_committed_count` back to `seats_available` and advancing
        both the seat's and the section's `version` by 1; and it walks the
        consuming slot from `CONSUMED` back to `FORFEITED`, advancing that slot's
        `version` by 1."

        Design: Difficulty/compensating_invariant/pick_then_release_conserves_section_seat_inventory
        """
        section, seat, _event, _slot, assignment, _before = (
            _held_seat_in_a_three_seat_section(client)
        )

        advance_occupancy(
            client,
            assignment["id"],
            OCCUPANCY_RELEASED,
            headers=OFFICER,
            release_reason=RELEASE_DONOR_RELEASE,
        )

        assert_seat_inventory(
            read_section(client, section["id"]),
            seats_available=3,
            seats_committed_count=0,
            decommissioned_seat_count=0,
            assigned_seat_count=0,
            seat_row_count=3,
            label="section after the release",
        )
        assert read_seat(client, seat["id"])["seat_status"] == SEAT_AVAILABLE

    def test_the_release_walks_the_consuming_slot_to_forfeited(self, client):
        """CONSUMED is not a lockdown state: the slot moves to the other terminal.

        PRD 3.9: "That last step is worth dwelling on: `CONSUMED` looks terminal
        but is not a lockdown state, and a release moves the slot to the *other*
        terminal state rather than restoring the donor's turn."

        Design: Difficulty/compensating_invariant/pick_then_release_conserves_section_seat_inventory
        """
        _section, _seat, event, slot, assignment, _before = (
            _held_seat_in_a_three_seat_section(client)
        )

        advance_occupancy(
            client,
            assignment["id"],
            OCCUPANCY_RELEASED,
            headers=OFFICER,
            release_reason=RELEASE_DONOR_RELEASE,
        )

        released = read_assignment(client, assignment["id"])
        assert released["occupancy_status"] == OCCUPANCY_RELEASED
        assert released["release_reason"] == RELEASE_DONOR_RELEASE
        assert read_slot(client, slot["id"])["slot_status"] == SLOT_FORFEITED
        assert read_event(client, event["id"])["scheduled_slot_count"] == 0
