"""FulfillmentPlan creation (OCC + supersede cascade), reads, and
PlanLineItem reservation."""

from flask import Blueprint, request, g

from auth import require_roles
from cascade import plans_of_wish, lines_of_plan, supersede_open_plans
from db import STORE, now, new_entity, touch
from errors import ApiError
from resp import ok, created, list_resp
from serialize import ser_plan, ser_line
from util import (
    body_json, req_str, req_int, opt_str, pagination, paginate, bad,
)

bp = Blueprint("plans", __name__)

CATEGORY_BY_WISH_TYPE = {
    "TRAVEL": {"AIRLINE", "RESORT"},
    "RECEIVE_ITEM": {"RETAILER"},
    "MEET_PERSON": {"SPONSOR"},
    "BE_SOMETHING": {"SPONSOR", "RETAILER"},
}


@bp.post("/wish-grant/fulfillment-plans")
@require_roles("WishCoordinator", "ChapterDirector")
def create_plan():
    body = body_json()
    wish_id = req_str(body, "wish_id")
    cash = req_int(body, "cash_cost_cents")
    if cash < 0:
        bad("cash_cost_cents must be >= 0")
    expected = req_int(body, "expected_wish_version")
    notes = opt_str(body, "notes")

    wish = STORE["wishes"].get(wish_id)
    if wish is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Wish not found")
    if wish["status"] not in ("DETERMINED", "PLANNING"):
        raise ApiError(
            "ERR_INVALID_WISH_STATE", 409,
            "Wish %s does not accept plan creation" % wish["status"],
        )
    if expected != wish["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_wish_version does not match the wish version",
        )
    for p in plans_of_wish(wish["id"]):
        if p["status"] == "APPROVED":
            raise ApiError(
                "ERR_PLAN_ALREADY_APPROVED", 409,
                "The wish already has an APPROVED plan",
            )

    supersede_open_plans(wish["id"])

    plan = new_entity(
        wish_id=wish["id"],
        cash_cost_cents=cash,
        notes=notes,
        status="DRAFT",
        created_by_user_id=g.user_id,
        approved_by_user_id=None,
        escalation_required=False,
    )
    STORE["plans"][plan["id"]] = plan
    wish["status"] = "PLANNING"
    touch(wish)
    return created(ser_plan(plan))


@bp.get("/wish-grant/wishes/<wid>/fulfillment-plans")
@require_roles("WishCoordinator", "ChapterDirector", "NationalDirector")
def list_wish_plans(wid):
    wish = STORE["wishes"].get(wid)
    if wish is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Wish not found")
    limit, offset = pagination()
    items = sorted(STORE["plans"].values(), key=lambda e: e["created_at"])
    items = [p for p in items if p["wish_id"] == wid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total, has_more = paginate(items, limit, offset)
    return list_resp([ser_plan(p) for p in page], total, limit, offset, has_more)


@bp.get("/wish-grant/fulfillment-plans/<pid>")
@require_roles("WishCoordinator", "ChapterDirector", "NationalDirector")
def get_plan(pid):
    p = STORE["plans"].get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "FulfillmentPlan not found")
    return ok(ser_plan(p))


@bp.post("/wish-grant/fulfillment-plans/<pid>/line-items")
@require_roles("WishCoordinator", "ChapterDirector")
def add_line_item(pid):
    plan = STORE["plans"].get(pid)
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", 404, "FulfillmentPlan not found")
    body = body_json()
    offer_id = req_str(body, "donation_offer_id")
    quantity = req_int(body, "quantity")
    if quantity < 1:
        bad("quantity must be >= 1")
    offer = STORE["offers"].get(offer_id)
    if offer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "DonationOffer not found")

    if plan["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_PLAN_STATE", 409,
            "Line items can only be added to a DRAFT plan",
        )
    if offer["status"] != "AVAILABLE":
        raise ApiError(
            "ERR_INVALID_OFFER_STATE", 409,
            "Donation offer is not AVAILABLE",
        )
    if now().date() > offer["valid_until"]:
        raise ApiError(
            "ERR_DONATION_EXPIRED", 409,
            "Offer valid_until is in the past",
        )
    wish = STORE["wishes"][plan["wish_id"]]
    allowed = CATEGORY_BY_WISH_TYPE.get(wish["wish_type"], set())
    if offer["category"] not in allowed:
        raise ApiError(
            "ERR_CATEGORY_WISH_TYPE_MISMATCH", 422,
            "Offer category %s cannot serve wish type %s"
            % (offer["category"], wish["wish_type"]),
        )
    available = offer["quantity_total"] - offer["quantity_reserved"]
    if quantity > available:
        raise ApiError(
            "ERR_INSUFFICIENT_DONATION_QTY", 409,
            "Requested quantity exceeds quantity_available",
        )

    line = new_entity(
        plan_id=plan["id"],
        donation_offer_id=offer["id"],
        quantity=quantity,
        line_fmv_cents=quantity * offer["fmv_unit_cents"],
        status="RESERVED",
    )
    STORE["lines"][line["id"]] = line
    offer["quantity_reserved"] += quantity
    if offer["quantity_total"] - offer["quantity_reserved"] == 0:
        offer["status"] = "FULLY_RESERVED"
    touch(offer)
    touch(plan)
    return created(ser_line(line))


@bp.get("/wish-grant/fulfillment-plans/<pid>/line-items")
@require_roles("WishCoordinator", "ChapterDirector", "NationalDirector", "InKindOfficer")
def list_plan_line_items(pid):
    plan = STORE["plans"].get(pid)
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", 404, "FulfillmentPlan not found")
    limit, offset = pagination()
    items = sorted(lines_of_plan(pid), key=lambda e: e["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    return list_resp([ser_line(l) for l in page], total, limit, offset, has_more)
