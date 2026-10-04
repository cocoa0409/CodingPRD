"""Loan routes: checkout, return, renew, listing."""
from flask import Blueprint, request
from db import stores
from middleware import require_roles
from response import success, paginate
from engine import (
    new_id, now, touch_common, require_body, req_field, opt_field,
    get_patron, get_title, get_loan, get_license, serialize, select_license,
    write_event, sync_patron_counters, fund_covering, recompute_fund,
)
from lending import perform_checkout, do_return
from timeutil import parse_iso
from datetime import timedelta
from errors import (
    err, ERR_REFERENCE_NOT_FOUND, ERR_LOAN_NOT_FOUND, ERR_PATRON_NOT_FOUND,
    ERR_TITLE_NOT_FOUND, ERR_FORBIDDEN, ERR_PATRON_NOT_ACTIVE, ERR_CARD_EXPIRED,
    ERR_LOAN_LIMIT_EXCEEDED, ERR_DUPLICATE_LOAN, ERR_CHECKOUT_BLOCKED_BY_HOLDS,
    ERR_SKIP_THE_LINE_DISABLED, ERR_NO_LICENSE_AVAILABLE, ERR_LOAN_NOT_ACTIVE,
    ERR_RENEWAL_LIMIT_REACHED, ERR_RENEWAL_BLOCKED_BY_HOLDS,
    ERR_RENEWAL_BEYOND_LICENSE_TERM,
)

bp = Blueprint("loans", __name__)


def _annotate_loan(loan, patron, title):
    loan["_library_id"] = patron["library_id"]
    loan["_title_id"] = title["id"]
    loan["_due_dt"] = parse_iso(loan["due_at"])
    loan["_checkout_dt"] = parse_iso(loan["checkout_at"])


def _check_patron_standing(patron, library):
    if patron["status"] != "ACTIVE":
        raise err(ERR_PATRON_NOT_ACTIVE, "patron card is not ACTIVE")
    if patron["_card_expires_dt"] <= now():
        raise err(ERR_CARD_EXPIRED, "patron card has expired")
    sync_patron_counters(patron["id"])
    if patron["active_loan_count"] >= library["max_concurrent_loans"]:
        raise err(ERR_LOAN_LIMIT_EXCEEDED, "max_concurrent_loans reached")


@bp.post("/lending/loans")
def checkout():
    body = require_body()
    patron_id = req_field(body, "patron_id", (str,))
    title_id = req_field(body, "title_id", (str,))
    skip = opt_field(body, "skip_the_line", (bool,), default=False)
    role, uid = require_roles({"Patron"})
    if uid != patron_id:
        raise err(ERR_FORBIDDEN, "patrons may only check out for themselves")
    patron = stores["patrons"].get(patron_id)
    if patron is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "patron_id does not resolve")
    title = stores["titles"].get(title_id)
    if title is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "title_id does not resolve")
    library = stores["libraries"][patron["library_id"]]
    _check_patron_standing(patron, library)
    for loan in stores["loans"].values():
        if loan["patron_id"] == patron_id and loan["_title_id"] == title_id \
                and loan["status"] == "ACTIVE":
            raise err(ERR_DUPLICATE_LOAN, "patron already has an ACTIVE loan on this title")
    queue_exists = any(h["title_id"] == title_id and h["status"] in ("PLACED", "READY", "SUSPENDED")
                       for h in stores["holds"].values())
    if skip:
        if not title["skip_the_line_enabled"]:
            raise err(ERR_SKIP_THE_LINE_DISABLED, "skip-the-line not enabled for this title")
    else:
        if queue_exists:
            raise err(ERR_CHECKOUT_BLOCKED_BY_HOLDS, "a hold queue exists on this title")
    lic = select_license(title, patron["library_id"])
    if lic is None:
        raise err(ERR_NO_LICENSE_AVAILABLE, "no eligible license available")
    loan = perform_checkout(patron, title, library, lic, hold=None, is_skip=skip)
    _annotate_loan(loan, patron, title)
    return success(serialize(loan), 201)


@bp.get("/lending/loans")
def list_loans():
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "SystemAnalyst"})
    items = list(stores["loans"].values())
    for key in ("license_id", "patron_id", "hold_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [l for l in items if str(l.get(key)) == v]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, meta = paginate([serialize(l) for l in items], request.args)
    return success(page, 200, meta)


@bp.get("/lending/loans/<lid>")
def read_loan(lid):
    role, uid = require_roles({"LibraryAdmin", "Patron", "SystemAnalyst"})
    loan = get_loan(lid, ERR_LOAN_NOT_FOUND)
    if role == "Patron" and uid != loan["patron_id"]:
        raise err(ERR_FORBIDDEN, "patrons may only read their own loans")
    return success(serialize(loan))


@bp.post("/lending/loans/<lid>/return")
def return_loan(lid):
    role, uid = require_roles({"Patron"})
    loan = get_loan(lid, ERR_LOAN_NOT_FOUND)
    if uid != loan["patron_id"]:
        raise err(ERR_FORBIDDEN, "patrons may only return their own loans")
    if loan["status"] != "ACTIVE":
        raise err(ERR_LOAN_NOT_ACTIVE, "loan is not ACTIVE")
    do_return(loan)
    return success(serialize(loan))


@bp.post("/lending/loans/<lid>/renew")
def renew_loan(lid):
    role, uid = require_roles({"Patron"})
    loan = get_loan(lid, ERR_LOAN_NOT_FOUND)
    if uid != loan["patron_id"]:
        raise err(ERR_FORBIDDEN, "patrons may only renew their own loans")
    if loan["status"] != "ACTIVE":
        raise err(ERR_LOAN_NOT_ACTIVE, "loan is not ACTIVE")
    patron = stores["patrons"][loan["patron_id"]]
    library = stores["libraries"][patron["library_id"]]
    if patron["status"] != "ACTIVE":
        raise err(ERR_PATRON_NOT_ACTIVE, "patron card is not ACTIVE")
    if loan["is_skip_the_line"]:
        raise err(ERR_RENEWAL_LIMIT_REACHED, "skip-the-line loans can never renew")
    if loan["renewals_used"] >= library["max_renewals"]:
        raise err(ERR_RENEWAL_LIMIT_REACHED, "max renewals reached")
    title_id = loan["_title_id"]
    if any(h["title_id"] == title_id and h["status"] in ("PLACED", "READY", "SUSPENDED")
           for h in stores["holds"].values()):
        raise err(ERR_RENEWAL_BLOCKED_BY_HOLDS, "queued demand blocks renewal")
    if now() >= loan["_due_dt"]:
        raise err(ERR_LOAN_NOT_ACTIVE, "loan is past due")
    lic = stores["licenses"][loan["license_id"]]
    new_due = loan["_due_dt"] + timedelta(days=library["renewal_period_days"])
    if lic["model"] in ("METERED_TIME", "SIMULTANEOUS_USE"):
        exp = lic.get("expires_at_dt")
        if exp is not None and new_due > exp:
            raise err(ERR_RENEWAL_BEYOND_LICENSE_TERM, "renewal would exceed license term")
    from timeutil import fmt_ts
    loan["due_at"] = fmt_ts(new_due)
    loan["_due_dt"] = new_due
    loan["renewals_used"] += 1
    touch_common(loan)
    write_event(patron["library_id"], title_id, patron["id"], loan["id"],
                loan.get("hold_id"), lic["id"], "RENEW")
    return success(serialize(loan))
