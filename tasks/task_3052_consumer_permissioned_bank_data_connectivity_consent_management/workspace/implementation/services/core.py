"""Shared domain helpers: clock, cascades, health recompute, serializers."""

from datetime import datetime, timezone, timedelta

import db
from errors import err

DATA_SCOPES = {"BALANCE", "TRANSACTIONS", "IDENTITY", "INCOME", "ASSETS"}
METHODS = {"CREDENTIALS", "OAUTH_TOKEN", "BANK_API"}
TARGET_METHODS = {"BANK_API", "OAUTH_TOKEN"}
MINIMIZATION = {"STRICT", "STANDARD", "BROAD"}
RATE_CLASSES = {"LOW", "MEDIUM", "HIGH"}
FAILURE_REASONS = {"TRANSIENT", "INSTITUTION_DOWN", "CREDENTIALS_INVALID", "RATE_LIMITED"}
JOB_KINDS = {"FULL", "INCREMENTAL"}

MINIMIZATION_FORBIDDEN = {
    "STRICT": {"IDENTITY", "INCOME", "ASSETS"},
    "STANDARD": {"INCOME", "ASSETS"},
    "BROAD": set(),
}

UNIT_COST = {
    "LOW": {"FULL": 2, "INCREMENTAL": 1},
    "MEDIUM": {"FULL": 4, "INCREMENTAL": 2},
    "HIGH": {"FULL": 8, "INCREMENTAL": 3},
}
FREE_UNITS = {"LOW": 10, "MEDIUM": 20, "HIGH": 40}

CONSENT_TERMINAL = {"REVOKED", "EXPIRED", "SUPERSEDED"}
DISCONNECTABLE_CONN_STATES = {"PENDING_AUTH", "ACTIVE", "REAUTH_REQUIRED", "BROKEN", "MIGRATING"}


def parse_dt(value, field_name):
    """Parse an ISO8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{field_name} must be an ISO8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"{field_name} is not a parseable datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    return db.ts_iso(dt)


# ---------------------------------------------------------------- audit log

def audit(actor_role, action, entity_type, entity_id, detail=None):
    entry = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "actor_role": actor_role,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "occurred_at": db.now_iso(),
        "detail": detail or {},
    }
    db.audit_logs[entry["id"]] = entry
    return entry


# ---------------------------------------------------------------- webhooks

def emit_webhook(connection_id, recipient_id, event_type, payload=None):
    ev = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "connection_id": connection_id,
        "recipient_id": recipient_id,
        "event_type": event_type,
        "payload": payload or {},
        "delivery_attempts": 0,
        "delivered_at": None,
    }
    db.webhook_events[ev["id"]] = ev
    return ev


# ---------------------------------------------------------------- common field helpers

def stamp_new(entity):
    """Set id/created_at/updated_at/version on a fresh primary entity."""
    entity["id"] = db.new_id()
    entity["created_at"] = db.now_iso()
    entity["updated_at"] = db.now_iso()
    entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = db.now_iso()
    entity["version"] += 1
    return entity


# ---------------------------------------------------------------- consent expiry

def consent_is_expired(consent):
    return consent["status"] == "ACTIVE" and db.get_clock() >= consent["_expires_dt"]


def expire_consent(consent):
    """ACTIVE -> EXPIRED with full cascade. Returns True if transition happened."""
    if not consent_is_expired(consent):
        return False
    _terminate_consent(consent, "EXPIRED", "CONSENT_EXPIRED")
    return True


def _terminate_consent(consent, new_status, webhook_type):
    """Shared revocation/expiry cascade machinery."""
    consent["status"] = new_status
    if new_status == "REVOKED":
        consent["revoked_at"] = db.now_iso()
    touch(consent)
    for conn in list(db.connections.values()):
        if conn["consent_id"] == consent["id"] and conn["status"] in DISCONNECTABLE_CONN_STATES:
            conn["status"] = "DISCONNECTED"
            touch(conn)
            emit_webhook(conn["id"], consent["recipient_id"], webhook_type,
                         {"consent_id": consent["id"]})


def revoke_consent_cascade(consent, actor_role=None, write_audit=True):
    """ACTIVE -> REVOKED with cascade + audit."""
    _terminate_consent(consent, "REVOKED", "CONSENT_REVOKED")
    if write_audit:
        audit(actor_role or "system", "consent.revoke", "ConsentRecord", consent["id"],
              {"old_status": "ACTIVE", "new_status": "REVOKED"})


def sweep_expired_consents():
    """Eager sweep: expire all ACTIVE consents past expires_at. Returns ids."""
    expired_ids = []
    for consent in list(db.consents.values()):
        if expire_consent(consent):
            expired_ids.append(consent["id"])
    return expired_ids


def lazy_expire(consent):
    """Apply lazy expiry to a single consent."""
    expire_consent(consent)
    return consent


# ---------------------------------------------------------------- institution health

def recompute_institution_health(inst):
    """Recompute institution status from rolling-window breakage events.

    Window: occurred_at >= clock - 86400 AND occurred_at > last_recovered_at
    (or all events if never recovered).
    Returns the new status. Handles BROKEN transition side effects.
    """
    clock = db.get_clock()
    window_start = clock - timedelta(seconds=86400)
    last_rec = inst.get("_last_recovered_dt")
    n = 0
    for bev in db.breakage_events.values():
        if bev["institution_id"] != inst["id"]:
            continue
        occ = bev["_occurred_dt"]
        if occ < window_start:
            continue
        if last_rec is not None and occ <= last_rec:
            continue
        n += 1
    if n >= 5:
        new_status = "BROKEN"
    elif n >= 3:
        new_status = "DEGRADED"
    else:
        new_status = "ACTIVE"

    old_status = inst["status"]
    if new_status != old_status:
        inst["status"] = new_status
        # don't bump version for system-derived lazy status flips on read;
        # but DO bump on failure-triggered recomputes per §2.5 "updated_at
        # refreshes on every mutation". Lazy read recompute mutates the entity,
        # so touch it. To stay safe we only touch when status actually changes.
        inst["updated_at"] = db.now_iso()
        if new_status == "BROKEN":
            _institution_broken_side_effects(inst)
    return new_status


def _institution_broken_side_effects(inst):
    """On BROKEN: connections ACTIVE/MIGRATING -> REAUTH_REQUIRED + webhooks."""
    for conn in list(db.connections.values()):
        if conn["institution_id"] != inst["id"]:
            continue
        if conn["status"] in {"ACTIVE", "MIGRATING"}:
            conn["status"] = "REAUTH_REQUIRED"
            touch(conn)
            consent = db.consents.get(conn["consent_id"])
            recipient_id = consent["recipient_id"] if consent else None
            emit_webhook(conn["id"], recipient_id, "INSTITUTION_BROKEN",
                         {"institution_id": inst["id"]})


def active_agreement_for(institution_id):
    for ag in db.agreements.values():
        if ag["institution_id"] == institution_id and ag.get("active"):
            return ag
    return None


def connectivity_mode(inst):
    ms = inst["migration_state"]
    if ms == "NOT_STARTED":
        return "LEGACY_MODE"
    if ms == "IN_PROGRESS":
        return "HYBRID"
    return "API_ONLY"
