"""EmployerCoverageRecord: register, list, verify, end (+SEP/payer cascades)."""
from __future__ import annotations

from authn import (ROLE_BENEFICIARY, ROLE_FIELD_OFFICER, authenticate,
                   authorize, body_beneficiary_ownership, check_ownership)
from calcs import calc_sep_window
from clock import (add_months, clock_month, month_diff, month_str,
                   parse_month)
from db import find, get, make_entity, public, sort_entities, touch
from domain import (apply_payer_role_change, derive_window_status,
                    payer_role_at)
from envelope import success_list, success_object
from errors import fail
from validate import (body_json, opt_bool, opt_month_str, pagination_args,
                      paginate, req_enum, req_int, req_month_str, req_str)

_FAR_FUTURE = (9999, 12)


def _closed_bounds(rec):
    start = parse_month(rec["coverage_start_month"])
    end = (parse_month(rec["coverage_end_month"])
           if rec["coverage_end_month"] else _FAR_FUTURE)
    return start, end


def _intervals_collide(a_start, a_end, b_start, b_end) -> bool:
    """Closed-interval overlap: share even one calendar month."""
    return month_diff(a_start, b_end) <= 0 and month_diff(b_start, a_end) <= 0


def _load_record(record_id, role=None, uid=None, ownership=False):
    rec = get("employer_coverages", record_id)
    if not rec:
        fail("ERR_COVERAGE_RECORD_NOT_FOUND",
             "No employer coverage record with that id")
    if ownership:
        check_ownership(role, uid, rec["beneficiary_id"])
    return rec


def create_employer_coverage():
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])
    body = body_json()
    body_beneficiary_ownership(role, uid, body)
    bid = req_str(body, "beneficiary_id")
    employer_name = req_str(body, "employer_name")
    employer_size = req_int(body, "employer_size")
    start = req_month_str(body, "coverage_start_month")
    end = opt_month_str(body, "coverage_end_month")
    employment_end = opt_month_str(body, "employment_end_month")
    creditable = opt_bool(body, "is_drug_coverage_creditable", default=False)
    if not get("beneficiaries", bid):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    new_start, new_end = parse_month(start), \
        (parse_month(end) if end else _FAR_FUTURE)
    for other in find("employer_coverages",
                      lambda r: r["beneficiary_id"] == bid
                      and r["employer_name"] == employer_name
                      and r["verification_status"] != "REJECTED"):
        o_start, o_end = _closed_bounds(other)
        if _intervals_collide(new_start, new_end, o_start, o_end):
            fail("ERR_COVERAGE_PERIOD_OVERLAP",
                 "Coverage interval collides with an existing record")
    rec = make_entity("employer_coverages", {
        "beneficiary_id": bid,
        "employer_name": employer_name,
        "employer_size": employer_size,
        "coverage_start_month": start,
        "coverage_end_month": end,
        "employment_end_month": employment_end,
        "is_drug_coverage_creditable": creditable,
        "verification_status": "UNVERIFIED",
        "record_status": "ACTIVE_COVERAGE",
    })
    return success_object(public(rec), 201)


def list_employer_coverages(beneficiary_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])
    check_ownership(role, uid, beneficiary_id)
    if not get("beneficiaries", beneficiary_id):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    limit, offset = pagination_args()
    rows = sort_entities(find("employer_coverages",
                              lambda e: e["beneficiary_id"] == beneficiary_id))
    page, total = paginate(rows, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


def verify_employer_coverage(record_id):
    role, uid = authenticate()
    authorize(role, [ROLE_FIELD_OFFICER])
    body = body_json()
    decision = req_enum(body, "decision", ("VERIFIED", "REJECTED"))
    rec = _load_record(record_id)
    if decision == "VERIFIED":
        if rec["verification_status"] not in ("UNVERIFIED", "REJECTED"):
            fail("ERR_INVALID_STATE", "Record is already VERIFIED")
        new_start, new_end = _closed_bounds(rec)
        for other in find("employer_coverages",
                          lambda r: r["beneficiary_id"] == rec["beneficiary_id"]
                          and r["employer_name"] == rec["employer_name"]
                          and r["id"] != rec["id"]
                          and r["verification_status"] == "VERIFIED"):
            o_start, o_end = _closed_bounds(other)
            if _intervals_collide(new_start, new_end, o_start, o_end):
                fail("ERR_COVERAGE_PERIOD_OVERLAP",
                     "Coverage interval collides with a VERIFIED record")
        rec["verification_status"] = "VERIFIED"
        touch(rec)
        # Retroactive payer recompute from coverage_start_month
        start_ym = parse_month(rec["coverage_start_month"])
        new_role, new_basis = payer_role_at(rec["beneficiary_id"], start_ym)
        apply_payer_role_change(rec["beneficiary_id"], new_role, new_basis,
                                start_ym)
    else:  # REJECTED
        if rec["verification_status"] != "UNVERIFIED":
            fail("ERR_INVALID_STATE",
                 "Only an UNVERIFIED record may be rejected")
        rec["verification_status"] = "REJECTED"
        touch(rec)
    return success_object(public(rec))


def end_employer_coverage(record_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])
    body = body_json()
    coverage_end = req_month_str(body, "coverage_end_month")
    employment_end = req_month_str(body, "employment_end_month")
    rec = _load_record(record_id, role, uid, ownership=True)
    cm = clock_month()
    # Pinned order: generic state -> temporal sanity -> verification
    if rec["record_status"] != "ACTIVE_COVERAGE":
        fail("ERR_INVALID_STATE", "Coverage record is already ENDED")
    cov_end_ym = parse_month(coverage_end)
    emp_end_ym = parse_month(employment_end)
    if (month_diff(cov_end_ym, parse_month(rec["coverage_start_month"])) < 0
            or month_diff(cov_end_ym, cm) > 0
            or month_diff(emp_end_ym, cm) > 0):
        fail("ERR_EFFECTIVE_DATE_INVALID",
             "End months must be >= coverage_start_month and <= clock month")
    if rec["verification_status"] != "VERIFIED":
        fail("ERR_COVERAGE_NOT_VERIFIED",
             "Coverage must be VERIFIED before it can be ended")
    rec["coverage_end_month"] = coverage_end
    rec["employment_end_month"] = employment_end
    rec["record_status"] = "ENDED"
    touch(rec)
    # SEP cascade: anchor = whichever ended first; [anchor+1, anchor+8]
    sep_start, sep_end = calc_sep_window(employment_end, coverage_end)
    make_entity("enrollment_periods", {
        "beneficiary_id": rec["beneficiary_id"],
        "window_type": "SEP",
        "window_start_month": month_str(sep_start),
        "window_end_month": month_str(sep_end),
        "status": derive_window_status(sep_start, sep_end, cm),
        "source_coverage_ref": rec["id"],
    })
    # Payer flip (prospective): PRIMARY resumes at coverage_end_month + 1
    resume_ym = add_months(cov_end_ym, 1)
    new_role, new_basis = payer_role_at(rec["beneficiary_id"], resume_ym)
    apply_payer_role_change(rec["beneficiary_id"], new_role, new_basis,
                            resume_ym)
    return success_object(public(rec))


def register(app):
    app.add_url_rule("/medicare/employer-coverages",
                     "create_employer_coverage", create_employer_coverage,
                     methods=["POST"])
    app.add_url_rule("/medicare/beneficiaries/<beneficiary_id>/employer-coverages",
                     "list_employer_coverages", list_employer_coverages,
                     methods=["GET"])
    app.add_url_rule("/medicare/employer-coverages/<record_id>/verify",
                     "verify_employer_coverage", verify_employer_coverage,
                     methods=["POST"])
    app.add_url_rule("/medicare/employer-coverages/<record_id>/end",
                     "end_employer_coverage", end_employer_coverage,
                     methods=["POST"])
