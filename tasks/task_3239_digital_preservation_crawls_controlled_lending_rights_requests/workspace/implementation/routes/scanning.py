"""Scan batches and scan items."""
from flask import Blueprint, request

import db
from errors import ERR_INVALID_STATE, ERR_SEAL_EMPTY_BATCH, not_found, raise_err, validation
from middleware import require_roles
from models import serialize_batch, serialize_item, stamp_new, touch, work_availability
from response import paginate, parse_pagination, success_list, success_object
from services import run_promotion

bp = Blueprint("scanning", __name__)


@bp.post("/archive/scan-batches")
def create_batch():
    require_roles("ScanOperator")
    body = request.get_json(silent=True) or {}
    operator_code = body.get("operator_code")
    if not isinstance(operator_code, str) or not operator_code:
        validation("operator_code is required")
    b = stamp_new()
    b.update({
        "operator_code": operator_code,
        "status": "OPEN",
        "item_count": 0,
        "page_count": 0,
    })
    db.batches[b["id"]] = b
    return success_object(serialize_batch(b), status=201)


@bp.get("/archive/scan-batches/<bid>")
def get_batch(bid):
    require_roles("Admin", "ScanOperator")
    b = db.batches.get(bid)
    if b is None:
        not_found("Scan batch not found")
    return success_object(serialize_batch(b))


@bp.post("/archive/scan-batches/<bid>/seal")
def seal_batch(bid):
    require_roles("ScanOperator")
    b = db.batches.get(bid)
    if b is None:
        not_found("Scan batch not found")
    if b["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Batch is not OPEN")
    if b["item_count"] < 1:
        raise_err(ERR_SEAL_EMPTY_BATCH, "Cannot seal an empty batch")
    b["status"] = "SEALED"
    touch(b)
    # Evaluate each DEPOSITED item for promotion to LENDABLE.
    affected_works = []
    for it in list(db.items.values()):
        if it["batch_id"] != bid or it["status"] != "DEPOSITED":
            continue
        work = db.works.get(it["work_id"])
        lib = db.libraries.get(it["owning_library_id"])
        if (
            work is not None
            and work_availability(work) == "AVAILABLE"
            and lib is not None
            and lib["status"] == "ACTIVE"
        ):
            it["status"] = "LENDABLE"
            touch(it)
            affected_works.append(it["work_id"])
    for wid in affected_works:
        run_promotion(wid)
    return success_object(serialize_batch(b))


@bp.post("/archive/items")
def create_item():
    require_roles("ScanOperator")
    body = request.get_json(silent=True) or {}
    batch_id = body.get("batch_id")
    work_id = body.get("work_id")
    library_id = body.get("owning_library_id")
    page_count = body.get("page_count")
    condition = body.get("condition_grade")
    # Priority 3: FK existence, left-to-right as declared.
    if batch_id is not None and batch_id not in db.batches:
        not_found("Scan batch not found")
    if work_id is not None and work_id not in db.works:
        not_found("Work not found")
    if library_id is not None and library_id not in db.libraries:
        not_found("Partner library not found")
    # Priority 4: batch must be OPEN.
    if batch_id is not None and db.batches[batch_id]["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Batch is not OPEN")
    # Priority 6: schema.
    if not isinstance(batch_id, str) or not batch_id:
        validation("batch_id is required")
    if not isinstance(work_id, str) or not work_id:
        validation("work_id is required")
    if not isinstance(library_id, str) or not library_id:
        validation("owning_library_id is required")
    if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 1:
        validation("page_count must be an integer >= 1")
    if condition not in ("FINE", "GOOD", "FAIR", "FRAGILE"):
        validation("condition_grade must be FINE, GOOD, FAIR, or FRAGILE")
    it = stamp_new()
    it.update({
        "batch_id": batch_id,
        "work_id": work_id,
        "owning_library_id": library_id,
        "page_count": page_count,
        "condition_grade": condition,
        "status": "DEPOSITED",
    })
    db.items[it["id"]] = it
    batch = db.batches[batch_id]
    batch["item_count"] += 1
    batch["page_count"] += page_count
    touch(batch)
    return success_object(serialize_item(it), status=201)


@bp.get("/archive/items/<iid>")
def get_item(iid):
    require_roles("Admin", "LibraryAdmin", "ScanOperator", "Patron")
    it = db.items.get(iid)
    if it is None:
        not_found("Scan item not found")
    return success_object(serialize_item(it))


@bp.get("/archive/works/<wid>/items")
def list_work_items(wid):
    require_roles("Admin", "LibraryAdmin", "ScanOperator", "Patron")
    if wid not in db.works:
        not_found("Work not found")
    limit, offset = parse_pagination(request.args)
    batch_id = request.args.get("batch_id")
    library_id = request.args.get("owning_library_id")
    status = request.args.get("status")
    rows = [it for it in db.items.values() if it["work_id"] == wid]
    if batch_id is not None:
        rows = [it for it in rows if it["batch_id"] == batch_id]
    if library_id is not None:
        rows = [it for it in rows if it["owning_library_id"] == library_id]
    if status is not None:
        rows = [it for it in rows if it["status"] == status]
    rows.sort(key=lambda it: it["created_at"])
    page, total = paginate([serialize_item(it) for it in rows], limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/archive/scan-batches/<bid>/items")
def list_batch_items(bid):
    require_roles("Admin", "ScanOperator")
    if bid not in db.batches:
        not_found("Scan batch not found")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = [it for it in db.items.values() if it["batch_id"] == bid]
    if status is not None:
        rows = [it for it in rows if it["status"] == status]
    rows.sort(key=lambda it: it["created_at"])
    page, total = paginate([serialize_item(it) for it in rows], limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/archive/partner-libraries/<lid>/items")
def list_library_items(lid):
    require_roles("Admin", "LibraryAdmin")
    if lid not in db.libraries:
        not_found("Partner library not found")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = [it for it in db.items.values() if it["owning_library_id"] == lid]
    if status is not None:
        rows = [it for it in rows if it["status"] == status]
    rows.sort(key=lambda it: it["created_at"])
    page, total = paginate([serialize_item(it) for it in rows], limit, offset)
    return success_list(page, limit, offset, total)
