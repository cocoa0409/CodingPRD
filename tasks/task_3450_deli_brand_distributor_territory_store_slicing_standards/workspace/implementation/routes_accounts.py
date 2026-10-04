"""Account, Product, and AccountProductAuthorization endpoints (PRD SS3.2)."""
from flask import Blueprint, request

import store
from domain import (lazy_territory, reinstate_account, suspend_account, touch)
from errors import fail
from serializers import ser_account, ser_authorization, ser_product
from store import db
from util import (ALL_ROLES, auth, body, list_response, new_id, ok, opt_bool,
                  req_array, req_enum, req_int, req_str, sort_std)

bp = Blueprint("accounts", __name__)

CHANNELS = {"INDEPENDENT_GROCER", "CONVENIENCE", "FOODSERVICE", "MASS_MERCHANT", "CLUB_STORE"}
REFUSED_CHANNELS = {"MASS_MERCHANT", "CLUB_STORE"}
ALLERGENS = {"MILK", "EGG", "WHEAT", "SOY", "PEANUT", "TREE_NUT", "SESAME"}
ACCOUNT_READERS = ("BrandAdmin", "DistributorRep", "RetailManager", "SafetyOfficer")


def _get_account(aid):
    a = db["accounts"].get(aid)
    if a is None:
        fail("ERR_NOT_FOUND", 404, "account not found")
    return a


def _get_product(pid):
    p = db["products"].get(pid)
    if p is None:
        fail("ERR_NOT_FOUND", 404, "product not found")
    return p


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------

@bp.post("/api/accounts")
def create_account():
    _, uid = auth("DistributorRep")
    b = body()
    name = req_str(b, "name")
    channel = req_enum(b, "channel", CHANNELS)
    territory_id = req_str(b, "territory_id")
    t = db["territories"].get(territory_id)
    if t is None:
        fail("ERR_NOT_FOUND", 404, "territory not found")
    lazy_territory(t)
    # territory exclusivity: effectively GRANTED to the proposing distributor
    if t["status"] != "GRANTED" or t["granted_distributor_id"] != uid:
        fail("ERR_TERRITORY_VIOLATION", 422,
             "territory is not effectively GRANTED to the proposing distributor")
    now = store.now()
    a = {
        "id": new_id(), "_seq": store.next_seq(), "name": name, "channel": channel,
        "approval_status": "UNDER_REVIEW", "territory_id": territory_id,
        "distributor_id": uid, "approved_at": None,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["accounts"][a["id"]] = a
    return ok(ser_account(a), 201)


@bp.get("/api/accounts")
def list_accounts():
    auth(*ACCOUNT_READERS)
    items = sort_std(db["accounts"].values())
    approval = request.args.get("approval_status")
    territory_id = request.args.get("territory_id")
    distributor_id = request.args.get("distributor_id")
    channel = request.args.get("channel")
    if approval is not None:
        items = [a for a in items if a["approval_status"] == approval]
    if territory_id is not None:
        items = [a for a in items if a["territory_id"] == territory_id]
    if distributor_id is not None:
        items = [a for a in items if a["distributor_id"] == distributor_id]
    if channel is not None:
        items = [a for a in items if a["channel"] == channel]
    return list_response([ser_account(a) for a in items])


@bp.get("/api/accounts/<aid>")
def get_account(aid):
    auth(*ACCOUNT_READERS)
    return ok(ser_account(_get_account(aid)))


@bp.post("/api/accounts/<aid>/review")
def review_account(aid):
    auth("BrandAdmin")
    b = body()
    decision = req_enum(b, "decision", {"APPROVE", "REJECT"})
    a = _get_account(aid)
    if a["approval_status"] == "REJECTED":
        fail("ERR_ALREADY_TERMINAL", 409, "account is REJECTED")
    if a["approval_status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", 409, "account is not UNDER_REVIEW")
    if decision == "APPROVE":
        # channel refusal: the brand never supplies mass / club channels
        if a["channel"] in REFUSED_CHANNELS:
            fail("ERR_CHANNEL_REFUSED", 422, "brand refuses supply to this channel")
        # territory must still be GRANTED to the account's own distributor
        t = db["territories"].get(a["territory_id"])
        if t is not None:
            lazy_territory(t)
        if (t is None or t["status"] != "GRANTED"
                or t["granted_distributor_id"] != a["distributor_id"]):
            fail("ERR_TERRITORY_VIOLATION", 422,
                 "territory is no longer GRANTED to the account's distributor")
        a["approval_status"] = "APPROVED"
        a["approved_at"] = store.now()
        # immediately authorize the account's pending catalog
        for authz in db["authorizations"].values():
            if authz["account_id"] == a["id"] and authz["status"] == "REQUESTED":
                authz["status"] = "AUTHORIZED"
                touch(authz)
    else:
        a["approval_status"] = "REJECTED"
    touch(a)
    return ok(ser_account(a))


@bp.post("/api/accounts/<aid>/suspend")
def suspend_account_endpoint(aid):
    auth("BrandAdmin")
    a = _get_account(aid)
    if a["approval_status"] == "REJECTED":
        fail("ERR_ALREADY_TERMINAL", 409, "account is REJECTED")
    if a["approval_status"] != "APPROVED":
        fail("ERR_INVALID_STATE", 409, "account is not APPROVED")
    suspend_account(a)
    return ok(ser_account(a))


@bp.post("/api/accounts/<aid>/reinstate")
def reinstate_account_endpoint(aid):
    auth("BrandAdmin")
    a = _get_account(aid)
    if a["approval_status"] == "REJECTED":
        fail("ERR_ALREADY_TERMINAL", 409, "account is REJECTED")
    if a["approval_status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", 409, "account is not SUSPENDED")
    reinstate_account(a)
    return ok(ser_account(a))


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------

@bp.post("/api/products")
def create_product():
    auth("BrandAdmin")
    b = body()
    code = req_str(b, "code")
    name = req_str(b, "name")
    base_price_cents = req_int(b, "base_price_cents", min_value=1)
    shelf_life_opened_hours = req_int(b, "shelf_life_opened_hours", min_value=1)
    shelf_life_unopened_days = req_int(b, "shelf_life_unopened_days", min_value=1)
    allergen_tags = req_array(b, "allergen_tags")
    for tag in allergen_tags:
        if not isinstance(tag, str) or tag not in ALLERGENS:
            fail("ERR_VALIDATION", 400,
                 "allergen_tags must contain only MILK, EGG, WHEAT, SOY, PEANUT, TREE_NUT, SESAME")
    requires_dedicated = opt_bool(b, "requires_dedicated_slicer", False)
    channel_restricted = opt_bool(b, "channel_restricted", False)
    for p in db["products"].values():
        if p["code"] == code:
            fail("ERR_DUPLICATE_CODE", 409, "product code already in use")
    now = store.now()
    p = {
        "id": new_id(), "_seq": store.next_seq(), "code": code, "name": name,
        "base_price_cents": base_price_cents,
        "shelf_life_opened_hours": shelf_life_opened_hours,
        "shelf_life_unopened_days": shelf_life_unopened_days,
        "allergen_tags": list(allergen_tags),
        "requires_dedicated_slicer": requires_dedicated,
        "channel_restricted": channel_restricted,
        "status": "ACTIVE",
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["products"][p["id"]] = p
    return ok(ser_product(p), 201)


@bp.get("/api/products")
def list_products():
    auth(*ALL_ROLES)
    items = sort_std(db["products"].values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response([ser_product(p) for p in items])


@bp.get("/api/products/<pid>")
def get_product(pid):
    auth(*ALL_ROLES)
    return ok(ser_product(_get_product(pid)))


# ---------------------------------------------------------------------------
# account product authorizations
# ---------------------------------------------------------------------------

@bp.post("/api/account-product-authorizations")
def create_authorization():
    auth("BrandAdmin")
    b = body()
    account_id = req_str(b, "account_id")
    product_id = req_str(b, "product_id")
    account = db["accounts"].get(account_id)
    if account is None:
        fail("ERR_NOT_FOUND", 404, "account not found")
    product = db["products"].get(product_id)
    if product is None:
        fail("ERR_NOT_FOUND", 404, "product not found")
    # channel restriction enforced at creation
    if product["channel_restricted"] and account["channel"] != "INDEPENDENT_GROCER":
        fail("ERR_PRODUCT_CHANNEL_RESTRICTED", 422,
             "channel_restricted product may only be authorized for INDEPENDENT_GROCER accounts")
    now = store.now()
    status = "AUTHORIZED" if account["approval_status"] == "APPROVED" else "REQUESTED"
    a = {
        "id": new_id(), "_seq": store.next_seq(), "account_id": account_id,
        "product_id": product_id, "status": status, "suspension_source": "NONE",
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["authorizations"][a["id"]] = a
    return ok(ser_authorization(a), 201)


@bp.get("/api/account-product-authorizations")
def list_authorizations():
    auth(*ACCOUNT_READERS)
    items = sort_std(db["authorizations"].values())
    account_id = request.args.get("account_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [a for a in items if a["account_id"] == account_id]
    if product_id is not None:
        items = [a for a in items if a["product_id"] == product_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response([ser_authorization(a) for a in items])


@bp.get("/api/account-product-authorizations/<aid>")
def get_authorization(aid):
    auth(*ACCOUNT_READERS)
    a = db["authorizations"].get(aid)
    if a is None:
        fail("ERR_NOT_FOUND", 404, "authorization not found")
    return ok(ser_authorization(a))


@bp.post("/api/account-product-authorizations/<aid>/revoke")
def revoke_authorization(aid):
    auth("BrandAdmin")
    a = db["authorizations"].get(aid)
    if a is None:
        fail("ERR_NOT_FOUND", 404, "authorization not found")
    if a["status"] == "REVOKED":
        fail("ERR_ALREADY_TERMINAL", 409, "authorization is REVOKED")
    if a["status"] not in ("AUTHORIZED", "SUSPENDED"):
        fail("ERR_INVALID_STATE", 409, "authorization is not AUTHORIZED or SUSPENDED")
    a["status"] = "REVOKED"
    touch(a)
    return ok(ser_authorization(a))
