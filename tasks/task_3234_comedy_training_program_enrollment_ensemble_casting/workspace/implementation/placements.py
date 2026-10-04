"""PlacementEvaluation routes."""
from flask import Blueprint, request
from store import store, fresh, stamp
from middleware import auth, json_body, require_fields, pagination_params, require_student_owner
from response import success_obj, success_list
from errors import (
    not_found, invalid_request, raise_err, ERR_INVALID_STATE,
    ERR_PLACEMENT_NOT_ALLOWED, ERR_PORTFOLIO_SCORE_TOO_LOW, ERR_UNRECOGNIZED_INSTITUTION,
)
from services import granted_codes_for

bp = Blueprint("placements", __name__)

RECOGNIZED_INSTITUTIONS = ["iO", "UCB", "Groundlings", "Second City (other campus)"]
PORTFOLIO_PASS_THRESHOLD = 70


def _get_pe(pe_id):
    pe = store.placements.get(pe_id)
    if not pe:
        not_found("placement evaluation not found")
    return pe


@bp.post("/placement-evaluations")
def create_pe():
    user_id, role = auth(["Student", "PlacementOfficer"])
    body = json_body()
    require_fields(body, ["student_id", "target_level_id", "track", "prior_institution"])
    if role == "Student":
        require_student_owner(user_id, role, body["student_id"])
    student = store.students.get(body["student_id"])
    if not student:
        not_found("student not found")
    target = store.levels.get(body["target_level_id"])
    if not target:
        not_found("target level not found")
    if not target.get("allows_placement_bypass"):
        raise_err(ERR_PLACEMENT_NOT_ALLOWED, "target level does not allow placement bypass")
    if not isinstance(body.get("prior_institution"), str):
        invalid_request("prior_institution must be a string")
    portfolio = body.get("portfolio_score", 0)
    if not isinstance(portfolio, int) or isinstance(portfolio, bool) or not (0 <= portfolio <= 100):
        invalid_request("portfolio_score must be an integer 0..100")
    variant = "AUDITION_BYPASS" if body["prior_institution"] in RECOGNIZED_INSTITUTIONS else "PORTFOLIO_REVIEW"
    pe = fresh({
        "student_id": body["student_id"],
        "target_level_id": body["target_level_id"],
        "track": body["track"],
        "prior_institution": body["prior_institution"],
        "portfolio_score": portfolio,
        "variant": variant,
        "decision": "SUBMITTED",
        "granted_level_codes": [],
    })
    store.placements[pe["id"]] = pe
    return success_obj(pe, 201)


@bp.get("/placement-evaluations")
def list_pe():
    auth(["PlacementOfficer", "ProgramDirector"])
    limit, offset = pagination_params()
    items = list(store.placements.values())
    if request.args.get("student_id"):
        items = [x for x in items if x["student_id"] == request.args["student_id"]]
    if request.args.get("target_level_id"):
        items = [x for x in items if x["target_level_id"] == request.args["target_level_id"]]
    if request.args.get("decision"):
        items = [x for x in items if x["decision"] == request.args["decision"]]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/placement-evaluations/<pe_id>")
def get_pe(pe_id):
    user_id, role = auth(["PlacementOfficer", "ProgramDirector", "Student"])
    pe = _get_pe(pe_id)
    if role == "Student":
        require_student_owner(user_id, role, pe["student_id"])
    return success_obj(pe)


@bp.post("/placement-evaluations/<pe_id>/begin-review")
def begin_review(pe_id):
    auth(["PlacementOfficer"])
    pe = _get_pe(pe_id)
    if pe["decision"] not in ("SUBMITTED", "APPEALED"):
        raise_err(ERR_INVALID_STATE, "evaluation must be SUBMITTED or APPEALED")
    pe["decision"] = "UNDER_REVIEW"
    stamp(pe)
    return success_obj(pe)


@bp.post("/placement-evaluations/<pe_id>/grant")
def grant(pe_id):
    auth(["PlacementOfficer"])
    pe = _get_pe(pe_id)
    if pe["decision"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "evaluation must be UNDER_REVIEW")
    target = store.levels.get(pe["target_level_id"])
    if not target or not target.get("allows_placement_bypass"):
        raise_err(ERR_PLACEMENT_NOT_ALLOWED, "target level does not allow placement bypass")
    if pe["variant"] == "AUDITION_BYPASS":
        if pe["prior_institution"] not in RECOGNIZED_INSTITUTIONS:
            raise_err(ERR_UNRECOGNIZED_INSTITUTION, "institution not recognized")
    else:  # PORTFOLIO_REVIEW
        if pe.get("portfolio_score", 0) < PORTFOLIO_PASS_THRESHOLD:
            raise_err(ERR_PORTFOLIO_SCORE_TOO_LOW, "portfolio_score below threshold")
    pe["granted_level_codes"] = granted_codes_for(target) if target else []
    pe["decision"] = "GRANTED"
    stamp(pe)
    student = store.students.get(pe["student_id"])
    if student:
        merged = set(student.get("placement_credit_codes") or []) | set(pe["granted_level_codes"])
        student["placement_credit_codes"] = sorted(merged)
        stamp(student)
    return success_obj(pe)


@bp.post("/placement-evaluations/<pe_id>/deny")
def deny(pe_id):
    auth(["PlacementOfficer"])
    pe = _get_pe(pe_id)
    if pe["decision"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "evaluation must be UNDER_REVIEW")
    pe["decision"] = "DENIED"
    stamp(pe)
    return success_obj(pe)


@bp.post("/placement-evaluations/<pe_id>/appeal")
def appeal(pe_id):
    user_id, role = auth(["Student"])
    pe = _get_pe(pe_id)
    require_student_owner(user_id, role, pe["student_id"])
    if pe["decision"] != "DENIED":
        raise_err(ERR_INVALID_STATE, "evaluation must be DENIED")
    pe["decision"] = "APPEALED"
    stamp(pe)
    return success_obj(pe)
