"""Request-payload builders.

Each builder returns a dict that satisfies every declared constraint of the
operation it names, and accepts ``**overrides`` so that a test can perturb one
field without restating the rest.  Overrides are applied by ``update`` after
the defaults are assembled, so no field is ever passed twice.

Two conventions matter and are applied everywhere:

* money and points travel as JSON numbers - integer cents for ``*_cents``
  fields and a 2-place decimal for point amounts - never as strings;
* every field the PRD types as an instant carries a full ISO 8601 UTC
  timestamp with three fractional digits, never a bare date.
"""

import itertools

from .constants import (
    ACTION_REPRICE,
    ACTION_SURVEY,
    ALUMNUS,
    ATHLETICS_ANNUAL,
    DECISION_UPHOLD,
    DONOR_LAPSED,
    EVENT_OPEN,
    EVENT_SEASON_TICKET,
    GIFT_RECEIVED,
    INDIVIDUAL,
    OCCUPANCY_ASSIGNED,
    PAYMENT_INVOICED,
    POLICY_GRANT,
    REQUEST_RELOCATION,
)

_SEQUENCE = itertools.count(1)


def next_sequence():
    """A monotonically increasing integer for unique-per-test literals."""
    return next(_SEQUENCE)


# ─── Instant helpers ──────────────────────────────────────────────────────


def instant(year, month, day, hour=0, minute=0, second=0, millisecond=0):
    """Build an ISO 8601 UTC instant with exactly three fractional digits."""
    return "{0:04d}-{1:02d}-{2:02d}T{3:02d}:{4:02d}:{5:02d}.{6:03d}Z".format(
        year, month, day, hour, minute, second, millisecond
    )


def end_of_day(year, month, day):
    """The last representable instant of a UTC day, three fractional digits."""
    return instant(year, month, day, 23, 59, 59, 999)


# ─── Donors ───────────────────────────────────────────────────────────────


def donor_payload(**overrides):
    serial = next_sequence()
    payload = {
        "full_name": "Donor {0:04d} Priority".format(serial),
        "email": "donor{0:04d}@athletics.example.org".format(serial),
        "alumni_status": ALUMNUS,
        "entity_type": INDIVIDUAL,
    }
    payload.update(overrides)
    return payload


def status_change_payload(new_status, effective_date, expected_donor_version, **overrides):
    payload = {
        "new_status": new_status,
        "effective_date": effective_date,
        "reason": "Recorded by the development office from primary documents.",
        "expected_donor_version": expected_donor_version,
    }
    payload.update(overrides)
    return payload


def lapse_payload(effective_date, expected_donor_version, **overrides):
    return status_change_payload(
        DONOR_LAPSED, effective_date, expected_donor_version, **overrides
    )


def household_link_payload(partner_donor_id, expected_donor_version, **overrides):
    payload = {
        "partner_donor_id": partner_donor_id,
        "expected_donor_version": expected_donor_version,
    }
    payload.update(overrides)
    return payload


def season_ticket_renewal_payload(cycle_year, **overrides):
    payload = {"cycle_year": cycle_year}
    payload.update(overrides)
    return payload


# ─── Gifts ────────────────────────────────────────────────────────────────


def gift_payload(amount_cents, gift_date, **overrides):
    payload = {
        "amount_cents": amount_cents,
        "gift_date": gift_date,
        "designation": ATHLETICS_ANNUAL,
    }
    payload.update(overrides)
    return payload


def received_gift_payload(amount_cents, gift_date, **overrides):
    overrides.setdefault("gift_status", GIFT_RECEIVED)
    return gift_payload(amount_cents, gift_date, **overrides)


def settle_gift_payload(new_status, **overrides):
    payload = {"new_status": new_status}
    payload.update(overrides)
    return payload


# ─── Recalculations ───────────────────────────────────────────────────────


def recalculation_payload(cycle_year, **overrides):
    payload = {
        "cycle_year": cycle_year,
        "cutoff_date": end_of_day(cycle_year, 6, 30),
        "dispute_window_end": end_of_day(cycle_year, 9, 30),
    }
    payload.update(overrides)
    return payload


def certify_payload(expected_recalculation_version, **overrides):
    payload = {"expected_recalculation_version": expected_recalculation_version}
    payload.update(overrides)
    return payload


# ─── Disputes ─────────────────────────────────────────────────────────────


def dispute_payload(donor_id, recalculation_id, claimed_points_delta, **overrides):
    payload = {
        "donor_id": donor_id,
        "recalculation_id": recalculation_id,
        "claimed_points_delta": claimed_points_delta,
        "basis_note": "A 2026 capital gift is missing from my statement.",
    }
    payload.update(overrides)
    return payload


def request_info_payload(**overrides):
    payload = {"info_note": "Please send the gift receipt for the disputed year."}
    payload.update(overrides)
    return payload


def provide_info_payload(**overrides):
    payload = {"response_note": "The receipt from the athletics fund is attached."}
    payload.update(overrides)
    return payload


def dispute_decision_payload(decision=DECISION_UPHOLD, **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ─── Point transfers ──────────────────────────────────────────────────────


def transfer_payload(
    source_donor_id,
    recipient_donor_id,
    basis,
    points_amount,
    expected_source_donor_version,
    **overrides
):
    payload = {
        "source_donor_id": source_donor_id,
        "recipient_donor_id": recipient_donor_id,
        "basis": basis,
        "points_amount": points_amount,
        "expected_source_donor_version": expected_source_donor_version,
    }
    payload.update(overrides)
    return payload


def transfer_policy_decision_payload(decision=POLICY_GRANT, **overrides):
    payload = {
        "decision": decision,
        "note": "The policy committee reviewed the supporting documentation.",
    }
    payload.update(overrides)
    return payload


def reverse_transfer_payload(**overrides):
    payload = {"reason": "Estate settlement reversed the designation."}
    payload.update(overrides)
    return payload


# ─── Sections and seats ───────────────────────────────────────────────────


def section_payload(**overrides):
    serial = next_sequence()
    payload = {
        "section_code": "SEC-{0:04d}".format(serial),
        "venue_code": "MEMORIAL-STADIUM",
        "seat_capacity": 3,
        "per_seat_requirement_cents": 100000,
        "required_points_per_seat": 0.00,
    }
    payload.update(overrides)
    return payload


def seat_payload(row_label, seat_number, **overrides):
    payload = {"row_label": row_label, "seat_number": seat_number}
    payload.update(overrides)
    return payload


def reprice_payload(
    per_seat_requirement_cents, cycle_year, expected_section_version, **overrides
):
    payload = {
        "per_seat_requirement_cents": per_seat_requirement_cents,
        "cycle_year": cycle_year,
        "expected_section_version": expected_section_version,
    }
    payload.update(overrides)
    return payload


def renovation_payload(renovation_action, expected_section_version, **overrides):
    payload = {
        "renovation_action": renovation_action,
        "expected_section_version": expected_section_version,
    }
    payload.update(overrides)
    return payload


def survey_payload(expected_section_version, **overrides):
    return renovation_payload(ACTION_SURVEY, expected_section_version, **overrides)


def reprice_renovation_payload(
    expected_section_version,
    post_renovation_capacity,
    post_renovation_requirement_cents,
    **overrides
):
    overrides.setdefault("post_renovation_capacity", post_renovation_capacity)
    overrides.setdefault(
        "post_renovation_requirement_cents", post_renovation_requirement_cents
    )
    return renovation_payload(ACTION_REPRICE, expected_section_version, **overrides)


# ─── Selection events and slots ───────────────────────────────────────────


def selection_event_payload(window_start, window_end, slot_minutes, **overrides):
    payload = {
        "event_type": EVENT_SEASON_TICKET,
        "window_start": window_start,
        "window_end": window_end,
        "slot_minutes": slot_minutes,
    }
    payload.update(overrides)
    return payload


def gate_payload(to_status=EVENT_OPEN, **overrides):
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def pick_payload(seat_id, expected_seat_version, **overrides):
    payload = {"seat_id": seat_id, "expected_seat_version": expected_seat_version}
    payload.update(overrides)
    return payload


def forfeit_payload(**overrides):
    payload = {"reason": "The donor does not want a seat in this cycle."}
    payload.update(overrides)
    return payload


# ─── Seat assignments ─────────────────────────────────────────────────────


def occupancy_payload(to_status, expected_seat_assignment_version, **overrides):
    payload = {
        "to_status": to_status,
        "expected_seat_assignment_version": expected_seat_assignment_version,
    }
    payload.update(overrides)
    return payload


def confirm_occupancy_payload(expected_seat_assignment_version, **overrides):
    return occupancy_payload(
        OCCUPANCY_ASSIGNED, expected_seat_assignment_version, **overrides
    )


def billing_payload(to_status=PAYMENT_INVOICED, **overrides):
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def payment_payload(to_status, amount_cents, **overrides):
    payload = {"to_status": to_status, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ─── Relocation requests ──────────────────────────────────────────────────


def relocation_request_payload(
    donor_id,
    current_seat_assignment_id,
    target_section_id,
    selection_event_id,
    expected_donor_version,
    **overrides
):
    payload = {
        "donor_id": donor_id,
        "current_seat_assignment_id": current_seat_assignment_id,
        "target_section_id": target_section_id,
        "selection_event_id": selection_event_id,
        "request_type": REQUEST_RELOCATION,
        "expected_donor_version": expected_donor_version,
    }
    payload.update(overrides)
    return payload


def relocation_decision_payload(decision, **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ─── Logical clock ────────────────────────────────────────────────────────


def clock_payload(to_iso8601, **overrides):
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
