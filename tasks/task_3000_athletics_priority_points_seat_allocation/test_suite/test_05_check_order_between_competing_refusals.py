"""Requests that break two rules at once, and which refusal wins.

Section 2.8 fixes the evaluation order, so a relocation filed against a draft
event on an unpaid seat reports the event first, and a pick outside its slot
window on an occupied seat reports the window first.
"""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_EVENT_NOT_OPEN_FOR_REQUESTS,
    ERR_OUTSIDE_SLOT_WINDOW,
    ERR_SEAT_DONATION_SHORTFALL,
    ERR_SEAT_NOT_AVAILABLE,
)
from test_helpers.assertions import (
    assert_page_meta,
    validate_error,
    validate_list,
    validate_success,
)
from test_helpers.constants import (
    EVENT_SLOTS_PUBLISHED,
    NON_ALUMNUS,
    PAYMENT_INVOICED,
    PAYMENT_PAID,
    PAYMENT_UNBILLED,
    RELOCATION_AWAITING_SELECTION,
    SEAT_ASSIGNED,
    SEAT_AVAILABLE,
    SLOT_SCHEDULED,
)
from test_helpers.fixtures import (
    bill,
    certified_cycle,
    confirm_assignment,
    create_event,
    create_section_with_seats,
    file_relocation_request,
    pick_seat,
    pick_through_event,
    publish_and_open,
    publish_slots,
    read_donor,
    read_event,
    read_seat,
    read_section,
    read_slot,
    register_donor,
    set_clock,
    slot_for_donor,
)
from test_helpers.test_users import OFFICER


def _unpaid_seat_and_draft_event(client):
    """A donor holding an unbilled seat, plus a second event still in DRAFT."""
    set_clock(client, f.instant(2026, 4, 1))
    section, seats = create_section_with_seats(
        client,
        [("H", 1), ("H", 2)],
        seat_capacity=2,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    cycle = certified_cycle(client, 2026)

    first_event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    set_clock(client, f.instant(2026, 9, 1, 12))
    assignment = pick_through_event(client, first_event["id"], seats[0]["id"], donor["id"])
    assert assignment["payment_status"] == PAYMENT_UNBILLED

    second_event = create_event(
        client, cycle["id"], f.instant(2026, 9, 10), f.instant(2026, 9, 14), 2880
    )
    return section, donor, assignment, second_event


class TestRelocationEventStatusBeatsTheMoney:
    """The event gate is checked before the assignment's balance."""

    def test_a_draft_target_event_is_reported_before_the_unpaid_balance(self, client):
        """Both rules are broken; the event status is the one that answers.

        PRD 3.9: "The named event must be in `SLOTS_PUBLISHED` or `OPEN`; an
        event in any other status, `SLOTS_STALE` included, is refused with
        `ERR_EVENT_NOT_OPEN_FOR_REQUESTS`."

        Design: Difficulty/priority_pair_validation_conflict/relocation_create_state_beats_fiscal
        """
        section, donor, assignment, second_event = _unpaid_seat_and_draft_event(client)

        refused = file_relocation_request(
            client, donor["id"], assignment["id"], section["id"], second_event["id"]
        )
        validate_error(refused, ERR_EVENT_NOT_OPEN_FOR_REQUESTS, 409)

    def test_publishing_the_event_reveals_the_shortfall_underneath(self, client):
        """With the event admissible, the unpaid balance is what refuses.

        PRD 3.9: "The donor's current assignment must also be fully paid —
        filing while it still owes money is refused with
        `ERR_SEAT_DONATION_SHORTFALL`."

        Design: Difficulty/priority_pair_validation_conflict/relocation_create_state_beats_fiscal
        """
        section, donor, assignment, second_event = _unpaid_seat_and_draft_event(client)
        publish_slots(client, second_event["id"])

        refused = file_relocation_request(
            client, donor["id"], assignment["id"], section["id"], second_event["id"]
        )
        validate_error(refused, ERR_SEAT_DONATION_SHORTFALL, 402)

        assert (
            read_event(client, second_event["id"])["status"] == EVENT_SLOTS_PUBLISHED
        )

    def test_paying_the_row_lets_the_identical_filing_through(self, client):
        """The third attempt differs from the second only in the money.

        PRD 3.9: "The new request lands in `AWAITING_SELECTION` with
        `granted_seat_assignment_id` and `decision_note` null, and the donor's
        `version` advances by 1."

        Design: Difficulty/priority_pair_validation_conflict/relocation_create_state_beats_fiscal
        """
        section, donor, assignment, second_event = _unpaid_seat_and_draft_event(client)
        publish_slots(client, second_event["id"])
        bill(client, assignment["id"], PAYMENT_INVOICED)
        bill(client, assignment["id"], PAYMENT_PAID, amount_cents=100000)

        created = validate_success(
            file_relocation_request(
                client, donor["id"], assignment["id"], section["id"], second_event["id"]
            ),
            expected_status=201,
        )
        assert created["status"] == RELOCATION_AWAITING_SELECTION
        assert created["granted_seat_assignment_id"] is None
        assert read_donor(client, donor["id"])["pending_request_count"] == 1

    def test_only_the_successful_filing_is_discoverable_on_the_list(self, client):
        """The two refusals left no rows behind them.

        PRD 2.9: "`pending_request_count` tracks the number of the donor's
        relocation requests currently in `AWAITING_SELECTION`"

        Design: Difficulty/priority_pair_validation_conflict/relocation_create_state_beats_fiscal
        """
        section, donor, assignment, second_event = _unpaid_seat_and_draft_event(client)
        publish_slots(client, second_event["id"])
        bill(client, assignment["id"], PAYMENT_INVOICED)
        bill(client, assignment["id"], PAYMENT_PAID, amount_cents=100000)
        validate_success(
            file_relocation_request(
                client, donor["id"], assignment["id"], section["id"], second_event["id"]
            ),
            expected_status=201,
        )

        rows, meta = validate_list(
            client.list_relocation_requests(
                headers=OFFICER, params={"donor_id": donor["id"]}
            )
        )
        assert len(rows) == 1
        assert_page_meta(meta, total_count=1, has_more=False)


def _occupied_seat_and_a_later_slot(client):
    """The first donor's seat is confirmed; the second donor's turn is later."""
    set_clock(client, f.instant(2026, 4, 1))
    _section, seats = create_section_with_seats(
        client,
        [("G", 1), ("G", 2)],
        seat_capacity=2,
        per_seat_requirement_cents=100000,
        required_points_per_seat=0.00,
    )
    first = register_donor(client, alumni_status=NON_ALUMNUS)
    second = register_donor(client, alumni_status=NON_ALUMNUS)
    cycle = certified_cycle(client, 2026)
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )

    set_clock(client, f.instant(2026, 9, 1, 12))
    assignment = pick_through_event(client, event["id"], seats[0]["id"], first["id"])
    confirm_assignment(client, assignment["id"])

    later_slot = slot_for_donor(client, event["id"], second["id"])
    return _section, seats, second, later_slot


class TestPickWindowBeatsSeatAvailability:
    """The slot window is checked before the seat's own state."""

    def test_a_pick_outside_the_window_reports_the_window(self, client):
        """Past the whole event, the window refusal wins over the taken seat.

        PRD 3.8: "Each slot is **half-open**, including `slot_start` and
        excluding `slot_end`: a pick at exactly `slot_end` belongs to the next
        slot, never to this one, and is rejected against this slot with
        `ERR_OUTSIDE_SLOT_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/pick_temporal_beats_constraint
        """
        _section, seats, second, later_slot = _occupied_seat_and_a_later_slot(client)

        set_clock(client, f.instant(2026, 9, 6))
        refused = pick_seat(client, later_slot["id"], seats[0]["id"], second["id"])
        validate_error(refused, ERR_OUTSIDE_SLOT_WINDOW, 422)

    def test_inside_the_window_the_seat_state_refuses_instead(self, client):
        """Same request, same seat, only the clock differs.

        PRD 3.8: "A seat already `ASSIGNED`, or one that has been
        `DECOMMISSIONED`, is refused with `ERR_SEAT_NOT_AVAILABLE`."

        Design: Difficulty/priority_pair_validation_conflict/pick_temporal_beats_constraint
        """
        _section, seats, second, later_slot = _occupied_seat_and_a_later_slot(client)

        set_clock(client, f.instant(2026, 9, 3, 12))
        refused = pick_seat(client, later_slot["id"], seats[0]["id"], second["id"])
        validate_error(refused, ERR_SEAT_NOT_AVAILABLE, 409)

    def test_neither_refusal_disturbs_the_slot_or_the_inventory(self, client):
        """Two rejected picks leave the schedule and the seats exactly as they were.

        PRD 3.8: "A slot's four states are `SCHEDULED`, `STALE`, `CONSUMED` and
        `FORFEITED`, of which `CONSUMED` and `FORFEITED` are terminal."

        Design: Difficulty/priority_pair_validation_conflict/pick_temporal_beats_constraint
        """
        section, seats, second, later_slot = _occupied_seat_and_a_later_slot(client)

        set_clock(client, f.instant(2026, 9, 6))
        pick_seat(client, later_slot["id"], seats[0]["id"], second["id"])
        set_clock(client, f.instant(2026, 9, 3, 12))
        pick_seat(client, later_slot["id"], seats[0]["id"], second["id"])

        assert read_slot(client, later_slot["id"])["slot_status"] == SLOT_SCHEDULED
        assert read_seat(client, seats[0]["id"])["seat_status"] == SEAT_ASSIGNED
        assert read_seat(client, seats[1]["id"])["seat_status"] == SEAT_AVAILABLE
        assert read_section(client, section["id"])["assigned_seat_count"] == 1

        rows, meta = validate_list(
            client.list_seat_assignments(
                headers=OFFICER, params={"donor_id": second["id"]}
            )
        )
        assert rows == []
        assert_page_meta(meta, total_count=0, has_more=False)
