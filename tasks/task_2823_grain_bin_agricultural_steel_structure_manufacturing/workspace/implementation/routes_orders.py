"""Dealer orders: the kit bill of materials, the price build-up, the three
parallel state dimensions and crew assignment."""
from flask import Blueprint, request

import calc
import serializers
import services
import store
from authz import ALL_ROLES, authorize
from common import D
from envelope import created, ok, paginated
from errors import ApiError
from routes_parties import find_crew, find_dealer
from shape import body, req_enum, req_int, req_str
from store import insert, touch

bp = Blueprint("orders", __name__)

SEASONS = ("PRESEASON", "HARVEST_PEAK", "OFFSEASON")
AERATION_PACKAGES = ("NONE", "AERATION", "DRYING_FULL")
UNLOAD_SYSTEMS = ("GRAVITY", "SWEEP_AUGER", "POWER_SWEEP")


def find_order(row_id):
    row = store.dealer_orders.get(row_id)
    if row is None:
        raise ApiError("ERR_DEALER_ORDER_NOT_FOUND")
    return row


def acting_dealer(user_id):
    """Ladder step 6 for the DealerPrincipal identity."""
    row = store.dealers.get(user_id)
    if row is None:
        raise ApiError("ERR_DEALER_SCOPE_VIOLATION")
    return row


def own_order(order, user_id):
    dealer = acting_dealer(user_id)
    if order["dealer_id"] != user_id:
        raise ApiError("ERR_DEALER_SCOPE_VIOLATION")
    return dealer


@bp.post("/dealer-orders")
def place_order():
    user_id, _ = authorize(("DealerPrincipal",))
    payload = body()
    dealer_id = req_str(payload, "dealer_id")
    bin_design_id = req_str(payload, "bin_design_id")
    order_season = req_enum(payload, "order_season", SEASONS)
    aeration_package = req_enum(payload, "aeration_package", AERATION_PACKAGES)
    unload_system = req_enum(payload, "unload_system", UNLOAD_SYSTEMS)

    dealer = find_dealer(dealer_id)
    design = store.bin_designs.get(bin_design_id)
    if design is None:
        raise ApiError("ERR_BIN_DESIGN_NOT_FOUND")

    acting_dealer(user_id)
    if dealer_id != user_id:
        raise ApiError("ERR_DEALER_SCOPE_VIOLATION")

    if design["status"] == "RECALLED":
        raise ApiError("ERR_DESIGN_RECALLED")

    grain_profile = store.grain_profiles[design["grain_profile_id"]]
    coating = store.coating_specs[design["coating_spec_id"]]

    sizing = calc.aeration_sizing(
        design["capacity_m3"],
        design["eave_height_m"],
        design["moisture_pct"],
        grain_profile["bulk_density_kg_per_m3"],
        grain_profile["max_safe_moisture_pct"],
        grain_profile["aeration_cfm_per_m3_base"],
        grain_profile["drying_multiplier"],
        aeration_package,
        unload_system,
    )
    if aeration_package != "NONE" and sizing["raw_cfm"] > calc.MAX_FAN_CFM:
        raise ApiError("ERR_AERATION_UNDERSIZED")

    if order_season != calc.derived_season(store.clock_now()):
        raise ApiError("ERR_SEASON_WINDOW_MISMATCH")

    quantities = calc.kit_quantities(
        design, aeration_package, unload_system, sizing["required_fan_cfm"]
    )
    lines, kit_subtotal_cents, kit_weight_kg, kit_cube_m3 = calc.kit_lines_for(
        design, quantities, coating["coating_cost_per_kg_cents"]
    )
    pricing = calc.price_order(kit_subtotal_cents, order_season, dealer["program_tier"])

    order = {
        "dealer_id": dealer_id,
        "bin_design_id": bin_design_id,
        "freight_load_id": None,
        "installation_crew_id": None,
        "order_season": order_season,
        "aeration_package": aeration_package,
        "unload_system": unload_system,
        "kit_subtotal_cents": kit_subtotal_cents,
        "season_uplift_cents": pricing["season_uplift_cents"],
        "program_discount_cents": pricing["program_discount_cents"],
        "net_subtotal_cents": pricing["net_subtotal_cents"],
        "freight_surcharge_pct": pricing["freight_surcharge_pct"],
        "freight_surcharge_cents": pricing["freight_surcharge_cents"],
        "total_cents": pricing["total_cents"],
        "required_deposit_cents": pricing["required_deposit_cents"],
        "credit_hold_cents": pricing["credit_hold_cents"],
        "deposit_paid_cents": 0,
        "kit_weight_kg": kit_weight_kg,
        "kit_cube_m3": kit_cube_m3,
        "grain_mass_kg": sizing["grain_mass_kg"],
        "required_fan_cfm": sizing["required_fan_cfm"],
        "drying_hours_estimate": sizing["drying_hours_estimate"],
        "unload_rate_bph": sizing["unload_rate_bph"],
        "allocated_freight_cents": 0,
        "freight_sequence": None,
        "production_status": "DRAFT",
        "financial_status": "AWAITING_DEPOSIT",
        "installation_readiness": "UNASSIGNED",
    }
    insert(store.dealer_orders, order)
    for line in lines:
        line["dealer_order_id"] = order["id"]
        insert(store.kit_lines, line, versioned=False)
    return created(serializers.dealer_order(order))


@bp.get("/dealer-orders")
def list_orders():
    authorize(ALL_ROLES)
    rows = store.ordered(store.dealer_orders)
    for field in ("dealer_id", "bin_design_id", "freight_load_id", "installation_crew_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row[field] == value]
    return paginated(rows, serializers.dealer_order)


@bp.get("/dealer-orders/<row_id>")
def read_order(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.dealer_order(find_order(row_id)))


@bp.get("/dealer-orders/<row_id>/kit-lines")
def list_kit_lines(row_id):
    authorize(ALL_ROLES)
    order = find_order(row_id)
    rows = store.kit_lines_of_order(order["id"])
    rows = sorted(rows, key=lambda row: calc.COMPONENT_ORDER.index(row["component_code"]))
    return paginated(rows, serializers.kit_line)


@bp.post("/dealer-orders/<row_id>/confirm")
def confirm_order(row_id):
    user_id, _ = authorize(("DealerPrincipal",))
    order = find_order(row_id)
    dealer = own_order(order, user_id)

    if order["production_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_STATE_INVALID")

    design = store.bin_designs[order["bin_design_id"]]
    if design["seal_required"]:
        if design["status"] != "SEALED":
            raise ApiError("ERR_DESIGN_NOT_SEALED")
    elif design["status"] not in ("UNDER_REVIEW", "SEALED"):
        raise ApiError("ERR_DESIGN_NOT_SEALED")

    if design["seal_required"]:
        permit_ready_at = design["permit_ready_at"]
        if permit_ready_at is None or store.clock_now() < permit_ready_at:
            raise ApiError("ERR_PERMIT_REVIEW_PENDING")

    if dealer["credit_available_cents"] < order["credit_hold_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")

    order["production_status"] = "QUEUED"
    touch(order)
    services.recompute_dealer_ledger(dealer)
    return ok(serializers.dealer_order(order))


@bp.post("/dealer-orders/<row_id>/payments")
def pay_deposit(row_id):
    user_id, _ = authorize(("DealerPrincipal",))
    payload = body()
    amount_cents = req_int(payload, "amount_cents")

    order = find_order(row_id)
    own_order(order, user_id)

    if order["financial_status"] != "AWAITING_DEPOSIT":
        raise ApiError("ERR_DEPOSIT_ALREADY_PAID")
    if order["production_status"] == "CANCELLED":
        raise ApiError("ERR_ORDER_STATE_INVALID")
    if amount_cents != order["required_deposit_cents"]:
        raise ApiError("ERR_DEPOSIT_AMOUNT_MISMATCH")

    order["deposit_paid_cents"] = amount_cents
    order["financial_status"] = "DEPOSIT_PAID"
    touch(order)
    return ok(serializers.dealer_order(order))


@bp.post("/dealer-orders/<row_id>/cancel")
def cancel_order(row_id):
    user_id, _ = authorize(("DealerPrincipal",))
    order = find_order(row_id)
    dealer = own_order(order, user_id)

    if order["production_status"] not in (
        "DRAFT",
        "QUEUED",
        "KITTED",
        "HOLD_CREDIT",
        "HOLD_ENGINEERING",
    ):
        raise ApiError("ERR_ORDER_STATE_INVALID")

    order["production_status"] = "CANCELLED"
    order["financial_status"] = "VOIDED"
    order["credit_hold_cents"] = 0
    touch(order)
    services.detach_order(order)
    services.recompute_dealer_ledger(dealer)
    return ok(serializers.dealer_order(order))


@bp.post("/dealer-orders/<row_id>/assign-crew")
def assign_crew(row_id):
    authorize(("PlantAdmin",))
    payload = body()
    crew_id = req_str(payload, "installation_crew_id")

    order = find_order(row_id)
    crew = find_crew(crew_id)

    if order["installation_crew_id"] is not None:
        raise ApiError("ERR_ORDER_STATE_INVALID")
    if order["production_status"] in ("CANCELLED", "SHIPPED"):
        raise ApiError("ERR_ORDER_STATE_INVALID")
    if crew["status"] != "CERTIFIED":
        raise ApiError("ERR_CREW_NOT_CERTIFIED")

    design = store.bin_designs[order["bin_design_id"]]
    if D(design["diameter_m"]) > D(crew["max_diameter_m"]):
        raise ApiError("ERR_CREW_TIER_INSUFFICIENT")
    if crew["dealer_id"] != order["dealer_id"]:
        raise ApiError("ERR_CREW_DEALER_MISMATCH")
    if store.clock_now() > crew["certified_until"]:
        raise ApiError("ERR_CREW_CERTIFICATION_EXPIRED")

    order["installation_crew_id"] = crew_id
    order["installation_readiness"] = "ASSIGNED"
    touch(order)
    return ok(serializers.dealer_order(order))
