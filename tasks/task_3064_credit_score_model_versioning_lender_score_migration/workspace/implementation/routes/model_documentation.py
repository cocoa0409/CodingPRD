"""Regulatory documentation endpoints."""

from flask import Blueprint, request

from core import (
    DB, new_record, store, touch, ok, ok_list, resolve_actor, score_model,
    model_documentation, validation_study, body_of, reject_unknown, require_fields,
    as_str, as_enum, read_pagination, paginate, ordered_rows, check_occ, now_iso,
)
from errors import ApiError
from services import recompute_doc_checksum, doc_checksum

bp = Blueprint("model_documentation", __name__)

READ_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer",
]
WRITE_ROLES = ["ComplianceOfficer", "ValidationAnalyst"]

DOC_TYPES = {"MODEL_RISK_REPORT", "FAIR_LENDING_REPORT", "ADVERSE_ACTION_MAP",
             "BUREAU_DISCREPANCY_REPORT"}


@bp.post("/model-documentation")
def create_document():
    resolve_actor(request, WRITE_ROLES)
    body = body_of(request)
    reject_unknown(body, {"score_model_id", "study_id", "doc_type", "required_version_label"})
    require_fields(body, ["score_model_id", "doc_type", "required_version_label"])

    model = score_model(as_str(body["score_model_id"], "score_model_id"))
    doc_type = as_enum(body["doc_type"], DOC_TYPES, "doc_type")
    required_version_label = as_str(body["required_version_label"], "required_version_label")

    study_id = body.get("study_id")
    if study_id is not None:
        validation_study(as_str(study_id, "study_id"))

    rec = new_record()
    rec.update({
        "score_model_id": model["id"],
        "study_id": study_id,
        "doc_type": doc_type,
        "required_version_label": required_version_label,
        "status": "DRAFT",
        "filed_at": None,
        "checksum": "",
    })
    recompute_doc_checksum(rec)
    store("model_documentation", rec)
    return ok(rec, 201)


@bp.get("/model-documentation/<document_id>")
def get_document(document_id):
    resolve_actor(request, READ_ROLES)
    return ok(model_documentation(document_id))


@bp.get("/model-documentation")
def list_documents():
    resolve_actor(request, READ_ROLES)
    limit, offset = read_pagination(request)
    rows = ordered_rows("model_documentation")

    for param in ("score_model_id", "study_id", "doc_type", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(param) == value]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/model-documentation/<document_id>/file")
def file_document(document_id):
    resolve_actor(request, ["ComplianceOfficer", "FairLendingOfficer"])
    rec = model_documentation(document_id)
    body = body_of(request)
    reject_unknown(body, {"expected_documentation_version"})

    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    check_occ(rec, body, "expected_documentation_version")

    rec["status"] = "FILED"
    rec["filed_at"] = now_iso()
    recompute_doc_checksum(rec)
    touch(rec)
    return ok(rec)