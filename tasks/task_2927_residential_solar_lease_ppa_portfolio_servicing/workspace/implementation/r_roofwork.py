"""Roof work orders: removal, roofing and reinstallation (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint

import calc
from calc import MAX_ROOF_WORK_ORDERS_PER_YEAR, MAX_ROOF_WORK_SPAN_DAYS, ROOF_WORK_BUFFER_DAYS
from core import ApiError, clock, fmt_date, parse_date, sorted_rows, stamp_new, store, touch
from guards import (
    homeowner_agreement_ids, homeowner_scope, lookup, require_child_write_allowed,
    require_not_decommissioned,
)
from serialize import roof_work_order_view
from web import (
    apply_filters, authenticate, created, filters, ok, ok_list, paginate,
    pagination, validate_body,
)

bp = Blueprint("roof_work_routes", __name__)

ROOF_STATUSES = ("REQUESTED", "QUOTED", "APPROVED", "PANELS_REMOVED",
                 "ROOF_COMPLETE", "REINSTALLED", "CANCELLED")
BLOCKING_STATUSES = ("APPROVED", "PANELS_REMOVED", "ROOF_COMPLETE")
COUNTED_STATUSES = ("APPROVED", "PANELS_REMOVED", "ROOF_COMPLETE", "REINSTALLED")

ROOF_SPECS = [
    {"name": "agreement_id", "kind": "id", "required": True},
    {"name": "requested_removal_date", "kind": "date", "required": True},
    {"name": "reinstall_target_date", "kind": "date", "required": True},
    {"name": "roofer_company", "kind": "str", "required": True, "minlen": 1,
     "maxlen": 80, "nonblank": True},
]


def bad_dates(message):
    return ApiError("ERR_ROOF_DATES_INVALID", message)


@bp.post("/servicing/roof-work-orders")
def create_roof_work_order():
    user_id, role = authenticate(("Homeowner", "ServicingAgent", "PortfolioAdmin"))
    body = validate_body(ROOF_SPECS)
    ag = lookup("agreements", body["agreement_id"])
    homeowner_scope(role, user_id, ag)
    require_child_write_allowed(ag)
    require_not_decommissioned(ag)
    removal = parse_date(body["requested_removal_date"])
    reinstall = parse_date(body["reinstall_target_date"])
    if removal < clock.today():
        raise bad_dates("requested_removal_date is before the current clock date.")
    if reinstall <= removal:
        raise bad_dates("reinstall_target_date must be strictly after "
                        "requested_removal_date.")
    if (reinstall - removal).days > MAX_ROOF_WORK_SPAN_DAYS:
        raise bad_dates("The two dates are more than %d days apart."
                        % MAX_ROOF_WORK_SPAN_DAYS)

    start = parse_date(ag["contract_start_date"])
    order = {
        "agreement_id": ag["id"],
        "requested_removal_date": fmt_date(removal),
        "reinstall_target_date": fmt_date(reinstall),
        "roofer_company": body["roofer_company"],
        "quote_cents": None,
        "suspension_start_date": fmt_date(removal),
        "suspension_end_date": fmt_date(reinstall),
        "suspension_days": (reinstall - removal).days + 1,
        "contract_year": calc.contract_year_raw(start, removal.year, removal.month),
        "approved_by_user_id": None,
        "status": "REQUESTED",
    }
    stamp_new(order)
    store.roof_work_orders[order["id"]] = order
    return created(roof_work_order_view(order))


@bp.get("/servicing/roof-work-orders/<roof_work_order_id>")
def get_roof_work_order(roof_work_order_id):
    user_id, role = authenticate(("Homeowner", "ServicingAgent",
                                  "FieldOpsCoordinator", "PortfolioAdmin"))
    order = lookup("roof_work_orders", roof_work_order_id)
    homeowner_scope(role, user_id, store.agreements.get(order["agreement_id"]))
    return ok(roof_work_order_view(order))


@bp.get("/servicing/roof-work-orders")
def list_roof_work_orders():
    user_id, role = authenticate(("Homeowner", "ServicingAgent",
                                  "FieldOpsCoordinator", "PortfolioAdmin"))
    limit, offset = pagination()
    flt = filters([
        ("agreement_id", "str", None),
        ("status", "enum", ROOF_STATUSES),
        ("contract_year", "int", None),
    ])
    rows = list(store.roof_work_orders.values())
    if role == "Homeowner":
        if "agreement_id" in flt:
            homeowner_scope(role, user_id, store.agreements.get(flt["agreement_id"]))
        owned = homeowner_agreement_ids(user_id)
        rows = [r for r in rows if r["agreement_id"] in owned]
    rows = apply_filters(sorted_rows(rows), flt)
    page, total = paginate(rows, limit, offset)
    return ok_list([roof_work_order_view(r) for r in page], limit, offset, total)


@bp.post("/servicing/roof-work-orders/<roof_work_order_id>/quote")
def quote_roof_work_order(roof_work_order_id):
    authenticate(("FieldOpsCoordinator", "ServicingAgent"))
    body = validate_body([{"name": "quote_cents", "kind": "int", "required": True,
                           "min": 0}])
    order = lookup("roof_work_orders", roof_work_order_id)
    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a REQUESTED order may be quoted.")
    order["quote_cents"] = body["quote_cents"]
    order["status"] = "QUOTED"
    touch(order)
    return ok(roof_work_order_view(order))


@bp.post("/servicing/roof-work-orders/<roof_work_order_id>/approve")
def approve_roof_work_order(roof_work_order_id):
    user_id, role = authenticate(("ServicingAgent", "PortfolioAdmin"))
    validate_body([])
    order = lookup("roof_work_orders", roof_work_order_id)
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a QUOTED order may be approved.")
    start = parse_date(order["suspension_start_date"])
    end = parse_date(order["suspension_end_date"])
    buffer_days = timedelta(days=ROOF_WORK_BUFFER_DAYS)
    for other in store.roof_work_orders.values():
        if other["id"] == order["id"]:
            continue
        if other["agreement_id"] != order["agreement_id"]:
            continue
        if other["status"] not in BLOCKING_STATUSES:
            continue
        o_start = parse_date(other["suspension_start_date"]) - buffer_days
        o_end = parse_date(other["suspension_end_date"]) + buffer_days
        if (start - buffer_days) <= o_end and o_start <= (end + buffer_days):
            raise ApiError("ERR_ROOF_WINDOW_CONFLICT",
                           "Another committed roof-work window conflicts with this "
                           "one.")
    counted = [o for o in store.roof_work_orders.values()
               if o["agreement_id"] == order["agreement_id"]
               and o["contract_year"] == order["contract_year"]
               and o["status"] in COUNTED_STATUSES and o["id"] != order["id"]]
    if len(counted) + 1 > MAX_ROOF_WORK_ORDERS_PER_YEAR:
        raise ApiError("ERR_ROOF_WORK_LIMIT_EXCEEDED",
                       "Contract year %d already has %d committed roof-work orders."
                       % (order["contract_year"], len(counted)))
    order["status"] = "APPROVED"
    order["approved_by_user_id"] = user_id
    touch(order)
    return ok(roof_work_order_view(order))


@bp.post("/servicing/roof-work-orders/<roof_work_order_id>/remove-panels")
def remove_panels(roof_work_order_id):
    authenticate(("FieldOpsCoordinator",))
    validate_body([])
    order = lookup("roof_work_orders", roof_work_order_id)
    ag = store.agreements[order["agreement_id"]]
    if order["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an APPROVED order may have its panels removed.")
    if clock.today() < parse_date(order["suspension_start_date"]):
        raise bad_dates("The clock date is before the order's suspension_start_date.")
    order["status"] = "PANELS_REMOVED"
    touch(order)
    ag["service_status"] = "ROOF_WORK_SUSPENDED"
    touch(ag)
    return ok(roof_work_order_view(order))


@bp.post("/servicing/roof-work-orders/<roof_work_order_id>/roof-complete")
def roof_complete(roof_work_order_id):
    authenticate(("FieldOpsCoordinator",))
    validate_body([])
    order = lookup("roof_work_orders", roof_work_order_id)
    if order["status"] != "PANELS_REMOVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a PANELS_REMOVED order may be signed off.")
    order["status"] = "ROOF_COMPLETE"
    touch(order)
    return ok(roof_work_order_view(order))


@bp.post("/servicing/roof-work-orders/<roof_work_order_id>/reinstall")
def reinstall(roof_work_order_id):
    authenticate(("FieldOpsCoordinator",))
    validate_body([])
    order = lookup("roof_work_orders", roof_work_order_id)
    ag = store.agreements[order["agreement_id"]]
    if order["status"] != "ROOF_COMPLETE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a ROOF_COMPLETE order may be reinstalled.")
    order["status"] = "REINSTALLED"
    touch(order)
    ag["service_status"] = "IN_SERVICE"
    touch(ag)
    return ok(roof_work_order_view(order))


@bp.post("/servicing/roof-work-orders/<roof_work_order_id>/cancel")
def cancel_roof_work_order(roof_work_order_id):
    user_id, role = authenticate(("Homeowner", "ServicingAgent", "PortfolioAdmin"))
    validate_body([])
    order = lookup("roof_work_orders", roof_work_order_id)
    homeowner_scope(role, user_id, store.agreements.get(order["agreement_id"]))
    if order["status"] not in ("REQUESTED", "QUOTED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a pre-physical order may be cancelled.")
    order["status"] = "CANCELLED"
    touch(order)
    return ok(roof_work_order_view(order))
