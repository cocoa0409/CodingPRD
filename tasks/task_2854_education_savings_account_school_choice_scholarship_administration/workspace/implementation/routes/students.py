"""Student intake and the allowable-expense catalogue."""
import re

from flask import Blueprint

import lookups
from envelope import object_response, public
from errors import invalid
from store import new_id, store
from validators import (CATEGORY_CODE_RE, CATEGORY_FLAGS, INCOME_BANDS,
                        PRIOR_ENROLLMENTS, authenticate, body, v_bool, v_date,
                        v_enum, v_flag_list, v_int, v_state_code, v_str)

bp = Blueprint("students", __name__)


@bp.post("/students")
def create_student():
    authenticate("ProgramAdmin")
    payload = body()
    household_id = v_str(payload, "household_id")
    first_name = v_str(payload, "first_name")
    last_name = v_str(payload, "last_name")
    date_of_birth = v_date(payload, "date_of_birth")
    residency_state = v_state_code(payload, "residency_state")
    prior_enrollment = v_enum(payload, "prior_enrollment", PRIOR_ENROLLMENTS)
    income_band = v_enum(payload, "income_band", INCOME_BANDS)
    category_flags = v_flag_list(payload, "category_flags", CATEGORY_FLAGS,
                                 required=False, default=[])
    has_enrolled_sibling = v_bool(payload, "has_enrolled_sibling",
                                  required=False, default=False)

    created_at = store.next_created_at()
    record = {
        "id": new_id(),
        "household_id": household_id,
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": date_of_birth,
        "residency_state": residency_state,
        "prior_enrollment": prior_enrollment,
        "income_band": income_band,
        "category_flags": list(category_flags or []),
        "has_enrolled_sibling": has_enrolled_sibling,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.students[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/students/<sid>")
def read_student(sid):
    authenticate("ProgramAdmin", "EligibilityOfficer", "ComplianceOfficer",
                 "AppealsOfficer", "Guardian")
    return object_response(public(lookups.student(sid)))


@bp.post("/expense-categories")
def create_expense_category():
    authenticate("ProgramAdmin")
    payload = body()
    code = v_str(payload, "code")
    name = v_str(payload, "name")
    per_year_cap_cents = v_int(payload, "per_year_cap_cents", minimum=1)
    allowable = v_bool(payload, "allowable", required=False, default=True)
    requires_preapproval = v_bool(payload, "requires_preapproval",
                                  required=False, default=True)
    requires_service_period = v_bool(payload, "requires_service_period",
                                     required=False, default=False)
    if not CATEGORY_CODE_RE.match(code):
        invalid("code must be uppercase snake case")
    if lookups.category_by_code(code) is not None:
        invalid("code '%s' already exists in the catalogue" % code)

    created_at = store.next_created_at()
    record = {
        "id": new_id(),
        "code": code,
        "name": name,
        "allowable": allowable,
        "requires_preapproval": requires_preapproval,
        "per_year_cap_cents": per_year_cap_cents,
        "requires_service_period": requires_service_period,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.expense_categories[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/expense-categories/<cid>")
def read_expense_category(cid):
    authenticate("ProgramAdmin", "ExpenseReviewer", "ComplianceOfficer",
                 "VendorScreener", "Guardian", "Provider")
    return object_response(public(lookups.expense_category(cid)))
