"""Consent tickets and remote diagnostic sessions (PRD sections 2.7 and 3.5)."""

from datetime import timedelta

from flask import Blueprint, request

from auth import (
    as_bool,
    as_enum,
    as_str,
    body_json,
    caller,
    can_see_scope,
    get_or_404,
    list_resources,
    need,
    require_role,
    access_denied,
)
from constants import CONSENT_TTL_HOURS
from db import STORES, now
from domain import new_record, serialize, touch
from envelope import created, ok, ok_list
from errors import (
    ERR_CONSENT_ALREADY_CONSUMED,
    ERR_CONSENT_EXPIRED,
    ERR_DEALER_SUSPENDED,
    ERR_MACHINE_POSTURE_BLOCKED,
    ERR_MACHINE_SESSION_ACTIVE,
    ERR_NOT_FOUND,
    ERR_ORG_SUSPENDED,
    ERR_RTR_NOT_ENABLED,
    ERR_TICKET_MACHINE_MISMATCH,
    ERR_TICKET_TYPE_MISMATCH,
    ApiError,
    invalid_state,
)

bp = Blueprint("consent", __name__)

TICKET_TYPES = {"REMOTE_DIAGNOSTIC", "SOFTWARE_UPDATE"}
TICKET_READ_ROLES = {"GrowerManager", "PlatformAdmin", "DealerTechnician", "IndependentTechnician"}
SESSION_READ_ROLES = {
    "GrowerManager",
    "PlatformAdmin",
    "DealerTechnician",
    "IndependentTechnician",
    "Agronomist",
    "CoopAnalyst",
}


# ---------------------------------------------------------------------------
# Consent tickets
# ---------------------------------------------------------------------------

@bp.post("/consent-tickets")
def create_ticket():
    uid, role = caller()
    require_role(role, {"DealerTechnician", "IndependentTechnician", "PlatformAdmin"})
    b = body_json()
    organization_id = as_str(need(b, "organization_id"), "organization_id")
    machine_id = as_str(need(b, "machine_id"), "machine_id")
    ticket_type = as_enum(need(b, "ticket_type"), "ticket_type", TICKET_TYPES)
    requester_ref_id = as_str(need(b, "requester_ref_id"), "requester_ref_id")
    org = get_or_404("organizations", organization_id, "organization")
    get_or_404("machines", machine_id, "machine")
    # Compliance gate: right-to-repair must be enabled for independents
    if role == "IndependentTechnician" and not org["right_to_repair_enabled"]:
        raise ApiError(ERR_RTR_NOT_ENABLED, 403, "organization has not enabled right-to-repair")
    rec = new_record(
        {
            "organization_id": organization_id,
            "machine_id": machine_id,
            "ticket_type": ticket_type,
            "requester_ref_id": requester_ref_id,
            "status": "REQUESTED",
            "expires_at": now() + timedelta(hours=CONSENT_TTL_HOURS),
            "granted_at": None,
            "bound_session_id": None,
            "bound_delivery_id": None,
        }
    )
    STORES["consent_tickets"][rec["id"]] = rec
    return created(serialize(rec))


def _ticket_visible(t, role, uid):
    if role == "PlatformAdmin":
        return True
    if role == "GrowerManager":
        return uid == t["organization_id"]
    # DealerTechnician / IndependentTechnician: the recorded requester
    return t["requester_ref_id"] == uid


@bp.get("/consent-tickets/<tid>")
def get_ticket(tid):
    uid, role = caller()
    require_role(role, TICKET_READ_ROLES)
    t = get_or_404("consent_tickets", tid, "consent ticket")
    if not _ticket_visible(t, role, uid):
        raise access_denied("caller is neither the org owner nor the requester")
    return ok(serialize(t))


@bp.get("/consent-tickets")
def list_tickets():
    uid, role = caller()
    require_role(role, TICKET_READ_ROLES)
    org_filter = request.args.get("organization_id")
    filters = []
    for f in ("organization_id", "machine_id", "ticket_type", "status"):
        v = request.args.get(f)
        if v is not None:
            filters.append((f, v))
    if role == "GrowerManager" and org_filter is not None and org_filter != uid:
        raise access_denied("grower may list only its own organization")
    visible = lambda r: _ticket_visible(r, role, uid)
    page, total, limit, offset = list_resources("consent_tickets", filters, visible)
    return ok_list([serialize(r) for r in page], total, limit, offset)


@bp.post("/consent-tickets/<tid>/grant")
def grant_ticket(tid):
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    t = get_or_404("consent_tickets", tid, "consent ticket")
    if uid != t["organization_id"]:
        raise access_denied("ticket belongs to another organization")
    if t["status"] != "REQUESTED":
        raise invalid_state("ticket is not REQUESTED")
    org = STORES["organizations"].get(t["organization_id"])
    if org is None or org["status"] != "ACTIVE":
        raise ApiError(ERR_ORG_SUSPENDED, 409, "owning organization is SUSPENDED")
    t["status"] = "GRANTED"
    t["granted_at"] = now()
    touch(t)
    d = STORES["update_deliveries"].get(t["bound_delivery_id"]) if t["bound_delivery_id"] else None
    if d is not None and d["status"] == "AWAITING_CONSENT":
        d["status"] = "CONSENT_GRANTED"
        touch(d)
    return ok(serialize(t))


@bp.post("/consent-tickets/<tid>/deny")
def deny_ticket(tid):
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    t = get_or_404("consent_tickets", tid, "consent ticket")
    if uid != t["organization_id"]:
        raise access_denied("ticket belongs to another organization")
    if t["status"] != "REQUESTED":
        raise invalid_state("ticket is not REQUESTED")
    t["status"] = "DENIED"
    touch(t)
    d = STORES["update_deliveries"].get(t["bound_delivery_id"]) if t["bound_delivery_id"] else None
    if d is not None and d["status"] == "AWAITING_CONSENT":
        d["status"] = "DECLINED"
        touch(d)
    return ok(serialize(t))


# ---------------------------------------------------------------------------
# Diagnostic sessions
# ---------------------------------------------------------------------------

@bp.post("/diagnostic-sessions")
def open_session():
    uid, role = caller()
    require_role(role, {"DealerTechnician", "IndependentTechnician"})
    b = body_json()
    machine_id = as_str(need(b, "machine_id"), "machine_id")
    consent_ticket_id = as_str(need(b, "consent_ticket_id"), "consent_ticket_id")
    # Existence: body foreign keys in declared input order
    machine = get_or_404("machines", machine_id, "machine")
    ticket = get_or_404("consent_tickets", consent_ticket_id, "consent ticket")
    # State gates (priority 6). A CONSUMED ticket's rejection wins over the
    # referential mismatches below.
    if ticket["status"] == "CONSUMED":
        raise ApiError(ERR_CONSENT_ALREADY_CONSUMED, 409, "consent ticket already consumed")
    if ticket["status"] == "EXPIRED":
        raise ApiError(ERR_CONSENT_EXPIRED, 409, "consent ticket is expired")
    if ticket["status"] != "GRANTED":
        raise invalid_state("consent ticket is not GRANTED")
    if machine["connectivity_posture"] not in ("CONNECTED", "THROTTLED"):
        raise ApiError(
            ERR_MACHINE_POSTURE_BLOCKED, 409, "machine posture is not CONNECTED or THROTTLED"
        )
    org = STORES["organizations"].get(machine["organization_id"])
    if org is None or org["status"] != "ACTIVE":
        raise ApiError(ERR_ORG_SUSPENDED, 409, "owning organization is SUSPENDED")
    if role == "DealerTechnician":
        dealer = STORES["dealers"].get(uid)
        if dealer is None:
            raise ApiError(ERR_NOT_FOUND, 404, "caller dealer not found")
        if dealer["status"] != "ACTIVE":
            raise ApiError(ERR_DEALER_SUSPENDED, 409, "dealer is SUSPENDED")
    # Compliance gate (priority 7)
    if role == "IndependentTechnician" and not org["right_to_repair_enabled"]:
        raise ApiError(ERR_RTR_NOT_ENABLED, 403, "organization has not enabled right-to-repair")
    # Capacity (priority 8): at most one OPEN session per machine
    for s in STORES["diagnostic_sessions"].values():
        if s["machine_id"] == machine_id and s["status"] == "OPEN":
            raise ApiError(ERR_MACHINE_SESSION_ACTIVE, 409, "machine already has an OPEN session")
    # Referential agreement (priority 9)
    if ticket["ticket_type"] != "REMOTE_DIAGNOSTIC":
        raise ApiError(ERR_TICKET_TYPE_MISMATCH, 409, "ticket is not REMOTE_DIAGNOSTIC")
    if ticket["machine_id"] != machine_id:
        raise ApiError(ERR_TICKET_MACHINE_MISMATCH, 409, "ticket covers a different machine")
    kind = "DEALER" if role == "DealerTechnician" else "INDEPENDENT"
    rec = new_record(
        {
            "machine_id": machine_id,
            "organization_id": machine["organization_id"],
            "dealer_id": uid if kind == "DEALER" else None,
            "consent_ticket_id": consent_ticket_id,
            "technician_kind": kind,
            "diagnostic_detail_level": "EXTENDED" if kind == "DEALER" else "BASIC",
            "status": "OPEN",
            "opened_at": now(),
            "closed_at": None,
            "closed_reason": None,
            "fault_found": None,
        }
    )
    STORES["diagnostic_sessions"][rec["id"]] = rec
    # Consent is consumed exactly once
    ticket["status"] = "CONSUMED"
    ticket["bound_session_id"] = rec["id"]
    touch(ticket)
    return created(serialize(rec))


def _session_visible(s, role, uid):
    if role == "PlatformAdmin":
        return True
    if role == "GrowerManager":
        return uid == s["organization_id"]
    if role == "DealerTechnician" and s["dealer_id"] == uid:
        return True
    if role == "IndependentTechnician" and s["technician_kind"] == "INDEPENDENT":
        t = STORES["consent_tickets"].get(s["consent_ticket_id"])
        if t is not None and t["requester_ref_id"] == uid:
            return True
    return can_see_scope(s["organization_id"], role, uid, "DIAGNOSTICS") and role != "GrowerManager"


@bp.get("/diagnostic-sessions/<sid>")
def get_session(sid):
    uid, role = caller()
    require_role(role, SESSION_READ_ROLES)
    s = get_or_404("diagnostic_sessions", sid, "diagnostic session")
    if not _session_visible(s, role, uid):
        raise access_denied("caller may not read this session")
    return ok(serialize(s))


@bp.get("/diagnostic-sessions")
def list_sessions():
    uid, role = caller()
    require_role(role, SESSION_READ_ROLES)
    org_filter = request.args.get("organization_id")
    filters = []
    for f in ("machine_id", "organization_id", "dealer_id", "consent_ticket_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters.append((f, v))
    if role == "GrowerManager" and org_filter is not None and org_filter != uid:
        raise access_denied("grower may list only its own organization")
    visible = lambda r: _session_visible(r, role, uid)
    page, total, limit, offset = list_resources("diagnostic_sessions", filters, visible)
    return ok_list([serialize(r) for r in page], total, limit, offset)


@bp.post("/diagnostic-sessions/<sid>/close")
def close_session(sid):
    uid, role = caller()
    require_role(role, {"DealerTechnician", "IndependentTechnician"})
    b = body_json()
    fault_found = as_bool(need(b, "fault_found"), "fault_found")
    s = get_or_404("diagnostic_sessions", sid, "diagnostic session")
    # Only the opener may close: dealer sessions key on dealer_id, independent
    # sessions key on the consuming ticket's requester_ref_id
    if s["technician_kind"] == "DEALER":
        if uid != s["dealer_id"]:
            raise access_denied("only the session opener may close it")
    else:
        t = STORES["consent_tickets"].get(s["consent_ticket_id"])
        if t is None or t["requester_ref_id"] != uid:
            raise access_denied("only the session opener may close it")
    if s["status"] != "OPEN":
        raise invalid_state("session is not OPEN")
    s["status"] = "CLOSED"
    s["closed_at"] = now()
    s["closed_reason"] = "COMPLETED"
    s["fault_found"] = fault_found
    touch(s)
    return ok(serialize(s))
