"""TaxReturnRecord: IRS feed submission (finalizes PROVISIONALs) + list."""
from __future__ import annotations

from authn import (ROLE_APPEALS_OFFICER, ROLE_BENEFICIARY, ROLE_FIELD_OFFICER,
                   ROLE_IRS_DATA_AGENT, authenticate, authorize,
                   check_ownership)
from db import find, find_one, get, make_entity, public, sort_entities
from domain import finalize_provisional
from envelope import success_list, success_object
from errors import fail
from validate import (body_json, pagination_args, paginate, req_enum, req_int,
                      req_str)

FILING_STATUSES = ("SINGLE", "MARRIED_JOINT")


def create_tax_record():
    role, uid = authenticate()
    authorize(role, [ROLE_IRS_DATA_AGENT])
    body = body_json()
    bid = req_str(body, "beneficiary_id")
    tax_year = req_int(body, "tax_year")
    magi = req_int(body, "magi_cents", minimum=0)
    filing = req_enum(body, "filing_status", FILING_STATUSES)
    if not get("beneficiaries", bid):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    if find_one("tax_records",
                lambda t: t["beneficiary_id"] == bid
                and t["tax_year"] == tax_year):
        fail("ERR_DUPLICATE_TAX_YEAR",
             "A TaxReturnRecord for that tax year already exists")
    rec = make_entity("tax_records", {
        "beneficiary_id": bid,
        "tax_year": tax_year,
        "magi_cents": magi,
        "filing_status": filing,
    })
    # Finalize waiting PROVISIONAL determinations (coverage_year - 2 == year)
    for det in find("determinations",
                    lambda d: d["beneficiary_id"] == bid
                    and d["status"] == "PROVISIONAL"
                    and d["coverage_year"] - 2 == tax_year):
        finalize_provisional(det, rec)
    return success_object(public(rec), 201)


def list_tax_records(beneficiary_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER,
                     ROLE_APPEALS_OFFICER])
    check_ownership(role, uid, beneficiary_id)
    if not get("beneficiaries", beneficiary_id):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    limit, offset = pagination_args()
    rows = sort_entities(find("tax_records",
                              lambda e: e["beneficiary_id"] == beneficiary_id))
    page, total = paginate(rows, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


def register(app):
    app.add_url_rule("/medicare/tax-records", "create_tax_record",
                     create_tax_record, methods=["POST"])
    app.add_url_rule("/medicare/beneficiaries/<beneficiary_id>/tax-records",
                     "list_tax_records", list_tax_records, methods=["GET"])
