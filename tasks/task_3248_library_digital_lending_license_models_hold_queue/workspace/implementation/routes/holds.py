"""Hold routes: placement, suspend/resume/cancel/claim, listing."""
from flask import Blueprint, request
from db import stores
from middleware import require_roles
from response import success, paginate
from engine import (
    new_id, now, touch_common, require_body, req_field,
    get_patron, get_title, get_hold, serialize, holds_queue,
    write_event, sync_patron_counters, compute_waits,
    get_library,
)
from lending import perform_checkout, run_promotion, _release_ready_reservation
from timeutil import parse_iso
from errors import (
    err, ERR_REFERENCE_NOT_FOUND, ERR_HOLD_NOT_FOUND, ERR_FORBIDDEN,
    ERR_PATRON_NOT_ACTIVE, ERR_CARD_EXPIRED, ERR_HOLD_LIMIT_EXCEEDED,
    ERR_DUPLICATE_HOLD, ERR_HOLD_NOT_ACTIONABLE, ERR_LOAN_LIMIT_EXCEEDED,
)

bp = Blueprint("holds", __name__)


@bp.post("/lending/holds")
def place_hold():
    body = require_body()
    patron_id = req_field(body, "patron_id", (str,))
    title_id = req_field(body, "title_id", (str,))
    role, uid = require_roles({"Patron"})
    if uid != patron_id:
        raise err(ERR_FORBIDDEN, "patrons may only place holds for themselves")
    patron = stores["patrons"].get(patron_id)
    if patron is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "patron_id does not resolve")
    title = stores["titles"].get(title_id)
    if title is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "title_id does not resolve")
    library = stores["libraries"][patron["library_id"]]
    if patron["status"] != "ACTIVE":
        raise err(ERR_PATRON_NOT_ACTIVE, "patron card is not ACTIVE")
    if patron["_card_expires_dt"] <= now():
        raise err(ERR_CARD_EXPIRED, "patron card has expired")
    sync_patron_counters(patron_id)
    if patron["active_hold_count"] >= library["max_concurrent_holds"]:
        raise err(ERR_HOLD_LIMIT_EXCEEDED, "max_concurrent_holds reached")
    for h in stores["holds"].values():
        if h["patron_id"] == patron_id and h["title_id"] == title_id \
                and h["status"] in ("PLACED", "READY", "SUSPENDED"):
            raise err(ERR_DUPLICATE_HOLD, "patron already has an active hold on this title")
    hold = {
        "id": new_id(),
        "title_id": title_id,
        "patron_id": patron_id,
        "library_id": patron["library_id"],
        "status": "PLACED",
        "placed_at": None,
        "ready_since": None,
        "ready_until": None,
        "suspension_count": 0,
        "optimistic_wait_days": 0,
        "pessimistic_wait_days": 0,
    }
    from timeutil import fmt_ts
    hold["placed_at"] = fmt_ts(now())
    touch_common(hold, created=True)
    hold["_seq"] = len(stores["holds"])
    hold["_placed_dt"] = now()
    hold["_ready_until_dt"] = None
    stores["holds"][hold["id"]] = hold
    opt, pess = compute_waits(hold, library, title)
    hold["optimistic_wait_days"] = opt
    hold["pessimistic_wait_days"] = pess
    write_event(patron["library_id"], title_id, patron_id, None, hold["id"], None, "HOLD_PLACED")
    sync_patron_counters(patron_id)
    # NOTE: placement is not a promotion trigger — promotion fires only when a
    # copy becomes available (return, loan expiry, ready-hold lapse/cancel,
    # license fulfillment, auto-purchase), per the PRD's pinned trigger list.
    return success(serialize(hold), 201)


@bp.get("/lending/holds")
def list_holds():
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "Patron", "SystemAnalyst"})
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    items = list(stores["holds"].values())
    if role == "Patron":
        items = [h for h in items if h["patron_id"] == uid]
    for key in ("title_id", "patron_id", "library_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [h for h in items if str(h.get(key)) == v]
    items.sort(key=lambda h: (h["created_at"], h["_seq"]))
    page, meta = paginate([serialize(h) for h in items], request.args)
    return success(page, 200, meta)


@bp.get("/lending/holds/<hid>")
def read_hold(hid):
    role, uid = require_roles({"LibraryAdmin", "Patron", "SystemAnalyst"})
    h = get_hold(hid, ERR_HOLD_NOT_FOUND)
    if role == "Patron" and uid != h["patron_id"]:
        raise err(ERR_FORBIDDEN, "patrons may only read their own holds")
    return success(serialize(h))


def _own_hold(hid, uid):
    h = get_hold(hid, ERR_HOLD_NOT_FOUND)
    if uid != h["patron_id"]:
        raise err(ERR_FORBIDDEN, "patrons may only manage their own holds")
    return h


@bp.post("/lending/holds/<hid>/suspend")
def suspend_hold(hid):
    role, uid = require_roles({"Patron"})
    h = _own_hold(hid, uid)
    if h["status"] != "PLACED":
        raise err(ERR_HOLD_NOT_ACTIONABLE, "hold is not PLACED")
    h["status"] = "SUSPENDED"
    h["suspension_count"] += 1
    touch_common(h)
    return success(serialize(h))


@bp.post("/lending/holds/<hid>/resume")
def resume_hold(hid):
    role, uid = require_roles({"Patron"})
    h = _own_hold(hid, uid)
    if h["status"] != "SUSPENDED":
        raise err(ERR_HOLD_NOT_ACTIONABLE, "hold is not SUSPENDED")
    h["status"] = "PLACED"
    touch_common(h)
    return success(serialize(h))


@bp.post("/lending/holds/<hid>/cancel")
def cancel_hold(hid):
    role, uid = require_roles({"Patron"})
    h = _own_hold(hid, uid)
    if h["status"] not in ("PLACED", "SUSPENDED", "READY"):
        raise err(ERR_HOLD_NOT_ACTIONABLE, "hold cannot be cancelled from its current state")
    was_ready = h["status"] == "READY"
    lic_id = None
    if was_ready:
        lic_id = _release_ready_reservation(h)
    h["status"] = "CANCELLED"
    touch_common(h)
    write_event(h["library_id"], h["title_id"], h["patron_id"], None, h["id"], lic_id,
                "HOLD_CANCELLED")
    sync_patron_counters(h["patron_id"])
    if was_ready:
        run_promotion(h["title_id"])
    return success(serialize(h))


@bp.post("/lending/holds/<hid>/claim")
def claim_hold(hid):
    role, uid = require_roles({"Patron"})
    h = _own_hold(hid, uid)
    if h["status"] != "READY":
        raise err(ERR_HOLD_NOT_ACTIONABLE, "hold is not READY")
    patron = stores["patrons"][h["patron_id"]]
    library = stores["libraries"][h["library_id"]]
    if patron["status"] != "ACTIVE":
        raise err(ERR_PATRON_NOT_ACTIVE, "patron card is not ACTIVE")
    if patron["_card_expires_dt"] <= now():
        raise err(ERR_CARD_EXPIRED, "patron card has expired")
    sync_patron_counters(patron["id"])
    if patron["active_loan_count"] >= library["max_concurrent_loans"]:
        raise err(ERR_LOAN_LIMIT_EXCEEDED, "max_concurrent_loans reached")
    if h["_ready_until_dt"] is not None and now() >= h["_ready_until_dt"]:
        raise err(ERR_HOLD_NOT_ACTIONABLE, "hold pickup window has closed")
    lic_id = h.get("_reserved_license_id")
    lic = stores["licenses"].get(lic_id) if lic_id else None
    if lic is None or lic["status"] != "ACTIVE":
        raise err(ERR_HOLD_NOT_ACTIONABLE, "reserved license is unavailable")
    title = stores["titles"][h["title_id"]]
    h["status"] = "FULFILLED"
    touch_common(h)
    loan = perform_checkout(patron, title, library, lic, hold=h, is_skip=False)
    loan["_library_id"] = patron["library_id"]
    loan["_title_id"] = title["id"]
    loan["_due_dt"] = parse_iso(loan["due_at"])
    loan["_checkout_dt"] = parse_iso(loan["checkout_at"])
    write_event(h["library_id"], h["title_id"], h["patron_id"], loan["id"], h["id"],
                lic["id"], "HOLD_FULFILLED")
    sync_patron_counters(patron["id"])
    return success(serialize(loan), 201)
