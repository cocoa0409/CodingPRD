"""Donation product plane: products, their variant lines, liabilities and claims."""

from flask import Blueprint, request

from db import DB, iso3, new_id
from errors import ApiError
from middleware import (ALLOCATION_PLANNER, CUSTOMER_SERVICE, IMPACT_AUDITOR,
                        MARKETING_MANAGER, PRODUCT_DESIGNER, PROVISIONING_PARTNER,
                        roles)
from response import pagination_meta, success
from routes import _common as common
from services import calc, core, serial
from validation import (as_bool, as_enum, as_int, as_nonempty_str, body,
                        paginate, pagination, require)

bp = Blueprint("products", __name__)

PRODUCT_KINDS = ["ATHLETIC_SOCK", "APPAREL_TOP", "UNDERGARMENT", "SLEEP_ACCESSORY"]
DESIGN_CHANNELS = ["DONATION_ONLY", "DUAL_CHANNEL"]
OBLIGATION_MODELS = ["AT_SALE", "AT_VESTING"]
PRODUCT_STATUSES = ["DRAFT", "ACTIVE", "RETIRED", "ARCHIVED"]
LINE_STATUSES = ["DRAFT", "ACTIVE", "COMMITTED", "RETIRED", "VESTED", "SUNSET", "ARCHIVED"]

PRODUCT_DESIGNERS = [PRODUCT_DESIGNER, PROVISIONING_PARTNER]
PRODUCT_VIEWERS = [PRODUCT_DESIGNER, PROVISIONING_PARTNER, ALLOCATION_PLANNER,
                   MARKETING_MANAGER, CUSTOMER_SERVICE, IMPACT_AUDITOR]


# ===========================================================================
# Donation products
# ===========================================================================

@bp.route("/impact-program/donation-products", methods=["POST"])
@roles(*PRODUCT_DESIGNERS)
def create_product():
    payload = body()
    require(payload, "product_name", "product_kind", "design_channel",
            "obligation_model", "approved_donation_ratio_units",
            "retail_price_cents", "unit_cost_cents", "is_reusable")
    product_name = as_nonempty_str(payload, "product_name", required=True)
    product_kind = as_enum(payload, "product_kind", PRODUCT_KINDS, required=True)
    design_channel = as_enum(payload, "design_channel", DESIGN_CHANNELS, required=True)
    obligation_model = as_enum(payload, "obligation_model", OBLIGATION_MODELS, required=True)
    ratio = as_int(payload, "approved_donation_ratio_units", required=True, minimum=1)
    retail_price = as_int(payload, "retail_price_cents", required=True, minimum=0)
    unit_cost = as_int(payload, "unit_cost_cents", required=True, minimum=0)
    is_reusable = as_bool(payload, "is_reusable", required=True)

    now = iso3(DB.now())
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "product_name": product_name,
        "product_kind": product_kind,
        "design_channel": design_channel,
        "design_weight_score": 0,
        "obligation_model": obligation_model,
        "approved_donation_ratio_units": ratio,
        "retail_price_cents": retail_price,
        "unit_cost_cents": unit_cost,
        "is_reusable": is_reusable,
        "status": "DRAFT",
        "active_season_code": None,
        "obligation_units_total": 0,
        "impact_units_retail_equivalent": 0,
    }
    DB.donation_products[record["id"]] = record
    core.recompute_product(record)
    return success(serial.serialize("DonationProduct", record)), 201


@bp.route("/impact-program/donation-products", methods=["GET"])
@roles(*(PRODUCT_VIEWERS + [CUSTOMER_SERVICE]))
def list_products():
    status = request.args.get("status")
    design_channel = request.args.get("design_channel")
    product_kind = request.args.get("product_kind")
    limit, offset = pagination()
    rows = list(DB.donation_products.values())
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if design_channel:
        rows = [r for r in rows if r.get("design_channel") == design_channel]
    if product_kind:
        rows = [r for r in rows if r.get("product_kind") == product_kind]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationProduct", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/donation-products/<product_id>", methods=["GET"])
@roles(*PRODUCT_VIEWERS)
def get_product(product_id):
    record = common.product_or_404(product_id)
    core.recompute_product(record)
    return success(serial.serialize("DonationProduct", record))


@bp.route("/impact-program/donation-products/<product_id>", methods=["PUT"])
@roles(*PRODUCT_DESIGNERS)
def update_product(product_id):
    record = common.product_or_404(product_id)
    payload = body()
    require(payload, "status")
    target = as_enum(payload, "status", PRODUCT_STATUSES, required=True)
    current = record.get("status")

    if target == current:
        pass
    elif target == "RETIRED":
        if current != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        record["status"] = "RETIRED"
        # Ineligible active lines retire; eligible ones stay until the season closes.
        for variant in DB.product_lines(product_id):
            if variant.get("status") == "ACTIVE" and not variant.get("donation_eligible"):
                variant["status"] = "RETIRED"
                DB.touch(variant)
    elif target == "ACTIVE":
        if current != "RETIRED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        active_variants = [v for v in DB.product_lines(product_id) if v.get("status") == "ACTIVE"]
        for variant in active_variants:
            core.recompute_product_line(variant)
            if variant.get("design_variant_code") == "none":
                raise ApiError("ERR_INVALID_STATE_TRANSITION")
        record["status"] = "ACTIVE"
        for variant in DB.product_lines(product_id):
            if variant.get("status") == "RETIRED":
                variant["status"] = "ACTIVE"
                core.recompute_product_line(variant)
                DB.touch(variant)
    elif target == "ARCHIVED":
        if current not in ("ACTIVE", "RETIRED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        for line in DB.sales_order_lines.values():
            if line.get("donation_product_id") != product_id:
                continue
            if line.get("status") in ("OPEN", "RETURN_REQUESTED"):
                raise ApiError("ERR_INVALID_STATE_TRANSITION")
        record["status"] = "ARCHIVED"
        for variant in DB.product_lines(product_id):
            variant["status"] = "ARCHIVED"
            DB.touch(variant)
    elif target == "DRAFT":
        if current != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if "retail_price_cents" in payload:
        record["retail_price_cents"] = as_int(payload, "retail_price_cents", minimum=0)
    if "unit_cost_cents" in payload:
        record["unit_cost_cents"] = as_int(payload, "unit_cost_cents", minimum=0)
    if "approved_donation_ratio_units" in payload:
        record["approved_donation_ratio_units"] = as_int(
            payload, "approved_donation_ratio_units", minimum=1)
    for variant in DB.product_lines(product_id):
        core.recompute_product_line(variant)
    core.recompute_product(record)
    DB.touch(record)
    return success(serial.serialize("DonationProduct", record))


@bp.route("/impact-program/donation-products/<product_id>/activate", methods=["POST"])
@roles(*PRODUCT_DESIGNERS)
def activate_product(product_id):
    record = common.product_or_404(product_id)
    if record.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    core.recompute_product(record)
    if (record.get("design_weight_score") or 0) < calc.ACTIVATION_MINIMUM:
        raise ApiError("ERR_DESIGN_WEIGHT_BELOW_MINIMUM")

    record["status"] = "ACTIVE"
    for variant in DB.product_lines(product_id):
        if variant.get("status") == "DRAFT":
            variant["status"] = "ACTIVE"
            core.recompute_product_line(variant)
            DB.touch(variant)
    core.recompute_product(record)
    DB.touch(record)
    return success(serial.serialize("DonationProduct", record))


# ===========================================================================
# Donation product lines
# ===========================================================================

@bp.route("/impact-program/donation-products/<product_id>/lines", methods=["POST"])
@roles(*PRODUCT_DESIGNERS)
def create_line(product_id):
    common.product_or_404(product_id)
    payload = body()
    require(payload, "gtin", "unit_size_label", "is_essential_good", "donation_eligible")
    gtin = as_nonempty_str(payload, "gtin", required=True)
    unit_size_label = as_nonempty_str(payload, "unit_size_label", required=True)
    is_essential_good = as_bool(payload, "is_essential_good", required=True)
    donation_eligible = as_bool(payload, "donation_eligible", required=True)

    now = iso3(DB.now())
    variant = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "donation_product_id": product_id,
        "gtin": gtin,
        "unit_size_label": unit_size_label,
        "is_essential_good": is_essential_good,
        "donation_eligible": donation_eligible,
        "obligation_units": 0,
        "unit_obligation_cost_cents": 0,
        "design_variant_code": "none",
        "status": "DRAFT",
    }
    DB.donation_product_lines[variant["id"]] = variant
    core.recompute_product_line(variant)
    return success(serial.serialize("DonationProductLine", variant)), 201


@bp.route("/impact-program/donation-products/<product_id>/lines", methods=["GET"])
@roles(PRODUCT_DESIGNER, PROVISIONING_PARTNER, ALLOCATION_PLANNER, CUSTOMER_SERVICE)
def list_product_lines(product_id):
    common.product_or_404(product_id)
    status = request.args.get("status")
    eligible = request.args.get("donation_eligible")
    limit, offset = pagination()
    rows = DB.product_lines(product_id)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if eligible is not None:
        flag = eligible.strip().lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r.get("donation_eligible")) is flag]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationProductLine", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/donation-product-lines", methods=["GET"])
@roles(PRODUCT_DESIGNER, PROVISIONING_PARTNER, ALLOCATION_PLANNER, CUSTOMER_SERVICE)
def list_lines():
    product_id = request.args.get("donation_product_id")
    status = request.args.get("status")
    eligible = request.args.get("donation_eligible")
    limit, offset = pagination()
    rows = list(DB.donation_product_lines.values())
    if product_id:
        rows = [r for r in rows if r.get("donation_product_id") == product_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if eligible is not None:
        flag = eligible.strip().lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r.get("donation_eligible")) is flag]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationProductLine", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/donation-product-lines/<line_id>", methods=["GET"])
@roles(PRODUCT_DESIGNER, PROVISIONING_PARTNER, CUSTOMER_SERVICE)
def get_line(line_id):
    variant = common.product_line_or_404(line_id)
    core.recompute_product_line(variant)
    return success(serial.serialize("DonationProductLine", variant))


@bp.route("/impact-program/donation-product-lines/<line_id>", methods=["PUT"])
@roles(*PRODUCT_DESIGNERS)
def update_line(line_id):
    variant = common.product_line_or_404(line_id)
    payload = body()
    if "unit_size_label" in payload:
        variant["unit_size_label"] = as_nonempty_str(payload, "unit_size_label")
    if "is_essential_good" in payload:
        variant["is_essential_good"] = as_bool(payload, "is_essential_good")
    if "donation_eligible" in payload:
        variant["donation_eligible"] = as_bool(payload, "donation_eligible")
        product = DB.product(variant["donation_product_id"])
        if product and product.get("status") in ("ACTIVE", "RETIRED"):
            variant["status"] = "ACTIVE" if variant["donation_eligible"] else "RETIRED"
    core.recompute_product_line(variant)
    DB.touch(variant)
    return success(serial.serialize("DonationProductLine", variant))


# ===========================================================================
# Product-scoped reads
# ===========================================================================

@bp.route("/impact-program/donation-products/<product_id>/liabilities", methods=["GET"])
@roles(IMPACT_AUDITOR, ALLOCATION_PLANNER, MARKETING_MANAGER)
def product_liabilities(product_id):
    common.product_or_404(product_id)
    season_id = request.args.get("impact_season_id")
    status = request.args.get("status")
    limit, offset = pagination()
    rows = [l for l in DB.donation_liabilities.values() if l.get("donation_product_id") == product_id]
    if season_id:
        rows = [r for r in rows if r.get("impact_season_id") == season_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("DonationLiability", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/donation-products/<product_id>/claims", methods=["GET"])
@roles(MARKETING_MANAGER, IMPACT_AUDITOR)
def product_claims(product_id):
    common.product_or_404(product_id)
    status = request.args.get("status")
    limit, offset = pagination()
    rows = [c for c in DB.marketing_claims.values() if c.get("donation_product_id") == product_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("MarketingClaim", page),
                   pagination=pagination_meta(limit, offset, total))