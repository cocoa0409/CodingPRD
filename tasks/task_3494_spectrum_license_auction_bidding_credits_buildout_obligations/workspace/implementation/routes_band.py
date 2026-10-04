"""Band planning: band plans, license areas, license blocks (PRD §3.1)."""
from flask import Blueprint

import store
import calcs
import serializers
from errors import ApiError, success
from helpers import (auth, require_role, body, req_present, as_str, as_int,
                     as_number, as_enum, get_or_404, paginate, touch)

bp = Blueprint("band", __name__)

ANY_ROLE = ("AuctionAdmin", "Bidder", "IncumbentOperator", "TransferReviewer")
BLOCK_CATEGORIES = ("CATEGORY_A", "CATEGORY_B", "CATEGORY_C", "CATEGORY_D")


@bp.route("/spectrum-auctions/band-plans", methods=["POST"])
def create_band_plan():
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    b = body()
    band_name = as_str(req_present(b, "band_name"), "band_name")
    start = as_number(req_present(b, "frequency_start_mhz"), "frequency_start_mhz")
    end = as_number(req_present(b, "frequency_end_mhz"), "frequency_end_mhz")
    if not start < end:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "frequency_start_mhz must be < frequency_end_mhz")
    technical_rules = b.get("technical_rules", "")
    if not isinstance(technical_rules, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "technical_rules must be a string")
    plan = store.stamp_new({
        "id": store.new_id(),
        "band_name": band_name,
        "frequency_start_mhz": start,
        "frequency_end_mhz": end,
        "technical_rules": technical_rules,
        "status": "DRAFT",
    })
    store.DB["band_plans"][plan["id"]] = plan
    return success(serializers.band_plan(plan), 201)


@bp.route("/spectrum-auctions/band-plans/<pid>", methods=["GET"])
def get_band_plan(pid):
    auth()
    plan = get_or_404("band_plans", pid)
    return success(serializers.band_plan(plan), 200)


@bp.route("/spectrum-auctions/band-plans/<pid>/publish", methods=["POST"])
def publish_band_plan(pid):
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    plan = get_or_404("band_plans", pid)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_BAND_PLAN_NOT_DRAFT", 409,
                       "Band plan is not in DRAFT")
    if not calcs.areas_of_plan(pid) or not calcs.blocks_of_plan(pid):
        raise ApiError("ERR_BAND_PLAN_INCOMPLETE", 422,
                       "Publish requires at least one license area and one "
                       "license block")
    plan["status"] = "PUBLISHED"
    touch(plan)
    return success(serializers.band_plan(plan), 200)


@bp.route("/spectrum-auctions/license-areas", methods=["POST"])
def create_license_area():
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    b = body()
    plan_id = as_str(req_present(b, "band_plan_id"), "band_plan_id")
    area_code = as_str(req_present(b, "area_code"), "area_code")
    name = as_str(req_present(b, "name"), "name")
    population = as_int(req_present(b, "population"), "population", minimum=1)
    plan = get_or_404("band_plans", plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_BAND_PLAN_NOT_DRAFT", 409,
                       "Band plan is not in DRAFT")
    if calcs.find_area_by_code(plan_id, area_code) is not None:
        raise ApiError("ERR_DUPLICATE_AREA_CODE", 409,
                       "area_code already exists within this band plan")
    area = store.stamp_new({
        "id": store.new_id(),
        "band_plan_id": plan_id,
        "area_code": area_code,
        "name": name,
        "population": population,
    })
    store.DB["areas"][area["id"]] = area
    return success(serializers.license_area(area), 201)


@bp.route("/spectrum-auctions/band-plans/<pid>/license-areas", methods=["GET"])
def list_license_areas(pid):
    auth()
    get_or_404("band_plans", pid)
    page, meta = paginate(calcs.areas_of_plan(pid))
    return success([serializers.license_area(a) for a in page], 200, meta)


@bp.route("/spectrum-auctions/license-blocks", methods=["POST"])
def create_license_block():
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    b = body()
    plan_id = as_str(req_present(b, "band_plan_id"), "band_plan_id")
    category = as_enum(req_present(b, "category"), "category", BLOCK_CATEGORIES)
    mhz_size = as_int(req_present(b, "mhz_size"), "mhz_size", minimum=1)
    supply = as_int(req_present(b, "supply_per_area"), "supply_per_area", minimum=1)
    price = as_int(req_present(b, "price_per_mhz_pop_cents"),
                   "price_per_mhz_pop_cents", minimum=0)
    plan = get_or_404("band_plans", plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_BAND_PLAN_NOT_DRAFT", 409,
                       "Band plan is not in DRAFT")
    if calcs.find_block_by_category(plan_id, category) is not None:
        raise ApiError("ERR_DUPLICATE_BLOCK_CATEGORY", 409,
                       "category already exists within this band plan")
    block = store.stamp_new({
        "id": store.new_id(),
        "band_plan_id": plan_id,
        "category": category,
        "mhz_size": mhz_size,
        "supply_per_area": supply,
        "price_per_mhz_pop_cents": price,
    })
    store.DB["blocks"][block["id"]] = block
    return success(serializers.license_block(block), 201)


@bp.route("/spectrum-auctions/band-plans/<pid>/license-blocks", methods=["GET"])
def list_license_blocks(pid):
    auth()
    get_or_404("band_plans", pid)
    page, meta = paginate(calcs.blocks_of_plan(pid))
    return success([serializers.license_block(b) for b in page], 200, meta)
