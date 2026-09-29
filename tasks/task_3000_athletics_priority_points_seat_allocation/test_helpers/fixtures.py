"""Composite setup builders and the pytest fixtures that expose them.

Every builder here drives the public API only - there is no direct database
access anywhere in this suite.  Builders use ``get_success_data`` so that a
setup step which the PRD allows to answer 200 or 201 does not have to be
pinned to one of the two at every call site.

The builders are deliberately *phased*: ``create_section_with_seats`` leaves
the section in ``OPEN`` with every seat ``AVAILABLE``, ``publish_and_open``
leaves the event ``OPEN``, and nothing a builder does at its last step
invalidates a precondition an earlier step of the same builder established.
That keeps them safe to compose and to reuse inside one test.
"""

import pytest

from .api_client import ApiClient
from .assertions import get_success_data
from .constants import (
    ACTION_REPRICE,
    ACTION_START_RESEATING,
    ACTION_SURVEY,
    CLOCK_INITIAL_INSTANT,
    EVENT_OPEN,
    GIFT_RECEIVED,
    OCCUPANCY_ASSIGNED,
    PAYMENT_INVOICED,
    PAYMENT_PAID,
)
from . import factories as f
from .test_users import ADMIN, CERTIFIER, OFFICER, make_donor_headers

# ─── pytest fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def client():
    """A client bound to the service under test."""
    return ApiClient()


@pytest.fixture
def api(client):
    """Alias kept so a test can read either name."""
    return client


# ─── Logical clock ────────────────────────────────────────────────────────


def set_clock(client, to_iso8601, headers=ADMIN):
    """Move the logical clock and return the instant it now reads."""
    response = client.set_clock(to_iso8601, headers=headers)
    assert response.status_code in (200, 201), (
        "setting the logical clock to {0} failed with {1}: {2}".format(
            to_iso8601, response.status_code, response.text
        )
    )
    return to_iso8601


def reset_clock(client, headers=ADMIN):
    return set_clock(client, CLOCK_INITIAL_INSTANT, headers=headers)


# ─── Donors and gifts ─────────────────────────────────────────────────────


def register_donor(client, headers=OFFICER, **overrides):
    response = client.create_donor(f.donor_payload(**overrides), headers=headers)
    return get_success_data(response)


def donor_headers(donor):
    """Headers for the donor row itself - X-User-ID is the donor's own id."""
    return make_donor_headers(donor["id"])


def read_donor(client, donor_id, headers=OFFICER):
    return get_success_data(client.get_donor(donor_id, headers=headers))


def add_gift(client, donor_id, amount_cents, gift_date, headers=OFFICER, **overrides):
    response = client.create_gift(
        donor_id, f.gift_payload(amount_cents, gift_date, **overrides), headers=headers
    )
    return get_success_data(response)


def add_received_gift(
    client, donor_id, amount_cents, gift_date, headers=OFFICER, **overrides
):
    overrides.setdefault("gift_status", GIFT_RECEIVED)
    return add_gift(
        client, donor_id, amount_cents, gift_date, headers=headers, **overrides
    )


def change_status(client, donor, new_status, effective_date, headers=OFFICER):
    """Read the donor fresh so the version stamp is always current."""
    current = read_donor(client, donor["id"], headers=headers)
    response = client.change_donor_status(
        donor["id"],
        f.status_change_payload(new_status, effective_date, current["version"]),
        headers=headers,
    )
    return get_success_data(response)


def link_partners(client, first_donor, second_donor, headers=OFFICER):
    current = read_donor(client, first_donor["id"], headers=headers)
    response = client.link_household(
        first_donor["id"],
        f.household_link_payload(second_donor["id"], current["version"]),
        headers=headers,
    )
    return get_success_data(response)


def renew_season(client, donor_id, cycle_year, headers=OFFICER):
    response = client.renew_season_ticket(
        donor_id, f.season_ticket_renewal_payload(cycle_year), headers=headers
    )
    return get_success_data(response)


# ─── Recalculation lifecycle ──────────────────────────────────────────────


def open_cycle(client, cycle_year, headers=OFFICER, **overrides):
    response = client.create_recalculation(
        f.recalculation_payload(cycle_year, **overrides), headers=headers
    )
    return get_success_data(response)


def run_cycle(client, recalculation_id, headers=OFFICER):
    return get_success_data(
        client.run_recalculation(recalculation_id, headers=headers)
    )


def communicate_cycle(client, recalculation_id, headers=OFFICER):
    return get_success_data(
        client.send_communications(recalculation_id, headers=headers)
    )


def read_cycle(client, recalculation_id, headers=OFFICER):
    return get_success_data(client.get_recalculation(recalculation_id, headers=headers))


def certify_cycle(client, recalculation_id, headers=CERTIFIER, reader=OFFICER):
    """Certify with a fresh version stamp and a certifier who is not the initiator."""
    current = read_cycle(client, recalculation_id, headers=reader)
    response = client.certify_recalculation(
        recalculation_id, f.certify_payload(current["version"]), headers=headers
    )
    return get_success_data(response)


def certified_cycle(client, cycle_year, headers=OFFICER, **overrides):
    """DRAFT -> COMPUTED -> COMMUNICATED -> CERTIFIED in one call."""
    cycle = open_cycle(client, cycle_year, headers=headers, **overrides)
    run_cycle(client, cycle["id"], headers=headers)
    communicate_cycle(client, cycle["id"], headers=headers)
    return certify_cycle(client, cycle["id"], reader=headers)


def communicated_cycle(client, cycle_year, headers=OFFICER, **overrides):
    """DRAFT -> COMPUTED -> COMMUNICATED, leaving the dispute window open."""
    cycle = open_cycle(client, cycle_year, headers=headers, **overrides)
    run_cycle(client, cycle["id"], headers=headers)
    return communicate_cycle(client, cycle["id"], headers=headers)


# ─── Sections and seats ───────────────────────────────────────────────────


def create_section(client, headers=ADMIN, **overrides):
    response = client.create_section(f.section_payload(**overrides), headers=headers)
    return get_success_data(response)


def read_section(client, section_id, headers=ADMIN):
    return get_success_data(client.get_section(section_id, headers=headers))


def add_seat(client, section_id, row_label, seat_number, headers=ADMIN, **overrides):
    response = client.create_seat(
        section_id, f.seat_payload(row_label, seat_number, **overrides), headers=headers
    )
    return get_success_data(response)


def create_section_with_seats(client, seat_specs, headers=ADMIN, **section_overrides):
    """Open a section and add its seats; the section is left OPEN.

    ``seat_specs`` is a sequence of ``(row_label, seat_number)`` pairs or of
    ``(row_label, seat_number, extra_kwargs)`` triples.
    """
    section = create_section(client, headers=headers, **section_overrides)
    seats = []
    for spec in seat_specs:
        if len(spec) == 3:
            row_label, seat_number, extra = spec
        else:
            row_label, seat_number = spec
            extra = {}
        seats.append(
            add_seat(client, section["id"], row_label, seat_number, headers=headers, **extra)
        )
    return read_section(client, section["id"], headers=headers), seats


def read_seat(client, seat_id, headers=ADMIN):
    return get_success_data(client.get_seat(seat_id, headers=headers))


def reprice_section(
    client, section_id, per_seat_requirement_cents, cycle_year, headers=ADMIN
):
    current = read_section(client, section_id, headers=headers)
    response = client.reprice_section(
        section_id,
        f.reprice_payload(
            per_seat_requirement_cents, cycle_year, current["version"]
        ),
        headers=headers,
    )
    return get_success_data(response)


def renovation_action(client, section_id, action, headers=ADMIN, **extra):
    """Drive one renovation action, always with a freshly read version stamp."""
    current = read_section(client, section_id, headers=headers)
    response = client.section_renovation(
        section_id,
        f.renovation_payload(action, current["version"], **extra),
        headers=headers,
    )
    return get_success_data(response)


def survey_section(client, section_id, headers=ADMIN):
    return renovation_action(client, section_id, ACTION_SURVEY, headers=headers)


def reprice_renovation(
    client,
    section_id,
    post_renovation_capacity,
    post_renovation_requirement_cents,
    headers=ADMIN,
):
    return renovation_action(
        client,
        section_id,
        ACTION_REPRICE,
        headers=headers,
        post_renovation_capacity=post_renovation_capacity,
        post_renovation_requirement_cents=post_renovation_requirement_cents,
    )


def start_reseating(client, section_id, reseating_recalculation_id, headers=ADMIN):
    return renovation_action(
        client,
        section_id,
        ACTION_START_RESEATING,
        headers=headers,
        reseating_recalculation_id=reseating_recalculation_id,
    )


# ─── Selection events and slots ───────────────────────────────────────────


def create_event(
    client,
    recalculation_id,
    window_start,
    window_end,
    slot_minutes,
    headers=OFFICER,
    **overrides
):
    response = client.create_selection_event(
        recalculation_id,
        f.selection_event_payload(
            window_start, window_end, slot_minutes, **overrides
        ),
        headers=headers,
    )
    return get_success_data(response)


def read_event(client, event_id, headers=OFFICER):
    return get_success_data(client.get_selection_event(event_id, headers=headers))


def publish_slots(client, event_id, headers=OFFICER):
    return get_success_data(client.publish_slots(event_id, headers=headers))


def gate_event(client, event_id, to_status=EVENT_OPEN, headers=OFFICER):
    return get_success_data(
        client.gate_selection_event(event_id, f.gate_payload(to_status), headers=headers)
    )


def publish_and_open(
    client,
    recalculation_id,
    window_start,
    window_end,
    slot_minutes,
    headers=OFFICER,
    **overrides
):
    """Create an event, publish its slots and open it for picks."""
    event = create_event(
        client,
        recalculation_id,
        window_start,
        window_end,
        slot_minutes,
        headers=headers,
        **overrides
    )
    publish_slots(client, event["id"], headers=headers)
    return gate_event(client, event["id"], EVENT_OPEN, headers=headers)


def list_event_slots(client, event_id, headers=OFFICER, **params):
    params.setdefault("selection_event_id", event_id)
    response = client.list_selection_slots(headers=headers, params=params)
    body = response.json()
    return body.get("data", [])


def slot_for_donor(client, event_id, donor_id, headers=OFFICER):
    """The single slot this event published for this donor."""
    slots = list_event_slots(client, event_id, headers=headers, donor_id=donor_id)
    assert len(slots) == 1, (
        "expected exactly one slot for donor {0} on event {1}, found {2}".format(
            donor_id, event_id, len(slots)
        )
    )
    return slots[0]


def read_slot(client, slot_id, headers=OFFICER):
    return get_success_data(client.get_selection_slot(slot_id, headers=headers))


# ─── Picks and seat assignments ───────────────────────────────────────────


def pick_seat(client, slot_id, seat_id, donor_id, client_headers=None, reader=ADMIN):
    """Consume a slot for a seat, echoing the seat's current version."""
    seat = read_seat(client, seat_id, headers=reader)
    headers = client_headers or make_donor_headers(donor_id)
    response = client.pick_seat(
        slot_id, f.pick_payload(seat_id, seat["version"]), headers=headers
    )
    return response


def pick_seat_ok(client, slot_id, seat_id, donor_id, reader=ADMIN):
    """The same pick, asserted to have succeeded, returning the assignment."""
    response = pick_seat(client, slot_id, seat_id, donor_id, reader=reader)
    return get_success_data(response)


def pick_through_event(client, event_id, seat_id, donor_id, reader=ADMIN):
    """Locate the donor's slot on the event and consume it for the seat."""
    slot = slot_for_donor(client, event_id, donor_id)
    return pick_seat_ok(client, slot["id"], seat_id, donor_id, reader=reader)


def read_assignment(client, assignment_id, headers=OFFICER):
    return get_success_data(client.get_seat_assignment(assignment_id, headers=headers))


def bill(client, assignment_id, to_status, amount_cents=None, headers=OFFICER):
    if amount_cents is None:
        payload = f.billing_payload(to_status)
    else:
        payload = f.payment_payload(to_status, amount_cents)
    return get_success_data(
        client.set_billing(assignment_id, payload, headers=headers)
    )


def invoice_and_pay(client, assignment_id, headers=OFFICER):
    """INVOICED then PAID, tendering exactly the frozen total_due_cents."""
    invoiced = bill(client, assignment_id, PAYMENT_INVOICED, headers=headers)
    return bill(
        client,
        assignment_id,
        PAYMENT_PAID,
        amount_cents=invoiced["total_due_cents"],
        headers=headers,
    )


def advance_occupancy(
    client, assignment_id, to_status, headers=OFFICER, **overrides
):
    current = read_assignment(client, assignment_id, headers=headers)
    response = client.set_occupancy(
        assignment_id,
        f.occupancy_payload(to_status, current["version"], **overrides),
        headers=headers,
    )
    return get_success_data(response)


def confirm_assignment(client, assignment_id, headers=OFFICER):
    """Pay the row in full and then confirm the hold as ASSIGNED."""
    invoice_and_pay(client, assignment_id, headers=headers)
    return advance_occupancy(
        client, assignment_id, OCCUPANCY_ASSIGNED, headers=headers
    )


def seated_donor(
    client, event_id, seat_id, donor_id, reader=ADMIN, headers=OFFICER
):
    """Pick, pay and confirm in one go, leaving the row ASSIGNED and PAID."""
    assignment = pick_through_event(client, event_id, seat_id, donor_id, reader=reader)
    return confirm_assignment(client, assignment["id"], headers=headers)


# ─── Relocation requests ──────────────────────────────────────────────────


def file_relocation_request(
    client,
    donor_id,
    current_seat_assignment_id,
    target_section_id,
    selection_event_id,
    headers=None,
    reader=OFFICER,
    **overrides
):
    """File a request, echoing the donor's freshly read version."""
    donor = read_donor(client, donor_id, headers=reader)
    payload = f.relocation_request_payload(
        donor_id,
        current_seat_assignment_id,
        target_section_id,
        selection_event_id,
        donor["version"],
        **overrides
    )
    return client.create_relocation_request(
        payload, headers=headers or make_donor_headers(donor_id)
    )


def read_relocation_request(client, request_id, headers=OFFICER):
    return get_success_data(
        client.get_relocation_request(request_id, headers=headers)
    )


# ─── Disputes ─────────────────────────────────────────────────────────────


def file_dispute(
    client, donor_id, recalculation_id, claimed_points_delta, headers=None, **overrides
):
    payload = f.dispute_payload(
        donor_id, recalculation_id, claimed_points_delta, **overrides
    )
    response = client.create_dispute(
        payload, headers=headers or make_donor_headers(donor_id)
    )
    return get_success_data(response)


def read_dispute(client, dispute_id, headers=OFFICER):
    return get_success_data(client.get_dispute(dispute_id, headers=headers))


# ─── Point transfers ──────────────────────────────────────────────────────


def request_transfer(
    client, source_donor_id, recipient_donor_id, basis, points_amount, headers=OFFICER
):
    source = read_donor(client, source_donor_id, headers=headers)
    payload = f.transfer_payload(
        source_donor_id,
        recipient_donor_id,
        basis,
        points_amount,
        source["version"],
    )
    return client.create_point_transfer(payload, headers=headers)


def request_transfer_ok(
    client, source_donor_id, recipient_donor_id, basis, points_amount, headers=OFFICER
):
    return get_success_data(
        request_transfer(
            client,
            source_donor_id,
            recipient_donor_id,
            basis,
            points_amount,
            headers=headers,
        )
    )


# ─── Convenience readers ──────────────────────────────────────────────────


def ledger_entries(client, headers=OFFICER, **params):
    params.setdefault("limit", 100)
    response = client.list_point_ledger_entries(headers=headers, params=params)
    return response.json().get("data", [])


def sensitivity(client, section_id, headers=ADMIN):
    return get_success_data(
        client.get_pricing_sensitivity(section_id, headers=headers)
    )


def retention(client, recalculation_id, headers=OFFICER):
    return get_success_data(
        client.get_retention_analysis(recalculation_id, headers=headers)
    )
