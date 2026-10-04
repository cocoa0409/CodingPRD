"""Supplier registration and lifecycle transitions (PRD section 3.1)."""
from flask import Blueprint

from auth import authenticate, authorize
from db import STORE, new_resource, public, touch
from envelope import ok
from errors import fail
from validate import INGREDIENT_CATEGORIES, get_body, req_enum, req_str

bp = Blueprint("suppliers", __name__)

READ_ROLES = ("SourcingManager", "SustainabilityAuditor", "AuditVerifier",
              "DairyProgramManager", "FlavorManager", "IndependentBoardMember",
              "ParentOpsController", "FranchiseAdmin")


def get_supplier(sid):
    s = STORE["suppliers"].get(sid)
    if s is None:
        fail("ERR_SUPPLIER_NOT_FOUND", "Supplier id does not exist")
    return s


@bp.post("/suppliers")
def create_supplier():
    _, role = authenticate()
    authorize(role, ("SourcingManager",))
    body = get_body()
    name = req_str(body, "name")
    country = req_str(body, "country_code")
    category = req_enum(body, "ingredient_category", INGREDIENT_CATEGORIES)
    r = new_resource()
    r.update({
        "name": name,
        "country_code": country,
        "ingredient_category": category,
        "status": "PROSPECT",
        "social_criteria_score": None,
    })
    STORE["suppliers"][r["id"]] = r
    return ok(public(r), 201)


@bp.get("/suppliers/<sid>")
def read_supplier(sid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    return ok(public(get_supplier(sid)))


def _lifecycle(sid, allowed_from, target):
    _, role = authenticate()
    authorize(role, ("SourcingManager",))
    s = get_supplier(sid)
    if s["status"] not in allowed_from:
        fail("ERR_INVALID_STATE",
             "Supplier in %s cannot move to %s" % (s["status"], target))
    s["status"] = target
    touch(s)
    return ok(public(s))


@bp.post("/suppliers/<sid>/suspend")
def suspend_supplier(sid):
    # Manual suspension preserves commitments and certifications untouched.
    return _lifecycle(sid, ("APPROVED",), "SUSPENDED")


@bp.post("/suppliers/<sid>/reinstate")
def reinstate_supplier(sid):
    # Manual reinstate; LAPSED commitments are NOT resurrected.
    return _lifecycle(sid, ("SUSPENDED",), "APPROVED")


@bp.post("/suppliers/<sid>/terminate")
def terminate_supplier(sid):
    return _lifecycle(sid, ("PROSPECT", "APPROVED", "SUSPENDED"), "TERMINATED")
