"""PublicComment routes."""

from datetime import date

from flask import Blueprint, request

from db import store
from errors import (
    ERR_COMMENT_NOT_FOUND, ERR_COMMENT_WINDOW_CLOSED, ERR_INVALID_STATE,
    ERR_PLAN_NOT_OPEN_FOR_COMMENT, raise_error,
)
from helpers import (
    body, get_str, paginate, parse_pagination, require_fields, stamp_new, touch,
)
from middleware import require_roles
from response import success_list, success_object
from routes_plans import ALL_ROLES, get_plan_or_404
from serializers import comment_view

bp = Blueprint("comments", __name__)


def get_comment_or_404(comment_id: str, plan_id: str = None) -> dict:
    c = store.comments.get(comment_id)
    if c is None or (plan_id is not None and c["plan_id"] != plan_id):
        raise_error(ERR_COMMENT_NOT_FOUND, f"Comment {comment_id} not found")
    return c


@bp.route("/plans/<planId>/comments", methods=["POST"])
@require_roles("PublicCommenter", "UtilityPlanner")
def create_comment(user_id, role, planId):
    plan = get_plan_or_404(planId)
    payload = body()
    require_fields(payload, "commenter_name", "commenter_email", "body")
    commenter_name = get_str(payload, "commenter_name")
    commenter_email = get_str(payload, "commenter_email")
    comment_body = get_str(payload, "body")
    # State gate (priority 5).
    if plan["status"] != "OPEN_FOR_COMMENT":
        raise_error(ERR_PLAN_NOT_OPEN_FOR_COMMENT,
                    "Plan is not OPEN_FOR_COMMENT")
    # Temporal gate (priority 6): clock date within [opens, closes] inclusive.
    clock_date = store.clock.now().date()
    opens = date.fromisoformat(plan["comment_window_opens_on"])
    closes = date.fromisoformat(plan["comment_window_closes_on"])
    if clock_date < opens or clock_date > closes:
        raise_error(ERR_COMMENT_WINDOW_CLOSED,
                    "Comment filed outside the comment window")
    c = stamp_new({
        "plan_id": plan["id"],
        "commenter_name": commenter_name,
        "commenter_email": commenter_email,
        "body": comment_body,
        "status": "RECEIVED",
    })
    store.comments[c["id"]] = c
    return success_object(comment_view(c), 201)


@bp.route("/plans/<planId>/comments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_plan_comments(user_id, role, planId):
    plan = get_plan_or_404(planId)
    limit, offset = parse_pagination()
    items = [c for c in store.comments.values() if c["plan_id"] == plan["id"]]
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    page, total = paginate(items, limit, offset)
    return success_list([comment_view(c) for c in page], limit, offset, total)


@bp.route("/plans/<planId>/comments/<commentId>/acknowledge", methods=["POST"])
@require_roles("UtilityPlanner")
def acknowledge_comment(user_id, role, planId, commentId):
    plan = get_plan_or_404(planId)
    c = get_comment_or_404(commentId, plan_id=planId)
    if plan["status"] != "OPEN_FOR_COMMENT":
        raise_error(ERR_PLAN_NOT_OPEN_FOR_COMMENT,
                    "Plan is not OPEN_FOR_COMMENT")
    if c["status"] != "RECEIVED":
        raise_error(ERR_INVALID_STATE,
                    "Only a RECEIVED comment can be acknowledged")
    c["status"] = "ACKNOWLEDGED"
    touch(c)
    return success_object(comment_view(c), 200)


@bp.route("/comments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_comments_flat(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.comments.values())
    if "plan_id" in request.args:
        items = [c for c in items if c["plan_id"] == request.args["plan_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([comment_view(c) for c in page], limit, offset, total)


@bp.route("/comments/<commentId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_comment_flat(user_id, role, commentId):
    c = get_comment_or_404(commentId)
    return success_object(comment_view(c), 200)
