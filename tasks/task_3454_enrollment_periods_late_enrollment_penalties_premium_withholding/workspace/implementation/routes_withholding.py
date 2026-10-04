"""WithholdingArrangement: establish (sweeps DIRECT_BILL), list, adjust."""
from __future__ import annotations

from authn import (ROLE_BENEFICIARY, ROLE_BENEFIT_ADMINISTRATOR, authenticate,
                   authorize, body_beneficiary_ownership, check_ownership)
from calcs import PARTS_BILLABLE
from clock import clock_month
from db import find, find_one, get, make_entity, public, sort_entities, touch
from domain import invoice_amount_cents, non_stopped_arrangement
from envelope import success_list, success_object
from errors import fail
from validate import body_json, pagination_args, paginate, req_int, req_str


def create_arrangement():
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_BENEFIT_ADMINISTRATOR])
    body = body_json()
    body_beneficiary_ownership(role, uid, body)
    bid = req_str(body, "beneficiary_id")
    benefit = req_int(body, "monthly_benefit_cents", minimum=0)
    if not get("beneficiaries", bid):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    if non_stopped_arrangement(bid):
        fail("ERR_DUPLICATE_WITHHOLDING",
             "A non-STOPPED withholding arrangement already exists")
    arr = make_entity("arrangements", {
        "beneficiary_id": bid,
        "monthly_benefit_cents": benefit,
        "status": "ACTIVE",
    })
    # Sweep: only DIRECT_BILL enrollments; PENDING_SETUP resolve at activation
    for ent in find("enrollments",
                    lambda e: e["beneficiary_id"] == bid
                    and e["collection_status"] == "DIRECT_BILL"):
        ent["collection_status"] = "WITHHOLDING"
        touch(ent)
    return success_object(public(arr), 201)


def list_arrangements(beneficiary_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_BENEFIT_ADMINISTRATOR])
    check_ownership(role, uid, beneficiary_id)
    if not get("beneficiaries", beneficiary_id):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    limit, offset = pagination_args()
    rows = sort_entities(find("arrangements",
                              lambda e: e["beneficiary_id"] == beneficiary_id))
    page, total = paginate(rows, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


def adjust_arrangement(arrangement_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFIT_ADMINISTRATOR])
    body = body_json()
    benefit = req_int(body, "monthly_benefit_cents", minimum=0)
    arr = get("arrangements", arrangement_id)
    if not arr:
        fail("ERR_ARRANGEMENT_NOT_FOUND",
             "No withholding arrangement with that id")
    if arr["status"] == "STOPPED":
        fail("ERR_INVALID_STATE", "A STOPPED arrangement cannot be adjusted")
    arr["monthly_benefit_cents"] = benefit
    if arr["status"] == "SUSPENDED":
        # Resume iff the new benefit covers the sum of current monthly
        # premiums of the beneficiary's ACTIVE billable enrollments.
        cm = clock_month()
        total = 0
        for ent in find("enrollments",
                        lambda e: e["beneficiary_id"] == arr["beneficiary_id"]
                        and e["enrollment_status"] == "ACTIVE"
                        and e["part"] in PARTS_BILLABLE):
            amt = invoice_amount_cents(arr["beneficiary_id"], ent["part"], cm)
            total += amt if amt is not None else 0
        if benefit >= total:
            arr["status"] = "ACTIVE"
    # NOTE: resume does NOT flip enrollments back (explicit switch required)
    touch(arr)
    return success_object(public(arr))


def register(app):
    app.add_url_rule("/medicare/withholding-arrangements",
                     "create_arrangement", create_arrangement,
                     methods=["POST"])
    app.add_url_rule(
        "/medicare/beneficiaries/<beneficiary_id>/withholding-arrangements",
        "list_arrangements", list_arrangements, methods=["GET"])
    app.add_url_rule("/medicare/withholding-arrangements/<arrangement_id>/adjust",
                     "adjust_arrangement", adjust_arrangement, methods=["POST"])
