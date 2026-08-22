"""Replenishment orders, order lines and substitution requests."""
from flask import Blueprint, g

from auth import ALL_ROLES, endpoint, scope_check
from db import by_creation, clock_now, iso_ms, new_entity, parse_iso, store, touch
from errors import ApiError
from response import ok, ok_list
from services import (
    COLD_CLASSES,
    COMMITTED_FULFILLMENT_STATUSES,
    CONTROLLED_CLASSES,
    CONTROLLED_MAX_UNITS_PER_ORDER,
    NON_TERMINAL_LINE_STATUSES,
    SUBSTITUTION_MAX_ROUNDS,
    allocate_order,
    apply_order_total,
    compute_line_amounts,
    compute_unit_price,
    formulary_for,
    lines_of_order,
    orders_on_route,
    recompute_route_counters,
    room_of_order,
)
from validation import (
    CLINICIAN_ACTIONS,
    FULFILLMENT_STATUSES,
    LINE_STATUSES,
    REQUESTER_ACTIONS,
    SETTLEMENT_STATUSES,
    SUBSTITUTION_STATUSES,
    get_body,
    opt_str,
    pagination,
    query_enum,
    query_str,
    req_enum,
    req_id,
    req_int,
    req_str,
)

bp = Blueprint("orders", __name__)


def _order_or_404(order_id):
    order = store.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", "Order %s does not exist." % order_id)
    return order


def _line_or_404(order_line_id):
    line = store.order_lines.get(order_line_id)
    if line is None:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND",
                       "Order line %s does not exist." % order_line_id)
    return line


def _request_or_404(substitution_request_id):
    req = store.substitution_requests.get(substitution_request_id)
    if req is None:
        raise ApiError("ERR_SUBSTITUTION_REQUEST_NOT_FOUND",
                       "Substitution request %s does not exist." % substitution_request_id)
    return req


# ---------------------------------------------------------------------------
# ReplenishmentOrder
# ---------------------------------------------------------------------------
@bp.route("/orders", methods=["POST"])
@endpoint(["MaterialsManager"])
def create_order():
    body = get_body()
    supply_room_id = req_id(body, "supply_room_id")

    if supply_room_id not in store.supply_rooms:
        raise ApiError("ERR_SUPPLY_ROOM_NOT_FOUND",
                       "Supply room %s does not exist." % supply_room_id)

    scope_check(supply_room_id)

    order = new_entity({
        "supply_room_id": supply_room_id,
        "route_id": None,
        "stop_arrival_min": None,
        "stop_service_minutes": None,
        "service_date": None,
        "fulfillment_status": "DRAFT",
        "settlement_status": "UNBILLED",
        "order_total_cents": 0,
        "submitted_at": None,
        "delivered_at": None,
    })
    store.orders[order["id"]] = order
    return ok(order, 201)


@bp.route("/orders/<order_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_order(order_id):
    return ok(_order_or_404(order_id))


@bp.route("/orders", methods=["GET"])
@endpoint(ALL_ROLES)
def list_orders():
    limit, offset = pagination()
    supply_room_id = query_str("supply_room_id")
    route_id = query_str("route_id")
    fulfillment_status = query_enum("fulfillment_status", FULFILLMENT_STATUSES)
    settlement_status = query_enum("settlement_status", SETTLEMENT_STATUSES)
    rows = []
    for order in store.orders.values():
        if supply_room_id is not None and order["supply_room_id"] != supply_room_id:
            continue
        if route_id is not None and order["route_id"] != route_id:
            continue
        if fulfillment_status is not None and order["fulfillment_status"] != fulfillment_status:
            continue
        if settlement_status is not None and order["settlement_status"] != settlement_status:
            continue
        rows.append(order)
    rows = by_creation(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.route("/orders/<order_id>/lines", methods=["POST"])
@endpoint(["MaterialsManager"])
def create_order_line(order_id):
    body = get_body()
    item_id = req_id(body, "item_id")
    requested_qty = req_int(body, "requested_qty", minimum=1)
    expected_order_version = req_int(body, "expected_order_version")

    order = _order_or_404(order_id)
    item = store.items.get(item_id)
    if item is None:
        raise ApiError("ERR_ITEM_NOT_FOUND", "Item %s does not exist." % item_id)

    scope_check(order["supply_room_id"])

    if expected_order_version != order["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_order_version %s does not match the current version %s."
                       % (expected_order_version, order["version"]))

    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT",
                       "Lines may only be written onto a DRAFT order.")

    room = room_of_order(order)
    mapping = formulary_for(order["supply_room_id"], item_id)
    if mapping is None or mapping["formulary_status"] != "APPROVED":
        raise ApiError("ERR_ITEM_NOT_ON_FORMULARY",
                       "Item %s is not APPROVED on this room's formulary." % item_id)

    unit_price, contract_line = compute_unit_price(item, room, clock_now(), mapping)

    line = new_entity({
        "order_id": order_id,
        "item_id": item_id,
        "lot_id": None,
        "pinned_contract_line_id": contract_line["id"],
        "requested_qty": requested_qty,
        "allocated_qty": 0,
        "pinned_unit_price_cents": unit_price,
        "settled_unit_price_cents": None,
        "extended_price_cents": 0,
        "line_fee_cents": 0,
        "chargeback_eligible": bool(contract_line["chargeback_eligible"]),
        "line_status": "OPEN",
    })
    extended, fee = compute_line_amounts(line)
    line["extended_price_cents"] = extended
    line["line_fee_cents"] = fee
    store.order_lines[line["id"]] = line

    apply_order_total(order)
    touch(order)
    return ok(line, 201)


@bp.route("/orders/<order_id>/submit", methods=["POST"])
@endpoint(["MaterialsManager"])
def submit_order(order_id):
    order = _order_or_404(order_id)
    scope_check(order["supply_room_id"])

    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT",
                       "Only a DRAFT order may be submitted.")

    lines = lines_of_order(order)
    open_lines = [ln for ln in lines if ln["line_status"] == "OPEN"]
    if not open_lines:
        raise ApiError("ERR_ORDER_NOT_DRAFT",
                       "The order carries no OPEN line to submit.")

    room = room_of_order(order)
    non_terminal = [ln for ln in lines if ln["line_status"] in NON_TERMINAL_LINE_STATUSES]

    # gate 10 - controlled-item room eligibility
    for line in non_terminal:
        item = store.items.get(line["item_id"])
        if item is None:
            continue
        if item["handling_class"] in CONTROLLED_CLASSES:
            if not (room["controlled_secured"] and room["controlled_license_status"] == "ACTIVE"):
                raise ApiError("ERR_CONTROLLED_HANDLING_NOT_PERMITTED",
                               "The destination room may not receive controlled items.")

    # gate 11 - cold-chain room eligibility
    for line in non_terminal:
        item = store.items.get(line["item_id"])
        if item is None:
            continue
        if item["handling_class"] in COLD_CLASSES:
            if not room["refrigerated"]:
                raise ApiError("ERR_COLD_CHAIN_ROOM_REQUIRED",
                               "The destination room is not refrigerated.")

    # gate 15 - formulary standing
    for line in open_lines:
        mapping = formulary_for(order["supply_room_id"], line["item_id"])
        if mapping is None or mapping["formulary_status"] != "APPROVED":
            raise ApiError("ERR_ITEM_NOT_ON_FORMULARY",
                           "Item %s is no longer APPROVED on this room's formulary."
                           % line["item_id"])

    # gate 21 - controlled-substance quantity ceiling
    controlled_units = 0
    for line in non_terminal:
        item = store.items.get(line["item_id"])
        if item is not None and item["handling_class"] in CONTROLLED_CLASSES:
            controlled_units += line["requested_qty"]
    if controlled_units > CONTROLLED_MAX_UNITS_PER_ORDER:
        raise ApiError("ERR_CONTROLLED_QTY_LIMIT_EXCEEDED",
                       "Controlled units on this order exceed %d."
                       % CONTROLLED_MAX_UNITS_PER_ORDER)

    # gate 24 - room credit limit
    if room["open_commitment_cents"] + order["order_total_cents"] > room["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                       "Submitting this order would exceed the room's credit limit.")

    order["fulfillment_status"] = "SUBMITTED"
    order["submitted_at"] = iso_ms(clock_now())
    touch(order)
    room["open_commitment_cents"] = room["open_commitment_cents"] + order["order_total_cents"]
    touch(room)
    return ok(order)


@bp.route("/orders/<order_id>/allocate", methods=["POST"])
@endpoint(["DistributionOperator"])
def allocate(order_id):
    order = _order_or_404(order_id)
    if order["fulfillment_status"] not in ("SUBMITTED", "HELD"):
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "Only a SUBMITTED or HELD order may be picked.")

    allocated_any = allocate_order(order)
    if allocated_any:
        if order["fulfillment_status"] != "ALLOCATED":
            order["fulfillment_status"] = "ALLOCATED"
            touch(order)
    elif order["fulfillment_status"] == "SUBMITTED":
        order["fulfillment_status"] = "HELD"
        touch(order)

    apply_order_total(order)
    return ok(order)


@bp.route("/orders/<order_id>/deliver", methods=["POST"])
@endpoint(["DistributionOperator"])
def deliver(order_id):
    order = _order_or_404(order_id)
    if order["fulfillment_status"] != "IN_TRANSIT":
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "Only an IN_TRANSIT order may be delivered.")

    now = clock_now()
    lines = [ln for ln in lines_of_order(order) if ln["line_status"] == "ALLOCATED"]

    # rule 12 - lot still allocatable
    for line in lines:
        lot = store.lots.get(line["lot_id"]) if line["lot_id"] else None
        if lot is None or lot["status"] != "AVAILABLE":
            raise ApiError("ERR_LOT_NOT_ALLOCATABLE",
                           "The lot backing line %s is no longer AVAILABLE." % line["id"])

    # rule 13 - lot not expired
    for line in lines:
        lot = store.lots.get(line["lot_id"])
        expiry = parse_iso(lot["expiry_date"])
        if not (expiry > now):
            raise ApiError("ERR_LOT_EXPIRED",
                           "The lot backing line %s has expired." % line["id"])

    # rule 16 - settlement reprice must resolve for every line
    room = room_of_order(order)
    settled_prices = {}
    for line in lines:
        item = store.items.get(line["item_id"])
        mapping = formulary_for(order["supply_room_id"], line["item_id"])
        price, _cl = compute_unit_price(item, room, now, mapping)
        settled_prices[line["id"]] = price

    for line in lines:
        line["settled_unit_price_cents"] = settled_prices[line["id"]]
        line["line_status"] = "DELIVERED"
        touch(line)

    apply_order_total(order)

    order["fulfillment_status"] = "DELIVERED"
    order["delivered_at"] = iso_ms(now)
    touch(order)

    if room is not None:
        room["open_commitment_cents"] = room["open_commitment_cents"] - order["order_total_cents"]
        touch(room)

    for line in lines:
        item = store.items.get(line["item_id"])
        mapping = formulary_for(order["supply_room_id"], line["item_id"])
        if mapping is None or item is None:
            continue
        multiplier = item["units_per_parent"] if item["uom"] == "CS" else 1
        mapping["on_hand_qty"] = mapping["on_hand_qty"] + line["allocated_qty"] * multiplier
        touch(mapping)

    route_id = order.get("route_id")
    if route_id:
        route = store.routes.get(route_id)
        if route is not None and route["status"] == "DISPATCHED":
            assigned = orders_on_route(route_id)
            if assigned and all(o["fulfillment_status"] == "DELIVERED" for o in assigned):
                route["status"] = "COMPLETED"
                touch(route)

    return ok(order)


# ---------------------------------------------------------------------------
# OrderLine
# ---------------------------------------------------------------------------
@bp.route("/order-lines/<order_line_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_order_line(order_line_id):
    return ok(_line_or_404(order_line_id))


@bp.route("/order-lines", methods=["GET"])
@endpoint(ALL_ROLES)
def list_order_lines():
    limit, offset = pagination()
    order_id = query_str("order_id")
    item_id = query_str("item_id")
    lot_id = query_str("lot_id")
    pinned_contract_line_id = query_str("pinned_contract_line_id")
    line_status = query_enum("line_status", LINE_STATUSES)
    rows = []
    for line in store.order_lines.values():
        if order_id is not None and line["order_id"] != order_id:
            continue
        if item_id is not None and line["item_id"] != item_id:
            continue
        if lot_id is not None and line["lot_id"] != lot_id:
            continue
        if pinned_contract_line_id is not None and line["pinned_contract_line_id"] != pinned_contract_line_id:
            continue
        if line_status is not None and line["line_status"] != line_status:
            continue
        rows.append(line)
    rows = by_creation(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, len(rows))


# ---------------------------------------------------------------------------
# SubstitutionRequest
# ---------------------------------------------------------------------------
@bp.route("/order-lines/<order_line_id>/substitution-requests", methods=["POST"])
@endpoint(["MaterialsManager"])
def create_substitution_request(order_line_id):
    body = get_body()
    proposed_item_id = req_id(body, "proposed_item_id")
    justification = req_str(body, "justification")

    line = _line_or_404(order_line_id)
    if proposed_item_id not in store.items:
        raise ApiError("ERR_ITEM_NOT_FOUND", "Item %s does not exist." % proposed_item_id)

    order = store.orders.get(line["order_id"])
    scope_check(order["supply_room_id"] if order else None)

    if line["line_status"] not in ("OPEN", "BACKORDERED"):
        raise ApiError("ERR_ORDER_LINE_STATE_INVALID",
                       "A substitution request needs an OPEN or BACKORDERED line.")

    request_row = new_entity({
        "order_line_id": order_line_id,
        "proposed_item_id": proposed_item_id,
        "requested_by_user_id": g.user_id,
        "clinician_user_id": None,
        "justification": justification,
        "info_request_note": None,
        "response_note": None,
        "rounds_used": 0,
        "status": "PENDING",
        "price_delta_cents": None,
    })
    store.substitution_requests[request_row["id"]] = request_row
    return ok(request_row, 201)


@bp.route("/substitution-requests/<substitution_request_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_substitution_request(substitution_request_id):
    return ok(_request_or_404(substitution_request_id))


@bp.route("/substitution-requests", methods=["GET"])
@endpoint(ALL_ROLES)
def list_substitution_requests():
    limit, offset = pagination()
    order_line_id = query_str("order_line_id")
    proposed_item_id = query_str("proposed_item_id")
    status = query_enum("status", SUBSTITUTION_STATUSES)
    rows = []
    for row in store.substitution_requests.values():
        if order_line_id is not None and row["order_line_id"] != order_line_id:
            continue
        if proposed_item_id is not None and row["proposed_item_id"] != proposed_item_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = by_creation(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.route("/substitution-requests/<substitution_request_id>/clinician-action", methods=["POST"])
@endpoint(["Clinician"])
def clinician_action(substitution_request_id):
    body = get_body()
    action = req_enum(body, "action", CLINICIAN_ACTIONS)
    note = opt_str(body, "note", None)

    request_row = _request_or_404(substitution_request_id)
    line = store.order_lines.get(request_row["order_line_id"])
    order = store.orders.get(line["order_id"]) if line else None
    room = room_of_order(order) if order else None

    status = request_row["status"]

    if action == "REQUEST_INFO":
        if status != "PENDING":
            raise ApiError("ERR_SUBSTITUTION_STATE_INVALID",
                           "REQUEST_INFO is only permitted from PENDING.")
        if request_row["rounds_used"] >= SUBSTITUTION_MAX_ROUNDS:
            raise ApiError("ERR_SUBSTITUTION_ROUNDS_EXHAUSTED",
                           "The information-request round budget is exhausted.")
        request_row["status"] = "INFO_REQUESTED"
        request_row["info_request_note"] = note
        request_row["clinician_user_id"] = g.user_id
        touch(request_row)
        return ok(request_row)

    if action == "REJECT":
        if status not in ("PENDING", "INFO_REQUESTED"):
            raise ApiError("ERR_SUBSTITUTION_STATE_INVALID",
                           "REJECT is only permitted from PENDING or INFO_REQUESTED.")
        request_row["status"] = "REJECTED"
        request_row["clinician_user_id"] = g.user_id
        touch(request_row)
        if line is not None and line["line_status"] == "BACKORDERED":
            line["line_status"] = "SHORTED"
            touch(line)
            if order is not None:
                apply_order_total(order)
        return ok(request_row)

    # APPROVE
    if status != "PENDING":
        raise ApiError("ERR_SUBSTITUTION_STATE_INVALID",
                       "APPROVE is only permitted from PENDING.")
    if line is None or line["line_status"] != "BACKORDERED":
        raise ApiError("ERR_ORDER_LINE_STATE_INVALID",
                       "An approval requires a BACKORDERED order line.")

    proposed_item = store.items.get(request_row["proposed_item_id"])

    # rule 10 - controlled-item room eligibility
    if proposed_item is not None and proposed_item["handling_class"] in CONTROLLED_CLASSES:
        if not (room["controlled_secured"] and room["controlled_license_status"] == "ACTIVE"):
            raise ApiError("ERR_CONTROLLED_HANDLING_NOT_PERMITTED",
                           "The destination room may not receive controlled items.")

    # rule 11 - cold-chain room eligibility
    if proposed_item is not None and proposed_item["handling_class"] in COLD_CLASSES:
        if not room["refrigerated"]:
            raise ApiError("ERR_COLD_CHAIN_ROOM_REQUIRED",
                           "The destination room is not refrigerated.")

    # rule 15 - formulary standing of the proposed item
    mapping = formulary_for(order["supply_room_id"], request_row["proposed_item_id"])
    if mapping is None or mapping["formulary_status"] != "APPROVED":
        raise ApiError("ERR_ITEM_NOT_ON_FORMULARY",
                       "The proposed item is not APPROVED on this room's formulary.")

    # rule 16 - an active contract must price the proposed item
    unit_price, contract_line = compute_unit_price(
        proposed_item, room, clock_now(), mapping)

    previous_price = line["pinned_unit_price_cents"]
    request_row["status"] = "APPROVED"
    request_row["clinician_user_id"] = g.user_id
    request_row["price_delta_cents"] = unit_price - previous_price
    touch(request_row)

    line["item_id"] = request_row["proposed_item_id"]
    line["pinned_contract_line_id"] = contract_line["id"]
    line["pinned_unit_price_cents"] = unit_price
    line["chargeback_eligible"] = bool(contract_line["chargeback_eligible"])
    line["line_status"] = "SUBSTITUTED"
    touch(line)

    apply_order_total(order)
    return ok(request_row)


@bp.route("/substitution-requests/<substitution_request_id>/respond", methods=["POST"])
@endpoint(["MaterialsManager"])
def respond_substitution_request(substitution_request_id):
    body = get_body()
    action = req_enum(body, "action", REQUESTER_ACTIONS)
    response_note = opt_str(body, "response_note", None)

    request_row = _request_or_404(substitution_request_id)
    line = store.order_lines.get(request_row["order_line_id"])
    order = store.orders.get(line["order_id"]) if line else None
    scope_check(order["supply_room_id"] if order else None)

    status = request_row["status"]

    if action == "RESPOND":
        if status != "INFO_REQUESTED":
            raise ApiError("ERR_SUBSTITUTION_STATE_INVALID",
                           "RESPOND is only permitted from INFO_REQUESTED.")
        request_row["status"] = "PENDING"
        request_row["response_note"] = response_note
        request_row["rounds_used"] = request_row["rounds_used"] + 1
        touch(request_row)
        return ok(request_row)

    # WITHDRAW
    if status not in ("PENDING", "INFO_REQUESTED"):
        raise ApiError("ERR_SUBSTITUTION_STATE_INVALID",
                       "WITHDRAW is only permitted from PENDING or INFO_REQUESTED.")
    request_row["status"] = "WITHDRAWN"
    touch(request_row)

    if line is not None and line["line_status"] == "OPEN":
        line["line_status"] = "CANCELLED"
        line["extended_price_cents"] = 0
        line["line_fee_cents"] = 0
        touch(line)
        if order is not None:
            apply_order_total(order)
            lines = lines_of_order(order)
            if (order["fulfillment_status"] == "DRAFT" and lines and
                    all(ln["line_status"] == "CANCELLED" for ln in lines)):
                order["fulfillment_status"] = "CANCELLED"
                if order["order_total_cents"] != 0:
                    order["order_total_cents"] = 0
                touch(order)
    return ok(request_row)
