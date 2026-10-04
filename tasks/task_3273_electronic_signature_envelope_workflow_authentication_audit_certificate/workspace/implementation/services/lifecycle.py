"""Envelope lifecycle cascades and shared state guards (PRD §2.6, §3.7)."""

from db import db
from errors import (
    ApiError,
    ERR_ENVELOPE_TERMINAL,
    ERR_INVALID_ENVELOPE_STATE,
    ERR_INVALID_REQUEST,
    ERR_LEGAL_HOLD_FROZEN,
    ERR_STALE_VERSION,
)
from services.common import append_event, touch
from timeutil import parse_iso

ENVELOPE_TERMINAL_STATES = ("COMPLETED", "DECLINED", "VOIDED", "EXPIRED")
RECIPIENT_TERMINAL_STATES = ("SIGNED", "APPROVED", "DECLINED", "VOIDED",
                             "EXPIRED")
IN_FLIGHT_RECIPIENT_STATES = ("WAITING", "SENT", "DELIVERED", "SIGNING")


def is_envelope_terminal(envelope):
    return envelope["status"] in ENVELOPE_TERMINAL_STATES


def legal_hold_active(envelope):
    """The hold window [legal_hold_started_at, legal_hold_until or +inf) covers
    the logical clock (scaffold validation priority 12, PRD §2.11)."""
    from db import now_clock

    if not envelope.get("legal_hold"):
        return False
    start = parse_iso(envelope.get("legal_hold_started_at"))
    if start is None:
        return True
    until = parse_iso(envelope.get("legal_hold_until"))
    now = now_clock()
    if now < start:
        return False
    if until is not None and now >= until:
        return False
    return True


# --- guard helpers (called in the scaffold's ascending priority order) ---

def guard_envelope_terminal(envelope):
    """priority 11 -> ERR_ENVELOPE_TERMINAL (409)"""
    if is_envelope_terminal(envelope):
        raise ApiError(
            ERR_ENVELOPE_TERMINAL[0],
            "envelope is already in terminal status %s" % envelope["status"],
            ERR_ENVELOPE_TERMINAL[1],
        )


def guard_not_frozen(envelope):
    """priority 12 -> ERR_LEGAL_HOLD_FROZEN (409)"""
    if legal_hold_active(envelope):
        raise ApiError(
            ERR_LEGAL_HOLD_FROZEN[0],
            "envelope is under an active legal hold",
            ERR_LEGAL_HOLD_FROZEN[1],
        )


def guard_envelope_from_set(envelope, allowed):
    """priority 13 -> ERR_INVALID_ENVELOPE_STATE (409)"""
    if envelope["status"] not in allowed:
        raise ApiError(
            ERR_INVALID_ENVELOPE_STATE[0],
            "envelope status %s is not one of %s"
            % (envelope["status"], "|".join(allowed)),
            ERR_INVALID_ENVELOPE_STATE[1],
        )


def guard_expected_version(envelope, expected):
    """priority 33 -> ERR_STALE_VERSION (412).

    `expected_envelope_version` is a non-optional input on all four terminal
    envelope writes (PRD §2.8), so an absent value is a shape failure.
    """
    if expected is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "required field 'expected_envelope_version' is missing",
            ERR_INVALID_REQUEST[1],
        )
    if int(expected) != int(envelope.get("version", 0)):
        raise ApiError(
            ERR_STALE_VERSION[0],
            "expected_envelope_version %s does not match envelope version %s"
            % (expected, envelope.get("version")),
            ERR_STALE_VERSION[1],
        )


# --- cascades -----------------------------------------------------------

def cascade_recipients(envelope_id, from_states, to_status, skip_ids=(),
                       event_type=None):
    """Move in-flight recipients to a new status; never rewrite a terminal one."""
    changed = []
    for recipient in db.recipients_of(envelope_id):
        if recipient["id"] in skip_ids:
            continue
        if recipient["status"] in from_states:
            recipient["status"] = to_status
            touch(recipient)
            changed.append(recipient)
            if event_type:
                append_event(
                    envelope_id, event_type, recipient_id=recipient["id"]
                )
    return changed


def cascade_sessions(envelope_id, to_status, event_type=None):
    """Move every OPEN signing session of the envelope to a new status."""
    changed = []
    for session in db.sessions_of(envelope_id):
        if session["status"] == "OPEN":
            session["status"] = to_status
            touch(session)
            changed.append(session)
            if event_type:
                append_event(
                    envelope_id, event_type, recipient_id=session["recipient_id"]
                )
    return changed


def void_cascade(envelope, void_reason, refund_credit=False):
    envelope["status"] = "VOIDED"
    envelope["void_reason"] = void_reason
    cascade_recipients(
        envelope["id"], IN_FLIGHT_RECIPIENT_STATES, "VOIDED"
    )
    cascade_sessions(envelope["id"], "EXPIRED")
    if refund_credit:
        account = db.account(envelope["sender_account_id"])
        if account is not None:
            from services.calculations import credit_spend_consumption

            account["credit_balance"] = int(account["credit_balance"]) + int(
                credit_spend_consumption(envelope)
            )
            touch(account)
    append_event(envelope["id"], "VOIDED")
    touch(envelope)
    return envelope


def expire_cascade(envelope):
    envelope["status"] = "EXPIRED"
    cascade_recipients(envelope["id"], IN_FLIGHT_RECIPIENT_STATES, "EXPIRED")
    cascade_sessions(envelope["id"], "EXPIRED")
    append_event(envelope["id"], "EXPIRED")
    touch(envelope)
    return envelope


def decline_cascade(envelope, acting_recipient, decline_reason):
    """A signer declines: the recipient goes DECLINED and the envelope bubbles
    up to DECLINED; every OTHER in-flight recipient goes VOIDED and every open
    session goes DECLINED (PRD §2.6, §3.5)."""
    acting_recipient["status"] = "DECLINED"
    touch(acting_recipient)
    envelope["status"] = "DECLINED"
    envelope["decline_reason"] = decline_reason
    cascade_recipients(
        envelope["id"],
        IN_FLIGHT_RECIPIENT_STATES,
        "VOIDED",
        skip_ids=(acting_recipient["id"],),
    )
    cascade_sessions(envelope["id"], "DECLINED")
    append_event(
        envelope["id"], "RECIPIENT_DECLINED", recipient_id=acting_recipient["id"]
    )
    touch(envelope)
    return envelope