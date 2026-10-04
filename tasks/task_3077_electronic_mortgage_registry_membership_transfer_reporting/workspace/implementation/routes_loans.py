"""Loan registration, foreclosure lifecycle, and borrower inquiry."""
from flask import Blueprint, request

from db import store, iso
from domain import (
    ASSIGN_OUT_STATES, base_record, err, find_loan, luhn_check_digit,
    get_body, opt_bool, paginate, parse_iso, req_int, req_iso, req_str,
    sorted_items, touch,
)
from errors import err as _err  # noqa: F401  (kept import-stable)
from middleware import require_member_active, require_role
from response import success
from views import loan_view

bp = Blueprint("loans", __name__)


@bp.post("/loans")
def create_loan():
    body = get_body()
    user_id, _role = require_role("MemberRep")
    amount = req_int(body, "loan_amount_cents")
    if amount <= 0:
        raise err("ERR_INVALID_REQUEST", "loan_amount_cents must be a positive integer")
    state = req_str(body, "property_state")
    if not (len(state) == 2 and state.isalpha() and state.isupper()):
        raise err("ERR_INVALID_REQUEST",
                  "property_state must be a 2-letter uppercase US state code")
    closing_date = req_iso(body, "closing_date")

    member = store.members.get(user_id)
    if member is None:
        raise err("ERR_MEMBER_NOT_FOUND", "Acting member does not exist")
    require_member_active(member)
    if closing_date > store.clock:
        raise err("ERR_CLOSING_DATE_IN_FUTURE",
                  "closing_date is after the current logical clock")

    serial = store.member_serials.get(member["id"], 0) + 1
    store.member_serials[member["id"]] = serial
    payload = member["org_id"] + str(serial).zfill(10)
    min_value = payload + str(luhn_check_digit(payload))

    rec = base_record()
    rec.update({
        "min": min_value,
        "serial": serial,
        "registering_member_id": member["id"],
        "loan_amount_cents": amount,
        "property_state": state,
        "closing_date": iso(closing_date),
        "foreclosure_mode": ("ASSIGN_OUT_REQUIRED" if state in ASSIGN_OUT_STATES
                             else "IN_REGISTRY_ALLOWED"),
        "current_investor_id": member["id"],
        "current_servicer_id": member["id"],
        "status": "ACTIVE",
        "assigned_out_at": None,
    })
    store.loans[rec["id"]] = rec
    return success(loan_view(rec), status=201)


@bp.get("/loans")
def list_loans():
    require_role("RegistryAdmin", "MemberRep", "QAAuditor", "BorrowerInquirer")
    items = sorted_items(store.loans)
    for field in ("registering_member_id", "current_investor_id",
                  "current_servicer_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [l for l in items if l[field] == value]
    page, meta = paginate(items)
    return success([loan_view(l) for l in page], is_list=True, pagination=meta)


@bp.get("/loans/<loanId>")
def get_loan(loanId):
    require_role("RegistryAdmin", "MemberRep", "QAAuditor", "BorrowerInquirer")
    return success(loan_view(find_loan(loanId)))


def _acting_member(user_id):
    member = store.members.get(user_id)
    if member is None:
        raise err("ERR_MEMBER_NOT_FOUND", "Acting member does not exist")
    return member


def _require_rights_holder(loan, member_id):
    if loan["current_servicer_id"] != member_id and loan["current_investor_id"] != member_id:
        raise err("ERR_NOT_RIGHTS_HOLDER",
                  "Acting member is not the current servicer or investor of the loan")


@bp.post("/loans/<loanId>/foreclose")
def foreclose_loan(loanId):
    body = get_body()
    user_id, _role = require_role("MemberRep")
    signer_id = req_str(body, "signer_id")
    assignment_out = opt_bool(body, "assignment_out", False)
    loan = find_loan(loanId)
    member = _acting_member(user_id)

    require_member_active(member)
    if loan["status"] != "ACTIVE":
        raise err("ERR_LOAN_NOT_ACTIVE", "Loan must be ACTIVE to enter foreclosure")
    _require_rights_holder(loan, member["id"])

    signer = store.signers.get(signer_id)
    authorized = (
        signer is not None
        and signer["member_id"] == member["id"]
        and signer["status"] == "ACTIVE"
        and signer["role_scope"] in ("FORECLOSURE", "ALL")
        and parse_iso(signer["effective_from"], "effective_from") <= store.clock
        and (signer["effective_until"] is None
             or store.clock < parse_iso(signer["effective_until"], "effective_until"))
    )
    if not authorized:
        raise err("ERR_SIGNER_NOT_AUTHORIZED",
                  "signer_id does not name a currently authorized signer covering FORECLOSURE")

    if loan["foreclosure_mode"] == "ASSIGN_OUT_REQUIRED":
        if not assignment_out:
            raise err("ERR_ASSIGNMENT_OUT_REQUIRED",
                      "This loan's jurisdiction requires assignment out of the registry")
        loan["status"] = "INACTIVE_ASSIGNED_OUT"
        loan["assigned_out_at"] = iso(store.clock)
    else:
        if assignment_out:
            raise err("ERR_FORECLOSURE_MODE_FORBIDS_ASSIGN_OUT",
                      "assignment_out is not permitted for an IN_REGISTRY_ALLOWED loan")
        loan["status"] = "FORECLOSING"
    touch(loan)
    return success(loan_view(loan))


@bp.post("/loans/<loanId>/rescind-foreclosure")
def rescind_foreclosure(loanId):
    get_body()
    user_id, _role = require_role("MemberRep")
    loan = find_loan(loanId)
    member = _acting_member(user_id)
    require_member_active(member)
    if loan["status"] != "FORECLOSING":
        raise err("ERR_LOAN_NOT_FORECLOSING", "Loan is not in FORECLOSING status")
    _require_rights_holder(loan, member["id"])
    loan["status"] = "ACTIVE"
    touch(loan)
    return success(loan_view(loan))


@bp.post("/loans/<loanId>/satisfy")
def satisfy_loan(loanId):
    get_body()
    user_id, _role = require_role("MemberRep")
    loan = find_loan(loanId)
    member = _acting_member(user_id)
    require_member_active(member)
    if loan["status"] != "ACTIVE":
        raise err("ERR_LOAN_NOT_ACTIVE", "Loan must be ACTIVE to be satisfied")
    _require_rights_holder(loan, member["id"])
    loan["status"] = "INACTIVE_SATISFIED"
    touch(loan)
    return success(loan_view(loan))


@bp.get("/borrower-inquiries/<min_value>")
def borrower_inquiry(min_value):
    require_role("BorrowerInquirer")
    loan = next((l for l in store.loans.values() if l["min"] == min_value), None)
    if loan is None:
        raise err("ERR_LOAN_NOT_FOUND", f"No loan registered under MIN {min_value}")
    investor = store.members.get(loan["current_investor_id"])
    servicer = store.members.get(loan["current_servicer_id"])
    return success({
        "min": loan["min"],
        "loan_id": loan["id"],
        "loan_status": loan["status"],
        "current_investor_id": loan["current_investor_id"],
        "current_investor_org_id": investor["org_id"] if investor else None,
        "current_servicer_id": loan["current_servicer_id"],
        "current_servicer_org_id": servicer["org_id"] if servicer else None,
    })
