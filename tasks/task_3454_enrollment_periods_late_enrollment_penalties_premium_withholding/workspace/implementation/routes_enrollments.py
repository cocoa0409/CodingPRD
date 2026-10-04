"""CoverageEnrollment: create, read, list, terminate, switch collection."""
from __future__ import annotations

from authn import (ROLE_BENEFICIARY, ROLE_BENEFIT_ADMINISTRATOR,
                   ROLE_FIELD_OFFICER, authenticate, authorize,
                   body_beneficiary_ownership, check_ownership)
from calcs import calc_coverage_effective_month
from clock import clock_month, month_diff, month_str, parse_month
from db import find, find_one, get, make_entity, public, sort_entities, touch
from domain import (activate_enrollment, active_arrangement,
                    governing_window, maybe_stop_arrangement, sync_penalty)
from envelope import success_list, success_object
from errors import fail
from validate import (body_json, pagination_args, paginate, req_enum, req_str)

ENROLLABLE_PARTS = ("PART_A", "PART_B", "PART_D")
ALL_PARTS = ("PART_A", "PART_B", "PART_C", "PART_D")


def _load_enrollment(enrollment_id, role, uid):
    ent = get("enrollments", enrollment_id)
    if not ent:
        fail("ERR_ENROLLMENT_NOT_FOUND", "No enrollment with that id")
    check_ownership(role, uid, ent["beneficiary_id"])
    return ent


def create_enrollment():
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])
    body = body_json()
    body_beneficiary_ownership(role, uid, body)
    bid = req_str(body, "beneficiary_id")
    part = req_enum(body, "part", ALL_PARTS)
    benef = get("beneficiaries", bid)
    if not benef:
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    cm = clock_month()
    # Pinned order: window -> duplicate -> part support
    window = governing_window(benef, cm)
    if window is None:
        fail("ERR_NO_OPEN_ENROLLMENT_WINDOW",
             "No enrollment window governs the clock month")
    dup = find_one("enrollments",
                   lambda e: e["beneficiary_id"] == bid
                   and e["part"] == part
                   and e["enrollment_status"] in ("PENDING", "ACTIVE"))
    if dup:
        fail("ERR_DUPLICATE_ENROLLMENT",
             "A PENDING or ACTIVE enrollment for that part already exists")
    if part not in ENROLLABLE_PARTS:
        fail("ERR_UNSUPPORTED_PART",
             "PART_C is created only by election effectivity")
    eff_ym = calc_coverage_effective_month(window, benef["attainment_month"], cm)
    ent = make_entity("enrollments", {
        "beneficiary_id": bid,
        "part": part,
        "enrollment_status": "PENDING",
        "collection_status": "PENDING_SETUP",
        "effective_month": month_str(eff_ym),
        "end_month": None,
        "enrolled_via_window": window,
    })
    if month_diff(eff_ym, cm) <= 0:
        activate_enrollment(ent)
    if part in ("PART_B", "PART_D"):
        sync_penalty(bid, part, eff_ym, exclude_enrollment_id=ent["id"])
    return success_object(public(ent), 201)


def get_enrollment(enrollment_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER,
                     ROLE_BENEFIT_ADMINISTRATOR])
    ent = _load_enrollment(enrollment_id, role, uid)
    return success_object(public(ent))


def list_enrollments(beneficiary_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER,
                     ROLE_BENEFIT_ADMINISTRATOR])
    check_ownership(role, uid, beneficiary_id)
    if not get("beneficiaries", beneficiary_id):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    limit, offset = pagination_args()
    rows = sort_entities(find("enrollments",
                              lambda e: e["beneficiary_id"] == beneficiary_id))
    page, total = paginate(rows, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


def terminate_enrollment_route(enrollment_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])
    ent = _load_enrollment(enrollment_id, role, uid)
    status = ent["enrollment_status"]
    if status == "PENDING":
        ent["enrollment_status"] = "CANCELLED"
        ent["collection_status"] = "CLOSED"  # end_month stays null
        touch(ent)
        maybe_stop_arrangement(ent["beneficiary_id"])
    elif status == "ACTIVE":
        ent["enrollment_status"] = "TERMINATED"
        ent["end_month"] = month_str(clock_month())
        ent["collection_status"] = "CLOSED"
        touch(ent)
        maybe_stop_arrangement(ent["beneficiary_id"])
    else:
        fail("ERR_INVALID_STATE", "Enrollment is already terminal")
    return success_object(public(ent))


def switch_collection_method(enrollment_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])
    body = body_json()
    target = req_enum(body, "target_method", ("WITHHOLDING", "DIRECT_BILL"))
    ent = _load_enrollment(enrollment_id, role, uid)
    current = ent["collection_status"]
    if target == "WITHHOLDING":
        if current != "DIRECT_BILL":
            fail("ERR_INVALID_STATE",
                 "Switch to WITHHOLDING requires DIRECT_BILL source state")
        if not active_arrangement(ent["beneficiary_id"]):
            fail("ERR_NO_ACTIVE_WITHHOLDING",
                 "Beneficiary has no ACTIVE withholding arrangement")
        ent["collection_status"] = "WITHHOLDING"
    else:  # DIRECT_BILL
        if current != "WITHHOLDING":
            fail("ERR_INVALID_STATE",
                 "Switch to DIRECT_BILL requires WITHHOLDING source state")
        ent["collection_status"] = "DIRECT_BILL"
    touch(ent)
    return success_object(public(ent))


def register(app):
    app.add_url_rule("/medicare/enrollments", "create_enrollment",
                     create_enrollment, methods=["POST"])
    app.add_url_rule("/medicare/enrollments/<enrollment_id>",
                     "get_enrollment", get_enrollment, methods=["GET"])
    app.add_url_rule("/medicare/beneficiaries/<beneficiary_id>/enrollments",
                     "list_enrollments", list_enrollments, methods=["GET"])
    app.add_url_rule("/medicare/enrollments/<enrollment_id>/terminate",
                     "terminate_enrollment", terminate_enrollment_route,
                     methods=["POST"])
    app.add_url_rule(
        "/medicare/enrollments/<enrollment_id>/switch-collection-method",
        "switch_collection_method", switch_collection_method, methods=["POST"])
