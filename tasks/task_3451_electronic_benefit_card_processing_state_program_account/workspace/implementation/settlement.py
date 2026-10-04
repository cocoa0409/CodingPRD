"""Settlement batches, reconciliation, and disputes."""
from datetime import timedelta

from flask import Blueprint

from errors import ApiError
from state import DB
from domain import (
    new_entity, touch, ser_batch, ser_dispute, batch_open_disputes,
    batch_adjustment_total,
)
from util import (
    authed, body, req_str, req_int, ok_object, list_response, sort_created,
    query_filter, now_dt,
)

bp = Blueprint("settlement", __name__, url_prefix="/ebt")


def get_batch(bid):
    b = DB.batches.get(bid)
    if b is None:
        raise ApiError("ERR_NOT_FOUND", "settlement batch not found")
    return b


def get_dispute(did):
    d = DB.disputes.get(did)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", "dispute not found")
    return d


def _batch_involves_retailer(batch, retailer_id):
    for tid in batch["settled_authorization_ids"]:
        t = DB.txns.get(tid)
        if t is not None and t["retailer_id"] == retailer_id:
            return True
    return False


@bp.get("/settlement-batches")
def list_batches():
    authed(["StateAdmin", "CardholderServices"])
    rows = list(DB.batches.values())
    contract_id = query_filter("contract_id")
    if contract_id is not None:
        rows = [b for b in rows if b["contract_id"] == contract_id]
    acquirer = query_filter("acquirer_reference")
    if acquirer is not None:
        rows = [b for b in rows if b["acquirer_reference"] == acquirer]
    status = query_filter("batch_status")
    if status is not None:
        rows = [b for b in rows if b["batch_status"] == status]
    return list_response(sort_created(rows), ser_batch)


@bp.get("/settlement-batches/<bid>")
def read_batch(bid):
    authed(["StateAdmin", "CardholderServices"])
    return ok_object(ser_batch(get_batch(bid)))


@bp.post("/settlement-batches/<bid>/reconcile")
def reconcile(bid):
    authed(["StateAdmin"])
    batch = get_batch(bid)
    b = body()
    actual = req_int(b, "actual_settled_cents")
    if batch["batch_status"] == "RECONCILED":
        raise ApiError("ERR_INVALID_STATE", "batch is already RECONCILED")
    if batch_open_disputes(batch["id"]):
        raise ApiError("ERR_BATCH_HAS_OPEN_DISPUTES",
                       "batch has OPEN disputes")
    now = now_dt()
    net = batch["gross_settled_cents"] - batch["acquirer_fee_cents"] \
        + batch_adjustment_total(batch["id"])
    batch["actual_settled_cents"] = actual
    if actual == net:
        batch["batch_status"] = "RECONCILED"
        batch["reconciled_at"] = now
        touch(batch)
        return ok_object(ser_batch(batch))
    batch["batch_status"] = "DISPUTED"
    touch(batch)
    dispute = new_entity()
    dispute.update({
        "settlement_batch_id": batch["id"],
        "dispute_type": "RECONCILIATION_MISMATCH",
        "retailer_id": None,
        "dispute_status": "OPEN",
        "disputed_amount_cents": actual - net,
        "adjustment_cents": None,
        "reason": "reconciliation mismatch",
        "filed_by_user_id": None,
        "decided_at": None,
    })
    DB.disputes[dispute["id"]] = dispute
    return ok_object(ser_batch(batch))


@bp.post("/disputes")
def file_dispute():
    role, uid = authed(["RetailerSystem"])
    b = body()
    batch_id = req_str(b, "settlement_batch_id")
    disputed_amount = req_int(b, "disputed_amount_cents")
    reason = req_str(b, "reason")
    batch = DB.batches.get(batch_id)
    if batch is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "settlement_batch_id does not exist")
    if not _batch_involves_retailer(batch, uid):
        raise ApiError("ERR_FORBIDDEN",
                       "the batch contains no settled transaction of this retailer")
    if batch["batch_status"] not in ("CUTOFF", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "disputes may be filed only against CUTOFF or DISPUTED batches")
    contract = DB.contracts[batch["contract_id"]]
    now = now_dt()
    if now > batch["cutoff_at"] + timedelta(days=contract["dispute_window_days"]):
        raise ApiError("ERR_DISPUTE_WINDOW_EXPIRED",
                       "dispute filing window has expired")
    dispute = new_entity()
    dispute.update({
        "settlement_batch_id": batch["id"],
        "dispute_type": "RETAILER_DISPUTE",
        "retailer_id": uid,
        "dispute_status": "OPEN",
        "disputed_amount_cents": disputed_amount,
        "adjustment_cents": None,
        "reason": reason,
        "filed_by_user_id": uid,
        "decided_at": None,
    })
    DB.disputes[dispute["id"]] = dispute
    if batch["batch_status"] == "CUTOFF":
        batch["batch_status"] = "DISPUTED"
        touch(batch)
    return ok_object(ser_dispute(dispute), 201)


@bp.get("/settlement-batches/<bid>/disputes")
def list_disputes(bid):
    role, uid = authed(["StateAdmin", "CardholderServices", "RetailerSystem"])
    batch = get_batch(bid)
    if role == "RetailerSystem" and not _batch_involves_retailer(batch, uid):
        raise ApiError("ERR_FORBIDDEN",
                       "the batch contains no settled transaction of this retailer")
    rows = [d for d in DB.disputes.values() if d["settlement_batch_id"] == bid]
    status = query_filter("dispute_status")
    if status is not None:
        rows = [d for d in rows if d["dispute_status"] == status]
    return list_response(sort_created(rows), ser_dispute)


@bp.post("/disputes/<did>/status")
def dispute_status(did):
    authed(["StateAdmin"])
    dispute = get_dispute(did)
    b = body()
    to = req_str(b, "to")
    if to not in ("OPEN", "UPHELD", "OVERTURNED"):
        raise ApiError("ERR_INVALID_REQUEST", "unknown target status")
    if dispute["dispute_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "dispute is already decided")
    if to == "OPEN":
        raise ApiError("ERR_INVALID_STATE", "dispute cannot transition to OPEN")
    now = now_dt()
    if to == "UPHELD":
        adjustment = req_int(b, "adjustment_cents")
        dispute["adjustment_cents"] = adjustment
    dispute["dispute_status"] = to
    dispute["decided_at"] = now
    touch(dispute)
    if to == "UPHELD":
        batch = DB.batches[dispute["settlement_batch_id"]]
        touch(batch)  # totals recomputed at read; record the mutation
    return ok_object(ser_dispute(dispute))
