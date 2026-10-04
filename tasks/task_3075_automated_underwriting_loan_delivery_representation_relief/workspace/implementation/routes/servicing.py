"""Servicing transfers, subservicer oversight, pipelines, LLPA update events."""
from flask import Blueprint, g

from core import (
    ApiError, db, dump, endpoint, f_dt, f_int, f_str, body, new_row, now,
    paginate, q_enum, q_str, respond_object, sort_created, touch,
)
from svc import (
    MIN_OVERSIGHT_SCORE_FOR_TRANSFER, active_matrix, find_pipeline,
    pipeline_value, recompute_oversight_score,
)

bp = Blueprint("servicing", __name__)

ALL_ROLES = ("GseAdmin", "GseUnderwritingEngine", "SellerOfficer", "Underwriter", "QcAuditor", "ServicerOfficer")
TRANSFER_STATUSES = ("REQUESTED", "APPROVED", "REJECTED", "COMPLETED", "CANCELLED")
OVERSIGHT_STATUSES = ("OPEN", "CLOSED")


# ---------------------------------------------------------------------------
# Servicing transfers
# ---------------------------------------------------------------------------
@bp.post("/gse/servicing-transfers")
@endpoint("ServicerOfficer")
def create_transfer():
    payload = body()
    loan_id = f_str(payload, "loan_id")
    to_servicer_id = f_str(payload, "to_servicer_id")
    effective_date = f_dt(payload, "effective_date")
    if effective_date <= now():
        raise ApiError("ERR_TRANSFER_DATE_PAST", "Transfer effective_date must be strictly after the current logical time.")
    loan = db.loans.get(loan_id)
    if loan is None:
        raise ApiError("ERR_NOT_FOUND", "Loan not found.")
    if to_servicer_id not in db.servicers:
        raise ApiError("ERR_NOT_FOUND", "Receiving servicer not found.")
    if loan["status"] != "PURCHASED":
        raise ApiError("ERR_LOAN_NOT_PURCHASED", "Servicing transfers require a PURCHASED loan.")
    transfer = new_row(
        "transfer",
        loan_id=loan_id,
        from_servicer_id=loan["servicer_id"],
        to_servicer_id=to_servicer_id,
        effective_date=effective_date,
        requester_id=g.user_id,
        status="REQUESTED",
    )
    db.transfers[transfer["id"]] = transfer
    return respond_object(dump(transfer), 201)


def get_transfer_or_404(transfer_id):
    transfer = db.transfers.get(transfer_id)
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", "Servicing transfer not found.")
    return transfer


@bp.get("/gse/servicing-transfers/<transfer_id>")
@endpoint(*ALL_ROLES)
def get_transfer(transfer_id):
    return respond_object(dump(get_transfer_or_404(transfer_id)), 200)


@bp.get("/gse/servicing-transfers")
@endpoint(*ALL_ROLES)
def list_transfers():
    rows = list(db.transfers.values())
    loan_id = q_str("loan_id")
    from_servicer_id = q_str("from_servicer_id")
    to_servicer_id = q_str("to_servicer_id")
    status = q_enum("status", TRANSFER_STATUSES)
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    if from_servicer_id is not None:
        rows = [r for r in rows if r["from_servicer_id"] == from_servicer_id]
    if to_servicer_id is not None:
        rows = [r for r in rows if r["to_servicer_id"] == to_servicer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.post("/gse/servicing-transfers/<transfer_id>/approve")
@endpoint("GseAdmin")
def approve_transfer(transfer_id):
    transfer = get_transfer_or_404(transfer_id)
    payload = body()
    expected_loan_version = f_int(payload, "expected_loan_version")
    if transfer["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED transfer can be approved.")
    loan = db.loans.get(transfer["loan_id"])
    to_servicer = db.servicers.get(transfer["to_servicer_id"])
    # Compliance gates before the concurrency gate (PRD 2.9).
    if to_servicer is None or to_servicer["status"] != "APPROVED":
        raise ApiError("ERR_SERVICER_NOT_APPROVED", "Receiving servicer is not APPROVED.")
    recompute_oversight_score(to_servicer)
    if int(to_servicer["oversight_score"]) < MIN_OVERSIGHT_SCORE_FOR_TRANSFER:
        raise ApiError("ERR_SUBSERVICER_OVERSIGHT_DEFICIENT", "Receiving servicer oversight score below 60.")
    if g.user_id == transfer["requester_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Approving admin must differ from the requesting officer.")
    if loan is None or int(expected_loan_version) != int(loan["version"]):
        raise ApiError("ERR_STALE_VERSION", "Loan version has advanced since the caller's last read.")
    transfer["status"] = "APPROVED"
    touch(transfer)
    return respond_object(dump(transfer), 200)


@bp.post("/gse/servicing-transfers/<transfer_id>/reject")
@endpoint("GseAdmin")
def reject_transfer(transfer_id):
    transfer = get_transfer_or_404(transfer_id)
    if transfer["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED transfer can be rejected.")
    if g.user_id == transfer["requester_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Rejecting admin must differ from the requesting officer.")
    transfer["status"] = "REJECTED"
    touch(transfer)
    return respond_object(dump(transfer), 200)


@bp.post("/gse/servicing-transfers/<transfer_id>/cancel")
@endpoint("ServicerOfficer")
def cancel_transfer(transfer_id):
    transfer = get_transfer_or_404(transfer_id)
    if g.user_id != transfer["requester_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", "Only the requesting officer may cancel this transfer.")
    if transfer["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED transfer can be cancelled.")
    transfer["status"] = "CANCELLED"
    touch(transfer)
    return respond_object(dump(transfer), 200)


# ---------------------------------------------------------------------------
# Subservicer oversight
# ---------------------------------------------------------------------------
@bp.post("/gse/subservicer-oversight")
@endpoint("GseAdmin")
def create_oversight():
    payload = body()
    servicer_id = f_str(payload, "servicer_id")
    subservicer_id = f_str(payload, "subservicer_id")
    period_start = f_dt(payload, "oversight_period_start")
    period_end = f_dt(payload, "oversight_period_end")
    findings_count = f_int(payload, "findings_count", required=False, default=0, minimum=0)
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_REQUEST", "oversight_period_end must be strictly after oversight_period_start.")
    if servicer_id not in db.servicers:
        raise ApiError("ERR_NOT_FOUND", "Master servicer not found.")
    if subservicer_id not in db.servicers:
        raise ApiError("ERR_NOT_FOUND", "Subservicer not found.")
    record = new_row(
        "oversight",
        servicer_id=servicer_id,
        subservicer_id=subservicer_id,
        oversight_period_start=period_start,
        oversight_period_end=period_end,
        findings_count=findings_count,
        status="OPEN",
    )
    db.oversight[record["id"]] = record
    master = db.servicers.get(servicer_id)
    if master is not None:
        recompute_oversight_score(master)
    return respond_object(dump(record), 201)


def get_oversight_or_404(record_id):
    record = db.oversight.get(record_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", "Oversight record not found.")
    return record


@bp.get("/gse/subservicer-oversight/<record_id>")
@endpoint(*ALL_ROLES)
def get_oversight(record_id):
    return respond_object(dump(get_oversight_or_404(record_id)), 200)


@bp.get("/gse/subservicer-oversight")
@endpoint(*ALL_ROLES)
def list_oversight():
    rows = list(db.oversight.values())
    servicer_id = q_str("servicer_id")
    subservicer_id = q_str("subservicer_id")
    status = q_enum("status", OVERSIGHT_STATUSES)
    if servicer_id is not None:
        rows = [r for r in rows if r["servicer_id"] == servicer_id]
    if subservicer_id is not None:
        rows = [r for r in rows if r["subservicer_id"] == subservicer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.post("/gse/subservicer-oversight/<record_id>/close")
@endpoint("GseAdmin")
def close_oversight(record_id):
    record = get_oversight_or_404(record_id)
    if record["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN oversight record can be closed.")
    if now() < record["oversight_period_end"]:
        raise ApiError("ERR_OVERSIGHT_PERIOD_NOT_ENDED", "Oversight record cannot close before its period end.")
    record["status"] = "CLOSED"
    touch(record)
    master = db.servicers.get(record["servicer_id"])
    if master is not None:
        recompute_oversight_score(master)
    return respond_object(dump(record), 200)


# ---------------------------------------------------------------------------
# Pipelines and LLPA update events
# ---------------------------------------------------------------------------
@bp.post("/gse/pipelines")
@endpoint("SellerOfficer")
def create_pipeline():
    payload = body()
    seller_id = f_str(payload, "seller_id")
    # Existence of the body-referenced seller precedes the ownership gate (PRD §2.9).
    if seller_id not in db.sellers:
        raise ApiError("ERR_NOT_FOUND", "Seller not found.")
    if g.user_id != seller_id:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", "SellerOfficer may only create a pipeline for their own seller.")
    existing = find_pipeline(seller_id)
    if existing is not None:
        existing["projected_value_cents"] = pipeline_value(seller_id, active_matrix())
        return respond_object(dump(existing), 201)
    pipeline = new_row(
        "pipeline",
        seller_id=seller_id,
        projected_value_cents=pipeline_value(seller_id, active_matrix()),
    )
    db.pipelines[pipeline["id"]] = pipeline
    return respond_object(dump(pipeline), 201)


@bp.get("/gse/pipelines/<pipeline_id>")
@endpoint(*ALL_ROLES)
def get_pipeline(pipeline_id):
    pipeline = db.pipelines.get(pipeline_id)
    if pipeline is None:
        raise ApiError("ERR_NOT_FOUND", "Pipeline not found.")
    return respond_object(dump(pipeline), 200)


@bp.get("/gse/pipelines")
@endpoint(*ALL_ROLES)
def list_pipelines():
    rows = list(db.pipelines.values())
    seller_id = q_str("seller_id")
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    return paginate(sort_created(rows))


@bp.get("/gse/llpa-update-events")
@endpoint(*ALL_ROLES)
def list_update_events():
    rows = list(db.update_events.values())
    pipeline_id = q_str("pipeline_id")
    if pipeline_id is not None:
        rows = [r for r in rows if r["pipeline_id"] == pipeline_id]
    return paginate(sort_created(rows))
