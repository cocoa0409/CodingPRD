"""Partner, promo code, entitlement routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import ok_obj, ok_list
from serialize import serialize as ser, paginate, by_created
from services import partner as svc
from util import get_or_404, get_body

bp = Blueprint("partners", __name__)


@bp.post("/platform/partners")
def create_partner():
    require_roles(["PartnerManager"])
    return ok_obj(ser(svc.create_partner(get_body())), 201)


@bp.get("/platform/partners/<pid>")
def get_partner(pid):
    require_roles(["PartnerManager"])
    return ok_obj(ser(get_or_404("partners", pid)))


@bp.post("/platform/partners/<pid>/promo-codes")
def issue_code(pid):
    require_roles(["PartnerManager"])
    partner = get_or_404("partners", pid)
    return ok_obj(ser(svc.issue_promo_code(partner)), 201)


@bp.get("/platform/promo-codes")
def list_codes():
    require_roles(["PartnerManager"])
    items = by_created(list(db.promo_codes.values()))
    for f in ("partner_id", "code_status", "redeemed_by_viewer_id"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if str(c.get(f)) == v]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(c) for c in page], limit, offset, total)


@bp.get("/platform/promo-codes/<cid>")
def get_code(cid):
    require_roles(["PartnerManager"])
    return ok_obj(ser(get_or_404("promo_codes", cid)))


@bp.post("/platform/promo-codes/redeem")
def redeem():
    user_id, _ = require_roles(["Viewer"])
    ent = svc.redeem_promo(get_body(), user_id)
    return ok_obj(ser(ent), 200)


@bp.post("/platform/promo-codes/<cid>/revoke")
def revoke(cid):
    require_roles(["PartnerManager"])
    return ok_obj(ser(svc.revoke_promo(get_or_404("promo_codes", cid))))


@bp.get("/platform/entitlements")
def list_entitlements():
    user_id, role = require_roles(["PartnerManager", "Viewer"])
    items = by_created(list(db.entitlements.values()))
    for f in ("viewer_id", "partner_id"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e.get(f) == v]
    if role == "Viewer":
        items = [e for e in items if e["viewer_id"] == user_id]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.get("/platform/entitlements/<eid>")
def get_entitlement(eid):
    user_id, role = require_roles(["PartnerManager", "Viewer"])
    ent = get_or_404("entitlements", eid)
    if role == "Viewer" and ent["viewer_id"] != user_id:
        from errors import raise_err, ERR_FORBIDDEN
        raise_err(ERR_FORBIDDEN, "viewer may only read own entitlements")
    return ok_obj(ser(ent))
