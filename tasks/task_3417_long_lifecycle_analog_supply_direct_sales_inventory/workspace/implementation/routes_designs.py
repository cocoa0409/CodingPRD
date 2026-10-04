# Reference design and design win routes (PRD 3.8).
from flask import Blueprint, request

from auth import require_roles
from envelope import list_response, success
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_PART_NOT_ORDERABLE,
    ERR_REFERENCE_DESIGN_NOT_PUBLISHED,
)
from lookups import get_customer, get_design_win, get_part, get_reference_design
from serialize import design_win_public, reference_design_public
from store import store
from validate import (
    as_datetime,
    as_int_at_least,
    as_str,
    check_unknown_fields,
    get_body,
    require_fields,
)

bp = Blueprint("designs", __name__)

_RD_CREATE_ALLOWED = {"title", "featured_part_number"}
_WIN_CREATE_ALLOWED = {
    "reference_design_id",
    "customer_id",
    "part_id",
    "expected_lifetime_revenue_cents",
    "annual_volume_units",
    "start_date",
}


@bp.post("/reference-designs")
def create_reference_design():
    require_roles("FieldEngineer")
    body = get_body(required=True)
    require_fields(body, ["title", "featured_part_number"])
    check_unknown_fields(body, _RD_CREATE_ALLOWED)
    title = as_str(body["title"], "title")
    featured_part_number = as_str(body["featured_part_number"], "featured_part_number")
    design = {
        "title": title,
        "featured_part_number": featured_part_number,
        "status": "DRAFT",
        "published_at": None,
    }
    design.update(store.stamp())
    store.reference_designs[design["id"]] = design
    return success(reference_design_public(design), 201)


@bp.post("/reference-designs/<design_id>/publish")
def publish_reference_design(design_id):
    require_roles("FieldEngineer")
    design = get_reference_design(design_id)
    body = get_body(required=False)
    check_unknown_fields(body, set())
    if design["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT reference design can be published")
    # Row 9: the featured part must exist and be in ACTIVE or NRND lifecycle.
    featured = None
    for part in store.parts.values():
        if part["part_number"] == design["featured_part_number"]:
            featured = part
            break
    if featured is None or featured["lifecycle_status"] not in ("ACTIVE", "NRND"):
        raise ApiError(ERR_PART_NOT_ORDERABLE, 422, "The featured part is not in ACTIVE or NRND lifecycle")
    design["status"] = "PUBLISHED"
    design["published_at"] = store.now()
    store.touch(design)
    return success(reference_design_public(design))


@bp.post("/design-wins")
def create_design_win():
    require_roles("FieldEngineer")
    body = get_body(required=True)
    # Row 3 existence in the global type order: part, customer, reference design.
    if "part_id" in body and body["part_id"] is not None:
        part = get_part(body["part_id"])
    if "customer_id" in body and body["customer_id"] is not None:
        customer = get_customer(body["customer_id"])
    if "reference_design_id" in body and body["reference_design_id"] is not None:
        design = get_reference_design(body["reference_design_id"])
    # Row 4 schema.
    require_fields(body, [
        "reference_design_id", "customer_id", "part_id",
        "expected_lifetime_revenue_cents", "annual_volume_units", "start_date",
    ])
    check_unknown_fields(body, _WIN_CREATE_ALLOWED)
    as_str(body["reference_design_id"], "reference_design_id")
    as_str(body["customer_id"], "customer_id")
    as_str(body["part_id"], "part_id")
    expected_revenue = as_int_at_least(body["expected_lifetime_revenue_cents"], "expected_lifetime_revenue_cents", 0)
    annual_volume = as_int_at_least(body["annual_volume_units"], "annual_volume_units", 0)
    start_date = as_datetime(body["start_date"], "start_date")
    win = {
        "reference_design_id": design["id"],
        "customer_id": customer["id"],
        "part_id": part["id"],
        "expected_lifetime_revenue_cents": expected_revenue,
        "annual_volume_units": annual_volume,
        "start_date": start_date,
        "status": "REGISTERED",
    }
    win.update(store.stamp())
    store.design_wins[win["id"]] = win
    return success(design_win_public(win), 201)


@bp.get("/design-wins")
def list_design_wins():
    require_roles("PlatformAdmin", "FieldEngineer", "ChannelManager", "SupplyPlanner")
    wins = list(store.design_wins.values())
    rd_filter = request.args.get("reference_design_id")
    customer_filter = request.args.get("customer_id")
    part_filter = request.args.get("part_id")
    status_filter = request.args.get("status")
    if rd_filter is not None:
        wins = [w for w in wins if w["reference_design_id"] == rd_filter]
    if customer_filter is not None:
        wins = [w for w in wins if w["customer_id"] == customer_filter]
    if part_filter is not None:
        wins = [w for w in wins if w["part_id"] == part_filter]
    if status_filter is not None:
        wins = [w for w in wins if w["status"] == status_filter]
    wins.sort(key=lambda w: w["seq"])
    return list_response(wins, design_win_public)


@bp.get("/design-wins/<win_id>")
def fetch_design_win(win_id):
    require_roles("PlatformAdmin", "FieldEngineer", "ChannelManager", "SupplyPlanner")
    return success(design_win_public(get_design_win(win_id)))


@bp.post("/design-wins/<win_id>/activate")
def activate_design_win(win_id):
    require_roles("FieldEngineer")
    win = get_design_win(win_id)
    body = get_body(required=False)
    check_unknown_fields(body, set())
    if win["status"] != "REGISTERED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a REGISTERED design win can be activated")
    part = store.parts.get(win["part_id"])
    design = store.reference_designs.get(win["reference_design_id"])
    # Row 9 in written order: part orderable, then reference design published.
    if part is None or part["lifecycle_status"] not in ("ACTIVE", "NRND"):
        raise ApiError(ERR_PART_NOT_ORDERABLE, 422, "The designed-in part is not in ACTIVE or NRND lifecycle")
    if design is None or design["status"] != "PUBLISHED":
        raise ApiError(ERR_REFERENCE_DESIGN_NOT_PUBLISHED, 422, "The reference design is not PUBLISHED")
    win["status"] = "ACTIVE"
    store.touch(win)
    return success(design_win_public(win))
