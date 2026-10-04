"""Certification tests: list, get, pass, fail."""

from flask import Blueprint, request

import db
from errors import raise_err
from helpers import get_json, get_or_404, paginate, req_str, sort_by_created, touch
from middleware import require_roles
from response import ok

bp = Blueprint("certification_tests", __name__)

READ_ROLES = {"NetworkOperator", "CertificationEngineer"}


@bp.get("/network/certification-tests")
def list_tests():
    require_roles(READ_ROLES)
    items = list(db.certification_tests.values())
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [t for t in items if t["program_id"] == program_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/certification-tests/<tid>")
def get_test(tid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.certification_tests, tid)
    return ok(rec, 200)


@bp.post("/network/certification-tests/<tid>/pass")
def pass_test(tid):
    require_roles({"CertificationEngineer"})
    rec = get_or_404(db.certification_tests, tid)
    if rec["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "CertificationTest is not SUBMITTED")
    rec["status"] = "PASSED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/certification-tests/<tid>/fail")
def fail_test(tid):
    require_roles({"CertificationEngineer"})
    rec = get_or_404(db.certification_tests, tid)
    body = get_json()
    failure_reason = req_str(body, "failure_reason")
    if rec["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "CertificationTest is not SUBMITTED")
    rec["status"] = "FAILED"
    rec["failure_reason"] = failure_reason
    touch(rec)
    # Program reverts to REGISTERED when no other run remains SUBMITTED
    program = db.programs.get(rec["program_id"])
    if program is not None and program["status"] == "UNDER_CERTIFICATION":
        any_submitted = any(
            t["program_id"] == program["id"] and t["status"] == "SUBMITTED"
            for t in db.certification_tests.values()
        )
        if not any_submitted:
            program["status"] = "REGISTERED"
            touch(program)
    return ok(rec, 200)
