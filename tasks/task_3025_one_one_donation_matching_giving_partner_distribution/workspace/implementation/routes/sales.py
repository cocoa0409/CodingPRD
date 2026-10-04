"""Commercial plane: retail sales orders, their lines, payment, returns and exchanges."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB, iso3, new_id, parse_iso
from errors import ApiError
from middleware import (CUSTOMER_SERVICE, FULFILLMENT_OPERATOR, IMPACT_AUDITOR,
                        PROVISIONING_PARTNER, roles)
from response import pagination_meta, success
from routes import _common as common
from services import calc, core, serial
from validation import (as_bool, as_enum, as_int, as_nonempty_str, as_str, body,
                        occ, paginate, pagination, require)

bp = Blueprint("sales", __name__)

CHANNELS = ["RETAIL_POS", "RETAIL_ECOM"]
ORDER_STATUSES = ["CREATED", "PAID", "DONATION_SATISFIED", "PARTIALLY_REFUNDED",
                  "REFUNDED", "CANCELLED"]
FULFILLMENT_STATUSES = ["PLACED", "PICKED", "SHIPPED", "DELIVERED", "CANCELLED"]
FULFILLMENT_ORDER = {name: index for index, name in enumerate(FULFILLMENT_STATUSES)}
LINE_STATUSES = ["OPEN", "RETURN_REQUESTED", "RETURN_APPROVED", "RETURNED_CREDITED",
                 "EXCHANGED_REPLACED", "EXEMPTED", "SETTLED"]
REQUEST_REASONS = ["SIZE", "DEFECT", "CHANGE_OF_MIND", "GOODWILL"]

TERMINAL_LINE_STATES = ("EXEMPTED", "RETURNED_CREDITED", "EXCHANGED_REPLACED")

ORDER_VIEWERS = [CUSTOMER_SERVICE, IMPACT_AUDITOR, PROVISIONING_PARTNER]
LINE_VIEWERS = [CUSTOMER_SERVICE, IMPACT_AUDITOR]


# ===========================================================================
# Orders
# ===========================================================================

@bp.route("/impact-program/sales-orders", methods=["POST"])
@roles(CUSTOMER_SERVICE)
def create_order():
    payload = body()
    require(payload, "order_number", "channel")
    order_number = as_nonempty_str(payload, "order_number", required=True)
    channel = as_enum(payload, "channel", CHANNELS, required=True)

    for existing in DB.sales_orders.values():
        if existing.get("order_number") == order_number:
            raise ApiError("ERR_DUPLICATE_RESOURCE")

    now = iso3(DB.now())
    order = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "order_number": order_number,
        "channel": channel,
        "status": "CREATED",
        "fulfillment_status": "PLACED",
        "ordered_units": 0,
        "returned_units": 0,
        "fulfilled_units": 0,
        "refunded_cents": 0,
        "placed_at": now,
        "paid_at": None,
    }
    DB.sales_orders[order["id"]] = order
    return success(serial.serialize("SalesOrder", order)), 201


@bp.route("/impact-program/sales-orders", methods=["GET"])
@roles(CUSTOMER_SERVICE, IMPACT_AUDITOR, PROVISIONING_PARTNER)
def list_orders():
    limit, offset = pagination()
    rows = list(DB.sales_orders.values())
    for name in ("status", "fulfillment_status", "channel"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("SalesOrder", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/sales-orders/<order_id>", methods=["GET"])
@roles(CUSTOMER_SERVICE, IMPACT_AUDITOR, PROVISIONING_PARTNER)
def get_order(order_id):
    order = common.order_or_404(order_id)
    core.recompute_order(order)
    return success(serial.serialize("SalesOrder", order))


@bp.route("/impact-program/sales-orders/<order_id>/lines", methods=["POST"])
@roles(CUSTOMER_SERVICE)
def add_line(order_id):
    order = common.order_or_404(order_id)
    payload = body()
    require(payload, "donation_product_line_id", "quantity", "unit_price_cents")
    variant_id = as_str(payload, "donation_product_line_id", required=True)
    quantity = as_int(payload, "quantity", required=True, minimum=1)
    unit_price = as_int(payload, "unit_price_cents", required=True, minimum=0)
    line_discount = as_int(payload, "line_discount_cents", default=0, minimum=0)
    gtin = as_str(payload, "gtin")

    if order.get("status") == "CANCELLED":
        raise ApiError("ERR_SALES_ORDER_CANCELLED")

    variant = common.product_line_or_404(variant_id)
    product = common.product_or_404(variant["donation_product_id"])

    if not variant.get("donation_eligible"):
        raise ApiError("ERR_LINE_NOT_DONATION_ELIGIBLE")
    if gtin is not None and gtin != variant.get("gtin"):
        raise ApiError("ERR_ENTITY_UNRESOLVED")

    season = DB.current_season()
    now = iso3(DB.now())
    line = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "sales_order_id": order_id,
        "donation_product_id": product["id"],
        "donation_product_line_id": variant_id,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_discount_cents": line_discount,
        "return_window_days": 30,
        "obligated_units": 0,
        "status": "OPEN",
        "impact_season_id": season["id"] if season else None,
        "replacement_order_id": None,
    }
    DB.sales_order_lines[line["id"]] = line

    core.materialize_line_obligations(line)
    core.recompute_order(order)
    if season:
        liability = core.ensure_liability(product["id"], season)
        core.recompute_liability(liability)
        DB.touch(liability)
        core.recompute_season(season)
    DB.touch(order)

    # The sale activates the donation obligation on the product's variant line.
    if product.get("obligation_model") == "AT_VESTING" and variant.get("status") == "ACTIVE":
        variant["status"] = "VESTED"
        DB.touch(variant)
        # Vesting adds the variant's obligation units to the current season's
        # liability (scaffold: ACTIVE -> VESTED side effect).
        if season:
            liability = core.ensure_liability(product["id"], season)
            liability["obligation_units"] = (liability.get("obligation_units") or 0) \
                + (variant.get("obligation_units") or 0)
            DB.touch(liability)

    return success(serial.serialize("SalesOrderLine", line)), 201


@bp.route("/impact-program/sales-orders/<order_id>/lines", methods=["GET"])
@roles(CUSTOMER_SERVICE, IMPACT_AUDITOR)
def list_order_lines(order_id):
    common.order_or_404(order_id)
    status = request.args.get("status")
    limit, offset = pagination()
    rows = DB.order_lines(order_id)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("SalesOrderLine", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/sales-order-lines", methods=["GET"])
@roles(CUSTOMER_SERVICE, IMPACT_AUDITOR, PROVISIONING_PARTNER)
def list_all_lines():
    limit, offset = pagination()
    rows = list(DB.sales_order_lines.values())
    for name in ("sales_order_id", "donation_product_id", "donation_product_line_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("SalesOrderLine", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/sales-order-lines/<line_id>", methods=["GET"])
@roles(CUSTOMER_SERVICE, IMPACT_AUDITOR, PROVISIONING_PARTNER)
def get_line_by_own_id(line_id):
    line = common.sales_order_line_or_404(line_id)
    return success(serial.serialize("SalesOrderLine", line))


@bp.route("/impact-program/sales-orders/<order_id>/lines/<line_id>", methods=["GET"])
@roles(CUSTOMER_SERVICE, IMPACT_AUDITOR)
def get_order_line(order_id, line_id):
    common.order_or_404(order_id)
    line = common.order_line_or_404(order_id, line_id)
    return success(serial.serialize("SalesOrderLine", line))


@bp.route("/impact-program/sales-orders/<order_id>/pay", methods=["POST"])
@roles(CUSTOMER_SERVICE)
def pay_order(order_id):
    order = common.order_or_404(order_id)

    if order.get("status") in ("PAID", "DONATION_SATISFIED", "PARTIALLY_REFUNDED", "REFUNDED"):
        raise ApiError("ERR_SALES_ORDER_ALREADY_PAID")
    if order.get("status") == "CANCELLED":
        raise ApiError("ERR_SALES_ORDER_CANCELLED")
    # PRD §3.5: a PAID order whose fulfillment is still PLACED may be cancelled,
    # which returns it to CREATED so it can be corrected and paid again.
    if order.get("status") not in ("CREATED", "PAID"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if order.get("status") == "PAID" and order.get("fulfillment_status") != "PLACED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    lines = DB.order_lines(order_id)
    if any(l.get("status") != "OPEN" for l in lines):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    now = iso3(DB.now())
    order["status"] = "PAID"
    order["paid_at"] = now
    order["fulfillment_status"] = "PLACED"
    DB.touch(order)

    for line in lines:
        core.materialize_line_obligations(line)
        DB.touch(line)
        season = DB.season(line.get("impact_season_id"))
        if season:
            liability = core.ensure_liability(line["donation_product_id"], season)
            core.recompute_liability(liability)
            DB.touch(liability)
            core.recompute_season(season)
    return success(serial.serialize("SalesOrder", order))


@bp.route("/impact-program/sales-orders/<order_id>/lines/<line_id>/settle", methods=["POST"])
@roles(FULFILLMENT_OPERATOR)
def settle_line(order_id, line_id):
    order = common.order_or_404(order_id)
    line = common.order_line_or_404(order_id, line_id)
    payload = body()
    require(payload, "shipped_units")
    shipped_units = as_int(payload, "shipped_units", required=True, minimum=1)

    if order.get("status") == "CANCELLED":
        raise ApiError("ERR_SALES_ORDER_CANCELLED")
    if line.get("status") not in ("OPEN", "RETURN_REQUESTED", "RETURN_APPROVED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    product = common.product_or_404(line["donation_product_id"])
    variant = common.product_line_or_404(line["donation_product_line_id"])
    core.materialize_line_obligations(line)
    line["settled_units"] = shipped_units
    line["settled_at"] = iso3(DB.now())
    # PRD §3.5: settling is a one-shot out-of-warehouse act, so the line leaves
    # the OPEN family and a second settle trips the state rung instead of
    # double-counting the final ledger.
    line["status"] = "SETTLED"
    DB.touch(line)

    season = DB.season(line.get("impact_season_id"))
    if season:
        liability = core.ensure_liability(product["id"], season)
        core.recompute_liability(liability)
        DB.touch(liability)
        core.recompute_season(season)

    # PRD §3.4: "A variant moves to `VESTED` when a sales line for it settles,
    # provided the product's `obligation_model` is `AT_VESTING` and its
    # `design_channel` is `DUAL_CHANNEL`." A COMMITTED donation-only variant can
    # also still reach VESTED on its first settled sale.
    if variant.get("status") != "VESTED":
        if product.get("obligation_model") == "AT_VESTING" and \
                product.get("design_channel") == "DUAL_CHANNEL":
            variant["status"] = "VESTED"
            DB.touch(variant)
        elif variant.get("status") == "COMMITTED":
            variant["status"] = "VESTED"
            DB.touch(variant)
        if season:
            liability = core.ensure_liability(product["id"], season)
            liability["obligation_units"] = (liability.get("obligation_units") or 0) \
                + (variant.get("obligation_units") or 0)
            DB.touch(liability)
    core.recompute_order(order)
    DB.touch(order)
    return success(serial.serialize("SalesOrderLine", line))


@bp.route("/impact-program/sales-orders/<order_id>/cancel", methods=["POST"])
@roles(CUSTOMER_SERVICE)
def cancel_order(order_id):
    order = common.order_or_404(order_id)
    payload = body()
    reason = as_str(payload, "reason")

    if order.get("status") == "CANCELLED":
        raise ApiError("ERR_SALES_ORDER_CANCELLED")

    if order.get("status") == "CREATED":
        order["status"] = "CANCELLED"
        order["fulfillment_status"] = "CANCELLED"
    elif order.get("status") == "PAID" and order.get("fulfillment_status") == "PLACED":
        order["status"] = "CREATED"
        order["paid_at"] = None
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    DB.touch(order)
    _recompute_order_liabilities(order)
    return success(serial.serialize("SalesOrder", order))


def _recompute_order_liabilities(order):
    touched = set()
    for line in DB.order_lines(order["id"]):
        season_id = line.get("impact_season_id")
        if not season_id:
            continue
        touched.add((line["donation_product_id"], season_id))
    for product_id, season_id in touched:
        core.recompute_product_liabilities(product_id, season_id)
    for season_id in {s for _, s in touched}:
        season = DB.season(season_id)
        if season:
            core.recompute_season(season)


@bp.route("/impact-program/sales-orders/<order_id>/fulfillment", methods=["PATCH"])
@roles(FULFILLMENT_OPERATOR)
def advance_fulfillment(order_id):
    order = common.order_or_404(order_id)
    payload = body()
    require(payload, "fulfillment_status")
    target = as_enum(payload, "fulfillment_status", FULFILLMENT_STATUSES, required=True)

    current = order.get("fulfillment_status")
    if target == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if FULFILLMENT_ORDER.get(target, -1) <= FULFILLMENT_ORDER.get(current, -1):
        raise ApiError("ERR_FULFILLMENT_REGRESSION")

    order["fulfillment_status"] = target
    core.recompute_order(order)
    DB.touch(order)
    return success(serial.serialize("SalesOrder", order))


# ===========================================================================
# Returns and exchanges
# ===========================================================================

def _season_window_reset(season):
    if not season:
        return False
    flags = DB.season_flags.get(season["id"]) or {}
    return bool(flags.get("RESET_PURCHASE_WINDOW"))


def _window_expires_at(order, line):
    if not order.get("paid_at"):
        return None
    return parse_iso(order["paid_at"]) + timedelta(days=line.get("return_window_days") or 30)


def _create_return_request(order, line, payload):
    reason = as_enum(payload, "request_reason", REQUEST_REASONS, required=True)
    requested_units = as_int(payload, "requested_units", required=True, minimum=1)
    is_exchange = as_bool(payload, "is_exchange", default=False)
    replacement_product_id = as_str(payload, "replacement_product_id")
    expected_line_version = occ(payload, "expected_line_version")

    status = line.get("status")
    if status == "OPEN":
        pass
    elif status == "RETURNED_CREDITED":
        season = DB.season(line.get("impact_season_id"))
        if not season or season.get("status") != "PLANNED":
            raise ApiError("ERR_LINE_ALREADY_RETURNED")
    elif status == "EXCHANGED_REPLACED":
        pass
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    common.occ_check(line.get("version"), expected_line_version)

    season = DB.season(line.get("impact_season_id"))
    window_end = _window_expires_at(order, line)
    if window_end is not None and DB.now() > window_end:
        if reason != "DEFECT" and not _season_window_reset(season):
            raise ApiError("ERR_RETURN_WINDOW_CLOSED")

    liability = None
    if season:
        liability = calc.find_liability(DB, line["donation_product_id"], season["id"])

    now = iso3(DB.now())
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "sales_order_line_id": line["id"],
        "donation_liability_id": liability["id"] if liability else None,
        "request_reason": reason,
        "requested_units": requested_units,
        "is_exchange": bool(is_exchange),
        "replacement_product_id": replacement_product_id,
        "replacement_is_donation_good": False,
        "status": "REQUESTED",
        "terminal_outcome": None,
        "refund_amount_cents": 0,
        "liability_delta_units": 0,
        "window_expires_at": iso3(window_end),
    }
    DB.return_requests[record["id"]] = record
    line["status"] = "RETURN_REQUESTED"
    DB.touch(line)
    return record


@bp.route("/impact-program/sales-orders/<order_id>/lines/<line_id>/return-requests",
          methods=["POST"])
@roles(CUSTOMER_SERVICE)
def open_return_nested(order_id, line_id):
    order = common.order_or_404(order_id)
    line = common.order_line_or_404(order_id, line_id)
    record = _create_return_request(order, line, body())
    return success(serial.serialize("ReturnRequest", record)), 201


@bp.route("/impact-program/return-requests", methods=["POST"])
@roles(CUSTOMER_SERVICE)
def open_return_direct():
    payload = body()
    require(payload, "sales_order_line_id")
    line_id = as_str(payload, "sales_order_line_id", required=True)
    line = common.sales_order_line_or_404(line_id)
    order = common.order_or_404(line["sales_order_id"])
    record = _create_return_request(order, line, payload)
    return success(serial.serialize("ReturnRequest", record)), 201


@bp.route("/impact-program/return-requests", methods=["GET"])
@roles(CUSTOMER_SERVICE, IMPACT_AUDITOR, PROVISIONING_PARTNER)
def list_returns():
    limit, offset = pagination()
    rows = list(DB.return_requests.values())
    for name in ("sales_order_line_id", "donation_liability_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    is_exchange = request.args.get("is_exchange")
    if is_exchange is not None:
        flag = is_exchange.strip().lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r.get("is_exchange")) is flag]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("ReturnRequest", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/return-requests/<return_id>", methods=["GET"])
@roles(CUSTOMER_SERVICE, IMPACT_AUDITOR, PROVISIONING_PARTNER)
def get_return(return_id):
    record = common.return_or_404(return_id)
    return success(serial.serialize("ReturnRequest", record))


@bp.route("/impact-program/sales-orders/<order_id>/lines/<line_id>/return-requests",
          methods=["GET"])
@roles(CUSTOMER_SERVICE, IMPACT_AUDITOR)
def list_line_returns(order_id, line_id):
    common.order_or_404(order_id)
    common.order_line_or_404(order_id, line_id)
    status = request.args.get("status")
    limit, offset = pagination()
    rows = DB.line_return_requests(line_id)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("ReturnRequest", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/return-requests/<return_id>/approve", methods=["POST"])
@roles(CUSTOMER_SERVICE)
def approve_return(return_id):
    record = common.return_or_404(return_id)
    if record.get("status") != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    line = common.sales_order_line_or_404(record["sales_order_line_id"])
    order = common.order_or_404(line["sales_order_id"])
    window_end = _window_expires_at(order, line)
    if window_end is not None and DB.now() > window_end:
        if record.get("request_reason") != "DEFECT":
            raise ApiError("ERR_RETURN_WINDOW_CLOSED")

    record["status"] = "APPROVED"
    line["status"] = "RETURN_APPROVED"
    DB.touch(record)
    DB.touch(line)
    return success(serial.serialize("ReturnRequest", record))


@bp.route("/impact-program/return-requests/<return_id>/reject", methods=["POST"])
@roles(CUSTOMER_SERVICE)
def reject_return(return_id):
    record = common.return_or_404(return_id)
    if record.get("status") != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    line = common.sales_order_line_or_404(record["sales_order_line_id"])
    order = common.order_or_404(line["sales_order_id"])
    window_end = _window_expires_at(order, line)
    if record.get("request_reason") != "CHANGE_OF_MIND":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if window_end is not None and DB.now() > window_end:
        raise ApiError("ERR_RETURN_WINDOW_CLOSED")

    record["status"] = "REJECTED"
    line["status"] = "OPEN"
    DB.touch(record)
    DB.touch(line)
    return success(serial.serialize("ReturnRequest", record))


@bp.route("/impact-program/return-requests/<return_id>/credit", methods=["POST"])
@roles(CUSTOMER_SERVICE)
def credit_return(return_id):
    record = common.return_or_404(return_id)
    payload = body()
    line = common.sales_order_line_or_404(record["sales_order_line_id"])
    order = common.order_or_404(line["sales_order_id"])

    if record.get("status") != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if record.get("is_exchange"):
        replacement_id = as_str(payload, "replacement_product_id") or record.get("replacement_product_id")
        if replacement_id is None:
            raise ApiError("ERR_EXCHANGE_REPLACEMENT_INVALID")
        replacement = DB.product(replacement_id)
        if not replacement or replacement.get("status") != "ACTIVE":
            raise ApiError("ERR_EXCHANGE_REPLACEMENT_INVALID")
        record["replacement_product_id"] = replacement_id
        record["replacement_is_donation_good"] = bool(
            replacement.get("approved_donation_ratio_units"))
        record["status"] = "EXCHANGED"
        record["terminal_outcome"] = "REPLACED"
        record["refund_amount_cents"] = 0
        line["status"] = "EXCHANGED_REPLACED"
        season = DB.season(line.get("impact_season_id"))
        if season:
            core.ensure_liability(replacement_id, season)
            # A replacement obligation accrues while the original is retained.
            for variant in DB.product_lines(replacement_id):
                core.recompute_product_line(variant)
    else:
        record["status"] = "CREDITED"
        record["terminal_outcome"] = "REFUNDED"
        record["refund_amount_cents"] = calc.return_refund_amount(
            line, record.get("requested_units") or 0)
        line["status"] = "RETURNED_CREDITED"

    # The donation obligation is never reversed (PRD 3.6).
    record["liability_delta_units"] = 0
    DB.touch(record)
    DB.touch(line)
    core.recompute_order(order)
    DB.touch(order)
    _recompute_order_liabilities(order)
    return success(serial.serialize("ReturnRequest", record))


@bp.route("/impact-program/sales-orders/<order_id>/lines/<line_id>/exempt", methods=["POST"])
@roles(CUSTOMER_SERVICE)
def exempt_line(order_id, line_id):
    order = common.order_or_404(order_id)
    line = common.order_line_or_404(order_id, line_id)
    payload = body()
    require(payload, "request_reason")
    reason = as_enum(payload, "request_reason", REQUEST_REASONS, required=True)

    if line.get("status") != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if reason not in ("GOODWILL", "DEFECT"):
        raise ApiError("ERR_EXEMPTION_REASON_INVALID")

    line["status"] = "EXEMPTED"
    DB.touch(line)
    core.recompute_order(order)
    DB.touch(order)
    return success(serial.serialize("SalesOrderLine", line))