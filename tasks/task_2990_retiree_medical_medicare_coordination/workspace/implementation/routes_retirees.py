"""Retiree endpoints (PRD 3.3) including the Medicare dimension moves."""

from flask import Blueprint, request

import calc
import errors
from auth import (ALL_ROLES, ALL_ROLES_EXCEPT_RETIREE, ROLE_BENEFITS_ADMIN,
                  ROLE_ELIGIBILITY_ANALYST, require_caller)
from domain import active_enrollments_of_retiree, apply_msp, get_retiree
from envelope import object_response, paginate
from errors import fail
from store import base_record, db, order_asc, touch
from validate import read_body

bp = Blueprint("retirees", __name__)

MEDICARE_STATUSES = ("PRE_MEDICARE", "MEDICARE_ELIGIBLE_NOT_ENROLLED",
                     "MEDICARE_ENROLLED", "MEDICARE_WAIVED")
ELIGIBILITY_STATUSES = ("UNDETERMINED", "ELIGIBLE", "INELIGIBLE")
GRANDFATHER_GROUPS = ("GRANDFATHERED_A", "TRANSITION_B", "STANDARD_C")

# The three declared moves of the Medicare dimension.
MEDICARE_MOVES = {
    "PRE_MEDICARE": ("MEDICARE_ELIGIBLE_NOT_ENROLLED",),
    "MEDICARE_ELIGIBLE_NOT_ENROLLED": ("MEDICARE_WAIVED", "MEDICARE_ENROLLED"),
    "MEDICARE_WAIVED": ("MEDICARE_ENROLLED",),
    "MEDICARE_ENROLLED": (),
}

WRITER_ROLES = (ROLE_BENEFITS_ADMIN, ROLE_ELIGIBILITY_ANALYST)


@bp.post("/retiree-benefits/retirees")
def create_retiree():
    require_caller(WRITER_ROLES)
    body = read_body()

    full_name = body.string("full_name", min_len=1, max_len=120)
    birth_date = body.date("birth_date")
    hire_date = body.date("hire_date")
    retirement_date = body.date("retirement_date")
    credited_service_months = body.integer("credited_service_months", minimum=0)
    medicare_status = body.enum("medicare_status", MEDICARE_STATUSES,
                                required=False, default="PRE_MEDICARE")
    part_b_date = body.date("medicare_part_b_effective_date", required=False,
                            nullable=True, default=None)
    employer_size = body.integer("other_group_coverage_employer_size",
                                 required=False, minimum=0, default=0)
    active_employment = body.boolean("active_employment_flag", required=False,
                                     default=False)
    esrd_flag = body.boolean("esrd_flag", required=False, default=False)
    esrd_date = body.date("esrd_entitlement_date", required=False,
                          nullable=True, default=None)
    disability_flag = body.boolean("disability_entitlement_flag",
                                   required=False, default=False)

    record = base_record()
    record.update({
        "full_name": full_name,
        "birth_date": birth_date,
        "hire_date": hire_date,
        "retirement_date": retirement_date,
        "credited_service_months": credited_service_months,
        "eligibility_status": "UNDETERMINED",
        "medicare_status": medicare_status,
        "medicare_part_b_effective_date": part_b_date,
        "other_group_coverage_employer_size": employer_size,
        "active_employment_flag": active_employment,
        "esrd_flag": esrd_flag,
        "esrd_entitlement_date": esrd_date,
        "disability_entitlement_flag": disability_flag,
        "grandfathered_group": calc.grandfather_group(hire_date),
        "determination_sequence": 0,
    })
    record["eligibility_points"] = calc.eligibility_points(record)
    db.retirees[record["id"]] = record
    return object_response(record, 201)


@bp.get("/retiree-benefits/retirees/<retiree_id>")
def read_retiree(retiree_id):
    require_caller(ALL_ROLES)
    return object_response(get_retiree(retiree_id))


@bp.get("/retiree-benefits/retirees")
def list_retirees():
    require_caller(ALL_ROLES_EXCEPT_RETIREE)
    rows = list(db.retirees.values())
    for field in ("eligibility_status", "medicare_status", "grandfathered_group"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return paginate(order_asc(rows))


@bp.patch("/retiree-benefits/retirees/<retiree_id>")
def update_retiree(retiree_id):
    require_caller(WRITER_ROLES)
    retiree = get_retiree(retiree_id)
    body = read_body()

    requested_status = body.enum("medicare_status", MEDICARE_STATUSES,
                                 required=False, default=None)
    part_b_supplied = body.present("medicare_part_b_effective_date")
    part_b_date = body.date("medicare_part_b_effective_date", required=False,
                            nullable=True, default=None)
    employer_size = body.integer("other_group_coverage_employer_size",
                                 required=False, minimum=0, default=None)
    active_employment = body.boolean("active_employment_flag", required=False,
                                     default=None)
    esrd_flag = body.boolean("esrd_flag", required=False, default=None)
    esrd_supplied = body.present("esrd_entitlement_date")
    esrd_date = body.date("esrd_entitlement_date", required=False,
                          nullable=True, default=None)
    disability_flag = body.boolean("disability_entitlement_flag",
                                   required=False, default=None)
    credited_service_months = body.integer("credited_service_months",
                                           required=False, minimum=0,
                                           default=None)

    if requested_status is not None and requested_status != retiree["medicare_status"]:
        if requested_status not in MEDICARE_MOVES[retiree["medicare_status"]]:
            fail(errors.ERR_INVALID_REQUEST,
                 "medicare_status may not move from %s to %s."
                 % (retiree["medicare_status"], requested_status))
        if requested_status == "MEDICARE_ENROLLED":
            effective = part_b_date if part_b_supplied else retiree["medicare_part_b_effective_date"]
            if effective is None:
                fail(errors.ERR_INVALID_REQUEST,
                     "MEDICARE_ENROLLED requires a non-null "
                     "medicare_part_b_effective_date.")

    if part_b_supplied:
        retiree["medicare_part_b_effective_date"] = part_b_date
    if employer_size is not None:
        retiree["other_group_coverage_employer_size"] = employer_size
    if active_employment is not None:
        retiree["active_employment_flag"] = active_employment
    if esrd_flag is not None:
        retiree["esrd_flag"] = esrd_flag
    if esrd_supplied:
        retiree["esrd_entitlement_date"] = esrd_date
    if disability_flag is not None:
        retiree["disability_entitlement_flag"] = disability_flag
    if credited_service_months is not None:
        retiree["credited_service_months"] = credited_service_months
        retiree["eligibility_points"] = calc.eligibility_points(retiree)
    if requested_status is not None:
        retiree["medicare_status"] = requested_status

    for enrollment in active_enrollments_of_retiree(retiree["id"]):
        apply_msp(enrollment, retiree)
        touch(enrollment)

    touch(retiree)
    return object_response(retiree)
