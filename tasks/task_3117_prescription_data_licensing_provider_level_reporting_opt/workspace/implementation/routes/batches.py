"""DataFeedBatch endpoints: submit, validate, deidentify, accept, reject, reprocess."""

from flask import Blueprint, request

from db import db
from errors import (
    err_not_found,
    err_invalid_request,
    err_forbidden_ownership,
    err_agreement_not_active,
    err_batch_invalid_state,
    err_deid_qa_below_threshold,
    err_royalty_budget_exhausted,
)
from middleware import require_role, get_pagination, ALL_ROLES
from response import success_object, success_array
from services.calculations import calc_acquisition_royalty
from services.common import (
    body_json, require_fields, check_str, check_int, check_num, check_period, mint, touch,
)

bp = Blueprint("batches", __name__)

BATCH_STATUSES = {
    "RECEIVED", "VALIDATED", "DEIDENTIFIED", "ACCEPTED", "REJECTED", "REPROCESSED", "QUARANTINED",
}


def _get_batch(bid):
    batch = db.batches.get(bid)
    if batch is None:
        raise err_not_found("Batch not found")
    return batch


@bp.route("/data-feed-batches", methods=["POST"])
def create_batch():
    user_id, role = require_role(["SupplierOperator"])
    data = body_json()
    require_fields(data, ["agreement_id", "period_code", "record_count"])
    agreement_id = check_str(data, "agreement_id")
    period_code = check_period(data, "period_code")
    record_count = check_int(data, "record_count", min_v=1)
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        raise err_not_found("Agreement not found")
    if agreement["supplier_id"] != user_id:
        raise err_forbidden_ownership("Batch must be submitted under own supplier's agreement")
    if agreement["status"] != "ACTIVE":
        raise err_agreement_not_active("Agreement must be ACTIVE to submit a batch")
    batch = mint(db.batches, {
        "agreement_id": agreement_id,
        "period_code": period_code,
        "record_count": record_count,
        "deidentification_profile_id": None,
        "deid_qa_score": None,
        "royalty_cents": None,
        "status": "RECEIVED",
    })
    return success_object(batch, status=201)


@bp.route("/data-feed-batches", methods=["GET"])
def list_batches():
    require_role(ALL_ROLES)
    limit, offset = get_pagination()
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    if status is not None and status not in BATCH_STATUSES:
        raise err_invalid_request("Invalid status filter")
    items = sorted(db.batches.values(), key=lambda b: b["created_at"])
    if agreement_id is not None:
        items = [b for b in items if b["agreement_id"] == agreement_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)


@bp.route("/data-feed-batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_role(ALL_ROLES)
    return success_object(_get_batch(bid))


@bp.route("/data-feed-batches/<bid>/validate", methods=["POST"])
def validate_batch(bid):
    require_role(["DataAcquisitionManager"])
    batch = _get_batch(bid)
    if batch["status"] not in ("RECEIVED", "REPROCESSED"):
        raise err_batch_invalid_state("Batch must be RECEIVED or REPROCESSED to validate")
    if db.agreements[batch["agreement_id"]]["status"] != "ACTIVE":
        raise err_agreement_not_active("Agreement must be ACTIVE to validate a batch")
    batch["status"] = "VALIDATED"
    touch(batch)
    return success_object(batch)


@bp.route("/data-feed-batches/<bid>/deidentify", methods=["POST"])
def deidentify_batch(bid):
    require_role(["PrivacyOfficer"])
    batch = _get_batch(bid)
    data = body_json()
    require_fields(data, ["deidentification_profile_id"])
    profile_id = check_str(data, "deidentification_profile_id")
    if profile_id not in db.deid_profiles:
        raise err_not_found("De-identification profile not found")
    if batch["status"] != "VALIDATED":
        raise err_batch_invalid_state("Batch must be VALIDATED to de-identify")
    if db.agreements[batch["agreement_id"]]["status"] != "ACTIVE":
        raise err_agreement_not_active("Agreement must be ACTIVE to de-identify a batch")
    batch["status"] = "DEIDENTIFIED"
    batch["deidentification_profile_id"] = profile_id
    touch(batch)
    return success_object(batch)


@bp.route("/data-feed-batches/<bid>/accept", methods=["POST"])
def accept_batch(bid):
    require_role(["PrivacyOfficer"])
    batch = _get_batch(bid)
    data = body_json()
    require_fields(data, ["deid_qa_score"])
    qa = check_num(data, "deid_qa_score", min_v=0, max_v=1)
    if batch["status"] != "DEIDENTIFIED":
        raise err_batch_invalid_state("Batch must be DEIDENTIFIED to accept")
    if qa < 0.90:
        raise err_deid_qa_below_threshold()
    agreement = db.agreements[batch["agreement_id"]]
    supplier = db.suppliers[agreement["supplier_id"]]
    royalty = calc_acquisition_royalty(batch, supplier["supplier_type"], qa)
    if agreement["royalty_spent_cents"] + royalty > agreement["royalty_budget_cents"]:
        raise err_royalty_budget_exhausted()
    batch["deid_qa_score"] = qa
    batch["royalty_cents"] = royalty
    batch["status"] = "ACCEPTED"
    touch(batch)
    agreement["royalty_spent_cents"] += royalty
    touch(agreement)
    return success_object(batch)


@bp.route("/data-feed-batches/<bid>/reject", methods=["POST"])
def reject_batch(bid):
    require_role(["PrivacyOfficer"])
    batch = _get_batch(bid)
    if batch["status"] not in ("VALIDATED", "DEIDENTIFIED"):
        raise err_batch_invalid_state("Batch must be VALIDATED or DEIDENTIFIED to reject")
    was_deidentified = batch["status"] == "DEIDENTIFIED"
    batch["status"] = "REJECTED"
    if was_deidentified:
        batch["deidentification_profile_id"] = None
    touch(batch)
    return success_object(batch)


@bp.route("/data-feed-batches/<bid>/reprocess", methods=["POST"])
def reprocess_batch(bid):
    user_id, role = require_role(["SupplierOperator"])
    batch = _get_batch(bid)
    agreement = db.agreements[batch["agreement_id"]]
    if agreement["supplier_id"] != user_id:
        raise err_forbidden_ownership("Only the owning SupplierOperator may reprocess this batch")
    if batch["status"] != "REJECTED":
        raise err_batch_invalid_state("Batch must be REJECTED to reprocess")
    batch["status"] = "REPROCESSED"
    touch(batch)
    return success_object(batch)
