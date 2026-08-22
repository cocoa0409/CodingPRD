"""Barges, cleaning orders, fleeting berths and fleeting assignments."""
from flask import Blueprint

import calc
from common import (ALL_ROLES, ApiError, apply_filters, authenticate, created,
                    f_bool, f_dt, f_enum, f_int, f_num, f_str, fetch, get_body,
                    make_record, ok, paged_response, pagination, sorted_rows,
                    store, touch)
from schema import (ser_barge, ser_berth, ser_cleaning, ser_fleeting)

bp = Blueprint("harbor", __name__)


# ---------------------------------------------------------------------------
# Barges
# ---------------------------------------------------------------------------
@bp.post("/barges")
def create_barge():
    authenticate(["WaterwayAdmin"])
    body = get_body()
    hull_number = f_str(body, "hull_number")
    capacity = f_int(body, "capacity_tons", gt=0)
    light_draft = f_num(body, "light_draft_feet", gt=0)
    tpi = f_num(body, "tons_per_inch_immersion", gt=0)
    cleanliness = f_enum(body, "cleanliness_status", calc.CLEANLINESS_STATUSES,
                         required=False, default="WASHED")
    last_cargo = f_str(body, "last_cargo_commodity_id", required=False)
    if last_cargo is not None:
        fetch(store.commodities, last_cargo, "ERR_COMMODITY_NOT_FOUND")
    for existing in store.barges.values():
        if existing["hull_number"] == hull_number:
            raise ApiError("ERR_DUPLICATE_HULL_NUMBER")
    rec = make_record({
        "hull_number": hull_number,
        "capacity_tons": capacity,
        "light_draft_feet": light_draft,
        "tons_per_inch_immersion": tpi,
        "operational_status": "IDLE",
        "cleanliness_status": cleanliness,
        "last_cargo_commodity_id": last_cargo,
        "last_cleaning_certificate_number": None,
    })
    store.barges[rec["id"]] = rec
    return created(ser_barge(rec))


@bp.get("/barges/<barge_id>")
def get_barge(barge_id):
    authenticate(ALL_ROLES)
    return ok(ser_barge(fetch(store.barges, barge_id, "ERR_BARGE_NOT_FOUND")))


@bp.get("/barges")
def list_barges():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.barges),
                         [("operational_status", "operational_status"),
                          ("cleanliness_status", "cleanliness_status"),
                          ("last_cargo_commodity_id", "last_cargo_commodity_id")])
    return paged_response(rows, ser_barge, limit, offset)


# ---------------------------------------------------------------------------
# Cleaning orders
# ---------------------------------------------------------------------------
@bp.post("/barges/<barge_id>/cleaning-orders")
def create_cleaning_order(barge_id):
    authenticate(["HarborAgent"])
    body = get_body()
    commodity_id = f_str(body, "required_for_commodity_id")
    contract_id = f_str(body, "freight_contract_id", required=False)
    barge = fetch(store.barges, barge_id, "ERR_BARGE_NOT_FOUND")
    commodity = fetch(store.commodities, commodity_id, "ERR_COMMODITY_NOT_FOUND")
    if contract_id is not None:
        fetch(store.freight_contracts, contract_id, "ERR_FREIGHT_CONTRACT_NOT_FOUND")
    level, _prohibited = calc.resolve_requirement(barge, commodity)
    rec = make_record({
        "barge_id": barge_id,
        "required_for_commodity_id": commodity_id,
        "freight_contract_id": contract_id,
        "required_cleaning_level": level,
        "performed_level": None,
        "inspection_passed": None,
        "certificate_number": None,
        "status": "ORDERED",
        "fee_cents": 0,
    })
    store.cleaning_orders[rec["id"]] = rec
    return created(ser_cleaning(rec))


@bp.post("/cleaning-orders/<cleaning_order_id>/start")
def start_cleaning(cleaning_order_id):
    authenticate(["HarborAgent"])
    order = fetch(store.cleaning_orders, cleaning_order_id,
                  "ERR_CLEANING_ORDER_NOT_FOUND")
    if order["status"] not in ("ORDERED", "FAILED_INSPECTION"):
        raise ApiError("ERR_CLEANING_ORDER_INVALID_STATE")
    barge = store.barges.get(order["barge_id"])
    if barge is not None and barge["operational_status"] not in ("IDLE", "OUT_OF_SERVICE"):
        raise ApiError("ERR_BARGE_NOT_AVAILABLE")
    order["status"] = "IN_PROGRESS"
    touch(order)
    return ok(ser_cleaning(order))


@bp.post("/cleaning-orders/<cleaning_order_id>/complete")
def complete_cleaning(cleaning_order_id):
    authenticate(["HarborAgent"])
    body = get_body()
    performed = f_enum(body, "performed_level", calc.CLEANING_LEVELS)
    certificate = f_str(body, "certificate_number")
    passed = f_bool(body, "inspection_passed")
    order = fetch(store.cleaning_orders, cleaning_order_id,
                  "ERR_CLEANING_ORDER_NOT_FOUND")
    if order["status"] != "IN_PROGRESS":
        raise ApiError("ERR_CLEANING_ORDER_INVALID_STATE")
    barge = store.barges.get(order["barge_id"])
    order["performed_level"] = performed
    order["certificate_number"] = certificate
    order["inspection_passed"] = passed
    if passed:
        order["status"] = "COMPLETED"
        order["fee_cents"] = calc.CLEANING_FEE_CENTS[performed]
        if barge is not None:
            barge["cleanliness_status"] = calc.CLEANLINESS_LEVEL_TO_STATUS[performed]
            barge["last_cleaning_certificate_number"] = certificate
            if barge["operational_status"] == "OUT_OF_SERVICE":
                barge["operational_status"] = "IDLE"
            touch(barge)
    else:
        order["status"] = "FAILED_INSPECTION"
        order["fee_cents"] = 0
        if barge is not None:
            if barge["operational_status"] == "IDLE":
                barge["operational_status"] = "OUT_OF_SERVICE"
            touch(barge)
    touch(order)
    return ok(ser_cleaning(order))


@bp.get("/cleaning-orders/<cleaning_order_id>")
def get_cleaning(cleaning_order_id):
    authenticate(ALL_ROLES)
    return ok(ser_cleaning(fetch(store.cleaning_orders, cleaning_order_id,
                                 "ERR_CLEANING_ORDER_NOT_FOUND")))


@bp.get("/cleaning-orders")
def list_cleaning():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.cleaning_orders),
                         [("barge_id", "barge_id"),
                          ("freight_contract_id", "freight_contract_id"),
                          ("required_for_commodity_id", "required_for_commodity_id"),
                          ("status", "status")])
    return paged_response(rows, ser_cleaning, limit, offset)


# ---------------------------------------------------------------------------
# Fleeting berths
# ---------------------------------------------------------------------------
@bp.post("/fleeting-berths")
def create_berth():
    authenticate(["WaterwayAdmin"])
    body = get_body()
    rec = make_record({
        "harbor_name": f_str(body, "harbor_name"),
        "river_mile": f_num(body, "river_mile"),
        "capacity_barges": f_int(body, "capacity_barges", gt=0),
        "daily_fee_cents_per_barge": f_int(body, "daily_fee_cents_per_barge", ge=0),
        "switch_fee_cents": f_int(body, "switch_fee_cents", ge=0),
        "occupied_barge_count": 0,
    })
    store.fleeting_berths[rec["id"]] = rec
    return created(ser_berth(rec))


@bp.get("/fleeting-berths/<fleeting_berth_id>")
def get_berth(fleeting_berth_id):
    authenticate(ALL_ROLES)
    return ok(ser_berth(fetch(store.fleeting_berths, fleeting_berth_id,
                              "ERR_FLEETING_BERTH_NOT_FOUND")))


@bp.get("/fleeting-berths")
def list_berths():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.fleeting_berths),
                         [("harbor_name", "harbor_name")])
    return paged_response(rows, ser_berth, limit, offset)


# ---------------------------------------------------------------------------
# Fleeting assignments
# ---------------------------------------------------------------------------
@bp.post("/fleeting-assignments")
def create_fleeting():
    authenticate(["HarborAgent"])
    body = get_body()
    barge_id = f_str(body, "barge_id")
    berth_id = f_str(body, "fleeting_berth_id")
    start_at = f_dt(body, "start_at")
    end_at = f_dt(body, "end_at")
    if not end_at > start_at:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'end_at' must be strictly later than 'start_at'.")
    contract_id = f_str(body, "freight_contract_id", required=False)
    barge = fetch(store.barges, barge_id, "ERR_BARGE_NOT_FOUND")
    berth = fetch(store.fleeting_berths, berth_id, "ERR_FLEETING_BERTH_NOT_FOUND")
    if contract_id is not None:
        fetch(store.freight_contracts, contract_id, "ERR_FREIGHT_CONTRACT_NOT_FOUND")
    if barge["operational_status"] != "IDLE":
        raise ApiError("ERR_BARGE_NOT_AVAILABLE")
    if not calc.berth_capacity_ok(berth, start_at, end_at):
        raise ApiError("ERR_BERTH_CAPACITY_EXCEEDED")
    rec = make_record({
        "barge_id": barge_id,
        "fleeting_berth_id": berth_id,
        "freight_contract_id": contract_id,
        "start_at": start_at,
        "end_at": end_at,
        "released_at": None,
        "status": "RESERVED",
        "estimated_fee_cents": calc.estimated_fee(berth, start_at, end_at),
        "billable_days": 0,
        "fee_cents": 0,
    })
    store.fleeting_assignments[rec["id"]] = rec
    berth["occupied_barge_count"] += 1
    touch(berth)
    barge["operational_status"] = "FLEETED"
    touch(barge)
    return created(ser_fleeting(rec))


@bp.post("/fleeting-assignments/<fleeting_assignment_id>/release")
def release_fleeting(fleeting_assignment_id):
    authenticate(["HarborAgent"])
    body = get_body()
    released_at = f_dt(body, "released_at")
    row = fetch(store.fleeting_assignments, fleeting_assignment_id,
                "ERR_FLEETING_ASSIGNMENT_NOT_FOUND")
    if row["status"] != "RESERVED":
        raise ApiError("ERR_FLEETING_ASSIGNMENT_INVALID_STATE")
    if released_at < row["start_at"]:
        raise ApiError("ERR_UNLOAD_SEQUENCE_INVALID")
    berth = store.fleeting_berths.get(row["fleeting_berth_id"])
    row["status"] = "RELEASED"
    row["released_at"] = released_at
    if berth is not None:
        days, fee = calc.release_fee(berth, row["start_at"], released_at)
        row["billable_days"] = days
        row["fee_cents"] = fee
        berth["occupied_barge_count"] = max(0, berth["occupied_barge_count"] - 1)
        touch(berth)
    touch(row)
    barge = store.barges.get(row["barge_id"])
    if barge is not None and barge["operational_status"] == "FLEETED":
        barge["operational_status"] = "IDLE"
        touch(barge)
    return ok(ser_fleeting(row))


@bp.post("/fleeting-assignments/<fleeting_assignment_id>/cancel")
def cancel_fleeting(fleeting_assignment_id):
    authenticate(["HarborAgent"])
    row = fetch(store.fleeting_assignments, fleeting_assignment_id,
                "ERR_FLEETING_ASSIGNMENT_NOT_FOUND")
    if row["status"] != "RESERVED":
        raise ApiError("ERR_FLEETING_ASSIGNMENT_INVALID_STATE")
    row["status"] = "CANCELLED"
    row["fee_cents"] = 0
    row["billable_days"] = 0
    touch(row)
    berth = store.fleeting_berths.get(row["fleeting_berth_id"])
    if berth is not None:
        berth["occupied_barge_count"] = max(0, berth["occupied_barge_count"] - 1)
        touch(berth)
    barge = store.barges.get(row["barge_id"])
    if barge is not None and barge["operational_status"] == "FLEETED":
        barge["operational_status"] = "IDLE"
        touch(barge)
    return ok(ser_fleeting(row))


@bp.get("/fleeting-assignments/<fleeting_assignment_id>")
def get_fleeting(fleeting_assignment_id):
    authenticate(ALL_ROLES)
    return ok(ser_fleeting(fetch(store.fleeting_assignments, fleeting_assignment_id,
                                 "ERR_FLEETING_ASSIGNMENT_NOT_FOUND")))


@bp.get("/fleeting-assignments")
def list_fleeting():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.fleeting_assignments),
                         [("barge_id", "barge_id"),
                          ("fleeting_berth_id", "fleeting_berth_id"),
                          ("freight_contract_id", "freight_contract_id"),
                          ("status", "status")])
    return paged_response(rows, ser_fleeting, limit, offset)
