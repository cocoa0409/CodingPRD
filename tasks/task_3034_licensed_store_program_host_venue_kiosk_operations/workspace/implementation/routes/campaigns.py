"""Promotion campaigns and price preview."""
from datetime import date as date_type
from flask import request

import errors as E
import middleware as mw
from db import db
from response import success_list, success_object
from services import calculations as calc
from routes.agreements import bp, get_store


def pub_campaign(c):
    return {
        "id": c["id"], "store_id": c["store_id"], "name": c["name"],
        "start_date": c["start_date"], "end_date": c["end_date"],
        "discount_pct": c["discount_pct"], "floor_price_cents": c["floor_price_cents"],
        "status": c["status"], "reconciled": c["reconciled"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def get_campaign(cid):
    c = db.promotion_campaigns.get(cid)
    if c is None:
        raise E.err_not_found("promotion campaign not found")
    return c


def _campaign_licensee(c):
    return mw.licensee_of_store(db.stores[c["store_id"]])


def _campaign_scope(uid, role, c):
    if role == "LicenseeManager" and uid != _campaign_licensee(c):
        raise E.err_forbidden()


@bp.post("/licensing/stores/<sid>/promotion-campaigns")
def create_campaign(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    get_store(sid)
    b = mw.body()
    name = mw.req_str(b, "name")
    start = mw.req_date(b, "start_date")
    end = mw.req_date(b, "end_date")
    discount_pct = mw.req_int(b, "discount_pct", minimum=1, maximum=90)
    floor_price = mw.req_int(b, "floor_price_cents", minimum=1)
    if end < start:
        raise E.err_invalid_request("end_date must be >= start_date")
    for other in db.promotion_campaigns.values():
        if other["store_id"] != sid or other["status"] not in ("PLANNED", "ACTIVE"):
            continue
        os_ = date_type.fromisoformat(other["start_date"])
        oe = date_type.fromisoformat(other["end_date"])
        if os_ <= end and start <= oe:
            raise E.err_campaign_conflict()
    rec = mw.make_resource({
        "store_id": sid, "name": name,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "discount_pct": discount_pct, "floor_price_cents": floor_price,
        "status": "PLANNED", "reconciled": False,
    })
    db.promotion_campaigns[rec["id"]] = rec
    return success_object(pub_campaign(rec), 201)


@bp.get("/licensing/promotion-campaigns/<cid>")
def get_campaign_route(cid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    c = get_campaign(cid)
    _campaign_scope(uid, role, c)
    return success_object(pub_campaign(c))


@bp.get("/licensing/promotion-campaigns")
def list_campaigns():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    items = list(db.promotion_campaigns.values())
    if role == "LicenseeManager":
        items = [c for c in items if _campaign_licensee(c) == uid]
    sid = request.args.get("store_id")
    if sid is not None:
        items = [c for c in items if c["store_id"] == sid]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_campaign(x) for x in page], limit, offset, total)


@bp.post("/licensing/promotion-campaigns/<cid>/activate")
def activate_campaign(cid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    c = get_campaign(cid)
    if c["status"] != "PLANNED":
        raise E.err_invalid_campaign_state()
    today = db.clock.date()
    if not (date_type.fromisoformat(c["start_date"]) <= today <= date_type.fromisoformat(c["end_date"])):
        raise E.err_campaign_window()
    store = db.stores[c["store_id"]]
    if store["operating_status"] != "OPERATING":
        raise E.err_store_not_operating()
    if store["compliance_posture"] == "PROBATION":
        raise E.err_posture_probation()
    c["status"] = "ACTIVE"
    mw.touch(c)
    return success_object(pub_campaign(c))


@bp.post("/licensing/promotion-campaigns/<cid>/end")
def end_campaign(cid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    c = get_campaign(cid)
    if c["status"] != "ACTIVE":
        raise E.err_invalid_campaign_state()
    c["status"] = "ENDED"
    mw.touch(c)
    return success_object(pub_campaign(c))


@bp.post("/licensing/promotion-campaigns/<cid>/reconcile")
def reconcile_campaign(cid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    c = get_campaign(cid)
    if c["status"] != "ENDED":
        raise E.err_invalid_campaign_state()
    c["status"] = "RECONCILED"
    c["reconciled"] = True
    mw.touch(c)
    return success_object(pub_campaign(c))


@bp.post("/licensing/promotion-campaigns/<cid>/price-preview")
def price_preview(cid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    c = get_campaign(cid)
    _campaign_scope(uid, role, c)
    if c["status"] not in ("PLANNED", "ACTIVE"):
        raise E.err_invalid_campaign_state()
    b = mw.body()
    base_price = mw.req_int(b, "base_price_cents", minimum=0)
    member_id = mw.req_str(b, "member_id")
    member = db.loyalty_members.get(member_id)
    if member is None:
        raise E.err_not_found("loyalty member not found")
    result = calc.price_preview(
        base_price, c["discount_pct"], c["floor_price_cents"], member["points_balance"]
    )
    return success_object(result)
