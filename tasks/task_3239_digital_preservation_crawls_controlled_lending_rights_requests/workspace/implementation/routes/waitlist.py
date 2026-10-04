"""Waitlist entries: join, list, read, claim (with OCC)."""
from datetime import datetime, timedelta

from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE, ERR_INVALID_STATE, ERR_ITEM_NOT_LENDABLE,
    ERR_LOAN_CAP_REACHED, ERR_OFFER_EXPIRED, ERR_PATRON_SUSPENDED,
    ERR_STALE_VERSION, ERR_UNAUTHORIZED, ERR_WORK_UNAVAILABLE, not_found,
    raise_err, validation,
)
from middleware import require_roles
from models import (
    item_lendable, patron_max_loans, serialize_loan, serialize_waitlist_entry,
    stamp_new, touch, work_availability,
)
from response import iso_z, paginate, parse_pagination, success_list, success_object
from services import run_promotion

bp = Blueprint("waitlist", __name__)


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@bp.post("/archive/waitlist-entries")
def join_waitlist():
    user_id, _ = require_roles("Patron")
    body = request.get_json(silent=True) or {}
    work_id = body.get("work_id")
    patron_id = body.get("patron_id")
    if patron_id is not None and patron_id != user_id:
        raise_err(ERR_UNAUTHORIZED, "patron_id must equal X-User-ID")
    if work_id is not None and work_id not in db.works:
        not_found("Work not found")
    if patron_id is not None and patron_id not in db.patrons:
        not_found("Patron not found")
    if not isinstance(work_id, str) or not work_id:
        validation("work_id is required")
    if not isinstance(patron_id, str) or not patron_id:
        validation("patron_id is required")
    patron = db.patrons[patron_id]
    work = db.works[work_id]
    # Priority 7: patron standing.
    if patron["status"] != "ACTIVE":
        raise_err(ERR_PATRON_SUSPENDED, "Patron is not ACTIVE")
    # Priority 8: work availability.
    if work_availability(work) != "AVAILABLE":
        raise_err(ERR_WORK_UNAVAILABLE, "Work is not AVAILABLE")
    # Priority 21: live-entry uniqueness per (work_id, patron_id).
    if any(
        e["work_id"] == work_id and e["patron_id"] == patron_id
        and e["status"] in ("OPEN", "OFFERED")
        for e in db.waitlist_entries.values()
    ):
        raise_err(ERR_DUPLICATE, "A live waitlist entry already exists for this work and patron")
    e = stamp_new()
    e.update({
        "work_id": work_id,
        "patron_id": patron_id,
        "status": "OPEN",
        "offered_at": None,
        "offer_expires_at": None,
    })
    db.waitlist_entries[e["id"]] = e
    run_promotion(work_id)
    return success_object(serialize_waitlist_entry(db.waitlist_entries[e["id"]]), status=201)


@bp.get("/archive/works/<wid>/waitlist-entries")
def list_work_waitlist(wid):
    user_id, role = require_roles("Admin", "Patron")
    if wid not in db.works:
        not_found("Work not found")
    limit, offset = parse_pagination(request.args)
    patron_id = request.args.get("patron_id")
    status = request.args.get("status")
    if role == "Patron":
        # Patron role is implicitly restricted to its own entries.
        if patron_id is not None and patron_id != user_id:
            raise_err(ERR_UNAUTHORIZED, "patron_id filter must equal X-User-ID")
        patron_id = user_id
    rows = [e for e in db.waitlist_entries.values() if e["work_id"] == wid]
    if patron_id is not None:
        rows = [e for e in rows if e["patron_id"] == patron_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    rows.sort(key=lambda e: e["created_at"])
    page, total = paginate([serialize_waitlist_entry(e) for e in rows], limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/archive/patrons/<pid>/waitlist-entries")
def list_patron_waitlist(pid):
    user_id, role = require_roles("Admin", "Patron")
    if pid not in db.patrons:
        not_found("Patron not found")
    if role == "Patron" and user_id != pid:
        raise_err(ERR_UNAUTHORIZED, "Patrons may list only their own entries")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = [e for e in db.waitlist_entries.values() if e["patron_id"] == pid]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    rows.sort(key=lambda e: e["created_at"])
    page, total = paginate([serialize_waitlist_entry(e) for e in rows], limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/archive/waitlist-entries/<eid>")
def get_waitlist_entry(eid):
    user_id, role = require_roles("Admin", "Patron")
    e = db.waitlist_entries.get(eid)
    if e is None:
        not_found("Waitlist entry not found")
    if role == "Patron" and e["patron_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED, "Patrons may read only their own entries")
    return success_object(serialize_waitlist_entry(e))


@bp.post("/archive/waitlist-entries/<eid>/claim")
def claim_waitlist_entry(eid):
    user_id, _ = require_roles("Patron")
    e = db.waitlist_entries.get(eid)
    if e is None:
        not_found("Waitlist entry not found")
    if e["patron_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED, "Only the entry's patron may claim it")
    if e["status"] != "OFFERED":
        raise_err(ERR_INVALID_STATE, "Entry is not OFFERED")
    body = request.get_json(silent=True) or {}
    expected_version = body.get("expected_entry_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        validation("expected_entry_version is required and must be an integer")
    patron = db.patrons.get(e["patron_id"])
    # Priority 7: patron standing.
    if patron is None or patron["status"] != "ACTIVE":
        raise_err(ERR_PATRON_SUSPENDED, "Patron is not ACTIVE")
    # Priority 9: a lendable item of the work must exist at claim time.
    candidates = sorted(
        (it for it in db.items.values()
         if it["work_id"] == e["work_id"] and item_lendable(it)),
        key=lambda it: it["created_at"],
    )
    if not candidates:
        raise_err(ERR_ITEM_NOT_LENDABLE, "No lendable item of the work remains")
    # Priority 12: loan cap.
    if patron["active_loan_count"] >= patron_max_loans(patron["id"]):
        raise_err(ERR_LOAN_CAP_REACHED, "Patron loan cap reached")
    # Priority 16: offer window.
    now = db.now()
    if not (now < _ts(e["offer_expires_at"])):
        raise_err(ERR_OFFER_EXPIRED, "The offer window has lapsed")
    # Priority 23: OCC.
    if expected_version != e["version"]:
        raise_err(ERR_STALE_VERSION, "Stale expected_entry_version")
    # Execute claim: pick earliest-created lendable item, create STANDARD loan.
    item = candidates[0]
    loan = stamp_new()
    loan.update({
        "item_id": item["id"],
        "patron_id": patron["id"],
        "loan_kind": "STANDARD",
        "status": "ACTIVE",
        "checked_out_at": iso_z(now),
        "due_at": iso_z(now + timedelta(days=14)),
        "renewed": False,
    })
    db.loans[loan["id"]] = loan
    item["status"] = "ON_LOAN"
    touch(item)
    patron["active_loan_count"] += 1
    touch(patron)
    e["status"] = "CLAIMED"
    touch(e)  # increments entry version by 1
    run_promotion(e["work_id"])
    return success_object(serialize_loan(loan), status=201)
