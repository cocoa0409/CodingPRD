"""Delivery years, zones, forecasts routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, require_any
from response import success_object, success_list
from util import (base_entity, stamp, touch, parse_dt, dec, q3, paginate,
                  sort_created, strip_internal, require_fields, is_number, get_body)
from errors import (err_not_found, err_invalid_request, err_invalid_state,
                    err_invalid_time_range, err_forecast_shares)
from services.calcs import peak_load_requirement

bp = Blueprint("delivery_years", __name__)


def _serialize_dy(dy):
    out = strip_internal(dy)
    return out


def _serialize_zone(z):
    return strip_internal(z)


def _serialize_forecast(f):
    return strip_internal(f)


@bp.route("/capacity-market/delivery-years", methods=["POST"])
def create_delivery_year():
    require_roles("MarketAdmin")
    body = get_body()
    require_fields(body, ["delivery_year_label", "planning_period_start", "planning_period_end"])
    label = body["delivery_year_label"]
    if not isinstance(label, str) or not label.strip():
        raise err_invalid_request("delivery_year_label must be a non-empty string")
    # business: uniqueness of label
    for existing in db.delivery_years.values():
        if existing["delivery_year_label"] == label:
            raise err_invalid_request("delivery_year_label must be unique")
    start = parse_dt(body["planning_period_start"], "planning_period_start")
    end = parse_dt(body["planning_period_end"], "planning_period_end")
    if end <= start:
        raise err_invalid_time_range("planning_period_end must be after planning_period_start")
    dy = base_entity()
    dy.update({
        "delivery_year_label": label,
        "planning_period_start": body["planning_period_start"],
        "planning_period_end": body["planning_period_end"],
        "status": "DRAFT",
        "reliability_requirement_mw": 0,
        "forecast_version": 0,
        "_start_dt": start,
        "_end_dt": end,
    })
    db.delivery_years[dy["id"]] = dy
    return success_object(_serialize_dy(dy), 201)


@bp.route("/capacity-market/delivery-years", methods=["GET"])
def list_delivery_years():
    require_any()
    items = list(db.delivery_years.values())
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize_dy(d) for d in page], limit, offset, total)


@bp.route("/capacity-market/delivery-years/<dy_id>", methods=["GET"])
def get_delivery_year(dy_id):
    require_any()
    dy = db.delivery_years.get(dy_id)
    if dy is None:
        raise err_not_found("delivery year not found")
    return success_object(_serialize_dy(dy))


@bp.route("/capacity-market/delivery-years/<dy_id>/lock-forecast", methods=["POST"])
def lock_forecast(dy_id):
    require_roles("MarketAdmin")
    dy = db.delivery_years.get(dy_id)
    if dy is None:
        raise err_not_found("delivery year not found")
    if dy["status"] != "DRAFT":
        raise err_invalid_state("delivery year is not in DRAFT")
    drafts = [f for f in db.forecasts.values()
              if f["delivery_year_id"] == dy_id and f["status"] == "DRAFT"]
    if len(drafts) != 1:
        raise err_invalid_state("exactly one DRAFT forecast (highest revision) is required to lock")
    forecast = drafts[0]
    zones = [z for z in db.zones.values() if z["delivery_year_id"] == dy_id]
    if not zones:
        raise err_invalid_state("at least one zone must exist")
    if not any(z.get("parent_zone_id") is None for z in zones):
        raise err_invalid_state("the RTO-wide zone (parent_zone_id null) must exist")

    peak_load_requirement(dy, forecast)  # may raise ERR_FORECAST_SHARES_INVALID

    # state transitions
    for f in db.forecasts.values():
        if f["delivery_year_id"] == dy_id and f["status"] == "LOCKED":
            f["status"] = "SUPERSEDED"
            touch(f)
    forecast["status"] = "LOCKED"
    touch(forecast)
    dy["status"] = "FORECAST_LOCKED"
    touch(dy)
    return success_object(_serialize_dy(dy))


@bp.route("/capacity-market/delivery-years/<dy_id>/settle", methods=["POST"])
def settle_delivery_year(dy_id):
    require_roles("SettlementOps")
    dy = db.delivery_years.get(dy_id)
    if dy is None:
        raise err_not_found("delivery year not found")
    if dy["status"] != "CLEARED":
        raise err_invalid_state("delivery year is not in CLEARED")
    events = [e for e in db.emergency_events.values() if e["delivery_year_id"] == dy_id]
    for e in events:
        if e["status"] not in ("ASSESSED", "SETTLED"):
            raise err_invalid_state("all emergency events must be ASSESSED or SETTLED")
    assessments = [a for a in db.assessments.values()
                   if db.emergency_events.get(a["emergency_event_id"], {}).get("delivery_year_id") == dy_id]
    for a in assessments:
        if a["status"] != "FINALIZED":
            raise err_invalid_state("all performance assessments must be FINALIZED")
    dy_commitments = [c for c in db.commitments.values() if c["delivery_year_id"] == dy_id]
    dy_commit_ids = {c["id"] for c in dy_commitments}
    for r in db.replacements.values():
        if r["commitment_id"] in dy_commit_ids and r["status"] == "PENDING":
            raise err_invalid_state("a replacement transaction is still PENDING")

    from services.calcs import redistribution_pool
    for e in events:
        if e["status"] == "ASSESSED":
            redistribution_pool(e)
            e["status"] = "SETTLED"
            touch(e)
    for c in dy_commitments:
        if c["status"] == "ACTIVE":
            c["status"] = "SETTLED"
            touch(c)
    for run in db.auction_runs.values():
        if run["delivery_year_id"] == dy_id and run["status"] == "CLEARED":
            run["status"] = "SETTLED"
            touch(run)
    dy["status"] = "SETTLED"
    touch(dy)
    return success_object(_serialize_dy(dy))


@bp.route("/capacity-market/delivery-years/<dy_id>/close", methods=["POST"])
def close_delivery_year(dy_id):
    require_roles("SettlementOps")
    dy = db.delivery_years.get(dy_id)
    if dy is None:
        raise err_not_found("delivery year not found")
    if dy["status"] != "SETTLED":
        raise err_invalid_state("delivery year is not in SETTLED")
    dy["status"] = "CLOSED"
    touch(dy)
    return success_object(_serialize_dy(dy))


# ---------------- Zones ----------------

@bp.route("/capacity-market/delivery-years/<dy_id>/zones", methods=["POST"])
def create_zone(dy_id):
    require_roles("MarketAdmin")
    dy = db.delivery_years.get(dy_id)
    if dy is None:
        raise err_not_found("delivery year not found")
    body = get_body()
    require_fields(body, ["zone_code"])
    zone_code = body["zone_code"]
    if not isinstance(zone_code, str) or not zone_code.strip():
        raise err_invalid_request("zone_code must be a non-empty string")
    parent_zone_id = body.get("parent_zone_id")
    import_limit = body.get("import_limit_mw")

    # business: zone_code unique within delivery year; parent must exist in same DY
    for z in db.zones.values():
        if z["delivery_year_id"] == dy_id and z["zone_code"] == zone_code:
            raise err_invalid_request("zone_code must be unique within the delivery year")
    if parent_zone_id is not None:
        parent = db.zones.get(parent_zone_id)
        if parent is None or parent["delivery_year_id"] != dy_id:
            raise err_invalid_request("parent_zone_id must reference a Zone in the same delivery year")
    if import_limit is not None:
        if not is_number(import_limit) or dec(import_limit) <= 0:
            raise err_invalid_request("import_limit_mw must be > 0 when present")
    z = base_entity()
    z.update({
        "delivery_year_id": dy_id,
        "zone_code": zone_code,
        "parent_zone_id": parent_zone_id,
        "import_limit_mw": dec(import_limit) if import_limit is not None else None,
        "zonal_requirement_mw": 0,
        "clearing_price_per_mw_day": None,
        "cleared_mw": 0,
    })
    db.zones[z["id"]] = z
    return success_object(_serialize_zone(z), 201)


@bp.route("/capacity-market/delivery-years/<dy_id>/zones", methods=["GET"])
def list_zones_of_year(dy_id):
    require_any()
    dy = db.delivery_years.get(dy_id)
    if dy is None:
        raise err_not_found("delivery year not found")
    items = sort_created([z for z in db.zones.values() if z["delivery_year_id"] == dy_id])
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize_zone(z) for z in page], limit, offset, total)


@bp.route("/capacity-market/zones", methods=["GET"])
def list_zones():
    require_any()
    items = list(db.zones.values())
    dy_filter = request.args.get("delivery_year_id")
    parent_filter = request.args.get("parent_zone_id")
    if dy_filter:
        items = [z for z in items if z["delivery_year_id"] == dy_filter]
    if parent_filter:
        items = [z for z in items if z.get("parent_zone_id") == parent_filter]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize_zone(z) for z in page], limit, offset, total)


@bp.route("/capacity-market/zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    require_any()
    z = db.zones.get(zone_id)
    if z is None:
        raise err_not_found("zone not found")
    return success_object(_serialize_zone(z))


# ---------------- Forecasts ----------------

@bp.route("/capacity-market/delivery-years/<dy_id>/forecasts", methods=["POST"])
def create_forecast(dy_id):
    require_roles("MarketAdmin")
    dy = db.delivery_years.get(dy_id)
    if dy is None:
        raise err_not_found("delivery year not found")
    body = get_body()
    require_fields(body, ["rto_peak_load_mw", "reserve_margin_pct",
                          "pool_wide_avg_eford", "zonal_peak_shares"])
    rto_peak = body["rto_peak_load_mw"]
    rm = body["reserve_margin_pct"]
    eford = body["pool_wide_avg_eford"]
    shares = body["zonal_peak_shares"]

    # business: shares validation (priority 12) before request-shape (priority 20)
    if not isinstance(shares, dict):
        raise err_invalid_request("zonal_peak_shares must be an object")
    top_zones = [z for z in db.zones.values()
                 if z["delivery_year_id"] == dy_id and z.get("parent_zone_id") is None]
    for z in top_zones:
        if z["zone_code"] not in shares:
            raise err_forecast_shares("zonal_peak_shares missing top-level zone " + z["zone_code"])
    if top_zones:
        total = 0
        for z in top_zones:
            v = shares[z["zone_code"]]
            if not is_number(v):
                raise err_forecast_shares("zonal_peak_shares values must be numbers")
            total += float(q3(dec(v)))
        if abs(total - 1.0) > 1e-9:
            raise err_forecast_shares("zonal_peak_shares must sum to exactly 1.000")

    if not is_number(rto_peak) or dec(rto_peak) <= 0:
        raise err_invalid_request("rto_peak_load_mw must be > 0")
    if not is_number(rm) or not (dec(rm) > 0 and dec(rm) < 1):
        raise err_invalid_request("reserve_margin_pct must be in (0,1)")
    if not is_number(eford) or not (dec(eford) >= 0 and dec(eford) < 1):
        raise err_invalid_request("pool_wide_avg_eford must be in [0,1)")

    revision = max([f["revision"] for f in db.forecasts.values()
                    if f["delivery_year_id"] == dy_id], default=0) + 1
    f = base_entity()
    f.update({
        "delivery_year_id": dy_id,
        "revision": revision,
        "rto_peak_load_mw": dec(rto_peak),
        "reserve_margin_pct": dec(rm),
        "pool_wide_avg_eford": dec(eford),
        "zonal_peak_shares": shares,
        "status": "DRAFT",
    })
    db.forecasts[f["id"]] = f
    return success_object(_serialize_forecast(f), 201)


@bp.route("/capacity-market/delivery-years/<dy_id>/forecasts", methods=["GET"])
def list_forecasts(dy_id):
    require_any()
    dy = db.delivery_years.get(dy_id)
    if dy is None:
        raise err_not_found("delivery year not found")
    items = [f for f in db.forecasts.values() if f["delivery_year_id"] == dy_id]
    status = request.args.get("status")
    if status:
        items = [f for f in items if f["status"] == status]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize_forecast(f) for f in page], limit, offset, total)
