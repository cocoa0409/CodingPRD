"""Content items (§3.9): create, list/get with visibility, transition, share, moderate."""
from flask import Blueprint, request

import calc
import store
from auth import require_role
from envelope import paginate, success
from errors import err
from helpers import get_body, require_fields

bp = Blueprint("items", __name__)

ITEM_KINDS = "FEATURE_LAYER|TILE_LAYER|BASEMAP|WEB_MAP|NOTEBOOK|API_APP"
PUBLIC_LEVELS = {"CREATOR", "PROFESSIONAL", "PROFESSIONAL_PLUS"}


def _visible(item, caller_id, role):
    """Content visibility (§3.9): invisible -> treated as not found."""
    level = item["sharing_level"]
    if level == "PUBLIC":
        return True
    if level == "PRIVATE":
        return (caller_id == item["owner_named_user_id"]
                or role in ("PlatformAdmin", "ContentModerator"))
    # ORGANIZATION: same-org members. For entity-backed roles resolve org via NamedUser.
    if role in ("PlatformAdmin", "ContentModerator", "LicenseAdmin", "BillingAdmin"):
        return True
    user = store.named_users.get(caller_id)
    if user is not None and user["organization_id"] == item["organization_id"]:
        return True
    return caller_id == item["owner_named_user_id"]


@bp.post("/geo-orgs/content-items")
def create_item():
    caller_id, role = require_role("NamedUser")
    body = get_body()
    require_fields(body, [
        ("organization_id", "str", True),
        ("title", "str", True),
        ("item_kind", "enum:" + ITEM_KINDS, True),
        ("storage_bytes", "int", True),
        ("derived_from_item_id", "str", False),
        ("contains_licensed_basemap", "bool", False),
        ("offline_enabled", "bool", False),
    ])
    org = store.orgs.get(body["organization_id"])
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")
    if body.get("derived_from_item_id") is not None:
        if body["derived_from_item_id"] not in store.content_items:
            raise err("ERR_ITEM_NOT_FOUND")
    rec = store.new_record()
    rec.update({
        "organization_id": org["id"],
        "owner_named_user_id": caller_id,
        "title": body["title"],
        "item_kind": body["item_kind"],
        "sharing_level": "PRIVATE",
        "derived_from_item_id": body.get("derived_from_item_id"),
        "contains_licensed_basemap": body.get("contains_licensed_basemap", False),
        "offline_enabled": body.get("offline_enabled", False),
        "storage_bytes": body["storage_bytes"],
        "resolution_rationale": None,
        "status": "DRAFT",
    })
    store.content_items[rec["id"]] = rec
    return success(dict(rec), status=201)


@bp.get("/geo-orgs/content-items")
def list_items():
    caller_id, role = require_role("PlatformAdmin", "LicenseAdmin", "ContentModerator",
                                   "ComplianceOfficer", "NamedUser")
    items = [i for i in store.content_items.values() if _visible(i, caller_id, role)]
    items.sort(key=lambda r: r["created_at"])
    for param in ("organization_id", "owner_named_user_id", "derived_from_item_id",
                  "sharing_level", "status", "item_kind"):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if i.get(param) == v]
    page, pg = paginate(items, request.args)
    return success([dict(i) for i in page], pagination=pg)


@bp.get("/geo-orgs/content-items/<item_id>")
def get_item(item_id):
    caller_id, role = require_role("PlatformAdmin", "LicenseAdmin", "ContentModerator",
                                   "ComplianceOfficer", "NamedUser")
    item = store.content_items.get(item_id)
    if item is None or not _visible(item, caller_id, role):
        raise err("ERR_ITEM_NOT_FOUND")
    return success(dict(item))


def _synthesize_storage_batch(item):
    org = store.orgs.get(item["organization_id"])
    units = calc.storage_units(item["storage_bytes"])
    rec = store.new_record()
    rec.update({
        "organization_id": item["organization_id"],
        "api_key_id": None,
        "service_kind": "STORAGE",
        "requested_units": units,
        "extension_code": None,
        "provisional_credits": calc.provisional_credits("STORAGE", units, 0),
        "settled_credits": None,
        "idempotency_key": "storage:" + item["id"],
        "status": "PENDING",
        "creation_period_index": org["current_period_index"] if org else 0,
        "content_item_id": item["id"],
    })
    store.credit_batches[rec["id"]] = rec
    pool = store.pool_for_org(item["organization_id"])
    if pool is not None:
        pool["reserved_credits"] += rec["provisional_credits"]
        store.touch(pool)
        calc.refresh_pool(pool)
    return rec


def _reverse_storage_batch(item):
    for batch in store.credit_batches.values():
        if (batch.get("content_item_id") == item["id"]
                and batch["status"] == "PENDING"):
            batch["status"] = "REVERSED"
            store.touch(batch)
            pool = store.pool_for_org(item["organization_id"])
            if pool is not None:
                pool["reserved_credits"] -= batch["provisional_credits"]
                store.touch(pool)
                calc.refresh_pool(pool)


def _org_has_active_grant_with(org_id, predicate):
    for grant in store.license_grants.values():
        if grant["organization_id"] != org_id or grant["status"] != "ACTIVE":
            continue
        product = store.license_products.get(grant["license_product_id"])
        if product is not None and predicate(product):
            return True
    return False


@bp.post("/geo-orgs/content-items/<item_id>/transition")
def item_transition(item_id):
    caller_id, role = require_role("NamedUser", "ContentModerator")
    body = get_body()
    require_fields(body, [("target_status", "enum:PUBLISHED|RETRACTED", True)])
    target = body["target_status"]
    item = store.content_items.get(item_id)
    if item is None:
        raise err("ERR_ITEM_NOT_FOUND")

    if target == "PUBLISHED":
        if role != "NamedUser":
            raise err("ERR_INSUFFICIENT_PERMISSIONS", "publish requires the owner NamedUser")
        if item["status"] != "DRAFT":
            raise err("ERR_ITEM_NOT_DRAFT")
        if caller_id != item["owner_named_user_id"]:
            raise err("ERR_NOT_ITEM_OWNER")
        owner = store.named_users.get(item["owner_named_user_id"])
        if owner is None or owner["status"] != "ACTIVE":
            raise err("ERR_USER_NOT_ACTIVE")
        org = store.orgs.get(item["organization_id"])
        if org is None or org["status"] != "ACTIVE":
            raise err("ERR_ORG_NOT_ACTIVE")
        if item.get("derived_from_item_id"):
            if not _org_has_active_grant_with(item["organization_id"],
                                              lambda p: p["allows_derivative_works"]):
                raise err("ERR_DERIVATIVE_WORKS_NOT_LICENSED")
            source = store.content_items.get(item["derived_from_item_id"])
            if source is None or source["status"] != "PUBLISHED":
                raise err("ERR_DERIVATIVE_SOURCE_UNAVAILABLE")
        if item.get("offline_enabled"):
            if not _org_has_active_grant_with(item["organization_id"],
                                              lambda p: p["supports_offline"]):
                raise err("ERR_OFFLINE_NOT_LICENSED")
        item["status"] = "PUBLISHED"
        item["sharing_level"] = "PRIVATE"
        store.touch(item)
        _synthesize_storage_batch(item)
    elif target == "RETRACTED":
        if item["status"] != "PUBLISHED":
            raise err("ERR_ITEM_NOT_PUBLISHED")
        if role != "ContentModerator" and caller_id != item["owner_named_user_id"]:
            raise err("ERR_NOT_ITEM_OWNER")
        item["status"] = "RETRACTED"
        store.touch(item)
        _reverse_storage_batch(item)
    return success(dict(item))


@bp.post("/geo-orgs/content-items/<item_id>/share")
def item_share(item_id):
    caller_id, role = require_role("NamedUser")
    body = get_body()
    require_fields(body, [
        ("target_sharing_level", "enum:PRIVATE|ORGANIZATION|PUBLIC", True),
        ("expected_content_item_version", "int", True),
    ])
    item = store.content_items.get(item_id)
    if item is None:
        raise err("ERR_ITEM_NOT_FOUND")
    # OCC (priority 5)
    if body["expected_content_item_version"] != item["version"]:
        raise err("ERR_STALE_VERSION")
    target = body["target_sharing_level"]
    current = item["sharing_level"]
    if item["status"] != "PUBLISHED":
        raise err("ERR_ITEM_NOT_PUBLISHED")
    if caller_id != item["owner_named_user_id"]:
        raise err("ERR_NOT_ITEM_OWNER")
    allowed = {
        ("PRIVATE", "ORGANIZATION"),
        ("ORGANIZATION", "PUBLIC"),
        ("PUBLIC", "ORGANIZATION"),
        ("ORGANIZATION", "PRIVATE"),
    }
    if (current, target) not in allowed:
        raise err("ERR_INVALID_SHARING_TRANSITION")
    if target == "PUBLIC":
        owner = store.named_users.get(item["owner_named_user_id"])
        if owner is None or owner["named_user_level"] not in PUBLIC_LEVELS:
            raise err("ERR_INSUFFICIENT_USER_LEVEL")
        if item.get("contains_licensed_basemap"):
            if not _org_has_active_grant_with(item["organization_id"],
                                              lambda p: p["edition"] == "ADVANCED"):
                raise err("ERR_BASEMAP_PUBLIC_REQUIRES_ADVANCED")
    item["sharing_level"] = target
    store.touch(item)
    return success(dict(item))


@bp.post("/geo-orgs/content-items/<item_id>/moderate")
def item_moderate(item_id):
    require_role("ContentModerator")
    body = get_body()
    require_fields(body, [("action", "enum:FLAG|RESOLVE", True)])
    item = store.content_items.get(item_id)
    if item is None:
        raise err("ERR_ITEM_NOT_FOUND")
    action = body["action"]
    if action == "FLAG":
        if item["status"] != "PUBLISHED":
            raise err("ERR_ITEM_NOT_PUBLISHED")
        item["status"] = "FLAGGED"
        item["sharing_level"] = "PRIVATE"
        store.touch(item)
        # Depth-1 cascade: direct derivatives that are PUBLISHED -> FLAGGED
        for other in store.content_items.values():
            if (other["id"] != item["id"]
                    and other.get("derived_from_item_id") == item["id"]
                    and other["status"] == "PUBLISHED"):
                other["status"] = "FLAGGED"
                other["sharing_level"] = "PRIVATE"
                store.touch(other)
    else:  # RESOLVE
        if item["status"] != "FLAGGED":
            raise err("ERR_ITEM_NOT_FLAGGED")
        rationale = body.get("resolution_rationale")
        if not isinstance(rationale, str) or len(rationale) < 20:
            raise err("ERR_INSUFFICIENT_RATIONALE",
                      "resolution_rationale must be at least 20 characters")
        item["status"] = "PUBLISHED"
        item["resolution_rationale"] = rationale
        store.touch(item)
    return success(dict(item))
