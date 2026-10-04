"""Proactive campaign routes: the two-bucket target ranking, activation, and
the informational preview (PRD 3.5)."""

import db
import shapes
from approval import as_enum, as_int, as_str, body
from auth import (
    ROLE_INSTALLER,
    ROLE_PLATFORM_ADMIN,
    get_campaign,
    get_lot,
    require,
)
from errors import fail
from respond import ok, ok_list, paginate
from services import common
from services import orders as order_service

CAMPAIGN_MODELS = ("IQ7", "IQ8", "IQ8HC")

UNIT_PRIORITY = {"UNDERPERFORMING": 2, "ONLINE": 1}


def candidate_pool(lot_id):
    """The explicit enum filter: ONLINE and UNDERPERFORMING units of the lot."""
    return [u for u in db.all_units_of_lot(lot_id)
            if u.get("monitored_status") in ("ONLINE", "UNDERPERFORMING")]


def rank_candidates(campaign, pool):
    """The authoritative two-bucket selection (PRD 3.5)."""
    guaranteed_n = int(campaign.get("guaranteed_units", 0) or 0)
    max_units = int(campaign.get("max_units", 0) or 0)

    oldest_first = sorted(
        pool,
        key=lambda u: (u.get("installed_at") or "", u.get("created_at") or "",
                       u.get("id") or ""))
    guaranteed = oldest_first[:guaranteed_n]
    guaranteed_ids = {u["id"] for u in guaranteed}

    remainder = [u for u in pool if u["id"] not in guaranteed_ids]
    remainder.sort(key=lambda u: (
        -UNIT_PRIORITY.get(u.get("monitored_status"), 0),
        -int(u.get("underperformance_streak_hours", 0) or 0),
        u.get("installed_at") or "",
        u.get("created_at") or "",
        u.get("id") or "",
    ))

    budget = max(0, max_units - guaranteed_n)
    selected = guaranteed + remainder[:budget]
    return selected, [u["id"] for u in guaranteed]


def pure_rank_candidates(pool, max_units):
    """The preview variant: no reservation, rank the whole pool."""
    ranked = sorted(pool, key=lambda u: (
        -UNIT_PRIORITY.get(u.get("monitored_status"), 0),
        -int(u.get("underperformance_streak_hours", 0) or 0),
        u.get("installed_at") or "",
        u.get("created_at") or "",
        u.get("id") or "",
    ))
    return [u["id"] for u in ranked[:max(0, int(max_units or 0))]]


def recompute_target_unit_count(campaign):
    count = len(candidate_pool(campaign["lot_id"]))
    common.set_many(campaign, {"target_unit_count": count})
    return count


def create_campaign():
    data = body()
    lot_id = as_str(data, "lot_id")
    replacement_model_code = as_enum(data, "replacement_model_code", CAMPAIGN_MODELS)
    max_units = as_int(data, "max_units", minimum=1)
    guaranteed_units = as_int(data, "guaranteed_units", required_=False, default=0, minimum=0)

    lot = db.DB.production_lots.get(lot_id)
    if lot is None:
        fail("ERR_RESOURCE_NOT_FOUND", "lot %s does not exist" % lot_id)
    if guaranteed_units > max_units:
        fail("ERR_INVALID_REQUEST_BODY",
             "guaranteed_units must not exceed max_units")

    campaign = {
        "id": common.new_id(),
        "created_at": common.now_iso(),
        "updated_at": common.now_iso(),
        "version": 1,
        "lot_id": lot_id,
        "origin": "MANUAL",
        "replacement_model_code": replacement_model_code,
        "max_units": max_units,
        "guaranteed_units": guaranteed_units,
        "status": "DRAFT",
        "target_unit_count": 0,
        "dispatched_count": 0,
        "canceled_count": 0,
        "window_start_at": None,
        "window_end_at": None,
    }
    db.DB.campaigns[campaign["id"]] = campaign
    recompute_target_unit_count(campaign)
    return ok(shapes.proactive_campaign(campaign), 201)


def list_campaigns():
    from flask import request

    lot_id = request.args.get("lot_id")
    status = request.args.get("status")

    rows = list(db.DB.campaigns.values())
    if lot_id:
        rows = [c for c in rows if c.get("lot_id") == lot_id]
    if status:
        rows = [c for c in rows if c.get("status") == status]
    rows = db.by_created_at(rows)
    window, meta = paginate(rows, request.args)
    return ok_list([shapes.proactive_campaign(c) for c in window], pagination=meta)


def read_campaign(campaign_id):
    campaign = get_campaign(campaign_id)
    recompute_target_unit_count(campaign)
    return ok(shapes.proactive_campaign(campaign))


def read_preview(campaign_id):
    campaign = get_campaign(campaign_id)
    lot = db.DB.production_lots.get(campaign["lot_id"])
    pool = candidate_pool(campaign["lot_id"])
    count = len(pool)

    selected, guaranteed_ids = rank_candidates(campaign, pool)
    pure_ids = pure_rank_candidates(pool, campaign.get("max_units"))
    return ok(shapes.campaign_preview(
        campaign,
        order_service.lot_only_model(lot),
        pure_ids,
        guaranteed_ids,
        count,
    ))


def activate_campaign(campaign_id):
    campaign = get_campaign(campaign_id)
    if campaign.get("status") != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT campaign can be activated")

    lot = get_lot(campaign["lot_id"])
    if lot.get("lot_status") != "RECALL":
        fail("ERR_LOT_NOT_IN_RECALL")

    pool = candidate_pool(campaign["lot_id"])
    common.set_many(campaign, {"target_unit_count": len(pool)})
    if len(pool) == 0:
        fail("ERR_NO_CAMPAIGN_TARGETS")

    selected, _guaranteed_ids = rank_candidates(campaign, pool)

    model = campaign.get("replacement_model_code")
    for unit in selected:
        compatibility_class = order_service.classify(unit.get("model_code"), model)
        order_service.new_order(
            unit, model, compatibility_class, "PENDING_DISPATCH",
            campaign_id=campaign["id"])
        common.set_many(unit, {"version": int(unit.get("version", 0)) + 1})

    common.set_many(campaign, {
        "status": "DISPATCHING",
        "window_start_at": common.now_iso(),
        "dispatched_count": len(selected),
    })
    for unit in selected:
        common.recompute_unit(unit)
    return ok(shapes.proactive_campaign(campaign))


def close_campaign(campaign_id):
    campaign = get_campaign(campaign_id)
    if campaign.get("status") != "DISPATCHING":
        fail("ERR_INVALID_STATE", "only a DISPATCHING campaign can be closed")

    common.set_many(campaign, {
        "status": "COMPLETED",
        "window_end_at": common.now_iso(),
    })
    for order in db.orders_of_campaign(campaign["id"]):
        if order.get("status") != "DISPATCHED":
            continue
        unit = db.DB.units.get(order.get("unit_id"))
        order["status"] = "INSTALLED"
        order["installed_at"] = common.now_iso()
        if unit is not None:
            common.set_many(unit, {"monitored_status": "ONLINE"})
            common.touch(unit)
            common.recompute_unit(unit)
    order_service.recompute_campaign_counts(campaign)
    return ok(shapes.proactive_campaign(campaign))


def cancel_campaign(campaign_id):
    campaign = get_campaign(campaign_id)
    if campaign.get("status") != "DISPATCHING":
        fail("ERR_INVALID_STATE", "only a DISPATCHING campaign can be canceled")

    common.set_many(campaign, {
        "status": "CANCELED",
        "window_end_at": common.now_iso(),
    })
    canceled = 0
    for order in db.orders_of_campaign(campaign["id"]):
        if order.get("status") in ("PENDING_DISPATCH", "DISPATCHED"):
            order["status"] = "CANCELED"
            canceled += 1
    common.set_many(campaign, {"canceled_count": canceled})
    for order in db.orders_of_campaign(campaign["id"]):
        unit = db.DB.units.get(order.get("unit_id"))
        if unit is not None:
            common.recompute_unit(unit)
    return ok(shapes.proactive_campaign(campaign))


def register(app):
    app.add_url_rule("/warranty/proactive-campaigns", "create_campaign",
                     require(ROLE_PLATFORM_ADMIN)(create_campaign), methods=["POST"])
    app.add_url_rule("/warranty/proactive-campaigns", "list_campaigns",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER)(list_campaigns),
                     methods=["GET"])
    app.add_url_rule("/warranty/proactive-campaigns/<campaign_id>", "read_campaign",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER)(read_campaign),
                     methods=["GET"])
    app.add_url_rule("/warranty/proactive-campaigns/<campaign_id>/preview", "read_preview",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER)(read_preview),
                     methods=["GET"])
    app.add_url_rule("/warranty/proactive-campaigns/<campaign_id>/activate",
                     "activate_campaign",
                     require(ROLE_PLATFORM_ADMIN)(activate_campaign), methods=["POST"])
    app.add_url_rule("/warranty/proactive-campaigns/<campaign_id>/close", "close_campaign",
                     require(ROLE_PLATFORM_ADMIN)(close_campaign), methods=["POST"])
    app.add_url_rule("/warranty/proactive-campaigns/<campaign_id>/cancel", "cancel_campaign",
                     require(ROLE_PLATFORM_ADMIN)(cancel_campaign), methods=["POST"])