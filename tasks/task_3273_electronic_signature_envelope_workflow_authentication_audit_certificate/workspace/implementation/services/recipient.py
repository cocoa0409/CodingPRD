"""Recipient-level guards: routing release and the authentication ladder.

Priorities implemented here (SCAFFOLD §1.4):
  14 ERR_RECIPIENT_TERMINAL (409)
  16 ERR_AUTH_LEVEL_TOO_LOW (422)
  17 ERR_AUTH_REQUIRED (422)
  18 ERR_AUTH_MAX_ATTEMPTS (422)
  19 ERR_CONSENT_REQUIRED (422)
  20 ERR_INVALID_ACCESS_CODE (401)
  21 ERR_ROUTING_NOT_RELEASED (422)
  22 ERR_ENVELOPE_EXPIRED (409)
"""

from db import db, now_clock
from errors import (
    ApiError,
    ERR_AUTH_LEVEL_TOO_LOW,
    ERR_AUTH_MAX_ATTEMPTS,
    ERR_AUTH_REQUIRED,
    ERR_CONSENT_REQUIRED,
    ERR_ENVELOPE_EXPIRED,
    ERR_INVALID_ACCESS_CODE,
    ERR_RECIPIENT_TERMINAL,
    ERR_ROUTING_NOT_RELEASED,
)
from services.common import append_event, touch
from services.calculations import final_risk_score, recompute_provisional_scores
from services.lifecycle import RECIPIENT_TERMINAL_STATES
from timeutil import parse_iso

SIGNER_APPROVER = ("SIGNER", "APPROVER")
# Winning statuses for the routing gate — a lower routing_order recipient is
# considered dealt with once it reaches one of these (PRD §3.3).
ROUTING_TERMINAL_ATTEMPTED = ("SIGNED", "APPROVED", "DECLINED", "VOIDED")

AUTH_LEVEL_RANK = {"EMAIL_ACCESS": 0, "ACCESS_CODE": 1, "KBA": 2,
                   "ID_DOCUMENT": 3}
REQUIRED_LEVEL_AT_60 = "KBA"
REQUIRED_LEVEL_AT_80 = "ID_DOCUMENT"

VALID_AUTH_METHODS = ("EMAIL_ACCESS", "ACCESS_CODE", "KBA", "ID_DOCUMENT")


def guard_recipient_terminal(recipient):
    """priority 14"""
    if recipient["status"] in RECIPIENT_TERMINAL_STATES:
        raise ApiError(
            ERR_RECIPIENT_TERMINAL[0],
            "recipient is already in terminal status %s" % recipient["status"],
            ERR_RECIPIENT_TERMINAL[1],
        )


def routing_released(envelope, recipient):
    """A recipient may act when every lower-positioned SIGNER/APPROVER has
    reached SIGNED, APPROVED, DECLINED or VOIDED (PRD §3.3).

    PARALLEL envelopes release everyone at once. COPY recipients are ignored by
    the gate entirely.
    """
    if envelope["routing_mode"] == "PARALLEL":
        return True
    if recipient["role"] == "COPY":
        return True
    order = int(recipient.get("routing_order", 1))
    for other in db.recipients_of(envelope["id"]):
        if other["id"] == recipient["id"]:
            continue
        if other["role"] not in SIGNER_APPROVER:
            continue
        if int(other.get("routing_order", 1)) >= order:
            continue
        if other["status"] not in ROUTING_TERMINAL_ATTEMPTED:
            return False
    return True


def guard_routing_released(envelope, recipient):
    """priority 21"""
    if not routing_released(envelope, recipient):
        raise ApiError(
            ERR_ROUTING_NOT_RELEASED[0],
            "routing_order %s for this recipient is not released yet"
            % recipient.get("routing_order"),
            ERR_ROUTING_NOT_RELEASED[1],
        )


def guard_envelope_not_expired(envelope):
    """priority 22"""
    expires_at = parse_iso(envelope.get("expires_at"))
    if expires_at is not None and now_clock() >= expires_at:
        raise ApiError(
            ERR_ENVELOPE_EXPIRED[0],
            "the envelope's expires_at has passed",
            ERR_ENVELOPE_EXPIRED[1],
        )


def peer_risk_ceiling(recipient):
    """Maximum provisional auth_risk_score over the OTHER AUTHENTICATED
    recipients of the same envelope (PRD §3.4, validation priority 16)."""
    best = None
    for other in db.recipients_of(recipient["envelope_id"]):
        if other["id"] == recipient["id"]:
            continue
        if other["auth_status"] != "AUTHENTICATED":
            continue
        from services.calculations import provisional_risk_score

        score = provisional_risk_score(other)
        if best is None or score > best:
            best = score
    return best


def guard_auth_level_sufficient(recipient):
    """priority 16: >= 60 requires KBA, >= 80 requires ID_DOCUMENT."""
    ceiling = peer_risk_ceiling(recipient)
    if ceiling is None:
        return
    if ceiling >= 80:
        required = REQUIRED_LEVEL_AT_80
    elif ceiling >= 60:
        required = REQUIRED_LEVEL_AT_60
    else:
        return
    if AUTH_LEVEL_RANK.get(recipient["auth_level"], 0) < AUTH_LEVEL_RANK[required]:
        raise ApiError(
            ERR_AUTH_LEVEL_TOO_LOW[0],
            "peer risk %s requires auth_level %s but the recipient holds %s"
            % (ceiling, required, recipient["auth_level"]),
            ERR_AUTH_LEVEL_TOO_LOW[1],
        )


def auth_requirement_met(recipient):
    """priority 17: ACCESS_CODE/KBA/ID_DOCUMENT need AUTHENTICATED;
    EMAIL_ACCESS accepts AUTHENTICATED or still-PENDING."""
    if recipient["auth_level"] == "EMAIL_ACCESS":
        return recipient["auth_status"] in ("AUTHENTICATED", "PENDING")
    return recipient["auth_status"] == "AUTHENTICATED"


def guard_auth_requirement(recipient):
    """priority 17"""
    if not auth_requirement_met(recipient):
        raise ApiError(
            ERR_AUTH_REQUIRED[0],
            "recipient has not satisfied its authentication requirement",
            ERR_AUTH_REQUIRED[1],
        )


def guard_auth_max_attempts(recipient, method):
    """priority 18: a KBA challenge after 3 failures is refused."""
    if method == "KBA" and int(recipient.get("kba_fail_count", 0)) >= 3:
        raise ApiError(
            ERR_AUTH_MAX_ATTEMPTS[0],
            "knowledge-based-question attempts are exhausted",
            ERR_AUTH_MAX_ATTEMPTS[1],
        )


def guard_access_code(recipient, supplied):
    """priority 20"""
    if recipient["auth_level"] != "ACCESS_CODE":
        return
    if supplied is None or str(supplied) != str(recipient.get("access_code")):
        raise ApiError(
            ERR_INVALID_ACCESS_CODE[0],
            "the supplied access_code does not match",
            ERR_INVALID_ACCESS_CODE[1],
        )


def consent_recorded(recipient, session=None):
    if recipient.get("consent_accepted"):
        return True
    if session is not None and session.get("consent_to_electronic_records"):
        return True
    return False


def guard_consent(recipient, session=None):
    """priority 19: consent accepted on the Recipient or on the SigningSession."""
    if not consent_recorded(recipient, session):
        raise ApiError(
            ERR_CONSENT_REQUIRED[0],
            "consent to electronic records was not recorded before signing",
            ERR_CONSENT_REQUIRED[1],
        )


# --- authenticate -------------------------------------------------------

def authenticate_recipient(envelope, recipient, method, body):
    """Complete the recipient authentication challenge (PRD §3.4)."""
    guard_envelope_not_expired(envelope)
    guard_auth_max_attempts(recipient, method)

    success = False
    if method == "EMAIL_ACCESS":
        success = True
    elif method == "ACCESS_CODE":
        # A mismatched access code is a challenge failure: the refusal is raised
        # (priority 20, HTTP 401) but the failure side effect PRD §3.4 requires
        # — auth_status FAILED and an AUTH_FAILED audit event — is recorded
        # first, so the parallel auth dimension reflects the attempt.
        try:
            guard_access_code(recipient, body.get("access_code"))
        except ApiError:
            recipient["auth_status"] = "FAILED"
            touch(recipient)
            recompute_provisional_scores(envelope["id"])
            append_event(
                envelope["id"], "AUTH_FAILED", recipient_id=recipient["id"]
            )
            raise
        success = True
    elif method == "KBA":
        success = bool(body.get("kba_answers_correct"))
    elif method == "ID_DOCUMENT":
        verified = bool(body.get("identity_document_verified"))
        if verified:
            recipient["identity_verified"] = True
        success = verified

    if success:
        recipient["auth_status"] = "AUTHENTICATED"
    else:
        recipient["auth_status"] = "FAILED"
        if method == "KBA":
            recipient["kba_fail_count"] = int(recipient.get("kba_fail_count", 0)) + 1

    recompute_provisional_scores(envelope["id"])
    append_event(
        envelope["id"],
        "AUTH_SUCCEEDED" if success else "AUTH_FAILED",
        recipient_id=recipient["id"],
    )
    return recipient


# --- sessions -----------------------------------------------------------

def open_session(envelope, recipient, consent_flag):
    """Open a signing session (PRD §3.3)."""
    guard_routing_released(envelope, recipient)
    guard_envelope_not_expired(envelope)
    if recipient["auth_status"] == "FAILED":
        raise ApiError(
            "ERR_AUTH_REQUIRED",
            "a recipient whose authentication failed may not open a session",
            422,
        )
    for session in db.sessions_of_recipient(recipient["id"]):
        if session["status"] == "OPEN":
            raise ApiError(
                ERR_RECIPIENT_TERMINAL[0],
                "the recipient already holds an open signing session",
                ERR_RECIPIENT_TERMINAL[1],
            )
    if recipient["status"] not in ("WAITING", "SENT", "DELIVERED"):
        raise ApiError(
            ERR_RECIPIENT_TERMINAL[0],
            "recipient status %s may not open a signing session"
            % recipient["status"],
            ERR_RECIPIENT_TERMINAL[1],
        )
    return None


def release_next_routing_group(envelope, recipient):
    """After a signature/approval, every recipient of the envelope at the
    next-higher routing_order whose status is still WAITING moves to SENT with
    auth_status PENDING (scaffold §1.2, PRD §3.5)."""
    current = int(recipient.get("routing_order", 1))
    later_orders = [
        int(r.get("routing_order", 1))
        for r in db.recipients_of(envelope["id"])
        if int(r.get("routing_order", 1)) > current
    ]
    if not later_orders:
        return []
    next_order = min(later_orders)
    released = []
    for other in db.recipients_of(envelope["id"]):
        if int(other.get("routing_order", 1)) != next_order:
            continue
        if other["status"] == "WAITING":
            other["status"] = "SENT"
            other["auth_status"] = "PENDING"
            touch(other)
            released.append(other)
    return released


def seal_final_score(recipient):
    recipient["auth_risk_score_final"] = final_risk_score(recipient)
    return recipient["auth_risk_score_final"]