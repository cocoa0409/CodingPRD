"""Trade-in appraisals: dual-variant valuation and the negotiation loop."""
from flask import Blueprint

import calculations as calc
import helpers
from helpers import as_enum, as_int, as_str, auth, body, fail, ok, req, require_role, identity_entity
import storage
from storage import STORES, new_record, public, sort_created, touch

bp = Blueprint("appraisals", __name__)

CONDITION_GRADES = ("A", "B", "C", "D")
POLICIES = ("BOOK", "MARKET")
READ_ROLES = ("CorporateAdmin", "DistributorManager", "CourseManager")

_TRANSITIONS = {
    ("VALUED", "ACCEPTED"): "CourseManager",
    ("VALUED", "DISPUTED"): "CourseManager",
    ("DISPUTED", "VALUED"): "DistributorManager",
    ("DISPUTED", "VOIDED"): "DistributorManager",
}


def revert_appraisals(lease_id):
    """Lease revert/cancel compensation (also Cascade C2 link 3): appraisals in
    VALUED or DISPUTED become VOIDED; appraisals in ACCEPTED step back to VALUED."""
    for ap in STORES["appraisals"].values():
        if ap["lease_id"] != lease_id:
            continue
        if ap["status"] in ("VALUED", "DISPUTED"):
            ap["status"] = "VOIDED"
            touch(ap)
        elif ap["status"] == "ACCEPTED":
            ap["status"] = "VALUED"
            touch(ap)


def _revalue(ap):
    model = STORES["models"][ap["model_id"]]
    vals = calc.trade_in_valuation(model, ap["hours"], ap["condition_grade"], ap["policy"])
    ap["book_value_cents"] = vals["book_value_cents"]
    ap["market_value_cents"] = vals["market_value_cents"]
    ap["valued_cents"] = vals["valued_cents"]


@bp.post("/appraisals")
def create_appraisal():
    role, uid = auth()
    require_role(role, ("DistributorManager",))
    identity_entity(role, uid)
    b = body()
    model_id = as_str(req(b, "model_id"), "model_id")
    helpers.get_or_404("models", model_id, "model")
    lease_id = as_str(req(b, "lease_id"), "lease_id")
    lease = helpers.get_or_404("leases", lease_id, "lease")
    if lease["distributor_id"] != uid:
        fail("ERR_FORBIDDEN_OWNERSHIP", "lease belongs to another distributor")
    external_serial = as_str(req(b, "external_serial"), "external_serial")
    hours = as_int(req(b, "hours"), "hours")
    if hours < 0:
        fail("ERR_INVALID_REQUEST", "hours must be >= 0")
    grade = as_enum(req(b, "condition_grade"), "condition_grade", CONDITION_GRADES)
    policy = as_enum(req(b, "policy"), "policy", POLICIES)
    if lease["status"] not in ("DRAFT", "SPEC_REVIEW"):
        fail("ERR_INVALID_STATE", "appraisals may be opened only against a DRAFT or SPEC_REVIEW lease")
    rec = new_record("appraisals", {
        "lease_id": lease_id,
        "model_id": model_id,
        "external_serial": external_serial,
        "hours": hours,
        "condition_grade": grade,
        "policy": policy,
        "book_value_cents": None,
        "market_value_cents": None,
        "valued_cents": None,
        "status": "VALUED",
    })
    _revalue(rec)
    return ok(public(rec), 201)


@bp.get("/appraisals/<aid>")
def get_appraisal(aid):
    role, uid = auth()
    require_role(role, READ_ROLES)
    ap = helpers.get_or_404("appraisals", aid, "appraisal")
    return ok(public(ap))


@bp.get("/appraisals")
def list_appraisals():
    role, uid = auth()
    require_role(role, READ_ROLES)
    recs = helpers.apply_filters(sort_created(STORES["appraisals"].values()), {
        "lease_id": "lease_id",
        "model_id": "model_id",
        "status": "status",
    })
    return helpers.paginate(recs)


@bp.post("/appraisals/<aid>/transition")
def transition_appraisal(aid):
    role, uid = auth()
    require_role(role, ("DistributorManager", "CourseManager"))
    identity_entity(role, uid)
    ap = helpers.get_or_404("appraisals", aid, "appraisal")
    lease = STORES["leases"][ap["lease_id"]]
    if role == "DistributorManager" and lease["distributor_id"] != uid:
        fail("ERR_FORBIDDEN_OWNERSHIP", "appraisal lease belongs to another distributor")
    if role == "CourseManager" and lease["course_id"] != uid:
        fail("ERR_FORBIDDEN_OWNERSHIP", "appraisal lease belongs to another course")
    b = body()
    to = as_str(req(b, "to"), "to")
    # Optional revaluation overrides are shape-checked when present.
    new_hours = None
    new_grade = None
    new_policy = None
    if "hours" in b and b["hours"] is not None:
        new_hours = as_int(b["hours"], "hours")
        if new_hours < 0:
            fail("ERR_INVALID_REQUEST", "hours must be >= 0")
    if "condition_grade" in b and b["condition_grade"] is not None:
        new_grade = as_enum(b["condition_grade"], "condition_grade", CONDITION_GRADES)
    if "policy" in b and b["policy"] is not None:
        new_policy = as_enum(b["policy"], "policy", POLICIES)
    key = (ap["status"], to)
    if key not in _TRANSITIONS:
        fail("ERR_INVALID_STATE", "appraisal cannot move from " + ap["status"] + " to " + str(to))
    if role != _TRANSITIONS[key]:
        fail("ERR_UNAUTHORIZED", "role " + role + " may not drive appraisal to " + to)

    if key == ("VALUED", "ACCEPTED"):
        if lease["status"] not in ("DRAFT", "SPEC_REVIEW"):
            fail("ERR_INVALID_STATE", "owning lease is no longer in DRAFT or SPEC_REVIEW")
    elif key == ("DISPUTED", "VALUED"):
        # Overrides apply first, then the full valuation re-runs.
        if new_hours is not None:
            ap["hours"] = new_hours
        if new_grade is not None:
            ap["condition_grade"] = new_grade
        if new_policy is not None:
            ap["policy"] = new_policy
        _revalue(ap)

    ap["status"] = to
    touch(ap)
    return ok(public(ap))
