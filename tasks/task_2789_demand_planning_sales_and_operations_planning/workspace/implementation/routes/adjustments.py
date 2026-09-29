"""Consensus adjustments: proposal, review, resubmission (PRD 3.4)."""
from flask import Blueprint, g

from auth import (ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
                  ROLE_EXECUTIVE_SPONSOR, ROLE_SOP_ADMIN, ROLE_SUPPLY_PLANNER,
                  check_frozen, check_phase_actor, check_phase_closed,
                  check_sod, endpoint, find_or_404)
from calcs import (MAX_REVISION_ROUNDS, calc_applied_delta, rollup_consensus,
                   swing_ceiling)
from cascades import void_adjustment
from envelope import respond_list, respond_object
from errors import ApiError
from store import new_row, ordered, public, public_all, store, touch
from validators import (forbid, get_body, opt_int, opt_string, paginate,
                        pagination, query_enum, query_str, req_enum, req_id,
                        req_int, req_string)

bp = Blueprint("adjustments", __name__)

READ_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
              ROLE_SUPPLY_PLANNER, ROLE_EXECUTIVE_SPONSOR]

ADJUSTMENT_TYPES = ("SALES_INTELLIGENCE", "PROMOTION", "NEW_ITEM_PLAN")
ADJUSTMENT_STATUSES = ("PROPOSED", "REVISION_REQUESTED", "ENDORSED",
                       "COMMITTED", "REJECTED", "VOIDED")
DECISIONS = ("ENDORSE", "REJECT", "REQUEST_REVISION")


def _governing_cycle(forecast):
    return store.cycles.get(forecast["cycle_id"])


def _check_swing(forecast, applied_delta_units):
    ceiling = swing_ceiling(forecast["baseline_units"])
    if abs(applied_delta_units) > ceiling:
        raise ApiError("ERR_ADJUSTMENT_SWING_EXCEEDED",
                       "An applied delta of %d exceeds the swing ceiling of %d"
                       % (applied_delta_units, ceiling))


@bp.post("/sop/consensus-adjustments")
@endpoint([ROLE_DEMAND_PLANNER])
def create_adjustment():
    body = get_body()
    demand_forecast_id = req_id(body, "demand_forecast_id")
    adjustment_type = req_enum(body, "adjustment_type", ADJUSTMENT_TYPES)
    delta_units = req_int(body, "delta_units")
    rationale = req_string(body, "rationale")
    if adjustment_type == "PROMOTION":
        promotion_id = req_id(body, "promotion_id")
    else:
        forbid(body, "promotion_id",
               "promotion_id is only accepted for a PROMOTION adjustment")
        promotion_id = None
    expected_version = req_int(body, "expected_demand_forecast_version")

    forecast = find_or_404("forecasts", demand_forecast_id,
                           "ERR_FORECAST_NOT_FOUND")
    promotion = None
    if promotion_id is not None:
        promotion = find_or_404("promotions", promotion_id,
                                "ERR_PROMOTION_NOT_FOUND")

    cycle = _governing_cycle(forecast)
    item = store.items.get(forecast["item_id"])

    if cycle is not None:
        check_phase_actor(cycle, "DEMAND_REVIEW")
    if expected_version != forecast["version"]:
        raise ApiError("ERR_STALE_FORECAST_VERSION",
                       "The forecast line is at version %d, not %d"
                       % (forecast["version"], expected_version))
    if cycle is not None:
        check_frozen(cycle)
        check_phase_closed(cycle, "DEMAND_REVIEW")

    # priority 130 -- cross-entity referential eligibility
    if adjustment_type == "PROMOTION":
        if (promotion["status"] != "APPROVED"
                or promotion["item_id"] != forecast["item_id"]):
            raise ApiError("ERR_PROMOTION_NOT_APPROVED",
                           "The cited promotion is not an approved promotion "
                           "of this forecast line's item")
    elif adjustment_type == "NEW_ITEM_PLAN":
        if item is None or item["lifecycle_state"] not in ("PRELAUNCH", "RAMP"):
            raise ApiError("ERR_ADJUSTMENT_TYPE_NOT_PERMITTED",
                           "NEW_ITEM_PLAN is permitted only on a PRELAUNCH or "
                           "RAMP item")
    else:
        if item is not None and item["lifecycle_state"] == "PRELAUNCH":
            raise ApiError("ERR_ADJUSTMENT_TYPE_NOT_PERMITTED",
                           "SALES_INTELLIGENCE is forbidden on a PRELAUNCH item")

    applied_delta_units = calc_applied_delta(adjustment_type, delta_units,
                                            forecast, item, promotion)
    _check_swing(forecast, applied_delta_units)

    row = new_row()
    row.update({
        "demand_forecast_id": demand_forecast_id,
        "promotion_id": promotion_id,
        "adjustment_type": adjustment_type,
        "delta_units": delta_units,
        "applied_delta_units": applied_delta_units,
        "rationale": rationale,
        "status": "PROPOSED",
        "revision_round": 0,
        "proposed_by_user_id": g.user_id,
        "reviewed_by_user_id": None,
        "review_note": None,
    })

    # Supersede the proposer's earlier outstanding proposal of the same type.
    for other in ordered([a for a in store.adjustments.values()
                          if a["demand_forecast_id"] == demand_forecast_id]):
        if (other["status"] == "PROPOSED"
                and other["adjustment_type"] == adjustment_type
                and other["proposed_by_user_id"] == g.user_id):
            void_adjustment(other, recompute_line=False)

    store.adjustments[row["id"]] = row

    if forecast["status"] == "BASELINE":
        forecast["status"] = "UNDER_CONSENSUS"
    rollup_consensus(forecast)
    touch(forecast)

    return respond_object(public(row), 201)


@bp.post("/sop/consensus-adjustments/<adjustment_id>/reviews")
@endpoint([ROLE_DEMAND_REVIEW_LEAD])
def review_adjustment(adjustment_id):
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    review_note = opt_string(body, "review_note", allow_empty=True)

    adjustment = find_or_404("adjustments", adjustment_id,
                             "ERR_ADJUSTMENT_NOT_FOUND")
    forecast = store.forecasts.get(adjustment["demand_forecast_id"])
    cycle = _governing_cycle(forecast) if forecast is not None else None

    if cycle is not None:
        check_phase_actor(cycle, "DEMAND_REVIEW")
    check_sod(adjustment["proposed_by_user_id"], "proposed this adjustment")
    if cycle is not None:
        check_frozen(cycle)
        check_phase_closed(cycle, "DEMAND_REVIEW")

    if adjustment["status"] != "PROPOSED":
        raise ApiError("ERR_ADJUSTMENT_NOT_REVIEWABLE",
                       "An adjustment in %s may not be reviewed"
                       % adjustment["status"])

    adjustment["reviewed_by_user_id"] = g.user_id
    if decision == "ENDORSE":
        adjustment["status"] = "ENDORSED"
    elif decision == "REJECT":
        adjustment["status"] = "REJECTED"
    else:
        adjustment["status"] = "REVISION_REQUESTED"
        adjustment["review_note"] = review_note
    touch(adjustment)

    if decision == "ENDORSE" and forecast is not None:
        rollup_consensus(forecast)
        touch(forecast)

    return respond_object(public(adjustment))


@bp.post("/sop/consensus-adjustments/<adjustment_id>/resubmit")
@endpoint([ROLE_DEMAND_PLANNER])
def resubmit_adjustment(adjustment_id):
    body = get_body()
    rationale = req_string(body, "rationale")
    delta_units = opt_int(body, "delta_units")
    expected_version = req_int(body, "expected_demand_forecast_version")

    adjustment = find_or_404("adjustments", adjustment_id,
                             "ERR_ADJUSTMENT_NOT_FOUND")
    forecast = store.forecasts.get(adjustment["demand_forecast_id"])
    cycle = _governing_cycle(forecast) if forecast is not None else None

    if cycle is not None:
        check_phase_actor(cycle, "DEMAND_REVIEW")
    if forecast is not None and expected_version != forecast["version"]:
        raise ApiError("ERR_STALE_FORECAST_VERSION",
                       "The forecast line is at version %d, not %d"
                       % (forecast["version"], expected_version))
    if cycle is not None:
        check_frozen(cycle)
        check_phase_closed(cycle, "DEMAND_REVIEW")

    if adjustment["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_ADJUSTMENT_NOT_RESUBMITTABLE",
                       "An adjustment in %s may not be resubmitted"
                       % adjustment["status"])

    if adjustment["revision_round"] >= MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED",
                       "The adjustment has already been revised %d times"
                       % MAX_REVISION_ROUNDS)

    effective_delta = (adjustment["delta_units"] if delta_units is None
                       else delta_units)
    item = store.items.get(forecast["item_id"]) if forecast is not None else None
    promotion = (store.promotions.get(adjustment["promotion_id"])
                 if adjustment["promotion_id"] is not None else None)
    applied_delta_units = calc_applied_delta(adjustment["adjustment_type"],
                                            effective_delta, forecast, item,
                                            promotion)
    _check_swing(forecast, applied_delta_units)

    adjustment["revision_round"] += 1
    adjustment["delta_units"] = effective_delta
    adjustment["rationale"] = rationale
    adjustment["applied_delta_units"] = applied_delta_units
    adjustment["reviewed_by_user_id"] = None
    adjustment["review_note"] = None
    adjustment["status"] = "PROPOSED"
    touch(adjustment)

    if forecast is not None:
        rollup_consensus(forecast)
        touch(forecast)

    return respond_object(public(adjustment))


@bp.get("/sop/consensus-adjustments/<adjustment_id>")
@endpoint(READ_ROLES)
def get_adjustment(adjustment_id):
    row = find_or_404("adjustments", adjustment_id, "ERR_ADJUSTMENT_NOT_FOUND")
    return respond_object(public(row))


@bp.get("/sop/consensus-adjustments")
@endpoint(READ_ROLES)
def list_adjustments():
    limit, offset = pagination()
    demand_forecast_id = query_str("demand_forecast_id")
    promotion_id = query_str("promotion_id")
    status = query_enum("status", ADJUSTMENT_STATUSES)
    adjustment_type = query_enum("adjustment_type", ADJUSTMENT_TYPES)
    rows = ordered(store.adjustments.values())
    if demand_forecast_id is not None:
        rows = [r for r in rows if r["demand_forecast_id"] == demand_forecast_id]
    if promotion_id is not None:
        rows = [r for r in rows if r["promotion_id"] == promotion_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if adjustment_type is not None:
        rows = [r for r in rows if r["adjustment_type"] == adjustment_type]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)
