"""Envelope assembly, authentication plumbing and the send transition."""

import base64

from db import db, new_id, now_clock
from errors import (
    ApiError,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_DOCUMENT_ENVELOPE_MISMATCH,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_DUPLICATE_RECIPIENT,
    ERR_INSUFFICIENT_CREDIT,
    ERR_INVALID_ENVELOPE_STATE,
    ERR_INVALID_REQUEST,
    ERR_RECIPIENT_ENVELOPE_MISMATCH,
    ERR_RETENTION_POLICY_NOT_FOUND,
    ERR_ROUTING_ORDER_GAP,
    ERR_TEMPLATE_NOT_FOUND,
)
from services.calculations import (
    credit_spend_consumption,
    recompute_provisional_scores,
)
from services.common import (
    append_event,
    hash_bytes,
    stamp_new,
    touch,
)
from services.lifecycle import (
    guard_envelope_from_set,
    guard_envelope_terminal,
    guard_not_frozen,
    is_envelope_terminal,
)
from services.recipient import SIGNER_APPROVER
from timeutil import add_business_days, add_calendar_days, at_end_of_day, fmt
from timeutil import parse_iso

VALID_ROUTING_MODES = ("SEQUENTIAL", "PARALLEL")
VALID_RECIPIENT_ROLES = ("SIGNER", "APPROVER", "COPY")
VALID_AUTH_LEVELS = ("EMAIL_ACCESS", "ACCESS_CODE", "KBA", "ID_DOCUMENT")
VALID_FIELD_TYPES = ("SIGNATURE", "INITIAL", "DATE", "TEXT", "CHECKBOX")


# --- lookups ------------------------------------------------------------

def load_envelope(envelope_id):
    envelope = db.envelope(envelope_id)
    if envelope is None:
        from errors import ERR_ENVELOPE_NOT_FOUND

        raise ApiError(
            ERR_ENVELOPE_NOT_FOUND[0],
            "no envelope matches id %s" % envelope_id,
            ERR_ENVELOPE_NOT_FOUND[1],
        )
    return envelope


def load_recipient(recipient_id):
    recipient = db.recipient(recipient_id)
    if recipient is None:
        from errors import ERR_RECIPIENT_NOT_FOUND

        raise ApiError(
            ERR_RECIPIENT_NOT_FOUND[0],
            "no recipient matches id %s" % recipient_id,
            ERR_RECIPIENT_NOT_FOUND[1],
        )
    return recipient


def load_account(account_id):
    account = db.account(account_id)
    if account is None:
        raise ApiError(
            ERR_ACCOUNT_NOT_FOUND[0],
            "no account matches id %s" % account_id,
            ERR_ACCOUNT_NOT_FOUND[1],
        )
    return account


def load_policy(policy_id):
    policy = db.policy(policy_id)
    if policy is None:
        raise ApiError(
            ERR_RETENTION_POLICY_NOT_FOUND[0],
            "no retention policy matches id %s" % policy_id,
            ERR_RETENTION_POLICY_NOT_FOUND[1],
        )
    return policy


def load_template(template_id):
    template = db.template(template_id)
    if template is None:
        raise ApiError(
            ERR_TEMPLATE_NOT_FOUND[0],
            "no template matches id %s" % template_id,
            ERR_TEMPLATE_NOT_FOUND[1],
        )
    return template


# --- creation -----------------------------------------------------------

def build_envelope(body, routing_mode=None, template=None):
    account = load_account(body.get("sender_account_id"))
    load_policy(body.get("retention_policy_id"))

    subject = body.get("subject")
    if subject is None or str(subject).strip() == "":
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "required field 'subject' is missing",
            ERR_INVALID_REQUEST[1],
        )

    if routing_mode is None:
        routing_mode = body.get("routing_mode") or "SEQUENTIAL"
    if routing_mode not in VALID_ROUTING_MODES:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "routing_mode must be one of %s" % "|".join(VALID_ROUTING_MODES),
            ERR_INVALID_REQUEST[1],
        )

    expires_after_days = body.get("expires_after_days")
    if expires_after_days is None:
        expires_after_days = 120
    sender_visible_window_days = body.get("sender_visible_window_days")
    if sender_visible_window_days is None:
        sender_visible_window_days = 30

    envelope = {
        "id": new_id(),
        "sender_account_id": account["id"],
        "subject": subject,
        "status": "CREATED",
        "routing_mode": routing_mode,
        "sender_visible_window_days": int(sender_visible_window_days),
        "sent_at": None,
        "expires_at": None,
        "expires_after_days": int(expires_after_days),
        "sender_visible_expires_at": None,
        "is_sealed": False,
        "seal_hash": None,
        "certificate_hash": None,
        "audit_certificate_id": None,
        "retention_policy_id": body.get("retention_policy_id"),
        "legal_hold": bool(body.get("legal_hold", False)),
        "legal_hold_started_at": None,
        "legal_hold_until": None,
        "purged_at": None,
        "decline_reason": None,
        "void_reason": None,
        "template_id": body.get("template_id"),
    }
    stamp_new(envelope)
    db.insert(db.envelopes, envelope)
    append_event(envelope["id"], "ENVELOPE_CREATED", detail="envelope created")
    return envelope


def add_document(envelope, body):
    name = body.get("name")
    if name is None or str(name).strip() == "":
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'name' is missing",
            ERR_INVALID_REQUEST[1],
        )
    page_count = body.get("page_count")
    if page_count is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'page_count' is missing",
            ERR_INVALID_REQUEST[1],
        )
    try:
        page_count = int(page_count)
    except (TypeError, ValueError):
        raise ApiError(
            ERR_INVALID_REQUEST[0], "page_count must be an integer",
            ERR_INVALID_REQUEST[1],
        )
    if page_count < 1:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "page_count must be at least 1",
            ERR_INVALID_REQUEST[1],
        )

    seed = "|".join([envelope["id"], str(name), str(page_count),
                     str(len(db.documents_of(envelope["id"])))])
    document = {
        "id": new_id(),
        "envelope_id": envelope["id"],
        "name": name,
        "page_count": page_count,
        "document_hash": hash_bytes(seed),
        "is_certificate": False,
    }
    stamp_new(document)
    db.insert(db.documents, document)
    append_event(
        envelope["id"], "DOCUMENT_HASHED", detail="document %s hashed" % name
    )
    touch(envelope)
    return document


def add_recipient(envelope, body):
    role = body.get("role")
    if role not in VALID_RECIPIENT_ROLES:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "role must be one of %s" % "|".join(VALID_RECIPIENT_ROLES),
            ERR_INVALID_REQUEST[1],
        )
    email = body.get("email")
    if email is None or str(email).strip() == "":
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'email' is missing",
            ERR_INVALID_REQUEST[1],
        )
    routing_order = body.get("routing_order")
    routing_order = 1 if routing_order is None else int(routing_order)
    auth_level = body.get("auth_level") or "EMAIL_ACCESS"
    if auth_level not in VALID_AUTH_LEVELS:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "auth_level must be one of %s" % "|".join(VALID_AUTH_LEVELS),
            ERR_INVALID_REQUEST[1],
        )

    # priority 25: no two recipients share an email at the same routing_order
    for other in db.recipients_of(envelope["id"]):
        if (
            other["email"] == email
            and int(other["routing_order"]) == routing_order
        ):
            raise ApiError(
                ERR_DUPLICATE_RECIPIENT[0],
                "another recipient already uses %s at routing_order %s"
                % (email, routing_order),
                ERR_DUPLICATE_RECIPIENT[1],
            )

    recipient = {
        "id": new_id(),
        "envelope_id": envelope["id"],
        "role": role,
        "email": email,
        "routing_order": routing_order,
        "status": "WAITING",
        "auth_status": "PENDING",
        "auth_level": auth_level,
        "access_code": body.get("access_code"),
        "kba_fail_count": 0,
        "identity_verified": False,
        "consent_accepted": bool(body.get("consent_accepted", False)),
        "consent_accepted_at": None,
        "auth_risk_score": 0,
        "auth_risk_score_final": 0,
        "signed_at": None,
        "reminder_count": 0,
        "last_reminder_at": None,
    }
    if recipient["consent_accepted"]:
        recipient["consent_accepted_at"] = fmt(now_clock())
    stamp_new(recipient)
    db.insert(db.recipients, recipient)
    touch(envelope)
    return recipient


def add_field(envelope, body):
    document_id = body.get("envelope_document_id")
    document = db.document(document_id)
    if document is None:
        raise ApiError(
            ERR_DOCUMENT_NOT_FOUND[0],
            "no document matches id %s" % document_id,
            ERR_DOCUMENT_NOT_FOUND[1],
        )
    recipient_id = body.get("recipient_id")
    recipient = db.recipient(recipient_id)
    if recipient is None:
        raise ApiError(
            ERR_RECIPIENT_ENVELOPE_MISMATCH[0],
            "no recipient matches id %s" % recipient_id,
            ERR_RECIPIENT_ENVELOPE_MISMATCH[1],
        )
    # priority 29: recipient must belong to the envelope in the path
    if recipient["envelope_id"] != envelope["id"]:
        raise ApiError(
            ERR_RECIPIENT_ENVELOPE_MISMATCH[0],
            "recipient %s does not belong to envelope %s"
            % (recipient_id, envelope["id"]),
            ERR_RECIPIENT_ENVELOPE_MISMATCH[1],
        )
    # priority 30: document must belong to the envelope in the path
    if document["envelope_id"] != envelope["id"]:
        raise ApiError(
            ERR_DOCUMENT_ENVELOPE_MISMATCH[0],
            "document %s does not belong to envelope %s"
            % (document_id, envelope["id"]),
            ERR_DOCUMENT_ENVELOPE_MISMATCH[1],
        )

    field_type = body.get("field_type")
    if field_type not in VALID_FIELD_TYPES:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "field_type must be one of %s" % "|".join(VALID_FIELD_TYPES),
            ERR_INVALID_REQUEST[1],
        )
    page_number = body.get("page_number")
    if page_number is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'page_number' is missing",
            ERR_INVALID_REQUEST[1],
        )
    page_number = int(page_number)
    if page_number < 1:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "page_number must be at least 1",
            ERR_INVALID_REQUEST[1],
        )

    required = body.get("required")
    # SIGNATURE fields are always required and always count toward completion.
    if field_type == "SIGNATURE":
        required = True
    elif required is None:
        required = True
    else:
        required = bool(required)

    tab_order = body.get("tab_order")
    tab_order = 1 if tab_order is None else int(tab_order)

    field = {
        "id": new_id(),
        "envelope_id": envelope["id"],
        "envelope_document_id": document_id,
        "recipient_id": recipient_id,
        "field_type": field_type,
        "required": required,
        "value": body.get("value"),
        "page_number": page_number,
        "tab_order": tab_order,
    }
    stamp_new(field)
    db.insert(db.fields, field)
    if field["value"] is not None:
        append_event(
            envelope["id"], "FIELD_COMPLETED",
            recipient_id=recipient_id,
            detail="field %s completed" % field["id"],
        )
    touch(envelope)
    return field


# --- send ---------------------------------------------------------------

def routing_order_gap(envelope):
    """For a SEQUENTIAL envelope the routing_order set among SIGNER/APPROVER
    recipients must equal {1..max} exactly (priority 26)."""
    orders = sorted(
        {
            int(r.get("routing_order", 1))
            for r in db.recipients_of(envelope["id"])
            if r["role"] in SIGNER_APPROVER
        }
    )
    if not orders:
        return False
    return orders != list(range(1, orders[-1] + 1))


def guard_routing_contiguous(envelope):
    if envelope["routing_mode"] != "SEQUENTIAL":
        return
    if routing_order_gap(envelope):
        raise ApiError(
            ERR_ROUTING_ORDER_GAP[0],
            "sequential routing orders are not the contiguous set {1..max}",
            ERR_ROUTING_ORDER_GAP[1],
        )


def guard_credit_sufficient(envelope):
    account = db.account(envelope["sender_account_id"])
    needed = credit_spend_consumption(envelope)
    if int(account["credit_balance"]) < needed:
        raise ApiError(
            ERR_INSUFFICIENT_CREDIT[0],
            "account credit_balance %s is below the required %s credit units"
            % (account["credit_balance"], needed),
            ERR_INSUFFICIENT_CREDIT[1],
        )
    return needed


def send_envelope(envelope):
    """CREATED -> SENT with the full guard ladder and side-effect set."""
    # priority 11 terminal, 12 legal hold, 13 from-set
    guard_envelope_terminal(envelope)
    guard_not_frozen(envelope)
    guard_envelope_from_set(envelope, ("CREATED",))

    documents = db.documents_of(envelope["id"])
    if not any(d["page_count"] >= 1 for d in documents):
        raise ApiError(
            ERR_INVALID_ENVELOPE_STATE[0],
            "the envelope has no document with page_count >= 1",
            ERR_INVALID_ENVELOPE_STATE[1],
        )
    recipients = db.recipients_of(envelope["id"])
    if not any(r["role"] in SIGNER_APPROVER for r in recipients):
        raise ApiError(
            ERR_INVALID_ENVELOPE_STATE[0],
            "the envelope has no SIGNER or APPROVER recipient",
            ERR_INVALID_ENVELOPE_STATE[1],
        )
    # every field placement must resolve to a document of this envelope
    document_ids = {d["id"] for d in documents}
    for field in db.fields_of(envelope["id"]):
        if field["envelope_document_id"] not in document_ids:
            raise ApiError(
                ERR_DOCUMENT_ENVELOPE_MISMATCH[0],
                "field %s points at a document outside this envelope"
                % field["id"],
                ERR_DOCUMENT_ENVELOPE_MISMATCH[1],
            )

    # priority 26 routing continuity, then priority 31 credit sufficiency
    guard_routing_contiguous(envelope)
    needed = guard_credit_sufficient(envelope)

    sent_at = now_clock()
    envelope["sent_at"] = fmt(sent_at)
    envelope["expires_at"] = fmt(
        at_end_of_day(add_calendar_days(sent_at, int(envelope["expires_after_days"])))
    )
    envelope["sender_visible_expires_at"] = fmt(
        at_end_of_day(
            add_business_days(sent_at, int(envelope["sender_visible_window_days"]))
        )
    )

    account = db.account(envelope["sender_account_id"])
    account["credit_balance"] = int(account["credit_balance"]) - needed
    touch(account)

    envelope["status"] = "SENT"
    for recipient in db.recipients_of(envelope["id"]):
        if int(recipient.get("routing_order", 1)) == 1:
            recipient["status"] = "SENT"
            recipient["auth_status"] = "PENDING"
            touch(recipient)

    recompute_provisional_scores(envelope["id"])
    append_event(envelope["id"], "SENT", detail="envelope sent")
    touch(envelope)
    return envelope


def feed_envelope(envelope, feed_event):
    """The delivery feed (PRD §3.7). Only DELIVERED is a declared feed event."""
    guard_not_frozen(envelope)
    if feed_event != "DELIVERED":
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "feed_event must be DELIVERED",
            ERR_INVALID_REQUEST[1],
        )
    guard_envelope_from_set(envelope, ("SENT",))
    envelope["status"] = "DELIVERED"
    for recipient in db.recipients_of(envelope["id"]):
        if (
            recipient["status"] == "SENT"
            and int(recipient.get("routing_order", 1)) == 1
        ):
            recipient["status"] = "DELIVERED"
            touch(recipient)
    append_event(envelope["id"], "DELIVERED", detail="delivery confirmed")
    touch(envelope)
    return envelope