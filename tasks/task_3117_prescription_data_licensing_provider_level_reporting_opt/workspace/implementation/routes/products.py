"""ReportProduct endpoints, invoice preview, and delivery period creation/listing."""

from flask import Blueprint, request

from db import db
from errors import err_not_found, err_invalid_request, err_forbidden_ownership
from middleware import require_role, get_pagination, ALL_ROLES
from response import success_object, success_array
from services.calculations import calc_invoice_total, calc_deliverable_prescriber_count
from services.common import (
    body_json, require_fields, check_str, check_int, check_num,
    check_period, check_date, check_str_list, mint, touch,
)

bp = Blueprint("products", __name__)

PRODUCT_STATUSES = {"ACTIVE", "SUSPENDED"}


def _get_product(pid):
    product = db.products.get(pid)
    if product is None:
        raise err_not_found("Report product not found")
    return product


@bp.route("/report-products", methods=["POST"])
def create_product():
    require_role(["PlatformAdmin"])
    data = body_json()
    require_fields(data, [
        "client_id", "methodology_id", "name", "prescriber_ids",
        "base_fee_cents", "cell_fee_base_cents", "cell_fee_multiplier",
        "volume_discount_pct", "monthly_license_fee_cents",
    ])
    client_id = check_str(data, "client_id")
    if client_id not in db.clients:
        raise err_not_found("Client not found")
    methodology_id = check_str(data, "methodology_id")
    methodology = db.methodologies.get(methodology_id)
    if methodology is None:
        raise err_not_found("Methodology not found")
    name = check_str(data, "name")
    prescriber_ids = check_str_list(data, "prescriber_ids")
    base_fee_cents = check_int(data, "base_fee_cents", min_v=0)
    cell_fee_base_cents = check_int(data, "cell_fee_base_cents", min_v=0)
    cell_fee_multiplier = check_num(data, "cell_fee_multiplier")
    volume_discount_pct = check_num(data, "volume_discount_pct", min_v=0, max_v=1)
    monthly_license_fee_cents = check_int(data, "monthly_license_fee_cents", min_v=0)
    support_fee_pct = 0.08
    if "support_fee_pct" in data and data["support_fee_pct"] is not None:
        support_fee_pct = check_num(data, "support_fee_pct")
    for pid in prescriber_ids:
        if pid not in db.prescribers:
            raise err_not_found("Prescriber not found")
    product = mint(db.products, {
        "client_id": client_id,
        "methodology_id": methodology_id,
        "name": name,
        "prescriber_ids": list(prescriber_ids),
        "base_fee_cents": base_fee_cents,
        "cell_fee_base_cents": cell_fee_base_cents,
        "cell_fee_multiplier": cell_fee_multiplier,
        "volume_discount_pct": volume_discount_pct,
        "support_fee_pct": support_fee_pct,
        "monthly_license_fee_cents": monthly_license_fee_cents,
        "deliverable_prescriber_count": calc_deliverable_prescriber_count(prescriber_ids),
        "pinned_methodology_version": methodology["version"],
        "status": "ACTIVE",
    })
    return success_object(product, status=201)


@bp.route("/report-products", methods=["GET"])
def list_products():
    require_role(ALL_ROLES)
    limit, offset = get_pagination()
    client_id = request.args.get("client_id")
    methodology_id = request.args.get("methodology_id")
    status = request.args.get("status")
    if status is not None and status not in PRODUCT_STATUSES:
        raise err_invalid_request("Invalid status filter")
    items = sorted(db.products.values(), key=lambda p: p["created_at"])
    if client_id is not None:
        items = [p for p in items if p["client_id"] == client_id]
    if methodology_id is not None:
        items = [p for p in items if p["methodology_id"] == methodology_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)


@bp.route("/report-products/<pid>", methods=["GET"])
def get_product(pid):
    require_role(ALL_ROLES)
    return success_object(_get_product(pid))


@bp.route("/report-products/<pid>/sync-methodology", methods=["POST"])
def sync_methodology(pid):
    require_role(["PlatformAdmin"])
    product = _get_product(pid)
    methodology = db.methodologies[product["methodology_id"]]
    product["pinned_methodology_version"] = methodology["version"]
    touch(product)
    return success_object(product)


@bp.route("/report-products/<pid>/invoice-preview", methods=["POST"])
def invoice_preview(pid):
    user_id, role = require_role(["PlatformAdmin", "ManufacturerClient"])
    product = _get_product(pid)
    if role == "ManufacturerClient" and user_id != product["client_id"]:
        raise err_forbidden_ownership()
    data = body_json()
    require_fields(data, ["period_code"])
    period_code = check_period(data, "period_code")
    return success_object(calc_invoice_total(product, period_code))


@bp.route("/report-products/<pid>/delivery-periods", methods=["POST"])
def create_delivery_period(pid):
    require_role(["PlatformAdmin"])
    product = _get_product(pid)
    data = body_json()
    require_fields(data, ["period_code", "period_end_date", "total_due_deliveries"])
    period = mint(db.periods, {
        "product_id": pid,
        "period_code": check_period(data, "period_code"),
        "period_end_date": check_date(data, "period_end_date"),
        "total_due_deliveries": check_int(data, "total_due_deliveries", min_v=1),
        "breach_count": None,
        "sla_variant": None,
        "sla_credit_cents": None,
        "status": "OPEN",
    })
    return success_object(period, status=201)


@bp.route("/report-products/<pid>/delivery-periods", methods=["GET"])
def list_delivery_periods(pid):
    require_role(ALL_ROLES)
    _get_product(pid)
    limit, offset = get_pagination()
    items = sorted(
        (p for p in db.periods.values() if p["product_id"] == pid),
        key=lambda p: p["created_at"],
    )
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)
