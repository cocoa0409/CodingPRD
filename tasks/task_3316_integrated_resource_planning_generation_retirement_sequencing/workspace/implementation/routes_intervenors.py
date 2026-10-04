"""Intervenor and IntervenorTestimony routes."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_DUPLICATE_INTERVENOR, ERR_FORBIDDEN, ERR_INTERVENOR_NOT_FOUND,
    ERR_INTERVENOR_NO_STANDING, ERR_INVALID_STATE, ERR_PLAN_NOT_UNDER_REVIEW,
    ERR_TESTIMONY_NOT_FOUND, raise_error,
)
from helpers import (
    body, get_bool, get_str, paginate, parse_pagination, require_enum,
    require_fields, stamp_new, touch,
)
from middleware import require_roles
from response import success_list, success_object
from routes_plans import get_plan_or_404
from serializers import intervenor_view, testimony_view

bp = Blueprint("intervenors", __name__)

PARTY_TYPES = {"CONSUMER_ADVOCATE", "INDUSTRIAL_GROUP", "ENVIRONMENTAL_ORG", "MUNICIPALITY"}
INTERVENOR_READ_ROLES = ("UtilityPlanner", "Commissioner", "Intervener", "PlatformAdmin")


def get_intervenor_or_404(intervenor_id: str) -> dict:
    i = store.intervenors.get(intervenor_id)
    if i is None:
        raise_error(ERR_INTERVENOR_NOT_FOUND, f"Intervenor {intervenor_id} not found")
    return i


def get_testimony_or_404(testimony_id: str) -> dict:
    t = store.testimonies.get(testimony_id)
    if t is None:
        raise_error(ERR_TESTIMONY_NOT_FOUND, f"Testimony {testimony_id} not found")
    return t


# --- Intervenors ------------------------------------------------------------

@bp.route("/intervenors", methods=["POST"])
@require_roles("PlatformAdmin")
def create_intervenor(user_id, role):
    payload = body()
    require_fields(payload, "legal_name", "party_type")
    legal_name = get_str(payload, "legal_name")
    party_type = require_enum(payload, "party_type", PARTY_TYPES)
    standing = get_bool(payload, "standing_approved", default=True)
    for i in store.intervenors.values():
        if i["legal_name"] == legal_name:
            raise_error(ERR_DUPLICATE_INTERVENOR, "legal_name already registered")
    i = stamp_new({
        "legal_name": legal_name,
        "party_type": party_type,
        "standing_approved": standing,
    })
    store.intervenors[i["id"]] = i
    return success_object(intervenor_view(i), 201)


@bp.route("/intervenors", methods=["GET"])
@require_roles(*INTERVENOR_READ_ROLES)
def list_intervenors(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.intervenors.values())
    page, total = paginate(items, limit, offset)
    return success_list([intervenor_view(i) for i in page], limit, offset, total)


@bp.route("/intervenors/<intervenorId>", methods=["GET"])
@require_roles(*INTERVENOR_READ_ROLES)
def get_intervenor(user_id, role, intervenorId):
    i = get_intervenor_or_404(intervenorId)
    return success_object(intervenor_view(i), 200)


# --- Testimonies --------------------------------------------------------------

@bp.route("/plans/<planId>/testimonies", methods=["POST"])
@require_roles("Intervener")
def create_testimony(user_id, role, planId):
    plan = get_plan_or_404(planId)
    payload = body()
    require_fields(payload, "intervenor_id", "topic", "body")
    intervenor_id = payload["intervenor_id"]
    if not isinstance(intervenor_id, str):
        raise_error(ERR_INTERVENOR_NO_STANDING, "intervenor_id must be a string")
    topic = get_str(payload, "topic")
    testimony_body = get_str(payload, "body")
    # State gate (priority 5) before referential (priority 8).
    if plan["status"] != "UNDER_REVIEW":
        raise_error(ERR_PLAN_NOT_UNDER_REVIEW, "Plan is not UNDER_REVIEW")
    # Referential (priority 8): registered intervenor, standing, self-filing.
    intervenor = store.intervenors.get(intervenor_id)
    if (intervenor is None or not intervenor.get("standing_approved", True)
            or intervenor_id != user_id):
        raise_error(ERR_INTERVENOR_NO_STANDING,
                    "Intervenor lacks standing or is not the caller")
    # volume_no: per-(intervenor, plan) ordinal over non-withdrawn filings.
    count = sum(
        1 for t in store.testimonies.values()
        if t["plan_id"] == plan["id"] and t["intervenor_id"] == intervenor_id
        and t["status"] == "FILED"
    )
    t = stamp_new({
        "plan_id": plan["id"],
        "intervenor_id": intervenor_id,
        "topic": topic,
        "body": testimony_body,
        "volume_no": count + 1,
        "status": "FILED",
    })
    store.testimonies[t["id"]] = t
    return success_object(testimony_view(t), 201)


@bp.route("/plans/<planId>/testimonies", methods=["GET"])
@require_roles(*INTERVENOR_READ_ROLES)
def list_plan_testimonies(user_id, role, planId):
    plan = get_plan_or_404(planId)
    limit, offset = parse_pagination()
    items = [t for t in store.testimonies.values() if t["plan_id"] == plan["id"]]
    args = request.args
    if "status" in args:
        items = [t for t in items if t["status"] == args["status"]]
    if "intervenor_id" in args:
        items = [t for t in items if t["intervenor_id"] == args["intervenor_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([testimony_view(t) for t in page], limit, offset, total)


@bp.route("/testimonies/<testimonyId>", methods=["GET"])
@require_roles(*INTERVENOR_READ_ROLES)
def get_testimony(user_id, role, testimonyId):
    t = get_testimony_or_404(testimonyId)
    return success_object(testimony_view(t), 200)


@bp.route("/testimonies", methods=["GET"])
@require_roles(*INTERVENOR_READ_ROLES)
def list_testimonies_flat(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.testimonies.values())
    args = request.args
    if "plan_id" in args:
        items = [t for t in items if t["plan_id"] == args["plan_id"]]
    if "intervenor_id" in args:
        items = [t for t in items if t["intervenor_id"] == args["intervenor_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([testimony_view(t) for t in page], limit, offset, total)


def _testimony_transition(testimony_id, user_id, from_status, to_status):
    t = get_testimony_or_404(testimony_id)
    # Ownership (priority 2).
    if t["intervenor_id"] != user_id:
        raise_error(ERR_FORBIDDEN, "Testimony is owned by another intervenor")
    # State gates (priority 5).
    plan = store.plans.get(t["plan_id"])
    if plan is None or plan["status"] != "UNDER_REVIEW":
        raise_error(ERR_PLAN_NOT_UNDER_REVIEW, "Plan is not UNDER_REVIEW")
    if t["status"] != from_status:
        raise_error(ERR_INVALID_STATE, f"Testimony is not {from_status}")
    t["status"] = to_status
    touch(t)
    return t


@bp.route("/testimonies/<testimonyId>/withdraw", methods=["POST"])
@require_roles("Intervener")
def withdraw_testimony(user_id, role, testimonyId):
    t = _testimony_transition(testimonyId, user_id, "FILED", "WITHDRAWN")
    return success_object(testimony_view(t), 200)


@bp.route("/testimonies/<testimonyId>/refile", methods=["POST"])
@require_roles("Intervener")
def refile_testimony(user_id, role, testimonyId):
    # volume_no is preserved (never re-assigned).
    t = _testimony_transition(testimonyId, user_id, "WITHDRAWN", "FILED")
    return success_object(testimony_view(t), 200)
