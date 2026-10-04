"""Ad campaign, ad slot, and impression routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import ok_obj, ok_list
from serialize import serialize as ser, paginate, by_created
from services import campaign as camp_svc
from services import adslot as slot_svc
from util import get_or_404, get_body

bp = Blueprint("ads", __name__)


@bp.post("/platform/ad-campaigns")
def create_campaign():
    require_roles(["AdOps"])
    camp = camp_svc.create_campaign(get_body())
    return ok_obj(ser(camp), 201)


@bp.get("/platform/ad-campaigns/<cid>")
def get_campaign(cid):
    require_roles(["AdOps"])
    return ok_obj(ser(get_or_404("ad_campaigns", cid)))


@bp.post("/platform/ad-campaigns/<cid>/book")
def book(cid):
    require_roles(["AdOps"])
    return ok_obj(ser(camp_svc.book(get_or_404("ad_campaigns", cid))))


@bp.post("/platform/ad-campaigns/<cid>/pause")
def pause(cid):
    require_roles(["AdOps"])
    return ok_obj(ser(camp_svc.pause(get_or_404("ad_campaigns", cid))))


@bp.post("/platform/ad-campaigns/<cid>/resume")
def resume(cid):
    require_roles(["AdOps"])
    return ok_obj(ser(camp_svc.resume(get_or_404("ad_campaigns", cid))))


@bp.post("/platform/ad-slots")
def create_slot():
    require_roles(["AdOps"])
    return ok_obj(ser(slot_svc.create_slot(get_body())), 201)


@bp.get("/platform/ad-slots")
def list_slots():
    require_roles(["AdOps", "RightsManager"])
    items = by_created(list(db.ad_slots.values()))
    for f in ("window_id", "status", "booked_campaign_id"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if str(s.get(f)) == v]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(s) for s in page], limit, offset, total)


@bp.get("/platform/ad-slots/<sid>")
def get_slot(sid):
    require_roles(["AdOps", "RightsManager"])
    return ok_obj(ser(get_or_404("ad_slots", sid)))


@bp.post("/platform/ad-slots/<sid>/fill")
def fill(sid):
    require_roles(["AdOps"])
    slot = get_or_404("ad_slots", sid)
    return ok_obj(ser(slot_svc.fill_slot(slot, get_body())))


@bp.post("/platform/ad-slots/<sid>/release")
def release(sid):
    require_roles(["AdOps"])
    return ok_obj(ser(slot_svc.release_slot(get_or_404("ad_slots", sid))))


@bp.post("/platform/ad-slots/<sid>/mark-unfillable")
def mark_unfillable(sid):
    require_roles(["AdOps"])
    return ok_obj(ser(slot_svc.mark_unfillable(get_or_404("ad_slots", sid))))


@bp.post("/platform/ad-slots/<sid>/serve")
def serve(sid):
    require_roles(["AdOps"])
    slot = get_or_404("ad_slots", sid)
    return ok_obj(ser(slot_svc.serve(slot, get_body())), 201)


@bp.get("/platform/impressions")
def list_impressions():
    require_roles(["AdOps"])
    items = by_created(list(db.impressions.values()))
    for f in ("campaign_id", "viewer_id", "slot_id"):
        v = request.args.get(f)
        if v is not None:
            items = [i for i in items if i.get(f) == v]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(i) for i in page], limit, offset, total)


@bp.get("/platform/impressions/<iid>")
def get_impression(iid):
    require_roles(["AdOps"])
    return ok_obj(ser(get_or_404("impressions", iid)))
