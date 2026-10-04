"""Industry score variant endpoints."""

from decimal import Decimal

from flask import Blueprint, request

from core import (
    DB, new_record, store, touch, ok, ok_list, resolve_actor, score_model, score_variant,
    body_of, reject_unknown, require_fields, as_int, as_str, as_enum, as_number,
    read_pagination, paginate, ordered_rows, dec_out, half_up,
)
from errors import ApiError
from services import recompute_active_variant_count, variants_of_model

bp = Blueprint("score_variants", __name__)

ALL_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer", "ReasonCodeAdministrator", "ScoreConsumer",
]

INDUSTRIES = {"AUTO", "BANKCARD", "MORTGAGE", "PERSONAL_LOAN"}

ROUNDING_PENALTY_MAX = Decimal("0.05")

VARIANT_INPUTS = {
    "industry", "ref_score", "base_odds", "double_odds_points", "segment_width",
    "segment_offsets", "rounding_penalty_pct", "aggregate_weight_pct",
    "elongation_points", "cutoff_baseline",
}


@bp.post("/score-models/<model_id>/variants")
def create_variant(model_id):
    resolve_actor(request, ["ModelDeveloper"])
    model = score_model(model_id)
    body = body_of(request)
    reject_unknown(body, VARIANT_INPUTS)
    require_fields(body, list(VARIANT_INPUTS))

    industry = as_enum(body["industry"], INDUSTRIES, "industry")

    # Priority 12 (uniqueness) is evaluated before priority 14 (magnitude bounds).
    for existing in variants_of_model(model["id"]):
        if existing["industry"] == industry:
            raise ApiError("ERR_DUPLICATE_VARIANT_INDUSTRY")

    ref_score = as_int(body["ref_score"])
    base_odds = as_number(body["base_odds"])
    double_odds_points = as_int(body["double_odds_points"])
    segment_width = as_int(body["segment_width"])
    segment_offsets = body["segment_offsets"]
    rounding_penalty_pct = as_number(body["rounding_penalty_pct"])
    aggregate_weight_pct = as_number(body["aggregate_weight_pct"])
    elongation_points = as_int(body["elongation_points"])
    cutoff_baseline = as_int(body["cutoff_baseline"])

    if base_odds <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "base_odds must be strictly positive.")
    if double_odds_points < 1:
        raise ApiError("ERR_INVALID_REQUEST", "double_odds_points must be at least 1.")
    if segment_width < 1:
        raise ApiError("ERR_INVALID_REQUEST", "segment_width must be at least 1.")
    if not isinstance(segment_offsets, list) or len(segment_offsets) != 3:
        raise ApiError("ERR_INVALID_REQUEST", "segment_offsets must hold exactly three integers.")
    offsets = []
    for raw in segment_offsets:
        value = as_int(raw)
        if value < -40 or value > 40:
            raise ApiError("ERR_INVALID_REQUEST", "Each segment offset must lie between -40 and 40.")
        offsets.append(value)
    if rounding_penalty_pct < 0 or rounding_penalty_pct > ROUNDING_PENALTY_MAX:
        raise ApiError("ERR_INVALID_REQUEST", "rounding_penalty_pct must lie between 0 and 0.05.")
    if aggregate_weight_pct <= 0 or aggregate_weight_pct > 1:
        raise ApiError("ERR_INVALID_REQUEST", "aggregate_weight_pct must be greater than 0 and at most 1.")
    if elongation_points < 0:
        raise ApiError("ERR_INVALID_REQUEST", "elongation_points must be non-negative.")
    if cutoff_baseline < 300 or cutoff_baseline > 850:
        raise ApiError("ERR_INVALID_REQUEST", "cutoff_baseline must lie between 300 and 850.")

    rec = new_record()
    rec.update({
        "score_model_id": model["id"],
        "industry": industry,
        "ref_score": ref_score,
        "base_odds": float(half_up(base_odds, 6)),
        "double_odds_points": double_odds_points,
        "segment_width": segment_width,
        "segment_offsets": offsets,
        "rounding_penalty_pct": float(half_up(rounding_penalty_pct, 6)),
        "aggregate_weight_pct": float(half_up(aggregate_weight_pct, 6)),
        "elongation_points": elongation_points,
        "cutoff_baseline": cutoff_baseline,
        "status": "DRAFT",
        "distribution_shift_points": 0.0,
        "validated_at": None,
    })
    store("score_variants", rec)
    recompute_active_variant_count(model)
    return ok(rec, 201)


@bp.get("/score-variants/<variant_id>")
def get_variant(variant_id):
    resolve_actor(request, ALL_ROLES)
    return ok(score_variant(variant_id))


@bp.get("/score-variants")
def list_variants():
    resolve_actor(request, ALL_ROLES)
    limit, offset = read_pagination(request)
    rows = ordered_rows("score_variants")

    model_id = request.args.get("score_model_id")
    if model_id is not None:
        rows = [r for r in rows if r["score_model_id"] == model_id]
    industry = request.args.get("industry")
    if industry is not None:
        rows = [r for r in rows if r["industry"] == industry]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/score-variants/<variant_id>/release")
def release_variant(variant_id):
    resolve_actor(request, ["ModelDeveloper"])
    variant = score_variant(variant_id)
    body = body_of(request)
    reject_unknown(body, set())

    if variant["status"] not in ("DRAFT", "RECALLED"):
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    model = score_model(variant["score_model_id"])
    if model["status"] not in ("DEVELOPMENT", "RELEASED"):
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    variant["status"] = "RELEASED"
    touch(variant)
    recompute_active_variant_count(model)
    return ok(variant)


@bp.post("/score-variants/<variant_id>/recall")
def recall_variant(variant_id):
    resolve_actor(request, ["ModelDeveloper"])
    variant = score_variant(variant_id)
    body = body_of(request)
    reject_unknown(body, set())

    if variant["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    variant["status"] = "RECALLED"
    touch(variant)
    model = score_model(variant["score_model_id"])
    count = recompute_active_variant_count(model)
    if count == 0:
        for study in DB["validation_studies"].values():
            if study["score_model_id"] == model["id"] and study["status"] == "SCHEDULED":
                study["status"] = "BLOCKED"
                touch(study)
    return ok(variant)