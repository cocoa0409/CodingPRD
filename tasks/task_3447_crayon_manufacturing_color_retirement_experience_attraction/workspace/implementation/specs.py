"""Assortment specs (PRD section 3.4): creation, derived status, aggregates."""
from flask import request

from calculations import recompute_spec
from constants import BOX_SIZES, OPS_ROLES, ROLE_ALLOCATION_PLANNER, ROLE_PLATFORM_ADMIN
from envelope import ok, paginate
from errors import ApiError
from store import STORE
from validation import (
    apply_filters, auth, body, get_or_404, new_entity, pagination_params,
    req_enum, req_int, req_str, require_role,
)


def serialize_spec(spec):
    return {
        "id": spec["id"],
        "name": spec["name"],
        "kind": spec["kind"],
        "partner_name": spec["partner_name"],
        "entries": spec["entries"],
        "wholesale_price_cents": spec["wholesale_price_cents"],
        "box_size": spec["box_size"],
        "status": spec["status"],
        "boxes_available": spec["boxes_available"],
        "boxes_reserved": spec["boxes_reserved"],
        "created_at": spec["created_at"],
        "updated_at": spec["updated_at"],
        "version": spec["version"],
    }


def _validate_entries(entries):
    """Structural spec validation (stage 9); returns the entry color-id set."""
    if len(entries) == 0:
        raise ApiError("ERR_SPEC_INVALID", "entries must be non-empty")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each entry must be an object")
        color_id = entry.get("color_id")
        count = entry.get("count")
        if not isinstance(color_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "entry.color_id is required and must be a string")
        if not isinstance(count, int) or isinstance(count, bool):
            raise ApiError("ERR_INVALID_REQUEST", "entry.count is required and must be an integer")
        if count < 1:
            raise ApiError("ERR_SPEC_INVALID", "entry.count must be >= 1")
        if color_id in seen:
            raise ApiError("ERR_SPEC_INVALID", "at most one entry per color")
        seen.add(color_id)
        color = STORE.colors.get(color_id)
        if color is None or color["status"] != "ACTIVE":
            raise ApiError("ERR_SPEC_INVALID", "every entry color must exist and be ACTIVE")
    return seen


def create_spec():
    _, role = auth()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    data = body()
    name = req_str(data, "name")
    kind = req_enum(data, "kind", ("RETAIL", "CLASSROOM", "LICENSED"))
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ApiError("ERR_INVALID_REQUEST", "entries is required and must be an array")
    price = req_int(data, "wholesale_price_cents")
    partner_name = data.get("partner_name")
    # Conditional field: partner_name exactly when kind == CLASSROOM.
    if kind == "CLASSROOM":
        if not isinstance(partner_name, str):
            raise ApiError("ERR_INVALID_REQUEST", "partner_name is required for CLASSROOM specs")
    elif partner_name is not None:
        raise ApiError("ERR_INVALID_REQUEST", "partner_name must be omitted unless kind is CLASSROOM")
    if price < 1:
        raise ApiError("ERR_INVALID_REQUEST", "wholesale_price_cents must be >= 1")
    # Structural validation (stage 9).
    color_ids = _validate_entries(entries)
    box_size = sum(e["count"] for e in entries)
    if box_size not in BOX_SIZES:
        raise ApiError("ERR_SPEC_INVALID", "box_size must be one of 8, 16, 24, 64")
    if kind == "CLASSROOM":
        for color in STORE.colors.values():
            if (color["is_core_curriculum"] and color["status"] == "ACTIVE"
                    and color["id"] not in color_ids):
                raise ApiError(
                    "ERR_SPEC_INVALID",
                    "CLASSROOM spec must include every ACTIVE core-curriculum color")
    spec = new_entity({
        "name": name,
        "kind": kind,
        "partner_name": partner_name if kind == "CLASSROOM" else None,
        "entries": [{"color_id": e["color_id"], "count": e["count"]} for e in entries],
        "wholesale_price_cents": price,
        "box_size": box_size,
        "status": "ACTIVE",
        "boxes_available": 0,
        "boxes_reserved": 0,
    })
    STORE.specs[spec["id"]] = spec
    return ok(serialize_spec(spec), status=201)


def get_spec(spec_id):
    _, role = auth()
    require_role(role, OPS_ROLES)
    spec = get_or_404(STORE.specs, spec_id)
    recompute_spec(spec, bump=False)
    return ok(serialize_spec(spec))


def list_spec_allocations(spec_id):
    from allocations import serialize_allocation
    _, role = auth()
    require_role(role, {ROLE_PLATFORM_ADMIN, ROLE_ALLOCATION_PLANNER})
    get_or_404(STORE.specs, spec_id)
    limit, offset = pagination_params()
    items = [a for a in STORE.allocations.values() if a["assortment_spec_id"] == spec_id]
    items = apply_filters(items, [
        ("status", request.args.get("status")),
        ("priority_tier", request.args.get("priority_tier")),
    ])
    items.sort(key=lambda a: (a["created_at"], a["request_seq"]))
    page, meta = paginate(items, limit, offset)
    return ok([serialize_allocation(a) for a in page], response_type="array", pagination=meta)


def register(app):
    app.add_url_rule("/crayon-works/assortment-specs", view_func=create_spec, methods=["POST"])
    app.add_url_rule("/crayon-works/assortment-specs/<spec_id>", view_func=get_spec, methods=["GET"])
    app.add_url_rule("/crayon-works/assortment-specs/<spec_id>/retail-allocations",
                     view_func=list_spec_allocations, methods=["GET"])
