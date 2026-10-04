"""Craftsman and apprentice registration endpoints (PRD 3.3)."""
from flask import Blueprint

from auth import ALL_ROLES, authenticate
from db import STORE, new_entity
from envelope import ok
from errors import raise_err
from serialize import apprentice as ser_apprentice, craftsman as ser_craftsman
from validate import get_body, req_enum, req_str

bp = Blueprint("people", __name__, url_prefix="/piano-works")

SPECIALTIES = ("RIM_BENDING", "SEASONING_CHECK", "ACTION_REGULATION", "VOICING")
WM = ("WorkshopManager",)


@bp.post("/craftsmen")
def create_craftsman():
    authenticate(WM)
    body = get_body()
    c = new_entity()
    c.update({
        "name": req_str(body, "name"),
        "specialty": req_enum(body, "specialty", SPECIALTIES),
    })
    STORE["craftsmen"][c["id"]] = c
    return ok(ser_craftsman(c), 201)


@bp.get("/craftsmen/<cid>")
def get_craftsman(cid):
    authenticate(ALL_ROLES)
    c = STORE["craftsmen"].get(cid)
    if c is None:
        raise_err("ERR_NOT_FOUND", "craftsman %s not found" % cid)
    return ok(ser_craftsman(c))


@bp.post("/apprentices")
def create_apprentice():
    authenticate(WM)
    body = get_body()
    a = new_entity()
    a.update({"name": req_str(body, "name")})
    STORE["apprentices"][a["id"]] = a
    return ok(ser_apprentice(a), 201)


@bp.get("/apprentices/<aid>")
def get_apprentice(aid):
    authenticate(ALL_ROLES)
    a = STORE["apprentices"].get(aid)
    if a is None:
        raise_err("ERR_NOT_FOUND", "apprentice %s not found" % aid)
    return ok(ser_apprentice(a))
