"""Loyalty account events."""
import uuid as uuid_mod
from flask import request

import errors as E
import middleware as mw
from db import db
from response import success_list, success_object
from services import calculations as calc
from routes.agreements import bp


def pub_event(ev):
    out = {
        "id": ev["id"], "member_id": ev["member_id"], "store_id": ev["store_id"],
        "store_format": ev["store_format"], "event_type": ev["event_type"],
        "purchase_cents": ev["purchase_cents"], "points": ev["points"],
        "redemption_cents": ev["redemption_cents"],
        "created_at": ev["created_at"],
    }
    if ev.get("note") is not None:
        out["note"] = ev["note"]
    return out


EVENT_TYPES = ("EARN", "REDEEM", "ADJUST")
STORE_FORMATS = ("LICENSED", "COMPANY_OPERATED")


@bp.post("/licensing/loyalty-members/<mid>/events")
def post_loyalty_event(mid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager", "BrandProgramAdmin"))
    member = db.loyalty_members.get(mid)
    if member is None:
        raise E.err_not_found("loyalty member not found")
    b = mw.body()
    event_type = mw.req_enum(b, "event_type", EVENT_TYPES)
    store_format = mw.req_enum(b, "store_format", STORE_FORMATS)
    store_id = b.get("store_id")
    if store_id is not None and not isinstance(store_id, str):
        raise E.err_invalid_request("store_id must be a string or null")
    purchase_cents = None
    if event_type in ("EARN", "REDEEM"):
        purchase_cents = mw.req_int(b, "purchase_cents", minimum=0)
    elif "purchase_cents" in b:
        purchase_cents = mw.req_int(b, "purchase_cents", minimum=0)
    note = mw.opt_str(b, "note")
    # format/store consistency (referential)
    if store_format == "LICENSED":
        if store_id is None:
            raise E.err_invalid_loyalty_event("LICENSED events require a store_id")
        store = db.stores.get(store_id)
        if store is None:
            raise E.err_not_found("store not found")
        if role == "LicenseeManager" and uid != mw.licensee_of_store(store):
            raise E.err_forbidden()
        if store["operating_status"] != "OPERATING":
            raise E.err_invalid_loyalty_event("LICENSED events require an OPERATING store")
    else:
        if store_id is not None:
            raise E.err_invalid_loyalty_event("COMPANY_OPERATED events must not name a store")
    # points computation
    if event_type == "EARN":
        points = calc.earn_points(purchase_cents, store_format)
        member["points_balance"] += points
        member["lifetime_earned"] += points
        redemption_cents = None
    elif event_type == "REDEEM":
        requested = mw.req_int(b, "points", minimum=1)
        cap = calc.redeem_cap_points(purchase_cents, store_format)
        if requested > member["points_balance"] or requested > cap:
            raise E.err_loyalty_insufficient()
        points = requested
        member["points_balance"] -= points
        member["lifetime_redeemed"] += points
        redemption_cents = points * calc.POINT_VALUE_CENTS
    else:  # ADJUST
        points = mw.req_int(b, "points")
        if member["points_balance"] + points < 0:
            raise E.err_loyalty_insufficient("ADJUST would drive the balance negative")
        if points >= 0:
            member["lifetime_earned"] += points
        else:
            member["lifetime_redeemed"] += -points
        member["points_balance"] += points
        redemption_cents = None
    mw.touch(member)
    event = {
        "id": str(uuid_mod.uuid4()), "created_at": mw.sys_ts(),
        "member_id": mid, "store_id": store_id, "store_format": store_format,
        "event_type": event_type, "purchase_cents": purchase_cents,
        "points": points, "redemption_cents": redemption_cents, "note": note,
    }
    db.loyalty_account_events[event["id"]] = event
    return success_object(pub_event(event), 201)


@bp.get("/licensing/loyalty-account-events/<eid>")
def get_loyalty_event(eid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "LoyaltyMember"))
    ev = db.loyalty_account_events.get(eid)
    if ev is None:
        raise E.err_not_found("loyalty account event not found")
    mw.check_member_scope(uid, role, ev["member_id"])
    return success_object(pub_event(ev))


@bp.get("/licensing/loyalty-account-events")
def list_loyalty_events():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "LoyaltyMember"))
    items = list(db.loyalty_account_events.values())
    if role == "LoyaltyMember":
        items = [ev for ev in items if ev["member_id"] == uid]
    mid = request.args.get("member_id")
    if mid is not None:
        if role == "LoyaltyMember" and mid != uid:
            raise E.err_forbidden()
        items = [ev for ev in items if ev["member_id"] == mid]
    sid = request.args.get("store_id")
    if sid is not None:
        items = [ev for ev in items if ev["store_id"] == sid]
    et = request.args.get("event_type")
    if et is not None:
        items = [ev for ev in items if ev["event_type"] == et]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_event(x) for x in page], limit, offset, total)
