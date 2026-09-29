"""Existence resolution (PRD section 2.6 rung 4) in the declared left-to-right order."""

import errors
from db import store


def community(cid):
    row = store.communities.get(cid)
    if row is None:
        errors.fail(errors.ERR_COMMUNITY_NOT_FOUND, "No community with id %s." % cid)
    return row


def carrier(cid):
    row = store.carriers.get(cid)
    if row is None:
        errors.fail(errors.ERR_CARRIER_NOT_FOUND, "No carrier with id %s." % cid)
    return row


def aircraft_type(cid):
    row = store.aircraft_types.get(cid)
    if row is None:
        errors.fail(errors.ERR_AIRCRAFT_TYPE_NOT_FOUND,
                    "No aircraft type with id %s." % cid)
    return row


def solicitation(cid):
    row = store.solicitations.get(cid)
    if row is None:
        errors.fail(errors.ERR_SOLICITATION_NOT_FOUND,
                    "No solicitation with id %s." % cid)
    return row


def proposal(cid):
    row = store.proposals.get(cid)
    if row is None:
        errors.fail(errors.ERR_PROPOSAL_NOT_FOUND, "No proposal with id %s." % cid)
    return row


def agreement(cid):
    row = store.agreements.get(cid)
    if row is None:
        errors.fail(errors.ERR_AGREEMENT_NOT_FOUND,
                    "No service agreement with id %s." % cid)
    return row


def period(cid):
    row = store.periods.get(cid)
    if row is None:
        errors.fail(errors.ERR_SERVICE_PERIOD_NOT_FOUND,
                    "No service period with id %s." % cid)
    return row


def payment(cid):
    row = store.payments.get(cid)
    if row is None:
        errors.fail(errors.ERR_PAYMENT_NOT_FOUND,
                    "No subsidy payment with id %s." % cid)
    return row


def petition(cid):
    row = store.petitions.get(cid)
    if row is None:
        errors.fail(errors.ERR_PETITION_NOT_FOUND,
                    "No termination petition with id %s." % cid)
    return row


def renegotiation(cid):
    row = store.renegotiations.get(cid)
    if row is None:
        errors.fail(errors.ERR_RENEGOTIATION_NOT_FOUND,
                    "No rate renegotiation with id %s." % cid)
    return row


# ---------------------------------------------------------------------------
def agreements_of_community(community_id):
    return [a for a in store.agreements.values() if a["community_id"] == community_id]


def agreements_of_carrier(carrier_id):
    return [a for a in store.agreements.values() if a["carrier_id"] == carrier_id]


def periods_of_agreement(agreement_id):
    return [p for p in store.periods.values() if p["agreement_id"] == agreement_id]


def latest_determination(community_id):
    rows = [d for d in store.determinations.values()
            if d["community_id"] == community_id]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows[-1]


def fuel_index_for_month(index_month):
    for row in store.fuel_indices.values():
        if row["index_month"] == index_month:
            return row
    return None
