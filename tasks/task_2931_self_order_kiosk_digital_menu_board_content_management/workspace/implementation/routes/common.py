"""Shared route plumbing: filters, pagination, path resolution."""
from flask import request

import response
import serialize
from db import DB, ordered
from errors import fail

FILTERS = {
    "price_zones": ("zone_code",),
    "clusters": ("parent_cluster_id", "tier"),
    "stores": ("cluster_id", "price_zone_id", "content_posture"),
    "menu_items": ("category", "accessibility_state", "chainwide_availability_state"),
    "price_requests": ("menu_item_id", "price_zone_id", "state"),
    "availabilities": ("store_id", "menu_item_id", "availability_state"),
    "campaigns": ("cluster_id", "campaign_code", "state"),
    "upsell_rules": ("cluster_id", "trigger_item_id", "suggested_item_id", "state"),
    "bundles": ("cluster_id", "state"),
    "devices": ("store_id", "cached_bundle_id", "device_kind", "health_state"),
    "orders": ("device_id", "applied_campaign_version_id", "handoff_state"),
    "audit_events": ("subject_kind", "subject_id", "action"),
}


def apply_filters(rows, collection):
    for name in FILTERS[collection]:
        wanted = request.args.get(name)
        if wanted is None:
            continue
        rows = [r for r in rows if r.get(name) is not None and str(r.get(name)) == wanted]
    return rows


def listing(collection, kind, rows=None):
    limit, offset = response.read_pagination(request.args)
    if rows is None:
        rows = ordered(list(getattr(DB, collection).values()))
    rows = apply_filters(rows, collection)
    return response.collection(serialize.dump_many(kind, rows), limit, offset)


def path_row(collection, row_id):
    """Path identifiers resolve left to right; the first miss is a 404."""
    row = getattr(DB, collection).get(row_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no such %s" % collection)
    return row


def fk(data, field, collection):
    """Body foreign keys: an unresolved reference is a 404 (precedence 6)."""
    value = data.get(field)
    if value is None or not isinstance(value, str):
        return None
    if value not in getattr(DB, collection):
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND", "%s does not resolve" % field)
    return value


def unique_or_conflict(collection, field, value, scope_field=None, scope_value=None):
    for row in getattr(DB, collection).values():
        if row.get(field) != value:
            continue
        if scope_field is not None and row.get(scope_field) != scope_value:
            continue
        fail("ERR_DUPLICATE_NATURAL_KEY", "%s is already in use" % field)
