"""Vendors, JurisdictionRules, Stores, LoyaltyMembers."""

from __future__ import annotations

from flask import Blueprint

from db import db
from errors import not_found, invalid_request
from middleware import (
    require_roles,
    get_json_body,
    check_unknown_fields,
    require_fields,
    check_enum,
    check_int_range,
    check_int_ge,
    check_string,
    parse_pagination,
)
from response import success_object, success_list
from services.core import (
    next_seq,
    sort_by_created,
    serialize_vendor,
    serialize_jurisdiction,
    serialize_store,
    serialize_member,
    serialize_lot,
    serialize_allocation,
    serialize_assignment,
    serialize_purchase,
    touch,
)

bp = Blueprint("refdata", __name__)

ANY_ROLE = [
    "Admin", "SourcingBuyer", "SafetyOfficer", "PricingLead",
    "AllocationManager", "StoreManager", "ClubMember", "Anonymous",
]

COMPARISON_RULES = ["WAS_NOW_WINDOW", "MSRP_REFERENCE", "COMPARISON_PROHIBITED"]
PERFORMANCE_TIERS = ["TIER_1", "TIER_2", "TIER_3"]
MEMBER_TIERS = ["BRONZE", "SILVER", "GOLD"]
STATUS_AS = ["ACTIVE", "SUSPENDED"]


def new_entity() -> dict:
    return {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "_seq": next_seq(),
    }


def _get_or_404(store_dict, entity_id: str, label: str) -> dict:
    e = store_dict.get(entity_id)
    if e is None:
        raise not_found("%s not found: %s" % (label, entity_id))
    return e


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@bp.post("/vendors")
def create_vendor():
    require_roles(["SourcingBuyer", "Admin"])
    body = get_json_body()
    check_unknown_fields(body, ["name", "vendor_code"])
    require_fields(body, ["name", "vendor_code"])
    check_string(body, "name")
    check_string(body, "vendor_code")
    v = new_entity()
    v.update({"name": body["name"], "vendor_code": body["vendor_code"]})
    db.vendors[v["id"]] = v
    return success_object(serialize_vendor(v), 201)


@bp.get("/vendors/<vid>")
def get_vendor(vid):
    require_roles(ANY_ROLE)
    v = _get_or_404(db.vendors, vid, "Vendor")
    return success_object(serialize_vendor(v))


@bp.get("/vendors/<vid>/lots")
def list_vendor_lots(vid):
    require_roles(ANY_ROLE)
    _get_or_404(db.vendors, vid, "Vendor")
    limit, offset = parse_pagination()
    items = sort_by_created([l for l in db.lots.values() if l["vendor_id"] == vid])
    total = len(items)
    return success_list([serialize_lot(l) for l in items[offset:offset + limit]], limit, offset, total)


# ---------------------------------------------------------------------------
# JurisdictionRules
# ---------------------------------------------------------------------------

@bp.post("/jurisdiction-rules")
def create_jurisdiction_rule():
    require_roles(["PricingLead", "Admin"])
    body = get_json_body()
    check_unknown_fields(body, [
        "jurisdiction_code", "comparison_rule", "window_days",
        "required_offer_days", "max_advertised_discount_pct",
        "member_discount_cap_pct",
    ])
    require_fields(body, [
        "jurisdiction_code", "comparison_rule",
        "max_advertised_discount_pct", "member_discount_cap_pct",
    ])
    check_string(body, "jurisdiction_code")
    check_enum(body, "comparison_rule", COMPARISON_RULES)
    check_int_range(body, "max_advertised_discount_pct", 0, 100)
    check_int_range(body, "member_discount_cap_pct", 0, 100)
    if body["comparison_rule"] == "WAS_NOW_WINDOW":
        require_fields(body, ["window_days", "required_offer_days"])
        check_int_ge(body, "window_days", 0)
        check_int_ge(body, "required_offer_days", 0)
    else:
        if "window_days" in body and body["window_days"] is not None:
            raise invalid_request("window_days is only valid for WAS_NOW_WINDOW rules")
        if "required_offer_days" in body and body["required_offer_days"] is not None:
            raise invalid_request("required_offer_days is only valid for WAS_NOW_WINDOW rules")
    j = new_entity()
    j.update({
        "jurisdiction_code": body["jurisdiction_code"],
        "comparison_rule": body["comparison_rule"],
        "window_days": body.get("window_days"),
        "required_offer_days": body.get("required_offer_days"),
        "max_advertised_discount_pct": body["max_advertised_discount_pct"],
        "member_discount_cap_pct": body["member_discount_cap_pct"],
    })
    db.jurisdiction_rules[j["id"]] = j
    return success_object(serialize_jurisdiction(j), 201)


@bp.get("/jurisdiction-rules/<jid>")
def get_jurisdiction_rule(jid):
    require_roles(ANY_ROLE)
    j = _get_or_404(db.jurisdiction_rules, jid, "JurisdictionRule")
    return success_object(serialize_jurisdiction(j))


@bp.get("/jurisdiction-rules/<jid>/stores")
def list_jurisdiction_stores(jid):
    require_roles(ANY_ROLE)
    _get_or_404(db.jurisdiction_rules, jid, "JurisdictionRule")
    limit, offset = parse_pagination()
    items = sort_by_created([s for s in db.stores.values() if s["jurisdiction_id"] == jid])
    total = len(items)
    return success_list([serialize_store(s) for s in items[offset:offset + limit]], limit, offset, total)


@bp.get("/jurisdiction-rules/<jid>/lots")
def list_jurisdiction_lots(jid):
    require_roles(ANY_ROLE)
    _get_or_404(db.jurisdiction_rules, jid, "JurisdictionRule")
    limit, offset = parse_pagination()
    items = sort_by_created([l for l in db.lots.values() if l["home_jurisdiction_id"] == jid])
    total = len(items)
    return success_list([serialize_lot(l) for l in items[offset:offset + limit]], limit, offset, total)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

@bp.post("/stores")
def create_store():
    require_roles(["Admin"])
    body = get_json_body()
    check_unknown_fields(body, ["name", "store_code", "jurisdiction_id", "performance_tier"])
    require_fields(body, ["name", "store_code", "jurisdiction_id", "performance_tier"])
    check_string(body, "name")
    check_string(body, "store_code")
    check_enum(body, "performance_tier", PERFORMANCE_TIERS)
    _get_or_404(db.jurisdiction_rules, body["jurisdiction_id"], "JurisdictionRule")
    s = new_entity()
    s.update({
        "name": body["name"],
        "store_code": body["store_code"],
        "jurisdiction_id": body["jurisdiction_id"],
        "performance_tier": body["performance_tier"],
        "status": "ACTIVE",
    })
    db.stores[s["id"]] = s
    return success_object(serialize_store(s), 201)


@bp.get("/stores/<sid>")
def get_store(sid):
    require_roles(ANY_ROLE)
    s = _get_or_404(db.stores, sid, "Store")
    return success_object(serialize_store(s))


@bp.patch("/stores/<sid>")
def update_store(sid):
    require_roles(["Admin"])
    s = _get_or_404(db.stores, sid, "Store")
    body = get_json_body()
    check_unknown_fields(body, ["status", "performance_tier"])
    check_enum(body, "status", STATUS_AS)
    check_enum(body, "performance_tier", PERFORMANCE_TIERS)
    if "status" in body and body["status"] is not None:
        s["status"] = body["status"]
    if "performance_tier" in body and body["performance_tier"] is not None:
        s["performance_tier"] = body["performance_tier"]
    touch(s)
    return success_object(serialize_store(s))


@bp.get("/stores/<sid>/allocations")
def list_store_allocations(sid):
    require_roles(ANY_ROLE)
    _get_or_404(db.stores, sid, "Store")
    limit, offset = parse_pagination()
    items = sort_by_created([a for a in db.allocations.values() if a["store_id"] == sid])
    total = len(items)
    return success_list([serialize_allocation(a) for a in items[offset:offset + limit]], limit, offset, total)


@bp.get("/stores/<sid>/aisle-assignments")
def list_store_assignments(sid):
    require_roles(ANY_ROLE)
    _get_or_404(db.stores, sid, "Store")
    limit, offset = parse_pagination()
    items = sort_by_created([a for a in db.aisle_assignments.values() if a["store_id"] == sid])
    total = len(items)
    return success_list([serialize_assignment(a) for a in items[offset:offset + limit]], limit, offset, total)


@bp.get("/stores/<sid>/members")
def list_store_members(sid):
    require_roles(ANY_ROLE)
    _get_or_404(db.stores, sid, "Store")
    limit, offset = parse_pagination()
    items = sort_by_created([m for m in db.members.values() if m["home_store_id"] == sid])
    total = len(items)
    return success_list([serialize_member(m) for m in items[offset:offset + limit]], limit, offset, total)


@bp.get("/stores/<sid>/purchases")
def list_store_purchases(sid):
    require_roles(ANY_ROLE)
    _get_or_404(db.stores, sid, "Store")
    limit, offset = parse_pagination()
    items = sort_by_created([p for p in db.purchases.values() if p["store_id"] == sid])
    total = len(items)
    return success_list([serialize_purchase(p) for p in items[offset:offset + limit]], limit, offset, total)


# ---------------------------------------------------------------------------
# LoyaltyMembers
# ---------------------------------------------------------------------------

@bp.post("/members")
def create_member():
    require_roles(["Anonymous", "Admin"])
    body = get_json_body()
    check_unknown_fields(body, ["member_code", "tier", "home_store_id"])
    require_fields(body, ["member_code", "tier", "home_store_id"])
    check_string(body, "member_code")
    check_enum(body, "tier", MEMBER_TIERS)
    _get_or_404(db.stores, body["home_store_id"], "Store")
    m = new_entity()
    m.update({
        "member_code": body["member_code"],
        "tier": body["tier"],
        "home_store_id": body["home_store_id"],
        "status": "ACTIVE",
    })
    db.members[m["id"]] = m
    return success_object(serialize_member(m), 201)


@bp.get("/members/<mid>")
def get_member(mid):
    require_roles(ANY_ROLE)
    m = _get_or_404(db.members, mid, "LoyaltyMember")
    return success_object(serialize_member(m))


@bp.patch("/members/<mid>")
def update_member(mid):
    require_roles(["Admin"])
    m = _get_or_404(db.members, mid, "LoyaltyMember")
    body = get_json_body()
    check_unknown_fields(body, ["status", "tier"])
    check_enum(body, "status", STATUS_AS)
    check_enum(body, "tier", MEMBER_TIERS)
    if "status" in body and body["status"] is not None:
        m["status"] = body["status"]
    if "tier" in body and body["tier"] is not None:
        m["tier"] = body["tier"]
    touch(m)
    return success_object(serialize_member(m))


@bp.get("/members/<mid>/purchases")
def list_member_purchases(mid):
    require_roles(ANY_ROLE)
    _get_or_404(db.members, mid, "LoyaltyMember")
    limit, offset = parse_pagination()
    items = sort_by_created([p for p in db.purchases.values() if p["member_id"] == mid])
    total = len(items)
    return success_list([serialize_purchase(p) for p in items[offset:offset + limit]], limit, offset, total)
