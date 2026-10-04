"""PremiumDetermination: compute, read, list, list-appeals."""
from __future__ import annotations

from authn import (ROLE_APPEALS_OFFICER, ROLE_BENEFICIARY, ROLE_FIELD_OFFICER,
                   authenticate, authorize, body_beneficiary_ownership,
                   check_ownership)
from db import find, find_one, get, make_entity, public, sort_entities
from domain import (compute_determination_fields, rate_schedule_for_year,
                    tax_record_for)
from envelope import success_list, success_object
from errors import fail
from validate import (body_json, pagination_args, paginate, req_enum, req_int,
                      req_str)

DET_ROLES = [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER, ROLE_APPEALS_OFFICER]
PRICEABLE_PARTS = ("PART_B", "PART_D")
ALL_PARTS = ("PART_A", "PART_B", "PART_C", "PART_D")


def _load_determination(det_id, role, uid):
    det = get("determinations", det_id)
    if not det:
        fail("ERR_DETERMINATION_NOT_FOUND", "No premium determination with that id")
    check_ownership(role, uid, det["beneficiary_id"])
    return det


def create_determination():
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])
    body = body_json()
    body_beneficiary_ownership(role, uid, body)
    bid = req_str(body, "beneficiary_id")
    coverage_year = req_int(body, "coverage_year")
    part = req_enum(body, "part", ALL_PARTS)
    if not get("beneficiaries", bid):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    # Pinned business order: part -> schedule -> tax data -> enrollment -> dup
    if part not in PRICEABLE_PARTS:
        fail("ERR_UNSUPPORTED_PART",
             "PART_A is premium-free and PART_C is plan-priced")
    schedule = rate_schedule_for_year(coverage_year)
    if not schedule:
        fail("ERR_RATE_SCHEDULE_MISSING",
             "No RateSchedule published for that coverage_year")
    if not tax_record_for(bid, coverage_year - 2) \
            and not tax_record_for(bid, coverage_year - 3):
        fail("ERR_TAX_DATA_MISSING",
             "Neither coverage_year-2 nor coverage_year-3 has a tax record")
    has_enrollment = find_one(
        "enrollments",
        lambda e: e["beneficiary_id"] == bid
        and e["part"] == part
        and e["enrollment_status"] != "CANCELLED")
    if not has_enrollment:
        fail("ERR_NO_ENROLLMENT_FOR_PART",
             "No non-CANCELLED enrollment exists for that part")
    dup = find_one("determinations",
                   lambda d: d["beneficiary_id"] == bid
                   and d["coverage_year"] == coverage_year
                   and d["part"] == part
                   and d["status"] != "SUPERSEDED")
    if dup:
        fail("ERR_DUPLICATE_DETERMINATION",
             "A live determination already exists for that triple")
    fields = compute_determination_fields(bid, part, coverage_year, schedule)
    det = make_entity("determinations", {
        "beneficiary_id": bid,
        "coverage_year": coverage_year,
        "part": part,
        "created_by_user_id": uid,
        **fields,
    })
    return success_object(public(det), 201)


def get_determination(det_id):
    role, uid = authenticate()
    authorize(role, DET_ROLES)
    det = _load_determination(det_id, role, uid)
    return success_object(public(det))


def list_determinations(beneficiary_id):
    role, uid = authenticate()
    authorize(role, DET_ROLES)
    check_ownership(role, uid, beneficiary_id)
    if not get("beneficiaries", beneficiary_id):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    limit, offset = pagination_args()
    rows = sort_entities(find("determinations",
                              lambda e: e["beneficiary_id"] == beneficiary_id))
    page, total = paginate(rows, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


def list_determination_appeals(det_id):
    role, uid = authenticate()
    authorize(role, DET_ROLES)
    det = _load_determination(det_id, role, uid)
    limit, offset = pagination_args()
    rows = sort_entities(find("appeals",
                              lambda a: a["premium_determination_id"] == det["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


def register(app):
    app.add_url_rule("/medicare/premium-determinations",
                     "create_determination", create_determination,
                     methods=["POST"])
    app.add_url_rule("/medicare/premium-determinations/<det_id>",
                     "get_determination", get_determination, methods=["GET"])
    app.add_url_rule(
        "/medicare/beneficiaries/<beneficiary_id>/premium-determinations",
        "list_determinations", list_determinations, methods=["GET"])
    app.add_url_rule("/medicare/premium-determinations/<det_id>/appeals",
                     "list_determination_appeals", list_determination_appeals,
                     methods=["GET"])
