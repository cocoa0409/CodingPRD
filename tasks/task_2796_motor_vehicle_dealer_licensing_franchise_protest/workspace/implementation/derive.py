"""Derived counters, recomputed from surviving rows rather than adjusted (PRD 2.7/2.11)."""

import calc
import db

OPEN_DISPUTE_STATES = ("FILED", "UNDER_REVIEW")
ACTIVE_FILING_STATES = ("NOTICE_SERVED", "PROTEST_PENDING")
ACTIVE_PROTEST_STATES = ("FILED", "SCHEDULED", "HEARD", "SUSTAINED")
LIVE_PROTEST_STATES = ("FILED", "SCHEDULED", "HEARD", "SUSTAINED", "APPEALED")
SLOT_HOLDING_STATES = ("SCHEDULED", "HEARD", "SUSTAINED", "DENIED", "APPEALED", "FINAL")
ACCEPTED_EVIDENCE_STATES = ("ACCEPTED", "LATE_ACCEPTED")


def set_counter(record, field, value):
    """Write a derived counter, bumping version only when the value actually changes."""
    if record.get(field) != value:
        record[field] = value
        db.touch(record)


def holds_slot(protest):
    return protest.get("hearing_start_at") is not None and protest["status"] in SLOT_HOLDING_STATES


def protests_for_filing(filing_id):
    return db.where("protest", franchise_filing_id=filing_id)


def open_dispute_count(manufacturer_id):
    return len([
        d for d in db.where("warranty_rate_dispute", manufacturer_id=manufacturer_id)
        if d["status"] in OPEN_DISPUTE_STATES
    ])


def active_filing_count(manufacturer_id):
    return len([
        f for f in db.where("franchise_filing", manufacturer_id=manufacturer_id)
        if f["status"] in ACTIVE_FILING_STATES
    ])


def booked_hearing_count(room_id):
    return len([
        p for p in db.where("protest", hearing_room_id=room_id) if holds_slot(p)
    ])


def active_protest_count(filing_id):
    return len([
        p for p in protests_for_filing(filing_id) if p["status"] in ACTIVE_PROTEST_STATES
    ])


def licensed_salesperson_count(dealer_id):
    return len([
        s for s in db.where("salesperson", sponsoring_dealer_id=dealer_id)
        if s["license_status"] == "LICENSED"
    ])


def restitution_outstanding_cents(dealer_id):
    total = 0
    for complaint in db.where("consumer_complaint", dealer_id=dealer_id):
        if complaint["status"] != "SANCTIONED":
            continue
        ordered = complaint.get("restitution_ordered_cents") or 0
        paid = complaint.get("restitution_paid_cents") or 0
        remaining = ordered - paid
        if remaining > 0:
            total += remaining
    return total


def dealer_points(dealer_id, reference_date=None):
    reference = reference_date or db.today()
    return calc.rolling_points(db.where("consumer_complaint", dealer_id=dealer_id), reference)


def salesperson_points(salesperson_id, reference_date=None):
    reference = reference_date or db.today()
    return calc.rolling_points(
        db.where("consumer_complaint", salesperson_id=salesperson_id), reference
    )


def evidence_for_protest(protest_id):
    return db.where("evidence_submission", protest_id=protest_id)


def studies_for_protest(protest_id, party=None):
    rows = db.where("market_study", protest_id=protest_id)
    if party is None:
        return rows
    return [row for row in rows if row["submitted_by_party"] == party]


def refresh_manufacturer(manufacturer):
    if manufacturer is None:
        return
    set_counter(manufacturer, "open_dispute_count", open_dispute_count(manufacturer["id"]))
    set_counter(manufacturer, "active_filing_count", active_filing_count(manufacturer["id"]))


def refresh_room(room):
    if room is None:
        return
    set_counter(room, "booked_hearing_count", booked_hearing_count(room["id"]))


def refresh_filing(filing):
    if filing is None:
        return
    set_counter(filing, "active_protest_count", active_protest_count(filing["id"]))


def refresh_protest_evidence(protest):
    if protest is None:
        return
    rows = evidence_for_protest(protest["id"])
    pages = sum(
        row["page_count"] for row in rows if row["acceptance_status"] in ACCEPTED_EVIDENCE_STATES
    )
    late = len([row for row in rows if row["acceptance_status"] == "LATE_ACCEPTED"])
    set_counter(protest, "accepted_evidence_pages", pages)
    set_counter(protest, "late_evidence_count", late)


def refresh_dealer(dealer, reference_date=None):
    if dealer is None:
        return
    set_counter(dealer, "licensed_salesperson_count", licensed_salesperson_count(dealer["id"]))
    set_counter(dealer, "restitution_outstanding_cents", restitution_outstanding_cents(dealer["id"]))
    set_counter(dealer, "disciplinary_points", dealer_points(dealer["id"], reference_date))


def refresh_salesperson(salesperson, reference_date=None):
    if salesperson is None:
        return
    set_counter(
        salesperson, "disciplinary_points", salesperson_points(salesperson["id"], reference_date)
    )


def recompute_all(reference_date=None):
    """Recompute every derived counter in the store after a mutating request."""
    for manufacturer in db.ordered("manufacturer"):
        refresh_manufacturer(manufacturer)
    for room in db.ordered("hearing_room"):
        refresh_room(room)
    for filing in db.ordered("franchise_filing"):
        refresh_filing(filing)
    for protest in db.ordered("protest"):
        refresh_protest_evidence(protest)
    for dealer in db.ordered("dealer"):
        refresh_dealer(dealer, reference_date)
    for salesperson in db.ordered("salesperson"):
        refresh_salesperson(salesperson, reference_date)
