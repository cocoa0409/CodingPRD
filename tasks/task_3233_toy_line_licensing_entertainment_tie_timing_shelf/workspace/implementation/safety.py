from flask import Blueprint, request
from auth import caller, require_role
from store import db, stamp_new, touch
from util import ApiErr, ok_obj, paged, not_found, bad_req, new_id, get_body
from skus import validate_age, validate_claims, CLAIMS

bp = Blueprint("safety", __name__)

def st_json(t):
    return {"id": t["id"], "sku_id": t["sku_id"], "test_type": t["test_type"],
            "lab_name": t["lab_name"],
            "claimed_age_grade_months": t["claimed_age_grade_months"],
            "result_age_grade_months": t["result_age_grade_months"],
            "validated_claims": t["validated_claims"], "status": t["status"],
            "created_at": t["created_at"], "updated_at": t["updated_at"],
            "version": t["version"]}

@bp.post("/safety-tests")
def create_test():
    require_role("SafetyEngineer")
    b = get_body()
    req = ("sku_id", "test_type", "lab_name", "claimed_age_grade_months")
    for f in req:
        if f not in b: bad_req(f"{f} required")
    sku = db.skus.get(b["sku_id"])
    if not sku: not_found("sku not found")
    if b["test_type"] not in ("MECHANICAL", "FLAMMABILITY", "CHEMICAL"):
        bad_req("invalid test_type")
    if not isinstance(b["lab_name"], str): bad_req("lab_name required")
    if not isinstance(b["claimed_age_grade_months"], int):
        bad_req("claimed_age_grade_months must be int")
    if sku["safety_status"] not in ("NOT_TESTED", "FAILED"):
        raise ApiErr("ERR_INVALID_STATE", 409, "sku not testable")
    line = db.lines.get(sku["toy_line_id"])
    if line and line["status"] not in ("CONCEPT", "IN_DEVELOPMENT"):
        raise ApiErr("ERR_INVALID_STATE", 409, "line past development")
    t = {"id": new_id(), "sku_id": sku["id"], "test_type": b["test_type"],
         "lab_name": b["lab_name"], "claimed_age_grade_months": b["claimed_age_grade_months"],
         "result_age_grade_months": None, "validated_claims": None, "status": "SUBMITTED"}
    stamp_new(t)
    db.safety_tests[t["id"]] = t
    sku["safety_status"] = "TESTING"
    touch(sku)
    return ok_obj(st_json(t), 201)

@bp.get("/safety-tests/<tid>")
def get_test(tid):
    caller()
    t = db.safety_tests.get(tid)
    if not t: not_found("safety test not found")
    return ok_obj(st_json(t))

@bp.get("/safety-tests")
def list_tests():
    caller()
    items = list(db.safety_tests.values())
    for q in ("sku_id", "status"):
        v = request.args.get(q)
        if v is not None:
            items = [t for t in items if t[q] == v]
    return paged([st_json(t) for t in items])

@bp.post("/safety-tests/<tid>/record_result")
def record_result(tid):
    require_role("SafetyEngineer")
    t = db.safety_tests.get(tid)
    if not t: not_found("safety test not found")
    if t["status"] != "SUBMITTED":
        raise ApiErr("ERR_INVALID_STATE", 409, "test not SUBMITTED")
    b = get_body()
    for f in ("outcome", "result_age_grade_months", "validated_claims"):
        if f not in b: bad_req(f"{f} required")
    if b["outcome"] not in ("PASS", "FAIL"):
        bad_req("outcome must be PASS or FAIL")
    validate_age(b["result_age_grade_months"])
    if not isinstance(b["validated_claims"], list) or any(c not in CLAIMS for c in b["validated_claims"]):
        raise ApiErr("ERR_SAFETY_GATE", 422, "validated_claims outside enum")
    sku = db.skus.get(t["sku_id"])
    if b["outcome"] == "PASS":
        ok_age = b["result_age_grade_months"] <= sku["age_grade_months"]
        ok_claims = sorted(b["validated_claims"]) == sorted(sku["packaging_claims"])
        if not (ok_age and ok_claims):
            raise ApiErr("ERR_SAFETY_GATE", 422, "PASS result fails age/claims conformance")
        t["status"] = "PASSED"
        t["result_age_grade_months"] = b["result_age_grade_months"]
        t["validated_claims"] = list(b["validated_claims"])
        sku["safety_status"] = "PASSED"
        sku["tested_age_grade_months"] = b["result_age_grade_months"]
        sku["claims_validated"] = True
    else:
        t["status"] = "FAILED"
        t["result_age_grade_months"] = b["result_age_grade_months"]
        t["validated_claims"] = list(b["validated_claims"])
        sku["safety_status"] = "FAILED"
        sku["claims_validated"] = False
    touch(sku)
    touch(t)
    return ok_obj(st_json(t))
