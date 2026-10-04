"""TransitionItem endpoints: list, get, resolve."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import current_user, require_roles
from models import touch
from response import success_obj, success_list, json_body, parse_pagination, paginate
from routes_targets import get_target_or_404
from util import ALL_ROLES, TRANSITION_ITEM_ORDER

bp = Blueprint("transition_items", __name__)


def get_transition_item_or_404(item_id):
    item = db.transition_items.get(item_id)
    if item is None:
        raise ApiError("ERR_NOT_FOUND", 404, "TransitionItem not found")
    return item


@bp.route("/acquisitions/targets/<target_id>/transition-items", methods=["GET"])
def list_transition_items(target_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    get_target_or_404(target_id)
    limit, offset = parse_pagination()
    records = sorted(db.transition_items_of_target(target_id),
                     key=lambda i: (TRANSITION_ITEM_ORDER.index(i["category"])
                                    if i["category"] in TRANSITION_ITEM_ORDER
                                    else len(TRANSITION_ITEM_ORDER),
                                    i["created_at"], i["id"]))
    page, total = paginate(records, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/acquisitions/transition-items/<item_id>", methods=["GET"])
def get_transition_item(item_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    return success_obj(get_transition_item_or_404(item_id))


@bp.route("/acquisitions/transition-items/<item_id>/resolve", methods=["POST"])
def resolve_transition_item(item_id):
    _, role = current_user()
    require_roles(role, ["TransitionManager"])
    item = get_transition_item_or_404(item_id)
    target = db.targets[item["target_id"]]
    if item["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "TransitionItem is not in PENDING")
    if target["status"] != "CLOSING":
        raise ApiError("ERR_INVALID_STATE", 409, "Target is not in CLOSING")
    if item["category"] == "DEPOSITS":
        if any(a["status"] == "LEGACY"
               for a in db.customer_accounts_of_target(item["target_id"])):
            raise ApiError("ERR_ACCOUNTS_PENDING", 409,
                           "LEGACY customer accounts remain")
    body = json_body()
    note = body.get("resolution_note")
    if note is not None:
        if not isinstance(note, str):
            raise ApiError("ERR_INVALID_REQUEST", 422,
                           "resolution_note must be a string")
        item["resolution_note"] = note
    item["status"] = "DONE"
    touch(item)
    return success_obj(item)
