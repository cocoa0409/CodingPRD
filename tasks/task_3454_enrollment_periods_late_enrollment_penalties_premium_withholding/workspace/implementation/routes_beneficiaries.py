"""Beneficiary registration/read + beneficiary-scoped lists for
enrollment periods, payer coordination, and penalty assessments."""
from __future__ import annotations

from authn import (ROLE_APPEALS_OFFICER, ROLE_BENEFICIARY, ROLE_BENEFIT_ADMINISTRATOR,
                   ROLE_FIELD_OFFICER, authenticate, authorize, check_ownership)
from calcs import calc_attainment_month
from clock import clock_month, month_str, parse_month
from db import find, get, make_entity, public, sort_entities
from domain import derive_window_status
from envelope import success_list, success_object
from errors import fail
from validate import body_json, pagination_args, paginate, req_date_str, req_str


def _require_beneficiary(beneficiary_id, role, uid):
    """Ownership (3) on the direct path id, then existence (5)."""
    check_ownership(role, uid, beneficiary_id)
    benef = get("beneficiaries", beneficiary_id)
    if not benef:
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    return benef


def create_beneficiary():
    role, uid = authenticate()
    authorize(role, [ROLE_FIELD_OFFICER])
    body = body_json()
    full_name = req_str(body, "full_name")
    dob = req_date_str(body, "date_of_birth")
    attainment, iep_start, iep_end = calc_attainment_month(dob)
    benef = make_entity("beneficiaries", {
        "full_name": full_name,
        "date_of_birth": dob,
        "attainment_month": attainment,
        "iep_start_month": iep_start,
        "iep_end_month": iep_end,
        "credit_cents": 0,
    })
    cm = clock_month()
    make_entity("enrollment_periods", {
        "beneficiary_id": benef["id"],
        "window_type": "IEP",
        "window_start_month": iep_start,
        "window_end_month": iep_end,
        "status": derive_window_status(parse_month(iep_start),
                                       parse_month(iep_end), cm),
        "source_coverage_ref": None,
    })
    make_entity("payer_records", {
        "beneficiary_id": benef["id"],
        "role": "MEDICARE_PRIMARY",
        "basis": "NO_EMPLOYER_COVERAGE",
        "effective_start_month": month_str(cm),
        "effective_end_month": None,
    })
    return success_object(public(benef), 201)


def get_beneficiary(beneficiary_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER,
                     ROLE_APPEALS_OFFICER, ROLE_BENEFIT_ADMINISTRATOR])
    benef = _require_beneficiary(beneficiary_id, role, uid)
    return success_object(public(benef))


def _list_scoped(store, beneficiary_id, allowed_roles):
    role, uid = authenticate()
    authorize(role, allowed_roles)
    _require_beneficiary(beneficiary_id, role, uid)
    limit, offset = pagination_args()
    rows = sort_entities(find(store,
                              lambda e: e["beneficiary_id"] == beneficiary_id))
    page, total = paginate(rows, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


def list_enrollment_periods(beneficiary_id):
    return _list_scoped("enrollment_periods", beneficiary_id,
                        [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])


def list_payer_coordination(beneficiary_id):
    return _list_scoped("payer_records", beneficiary_id,
                        [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])


def list_penalties(beneficiary_id):
    return _list_scoped("penalties", beneficiary_id,
                        [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])


def register(app):
    app.add_url_rule("/medicare/beneficiaries", "create_beneficiary",
                     create_beneficiary, methods=["POST"])
    app.add_url_rule("/medicare/beneficiaries/<beneficiary_id>",
                     "get_beneficiary", get_beneficiary, methods=["GET"])
    app.add_url_rule("/medicare/beneficiaries/<beneficiary_id>/enrollment-periods",
                     "list_enrollment_periods", list_enrollment_periods,
                     methods=["GET"])
    app.add_url_rule("/medicare/beneficiaries/<beneficiary_id>/payer-coordination",
                     "list_payer_coordination", list_payer_coordination,
                     methods=["GET"])
    app.add_url_rule("/medicare/beneficiaries/<beneficiary_id>/penalties",
                     "list_penalties", list_penalties, methods=["GET"])
