"""Seed train stage endpoints (PRD 3.3): define/list/advance."""
from flask import Blueprint, request

import clock
import envelope
import serialize
import store
from auth import require_auth
from constants import SEED_STAGE_ADVANCE_TARGETS, TRANSFER_WINDOW_HOURS
from errors import err
from validate import action_value, body, must_get, paginate, req_int

bp = Blueprint("seed_stages", __name__)


@bp.route("/campaigns/<cid>/seed-stages", methods=["POST"])
def create_seed_stage(cid):
    require_auth(("ProcessEngineer",))
    campaign = must_get("campaign", cid)
    d = body()
    idx = req_int(d, "stage_index", min_value=1)
    dur = req_int(d, "planned_duration_hours", min_value=1)
    for s in store.all_recs("seed_stages"):
        if s["campaign_id"] == campaign["id"] and s["stage_index"] == idx:
            err("ERR_INVALID_REQUEST", "stage_index must be unique within the campaign")
    rec = store.create_rec("seed_stages", {
        "campaign_id": campaign["id"],
        "stage_index": idx,
        "planned_duration_hours": dur,
        "started_at": None,
        "completed_at": None,
        "status": "PENDING",
    })
    return envelope.ok(serialize.seed_stage(rec), 201)


@bp.route("/campaigns/<cid>/seed-stages", methods=["GET"])
def list_seed_stages(cid):
    require_auth(("Any",))
    must_get("campaign", cid)
    recs = [s for s in store.all_recs("seed_stages") if s["campaign_id"] == cid]
    status_f = request.args.get("status")
    if status_f is not None:
        recs = [s for s in recs if s["status"] == status_f]
    page, total, limit, offset = paginate(recs)
    return envelope.ok_list([serialize.seed_stage(s) for s in page], total, limit, offset)


def _to_running(rec):
    if rec["status"] not in ("PENDING", "FAILED", "EXPIRED"):
        err("ERR_INVALID_SEED_STAGE_STATE", "RUNNING requires PENDING, FAILED or EXPIRED")
    campaign = store.get("campaigns", rec["campaign_id"])
    if campaign["status"] != "SEED_IN_PROGRESS":
        err("ERR_INVALID_CAMPAIGN_STATE", "Stage advance requires SEED_IN_PROGRESS campaign")
    lower = [s for s in store.all_recs("seed_stages")
             if s["campaign_id"] == rec["campaign_id"] and s["stage_index"] < rec["stage_index"]]
    if any(s["status"] != "COMPLETED" for s in lower):
        err("ERR_SEED_STAGE_ORDER_VIOLATION", "A lower-indexed stage is not COMPLETED")
    if rec["stage_index"] > 1 and lower:
        prev = max(lower, key=lambda s: s["stage_index"])
        if clock.hours_between(prev["completed_at"], clock.now()) > TRANSFER_WINDOW_HOURS:
            prev["status"] = "EXPIRED"  # predecessor flips; the failed stage keeps status
            store.touch(prev)
            err("ERR_SEED_TRANSFER_WINDOW_EXPIRED",
                "More than 36 hours elapsed since the predecessor stage completed")
    rec["status"] = "RUNNING"
    rec["started_at"] = clock.now()
    rec["completed_at"] = None


@bp.route("/seed-stages/<sid>/advance", methods=["POST"])
def advance_seed_stage(sid):
    require_auth(("ProcessEngineer",))
    rec = must_get("seed_stage", sid)
    d = body()
    target = action_value(d, "to_status", SEED_STAGE_ADVANCE_TARGETS)
    if target == "RUNNING":
        _to_running(rec)
    elif target == "COMPLETED":
        if rec["status"] != "RUNNING":
            err("ERR_INVALID_SEED_STAGE_STATE", "COMPLETED requires RUNNING")
        rec["status"] = "COMPLETED"
        rec["completed_at"] = clock.now()
    else:  # FAILED
        if rec["status"] != "RUNNING":
            err("ERR_INVALID_SEED_STAGE_STATE", "FAILED requires RUNNING")
        rec["status"] = "FAILED"
    store.touch(rec)
    return envelope.ok(serialize.seed_stage(rec), 200)
