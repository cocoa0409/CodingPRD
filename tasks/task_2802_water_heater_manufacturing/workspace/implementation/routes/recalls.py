"""Recall campaigns and serial-based remedy tracking (PRD 3.9)."""

from flask import Blueprint

import db
import response
import serializers
import validation
from db import make_row, ordered, touch
from errors import ApiError
from middleware import endpoint
from services import calc
from services.core import (
    hold_unit,
    recall_population,
    require_unique,
    resolve,
    restrict_model_if_released,
    rows,
)

bp = Blueprint("recalls", __name__)

REMEDY_TYPES = ("TANK_REPLACEMENT", "GAS_VALVE_KIT", "TP_VALVE_KIT", "FULL_UNIT_REPLACEMENT")
CAMPAIGN_STATUSES = ("DRAFT", "SCOPED", "ANNOUNCED", "IN_REMEDY", "CLOSED", "CANCELLED")
NOTICE_STATUSES = ("PENDING", "NOTIFIED", "REMEDIED", "UNREACHABLE")
COMPLETION_THRESHOLD = calc.D("80.00")

READ_ROLES = ["WarrantyAnalyst", "PlantAdmin", "ComplianceEngineer"]


@bp.post("/recall-campaigns")
@endpoint(["WarrantyAnalyst"])
def create_campaign():
    body = validation.json_body()
    campaign_code = validation.string(body, "campaign_code", max_length=20)
    scope_product_model_id = validation.string(body, "scope_product_model_id")
    remedy_type = validation.enum(body, "remedy_type", REMEDY_TYPES)
    budget_cents = validation.integer(body, "budget_cents", minimum=0)

    model = resolve("model", scope_product_model_id)
    require_unique("campaign", "campaign_code", campaign_code)

    row = make_row(
        {
            "campaign_code": campaign_code,
            "scope_product_model_id": model["id"],
            "remedy_type": remedy_type,
            "budget_cents": budget_cents,
            "serial_range_start": None,
            "serial_range_end": None,
            "affected_unit_count": None,
            "per_unit_remedy_cost_cents": None,
            "estimated_remedy_cost_cents": None,
            "status": "DRAFT",
            "reason_code": None,
        }
    )
    db.db.campaigns[row["id"]] = row
    return response.created(serializers.recall_campaign(row))


@bp.get("/recall-campaigns/<cid>")
@endpoint(READ_ROLES)
def read_campaign(cid):
    return response.ok(serializers.recall_campaign(resolve("campaign", cid)))


@bp.get("/recall-campaigns")
@endpoint(READ_ROLES)
def list_campaigns():
    scope_product_model_id = validation.query_string("scope_product_model_id")
    status = validation.query_enum("status", CAMPAIGN_STATUSES)
    result = rows("campaign")
    if scope_product_model_id is not None:
        result = [
            r for r in result if r["scope_product_model_id"] == scope_product_model_id
        ]
    if status is not None:
        result = [r for r in result if r["status"] == status]
    return response.paginate(ordered(result), serializers.recall_campaign)


@bp.post("/recall-campaigns/<cid>/scope")
@endpoint(["WarrantyAnalyst"])
def scope_campaign(cid):
    campaign = resolve("campaign", cid)
    body = validation.json_body()
    range_start = validation.string(body, "serial_range_start")
    range_end = validation.string(body, "serial_range_end")

    if campaign["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")
    # Position 21: well-formedness precedes population resolution.
    if range_end < range_start:
        raise ApiError("ERR_SERIAL_RANGE_INVALID")

    campaign["serial_range_start"] = range_start
    campaign["serial_range_end"] = range_end
    population = recall_population(campaign)
    # Position 22: an empty scope is refused.
    if not population:
        campaign["serial_range_start"] = None
        campaign["serial_range_end"] = None
        raise ApiError("ERR_RECALL_SCOPE_EMPTY")

    per_unit = calc.per_unit_remedy_cost(campaign["remedy_type"])
    campaign["affected_unit_count"] = len(population)
    campaign["per_unit_remedy_cost_cents"] = per_unit
    # A snapshot of the scope at this instant, not a live figure.
    campaign["estimated_remedy_cost_cents"] = len(population) * per_unit
    campaign["status"] = "SCOPED"
    touch(campaign)
    return response.ok(serializers.recall_campaign(campaign))


@bp.post("/recall-campaigns/<cid>/announce")
@endpoint(["WarrantyAnalyst"])
def announce_campaign(cid):
    campaign = resolve("campaign", cid)
    if campaign["status"] != "SCOPED":
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")
    # Position 31: the budget is enforced only here.
    if campaign["estimated_remedy_cost_cents"] > campaign["budget_cents"]:
        raise ApiError("ERR_RECALL_BUDGET_EXCEEDED")

    campaign["status"] = "ANNOUNCED"
    touch(campaign)

    population = recall_population(campaign)
    per_unit = campaign["per_unit_remedy_cost_cents"]
    # Notices are issued in the affected units' created_at ascending order.
    for unit in ordered(population):
        if unit["build_status"] == "SHIPPED":
            notice = make_row(
                {
                    "recall_campaign_id": campaign["id"],
                    "heater_unit_id": unit["id"],
                    "status": "PENDING",
                    "remedy_cost_cents": per_unit,
                    "notified_at": None,
                    "remedied_at": None,
                    "reason_code": None,
                }
            )
            db.db.notices[notice["id"]] = notice
        elif unit["build_status"] in ("ASSEMBLED", "LABELED"):
            # No owner to notify for a unit that never left the plant.
            hold_unit(unit, "RECALL_SCOPE", invalidate_label=False)
        # A unit already HELD is left exactly as it is.

    model = db.db.models[campaign["scope_product_model_id"]]
    restrict_model_if_released(model)
    touch(model)
    return response.ok(serializers.recall_campaign(campaign))


@bp.post("/recall-campaigns/<cid>/close")
@endpoint(["WarrantyAnalyst"])
def close_campaign(cid):
    campaign = resolve("campaign", cid)
    if campaign["status"] != "IN_REMEDY":
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")

    notice_count, remedied, _ = serializers.campaign_counts(campaign["id"])
    population_pct = calc.completion_pct(remedied, campaign.get("affected_unit_count"))
    # Position 32: the stricter of the two measures gates closure.
    if population_pct < COMPLETION_THRESHOLD:
        raise ApiError("ERR_COMPLETION_BELOW_THRESHOLD")
    # Position 33: no in-plant unit of the population may still be held.
    for unit in recall_population(campaign):
        if unit["build_status"] == "HELD":
            raise ApiError("ERR_HELD_UNITS_REMAIN")

    campaign["status"] = "CLOSED"
    touch(campaign)
    return response.ok(serializers.recall_campaign(campaign))


@bp.post("/recall-campaigns/<cid>/cancel")
@endpoint(["WarrantyAnalyst"])
def cancel_campaign(cid):
    campaign = resolve("campaign", cid)
    body = validation.json_body()
    reason_code = validation.string(body, "reason_code")
    if campaign["status"] not in ("DRAFT", "SCOPED"):
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")

    # The scope snapshot is retained for the audit record.
    campaign["status"] = "CANCELLED"
    campaign["reason_code"] = reason_code
    touch(campaign)
    return response.ok(serializers.recall_campaign(campaign))


@bp.get("/recall-campaigns/<cid>/completion")
@endpoint(READ_ROLES)
def campaign_completion(cid):
    campaign = resolve("campaign", cid)
    notice_count, remedied, unreachable = serializers.campaign_counts(campaign["id"])
    affected = campaign.get("affected_unit_count")
    return response.ok(
        {
            "affected_unit_count": affected,
            "notice_count": notice_count,
            "remedied_count": remedied,
            "unreachable_count": unreachable,
            "completion_pct_notice_based": calc.out_num(
                calc.completion_pct(remedied, notice_count)
            ),
            "completion_pct_population_based": calc.out_num(
                calc.completion_pct(remedied, affected)
            ),
        }
    )


# --------------------------------------------------------------------------
# Recall notices
# --------------------------------------------------------------------------

def _live_campaign(notice):
    campaign = db.db.campaigns[notice["recall_campaign_id"]]
    # Every notice action requires a live campaign behind it.
    if campaign["status"] not in ("ANNOUNCED", "IN_REMEDY"):
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")
    return campaign


@bp.get("/recall-notices/<nid>")
@endpoint(READ_ROLES)
def read_notice(nid):
    return response.ok(serializers.recall_notice(resolve("notice", nid)))


@bp.get("/recall-notices")
@endpoint(READ_ROLES)
def list_notices():
    recall_campaign_id = validation.query_string("recall_campaign_id")
    heater_unit_id = validation.query_string("heater_unit_id")
    status = validation.query_enum("status", NOTICE_STATUSES)
    result = rows("notice")
    if recall_campaign_id is not None:
        result = [r for r in result if r["recall_campaign_id"] == recall_campaign_id]
    if heater_unit_id is not None:
        result = [r for r in result if r["heater_unit_id"] == heater_unit_id]
    if status is not None:
        result = [r for r in result if r["status"] == status]
    return response.paginate(ordered(result), serializers.recall_notice)


@bp.post("/recall-notices/<nid>/notify")
@endpoint(["WarrantyAnalyst"])
def notify_notice(nid):
    notice = resolve("notice", nid)
    _live_campaign(notice)
    if notice["status"] != "PENDING":
        raise ApiError("ERR_INVALID_NOTICE_STATE")
    notice["status"] = "NOTIFIED"
    notice["notified_at"] = db.db.now()
    # Notification alone does not move the campaign.
    touch(notice)
    return response.ok(serializers.recall_notice(notice))


@bp.post("/recall-notices/<nid>/remedy")
@endpoint(["WarrantyAnalyst"])
def remedy_notice(nid):
    notice = resolve("notice", nid)
    campaign = _live_campaign(notice)
    # A remedy can never skip notification.
    if notice["status"] != "NOTIFIED":
        raise ApiError("ERR_INVALID_NOTICE_STATE")

    notice["status"] = "REMEDIED"
    notice["remedied_at"] = db.db.now()
    touch(notice)
    # BUBBLE UP: the first remedy moves the campaign; later ones only recompute.
    if campaign["status"] == "ANNOUNCED":
        campaign["status"] = "IN_REMEDY"
    touch(campaign)
    return response.ok(serializers.recall_notice(notice))


@bp.post("/recall-notices/<nid>/mark-unreachable")
@endpoint(["WarrantyAnalyst"])
def mark_notice_unreachable(nid):
    notice = resolve("notice", nid)
    body = validation.json_body()
    reason_code = validation.string(body, "reason_code")
    campaign = _live_campaign(notice)
    if notice["status"] not in ("PENDING", "NOTIFIED"):
        raise ApiError("ERR_INVALID_NOTICE_STATE")

    # Unreachable is a failure to reach an owner, not a removal of an obligation:
    # the notice stays in the notice-based denominator.
    notice["status"] = "UNREACHABLE"
    notice["reason_code"] = reason_code
    touch(notice)
    touch(campaign)
    return response.ok(serializers.recall_notice(notice))
