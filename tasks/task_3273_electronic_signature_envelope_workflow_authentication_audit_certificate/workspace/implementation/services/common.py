"""Shared model helpers: system fields, serialization, audit chain, sealing."""

import hashlib

from db import db, new_id, now_clock
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
)
from timeutil import fmt

# Fields that must never appear in a response body (scaffold §1.1 Recipient:
# "shared secret required when auth_level is ACCESS_CODE; never returned in
# responses"; PRD §3.1 repeats it). `_ord` is an internal ordering key.
SCRUBBED_FIELDS = ("access_code", "_ord")


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_bytes(seed_text):
    """Server-stamped document hash over the assembled bytes."""
    return hashlib.sha256(seed_text.encode("utf-8")).hexdigest()


def stamp_new(obj):
    """Apply the common system fields to a freshly created resource."""
    instant = fmt(now_clock())
    obj["created_at"] = instant
    obj["updated_at"] = instant
    obj["version"] = 1
    return obj


def touch(obj):
    """Record a modification: refresh updated_at and bump version by one."""
    obj["updated_at"] = fmt(now_clock())
    obj["version"] = int(obj.get("version", 0)) + 1
    return obj


def serialize(obj):
    """Return a response-safe copy of a stored resource."""
    if obj is None:
        return None
    out = dict(obj)
    for field_name in SCRUBBED_FIELDS:
        out.pop(field_name, None)
    return out


def serialize_list(objects):
    return [serialize(o) for o in objects]


def require_body(body):
    if not isinstance(body, dict):
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "request body must be a JSON object",
            ERR_INVALID_REQUEST[1],
        )
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "required field '%s' is missing" % name,
            ERR_INVALID_REQUEST[1],
        )
    return body[name]


def require_enum(body, name, allowed, default=None):
    """Fetch an enum-valued body field, defaulting when the key is absent."""
    if name not in body or body[name] is None:
        if default is not None:
            return default
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "required field '%s' is missing" % name,
            ERR_INVALID_REQUEST[1],
        )
    value = body[name]
    if value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "field '%s' must be one of %s" % (name, "|".join(allowed)),
            ERR_INVALID_REQUEST[1],
        )
    return value


def optional(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


# --- audit chain --------------------------------------------------------

def next_sequence(envelope_id):
    events = db.events_of(envelope_id)
    return len(events) + 1


def append_event(envelope_id, event_type, recipient_id=None, detail=None):
    """Append an immutable AuditEvent and extend the tamper-evident chain.

    The chain is maintained on write (scaffold §1.1 AuditEvent, PRD §2.11):
      prev_hash  = previous event's event_hash (null for sequence_number 1)
      event_hash = sha256(str(sequence_number) + "|" + event_type + "|" +
                          iso8601(event_at) + "|" + (prev_hash or ""))
    """
    ordered = ordered_events(envelope_id)
    prev = ordered[-1]["event_hash"] if ordered else None
    sequence_number = len(ordered) + 1
    event = {
        "id": new_id(),
        "envelope_id": envelope_id,
        "sequence_number": sequence_number,
        "event_type": event_type,
        "recipient_id": recipient_id,
        "event_at": fmt(now_clock()),
        "prev_hash": prev,
        "event_hash": None,
        "detail": detail,
        "created_at": fmt(now_clock()),
    }
    event["event_hash"] = compute_event_hash(event, prev)
    db.insert(db.audit_events, event)
    return event


def compute_event_hash(event, prev_hash):
    payload = "|".join(
        [
            str(event["sequence_number"]),
            event["event_type"],
            event["event_at"] or "",
            prev_hash or "",
        ]
    )
    return sha256_hex(payload)


def ordered_events(envelope_id):
    events = db.events_of(envelope_id)
    events.sort(key=lambda e: (e["sequence_number"], e["id"]))
    return events


def event_chain_of(envelope_id):
    return ordered_events(envelope_id)


def chain_fingerprint(events):
    return sha256_hex("|".join(e["event_hash"] for e in events))


def seal_hash_of(envelope_id):
    docs = ordered_documents_for_seal(envelope_id)
    return sha256_hex("|".join(d["document_hash"] for d in docs))


def ordered_documents_for_seal(envelope_id):
    """Documents of the envelope in creation order (seal input set)."""
    docs = db.documents_of(envelope_id)
    docs.sort(key=lambda d: (d["created_at"], d.get("_ord", 0)))
    return docs


def total_pages(envelope_id):
    """Sum of page_count over non-certificate documents (PRD §2.9)."""
    return sum(
        d["page_count"]
        for d in db.documents_of(envelope_id)
        if not d["is_certificate"]
    )