"""Capacity pool and reservation routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import ok_obj, ok_list
from serialize import serialize as ser, paginate, by_created
from services import capacity as svc
from util import get_or_404, get_body

bp = Blueprint("capacity", __name__)

ROLES = ["StreamOps"]


@bp.post("/platform/capacity-pools")
def create_pool():
    require_roles(ROLES)
    pool = svc.create_pool(get_body())
    return ok_obj(ser(pool), 201)


@bp.get("/platform/capacity-pools")
def list_pools():
    require_roles(ROLES)
    items = by_created(list(db.capacity_pools.values()))
    for f in ("window_id", "scope_kind", "pool_code"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if str(p.get(f)) == v]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(p) for p in page], limit, offset, total)


@bp.get("/platform/capacity-pools/<pid>")
def get_pool(pid):
    require_roles(ROLES)
    return ok_obj(ser(get_or_404("capacity_pools", pid)))


@bp.post("/platform/capacity-reservations")
def create_reservation():
    require_roles(ROLES)
    res = svc.create_reservation(get_body())
    return ok_obj(ser(res), 201)


@bp.get("/platform/capacity-reservations")
def list_reservations():
    require_roles(ROLES)
    items = by_created(list(db.capacity_reservations.values()))
    for f in ("pool_id", "window_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if str(r.get(f)) == v]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser(r) for r in page], limit, offset, total)


@bp.get("/platform/capacity-reservations/<rid>")
def get_reservation(rid):
    require_roles(ROLES)
    return ok_obj(ser(get_or_404("capacity_reservations", rid)))


@bp.post("/platform/capacity-reservations/<rid>/confirm")
def confirm(rid):
    require_roles(ROLES)
    res = get_or_404("capacity_reservations", rid)
    svc.confirm_reservation(res)
    return ok_obj(ser(res))


@bp.post("/platform/capacity-reservations/<rid>/release")
def release(rid):
    require_roles(ROLES)
    res = get_or_404("capacity_reservations", rid)
    svc.release_reservation(res)
    return ok_obj(ser(res))
