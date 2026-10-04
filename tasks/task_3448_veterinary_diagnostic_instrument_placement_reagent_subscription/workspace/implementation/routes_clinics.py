"""Clinics: POST, GET one, PATCH (caseload and/or status transitions)."""
from flask import Blueprint

import db
import ser
import services
import util
from errors import err

bp = Blueprint("clinics", __name__)


@bp.post("/api/clinics")
def create_clinic():
    _, role = util.auth()
    util.require(role, ["PlatformAdmin"])
    b = util.body()

    name = b.get("name")
    if not isinstance(name, str) or not name:
        raise err("ERR_INVALID_REQUEST", "name is required")
    baseline = b.get("caseload_baseline_tests")
    if not util.is_int(baseline) or baseline <= 0:
        raise err("ERR_INVALID_REQUEST",
                  "caseload_baseline_tests must be a strictly positive integer")
    for code_field in ("corporate_group_code", "buying_group_code"):
        v = b.get(code_field)
        if v is not None and not isinstance(v, str):
            raise err("ERR_INVALID_REQUEST", f"{code_field} must be a string or null")

    c = services.stamp({
        "name": name,
        "corporate_group_code": b.get("corporate_group_code"),
        "buying_group_code": b.get("buying_group_code"),
        "caseload_baseline_tests": baseline,
        "caseload_current_tests": baseline,
        "status": "ACTIVE",
    })
    db.clinics[c["id"]] = c
    return util.ok(ser.clinic(c), code=201)


@bp.get("/api/clinics/<cid>")
def get_clinic(cid):
    util.auth()
    c = db.clinics.get(cid)
    if c is None:
        raise err("ERR_CLINIC_NOT_FOUND", "clinic does not exist")
    return util.ok(ser.clinic(c))


@bp.patch("/api/clinics/<cid>")
def patch_clinic(cid):
    uid, role = util.auth()
    util.require(role, ["PlatformAdmin", "ClinicManager"])
    b = util.body()

    # Tier 2 field-level rule: the status field is PlatformAdmin-only.
    status_present = b.get("status") is not None
    caseload_present = b.get("caseload_current_tests") is not None
    if status_present and role != "PlatformAdmin":
        util.forbidden("the status field requires PlatformAdmin")

    # Tier 3 ownership: for a clinic the target's clinic is the clinic itself.
    if role == "ClinicManager" and uid != cid:
        raise err("ERR_CLINIC_OWNERSHIP_MISMATCH",
                  "X-User-ID must equal the clinic id")

    c = db.clinics.get(cid)
    if c is None:
        raise err("ERR_CLINIC_NOT_FOUND", "clinic does not exist")

    # Tier 5 input shape.
    if caseload_present and not util.is_int(b["caseload_current_tests"]):
        raise err("ERR_INVALID_REQUEST",
                  "caseload_current_tests must be an integer")
    if status_present and b["status"] not in ("ACTIVE", "SUSPENDED", "TERMINATED"):
        raise err("ERR_INVALID_REQUEST", "invalid clinic status")

    # Tier 6+ state rules.
    if caseload_present and c["status"] != "ACTIVE":
        raise err("ERR_CLINIC_NOT_ACTIVE",
                  "caseload_current_tests is mutable only while the clinic is ACTIVE")
    if status_present:
        cur, tgt = c["status"], b["status"]
        if (cur, tgt) == ("ACTIVE", "SUSPENDED"):
            pass
        elif (cur, tgt) == ("SUSPENDED", "ACTIVE"):
            for a in db.agreements.values():
                if (a["clinic_id"] == cid and a["status"] == "BREACHED"
                        and a["cumulative_unpaid_billed_cents"] > 0):
                    raise err("ERR_AGREEMENT_INVALID_STATE",
                              "a BREACHED agreement with unpaid balance blocks "
                              "reactivation")
        elif tgt == "TERMINATED" and cur in ("ACTIVE", "SUSPENDED"):
            for a in db.agreements.values():
                if a["clinic_id"] == cid and a["status"] != "COMPLETED":
                    raise err("ERR_AGREEMENT_INVALID_STATE",
                              "every placement agreement must be COMPLETED before "
                              "termination")
            for a in db.agreements.values():
                if a["clinic_id"] == cid and a["cumulative_unpaid_billed_cents"] > 0:
                    raise err("ERR_OUTSTANDING_SHORTFALL_UNPAID",
                              "an agreement carries an unpaid shortfall balance")
        else:
            raise err("ERR_CLINIC_NOT_ACTIVE",
                      f"clinic status transition {cur} -> {tgt} is not allowed")

    mutated = False
    if caseload_present:
        c["caseload_current_tests"] = b["caseload_current_tests"]
        mutated = True
    if status_present:
        c["status"] = b["status"]
        mutated = True
    if mutated:
        services.bump(c)
    return util.ok(ser.clinic(c))
