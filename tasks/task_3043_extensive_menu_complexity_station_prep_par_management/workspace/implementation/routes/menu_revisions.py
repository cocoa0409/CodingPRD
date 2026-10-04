from flask import Blueprint, request

from db import db, new_id
from middleware import require_roles, get_user_context, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, touch, require_fields, check_str, resolve,
    list_paginated, active_recipe_item_ids, retire_prep_item,
    parse_datetime_value, format_iso,
)
from errors import ApiError

bp = Blueprint("menu_revisions", __name__)


def serialize(r):
    return {
        "id": r["id"],
        "restaurant_id": r["restaurant_id"],
        "label": r["label"],
        "effective_from": r["effective_from"],
        "review_cycle_count": r["review_cycle_count"],
        "retraining_required_count": r["retraining_required_count"],
        "recipe_card_redistribution_status": r["recipe_card_redistribution_status"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/api/menu-revisions", methods=["POST"])
def create_revision():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["restaurant_id", "label", "effective_from"])
    rid = check_str(body, "restaurant_id")
    label = check_str(body, "label")
    eff = parse_datetime_value(body.get("effective_from"), "effective_from")
    require_roles("MenuAdmin")
    resolve("restaurant", rid)
    ent = {
        "id": new_id(),
        "restaurant_id": rid,
        "label": label,
        "effective_from": format_iso(eff),
        "review_cycle_count": 0,
        "retraining_required_count": 0,
        "recipe_card_redistribution_status": "NOT_STARTED",
        "status": "DRAFT",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.menu_revisions[ent["id"]] = ent
    return success_object(serialize(ent), status=201)


@bp.route("/api/menu-revisions", methods=["GET"])
def list_revisions():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.menu_revisions,
        [("restaurant_id", "restaurant_id"), ("status", "status")],
        request.args,
    )
    return success_array([serialize(r) for r in page], limit, offset, total)


@bp.route("/api/menu-revisions/<rid>", methods=["GET"])
def get_revision(rid):
    require_roles(*ALL_ROLES)
    r = resolve("menu_revision", rid)
    return success_object(serialize(r))


@bp.route("/api/menu-revisions/<rid>/submit-review", methods=["POST"])
def submit_review(rid):
    uid, role = get_user_context()
    get_json_body()
    require_roles("MenuAdmin")
    r = resolve("menu_revision", rid)
    if r["status"] != "DRAFT":
        raise ApiError("ERR_REVISION_NOT_DRAFT", 409, "submit-review requires DRAFT")
    r["status"] = "IN_REVIEW"
    touch(r)
    return success_object(serialize(r))


@bp.route("/api/menu-revisions/<rid>/request-changes", methods=["POST"])
def request_changes(rid):
    get_user_context()
    get_json_body()
    require_roles("MenuAdmin")
    r = resolve("menu_revision", rid)
    if r["status"] != "IN_REVIEW":
        raise ApiError("ERR_REVISION_NOT_IN_REVIEW", 409, "request-changes requires IN_REVIEW")
    r["status"] = "DRAFT"
    r["review_cycle_count"] += 1
    touch(r)
    return success_object(serialize(r))


@bp.route("/api/menu-revisions/<rid>/approve", methods=["POST"])
def approve(rid):
    get_user_context()
    get_json_body()
    require_roles("MenuAdmin")
    r = resolve("menu_revision", rid)
    if r["status"] != "IN_REVIEW":
        raise ApiError("ERR_REVISION_NOT_IN_REVIEW", 409, "approve requires IN_REVIEW")
    r["status"] = "APPROVED"
    touch(r)
    return success_object(serialize(r))


@bp.route("/api/menu-revisions/<rid>/publish", methods=["POST"])
def publish(rid):
    get_user_context()
    get_json_body()
    require_roles("MenuAdmin")
    r = resolve("menu_revision", rid)
    if r["status"] != "APPROVED":
        raise ApiError("ERR_REVISION_NOT_APPROVED", 409, "publish requires APPROVED")

    # Supersede prior PUBLISHED revision of this restaurant + its ACTIVE recipes
    for other in db.menu_revisions.values():
        if (
            other["restaurant_id"] == r["restaurant_id"]
            and other["status"] == "PUBLISHED"
            and other["id"] != r["id"]
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
            for rec in db.recipes.values():
                if rec["menu_revision_id"] == other["id"] and rec["status"] == "ACTIVE":
                    rec["status"] = "SUPERSEDED"
                    touch(rec)

    r["status"] = "PUBLISHED"
    touch(r)

    # This revision's DRAFT recipes -> ACTIVE
    for rec in db.recipes.values():
        if rec["menu_revision_id"] == r["id"] and rec["status"] == "DRAFT":
            rec["status"] = "ACTIVE"
            touch(rec)

    # Retire unreferenced prep items (cascade suspends pars + cancels batches)
    referenced = active_recipe_item_ids(r["restaurant_id"])
    for item in list(db.prep_items.values()):
        if item["status"] == "ACTIVE" and item["id"] not in referenced:
            retire_prep_item(item)

    # Flag cooks whose certification doesn't match this revision
    count = 0
    for cook in db.cooks.values():
        if cook["restaurant_id"] == r["restaurant_id"] and cook["status"] != "INACTIVE":
            if cook["certification_menu_revision_id"] != r["id"]:
                if cook["status"] != "RETRAINING_REQUIRED":
                    cook["status"] = "RETRAINING_REQUIRED"
                    touch(cook)
    for cook in db.cooks.values():
        if cook["restaurant_id"] == r["restaurant_id"]:
            if cook["certification_menu_revision_id"] != r["id"]:
                count += 1
    r["retraining_required_count"] = count
    r["recipe_card_redistribution_status"] = "COMPLETE"
    touch(r)
    return success_object(serialize(r))
