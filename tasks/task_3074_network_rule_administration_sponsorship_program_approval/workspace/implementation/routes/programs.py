"""Programs: register, list, get, edit, certification-tests submit, approve,
enable-production, retire."""

import re

from flask import Blueprint, request

import db
from errors import raise_err
from helpers import (
    base_record, exists_or_404, get_json, get_or_404, paginate, req_enum,
    req_str, sort_by_created, touch,
)
from middleware import require_roles
from response import ok
from services.cascade import retire_program_cascade

bp = Blueprint("programs", __name__)

PROGRAM_TYPES = {"CARD_PRODUCT", "WALLET", "COMMERCIAL"}
READ_ROLES = {"NetworkOperator", "CertificationEngineer"}
PRODUCT_CODE_RE = re.compile(r"[A-Z0-9]{2,4}")


@bp.post("/network/programs")
def create_program():
    require_roles({"CertificationEngineer"})
    body = get_json()
    name = req_str(body, "name")
    program_type = req_enum(body, "program_type", PROGRAM_TYPES)
    product_code = req_str(body, "product_code")
    owner_member_id = req_str(body, "owner_member_id")
    owner = exists_or_404(db.members, owner_member_id, "owner member")
    if not PRODUCT_CODE_RE.fullmatch(product_code):
        raise_err("ERR_VALIDATION", "product_code must be 2-4 uppercase alphanumeric characters")
    if owner["status"] != "ACTIVE":
        raise_err("ERR_VALIDATION", "Owner member must be ACTIVE")
    rec = base_record()
    rec.update({
        "name": name,
        "program_type": program_type,
        "product_code": product_code,
        "owner_member_id": owner_member_id,
        "status": "REGISTERED",
        "approved_version": None,
    })
    db.programs[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/programs")
def list_programs():
    require_roles(READ_ROLES)
    items = list(db.programs.values())
    owner = request.args.get("owner_member_id")
    status = request.args.get("status")
    if owner is not None:
        items = [p for p in items if p["owner_member_id"] == owner]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/programs/<pid>")
def get_program(pid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.programs, pid)
    return ok(rec, 200)


@bp.patch("/network/programs/<pid>")
def edit_program(pid):
    require_roles({"CertificationEngineer"})
    rec = get_or_404(db.programs, pid)
    body = get_json()
    name = body.get("name")
    product_code = body.get("product_code")
    if name is not None:
        if not isinstance(name, str) or name == "":
            raise_err("ERR_INVALID_REQUEST", "name must be a non-empty string")
        rec["name"] = name
    if product_code is not None:
        if not isinstance(product_code, str) or not PRODUCT_CODE_RE.fullmatch(product_code):
            raise_err("ERR_VALIDATION", "product_code must be 2-4 uppercase alphanumeric characters")
        rec["product_code"] = product_code
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/programs/<pid>/certification-tests")
def submit_certification_test(pid):
    require_roles({"CertificationEngineer"})
    rec = get_or_404(db.programs, pid)
    body = get_json()
    scope = req_enum(body, "scope", {"NEW_PRODUCT", "WALLET", "COMBINED"})
    if rec["status"] not in ("REGISTERED", "UNDER_CERTIFICATION"):
        raise_err("ERR_INVALID_STATE", "Program must be REGISTERED or UNDER_CERTIFICATION")
    if rec["status"] == "REGISTERED":
        rec["status"] = "UNDER_CERTIFICATION"
    touch(rec)
    # evaluated_program_version captures the program version as of submission
    # (after the REGISTERED -> UNDER_CERTIFICATION transition increment), so the
    # natural submit -> pass -> approve flow binds the PASS to the current version.
    test = base_record()
    test.update({
        "program_id": pid,
        "scope": scope,
        "status": "SUBMITTED",
        "failure_reason": None,
        "evaluated_program_version": rec["version"],
    })
    db.certification_tests[test["id"]] = test
    return ok(test, 201)


@bp.post("/network/programs/<pid>/approve")
def approve_program(pid):
    require_roles({"CertificationEngineer"})
    rec = get_or_404(db.programs, pid)
    body = get_json()
    if rec["status"] != "UNDER_CERTIFICATION":
        raise_err("ERR_INVALID_STATE", "Program is not UNDER_CERTIFICATION")
    # OCC: expected_program_version required
    if "expected_program_version" not in body:
        raise_err("ERR_INVALID_REQUEST", "expected_program_version is required")
    expected = body["expected_program_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err("ERR_INVALID_REQUEST", "expected_program_version must be an integer")
    if expected != rec["version"]:
        raise_err("ERR_STALE_VERSION", "expected_program_version does not match current program version")
    # Certification validity
    has_valid_pass = any(
        t["program_id"] == pid and t["status"] == "PASSED"
        and t["evaluated_program_version"] == rec["version"]
        for t in db.certification_tests.values()
    )
    if not has_valid_pass:
        raise_err("ERR_CERTIFICATION_STALE",
                  "No PASSED certification test matches the current program version")
    rec["approved_version"] = expected
    rec["status"] = "APPROVED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/programs/<pid>/enable-production")
def enable_production(pid):
    require_roles({"CertificationEngineer"})
    rec = get_or_404(db.programs, pid)
    if rec["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Program is not APPROVED")
    if rec.get("approved_version") is None or rec["version"] != rec["approved_version"] + 1:
        raise_err("ERR_PROGRAM_NOT_ENABLED",
                  "Program version has drifted from the approved pin")
    rec["status"] = "PRODUCTION_ENABLED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/programs/<pid>/retire")
def retire_program(pid):
    require_roles({"CertificationEngineer"})
    rec = get_or_404(db.programs, pid)
    if rec["status"] != "PRODUCTION_ENABLED":
        raise_err("ERR_INVALID_STATE", "Program is not PRODUCTION_ENABLED")
    rec["status"] = "RETIRED"
    touch(rec)
    retire_program_cascade(pid)
    return ok(rec, 200)
