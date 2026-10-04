from flask import Blueprint, request

from db import db, new_id
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, touch, require_fields, check_str, check_array,
    resolve, list_paginated, finalize_batch_terminal, parse_datetime_value,
)
from errors import ApiError, err_invalid_request

bp = Blueprint("service_tickets", __name__)


def serialize(t):
    return {
        "id": t["id"],
        "restaurant_id": t["restaurant_id"],
        "table_ref": t["table_ref"],
        "items": t["items"],
        "allergen_review_status": t["allergen_review_status"],
        "fire_status": t["fire_status"],
        "recall_count": t["recall_count"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def latest_published_revision(restaurant_id):
    published = [
        r for r in db.menu_revisions.values()
        if r["restaurant_id"] == restaurant_id and r["status"] == "PUBLISHED"
    ]
    if not published:
        return None
    published.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    return published[-1]


@bp.route("/api/service-tickets", methods=["POST"])
def create_ticket():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["restaurant_id", "table_ref", "items"])
    rid = check_str(body, "restaurant_id")
    table_ref = check_str(body, "table_ref")
    raw_items = check_array(body, "items")
    items = []
    for it in raw_items:
        if not isinstance(it, dict):
            raise err_invalid_request("items entries must be objects")
        rid2 = it.get("recipe_id")
        if not isinstance(rid2, str):
            raise err_invalid_request("items.recipe_id must be a string")
        mods = it.get("modifications")
        flags = it.get("allergen_flags")
        if mods is None:
            mods = []
        if flags is None:
            flags = []
        if not isinstance(mods, list) or not isinstance(flags, list):
            raise err_invalid_request("modifications and allergen_flags must be arrays")
        items.append({"recipe_id": rid2, "modifications": mods, "allergen_flags": flags})
    require_roles("LineCook")
    resolve("restaurant", rid)
    for it in items:
        resolve("recipe", it["recipe_id"])
    # State gate: recipes must belong to the restaurant's latest PUBLISHED revision
    latest = latest_published_revision(rid)
    for it in items:
        recipe = db.recipes[it["recipe_id"]]
        if latest is None or recipe["menu_revision_id"] != latest["id"]:
            raise ApiError("ERR_RECIPE_NOT_ON_PUBLISHED_MENU", 409, "Recipe is not on the restaurant's latest PUBLISHED revision")
    # Business safety: modification policy
    for it in items:
        recipe = db.recipes[it["recipe_id"]]
        if recipe["modification_policy"] == "FORBIDDEN" and len(it["modifications"]) > 0:
            raise ApiError("ERR_TICKET_MODIFICATION_FORBIDDEN", 422, "Modifications are forbidden for this recipe")
    # Allergen review initialization
    allergen_status = "NOT_REQUIRED"
    for it in items:
        recipe = db.recipes[it["recipe_id"]]
        if set(it["allergen_flags"]) & set(recipe["allergen_tags"]):
            allergen_status = "PENDING"
            break
    ent = {
        "id": new_id(),
        "restaurant_id": rid,
        "table_ref": table_ref,
        "items": items,
        "allergen_review_status": allergen_status,
        "fire_status": "OPEN",
        "recall_count": 0,
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.service_tickets[ent["id"]] = ent
    return success_object(serialize(ent), status=201)


@bp.route("/api/service-tickets", methods=["GET"])
def list_tickets():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.service_tickets,
        [
            ("restaurant_id", "restaurant_id"),
            ("fire_status", "fire_status"),
            ("allergen_review_status", "allergen_review_status"),
        ],
        request.args,
    )
    return success_array([serialize(t) for t in page], limit, offset, total)


@bp.route("/api/service-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    require_roles(*ALL_ROLES)
    t = resolve("service_ticket", tid)
    return success_object(serialize(t))


@bp.route("/api/service-tickets/<tid>/fire", methods=["POST"])
def fire(tid):
    get_user_context()
    get_json_body()
    require_roles("LineCook")
    t = resolve("service_ticket", tid)
    if t["fire_status"] != "OPEN":
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "fire requires OPEN ticket")
    if t["allergen_review_status"] == "PENDING":
        raise ApiError("ERR_ALLERGEN_REVIEW_REQUIRED", 422, "Allergen review must be cleared before firing")
    t["fire_status"] = "FIRED"
    touch(t)
    return success_object(serialize(t))


@bp.route("/api/service-tickets/<tid>/mark-ready", methods=["POST"])
def mark_ready(tid):
    get_user_context()
    get_json_body()
    require_roles("LineCook")
    t = resolve("service_ticket", tid)
    if t["fire_status"] != "FIRED":
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "mark-ready requires FIRED ticket")
    # Station draw-down per ticket item's recipe components
    for it in t["items"]:
        recipe = db.recipes[it["recipe_id"]]
        for comp in recipe.get("components", []):
            needed = comp["quantity_per_portion"]
            candidates = []
            for st in db.stations.values():
                if st["restaurant_id"] == t["restaurant_id"] and st["station_type"] == recipe["station_type"]:
                    for b in db.prep_batches.values():
                        if (
                            b["station_id"] == st["id"]
                            and b["prep_item_id"] == comp["prep_item_id"]
                            and b["status"] == "PREPPED"
                        ):
                            candidates.append(b)
            candidates.sort(key=lambda b: (b["expires_at"] or "", b["created_at"]))
            for b in candidates:
                if needed <= 0:
                    break
                remaining = b["quantity"] - b["consumed_quantity"] - b["wasted_quantity"]
                take = min(needed, remaining)
                if take > 0:
                    b["consumed_quantity"] += take
                    needed -= take
                    touch(b)
                    if b["consumed_quantity"] + b["wasted_quantity"] >= b["quantity"]:
                        finalize_batch_terminal(b, "DEPLETED")
                    else:
                        from services.common import recompute_par_health
                        recompute_par_health(b["station_id"])
    t["fire_status"] = "READY"
    touch(t)
    return success_object(serialize(t))


@bp.route("/api/service-tickets/<tid>/serve", methods=["POST"])
def serve(tid):
    get_user_context()
    get_json_body()
    require_roles("LineCook")
    t = resolve("service_ticket", tid)
    if t["fire_status"] != "READY":
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "serve requires READY ticket")
    t["fire_status"] = "SERVED"
    touch(t)
    return success_object(serialize(t))


@bp.route("/api/service-tickets/<tid>/void", methods=["POST"])
def void(tid):
    get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    t = resolve("service_ticket", tid)
    if t["fire_status"] not in ("OPEN", "FIRED", "READY"):
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "void requires OPEN, FIRED, or READY ticket")
    t["fire_status"] = "VOIDED"
    touch(t)
    return success_object(serialize(t))


@bp.route("/api/service-tickets/<tid>/recall", methods=["POST"])
def recall(tid):
    get_user_context()
    get_json_body()
    require_roles("LineCook")
    t = resolve("service_ticket", tid)
    if t["fire_status"] != "READY":
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "recall requires READY ticket")
    t["fire_status"] = "FIRED"
    t["recall_count"] += 1
    touch(t)
    return success_object(serialize(t))


@bp.route("/api/service-tickets/<tid>/clear-allergen-review", methods=["POST"])
def clear_allergen_review(tid):
    get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    t = resolve("service_ticket", tid)
    if t["allergen_review_status"] != "PENDING":
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "clear-allergen-review requires PENDING allergen review")
    t["allergen_review_status"] = "CLEARED"
    touch(t)
    return success_object(serialize(t))
