from flask import Blueprint, request
from auth import caller, require_role
from store import db, stamp_new, touch, property_lifecycle
from util import ApiErr, ok_obj, paged, not_found, bad_req, new_id, get_body

bp = Blueprint("skus", __name__)

CLAIMS = {"CHOKING_HAZARD_FREE", "FLAME_RESISTANT", "BPA_FREE"}

def sku_json(s):
    return {"id": s["id"], "toy_line_id": s["toy_line_id"], "name": s["name"],
            "age_grade_months": s["age_grade_months"],
            "tested_age_grade_months": s["tested_age_grade_months"],
            "packaging_claims": s["packaging_claims"],
            "claims_validated": s["claims_validated"],
            "moq_units": s["moq_units"], "unit_cost_cents": s["unit_cost_cents"],
            "tooling_cost_cents": s["tooling_cost_cents"],
            "safety_status": s["safety_status"],
            "created_at": s["created_at"], "updated_at": s["updated_at"],
            "version": s["version"]}

def validate_age(age):
    if not isinstance(age, int) or age < 36 or age > 168:
        raise ApiErr("ERR_SAFETY_GATE", 422, "age_grade_months must be 36..168")

def validate_claims(claims):
    if not isinstance(claims, list) or any(c not in CLAIMS for c in claims):
        raise ApiErr("ERR_SAFETY_GATE", 422, "packaging_claims must be subset of declared enum")

def licensed_confidentiality(line):
    if line["brand_kind"] == "LICENSED":
        prop = db.properties.get(line["property_id"])
        if prop and property_lifecycle(prop) == "CONFIDENTIAL":
            raise ApiErr("ERR_CONFIDENTIALITY_BREACH", 422, "property is CONFIDENTIAL")

@bp.post("/skus")
def create_sku():
    require_role("BrandManager")
    b = get_body()
    req = ("toy_line_id", "name", "age_grade_months", "packaging_claims",
           "moq_units", "unit_cost_cents", "tooling_cost_cents")
    for f in req:
        if f not in b: bad_req(f"{f} required")
    line = db.lines.get(b["toy_line_id"])
    if not line: not_found("toy line not found")
    validate_age(b["age_grade_months"])
    validate_claims(b["packaging_claims"])
    licensed_confidentiality(line)
    if not isinstance(b["moq_units"], int) or b["moq_units"] < 1:
        bad_req("moq_units must be >= 1")
    for f in ("unit_cost_cents", "tooling_cost_cents"):
        if not isinstance(b[f], int) or b[f] < 0: bad_req(f"{f} must be non-negative int")
    if not isinstance(b["name"], str) or not b["name"]: bad_req("name required")
    s = {"id": new_id(), "toy_line_id": line["id"], "name": b["name"],
         "age_grade_months": b["age_grade_months"], "tested_age_grade_months": None,
         "packaging_claims": list(b["packaging_claims"]), "claims_validated": False,
         "moq_units": b["moq_units"], "unit_cost_cents": b["unit_cost_cents"],
         "tooling_cost_cents": b["tooling_cost_cents"], "safety_status": "NOT_TESTED"}
    stamp_new(s)
    db.skus[s["id"]] = s
    return ok_obj(sku_json(s), 201)

@bp.get("/skus/<sid>")
def get_sku(sid):
    caller()
    s = db.skus.get(sid)
    if not s: not_found("sku not found")
    return ok_obj(sku_json(s))

@bp.get("/skus")
def list_skus():
    caller()
    items = list(db.skus.values())
    tid = request.args.get("toy_line_id")
    if tid is not None:
        items = [s for s in items if s["toy_line_id"] == tid]
    return paged([sku_json(s) for s in items])

@bp.patch("/skus/<sid>")
def patch_sku(sid):
    require_role("BrandManager")
    s = db.skus.get(sid)
    if not s: not_found("sku not found")
    b = get_body()
    age_changed = False
    if "age_grade_months" in b:
        validate_age(b["age_grade_months"])
        if b["age_grade_months"] != s["age_grade_months"]:
            age_changed = True
        s["age_grade_months"] = b["age_grade_months"]
    if "packaging_claims" in b:
        validate_claims(b["packaging_claims"])
        s["packaging_claims"] = list(b["packaging_claims"])
    if age_changed and s["safety_status"] == "PASSED":
        # invalidate latest PASSED test
        passed = [t for t in db.safety_tests.values()
                  if t["sku_id"] == s["id"] and t["status"] == "PASSED"]
        if passed:
            latest = sorted(passed, key=lambda t: t["created_at"])[-1]
            latest["status"] = "INVALIDATED"
            touch(latest)
        s["safety_status"] = "FAILED"
        s["claims_validated"] = False
        line = db.lines.get(s["toy_line_id"])
        if line and line["status"] == "TOOLED":
            line["status"] = "IN_DEVELOPMENT"
            touch(line)
    touch(s)
    return ok_obj(sku_json(s))
