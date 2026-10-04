"""Computed ledger fields — single source of truth, derived on read.

nominations_used, the cohort seat ledger, training_completed_count and
meetings_held_count are computed from their base records so the PRD
invariants (seats_committed == count(ACCEPTED offers) pre-matriculation, with
FULFILLED offers keeping their committed seat per PRD 3.6, etc.) can never
drift.
"""

from core import store


def nominations_used(partner_id):
    """Partner's nominees whose status != WITHDRAWN (PRD 3.1)."""
    return sum(
        1
        for n in store.nominees.values()
        if n["nominator_id"] == partner_id and n["status"] != "WITHDRAWN"
    )


def seat_counts(cohort_id):
    """(seats_committed, offers_outstanding).

    seats_committed counts ACCEPTED offers — plus FULFILLED ones: at
    matriculation (PRD 3.6 step 3) a trained scholar's offer becomes FULFILLED
    with no ledger delta, while only a shortfall scholar's REVOKED offer makes
    seats_committed fall by one. FULFILLED offers exist only after
    matriculation, so pre-matriculation this equals the ACCEPTED count exactly.
    """
    committed = 0
    outstanding = 0
    for o in store.offers.values():
        if o["cohort_id"] != cohort_id:
            continue
        if o["status"] in ("ACCEPTED", "FULFILLED"):
            committed += 1
        elif o["status"] == "OFFERED":
            outstanding += 1
    return committed, outstanding


def has_live_offer(nominee_id):
    """Nominee holds an offer in OFFERED or ACCEPTED status in any cohort."""
    return any(
        o["nominee_id"] == nominee_id and o["status"] in ("OFFERED", "ACCEPTED")
        for o in store.offers.values()
    )


def round_evals(nominee_id, round_number):
    """All evaluations for (nominee, round); evaluations are immutable."""
    return [
        e
        for e in store.evaluations.values()
        if e["nominee_id"] == nominee_id and e["round_number"] == round_number
    ]


def training_completed_count(scholar_id):
    return sum(
        1
        for t in store.training_records.values()
        if t["scholar_id"] == scholar_id and t["status"] == "COMPLETED"
    )


def meetings_held_count(cohort_id):
    return sum(1 for m in store.meetings.values() if m["cohort_id"] == cohort_id)


def accepted_offer_of(cohort_id, nominee_id):
    for o in store.offers.values():
        if (
            o["cohort_id"] == cohort_id
            and o["nominee_id"] == nominee_id
            and o["status"] == "ACCEPTED"
        ):
            return o
    return None
