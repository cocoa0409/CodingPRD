"""Validation study endpoints: scheduling, running and the completion cascades."""

from decimal import Decimal

from flask import Blueprint, request

from core import (
    DB, ORDER, new_record, store, touch, ok, ok_list, resolve_actor, score_model,
    archive_sample, validation_study, body_of, reject_unknown, require_fields,
    as_str, as_enum, read_pagination, paginate, ordered_rows, check_occ, dec_out,
)
from errors import ApiError
from calculations import composite_scores, disparate_impact_ratio_ppm
from services import (
    c8_hop1, c8_hop2, c8_hop3, c9_replay, stamp_validated_at,
    non_voided_reason_codes_in_use, variants_of_model,
)

bp = Blueprint("validation_studies", __name__)

READ_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer",
]

PATHS = {"PROTECTED_CLASS", "CROSS_BUREAU"}

PROTECTED_REQUIRED_CODES = [
    "CREDIT-DUAL-DECISION-V1-SEGMENT_ZERO-STUDY-PRIMARY",
    "CREDIT-DUAL-DECISION-V1-UNDECIDED-ESCALATED-SECONDARY",
]
CROSS_BUREAU_REQUIRED_CODES = [
    "CREDIT-DUAL-DECISION-V1-BUREAU_DISAGREEMENT-TERTIARY",
    "CREDIT-DUAL-DECISION-V1-RECONCILIATION_SPREAD-STUDY-PRIMARY",
]


def required_codes_for(study_path):
    return list(PROTECTED_REQUIRED_CODES if study_path == "PROTECTED_CLASS"
                else CROSS_BUREAU_REQUIRED_CODES)


def active_reason_code_on_model(model_id):
    variant_ids = {v["id"] for v in variants_of_model(model_id)}
    for code in DB["reason_codes"].values():
        if code["score_variant_id"] in variant_ids and code["status"] == "ACTIVE":
            return True
    return False


@bp.post("/validation-studies")
def create_study():
    resolve_actor(request, ["ValidationAnalyst"])
    body = body_of(request)
    reject_unknown(body, {"score_model_id", "sample_id", "study_path", "performed_by"})
    require_fields(body, ["score_model_id", "sample_id", "study_path", "performed_by"])

    model = score_model(as_str(body["score_model_id"], "score_model_id"))
    sample = archive_sample(as_str(body["sample_id"], "sample_id"))
    study_path = as_enum(body["study_path"], PATHS, "study_path")
    performed_by = as_str(body["performed_by"], "performed_by")

    if sample["score_model_id"] != model["id"]:
        raise ApiError("ERR_SAMPLE_MODEL_MISMATCH")

    rec = new_record()
    rec.update({
        "score_model_id": model["id"],
        "sample_id": sample["id"],
        "study_path": study_path,
        "status": "SCHEDULED",
        "touched_model_ids": [model["id"]],
        "disparate_impact_ratio_ppm": None,
        "reconciliation_variance": None,
        "performed_by": performed_by,
        "finalized_by": None,
        "evidence_ref": None,
        "model_doc_id": None,
        "required_reason_codes": required_codes_for(study_path),
    })
    store("validation_studies", rec)
    return ok(rec, 201)


@bp.get("/validation-studies/<study_id>")
def get_study(study_id):
    resolve_actor(request, READ_ROLES)
    return ok(validation_study(study_id))


@bp.get("/validation-studies")
def list_studies():
    resolve_actor(request, READ_ROLES)
    limit, offset = read_pagination(request)
    rows = ordered_rows("validation_studies")

    for param, field in (("score_model_id", "score_model_id"), ("sample_id", "sample_id"),
                         ("model_doc_id", "model_doc_id"), ("study_path", "study_path"),
                         ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/validation-studies/<study_id>/run")
def run_study(study_id):
    resolve_actor(request, ["ValidationAnalyst"])
    study = validation_study(study_id)
    body = body_of(request)
    reject_unknown(body, {"expected_study_version"})

    if study["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    model = score_model(study["score_model_id"])
    sample = archive_sample(study["sample_id"])

    if sample["record_count"] < model["min_input_count"]:
        raise ApiError("ERR_SAMPLE_TOO_SMALL")
    if study["study_path"] == "PROTECTED_CLASS" and not active_reason_code_on_model(model["id"]):
        raise ApiError("ERR_REASON_CODE_MISSING")
    if study["study_path"] == "CROSS_BUREAU" and sample["sample_kind"] != "VALIDATION":
        raise ApiError("ERR_SAMPLE_KIND_MISMATCH")

    check_occ(study, body, "expected_study_version")

    weighted = 0.0
    unweighted = 0.0
    if study["study_path"] == "PROTECTED_CLASS":
        variant_ids = {v["id"] for v in variants_of_model(model["id"])}
        counts = {True: [0, 0], False: [0, 0]}
        for posting in ordered_rows("score_results"):
            if posting.get("_voided") or posting["score_variant_id"] not in variant_ids:
                continue
            consumer_rec = DB["consumers"].get(posting["consumer_id"])
            if consumer_rec is None:
                continue
            group = counts[bool(consumer_rec["is_protected_class"])]
            if posting["decision"] == "APPROVE":
                group[0] += 1
            elif posting["decision"] == "DECLINE":
                group[1] += 1
        study["disparate_impact_ratio_ppm"] = disparate_impact_ratio_ppm(
            {True: tuple(counts[True]), False: tuple(counts[False])})
        study["reconciliation_variance"] = None
    else:
        variant_ids = {v["id"] for v in variants_of_model(model["id"])}
        captured = []
        for posting in ordered_rows("score_results"):
            if posting.get("_voided") or posting["score_variant_id"] not in variant_ids:
                continue
            variant = DB["score_variants"][posting["score_variant_id"]]
            captured.append({
                "effective_score": posting["effective_score"],
                "variant_weight_pct": variant["aggregate_weight_pct"],
            })
        result = composite_scores(captured)
        weighted = result["weighted_composite"]
        unweighted = result["unweighted_composite"]
        study["reconciliation_variance"] = result["reconciliation_variance"]
        study["disparate_impact_ratio_ppm"] = None

    study["status"] = "VALIDATION_COMPLETE"

    # Cascade C8
    c8_hop1(study)
    stamp_validated_at(study)
    c8_hop2(study)

    touch(study)
    # PRD §2.2: a modify operation returns the updated resource object, so the
    # study carries its own id/version alongside the freshly measured composites.
    payload = dict(study)
    payload.update({
        "weighted_composite": weighted,
        "unweighted_composite": unweighted,
    })
    return ok(payload)


@bp.post("/validation-studies/<study_id>/acknowledge")
def acknowledge_study(study_id):
    resolve_actor(request, ["FairLendingOfficer"])
    study = validation_study(study_id)
    body = body_of(request)
    reject_unknown(body, {"finalized_by", "evidence_ref", "expected_study_version"})
    require_fields(body, ["finalized_by", "evidence_ref"])

    if study["status"] != "VALIDATION_COMPLETE":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    finalized_by = as_str(body["finalized_by"], "finalized_by")
    evidence_ref = as_str(body["evidence_ref"], "evidence_ref")

    if finalized_by == study["performed_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    available = non_voided_reason_codes_in_use()
    for code in study["required_reason_codes"]:
        if code not in available:
            raise ApiError("ERR_REASON_CODE_VIOLATION")

    check_occ(study, body, "expected_study_version")

    study["finalized_by"] = finalized_by
    study["evidence_ref"] = evidence_ref
    c8_hop3(study)
    touch(study)
    return ok(study)


@bp.post("/validation-studies/<study_id>/revert")
def revert_study(study_id):
    resolve_actor(request, ["ValidationAnalyst"])
    study = validation_study(study_id)
    body = body_of(request)
    reject_unknown(body, {"expected_study_version"})

    if study["status"] != "VALIDATION_COMPLETE":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    if study["finalized_by"] is not None:
        raise ApiError("ERR_STUDY_ALREADY_FINALIZED")

    check_occ(study, body, "expected_study_version")

    study["status"] = "SCHEDULED"
    study["disparate_impact_ratio_ppm"] = None
    study["reconciliation_variance"] = None
    c9_replay(study)
    touch(study)
    return ok(study)


@bp.post("/validation-studies/<study_id>/compensate")
def compensate_study(study_id):
    resolve_actor(request, ["FairLendingOfficer"])
    study = validation_study(study_id)
    body = body_of(request)
    reject_unknown(body, {"expected_study_version"})

    if study["status"] != "VALIDATION_COMPLETE":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    if study["finalized_by"] is None:
        raise ApiError("ERR_STUDY_NOT_FINALIZED")

    check_occ(study, body, "expected_study_version")

    study["status"] = "COMPENSATED"
    study["disparate_impact_ratio_ppm"] = None
    study["reconciliation_variance"] = None
    # The compensating action conserves the scoring ledger: no posting changes.
    touch(study)
    return ok(study)