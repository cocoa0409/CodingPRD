"""Score model version endpoints: creation, lifecycle and the release cascade."""

from flask import Blueprint, request

from core import (
    DB, ORDER, new_record, store, touch, ok, ok_list, resolve_actor, score_model,
    body_of, reject_unknown, require_fields, as_int, as_str, as_enum, as_bool,
    read_pagination, paginate, ordered_rows, check_occ,
)
from errors import ApiError
from services import (
    precompute_cascade_depth, recompute_active_variant_count,
    variants_of_model, model_risk_report_filed, c7_release_predecessor,
)

bp = Blueprint("score_models", __name__)

ALL_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer", "ReasonCodeAdministrator", "ScoreConsumer",
]

FAMILIES = {"FICO_CORE", "VANTAGE_STYLE"}


@bp.post("/score-models")
def create_score_model():
    resolve_actor(request, ["ModelDeveloper"])
    body = body_of(request)
    reject_unknown(body, {"family_code", "version_label", "predecessor_model_id",
                          "min_input_count", "score_floor", "score_ceiling"})
    require_fields(body, ["family_code", "version_label", "min_input_count"])

    family_code = as_enum(body["family_code"], FAMILIES, "family_code")
    version_label = as_str(body["version_label"], "version_label")
    min_input_count = as_int(body["min_input_count"])
    if min_input_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", "min_input_count must be at least 1.")
    score_floor = as_int(body["score_floor"]) if "score_floor" in body else 300
    score_ceiling = as_int(body["score_ceiling"]) if "score_ceiling" in body else 850
    if score_floor > score_ceiling:
        raise ApiError("ERR_INVALID_REQUEST", "score_floor must not exceed score_ceiling.")

    for existing in DB["score_models"].values():
        if existing["family_code"] == family_code and existing["version_label"] == version_label:
            raise ApiError("ERR_DUPLICATE_VERSION_LABEL")

    predecessor_id = body.get("predecessor_model_id")
    if predecessor_id is not None:
        predecessor = score_model(predecessor_id)
        if predecessor["family_code"] != family_code:
            raise ApiError("ERR_INVALID_REQUEST", "predecessor_model_id must share the family_code.")
        if predecessor["status"] == "RETIRED":
            raise ApiError("ERR_INVALID_REQUEST", "predecessor_model_id names a RETIRED version.")
        # A chain that re-enters a version is rejected at creation.
        seen = set()
        cursor = predecessor
        while cursor is not None:
            if cursor["id"] in seen:
                raise ApiError("ERR_INVALID_REQUEST", "The predecessor chain re-enters a version.")
            seen.add(cursor["id"])
            cursor = DB["score_models"].get(cursor.get("predecessor_model_id"))

    rec = new_record()
    rec.update({
        "family_code": family_code,
        "version_label": version_label,
        "predecessor_model_id": predecessor_id,
        "status": "DEVELOPMENT",
        "released_at": None,
        "retired_at": None,
        "min_input_count": min_input_count,
        "score_floor": score_floor,
        "score_ceiling": score_ceiling,
        "active_variant_count": 0,
        "cascade_depth": 0,
    })
    rec["cascade_depth"] = precompute_cascade_depth(rec)
    store("score_models", rec)
    return ok(rec, 201)


@bp.get("/score-models/<model_id>")
def get_score_model(model_id):
    resolve_actor(request, ALL_ROLES)
    return ok(score_model(model_id))


@bp.get("/score-models")
def list_score_models():
    resolve_actor(request, ALL_ROLES)
    limit, offset = read_pagination(request)
    rows = ordered_rows("score_models")

    family = request.args.get("family_code")
    if family is not None:
        rows = [r for r in rows if r["family_code"] == family]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    predecessor = request.args.get("predecessor_model_id")
    if predecessor is not None:
        rows = [r for r in rows if r.get("predecessor_model_id") == predecessor]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/score-models/<model_id>/release")
def release_model(model_id):
    resolve_actor(request, ["ModelDeveloper"])
    rec = score_model(model_id)
    body = body_of(request)
    reject_unknown(body, {"expected_model_version"})

    if rec["status"] != "DEVELOPMENT":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    # Gate order per PRD §3.1: documentation, released variant, predecessor edge.
    if not model_risk_report_filed(rec):
        raise ApiError("ERR_MODEL_DOC_REQUIRED")
    if not any(v["status"] == "RELEASED" for v in variants_of_model(rec["id"])):
        raise ApiError("ERR_NO_RELEASED_VARIANT")
    predecessor_id = rec.get("predecessor_model_id")
    if predecessor_id is not None:
        predecessor = DB["score_models"].get(predecessor_id)
        if predecessor is None or predecessor["status"] not in ("RELEASED", "DEPRECATED"):
            raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    check_occ(rec, body, "expected_model_version")

    from core import now_iso
    rec["status"] = "RELEASED"
    rec["released_at"] = now_iso()

    # Hop 1 of C7: designated predecessor and every model naming it supersede.
    c7_release_predecessor(rec, predecessor_id)

    rec["active_variant_count"] = sum(1 for v in variants_of_model(rec["id"]) if v["status"] == "RELEASED")
    rec["cascade_depth"] = precompute_cascade_depth(rec)
    touch(rec)
    return ok(rec)


@bp.post("/score-models/<model_id>/deprecate")
def deprecate_model(model_id):
    resolve_actor(request, ["ComplianceOfficer"])
    rec = score_model(model_id)
    body = body_of(request)
    reject_unknown(body, {"expected_model_version"})

    if rec["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    active_variant_ids = {v["id"] for v in variants_of_model(rec["id"])}
    for license_rec in DB["licenses"].values():
        if license_rec["score_variant_id"] in active_variant_ids and license_rec["status"] == "ACTIVE":
            raise ApiError("ERR_DEPRECATION_BLOCKED")

    check_occ(rec, body, "expected_model_version")
    rec["status"] = "DEPRECATED"
    touch(rec)
    return ok(rec)


@bp.post("/score-models/<model_id>/reopen")
def reopen_model(model_id):
    resolve_actor(request, ["ComplianceOfficer"])
    rec = score_model(model_id)
    body = body_of(request)
    reject_unknown(body, {"expected_model_version"})

    if rec["status"] != "DEPRECATED":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    if not model_risk_report_filed(rec):
        raise ApiError("ERR_MODEL_DOC_REQUIRED")

    check_occ(rec, body, "expected_model_version")

    from core import now_iso
    rec["status"] = "RELEASED"
    rec["released_at"] = now_iso()
    for study in DB["validation_studies"].values():
        if study["score_model_id"] == rec["id"] and study["status"] == "BLOCKED":
            study["status"] = "SCHEDULED"
            touch(study)
    touch(rec)
    return ok(rec)


@bp.post("/score-models/<model_id>/retire")
def retire_model(model_id):
    resolve_actor(request, ["ComplianceOfficer"])
    rec = score_model(model_id)
    body = body_of(request)
    reject_unknown(body, {"expected_model_version"})

    if rec["status"] != "DEPRECATED":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    for refset in DB["reference_sets"].values():
        if refset["score_model_id"] == rec["id"] and refset["status"] != "RECONCILED":
            raise ApiError("ERR_RETIREMENT_BLOCKED")

    check_occ(rec, body, "expected_model_version")

    from core import now_iso
    rec["status"] = "RETIRED"
    rec["retired_at"] = now_iso()
    touch(rec)
    return ok(rec)