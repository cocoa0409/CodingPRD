"""Service events: open warranty/descaling/replacement events and resolve them."""
from flask import Blueprint

from store import db, get_clock
from helpers import (
    ApiError, body, created, find, fmt_dt, init_common, list_ok, ok,
    require_roles, touch, v_enum, v_str,
)
from calc import descale_overdue, eval_brewer_lazy
from serializers import event_out

bp = Blueprint("service", __name__)

EVENT_KINDS = ("WARRANTY_CLAIM", "DESCALING", "REPLACEMENT")
OUTCOMES = ("APPROVED", "DENIED", "MISUSE_CONFIRMED")


@bp.post("/brewers/<rid>/service-events")
@require_roles("SupportAgent")
def create_event(rid):
    brewer = find("brewers", rid)
    eval_brewer_lazy(brewer, persist=True)
    b = body()
    kind = v_enum(b, "kind", EVENT_KINDS)
    note = v_str(b, "note", required=False)
    if kind == "WARRANTY_CLAIM" and brewer["warranty_status"] != "IN_WARRANTY":
        raise ApiError("ERR_WARRANTY_NOT_ACTIVE", 409,
                       "Warranty claims require an IN_WARRANTY brewer")
    if kind == "REPLACEMENT" and brewer["operational"] == "DECOMMISSIONED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cannot open a REPLACEMENT on a DECOMMISSIONED brewer")
    status = "OPEN"
    resolution = None
    resolved_at = None
    if kind == "WARRANTY_CLAIM" and descale_overdue(brewer):
        status = "DENIED"
        resolution = "AUTO_DENIED_DESCALE"
        resolved_at = fmt_dt(get_clock())
    event = init_common({
        "brewer_id": brewer["id"],
        "kind": kind,
        "note": note,
        "status": status,
        "resolution": resolution,
        "resolved_at": resolved_at,
    })
    db["events"][event["id"]] = event
    return created(event_out(event))


@bp.get("/brewers/<rid>/service-events")
@require_roles("SupportAgent", "PlatformAdmin")
def list_events(rid):
    brewer = find("brewers", rid)
    items = [e for e in db["events"].values() if e["brewer_id"] == brewer["id"]]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return list_ok(items, event_out)


@bp.post("/service-events/<rid>/resolve")
@require_roles("SupportAgent")
def resolve_event(rid):
    event = find("events", rid)
    b = body()
    outcome = v_enum(b, "outcome", OUTCOMES)
    if event["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN service event can be resolved")
    event["status"] = "DENIED" if outcome == "DENIED" else "RESOLVED"
    event["resolution"] = outcome
    event["resolved_at"] = fmt_dt(get_clock())
    touch(event)
    brewer = db["brewers"].get(event["brewer_id"])
    if brewer is not None:
        if event["kind"] == "DESCALING" and outcome == "APPROVED":
            brewer["last_descaled_brew_count"] = brewer["brew_count"]
            touch(brewer)
        elif event["kind"] == "WARRANTY_CLAIM" and outcome == "MISUSE_CONFIRMED":
            brewer["warranty_status"] = "VOID"
            touch(brewer)
        elif event["kind"] == "REPLACEMENT" and outcome == "APPROVED":
            brewer["operational"] = "DECOMMISSIONED"
            touch(brewer)
    return ok(event_out(event))
