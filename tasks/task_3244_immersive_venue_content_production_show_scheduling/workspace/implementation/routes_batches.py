"""Render batch routes."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB
from common import base_resource, touch, parse_dt, dt_to_iso
from middleware import require_role
from errors import not_found, invalid_state, batch_busy, render_blocked
from response import success_object
import calc
import services

bp = Blueprint("render_batches", __name__)


def batch_view(b):
    return dict(b)


@bp.post("/venue/render-batches")
def create_batch():
    require_role("ContentProducer")
    body = request.get_json(silent=True) or {}
    asset_ids = list(body.get("asset_ids") or [])
    b = base_resource()
    b.update({
        "status": "OPEN",
        "dispatch_mode": body.get("dispatch_mode"),
        "render_minutes": 0,
        "batch_cost_cents": 0,
        "submitted_asset_count": len(asset_ids),
        "failed_asset_count": 0,
        "submitted_asset_ids": asset_ids,
        "render_started_at": None,
    })
    DB.render_batches[b["id"]] = b
    return success_object(batch_view(b), 201)


@bp.get("/venue/render-batches/<bid>")
def get_batch(bid):
    require_role("ContentProducer", "ProductionDirector")
    b = DB.render_batches.get(bid)
    if not b:
        raise not_found()
    return success_object(batch_view(b))


@bp.post("/venue/render-batches/<bid>/dispatch")
def dispatch_batch(bid):
    require_role("ContentProducer")
    b = DB.render_batches.get(bid)
    if not b:
        raise not_found()
    if b["status"] != "OPEN":
        raise invalid_state()
    if b["submitted_asset_count"] <= 0:
        raise batch_busy("Batch has no submitted assets")
    for other in DB.render_batches.values():
        if other["id"] != bid and other["status"] in ("RENDERING", "SETTLING"):
            raise batch_busy("Another batch is RENDERING or SETTLING")
    render_minutes = calc.calc_render_minutes(b)
    now = DB.clock
    window_end = now + timedelta(minutes=render_minutes)
    # ENV_FX maintenance exclusion
    envfx_ids = {s["id"] for s in DB.venue_systems.values() if s["kind"] == "ENV_FX"}
    for w in DB.maintenance_windows.values():
        if w["venue_system_id"] not in envfx_ids:
            continue
        if w["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if calc.windows_overlap(now, window_end, parse_dt(w["start_time"]), parse_dt(w["end_time"])):
            raise render_blocked()
    # dispatch
    b["status"] = "RENDERING"
    b["render_minutes"] = render_minutes
    b["batch_cost_cents"] = render_minutes * calc.COST_PER_RENDER_MINUTE_CENTS
    b["render_started_at"] = dt_to_iso(now)
    touch(b)
    for aid in b["submitted_asset_ids"]:
        asset = DB.assets.get(aid)
        if asset and asset["status"] == "CAPTURED":
            asset["status"] = "RENDERING"
            touch(asset)
    return success_object(batch_view(b))


@bp.post("/venue/render-batches/<bid>/settle")
def settle_batch(bid):
    require_role("ContentProducer")
    b = DB.render_batches.get(bid)
    if not b:
        raise not_found()
    if b["status"] != "SETTLING":
        raise invalid_state()
    b["status"] = "SETTLED"
    touch(b)
    for aid in b["submitted_asset_ids"]:
        asset = DB.assets.get(aid)
        if asset and asset["status"] == "RENDERING":
            asset["status"] = "QC"
            touch(asset)
    return success_object(batch_view(b))


@bp.post("/venue/render-batches/<bid>/abort")
def abort_batch(bid):
    require_role("ContentProducer")
    b = DB.render_batches.get(bid)
    if not b:
        raise not_found()
    if b["status"] not in ("OPEN", "RENDERING", "SETTLING"):
        raise invalid_state()
    services.fail_batch(b)
    return success_object(batch_view(b))
