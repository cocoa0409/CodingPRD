"""Loans: checkout, return, renew, reads."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ERR_ACCESS_CREDENTIAL_REQUIRED, ERR_INVALID_STATE, ERR_ITEM_NOT_LENDABLE,
    ERR_LOAN_CAP_REACHED, ERR_LOAN_NOT_RENEWABLE, ERR_PATRON_SUSPENDED,
    ERR_RENEWAL_WINDOW_EXCEEDED, ERR_UNAUTHORIZED, ERR_VALIDATION,
    ERR_WAITLIST_PRIORITY, ERR_WORK_ALREADY_BORROWED, ERR_WORK_UNAVAILABLE,
    not_found, raise_err, validation,
)
from middleware import require_roles
from models import (
    item_lendable, patron_has_verified_credential, patron_max_loans,
    serialize_loan, stamp_new, touch, work_availability,
)
from response import iso_z, paginate, parse_pagination, success_list, success_object
from services import end_loan

bp = Blueprint("loans", __name__)


def _live_waitlist_exists(work_id):
    return any(
        e["work_id"] == work_id and e["status"] in ("OPEN", "OFFERED")
        for e in db.waitlist_entries.values()
    )


@bp.post("/archive/loans")
def create_loan():
    user_id, _ = require_roles("Patron")
    body = request.get_json(silent=True) or {}
    item_id = body.get("item_id")
    patron_id = body.get("patron_id")
    loan_kind = body.get("loan_kind")
    # Priority 2: entity-backed ownership.
    if patron_id is not None and patron_id != user_id:
        raise_err(ERR_UNAUTHORIZED, "patron_id must equal X-User-ID")
    # Priority 3: existence, left-to-right (item_id, then patron_id).
    if item_id is not None and item_id not in db.items:
        not_found("Scan item not found")
    if patron_id is not None and patron_id not in db.patrons:
        not_found("Patron not found")
    # Priority 6: schema.
    if not isinstance(item_id, str) or not item_id:
        validation("item_id is required")
    if not isinstance(patron_id, str) or not patron_id:
        validation("patron_id is required")
    if loan_kind not in ("STANDARD", "SHORT_READ"):
        raise_err(ERR_VALIDATION, "loan_kind must be STANDARD or SHORT_READ")
    item = db.items[item_id]
    patron = db.patrons[patron_id]
    work = db.works.get(item["work_id"])
    # Priority 7: patron standing.
    if patron["status"] != "ACTIVE":
        raise_err(ERR_PATRON_SUSPENDED, "Patron is not ACTIVE")
    # Priority 8: work availability.
    if work is None or work_availability(work) != "AVAILABLE":
        raise_err(ERR_WORK_UNAVAILABLE, "Work is not AVAILABLE")
    # Priority 9: item lendability.
    if not item_lendable(item):
        raise_err(ERR_ITEM_NOT_LENDABLE, "Item is not lendable")
    # Priority 10: waitlist priority.
    if _live_waitlist_exists(item["work_id"]):
        raise_err(ERR_WAITLIST_PRIORITY, "A live waitlist exists for this work")
    # Priority 11: duplicate possession.
    for loan in db.loans.values():
        if loan["patron_id"] != patron_id or loan["status"] != "ACTIVE":
            continue
        other_item = db.items.get(loan["item_id"])
        if other_item and other_item["work_id"] == item["work_id"]:
            raise_err(ERR_WORK_ALREADY_BORROWED, "Patron already holds this work")
    # Priority 12: loan cap.
    if patron["active_loan_count"] >= patron_max_loans(patron_id):
        raise_err(ERR_LOAN_CAP_REACHED, "Patron loan cap reached")
    # Priority 13: SHORT_READ credential gate.
    if loan_kind == "SHORT_READ" and not patron_has_verified_credential(patron_id):
        raise_err(ERR_ACCESS_CREDENTIAL_REQUIRED, "SHORT_READ requires a VERIFIED credential")
    # Create the loan.
    loan = stamp_new()
    now = db.now()
    due = now + (timedelta(days=14) if loan_kind == "STANDARD" else timedelta(hours=1))
    loan.update({
        "item_id": item_id,
        "patron_id": patron_id,
        "loan_kind": loan_kind,
        "status": "ACTIVE",
        "checked_out_at": iso_z(now),
        "due_at": iso_z(due),
        "renewed": False,
    })
    db.loans[loan["id"]] = loan
    item["status"] = "ON_LOAN"
    touch(item)
    patron["active_loan_count"] += 1
    touch(patron)
    return success_object(serialize_loan(loan), status=201)


@bp.get("/archive/patrons/<pid>/loans")
def list_patron_loans(pid):
    user_id, role = require_roles("Admin", "Patron")
    if pid not in db.patrons:
        not_found("Patron not found")
    if role == "Patron" and user_id != pid:
        raise_err(ERR_UNAUTHORIZED, "Patrons may list only their own loans")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = [l for l in db.loans.values() if l["patron_id"] == pid]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    rows.sort(key=lambda l: l["created_at"])
    page, total = paginate([serialize_loan(l) for l in rows], limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/archive/items/<iid>/loans")
def list_item_loans(iid):
    require_roles("Admin")
    if iid not in db.items:
        not_found("Scan item not found")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = [l for l in db.loans.values() if l["item_id"] == iid]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    rows.sort(key=lambda l: l["created_at"])
    page, total = paginate([serialize_loan(l) for l in rows], limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/archive/loans/<lid>")
def get_loan(lid):
    user_id, role = require_roles("Admin", "Patron")
    loan = db.loans.get(lid)
    if loan is None:
        not_found("Loan not found")
    if role == "Patron" and loan["patron_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED, "Patrons may read only their own loans")
    return success_object(serialize_loan(loan))


@bp.post("/archive/loans/<lid>/return")
def return_loan(lid):
    user_id, _ = require_roles("Patron")
    loan = db.loans.get(lid)
    if loan is None:
        not_found("Loan not found")
    if loan["patron_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED, "Only the borrower may return this loan")
    if loan["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Loan is not ACTIVE")
    end_loan(loan, "RETURNED")
    return success_object(serialize_loan(loan))


@bp.post("/archive/loans/<lid>/renew")
def renew_loan(lid):
    user_id, _ = require_roles("Patron")
    loan = db.loans.get(lid)
    if loan is None:
        not_found("Loan not found")
    if loan["patron_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED, "Only the borrower may renew this loan")
    if loan["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Loan is not ACTIVE")
    item = db.items.get(loan["item_id"])
    work_id = item["work_id"] if item else None
    now = db.now()
    from routes.system import _ts
    # Priority 17: renewal eligibility.
    if (
        loan["renewed"]
        or loan["loan_kind"] != "STANDARD"
        or not (now < _ts(loan["due_at"]))
        or (work_id is not None and _live_waitlist_exists(work_id))
    ):
        raise_err(ERR_LOAN_NOT_RENEWABLE, "Loan is not renewable")
    # Priority 18: absolute possession cap.
    if now + timedelta(days=14) > _ts(loan["checked_out_at"]) + timedelta(days=42):
        raise_err(ERR_RENEWAL_WINDOW_EXCEEDED, "Renewal exceeds the 42-day possession cap")
    loan["renewed"] = True
    loan["due_at"] = iso_z(now + timedelta(days=14))
    touch(loan)
    return success_object(serialize_loan(loan))
