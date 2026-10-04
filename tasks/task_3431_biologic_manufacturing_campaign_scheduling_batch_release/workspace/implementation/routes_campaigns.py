"""Campaign endpoints (PRD 3.2, 3.3): create/list/get/advance."""
from flask import Blueprint, request

import calc_capacity
import clock
import envelope
import serialize
import store
from auth import require_auth
from constants import CAMPAIGN_ADVANCE_TARGETS, DEMAND_TYPES, INOCULATION_WINDOW_HOURS
from errors import err
from validate import action_value, body, must_get, paginate, req_dt, req_enum, req_int

bp = Blueprint("campaigns", __name__)


def _check_market_scope(product, demand_type):
    scope = product["market_scope"]
    ok = (scope == "BOTH"
          or (scope == "CLINICAL_ONLY" and demand_type == "CLINICAL")
          or (scope == "COMMERCIAL_ONLY" and demand_type == "COMMERCIAL"))
    if not ok:
        err("ERR_MARKET_SCOPE_VIOLATION",
            "demand_type not permitted by product market_scope")


@bp.route("/trains/<tid>/campaigns", methods=["POST"])
def create_campaign(tid):
    require_auth(("ProcessEngineer",))
    train = must_get("train", tid)
    d = body()
    product_id = d.get("product_id")
    product = None
    if isinstance(product_id, str):
        product = must_get("product", product_id)  # body reference, stage 3
    if product is None:
        err("ERR_INVALID_REQUEST", "Missing required field: product_id")
    demand_type = req_enum(d, "demand_type", DEMAND_TYPES)
    start = req_dt(d, "planned_start_utc")
    end = req_dt(d, "planned_end_utc")
    if not end > start:
        err("ERR_INVALID_REQUEST", "planned_end_utc must be strictly after planned_start_utc")
    up = req_int(d, "upstream_hours", min_value=1)
    down = req_int(d, "downstream_hours", min_value=1)
    # PRD 3.2 creation check order: window, molecule compatibility, market scope.
    calc_capacity.check_window_conflict(tid, product, start, end)
    if product["molecule_type"] not in train["supported_molecule_types"]:
        err("ERR_TRAIN_PRODUCT_INCOMPATIBLE",
            "Product molecule_type not in train supported_molecule_types")
    _check_market_scope(product, demand_type)
    hours = calc_capacity.allocated_hours(tid, product, up, down, start)
    rec = store.create_rec("campaigns", {
        "train_id": train["id"],
        "product_id": product["id"],
        "demand_type": demand_type,
        "planned_start_utc": start,
        "planned_end_utc": end,
        "upstream_hours": up,
        "downstream_hours": down,
        "allocated_hours": hours,
        "status": "PROPOSED",
    })
    return envelope.ok(serialize.campaign(rec), 201)


@bp.route("/campaigns", methods=["GET"])
def list_campaigns():
    require_auth(("Any",))
    recs = store.all_recs("campaigns")
    site_f = request.args.get("site_id")
    train_f = request.args.get("train_id")
    product_f = request.args.get("product_id")
    demand_f = request.args.get("demand_type")
    status_f = request.args.get("status")
    if site_f is not None:
        recs = [c for c in recs
                if store.get("trains", c["train_id"])["site_id"] == site_f]
    if train_f is not None:
        recs = [c for c in recs if c["train_id"] == train_f]
    if product_f is not None:
        recs = [c for c in recs if c["product_id"] == product_f]
    if demand_f is not None:
        recs = [c for c in recs if c["demand_type"] == demand_f]
    if status_f is not None:
        recs = [c for c in recs if c["status"] == status_f]
    page, total, limit, offset = paginate(recs)
    return envelope.ok_list([serialize.campaign(c) for c in page], total, limit, offset)


@bp.route("/campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    require_auth(("Any",))
    return envelope.ok(serialize.campaign(must_get("campaign", cid)), 200)


def _advance_allocated(rec):
    if rec["status"] != "PROPOSED":
        err("ERR_INVALID_CAMPAIGN_STATE", "ALLOCATED requires current status PROPOSED")
    product = store.get("products", rec["product_id"])
    calc_capacity.check_window_conflict(  # window re-check before capacity
        rec["train_id"], product, rec["planned_start_utc"], rec["planned_end_utc"],
        exclude_id=rec["id"])
    train = store.get("trains", rec["train_id"])
    site = store.get("sites", train["site_id"])
    calc_capacity.capacity_waterfall(site, rec)
    rec["status"] = "ALLOCATED"


def _advance_proposed(rec):
    if rec["status"] != "ALLOCATED":
        err("ERR_INVALID_CAMPAIGN_STATE", "De-allocation requires current status ALLOCATED")
    rec["status"] = "PROPOSED"  # firm hours released: PROPOSED consumes nothing


def _advance_seed_in_progress(rec):
    if rec["status"] != "ALLOCATED":
        err("ERR_INVALID_CAMPAIGN_STATE", "SEED_IN_PROGRESS requires ALLOCATED")
    if clock.now() < rec["planned_start_utc"]:
        err("ERR_CAMPAIGN_START_TOO_EARLY", "Logical clock is before planned_start_utc")
    stages = [s for s in store.all_recs("seed_stages") if s["campaign_id"] == rec["id"]]
    if not stages:
        err("ERR_NO_SEED_STAGES_DEFINED", "Seed-train start requires a defined stage")
    train = store.get("trains", rec["train_id"])
    product = store.get("products", rec["product_id"])
    calc_capacity.check_material_coverage(train["site_id"], product)
    calc_capacity.consume_materials(train["site_id"], product)
    rec["status"] = "SEED_IN_PROGRESS"


def _advance_production_in_progress(rec):
    if rec["status"] != "SEED_IN_PROGRESS":
        err("ERR_INVALID_CAMPAIGN_STATE", "PRODUCTION_IN_PROGRESS requires SEED_IN_PROGRESS")
    stages = [s for s in store.all_recs("seed_stages") if s["campaign_id"] == rec["id"]]
    if not stages or any(s["status"] != "COMPLETED" for s in stages):
        err("ERR_SEED_STAGES_INCOMPLETE", "Every seed stage must be COMPLETED")
    last_completed = max(s["completed_at"] for s in stages)
    if clock.hours_between(last_completed, clock.now()) > INOCULATION_WINDOW_HOURS:
        top = max(stages, key=lambda s: s["stage_index"])
        top["status"] = "EXPIRED"  # highest-indexed stage flips to EXPIRED
        store.touch(top)
        err("ERR_SEED_INOCULATION_WINDOW_EXPIRED",
            "More than 24 hours elapsed since the last seed stage completed")
    rec["status"] = "PRODUCTION_IN_PROGRESS"


@bp.route("/campaigns/<cid>/advance", methods=["POST"])
def advance_campaign(cid):
    require_auth(("ProcessEngineer",))
    rec = must_get("campaign", cid)
    d = body()
    target = action_value(d, "to_status", CAMPAIGN_ADVANCE_TARGETS)
    if target == "ALLOCATED":
        _advance_allocated(rec)
    elif target == "PROPOSED":
        _advance_proposed(rec)
    elif target == "SEED_IN_PROGRESS":
        _advance_seed_in_progress(rec)
    else:
        _advance_production_in_progress(rec)
    store.touch(rec)
    return envelope.ok(serialize.campaign(rec), 200)
