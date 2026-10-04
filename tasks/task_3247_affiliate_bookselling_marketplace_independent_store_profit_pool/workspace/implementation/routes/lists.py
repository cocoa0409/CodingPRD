"""BookList endpoints."""
from flask import Blueprint, request

import db
import helpers
from errors import (
    err_validation, err_invalid_state, err_reference_not_found,
    err_list_not_publishable, err_unauthorized,
)
from middleware import get_auth, require_roles, require_owner
from response import ok_object

bp = Blueprint("lists", __name__)


def list_view(l):
    return {
        "id": l["id"],
        "owner_store_id": l["owner_store_id"],
        "title": l["title"],
        "items": l["items"],
        "status": l["status"],
        "publish_count": l["publish_count"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


@bp.post("/bookshop/lists")
def create_list():
    user_id, role = require_roles(["StoreManager"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    owner_store_id = body.get("owner_store_id")
    title = body.get("title")
    items = body.get("items")

    # Ownership check (priority 3): StoreManager X-User-ID must equal owner_store_id.
    # Per PRD 2.9, body FK existence (priority 5) follows, but ownership is earlier.
    if not isinstance(owner_store_id, str) or not owner_store_id:
        raise err_validation("owner_store_id is required")
    if owner_store_id != user_id:
        from errors import err_forbidden_owner
        raise err_forbidden_owner("owner_store_id must be the acting store")

    if owner_store_id not in db.DB.stores:
        raise err_reference_not_found("owner_store_id does not resolve")

    if not isinstance(title, str) or not title:
        raise err_validation("title is required")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise err_validation("items must be an array")

    seen_positions = set()
    for it in items:
        if not isinstance(it, dict):
            raise err_validation("each item must be an object")
        bid = it.get("book_id")
        pos = it.get("position")
        note = it.get("curator_note")
        if not isinstance(bid, str) or bid not in db.DB.books:
            raise err_reference_not_found("book_id does not resolve")
        book = db.DB.books[bid]
        if book["status"] != "LISTED":
            raise err_validation("book must be LISTED")
        if not isinstance(pos, int) or isinstance(pos, bool) or pos < 1:
            raise err_validation("position must be a 1-based integer")
        if pos in seen_positions:
            raise err_validation("positions must be unique within the list")
        seen_positions.add(pos)
        if note is not None and not isinstance(note, str):
            raise err_validation("curator_note must be a string")

    l = helpers.base_resource()
    l.update({
        "owner_store_id": owner_store_id,
        "title": title,
        "items": items,
        "status": "DRAFT",
        "publish_count": 0,
    })
    db.DB.lists[l["id"]] = l
    return ok_object(list_view(l), 201)


@bp.post("/bookshop/lists/<lid>/actions")
def list_actions(lid):
    user_id, role = get_auth()
    l = helpers.get_or_404(db.DB.lists, lid)
    if role != "StoreManager":
        raise err_unauthorized()
    require_owner(l["owner_store_id"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("JSON body required")
    action = body.get("action")
    if action not in ("publish", "unpublish", "archive"):
        if action is None or not isinstance(action, str):
            raise err_validation("action is required")
        raise err_invalid_state("Unknown action: %s" % action)

    if action == "publish":
        if l["status"] != "DRAFT":
            raise err_invalid_state("list must be DRAFT to publish")
        store = db.DB.stores.get(l["owner_store_id"])
        if store is None or store["status"] != "ACTIVE":
            raise err_invalid_state("owner store must be ACTIVE to publish")
        if len(l["items"]) < 1:
            raise err_list_not_publishable()
        l["status"] = "PUBLISHED"
        l["publish_count"] += 1
        helpers.touch(l)
    elif action == "unpublish":
        if l["status"] != "PUBLISHED":
            raise err_invalid_state("list must be PUBLISHED to unpublish")
        l["status"] = "DRAFT"
        helpers.touch(l)
    elif action == "archive":
        if l["status"] not in ("DRAFT", "PUBLISHED"):
            raise err_invalid_state("list must be DRAFT or PUBLISHED to archive")
        l["status"] = "ARCHIVED"
        helpers.touch(l)
    return ok_object(list_view(l))
