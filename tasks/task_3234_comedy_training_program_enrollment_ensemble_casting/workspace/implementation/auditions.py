"""Audition routes."""
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request
from store import store, fresh, stamp
from middleware import auth, json_body, require_fields, pagination_params
from response import success_obj, success_list
from errors import not_found, invalid_request, raise_err, ERR_INVALID_STATE

bp = Blueprint("auditions", __name__)

WEIGHTS = {"scene_work": Decimal("0.4"), "characters": Decimal("0.25"), "musicality": Decimal("0.2"), "game": Decimal("0.15")}
TARGET_KINDS = {"COHORT", "ENSEMBLE", "TOURING"}


def _get(aid):
    a = store.auditions.get(aid)
    if not a:
        not_found("audition not found")
    return a


def compute_composite(rubric):
    total = Decimal("0")
    for dim, w in WEIGHTS.items():
        score = rubric.get(dim, 0)
        total += Decimal(str(score)) * w
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@bp.post("/auditions")
def create_audition():
    auth(["CastingDirector"])
    body = json_body()
    require_fields(body, ["student_id", "target_kind", "rubric_scores"])
    if body["student_id"] not in store.students:
        not_found("student not found")
    if body["target_kind"] not in TARGET_KINDS:
        invalid_request("invalid target_kind")
    if not isinstance(body["rubric_scores"], dict):
        invalid_request("rubric_scores must be an object")
    for k, v in body["rubric_scores"].items():
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= 10):
            invalid_request("rubric scores must be numbers 0..10")
    cpid = body.get("cohort_program_id")
    ecid = body.get("ensemble_cast_id")
    if body["target_kind"] == "COHORT":
        if not cpid or cpid not in store.cohorts:
            not_found("cohort program not found")
    else:
        if not ecid or ecid not in store.casts:
            not_found("ensemble cast not found")
    a = fresh({
        "student_id": body["student_id"],
        "target_kind": body["target_kind"],
        "cohort_program_id": cpid if body["target_kind"] == "COHORT" else None,
        "ensemble_cast_id": ecid if body["target_kind"] in ("ENSEMBLE", "TOURING") else None,
        "rubric_scores": dict(body["rubric_scores"]),
        "composite_score": None,
        "outcome": "SCHEDULED",
    })
    store.auditions[a["id"]] = a
    return success_obj(a, 201)


@bp.get("/auditions")
def list_auditions():
    auth(["CastingDirector", "ProgramDirector"])
    limit, offset = pagination_params()
    items = list(store.auditions.values())
    for f in ("student_id", "target_kind", "cohort_program_id", "ensemble_cast_id", "outcome"):
        v = request.args.get(f)
        if v is not None:
            items = [x for x in items if x.get(f) == v]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/auditions/<aid>")
def get_audition(aid):
    auth(["CastingDirector", "ProgramDirector"])
    return success_obj(_get(aid))


@bp.post("/auditions/<aid>/evaluate")
def evaluate(aid):
    auth(["CastingDirector"])
    a = _get(aid)
    if a["outcome"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "audition must be SCHEDULED")
    a["composite_score"] = compute_composite(a["rubric_scores"])
    a["outcome"] = "EVALUATED"
    stamp(a)
    return success_obj(a)


@bp.post("/auditions/<aid>/waitlist")
def waitlist(aid):
    auth(["CastingDirector"])
    a = _get(aid)
    if a["outcome"] != "EVALUATED":
        raise_err(ERR_INVALID_STATE, "audition must be EVALUATED")
    a["outcome"] = "WAITLISTED"
    stamp(a)
    return success_obj(a)


@bp.post("/auditions/<aid>/reject")
def reject(aid):
    auth(["CastingDirector"])
    a = _get(aid)
    if a["outcome"] not in ("EVALUATED", "WAITLISTED"):
        raise_err(ERR_INVALID_STATE, "audition must be EVALUATED or WAITLISTED")
    a["outcome"] = "REJECTED"
    stamp(a)
    return success_obj(a)
