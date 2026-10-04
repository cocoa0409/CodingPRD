"""Franchise and partner scoop shops (PRD section 3.8).

franchise_fee_cents is computed by the server: 3,500,000 for FRANCHISEE, 0
for NONPROFIT_PARTNER (the partner-shop fee is waived). Opening a partner
shop requires nonprofit_verified == true. A ShopOperator's X-User-ID is the
shop id; ownership is checked before existence on the shop path.
"""
from flask import Blueprint

from auth import authenticate, authorize
from db import STORE, new_resource, public, touch
from envelope import ok
from errors import fail
from validate import (OPERATOR_TYPES, get_body, opt_bool, req_enum, req_int,
                      req_str)

bp = Blueprint("shops", __name__)

FRANCHISE_FEE_CENTS = 3500000
READ_ROLES = ("FranchiseAdmin", "ShopOperator", "ParentOpsController")


def get_shop(sid):
    s = STORE["shops"].get(sid)
    if s is None:
        fail("ERR_SHOP_NOT_FOUND", "ScoopShop id does not exist")
    return s


def check_shop_ownership(role, uid, sid):
    """ShopOperator may only touch their own shop (X-User-ID == shop id)."""
    if role == "ShopOperator" and uid != sid:
        fail("ERR_FORBIDDEN_OWNERSHIP",
             "A ShopOperator may only act on their own shop")


@bp.post("/scoop-shops")
def create_shop():
    _, role = authenticate()
    authorize(role, ("FranchiseAdmin",))
    body = get_body()
    name = req_str(body, "name")
    operator_type = req_enum(body, "operator_type", OPERATOR_TYPES)
    nonprofit_verified = opt_bool(body, "nonprofit_verified", False)
    city = req_str(body, "city")
    country = req_str(body, "country_code")
    credit_limit = req_int(body, "credit_limit_cents", 0)
    r = new_resource()
    r.update({
        "name": name,
        "operator_type": operator_type,
        "nonprofit_verified": nonprofit_verified,
        "city": city,
        "country_code": country,
        "credit_limit_cents": credit_limit,
        "franchise_fee_cents": (FRANCHISE_FEE_CENTS
                                if operator_type == "FRANCHISEE" else 0),
        "status": "SITE_REVIEW",
    })
    STORE["shops"][r["id"]] = r
    return ok(public(r), 201)


@bp.get("/scoop-shops/<sid>")
def read_shop(sid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    check_shop_ownership(role, uid, sid)
    return ok(public(get_shop(sid)))


def _shop_transition(sid, allowed_from, target):
    _, role = authenticate()
    authorize(role, ("FranchiseAdmin",))
    s = get_shop(sid)
    if s["status"] not in allowed_from:
        fail("ERR_INVALID_STATE",
             "Shop in %s cannot move to %s" % (s["status"], target))
    s["status"] = target
    touch(s)
    return ok(public(s))


@bp.post("/scoop-shops/<sid>/approve-site")
def approve_site(sid):
    return _shop_transition(sid, ("SITE_REVIEW",), "SITE_APPROVED")


@bp.post("/scoop-shops/<sid>/reject-site")
def reject_site(sid):
    return _shop_transition(sid, ("SITE_REVIEW",), "CLOSED")


@bp.post("/scoop-shops/<sid>/open")
def open_shop(sid):
    _, role = authenticate()
    authorize(role, ("FranchiseAdmin",))
    s = get_shop(sid)
    if s["status"] != "SITE_APPROVED":
        fail("ERR_INVALID_STATE",
             "Only a SITE_APPROVED shop can be opened")
    if s["operator_type"] != "FRANCHISEE" and not s["nonprofit_verified"]:
        fail("ERR_NONPROFIT_VERIFICATION_REQUIRED",
             "A partner shop requires verified nonprofit status to open")
    s["status"] = "OPERATING"
    touch(s)
    return ok(public(s))


@bp.post("/scoop-shops/<sid>/suspend")
def suspend_shop(sid):
    return _shop_transition(sid, ("OPERATING",), "SUSPENDED")


@bp.post("/scoop-shops/<sid>/reopen")
def reopen_shop(sid):
    return _shop_transition(sid, ("SUSPENDED",), "OPERATING")
