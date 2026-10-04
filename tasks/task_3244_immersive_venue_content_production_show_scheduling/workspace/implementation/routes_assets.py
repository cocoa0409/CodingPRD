"""Asset routes."""

from flask import Blueprint, request

from db import DB
from common import base_resource, touch, paginate
from middleware import require_role
from errors import not_found, invalid_state, asset_not_in_qc, format_mismatch
from response import success_object, success_list
import calc

bp = Blueprint("assets", __name__)


def asset_view(a):
    return dict(a)


def _find_batch_for_asset(asset_id):
    for b in DB.render_batches.values():
        if asset_id in b["submitted_asset_ids"]:
            return b
    return None


@bp.post("/venue/assets")
def create_asset():
    require_role("ContentProducer")
    body = request.get_json(silent=True) or {}
    prod = DB.productions.get(body.get("production_id"))
    if not prod:
        raise not_found("production_id does not exist")
    if prod.get("is_haptic_capable") and body.get("capture_format") != "WRAP_16K":
        raise format_mismatch()
    a = base_resource()
    a.update({
        "production_id": body.get("production_id"),
        "title": body.get("title"),
        "capture_format": body.get("capture_format"),
        "storage_gb": body.get("storage_gb"),
        "render_hours_base": body.get("render_hours_base"),
        "status": "CAPTURED",
        "render_cost_cents": 0,
    })
    DB.assets[a["id"]] = a
    return success_object(asset_view(a), 201)


@bp.get("/venue/assets")
def list_assets():
    require_role("ContentProducer", "ProductionDirector")
    items = sorted(DB.assets.values(), key=lambda x: x["created_at"])
    pid = request.args.get("production_id")
    status = request.args.get("status")
    if pid:
        items = [a for a in items if a["production_id"] == pid]
    if status:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = paginate([asset_view(a) for a in items], request.args)
    return success_list(page, limit, offset, total)


@bp.get("/venue/assets/<aid>")
def get_asset(aid):
    require_role("ContentProducer", "ProductionDirector")
    a = DB.assets.get(aid)
    if not a:
        raise not_found()
    return success_object(asset_view(a))


@bp.post("/venue/assets/<aid>/qc/approve")
def qc_approve(aid):
    require_role("ContentProducer")
    a = DB.assets.get(aid)
    if not a:
        raise not_found()
    if a["status"] != "QC":
        raise asset_not_in_qc()
    a["status"] = "APPROVED"
    a["render_cost_cents"] = calc.asset_render_cost_cents(a)
    touch(a)
    batch = _find_batch_for_asset(aid)
    if batch and batch["submitted_asset_count"] > 0:
        batch["submitted_asset_count"] -= 1
        touch(batch)
    return success_object(asset_view(a))


@bp.post("/venue/assets/<aid>/qc/fail")
def qc_fail(aid):
    require_role("ContentProducer")
    a = DB.assets.get(aid)
    if not a:
        raise not_found()
    if a["status"] != "QC":
        raise asset_not_in_qc()
    a["status"] = "QC_FAILED"
    touch(a)
    batch = _find_batch_for_asset(aid)
    if batch:
        batch["failed_asset_count"] += 1
        if batch["submitted_asset_count"] > 0:
            batch["submitted_asset_count"] -= 1
        touch(batch)
    return success_object(asset_view(a))


@bp.post("/venue/assets/<aid>/retry")
def retry_asset(aid):
    require_role("ContentProducer")
    a = DB.assets.get(aid)
    if not a:
        raise not_found()
    if a["status"] != "QC_FAILED":
        raise invalid_state()
    prod = DB.productions.get(a["production_id"])
    if prod and prod["status"] == "RETIRED":
        raise invalid_state("Production is RETIRED")
    a["status"] = "CAPTURED"
    touch(a)
    return success_object(asset_view(a))


@bp.post("/venue/assets/<aid>/archive")
def archive_asset(aid):
    require_role("ContentProducer")
    a = DB.assets.get(aid)
    if not a:
        raise not_found()
    if a["status"] != "APPROVED":
        raise invalid_state()
    a["status"] = "ARCHIVED"
    touch(a)
    return success_object(asset_view(a))
