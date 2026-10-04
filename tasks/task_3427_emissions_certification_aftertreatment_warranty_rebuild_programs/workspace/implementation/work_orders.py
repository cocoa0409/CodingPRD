"""Campaign work orders: scheduling, shop execution, verification (PRD §3.8)."""
from flask import Blueprint, request

import calculations
import cascade
import clock
import store
from errors import ApiError
from rbac import auth, ANY
from validators import (
    body, f_str, f_int, f_dt, get_or_404, page_args, slice_page,
    envelope_ok, new_entity, touch, ser,
)

bp = Blueprint("work_orders", __name__)

LEVEL2_MIN_BAY_DAYS = 3  # WORK_ORDER_LEVEL2_MIN_BAY_DAYS
LEVELS_2_PLUS = ("LEVEL_2", "LEVEL_3")


def _wo(wid):
    return get_or_404(store.work_orders, wid, "CampaignWorkOrder")


def _own_center(wo, user_id):
    """Ownership (priority 5): ServiceAdvisor acts only with their own center."""
    if wo["service_center_id"] != user_id:
        raise ApiError("ERR_CENTER_MISMATCH", 403,
                       "ServiceAdvisor may act only for their own center")


@bp.post("/emissions/field-campaigns/<campaignId>/work-orders")
def create_work_order(campaignId):
    user_id, _ = auth(("ServiceAdvisor",))
    b = body()
    unit_id = f_str(b, "engine_unit_id")
    center_id = f_str(b, "service_center_id")
    tech_id = f_str(b, "assigned_technician_id")
    start_day = f_dt(b, "scheduled_start_day")
    bay_days = f_int(b, "bay_days", min_v=1)
    # existence (priority 4): path id first, then body FKs left-to-right
    campaign = get_or_404(store.campaigns, campaignId, "FieldCampaign")
    unit = get_or_404(store.units, unit_id, "EngineUnit")
    center = get_or_404(store.centers, center_id, "ServiceCenter")
    tech = get_or_404(store.technicians, tech_id, "Technician")
    # ownership (priority 5)
    if center_id != user_id:
        raise ApiError("ERR_CENTER_MISMATCH", 403,
                       "ServiceAdvisor may schedule only for their own center")
    # state gates (priority 7), narrative order: campaign, unit, center
    if campaign["status"] != "IN_PROGRESS":
        raise ApiError("ERR_CAMPAIGN_NOT_IN_PROGRESS", 409,
                       "Work-order create requires the campaign IN_PROGRESS")
    if unit["campaign_compliance"] != "CAMPAIGN_OPEN":
        raise ApiError("ERR_UNIT_CAMPAIGN_NOT_OPEN", 409,
                       "The unit's campaign_compliance must be CAMPAIGN_OPEN")
    if center["auth_status"] != "AUTHORIZED":
        raise ApiError("ERR_CENTER_NOT_AUTHORIZED", 409,
                       "The executing center must be AUTHORIZED")
    # qualification (priority 9)
    cascade.materialize_technician(tech)  # CERT_ACTIVE at the logical clock (§2.4)
    if (tech["service_center_id"] != center["id"]
            or tech["cert_status"] != "CERT_ACTIVE"
            or not tech["emissions_endorsed"]
            or (bay_days >= LEVEL2_MIN_BAY_DAYS
                and tech["certification_level"] not in LEVELS_2_PLUS)):
        raise ApiError("ERR_TECHNICIAN_NOT_QUALIFIED", 409,
                       "Assigned technician fails center membership, certification, "
                       "endorsement, or the LEVEL_2+ requirement for bay_days >= 3")
    # capacity (priority 13)
    if not calculations.bay_capacity_ok(center_id, start_day, bay_days,
                                        center["bay_capacity_per_day"]):
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409,
                       "Some day in the span would exceed the center's bay capacity")
    ent = new_entity()
    ent.update({
        "campaign_id": campaign["id"],
        "engine_unit_id": unit["id"],
        "service_center_id": center["id"],
        "assigned_technician_id": tech["id"],
        "scheduled_start_day": start_day,
        "bay_days": bay_days,
        "status": "SCHEDULED",
        "completed_at": None,
        "verified_at": None,
    })
    store.work_orders[ent["id"]] = ent
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/campaign-work-orders")
def list_work_orders():
    auth(ANY)
    limit, offset = page_args()
    items = list(store.work_orders.values())
    for param, key in (("campaign_id", "campaign_id"),
                       ("engine_unit_id", "engine_unit_id"),
                       ("service_center_id", "service_center_id"),
                       ("assigned_technician_id", "assigned_technician_id"),
                       ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [w for w in items if w[key] == v]
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)


@bp.get("/emissions/campaign-work-orders/<wid>")
def get_work_order(wid):
    auth(ANY)
    return envelope_ok(ser(_wo(wid)), 200)


@bp.post("/emissions/campaign-work-orders/<wid>/start")
def start_work_order(wid):
    user_id, _ = auth(("ServiceAdvisor",))
    wo = _wo(wid)
    _own_center(wo, user_id)
    if wo["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "start requires SCHEDULED")
    # the center must hold at least one effectively CALIBRATED_ACTIVE tool
    has_tool = False
    for t in store.tools.values():
        if t["service_center_id"] != wo["service_center_id"]:
            continue
        cascade.materialize_tool(t)  # lazy RECAL_DUE on use (§2.4)
        if t["tool_status"] == "CALIBRATED_ACTIVE":
            has_tool = True
    if not has_tool:
        raise ApiError("ERR_TOOL_NOT_CALIBRATED", 409,
                       "The center holds no CALIBRATED_ACTIVE diagnostic tool")
    wo["status"] = "IN_BAY"
    touch(wo)
    return envelope_ok(ser(wo), 200)


@bp.post("/emissions/campaign-work-orders/<wid>/complete")
def complete_work_order(wid):
    user_id, _ = auth(("ServiceAdvisor",))
    wo = _wo(wid)
    _own_center(wo, user_id)
    if wo["status"] != "IN_BAY":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "complete requires IN_BAY")
    wo["status"] = "COMPLETED"
    wo["completed_at"] = clock.now_dt()
    touch(wo)
    return envelope_ok(ser(wo), 200)


@bp.post("/emissions/campaign-work-orders/<wid>/verify")
def verify_work_order(wid):
    auth(("RegulatoryOfficer",))
    wo = _wo(wid)
    if wo["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "verify requires COMPLETED")
    campaign = store.campaigns.get(wo["campaign_id"])
    if campaign is None or campaign["status"] not in ("IN_PROGRESS", "COMPLETION_REVIEW"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "verify requires the campaign IN_PROGRESS or COMPLETION_REVIEW")
    wo["status"] = "VERIFIED"
    wo["verified_at"] = clock.now_dt()
    touch(wo)
    # hop 1: unit CAMPAIGN_OPEN -> REMEDIED
    unit = store.units.get(wo["engine_unit_id"])
    if unit is not None and unit["campaign_compliance"] == "CAMPAIGN_OPEN":
        unit["campaign_compliance"] = "REMEDIED"
        touch(unit)
    # hop 2: campaign counters + rate
    campaign["verified_unit_count"] += 1
    rate = calculations.completion_rate_dec(
        campaign["verified_unit_count"], campaign["notified_unit_count"])
    campaign["completion_rate"] = float(rate)
    touch(campaign)
    # hop 3 (+ hop 4 inside close_campaign): threshold close while in review
    if (campaign["status"] == "COMPLETION_REVIEW"
            and rate >= calculations.D(campaign["completion_threshold"])):
        cascade.close_campaign(campaign)
    return envelope_ok(ser(wo), 200)


@bp.post("/emissions/campaign-work-orders/<wid>/cancel")
def cancel_work_order(wid):
    user_id, _ = auth(("ServiceAdvisor",))
    wo = _wo(wid)
    _own_center(wo, user_id)
    if wo["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "cancel requires SCHEDULED")
    wo["status"] = "CANCELLED"  # releases the occupied bay-days
    touch(wo)
    return envelope_ok(ser(wo), 200)
