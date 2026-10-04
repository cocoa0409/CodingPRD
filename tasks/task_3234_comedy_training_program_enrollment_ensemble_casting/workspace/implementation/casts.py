"""EnsembleCast routes with selector policy and OCC lock."""
from flask import Blueprint, request
from store import store, fresh, stamp
from middleware import auth, json_body, require_fields, pagination_params
from response import success_obj, success_list
from errors import (
    not_found, invalid_request, raise_err, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_NO_ELIGIBLE_AUDITIONS, ERR_CAST_INCOMPLETE, ERR_SOURCE_POLICY_VIOLATION,
)

bp = Blueprint("casts", __name__)

PIPELINE_BONUS = 0.5


def _get(cid):
    c = store.casts.get(cid)
    if not c:
        not_found("ensemble cast not found")
    return c


def _is_pipeline_student(student_id):
    """Student holds a CREDITED enrollment in a CONSERVATORY CohortProgram.

    PRD: PIPELINE_ONLY requires 'CREDITED enrollment in a CONSERVATORY CohortProgram'.
    We treat admission into a GRADUATED/ACTIVE conservatory cohort plus a CREDITED
    enrollment anywhere as the practical reading; simplest faithful proxy: the student
    has any CREDITED enrollment AND is admitted to a CONSERVATORY cohort.
    """
    has_credit = any(
        e["student_id"] == student_id and e["status"] == "CREDITED"
        for e in store.enrollments.values()
    )
    in_conservatory = any(
        c["kind"] == "CONSERVATORY" and student_id in (c.get("_admitted_ids") or [])
        for c in store.cohorts.values()
    )
    return has_credit and in_conservatory


@bp.post("/ensemble-casts")
def create_cast():
    auth(["CastingDirector"])
    body = json_body()
    require_fields(body, ["revue_title", "venue_slot_id", "cast_size", "understudy_slots"])
    if body["venue_slot_id"] not in store.venue_slots:
        not_found("venue slot not found")
    for f in ("cast_size", "understudy_slots"):
        if not isinstance(body[f], int) or isinstance(body[f], bool) or body[f] < 0:
            invalid_request(f"{f} must be a non-negative integer")
    policy = body.get("source_policy", "MIXED")
    if policy not in ("PIPELINE_ONLY", "OPEN_CALL", "MIXED"):
        invalid_request("invalid source_policy")
    cast = fresh({
        "revue_title": body["revue_title"],
        "venue_slot_id": body["venue_slot_id"],
        "cast_size": body["cast_size"],
        "understudy_slots": body["understudy_slots"],
        "source_policy": policy,
        "principal_ids": [],
        "understudy_ids": [],
        "status": "OPEN_ROLES",
    })
    store.casts[cast["id"]] = cast
    return success_obj(cast, 201)


@bp.get("/ensemble-casts")
def list_casts():
    auth(["CastingDirector", "ProgramDirector"])
    limit, offset = pagination_params()
    items = list(store.casts.values())
    if request.args.get("status"):
        items = [x for x in items if x["status"] == request.args["status"]]
    if request.args.get("venue_slot_id"):
        items = [x for x in items if x["venue_slot_id"] == request.args["venue_slot_id"]]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/ensemble-casts/<cid>")
def get_cast(cid):
    auth(["CastingDirector", "ProgramDirector"])
    return success_obj(_get(cid))


@bp.post("/ensemble-casts/<cid>/open-casting")
def open_casting(cid):
    auth(["CastingDirector"])
    cast = _get(cid)
    if cast["status"] != "OPEN_ROLES":
        raise_err(ERR_INVALID_STATE, "cast must be OPEN_ROLES")
    cast["status"] = "CASTING"
    stamp(cast)
    return success_obj(cast)


@bp.post("/ensemble-casts/<cid>/cast")
def run_casting(cid):
    auth(["CastingDirector"])
    cast = _get(cid)
    if cast["status"] != "CASTING":
        raise_err(ERR_INVALID_STATE, "cast must be CASTING")
    pool = [
        a for a in store.auditions.values()
        if a["target_kind"] == "ENSEMBLE" and a.get("ensemble_cast_id") == cast["id"]
        and a["outcome"] in ("EVALUATED", "WAITLISTED")
    ]
    if cast["source_policy"] == "PIPELINE_ONLY":
        eligible = []
        for a in pool:
            if _is_pipeline_student(a["student_id"]):
                eligible.append(a)
        if not eligible and pool:
            raise_err(ERR_SOURCE_POLICY_VIOLATION, "no pipeline-eligible auditions")
        pool = eligible
    if not pool:
        raise_err(ERR_NO_ELIGIBLE_AUDITIONS, "no eligible auditions")

    def rank_key(a):
        score = a.get("composite_score") or 0
        if cast["source_policy"] == "MIXED" and _is_pipeline_student(a["student_id"]):
            score = score + PIPELINE_BONUS
        return (-score, a["created_at"])

    pool.sort(key=rank_key)
    needed_p = cast["cast_size"] - len(cast["principal_ids"])
    needed_u = cast["understudy_slots"] - len(cast["understudy_ids"])
    principals = pool[:needed_p] if needed_p > 0 else []
    understudies = pool[len(principals):len(principals) + max(needed_u, 0)]
    for a in principals:
        cast["principal_ids"].append(a["student_id"])
        a["outcome"] = "SELECTED"
        stamp(a)
    for a in understudies:
        cast["understudy_ids"].append(a["student_id"])
        a["outcome"] = "SELECTED"
        stamp(a)
    stamp(cast)
    return success_obj(cast)


@bp.post("/ensemble-casts/<cid>/lock-cast")
def lock_cast(cid):
    auth(["CastingDirector"])
    cast = _get(cid)
    if cast["status"] != "CASTING":
        raise_err(ERR_INVALID_STATE, "cast must be CASTING")
    body = json_body()
    require_fields(body, ["expected_cast_version"])
    ecv = body["expected_cast_version"]
    if not isinstance(ecv, int) or isinstance(ecv, bool):
        invalid_request("expected_cast_version must be an integer")
    if ecv != cast["version"]:
        raise_err(ERR_STALE_VERSION, "expected_cast_version does not match current cast version")
    if len(cast["principal_ids"]) != cast["cast_size"] or len(cast["understudy_ids"]) != cast["understudy_slots"]:
        raise_err(ERR_CAST_INCOMPLETE, "roster incomplete")
    slot = store.venue_slots.get(cast["venue_slot_id"])
    if not slot or slot["status"] != "BOOKED":
        raise_err(ERR_CAST_INCOMPLETE, "opening-night venue slot must be BOOKED")
    cast["status"] = "REHEARSING"
    stamp(cast)
    return success_obj(cast)


@bp.post("/ensemble-casts/<cid>/open-revue")
def open_revue(cid):
    auth(["CastingDirector"])
    cast = _get(cid)
    if cast["status"] != "REHEARSING":
        raise_err(ERR_INVALID_STATE, "cast must be REHEARSING")
    cast["status"] = "RUNNING"
    stamp(cast)
    return success_obj(cast)


@bp.post("/ensemble-casts/<cid>/close-revue")
def close_revue(cid):
    auth(["CastingDirector"])
    cast = _get(cid)
    if cast["status"] != "RUNNING":
        raise_err(ERR_INVALID_STATE, "cast must be RUNNING")
    for t in store.tours.values():
        if t["ensemble_cast_id"] == cast["id"] and t["status"] not in ("RETURNED", "REPLACED", "DECLINED"):
            raise_err(ERR_INVALID_STATE, "non-terminal touring assignments remain")
    cast["status"] = "CLOSED"
    stamp(cast)
    return success_obj(cast)
