"""ReportDeliveryPeriod endpoints: get, close, schedule deliveries, list deliveries."""

from flask import Blueprint

from db import db
from errors import err_not_found, err_invalid_state
from middleware import require_role, get_pagination, ALL_ROLES
from response import success_object, success_array
from services.calculations import calc_sla_credit
from services.common import body_json, require_fields, check_enum, mint, touch

bp = Blueprint("periods", __name__)

SLA_VARIANTS = {"PERIOD_WEIGHTED", "DELIVERY_WEIGHTED"}


def _get_period(pid):
    period = db.periods.get(pid)
    if period is None:
        raise err_not_found("Delivery period not found")
    return period


@bp.route("/report-delivery-periods/<pid>", methods=["GET"])
def get_period(pid):
    require_role(ALL_ROLES)
    return success_object(_get_period(pid))


@bp.route("/report-delivery-periods/<pid>/close", methods=["POST"])
def close_period(pid):
    require_role(["PlatformAdmin"])
    period = _get_period(pid)
    data = body_json()
    require_fields(data, ["sla_variant"])
    sla_variant = check_enum(data, "sla_variant", SLA_VARIANTS)
    if period["status"] != "OPEN":
        raise err_invalid_state("Period must be OPEN to close")
    breach_count = sum(
        1 for d in db.deliveries.values()
        if d["period_id"] == pid and d["status"] == "RECALLED"
    )
    product = db.products[period["product_id"]]
    period["breach_count"] = breach_count
    period["sla_variant"] = sla_variant
    period["sla_credit_cents"] = calc_sla_credit(product, period, breach_count, sla_variant)
    period["status"] = "CLOSED"
    touch(period)
    return success_object(period)


@bp.route("/report-delivery-periods/<pid>/deliveries", methods=["POST"])
def schedule_delivery(pid):
    require_role(["PlatformAdmin"])
    period = _get_period(pid)
    delivery = mint(db.deliveries, {
        "period_id": pid,
        "period_code": period["period_code"],
        "status": "SCHEDULED",
        "compiled_cell_ids": [],
        "included_prescriber_ids": [],
        "fee_cents": None,
        "recall_count": 0,
        "must_recompile": False,
    })
    return success_object(delivery, status=201)


@bp.route("/report-delivery-periods/<pid>/deliveries", methods=["GET"])
def list_period_deliveries(pid):
    require_role(ALL_ROLES)
    _get_period(pid)
    limit, offset = get_pagination()
    items = sorted(
        (d for d in db.deliveries.values() if d["period_id"] == pid),
        key=lambda d: d["created_at"],
    )
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)
