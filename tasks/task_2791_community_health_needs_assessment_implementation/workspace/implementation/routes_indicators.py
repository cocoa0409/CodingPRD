"""Health indicators and their observations, including the void cascade entry point."""

from datetime import date

from flask import Blueprint

import consts as K
import derive as D
from core import (authenticate, body_or_empty, db, fail, filter_eq, new_record,
                  ok, ok_list, paginate, public, sorted_asc, touch, v_date,
                  v_enum, v_num, v_str, clock_date)

bp = Blueprint("indicators", __name__)


@bp.post("/health-indicators")
def create_indicator():
    authenticate([K.CBO, K.DS])
    body = body_or_empty()
    cycle_id = v_str(body, "cycle_id", 1, None)
    domain = v_enum(body, "domain", K.DOMAINS)
    name = v_str(body, "name", 1, 160)
    benchmark = v_num(body, "benchmark_value", 0, None, places=4, exclusive_lo=True)

    cycle = D.cycle_or_404(cycle_id)
    D.gate_child_write(cycle, restricted=True)
    if cycle["status"] != "DATA_COLLECTION":
        fail("ERR_INVALID_STATE")
    for existing in db.indicators.values():
        if existing["cycle_id"] == cycle["id"] and existing["name"] == name:
            fail("ERR_DUPLICATE_INDICATOR_NAME")

    rec = new_record()
    rec.update({
        "cycle_id": cycle["id"],
        "domain": domain,
        "name": name,
        "benchmark_value": benchmark,
        "latest_overall_value": None,
        "severity_score": None,
        "disparity_ratio": None,
        "subgroup_count": 0,
        "evidence_count": 0,
        "data_state": "INSUFFICIENT",
    })
    db.indicators[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/health-indicators")
def list_indicators():
    authenticate([K.CBO, K.DS, K.BC, K.CO])
    rows = list(db.indicators.values())
    rows = filter_eq(rows, "cycle_id")
    rows = filter_eq(rows, "domain")
    rows = filter_eq(rows, "data_state")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/health-indicators/<indicator_id>")
def get_indicator(indicator_id):
    authenticate([K.CBO, K.DS, K.BC, K.CO])
    return ok(public(D.indicator_or_404(indicator_id)))


@bp.post("/health-indicators/<indicator_id>/data-points")
def create_data_point(indicator_id):
    _user, _role = authenticate([K.DS])
    indicator = D.indicator_or_404(indicator_id)
    body = body_or_empty()
    subgroup = v_str(body, "population_subgroup", 1, 60)
    source_type = v_enum(body, "source_type", K.SOURCE_TYPES)
    value = v_num(body, "value", 0, None, places=4, exclusive_lo=True)
    collected_on = v_date(body, "collected_on")

    cycle = D.cycle_of_indicator(indicator)
    D.gate_child_write(cycle, restricted=True)
    if cycle is None or cycle["status"] != "DATA_COLLECTION":
        fail("ERR_INVALID_STATE")

    window_start = date(cycle["fiscal_year"] - 3, 1, 1)
    if collected_on < window_start or collected_on > clock_date():
        fail("ERR_DATA_POINT_OUT_OF_WINDOW")

    rec = new_record()
    rec.update({
        "indicator_id": indicator["id"],
        "population_subgroup": subgroup,
        "source_type": source_type,
        "value": value,
        "collected_on": collected_on.isoformat(),
        "status": "ACTIVE",
        "void_reason": None,
        "voided_by_user_id": None,
    })
    db.data_points[rec["id"]] = rec
    D.recompute_indicator(indicator)
    D.sync_cycle(cycle)
    return ok(public(rec), 201)


@bp.get("/health-indicators/<indicator_id>/data-points")
def list_indicator_data_points(indicator_id):
    authenticate([K.CBO, K.DS, K.CO])
    indicator = D.indicator_or_404(indicator_id)
    rows = [d for d in db.data_points.values() if d["indicator_id"] == indicator["id"]]
    rows = filter_eq(rows, "status")
    rows = filter_eq(rows, "population_subgroup")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/indicator-data-points")
def list_data_points():
    authenticate([K.CBO, K.DS, K.CO])
    rows = list(db.data_points.values())
    rows = filter_eq(rows, "indicator_id")
    rows = filter_eq(rows, "status")
    rows = filter_eq(rows, "population_subgroup")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/indicator-data-points/<data_point_id>")
def get_data_point(data_point_id):
    authenticate([K.CBO, K.DS, K.CO])
    return ok(public(D.data_point_or_404(data_point_id)))


@bp.post("/indicator-data-points/<data_point_id>/void")
def void_data_point(data_point_id):
    user_id, _role = authenticate([K.DS])
    dp = D.data_point_or_404(data_point_id)
    body = body_or_empty()
    reason = v_str(body, "reason", 1, None)

    indicator = db.indicators.get(dp["indicator_id"])
    cycle = D.cycle_of_indicator(indicator) if indicator else None
    # A data-quality correction is exempt from the RESTRICTED gate but not FROZEN.
    D.gate_frozen(cycle)
    if dp["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")

    dp["void_reason"] = reason
    dp["voided_by_user_id"] = user_id
    dp["status"] = "VOID"
    touch(dp)
    D.void_cascade(dp)
    return ok(public(dp))
