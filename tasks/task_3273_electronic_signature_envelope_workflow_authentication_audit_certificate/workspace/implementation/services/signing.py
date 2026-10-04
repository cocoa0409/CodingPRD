"""Signing, approval, decline, sealing, purge, legal hold and reminders."""

from db import db, new_id, now_clock
from errors import (
    ApiError,
    ERR_ENVELOPE_TERMINAL,
    ERR_FIELD_REQUIRED,
    ERR_INVALID_ENVELOPE_STATE,
    ERR_INVALID_REQUEST,
    ERR_LEGAL_HOLD_FROZEN,
    ERR_RECIPIENT_TERMINAL,
    ERR_REMINDER_COOLDOWN,
    ERR_RETENTION_NOT_EXPIRED,
    ERR_SESSION_CLOSED,
    ERR_SOD_VIOLATION,
)
from services.calculations import (
    audit_certificate_view,
    document_order,
    hold_blocks_purge,
    purge_eligible_at,
)
from services.common import (
    append_event,
    chain_fingerprint,
    hash_bytes,
    ordered_events,
    seal_hash_of,
    stamp_new,
    touch,
)
from services.lifecycle import (
    decline_cascade,
    expire_cascade,
    guard_envelope_from_set,
    guard_envelope_terminal,
    guard_expected_version,
    guard_not_frozen,
    is_envelope_terminal,
    legal_hold_active,
    void_cascade,
)
from services.recipient import (
    SIGNER_APPROVER,
    guard_auth_level_sufficient,
    guard_auth_requirement,
    guard_consent,
    guard_envelope_not_expired,
    guard_recipient_terminal,
    guard_routing_released,
    release_next_routing_group,
    seal_final_score,
)
from timeutil import fmt, parse_iso

REMINDABLE_STATUSES = ("SENT", "DELIVERED", "SIGNING")
REMINDER_COOLDOWN_HOURS = 24
SIGNED_OR_APPROVED = ("SIGNED", "APPROVED")


def open_session_for(recipient_id):
    for session in db.sessions_of_recipient(recipient_id):
        if session["status"] == "OPEN":
            return session
    return None


# --- signing ------------------------------------------------------------

def sign_recipient(envelope, recipient):
    """Sign (SIGNER) or approve (APPROVER) — PRD §3.5.

    Guard ladder in ascending priority order:
      14 ERR_RECIPIENT_TERMINAL, 15 ERR_SESSION_CLOSED,
      16 ERR_AUTH_LEVEL_TOO_LOW, 17 ERR_AUTH_REQUIRED, 19 ERR_CONSENT_REQUIRED,
      21 ERR_ROUTING_NOT_RELEASED, 22 ERR_ENVELOPE_EXPIRED,
      24 ERR_FIELD_REQUIRED
    """
    guard_recipient_terminal(recipient)

    session = open_session_for(recipient["id"])
    if session is None:
        raise ApiError(
            ERR_SESSION_CLOSED[0],
            "the recipient has no OPEN signing session",
            ERR_SESSION_CLOSED[1],
        )

    guard_auth_level_sufficient(recipient)
    guard_auth_requirement(recipient)
    guard_consent(recipient, session)
    guard_routing_released(envelope, recipient)
    guard_envelope_not_expired(envelope)
    guard_required_fields_complete(recipient)

    seal_final_score(recipient)
    recipient["signed_at"] = fmt(now_clock())
    if recipient["role"] == "APPROVER":
        recipient["status"] = "APPROVED"
        event_type = "RECIPIENT_APPROVED"
    else:
        recipient["status"] = "SIGNED"
        event_type = "RECIPIENT_SIGNED"
    touch(recipient)

    session["status"] = "COMPLETED"
    touch(session)
    append_event(
        envelope["id"], "FIELD_COMPLETED", recipient_id=recipient["id"],
        detail="field work completed",
    )

    release_next_routing_group(envelope, recipient)
    append_event(envelope["id"], event_type, recipient_id=recipient["id"])
    return recipient


def guard_required_fields_complete(recipient):
    """priority 24: every required field, and every SIGNATURE field, must hold a
    value (scaffold §1.4, PRD §3.5)."""
    for field in db.fields_of(recipient["envelope_id"]):
        if field["recipient_id"] != recipient["id"]:
            continue
        if field["required"] or field["field_type"] == "SIGNATURE":
            if field.get("value") is None:
                raise ApiError(
                    ERR_FIELD_REQUIRED[0],
                    "required field %s still has no value" % field["id"],
                    ERR_FIELD_REQUIRED[1],
                )


def guard_envelope_fields_complete(envelope):
    """priority 24 for the sealing path: every required placement on the
    envelope must hold a value."""
    for field in db.fields_of(envelope["id"]):
        if field["required"] or field["field_type"] == "SIGNATURE":
            if field.get("value") is None:
                raise ApiError(
                    ERR_FIELD_REQUIRED[0],
                    "required field %s still has no value" % field["id"],
                    ERR_FIELD_REQUIRED[1],
                )


# --- decline ------------------------------------------------------------

def decline_recipient(envelope, recipient, decline_reason):
    """Decline to sign; bubbles the decline up to the envelope (PRD §3.5).

    Envelope DELIVERED/SENT -> DECLINED preconditions: the acting recipient's
    role is SIGNER and its status is one of DELIVERED, AUTHENTICATED or
    SIGNING. Only a SIGNER may decline — the refusal is a state refusal.
    """
    guard_recipient_terminal(recipient)
    if recipient["role"] != "SIGNER":
        raise ApiError(
            ERR_INVALID_ENVELOPE_STATE[0],
            "only a SIGNER recipient may decline",
            ERR_INVALID_ENVELOPE_STATE[1],
        )
    actionable = (
        recipient["status"] in ("DELIVERED", "SIGNING")
        or recipient["auth_status"] == "AUTHENTICATED"
    )
    if not actionable:
        raise ApiError(
            ERR_INVALID_ENVELOPE_STATE[0],
            "recipient status %s is not one of DELIVERED, AUTHENTICATED or "
            "SIGNING" % recipient["status"],
            ERR_INVALID_ENVELOPE_STATE[1],
        )
    guard_not_frozen(envelope)
    guard_envelope_from_set(envelope, ("SENT", "DELIVERED"))
    return decline_cascade(envelope, recipient, decline_reason)


# --- sealing ------------------------------------------------------------

def segregation_of_duties_violation(actor, envelope):
    """priority 4: the sealing identity must not be an identity that
    authenticated and signed any recipient of the same envelope (PRD §2.4)."""
    if actor is None or not actor.is_account:
        return False
    for recipient in db.recipients_of(envelope["id"]):
        if recipient["id"] != actor.user_id:
            continue
        if recipient.get("signed_at") is not None:
            return True
        if recipient["auth_status"] == "AUTHENTICATED":
            return True
    return False


def complete_envelope(envelope, actor, expected_version):
    """Seal a fully-signed envelope and generate its audit certificate
    (PRD §3.6). Guard ladder: 4, 11, 12, 13, 24, 33."""
    if segregation_of_duties_violation(actor, envelope):
        raise ApiError(
            ERR_SOD_VIOLATION[0],
            "the sealing identity also acted as a recipient of this envelope",
            ERR_SOD_VIOLATION[1],
        )
    guard_envelope_terminal(envelope)
    guard_not_frozen(envelope)
    guard_envelope_from_set(envelope, ("DELIVERED",))

    # priority 13: every SIGNER/APPROVER must already be SIGNED or APPROVED
    for recipient in db.recipients_of(envelope["id"]):
        if recipient["role"] in SIGNER_APPROVER:
            if recipient["status"] not in SIGNED_OR_APPROVED:
                raise ApiError(
                    ERR_INVALID_ENVELOPE_STATE[0],
                    "recipient %s is not yet SIGNED or APPROVED"
                    % recipient["id"],
                    ERR_INVALID_ENVELOPE_STATE[1],
                )

    guard_envelope_fields_complete(envelope)
    guard_expected_version(envelope, expected_version)

    envelope["status"] = "COMPLETED"
    envelope["is_sealed"] = True
    envelope["seal_hash"] = seal_hash_of(envelope["id"])

    certificate_doc = {
        "id": new_id(),
        "envelope_id": envelope["id"],
        "name": "AuditCertificate.pdf",
        "page_count": 1,
        "document_hash": hash_bytes(
            "certificate|" + envelope["id"] + "|" + str(len(ordered_events(envelope["id"])))
        ),
        "is_certificate": True,
    }
    stamp_new(certificate_doc)
    db.insert(db.documents, certificate_doc)
    envelope["audit_certificate_id"] = certificate_doc["id"]

    append_event(envelope["id"], "SEALED", detail="envelope sealed")
    append_event(
        envelope["id"], "CERTIFICATE_GENERATED",
        detail="audit certificate generated",
    )

    # The certificate covers the whole ordered chain, including the SEALED and
    # CERTIFICATE_GENERATED events it attests to (PRD §3.6).
    envelope["certificate_hash"] = chain_fingerprint(ordered_events(envelope["id"]))

    template_id = envelope.get("template_id")
    if template_id:
        template = db.template(template_id)
        if template is not None:
            template["times_used"] = int(template.get("times_used", 0)) + 1
            touch(template)

    touch(envelope)
    return envelope


# --- purge / legal hold / reminders -------------------------------------

def purge_envelope(envelope, expected_version):
    """Purge envelope content once retention has expired, unless frozen.
    Guard ladder: 12 (retention-overlap hold), 23 retention, 33 stale."""
    # PRD §2.7 ladder: the priority-12 overlap freeze is a distinct, earlier rule
    # than the priority-23 retention gate, so it is evaluated first and must not
    # be masked by an unexpired retention window.
    eligible = purge_eligible_at(envelope)
    if hold_blocks_purge(envelope, eligible):
        raise ApiError(
            ERR_LEGAL_HOLD_FROZEN[0],
            "the retention window overlaps an active legal hold",
            ERR_LEGAL_HOLD_FROZEN[1],
        )
    if eligible is None or now_clock() < eligible:
        raise ApiError(
            ERR_RETENTION_NOT_EXPIRED[0],
            "the envelope's purge-eligible instant has not been reached",
            ERR_RETENTION_NOT_EXPIRED[1],
        )
    guard_expected_version(envelope, expected_version)

    envelope["purged_at"] = fmt(now_clock())

    policy = db.policy(envelope.get("retention_policy_id"))
    if policy is not None and policy["purge_mode"] == "DELETE_ALL":
        doomed = [
            d["id"]
            for d in db.documents_of(envelope["id"])
            if d["is_certificate"]
        ]
        for document_id in doomed:
            db.documents.pop(document_id, None)

    append_event(envelope["id"], "PURGED", detail="envelope content purged")
    touch(envelope)
    return envelope


def set_legal_hold(envelope, legal_hold, hold_until):
    if legal_hold:
        envelope["legal_hold"] = True
        envelope["legal_hold_started_at"] = fmt(now_clock())
        envelope["legal_hold_until"] = (
            fmt(parse_iso(hold_until)) if hold_until else None
        )
    else:
        envelope["legal_hold"] = False
        envelope["legal_hold_until"] = None
        envelope["legal_hold_started_at"] = None
    touch(envelope)
    return envelope


def send_reminders(envelope):
    """Reminder fan-out with the per-recipient 24-hour cooldown (PRD §3.7)."""
    guard_envelope_terminal(envelope)

    targets = [
        r
        for r in db.recipients_of(envelope["id"])
        if r["status"] in REMINDABLE_STATUSES
    ]

    # Atomicity: evaluate the cooldown for every target before mutating any.
    now = now_clock()
    for recipient in targets:
        last = parse_iso(recipient.get("last_reminder_at"))
        if last is None:
            continue
        if now < last + _cooldown_delta():
            raise ApiError(
                ERR_REMINDER_COOLDOWN[0],
                "recipient %s was reminded inside the 24-hour cooldown window"
                % recipient["id"],
                ERR_REMINDER_COOLDOWN[1],
            )

    for recipient in targets:
        recipient["reminder_count"] = int(recipient.get("reminder_count", 0)) + 1
        recipient["last_reminder_at"] = fmt(now)
        touch(recipient)
        append_event(
            envelope["id"], "REMINDER_SENT", recipient_id=recipient["id"],
            detail="reminder sent",
        )

    touch(envelope)
    return envelope


def _cooldown_delta():
    from datetime import timedelta

    return timedelta(hours=REMINDER_COOLDOWN_HOURS)


# re-exported for the route layer
__all__ = [
    "sign_recipient",
    "decline_recipient",
    "complete_envelope",
    "purge_envelope",
    "set_legal_hold",
    "send_reminders",
    "void_cascade",
    "expire_cascade",
    "legal_hold_active",
    "is_envelope_terminal",
    "audit_certificate_view",
    "document_order",
]