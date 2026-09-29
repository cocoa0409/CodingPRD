"""Parts selection, authorisation, negotiation, ordering, receipt, returns and delays."""
from flask import Blueprint, request

import auth
import calc
import db
import guards
import response
import serialize
import validate
from db import store
from errors import raise_error
from validate import F

bp = Blueprint("parts", __name__)

PART_TYPES = ("OEM", "AFTERMARKET", "RECYCLED", "RECONDITIONED")
PROCUREMENT_STATUSES = ("PLANNED", "QUOTED", "COUNTERED", "PRICE_LOCKED", "ORDERED",
                        "RECEIVED", "INSTALLED", "RETURNED", "VOID")
AUTH_STATUSES = ("INSURER_ALLOWED", "PENDING_CONSENT", "CUSTOMER_CONSENTED",
                 "CUSTOMER_DECLINED")
CONDITIONS = ("CORRECT", "INCORRECT", "DAMAGED")
RETURN_REASONS = ("UNUSED", "INCORRECT", "DAMAGED")

ALTERNATE_TYPES = ("AFTERMARKET", "RECYCLED", "RECONDITIONED")
ALLOWED_FLAG = {
    "AFTERMARKET": "aftermarket_allowed",
    "RECYCLED": "recycled_allowed",
    "RECONDITIONED": "reconditioned_allowed",
}

ORDERING_STAGES = ("ESTIMATE_LOCKED", "PARTS_STAGED", "REPAIR", "REFINISH_CALIBRATION",
                   "READY_FOR_QC")
INSTALL_STAGES = ("REPAIR", "REFINISH_CALIBRATION")


def _find_parts_line(parts_line_id):
    """Rung 10, the parts-line path identifier."""
    row = store.parts_lines.get(parts_line_id)
    if row is None:
        raise_error("ERR_PARTS_LINE_NOT_FOUND")
    return row


def _find_vendor(vendor_id):
    row = store.parts_vendors.get(vendor_id)
    if row is None:
        raise_error("ERR_PARTS_VENDOR_NOT_FOUND")
    return row


def _vehicle_age_ok(order, insurer):
    """Vehicle age in whole calendar years, per PRD 3.5."""
    minimum = int(insurer.get("alternate_parts_min_vehicle_age_years", 3))
    age = db.now().year - int(order["vehicle_model_year"])
    return age >= minimum


def _insurer_permits(insurer, part_type):
    if part_type == "OEM":
        return True
    return bool(insurer.get(ALLOWED_FLAG[part_type], False))


def _permits_any_alternate(insurer):
    return any(bool(insurer.get(ALLOWED_FLAG[t], False)) for t in ALTERNATE_TYPES)


CREATE_SPEC = [
    F("part_number", "string", required=True),
    F("part_description", "string", required=True),
    F("part_type", "string", required=True, enum=PART_TYPES),
    F("list_price_cents", "integer", required=True),
    F("qty", "integer", required=True),
    F("vendor_id", "string", nullable=True),
    F("oem_upgrade", "boolean", default=False),
]


@bp.route("/estimate-lines/<line_id>/parts-lines", methods=["POST"])
def create_parts_line(line_id):
    auth.authenticate(("PartsManager",))
    data = validate.body(CREATE_SPEC)
    validate.require(data["list_price_cents"] > 0, "list_price_cents must be > 0.")
    validate.require(data["qty"] >= 1, "qty must be at least 1.")

    estimate_line = store.estimate_lines.get(line_id)
    if estimate_line is None:
        raise_error("ERR_ESTIMATE_LINE_NOT_FOUND")
    vendor = None
    if data.get("vendor_id") is not None:
        vendor = _find_vendor(data["vendor_id"])
    order = store.repair_orders.get(estimate_line["repair_order_id"])
    guards.not_terminal(order)

    insurer = store.insurers.get(order["insurer_id"]) or {}
    part_type = data["part_type"]
    if not _insurer_permits(insurer, part_type):
        raise_error("ERR_PART_TYPE_NOT_ALLOWED_BY_INSURER")

    age_ok = _vehicle_age_ok(order, insurer)
    if data["oem_upgrade"]:
        if part_type != "OEM" or not _permits_any_alternate(insurer) or not age_ok:
            raise_error("ERR_OEM_UPGRADE_NOT_APPLICABLE")

    customer = store.customers.get(order["customer_id"]) or {}
    if part_type == "OEM":
        authorization = "INSURER_ALLOWED"
    elif age_ok:
        authorization = "INSURER_ALLOWED"
    elif customer.get("preferred_alternate_parts_ok"):
        authorization = "CUSTOMER_CONSENTED"
    else:
        authorization = "PENDING_CONSENT"

    bumper = calc.Bumper()
    row = db.base_row()
    row.update({
        "estimate_line_id": estimate_line["id"],
        "vendor_id": data.get("vendor_id"),
        "part_number": data["part_number"],
        "part_description": data["part_description"],
        "part_type": part_type,
        "list_price_cents": data["list_price_cents"],
        "qty": data["qty"],
        "oem_upgrade": bool(data["oem_upgrade"]),
        "quoted_unit_price_cents": None,
        "counter_unit_price_cents": None,
        "unit_price_cents": None,
        "quote_round": 0,
        "unit_extended_cents": None,
        "extended_price_cents": 0,
        "restocking_fee_cents": 0,
        "procurement_status": "PLANNED",
        "authorization_status": authorization,
        "vendor_order_seq": None,
        "promised_eta": None,
        "received_at": None,
        "received_qty": 0,
        "returned_qty": 0,
        "return_reason": None,
        "on_time": None,
    })
    store.parts_lines[row["id"]] = row
    calc.derive_posture(order)
    bumper.add(order)
    bumper.flush()
    return response.created(serialize.parts_line(row))


@bp.route("/parts-lines/<parts_line_id>", methods=["GET"])
def read_parts_line(parts_line_id):
    auth.authenticate(("Estimator", "PartsManager", "Technician"))
    return response.ok(serialize.parts_line(_find_parts_line(parts_line_id)))


@bp.route("/parts-lines", methods=["GET"])
def list_parts_lines():
    auth.authenticate(("Estimator", "PartsManager", "Technician"))
    status = validate.enum_filter(request.args, "procurement_status", PROCUREMENT_STATUSES)
    limit, offset = response.read_pagination(request.args)

    estimate_line_id = request.args.get("estimate_line_id")
    if estimate_line_id is not None and estimate_line_id not in store.estimate_lines:
        raise_error("ERR_ESTIMATE_LINE_NOT_FOUND")
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        _find_vendor(vendor_id)

    rows = db.in_creation_order(list(store.parts_lines.values()))
    if estimate_line_id is not None:
        rows = [r for r in rows if r["estimate_line_id"] == estimate_line_id]
    if vendor_id is not None:
        rows = [r for r in rows if r.get("vendor_id") == vendor_id]
    if status is not None:
        rows = [r for r in rows if r["procurement_status"] == status]
    return response.paginate(rows, limit, offset, serialize.parts_line)


# --- price negotiation -----------------------------------------------------------------
QUOTE_SPEC = [
    F("vendor_id", "string", required=True),
    F("quoted_unit_price_cents", "integer", required=True),
]


@bp.route("/parts-lines/<parts_line_id>/quote", methods=["POST"])
def record_quote(parts_line_id):
    auth.authenticate(("PartsManager",))
    data = validate.body(QUOTE_SPEC)
    validate.require(data["quoted_unit_price_cents"] > 0,
                     "quoted_unit_price_cents must be > 0.")
    vendor = _find_vendor(data["vendor_id"])
    parts_line = _find_parts_line(parts_line_id)
    order = calc.parts_line_order(parts_line)
    guards.not_terminal(order)
    guards.parts_state_in(parts_line, ("PLANNED", "COUNTERED"))
    if parts_line["part_type"] not in (vendor.get("part_types_offered") or []):
        raise_error("ERR_PART_TYPE_NOT_OFFERED")
    if parts_line["procurement_status"] == "COUNTERED" \
            and parts_line.get("vendor_id") != vendor["id"]:
        raise_error("ERR_VENDOR_MISMATCH")

    bumper = calc.Bumper()
    if parts_line["procurement_status"] == "PLANNED":
        parts_line["quote_round"] = 1
    else:
        parts_line["quote_round"] = int(parts_line["quote_round"]) + 1
        parts_line["counter_unit_price_cents"] = None
    parts_line["procurement_status"] = "QUOTED"
    parts_line["vendor_id"] = vendor["id"]
    parts_line["quoted_unit_price_cents"] = data["quoted_unit_price_cents"]
    bumper.add(parts_line)
    bumper.flush()
    return response.ok(serialize.parts_line(parts_line))


COUNTER_SPEC = [F("counter_unit_price_cents", "integer", required=True)]


@bp.route("/parts-lines/<parts_line_id>/counter-offer", methods=["POST"])
def counter_offer(parts_line_id):
    auth.authenticate(("PartsManager",))
    data = validate.body(COUNTER_SPEC)
    validate.require(data["counter_unit_price_cents"] > 0,
                     "counter_unit_price_cents must be > 0.")
    parts_line = _find_parts_line(parts_line_id)
    order = calc.parts_line_order(parts_line)
    guards.not_terminal(order)
    guards.parts_state_in(parts_line, ("QUOTED",))
    if int(data["counter_unit_price_cents"]) >= int(parts_line["quoted_unit_price_cents"]):
        raise_error("ERR_COUNTER_NOT_LOWER")

    bumper = calc.Bumper()
    parts_line["procurement_status"] = "COUNTERED"
    parts_line["counter_unit_price_cents"] = data["counter_unit_price_cents"]
    bumper.add(parts_line)
    bumper.flush()
    return response.ok(serialize.parts_line(parts_line))


@bp.route("/parts-lines/<parts_line_id>/accept-price", methods=["POST"])
def accept_price(parts_line_id):
    auth.authenticate(("PartsManager",))
    validate.body([])
    parts_line = _find_parts_line(parts_line_id)
    order = calc.parts_line_order(parts_line)
    guards.not_terminal(order)
    guards.parts_state_in(parts_line, ("QUOTED",))

    insurer = store.insurers.get(order["insurer_id"]) or {}
    ceiling = calc.round_cents(calc.dec(parts_line["list_price_cents"])
                               * calc.dec(insurer.get("parts_price_ceiling_pct", 1.1)))
    if int(parts_line["quoted_unit_price_cents"]) > ceiling:
        raise_error("ERR_PARTS_PRICE_CEILING_EXCEEDED")

    bumper = calc.Bumper()
    vendor = store.parts_vendors.get(parts_line.get("vendor_id")) or {}
    parts_line["procurement_status"] = "PRICE_LOCKED"
    parts_line["unit_price_cents"] = int(parts_line["quoted_unit_price_cents"])
    parts_line["unit_extended_cents"] = calc.parts_unit_extended(parts_line, vendor)
    parts_line["extended_price_cents"] = calc.parts_extended_price(parts_line)
    calc.estimate_totals(order, bumper)
    calc.derive_posture(order)
    bumper.add(parts_line)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.parts_line(parts_line))


# --- ordering, receipt, installation, returns -------------------------------------------
ORDER_SPEC = [F("promised_eta", "string", required=True)]


@bp.route("/parts-lines/<parts_line_id>/order", methods=["POST"])
def place_order(parts_line_id):
    auth.authenticate(("PartsManager",))
    data = validate.body(ORDER_SPEC)
    validate.instant(data["promised_eta"],
                     "promised_eta must be an ISO-8601 instant.")
    parts_line = _find_parts_line(parts_line_id)
    order = calc.parts_line_order(parts_line)
    guards.not_terminal(order)
    guards.stage_in(order, ORDERING_STAGES)
    guards.parts_state_in(parts_line, ("PRICE_LOCKED",))
    guards.posture_open(order)

    vendor = store.parts_vendors.get(parts_line.get("vendor_id"))
    if vendor is None:
        raise_error("ERR_PARTS_VENDOR_NOT_FOUND")
    if vendor.get("status") != "ACTIVE":
        raise_error("ERR_VENDOR_SUSPENDED")
    if int(parts_line["qty"]) > int(vendor.get("max_qty_per_line", 4)):
        raise_error("ERR_VENDOR_QTY_CAP_EXCEEDED")
    if parts_line["authorization_status"] not in ("INSURER_ALLOWED", "CUSTOMER_CONSENTED"):
        raise_error("ERR_CUSTOMER_CONSENT_REQUIRED")
    if int(vendor.get("fulfillment_score_rolling", 50)) < calc.VENDOR_SCORE_FLOOR:
        raise_error("ERR_VENDOR_SCORE_BELOW_FLOOR")
    exposure_ceiling = int(order["deductible_cents"]) + int(order.get("betterment_cents") or 0)
    if int(order.get("customer_pay_cents") or 0) > exposure_ceiling:
        raise_error("ERR_AUTHORIZED_AMOUNT_EXCEEDED")

    bumper = calc.Bumper()
    parts_line["procurement_status"] = "ORDERED"
    parts_line["promised_eta"] = data["promised_eta"]
    vendor["order_seq_counter"] = int(vendor.get("order_seq_counter") or 0) + 1
    parts_line["vendor_order_seq"] = vendor["order_seq_counter"]
    unit = int(parts_line.get("unit_extended_cents") or 0)
    order["parts_ordered_gross_cents"] = int(order.get("parts_ordered_gross_cents") or 0) \
        + unit * int(parts_line["qty"])
    calc.commitment_ledger(order)
    calc.estimate_totals(order, bumper)
    calc.derive_posture(order)
    bumper.add(parts_line)
    bumper.add(vendor)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.parts_line(parts_line))


RECEIVE_SPEC = [
    F("received_qty", "integer", required=True),
    F("condition", "string", required=True, enum=CONDITIONS),
]


@bp.route("/parts-lines/<parts_line_id>/receive", methods=["POST"])
def receive_part(parts_line_id):
    auth.authenticate(("PartsManager",))
    data = validate.body(RECEIVE_SPEC)
    parts_line = _find_parts_line(parts_line_id)
    order = calc.parts_line_order(parts_line)
    guards.not_terminal(order)
    guards.parts_state_in(parts_line, ("ORDERED",))
    if not (0 < int(data["received_qty"]) <= int(parts_line["qty"])):
        raise_error("ERR_INVALID_RECEIVE_QUANTITY")

    bumper = calc.Bumper()
    received_at = db.now_iso()
    parts_line["procurement_status"] = "RECEIVED"
    parts_line["received_at"] = received_at
    parts_line["received_qty"] = int(data["received_qty"])
    promised = db.parse_iso(parts_line.get("promised_eta"))
    parts_line["on_time"] = True if promised is None else db.now() <= promised
    if data["condition"] == "CORRECT":
        guards.close_delay_events(parts_line, order, bumper)
    else:
        guards.open_delay_event(parts_line, order, "INCORRECT_PART")
    vendor = store.parts_vendors.get(parts_line.get("vendor_id"))
    if vendor is not None:
        calc.vendor_score(vendor)
        bumper.add(vendor)
    bumper.add(parts_line)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.parts_line(parts_line))


@bp.route("/parts-lines/<parts_line_id>/install", methods=["POST"])
def install_part(parts_line_id):
    auth.authenticate(("Technician",))
    validate.body([])
    parts_line = _find_parts_line(parts_line_id)
    order = calc.parts_line_order(parts_line)
    guards.not_terminal(order)
    guards.stage_in(order, INSTALL_STAGES)
    guards.parts_state_in(parts_line, ("RECEIVED",))
    surviving = int(parts_line.get("received_qty") or 0) - int(parts_line.get("returned_qty") or 0)
    if surviving < 1:
        raise_error("ERR_INVALID_RECEIVE_QUANTITY")

    bumper = calc.Bumper()
    parts_line["procurement_status"] = "INSTALLED"
    bumper.add(parts_line)
    bumper.flush()
    return response.ok(serialize.parts_line(parts_line))


RETURN_SPEC = [
    F("return_qty", "integer", required=True),
    F("return_reason", "string", required=True, enum=RETURN_REASONS),
]


@bp.route("/parts-lines/<parts_line_id>/return", methods=["POST"])
def return_part(parts_line_id):
    auth.authenticate(("PartsManager",))
    data = validate.body(RETURN_SPEC)
    parts_line = _find_parts_line(parts_line_id)
    order = calc.parts_line_order(parts_line)
    guards.not_terminal(order)
    guards.parts_state_in(parts_line, ("RECEIVED", "INSTALLED"))
    already = int(parts_line.get("returned_qty") or 0)
    room = int(parts_line.get("received_qty") or 0) - already
    return_qty = int(data["return_qty"])
    if not (0 < return_qty <= room):
        raise_error("ERR_INVALID_RETURN_QUANTITY")

    bumper = calc.Bumper()
    was_stage = order["stage"]
    vendor = store.parts_vendors.get(parts_line.get("vendor_id")) or {}
    full = return_qty == int(parts_line["qty"]) - already

    parts_line["returned_qty"] = already + return_qty
    parts_line["return_reason"] = data["return_reason"]
    parts_line["restocking_fee_cents"] = int(parts_line.get("restocking_fee_cents") or 0) \
        + calc.restocking_fee(parts_line, vendor, return_qty, data["return_reason"])
    parts_line["extended_price_cents"] = calc.parts_extended_price(parts_line)
    if full:
        parts_line["procurement_status"] = "RETURNED"

    # hop one, then hop two
    calc.commitment_ledger(order)
    calc.estimate_totals(order, bumper)
    calc.derive_posture(order)

    if data["return_reason"] == "INCORRECT":
        guards.open_delay_event(parts_line, order, "INCORRECT_PART")

    if was_stage in ("REFINISH_CALIBRATION", "READY_FOR_QC"):
        order["stage"] = "REPAIR"
        guards.release_assignments(order, ("ACTIVE",), "CANCELLED", bumper,
                                   stage="REFINISH_CALIBRATION")

    if parts_line.get("vendor_id") is not None and vendor:
        calc.vendor_score(vendor)
        bumper.add(vendor)
    bumper.add(parts_line)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.parts_line(parts_line))


# --- the late-parts sweep and the interruption log --------------------------------------
@bp.route("/repair-orders/<order_id>/parts-delay-sweep", methods=["POST"])
def parts_delay_sweep(order_id):
    auth.authenticate(("PartsManager",))
    validate.body([])
    order = guards.find_order(order_id)
    guards.not_terminal(order)

    bumper = calc.Bumper()
    now = db.now()
    opened = 0
    for parts_line in calc.order_parts_lines(order["id"]):
        if parts_line["procurement_status"] != "ORDERED":
            continue
        promised = db.parse_iso(parts_line.get("promised_eta"))
        if promised is None or promised >= now:
            continue
        if guards.has_open_delay(parts_line):
            continue
        guards.open_delay_event(parts_line, order, "ETA_BREACH")
        opened += 1
    if opened:
        bumper.add(order)
    bumper.flush()
    return response.ok({
        "opened_count": opened,
        "open_parts_delay_count": int(order.get("open_parts_delay_count") or 0),
    })


@bp.route("/repair-orders/<order_id>/parts-delay-events", methods=["GET"])
def list_order_delay_events(order_id):
    auth.authenticate(("ShopAdmin", "PartsManager"))
    limit, offset = response.read_pagination(request.args)
    order = guards.find_order(order_id)
    rows = calc.order_delay_events(order["id"])
    return response.paginate(rows, limit, offset, serialize.parts_delay_event)


@bp.route("/parts-lines/<parts_line_id>/parts-delay-events", methods=["GET"])
def list_parts_line_delay_events(parts_line_id):
    auth.authenticate(("ShopAdmin", "PartsManager"))
    limit, offset = response.read_pagination(request.args)
    parts_line = _find_parts_line(parts_line_id)
    rows = calc.children(store.parts_delay_events, "parts_line_id", parts_line["id"])
    return response.paginate(rows, limit, offset, serialize.parts_delay_event)
