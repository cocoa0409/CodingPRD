"""Adverse-reaction incidents, refunds and the escalation cascade.

Implements PRD 3.7 and the incident ladder of scaffold 1.2.
"""

import db
import errors as E
import calculations as calc
from services import common


def _session_and_customer(incident):
    session = db.DB.sessions.get(incident.session_id)
    if session is None:
        E.fail(E.ERR_SESSION_NOT_FOUND)
    return session, common.session_owner_customer(session)


def file_incident(session, reported_at, severity, reaction_codes):
    incident = db.IncidentReport()
    incident.session_id = session.id
    incident.reported_at = db.fmt_instant(reported_at)
    incident.severity = severity
    incident.reaction_codes = list(reaction_codes)
    incident.escalation_status = "LOGGED"
    incident.refund_amount_cents = 0
    incident.refund_status = "NONE"
    db.DB.incidents[incident.id] = incident

    # Filing an incident increments the target session's version, and the owning
    # store's derived posture is reconciled (PRD 2.7: posture is recomputed
    # "whenever any incident escalation status changes at the store").
    session.touch()
    common.recompute_store_of_session(session)
    common.cascade_customer_flags()
    return incident


def triage(incident):
    if incident.escalation_status not in ("LOGGED", "REOPENED"):
        E.fail(E.ERR_INVALID_STATE,
               "Incident is not LOGGED or REOPENED")
    session, customer = _session_and_customer(incident)

    incident.escalation_status = "TRIAGED"
    if customer is not None:
        incident.refund_amount_cents = calc.incident_refund_allocation(
            incident, session, customer, "provisional_at_triage")
    incident.refund_status = "PENDING"
    incident.touch()
    common.recompute_store_of_session(session)
    common.cascade_customer_flags()
    return incident


def escalate(incident):
    if incident.escalation_status != "TRIAGED":
        E.fail(E.ERR_INVALID_STATE, "Incident is not TRIAGED")
    if incident.severity not in ("SEVERE", "MEDICAL_EMERGENCY"):
        E.fail(E.ERR_INVALID_STATE,
               "Only a SEVERE or MEDICAL_EMERGENCY incident may be escalated")

    session, _ = _session_and_customer(incident)
    incident.escalation_status = "ESCALATED"
    incident.touch()

    # Cascade (depth 3): session healing failure -> store count -> posture.
    session.healing_status = "FAILED"
    session.touch()

    store = common.session_store(session)
    if store is not None:
        posture = common.recompute_store_posture(store)
        if posture == "RESTRICTED":
            common.cancel_booking_rows(
                [a for a in common.appointments_at_store(store.id)
                 if a.status in ("BOOKED", "CONFIRMED")])

    common.cascade_customer_flags()
    return incident


def resolve(incident, resolution_note=None):
    status = incident.escalation_status
    if status == "TRIAGED":
        if incident.severity not in ("MINOR", "MODERATE"):
            E.fail(E.ERR_INVALID_STATE,
                   "Only a MINOR or MODERATE incident may be resolved from TRIAGED")
    elif status == "ESCALATED":
        if not resolution_note:
            E.fail(E.ERR_INVALID_REQUEST,
                   "A resolution note and a refund decision are required")
    else:
        E.fail(E.ERR_INVALID_STATE, "Incident is not TRIAGED or ESCALATED")

    session, customer = _session_and_customer(incident)
    incident.escalation_status = "RESOLVED"
    if customer is not None:
        incident.refund_amount_cents = calc.incident_refund_allocation(
            incident, session, customer, "final_at_resolution")
    incident.touch()
    common.recompute_store_of_session(session)
    common.cascade_customer_flags()
    return incident


def issue_refund(incident):
    if incident.escalation_status != "RESOLVED":
        E.fail(E.ERR_INVALID_STATE, "Incident is not RESOLVED")
    if incident.refund_amount_cents <= 0:
        E.fail(E.ERR_INVALID_STATE, "refund_amount_cents must be greater than 0")

    session, customer = _session_and_customer(incident)
    computed = incident.refund_amount_cents
    incident.escalation_status = "REFUND_ISSUED"
    incident.refund_status = "SETTLED"
    if customer is not None:
        customer.refunded_cents += computed
        customer.retained_cents += session.net_fee_cents - computed
        customer.touch()
    incident.touch()
    return incident


def reopen(incident, reopen_reason):
    if incident.escalation_status != "RESOLVED":
        E.fail(E.ERR_INVALID_STATE, "Incident is not RESOLVED")
    reported_at = db.parse_instant(incident.reported_at)
    if reported_at is None:
        E.fail(E.ERR_INVALID_REQUEST, "reported_at is not a valid instant")
    elapsed = db.DB.clock - reported_at
    if elapsed.total_seconds() > db.INCIDENT_REOPEN_DAYS * 86400:
        E.fail(E.ERR_INVALID_STATE,
               "reported_at falls outside the reopen window")
    incident.escalation_status = "REOPENED"
    incident.touch()
    session, _ = _session_and_customer(incident)
    common.recompute_store_of_session(session)
    common.cascade_customer_flags()
    return incident


def requested_refund_allowed(incident, requested_refund_cents):
    """An explicit requested amount above the computed cap is rejected (PRD 3.7)."""
    session, _ = _session_and_customer(incident)
    gross_fee_cents = session.base_fee_cents \
        + (db.AFTERCARE_KIT_FEE_CENTS if session.aftercare_kit_included else 0)
    retain_cap = max(gross_fee_cents - db.AFTERCARE_RETAIN_FLOOR_CENTS, 0)
    if requested_refund_cents > retain_cap:
        E.fail(E.ERR_REFUND_EXCEEDS_ALLOWABLE,
               "The requested refund exceeds the gross fee minus the retain floor")
    if requested_refund_cents > session.net_fee_cents:
        E.fail(E.ERR_REFUND_EXCEEDS_ALLOWABLE,
               "The requested refund exceeds the session's net fee")
    return requested_refund_cents