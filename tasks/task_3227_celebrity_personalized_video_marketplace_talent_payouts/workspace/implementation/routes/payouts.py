"""Payout and payout-line read endpoints."""
from flask import Blueprint, request

import db
from errors import err, parse_pagination, paginate
from middleware import authenticate, require_role
from response import envelope, envelope_list
from routes.talents import payout_public, payout_line_public

bp = Blueprint("payouts", __name__)


@bp.get("/marketplace/payouts/<pid>")
def get_payout(pid):
    _uid, role = authenticate()
    require_role(role, ["Talent", "PlatformAdmin"])
    p = db.payouts.get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND", "payout %s not found" % pid)
    return envelope(payout_public(p), "object", 200)


@bp.get("/marketplace/payouts/<pid>/payout-lines")
def get_payout_lines(pid):
    _uid, role = authenticate()
    require_role(role, ["Talent", "PlatformAdmin"])
    p = db.payouts.get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND", "payout %s not found" % pid)
    limit, offset = parse_pagination(request.args)
    items = [l for l in db.payout_lines.values() if l["payout_id"] == pid]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([payout_line_public(l) for l in page],
                         limit, offset, total, has_more)


@bp.get("/marketplace/payout-lines/<lid>")
def get_payout_line(lid):
    _uid, role = authenticate()
    require_role(role, ["Talent", "PlatformAdmin"])
    l = db.payout_lines.get(lid)
    if l is None:
        raise err("ERR_NOT_FOUND", "payout line %s not found" % lid)
    return envelope(payout_line_public(l), "object", 200)


@bp.get("/marketplace/payout-lines")
def list_payout_lines():
    _uid, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    limit, offset = parse_pagination(request.args)
    payout_f = request.args.get("payout_id")
    order_f = request.args.get("order_id")
    talent_f = request.args.get("talent_id")
    ss_f = request.args.get("settlement_status")
    items = [l for l in db.payout_lines.values()
             if (payout_f is None or l["payout_id"] == payout_f)
             and (order_f is None or l["order_id"] == order_f)
             and (talent_f is None or l["talent_id"] == talent_f)
             and (ss_f is None or l["settlement_status"] == ss_f)]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([payout_line_public(l) for l in page],
                         limit, offset, total, has_more)
