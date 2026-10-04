"""CapitalNeedItem endpoints: create/list/get, schedule, execute, split, cancel."""
from flask import Blueprint

import db
from calculations import recompute_estimates
from errors import ApiError
from middleware import (
    current_user, require_roles, require_fields, require_int, require_enum,
    require_str,
)
from models import new_capital_item, touch, base_record, midpoint
from response import success_obj, success_list, json_body, parse_pagination, paginate
from routes_assessments import get_assessment_or_404
from util import (
    ALL_ROLES, CAPITAL_CATEGORIES, CAPITAL_HORIZONS, MAX_CREWS_PER_TARGET,
    parse_iso, get_clock,
)

bp = Blueprint("capital_items", __name__)


def get_capital_item_or_404(item_id):
    item = db.capital_items.get(item_id)
    if item is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CapitalNeedItem not found")
    return item


def _target_of(item):
    assessment = db.assessments[item["assessment_id"]]
    return db.targets[assessment["target_id"]], assessment


@bp.route("/acquisitions/assessments/<assessment_id>/capital-items", methods=["POST"])
def create_capital_item(assessment_id):
    _, role = current_user()
    require_roles(role, ["AcquisitionAnalyst"])
    assessment = get_assessment_or_404(assessment_id)
    if assessment["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment is not in DRAFT")
    body = json_body()
    require_fields(body, ["category", "horizon", "description",
                          "cost_low_cents", "cost_high_cents", "crews_required"])
    require_enum(body, "category", CAPITAL_CATEGORIES)
    require_enum(body, "horizon", CAPITAL_HORIZONS)
    require_str(body, "description")
    low = require_int(body, "cost_low_cents", minimum=0)
    high = require_int(body, "cost_high_cents", minimum=0)
    if high < low:
        raise ApiError("ERR_INVALID_REQUEST", 422, "cost_high_cents must be >= cost_low_cents")
    require_int(body, "crews_required", minimum=1)
    item = new_capital_item(assessment_id, body)
    recompute_estimates(assessment)
    return success_obj(item, status=201)


@bp.route("/acquisitions/assessments/<assessment_id>/capital-items", methods=["GET"])
def list_capital_items(assessment_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    get_assessment_or_404(assessment_id)
    limit, offset = parse_pagination()
    records = sorted(db.capital_items_of_assessment(assessment_id),
                     key=lambda i: (i["created_at"], i["id"]))
    page, total = paginate(records, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/acquisitions/capital-items/<item_id>", methods=["GET"])
def get_capital_item(item_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    return success_obj(get_capital_item_or_404(item_id))


@bp.route("/acquisitions/capital-items/<item_id>/schedule", methods=["POST"])
def schedule_capital_item(item_id):
    _, role = current_user()
    require_roles(role, ["TransitionManager"])
    item = get_capital_item_or_404(item_id)
    target, assessment = _target_of(item)
    # Priority 5: state checks before window sanity (priority 6).
    if item["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Item is not in PLANNED")
    if assessment["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment is not ACCEPTED")
    if target["status"] in ("SCREENING", "REJECTED", "INTEGRATED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Target is not in VALUATION or a later non-terminal status")
    body = json_body()
    require_fields(body, ["window_start", "window_end"])
    start = parse_iso(body.get("window_start"))
    end = parse_iso(body.get("window_end"))
    if start is None or end is None:
        raise ApiError("ERR_INVALID_REQUEST", 422,
                       "window_start/window_end must be ISO 8601 timestamps")
    if not end > start:
        raise ApiError("ERR_INVALID_WINDOW", 422, "window_end must be strictly after window_start")
    # Priority 9: crew capacity, half-open windows. Sweep event endpoints.
    siblings = [i for i in db.capital_items_of_target(target["id"])
                if i["status"] == "SCHEDULED" and i["id"] != item["id"]]
    points = {start, end}
    for s in siblings:
        s_start = parse_iso(s["window_start"])
        s_end = parse_iso(s["window_end"])
        if s_start < end and start < s_end:
            points.add(max(start, s_start))
            points.add(min(end, s_end))
    for point in points:
        if not (start <= point < end):
            continue
        demand = item["crews_required"]
        for s in siblings:
            s_start = parse_iso(s["window_start"])
            s_end = parse_iso(s["window_end"])
            if s_start <= point < s_end:
                demand += s["crews_required"]
        if demand > MAX_CREWS_PER_TARGET:
            raise ApiError("ERR_CREW_CAPACITY_EXCEEDED", 409,
                           "Concurrent crew demand would exceed %d" % MAX_CREWS_PER_TARGET)
    item["window_start"] = body["window_start"]
    item["window_end"] = body["window_end"]
    item["status"] = "SCHEDULED"
    touch(item)
    return success_obj(item)


@bp.route("/acquisitions/capital-items/<item_id>/execute", methods=["POST"])
def execute_capital_item(item_id):
    _, role = current_user()
    require_roles(role, ["TransitionManager"])
    item = get_capital_item_or_404(item_id)
    target, _ = _target_of(item)
    if item["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Item is not in SCHEDULED")
    if target["status"] not in ("CLOSING", "INTEGRATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Target is not in CLOSING or INTEGRATED")
    if get_clock() < parse_iso(item["window_start"]):
        raise ApiError("ERR_WINDOW_NOT_OPEN", 409, "Logical clock is before window_start")
    item["status"] = "EXECUTED"
    touch(item)
    return success_obj(item)


@bp.route("/acquisitions/capital-items/<item_id>/split", methods=["POST"])
def split_capital_item(item_id):
    _, role = current_user()
    require_roles(role, ["AcquisitionAnalyst"])
    item = get_capital_item_or_404(item_id)
    _, assessment = _target_of(item)
    if item["status"] != "PLANNED" or assessment["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Item must be PLANNED and its assessment DRAFT")
    body = json_body()
    require_fields(body, ["split_low_cents", "split_high_cents"])
    split_low = require_int(body, "split_low_cents")
    split_high = require_int(body, "split_high_cents")
    if (split_low < 0 or split_low > item["cost_low_cents"]
            or split_high < 0 or split_high > item["cost_high_cents"]):
        raise ApiError("ERR_INVALID_SPLIT", 422,
                       "Split amounts must be non-negative and within parent bounds")
    child_specs = [
        (split_low, split_high),
        (item["cost_low_cents"] - split_low, item["cost_high_cents"] - split_high),
    ]
    for low, high in child_specs:
        child = base_record()
        child.update({
            "assessment_id": item["assessment_id"],
            "category": item["category"],
            "horizon": item["horizon"],
            "description": item["description"],
            "cost_low_cents": low,
            "cost_high_cents": high,
            "midpoint_estimate_cents": midpoint(low, high),
            "crews_required": item["crews_required"],
            "window_start": None,
            "window_end": None,
            "status": "PLANNED",
        })
        db.capital_items[child["id"]] = child
    item["status"] = "SPLIT"
    touch(item)
    recompute_estimates(assessment)
    return success_obj(item)


@bp.route("/acquisitions/capital-items/<item_id>/cancel", methods=["POST"])
def cancel_capital_item(item_id):
    _, role = current_user()
    require_roles(role, ["AcquisitionAnalyst"])
    item = get_capital_item_or_404(item_id)
    _, assessment = _target_of(item)
    if item["status"] != "PLANNED" or assessment["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Item must be PLANNED and its assessment DRAFT")
    item["status"] = "CANCELLED"
    touch(item)
    recompute_estimates(assessment)
    return success_obj(item)
