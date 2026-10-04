"""Batching surfaces: licence hold groups and deployment groups."""

import calc
import constants as K
from auth import roles
from error import (
    CatalogError,
    ERR_ALLOCATED_UNITS_CHANGED,
    ERR_EXPORT_LICENSE_REQUIRED,
    ERR_EXPORT_CONTROL_RESTRICTED,
    ERR_GROUP_NOT_SATISFIED,
    ERR_HOLD_TIER_EXCEEDS_BAND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LICENSE_GROUP_DUPLICATE_MEMBER,
    ERR_NO_ALLOCATION_CANDIDATE,
    ERR_NO_OPEN_EPOCH,
    ERR_NODE_NOT_OPEN_FOR_ALLOCATION,
    ERR_PARTNER_NOT_FOUND,
)
from envelope import created, ok
from rules import resolve, resource_or_404
from services import (
    append_audit,
    derive_product_allocated,
    move_capacity_ledger,
    recompute_node,
    serialize,
)
from store import DB
from util import require, require_enum

GROUP = "groups"


def _caller_partner(caller):
    partner = resolve("partners", caller.user_id)
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND, "X-User-ID does not name a partner account.")
    return partner


# ------------------------------------------------------ licence hold groups --
def _create_license_group(caller):
    from flask import request
    body = request.raw_payload or {}
    partner = _caller_partner(caller)
    members = body.get("members")
    if not isinstance(members, list) or not members:
        raise CatalogError(ERR_INVALID_REQUEST, "'members' must be a non-empty array.")
    tier = require_enum(body.get("hold_friction_tier") or "COOL", K.HOTNESS_TIERS, "hold_friction_tier")

    product = resolve("products", body.get("product_sku_id"))
    if product is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'product_sku_id' does not resolve.")
    node = resolve("nodes", body.get("supply_node_id"))
    if node is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'supply_node_id' does not resolve.")
    partner_ref = resolve("partners", body.get("partner_id")) if body.get("partner_id") else partner
    if partner_ref is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)

    # Priority 6: export control on the group's SKU.
    from rules import check_export_gate
    if body.get("destination_country_code"):
        check_export_gate(product, body["destination_country_code"])

    # Priority 9 / 10 / 11.
    if K.TIER_INDEX[tier] > K.TIER_INDEX[node.get("temp_band_ceiling", "COOL")]:
        raise CatalogError(ERR_HOLD_TIER_EXCEEDS_BAND)
    if node.get("stage") in ("DRAINING", "BINDING"):
        raise CatalogError(ERR_NODE_NOT_OPEN_FOR_ALLOCATION)
    if DB.open_epoch() is None:
        raise CatalogError(ERR_NO_OPEN_EPOCH)

    # Each product reference at most once.
    seen = set()
    total_units = 0
    for member in members:
        reference = member.get("product_sku_id") if isinstance(member, dict) else None
        if reference in seen:
            raise CatalogError(ERR_LICENSE_GROUP_DUPLICATE_MEMBER)
        seen.add(reference)
        total_units += int(member.get("quantity_units", 0)) if isinstance(member, dict) else int(member)

    if body.get("expected_allocated_units") is not None:
        if int(body["expected_allocated_units"]) != int(product.get("allocated_units", 0) or 0):
            raise CatalogError(ERR_ALLOCATED_UNITS_CHANGED)

    group = DB.mint({
        "partner_id": partner_ref["id"],
        "product_sku_id": product["id"],
        "supply_node_id": node["id"],
        "hold_friction_tier": tier,
        "group_satisfied": False,
        "member_count": len(members),
        "total_units": total_units,
    })
    DB.license_hold_groups[group["id"]] = group

    lines = []
    for member in members:
        quantity = int(member.get("quantity_units", 0)) if isinstance(member, dict) else int(member)
        if quantity <= 0:
            raise CatalogError(ERR_INVALID_REQUEST, "Each member quantity must be positive.")
        rate, _fee = calc.committed_rate_v2(partner_ref, quantity)
        line = DB.mint({
            "group_id": group["id"],
            "partner_id": partner_ref["id"],
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "quantity_units": quantity,
            "hold_friction_tier": tier,
            "committed_rate_v2": float(rate),
            "state": "REQUESTED",
        })
        DB.license_holds[line["id"]] = line
        lines.append(line)
    DB.bump(partner_ref)
    recompute_node(node)
    return created({
        **serialize(group),
        "members": [serialize(line) for line in lines],
    })


def _read_license_group(caller, group_id):
    from error import ERR_RESOURCE_NOT_FOUND
    group = DB.license_hold_groups.get(group_id)
    if group is None:
        raise CatalogError(ERR_RESOURCE_NOT_FOUND, "The licence hold group does not exist.")
    lines = [serialize(line) for line in DB.license_holds.values() if line.get("group_id") == group["id"]]
    return ok({**serialize(group), "members": lines})


def _read_license_hold(caller, hold_id):
    from error import ERR_RESOURCE_NOT_FOUND
    line = DB.license_holds.get(hold_id)
    if line is None:
        raise CatalogError(ERR_RESOURCE_NOT_FOUND, "The licence hold does not exist.")
    return ok(serialize(line))


def _preempt_group(caller, group_id):
    from error import ERR_RESOURCE_NOT_FOUND
    group = DB.license_hold_groups.get(group_id)
    if group is None:
        raise CatalogError(ERR_RESOURCE_NOT_FOUND, "The licence hold group does not exist.")
    node = DB.nodes.get(group.get("supply_node_id"))
    if node is None:
        raise CatalogError(ERR_INVALID_REQUEST, "The group's supply node no longer exists.")

    needed = int(group.get("total_units", 0))
    candidates = [
        (hold, node) for hold in DB.holds.values()
        if hold.get("product_sku_id") == node.get("product_sku_id")
        and hold.get("state") == "REQUESTED"
        and K.TIER_INDEX[hold.get("hold_friction_tier", "COOL")]
        <= K.TIER_INDEX[node.get("temp_band_ceiling", "COOL")]
    ]
    if not candidates:
        raise CatalogError(ERR_NO_ALLOCATION_CANDIDATE)
    ordered = calc.allocation_priority_ranking(DB, candidates)
    accumulated = 0
    displaced = []
    for hold in ordered:
        displaced.append(hold)
        accumulated += int(hold.get("quantity_units", 0))
        if accumulated >= needed:
            break
    for hold in displaced:
        hold["state"] = "RECLAIMED"
        DB.touch(hold)
        move_capacity_ledger(DB.partners.get(hold.get("partner_id")), -int(hold.get("quantity_units", 0)))
    group["group_satisfied"] = True
    DB.touch(group)
    recompute_node(node)
    return ok({"displaced": [serialize(row) for row in displaced], "group": serialize(group)})


# --------------------------------------------------------- deployment groups --
def _create_deployment_group(caller):
    from flask import request
    body = request.raw_payload or {}
    members = body.get("members")
    if not isinstance(members, list) or not members:
        raise CatalogError(ERR_INVALID_REQUEST, "'members' must be a non-empty array.")
    resolved = []
    for member in members:
        deployment_id = member.get("deployment_id") if isinstance(member, dict) else member
        deployment = DB.deployments.get(deployment_id)
        if deployment is None:
            raise CatalogError(ERR_INVALID_REQUEST, "A member deployment does not exist.")
        resolved.append(deployment["id"])
    group = DB.mint({
        "partner_id": body.get("partner_id"),
        "group_satisfied": bool(body.get("group_satisfied", False)),
        "member_ids": resolved,
        "dispatch_status": "OPEN",
    })
    DB.deployment_groups[group["id"]] = group
    return created(serialize(group))


def _read_deployment_group(caller, group_id):
    from error import ERR_RESOURCE_NOT_FOUND
    group = DB.deployment_groups.get(group_id)
    if group is None:
        raise CatalogError(ERR_RESOURCE_NOT_FOUND, "The deployment group does not exist.")
    return ok(serialize(group))


def _dispatch_group(caller, group_id):
    from error import ERR_RESOURCE_NOT_FOUND
    group = DB.deployment_groups.get(group_id)
    if group is None:
        raise CatalogError(ERR_RESOURCE_NOT_FOUND, "The deployment group does not exist.")
    if not group.get("group_satisfied"):
        raise CatalogError(ERR_GROUP_NOT_SATISFIED)
    for deployment_id in group.get("member_ids", []):
        deployment = DB.deployments.get(deployment_id)
        if deployment is None:
            continue
        deployment["activation_state"] = "ACTIVATED" if deployment.get("activation_state") == "PENDING" else deployment.get("activation_state")
        DB.touch(deployment)
    group["dispatch_status"] = "DISPATCHED"
    DB.touch(group)
    return ok(serialize(group))


ROUTES = [
    ("POST", "/accelerators/license-hold-groups", _create_license_group, ("PartnerOps",)),
    ("GET", "/accelerators/license-hold-groups/<group_id>", _read_license_group, ("PartnerOps",)),
    ("GET", "/accelerators/license-holds/<hold_id>", _read_license_hold, ("PartnerOps",)),
    ("POST", "/accelerators/license-hold-groups/<group_id>/preempt", _preempt_group, ("PlatformAdmin",)),
    ("POST", "/accelerators/deployment-groups", _create_deployment_group, ("SupportAccountManager",)),
    ("GET", "/accelerators/deployment-groups/<group_id>", _read_deployment_group, ("SupportAccountManager",)),
    ("POST", "/accelerators/deployment-groups/<group_id>/dispatch", _dispatch_group, ("SupportAccountManager",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])