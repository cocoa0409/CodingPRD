"""Healing outcome state machine (PRD 3.6, scaffold 1.2)."""

import db
import errors as E
import calculations as calc
from services import common


def create_outcome(session, assessed_at):
    outcome = db.HealingOutcome()
    outcome.session_id = session.id
    outcome.assessed_at = db.fmt_instant(assessed_at)
    outcome.healing_result = "PENDING_ASSESSMENT"
    outcome.downgrade_credited_cents = 0
    outcome.re_pierce_eligible = False
    outcome.re_pierce_claim_count = 0
    outcome.status = "ASSESSED"
    db.DB.outcomes[outcome.id] = outcome

    # Creating a healing outcome increments the target session's version.
    session.touch()
    return outcome


def downgrade(outcome, downgraded_sites):
    """ASSESSED -> DOWNGRADED, crediting the customer (PRD 3.6)."""
    if outcome.status != "ASSESSED":
        E.fail(E.ERR_INVALID_STATE, "Healing outcome is not ASSESSED")
    if outcome.healing_result != "HEALED":
        E.fail(E.ERR_INVALID_STATE, "Only a HEALED outcome may be downgraded")

    session = db.DB.sessions.get(outcome.session_id)
    if session is None:
        E.fail(E.ERR_SESSION_NOT_FOUND)

    credit = calc.downgrade_credit_amount(downgraded_sites)

    if session.healing_status == "HEALED":
        session.healing_status = "RE_PIERCED"
        session.touch()

    outcome.status = "DOWNGRADED"
    outcome.healing_result = "DOWNGRADED"
    outcome.downgrade_credited_cents = credit
    outcome.touch()

    customer = common.session_owner_customer(session)
    if customer is not None:
        customer.aftercare_credit_cents += credit
        customer.touch()
    return outcome


def claim_re_pierce(outcome):
    """RE_PIERCE_ELIGIBLE|DOWNGRADED -> RE_PIERCED (PRD 3.6)."""
    session = db.DB.sessions.get(outcome.session_id)
    if session is None:
        E.fail(E.ERR_SESSION_NOT_FOUND)

    if outcome.status == "RE_PIERCE_ELIGIBLE":
        if session.healing_status != "FAILED":
            E.fail(E.ERR_INVALID_STATE,
                   "The linked session's healing_status must be FAILED")
    elif outcome.status == "DOWNGRADED":
        if outcome.downgrade_credited_cents <= 0:
            E.fail(E.ERR_INVALID_STATE,
                   "The downgraded clawback must leave a positive credit")
    else:
        E.fail(E.ERR_RE_PIERCE_NOT_ELIGIBLE,
               "No unconsumed re-pierce entitlement exists for this outcome")

    outcome.status = "RE_PIERCED"
    outcome.re_pierce_claim_count = 1
    outcome.re_pierce_eligible = False
    outcome.touch()
    return outcome


def close(outcome):
    if outcome.status == "RE_PIERCED":
        open_incidents = [i for i in db.DB.incidents.values()
                          if i.session_id == outcome.session_id
                          and i.escalation_status in db.NON_TERMINAL_INCIDENT_STATES]
        if open_incidents:
            E.fail(E.ERR_INVALID_STATE,
                   "No linked incident may remain LOGGED, TRIAGED, ESCALATED or REOPENED")
    elif outcome.status == "DOWNGRADED":
        session = db.DB.sessions.get(outcome.session_id)
        customer = common.session_owner_customer(session) if session else None
        available = customer.aftercare_credit_cents if customer else 0
        if outcome.downgrade_credited_cents != 0 \
                and available < outcome.downgrade_credited_cents:
            E.fail(E.ERR_INVALID_STATE,
                   "The customer's aftercare credit does not cover the downgrade credit")
    else:
        E.fail(E.ERR_INVALID_STATE,
               "Only a RE_PIERCED or DOWNGRADED outcome may be closed")

    outcome.status = "CLOSED"
    outcome.touch()
    return outcome