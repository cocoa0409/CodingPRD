"""Recall notices, delivery routes, chargeback claims and the logical clock."""
from flask import Blueprint, g

from auth import ALL_ROLES, endpoint
from db import (
    by_creation,
    clock_now,
    iso_ms,
    new_entity,
    parse_iso,
    store,
    touch,
)
from errors import ApiError, validation_error
from response import ok, ok_list
from services import (
    ROOM_TURNOVER_BUFFER_MIN,
    ROUTE_LOAD_FULFILLMENT_STATUSES,
    cascade_recall,
    claims_of_order,
    compute_settlement,
    order_cold_units,
    orders_on_route,
    recompute_route_counters,
    route_cold_capacity,
    route_counters,
)
from validation import (
    CLAIM_OUTCOMES,
    CLAIM_SETTLE_ACTIONS,
    CLAIM_STATUSES,
    RECALL_ACTIONS,
    RECALL_CLASSES,
    RECALL_STATUSES,
    ROUTE_STATUSES,
    VEHICLE_CLASSES,
    get_body,
    opt_id,
    opt_str,
    pagination,
    query_enum,
    query_str,
    req_date,
    req_enum,
    req_id,
    req_int,
    req_str,
)

bp = Blueprint("logistics", __name__)


# ---------------------------------------------------------------------------
# RecallNotice
# ---------------------------------------------------------------------------
@bp.route("/recall-notices", methods=["POST"])
@endpoint(["ContractAdmin"])
def create_recall_notice():
    body = get_body()
    item_id = req_id(body, "item_id")
    recall_class = req_enum(body, "recall_class", RECALL_CLASSES)
    reason = req_str(body, "reason", allow_empty=True)
    lot_id = opt_id(body, "lot_id", None)

    if item_id not in store.items:
        raise ApiError("ERR_ITEM_NOT_FOUND", "Item %s does not exist." % item_id)
    if lot_id is not None and lot_id not in store.lots:
        raise ApiError("ERR_LOT_NOT_FOUND", "Lot %s does not exist." % lot_id)

    notice = new_entity({
        "item_id": item_id,
        "lot_id": lot_id,
        "recall_class": recall_class,
        "reason": reason,
        "status": "ISSUED",
        "quarantined_lot_count": 0,
        "backordered_line_count": 0,
        "cascaded_at": None,
    })
    store.recall_notices[notice["id"]] = notice
    return ok(notice, 201)


@bp.route("/recall-notices/<recall_notice_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_recall_notice(recall_notice_id):
    notice = store.recall_notices.get(recall_notice_id)
    if notice is None:
        raise ApiError("ERR_RECALL_NOTICE_NOT_FOUND",
                       "Recall notice %s does not exist." % recall_notice_id)
    return ok(notice)


@bp.route("/recall-notices", methods=["GET"])
@endpoint(ALL_ROLES)
def list_recall_notices():
    limit, offset = pagination()
    item_id = query_str("item_id")
    lot_id = query_str("lot_id")
    status = query_enum("status", RECALL_STATUSES)
    rows = []
    for notice in store.recall_notices.values():
        if item_id is not None and notice["item_id"] != item_id:
            continue
        if lot_id is not None and notice["lot_id"] != lot_id:
            continue
        if status is not None and notice["status"] != status:
            continue
        rows.append(notice)
    rows = by_creation(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.route("/recall-notices/<recall_notice_id>/cascade", methods=["POST"])
@endpoint(["DistributionOperator"])
def cascade_recall_notice(recall_notice_id):
    body = get_body()
    action = req_enum(body, "action", RECALL_ACTIONS)

    notice = store.recall_notices.get(recall_notice_id)
    if notice is None:
        raise ApiError("ERR_RECALL_NOTICE_NOT_FOUND",
                       "Recall notice %s does not exist." % recall_notice_id)

    if action == "CASCADE":
        if notice["status"] != "ISSUED":
            raise ApiError("ERR_RECALL_STATE_INVALID",
                           "Only an ISSUED notice may be cascaded.")
        cascade_recall(notice)
        notice["status"] = "CASCADED"
        notice["cascaded_at"] = iso_ms(clock_now())
        touch(notice)
        return ok(notice)

    if notice["status"] != "CASCADED":
        raise ApiError("ERR_RECALL_STATE_INVALID",
                       "Only a CASCADED notice may be closed.")
    notice["status"] = "CLOSED"
    touch(notice)
    return ok(notice)


# ---------------------------------------------------------------------------
# DeliveryRoute
# ---------------------------------------------------------------------------
@bp.route("/delivery-routes", methods=["POST"])
@endpoint(["DistributionOperator"])
def create_route():
    body = get_body()
    route_code = req_str(body, "route_code")
    service_date = req_date(body, "service_date")
    vehicle_class = req_enum(body, "vehicle_class", VEHICLE_CLASSES)

    for existing in store.routes.values():
        if existing["route_code"] == route_code:
            raise ApiError("ERR_DUPLICATE_ROUTE_CODE",
                           "route_code '%s' already exists." % route_code)

    route = new_entity({
        "route_code": route_code,
        "service_date": service_date,
        "vehicle_class": vehicle_class,
        "planned_order_count": 0,
        "cold_units_loaded": 0,
        "status": "PLANNED",
        "dispatched_at": None,
    })
    store.routes[route["id"]] = route
    return ok(route, 201)


@bp.route("/delivery-routes/<route_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_route(route_id):
    route = store.routes.get(route_id)
    if route is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND", "Route %s does not exist." % route_id)
    return ok(route)


@bp.route("/delivery-routes", methods=["GET"])
@endpoint(ALL_ROLES)
def list_routes():
    limit, offset = pagination()
    status = query_enum("status", ROUTE_STATUSES)
    service_date = query_str("service_date")
    rows = []
    for route in store.routes.values():
        if status is not None and route["status"] != status:
            continue
        if service_date is not None and route["service_date"] != service_date:
            continue
        rows.append(route)
    rows = by_creation(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.route("/delivery-routes/<route_id>/stops", methods=["POST"])
@endpoint(["DistributionOperator"])
def add_route_stop(route_id):
    body = get_body()
    order_id = req_id(body, "order_id")
    arrival_min = req_int(body, "arrival_min", minimum=0, maximum=1439)
    service_minutes = req_int(body, "service_minutes", minimum=1)

    route = store.routes.get(route_id)
    if route is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND", "Route %s does not exist." % route_id)
    order = store.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", "Order %s does not exist." % order_id)

    if route["status"] != "PLANNED":
        raise ApiError("ERR_ROUTE_STATE_INVALID",
                       "Stops may only be added to a PLANNED route.")
    if order["fulfillment_status"] != "ALLOCATED":
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "Only an ALLOCATED order may be added to a route.")

    room = store.supply_rooms.get(order["supply_room_id"])

    # rule 18 - stop-to-stop separation at the destination room
    for other in store.orders.values():
        if other["id"] == order_id:
            continue
        other_route_id = other.get("route_id")
        if not other_route_id:
            continue
        if other["supply_room_id"] != order["supply_room_id"]:
            continue
        if other.get("service_date") != route["service_date"]:
            continue
        other_route = store.routes.get(other_route_id)
        if other_route is None or other_route["status"] not in ("PLANNED", "DISPATCHED"):
            continue
        other_arrival = other.get("stop_arrival_min")
        other_service = other.get("stop_service_minutes")
        if other_arrival is None or other_service is None:
            continue
        if (arrival_min < other_arrival + other_service + ROOM_TURNOVER_BUFFER_MIN and
                other_arrival < arrival_min + service_minutes + ROOM_TURNOVER_BUFFER_MIN):
            raise ApiError("ERR_ROOM_WINDOW_CONFLICT",
                           "The proposed stop collides with an existing stop at this room.")

    # rule 19 - the room's receiving window
    if room is not None:
        if arrival_min < room["window_open_min"] or \
                arrival_min + service_minutes > room["window_close_min"]:
            raise ApiError("ERR_STOP_OUTSIDE_ROOM_WINDOW",
                           "The stop lies outside the room's receiving window.")

    # rule 20 - aggregate cold-chain payload ceiling
    _count, current_cold = route_counters(route_id, exclude_order_id=order_id)
    incoming_cold = order_cold_units(order)
    if current_cold + incoming_cold > route_cold_capacity(route):
        raise ApiError("ERR_ROUTE_COLD_CAPACITY_EXCEEDED",
                       "The route's cold-chain capacity would be exceeded.")

    order["route_id"] = route_id
    order["stop_arrival_min"] = arrival_min
    order["stop_service_minutes"] = service_minutes
    order["service_date"] = route["service_date"]
    touch(order)
    recompute_route_counters(route)
    return ok(order)


@bp.route("/delivery-routes/<route_id>/dispatch", methods=["POST"])
@endpoint(["DistributionOperator"])
def dispatch_route(route_id):
    route = store.routes.get(route_id)
    if route is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND", "Route %s does not exist." % route_id)

    if route["status"] != "PLANNED":
        raise ApiError("ERR_ROUTE_STATE_INVALID",
                       "Only a PLANNED route may be dispatched.")
    assigned = orders_on_route(route_id)
    if not assigned:
        raise ApiError("ERR_ROUTE_STATE_INVALID",
                       "A route with no assigned order cannot be dispatched.")
    for order in assigned:
        if order["fulfillment_status"] != "ALLOCATED":
            raise ApiError("ERR_ROUTE_STATE_INVALID",
                           "Every assigned order must be ALLOCATED before dispatch.")

    route["status"] = "DISPATCHED"
    route["dispatched_at"] = iso_ms(clock_now())
    touch(route)
    for order in assigned:
        order["fulfillment_status"] = "IN_TRANSIT"
        touch(order)
    return ok(route)


# ---------------------------------------------------------------------------
# ChargebackClaim
# ---------------------------------------------------------------------------
@bp.route("/chargeback-claims", methods=["POST"])
@endpoint(["ContractAdmin"])
def create_claim():
    body = get_body()
    order_id = req_id(body, "order_id")
    contract_id = req_id(body, "contract_id")

    order = store.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", "Order %s does not exist." % order_id)
    contract = store.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND",
                       "Contract %s does not exist." % contract_id)

    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "Only a DELIVERED order may be claimed.")

    for existing in claims_of_order(order_id):
        if existing["status"] != "DISPUTED":
            raise ApiError("ERR_CLAIM_ALREADY_OPEN",
                           "The order already carries a claim that is not DISPUTED.")

    figures = compute_settlement(order)

    claim = new_entity({
        "order_id": order_id,
        "contract_id": contract_id,
        "submitted_by_user_id": g.user_id,
        "reconciled_by_user_id": None,
        "gross_chargeback_cents": figures["gross_chargeback_cents"],
        "admin_fee_pct": figures["admin_fee_pct"],
        "admin_fee_cents": figures["admin_fee_cents"],
        "net_chargeback_cents": figures["net_chargeback_cents"],
        "eligible_line_count": figures["eligible_line_count"],
        "status": "SUBMITTED",
        "dispute_reason": None,
    })
    store.claims[claim["id"]] = claim

    contract["chargeback_payable_cents"] = (
        contract["chargeback_payable_cents"] + claim["net_chargeback_cents"])
    touch(contract)

    order["settlement_status"] = "CLAIMED"
    touch(order)
    return ok(claim, 201)


@bp.route("/chargeback-claims/<chargeback_claim_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_claim(chargeback_claim_id):
    claim = store.claims.get(chargeback_claim_id)
    if claim is None:
        raise ApiError("ERR_CHARGEBACK_CLAIM_NOT_FOUND",
                       "Chargeback claim %s does not exist." % chargeback_claim_id)
    return ok(claim)


@bp.route("/chargeback-claims", methods=["GET"])
@endpoint(ALL_ROLES)
def list_claims():
    limit, offset = pagination()
    order_id = query_str("order_id")
    contract_id = query_str("contract_id")
    status = query_enum("status", CLAIM_STATUSES)
    rows = []
    for claim in store.claims.values():
        if order_id is not None and claim["order_id"] != order_id:
            continue
        if contract_id is not None and claim["contract_id"] != contract_id:
            continue
        if status is not None and claim["status"] != status:
            continue
        rows.append(claim)
    rows = by_creation(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.route("/chargeback-claims/<chargeback_claim_id>/response", methods=["POST"])
@endpoint(["ManufacturerRep"])
def respond_claim(chargeback_claim_id):
    body = get_body()
    outcome = req_enum(body, "outcome", CLAIM_OUTCOMES)
    dispute_reason = opt_str(body, "dispute_reason", None)

    claim = store.claims.get(chargeback_claim_id)
    if claim is None:
        raise ApiError("ERR_CHARGEBACK_CLAIM_NOT_FOUND",
                       "Chargeback claim %s does not exist." % chargeback_claim_id)

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_STATE_INVALID",
                       "Only a SUBMITTED claim may be responded to.")

    order = store.orders.get(claim["order_id"])
    contract = store.contracts.get(claim["contract_id"])

    if outcome == "ACCEPT":
        claim["status"] = "ACCEPTED"
        touch(claim)
        return ok(claim)

    claim["status"] = "DISPUTED"
    claim["dispute_reason"] = dispute_reason
    touch(claim)
    if contract is not None:
        contract["chargeback_payable_cents"] = (
            contract["chargeback_payable_cents"] - claim["net_chargeback_cents"])
        touch(contract)
    if order is not None and order["settlement_status"] == "CLAIMED":
        order["settlement_status"] = "UNBILLED"
        touch(order)
    return ok(claim)


@bp.route("/chargeback-claims/<chargeback_claim_id>/settle", methods=["POST"])
@endpoint(["ContractAdmin"])
def settle_claim(chargeback_claim_id):
    body = get_body()
    action = req_enum(body, "action", CLAIM_SETTLE_ACTIONS)

    claim = store.claims.get(chargeback_claim_id)
    if claim is None:
        raise ApiError("ERR_CHARGEBACK_CLAIM_NOT_FOUND",
                       "Chargeback claim %s does not exist." % chargeback_claim_id)

    order = store.orders.get(claim["order_id"])
    contract = store.contracts.get(claim["contract_id"])

    if action == "RECONCILE":
        if claim["status"] != "ACCEPTED":
            raise ApiError("ERR_CLAIM_STATE_INVALID",
                           "Only an ACCEPTED claim may be reconciled.")
        if str(claim["submitted_by_user_id"]) == str(g.user_id):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The administrator who submitted the claim may not reconcile it.")
        claim["status"] = "RECONCILED"
        claim["reconciled_by_user_id"] = g.user_id
        touch(claim)
        if order is not None and order["settlement_status"] == "CLAIMED":
            order["settlement_status"] = "RECONCILED"
            touch(order)
        return ok(claim)

    # RESUBMIT
    if claim["status"] not in ("DISPUTED", "REBILL_REQUIRED"):
        raise ApiError("ERR_CLAIM_STATE_INVALID",
                       "Only a DISPUTED or REBILL_REQUIRED claim may be resubmitted.")
    if order is None:
        raise ApiError("ERR_NO_CHARGEBACK_ELIGIBLE_LINES",
                       "The claimed order no longer exists.")

    previous_status = claim["status"]
    figures = compute_settlement(order)
    claim["gross_chargeback_cents"] = figures["gross_chargeback_cents"]
    claim["admin_fee_pct"] = figures["admin_fee_pct"]
    claim["admin_fee_cents"] = figures["admin_fee_cents"]
    claim["net_chargeback_cents"] = figures["net_chargeback_cents"]
    claim["eligible_line_count"] = figures["eligible_line_count"]
    claim["status"] = "SUBMITTED"
    touch(claim)

    if contract is not None:
        contract["chargeback_payable_cents"] = (
            contract["chargeback_payable_cents"] + claim["net_chargeback_cents"])
        touch(contract)

    if previous_status == "DISPUTED":
        if order["settlement_status"] == "UNBILLED":
            order["settlement_status"] = "CLAIMED"
            touch(order)
    else:
        if order["settlement_status"] == "REBILL_REQUIRED":
            order["settlement_status"] = "CLAIMED"
            touch(order)
    return ok(claim)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["ContractAdmin"])
def set_clock():
    body = get_body()
    raw = req_str(body, "to_iso8601")
    try:
        parsed = parse_iso(raw)
    except Exception:
        raise validation_error("'to_iso8601' must be an ISO 8601 datetime.")
    store.clock = parsed
    return ok({"current_utc": raw})
