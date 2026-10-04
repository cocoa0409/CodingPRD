"""Retrofit mandates, shop work and the component purchasing path.

Covers PRD sections 3.2 (purchase/receipt) and 3.8 (mandates and shop work).
"""

from flask import request

from store import store, clock, to_date, fmt_date
from errors import (ApiError, invalid_state, already_terminal, invalid_request,
                    duplicate_row, prerequisite_not_met)
import calc
from calc import recompute_all_components, recompute_component, recompute_program_cost
from serialize import view
from web import (route, json_body, ok, created, list_response, parse_pagination,
                 filtered, must_get, require_int, require_enum, require_str,
                 require_date, optional_int, fk)

ALL_ROLES = ("PlatformAdmin", "SupplyChainCoordinator", "ProductionPlanner",
             "LeaseAdministrator", "PortfolioManager", "RegulatoryRetrofitist",
             "Lessee")
RETROFITIST = ("RegulatoryRetrofitist",)
PLANNER = ("ProductionPlanner",)
PLANNER_OR_RETROFITIST = ("ProductionPlanner", "RegulatoryRetrofitist")
SUPPLY = ("SupplyChainCoordinator",)


def covered_car_types(program_id):
    return {row["car_type_id"] for row in store.all("program_car_types")
            if row["retrofit_program_id"] == program_id}


def cars_of_types(type_ids, statuses=None):
    out = []
    for car in store.all("fleet_cars"):
        if car["car_type_id"] not in type_ids:
            continue
        if statuses is not None and car["status"] not in statuses:
            continue
        out.append(car)
    return out


def register(app):
    # ------------------------------------------------------------ retrofit programs
    @route(app, "/api/v1/retrofit-programs", "POST", RETROFITIST)
    def create_program(user_id, role):
        body = json_body()
        code = body.get("mandate_code")
        if code is not None and any(p["mandate_code"] == code
                                    for p in store.all("retrofit_programs")):
            raise duplicate_row("mandate_code %r already exists." % (code,))
        code = require_str(body, "mandate_code")
        description = require_str(body, "description")
        deadline = require_date(body, "compliance_deadline_date")
        shop_days = require_int(body, "required_shop_days_per_car", minimum=1)
        component = fk(body, "required_component_id", "components",
                       "required_component_id", required=False)
        row = store.new_row({
            "mandate_code": code, "description": description,
            "compliance_deadline_date": deadline,
            "required_shop_days_per_car": shop_days,
            "required_component_id": component["id"] if component is not None else None,
            "program_cost_cents": 0, "status": "PLANNED",
        })
        store.put("retrofit_programs", row)
        return created(view("retrofit_programs", row))

    @route(app, "/api/v1/retrofit-programs", "GET", ALL_ROLES)
    def list_programs(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("retrofit_programs")), request.args,
                        {"status": "status", "required_component_id": "required_component_id"})
        return list_response(rows, limit, offset, lambda r: view("retrofit_programs", r))

    @route(app, "/api/v1/retrofit-programs/{program_id}", "GET", ALL_ROLES)
    def get_program(user_id, role, program_id):
        row = must_get("retrofit_programs", program_id, "retrofit program")
        return ok(view("retrofit_programs", row))

    @route(app, "/api/v1/retrofit-programs/{program_id}/start", "POST", RETROFITIST)
    def start_program(user_id, role, program_id):
        program = must_get("retrofit_programs", program_id, "retrofit program")
        if program["status"] in ("COMPLETED", "VOIDED"):
            raise already_terminal()
        if program["status"] != "PLANNED":
            raise invalid_state("Only a planned program may be started.")
        types = covered_car_types(program["id"])
        if not types:
            raise prerequisite_not_met("The program covers no car type.")
        if to_date(program["compliance_deadline_date"]) < clock.date:
            raise ApiError("ERR_RETROFIT_DEADLINE_PASSED",
                           "The mandate's compliance deadline has already passed.")
        program["status"] = "IN_PROGRESS"
        for car in cars_of_types(types, ("HELD", "UNDER_REPAIR")):
            car["retrofit_required"] = True
            store.touch(car)
        recompute_program_cost(program)
        store.touch(program)
        return ok(view("retrofit_programs", program))

    @route(app, "/api/v1/retrofit-programs/{program_id}/complete", "POST", RETROFITIST)
    def complete_program(user_id, role, program_id):
        program = must_get("retrofit_programs", program_id, "retrofit program")
        if program["status"] in ("COMPLETED", "VOIDED"):
            raise already_terminal()
        if program["status"] != "IN_PROGRESS":
            raise invalid_state("Only an in-progress program may be completed.")
        types = covered_car_types(program["id"])
        work_orders = [w for w in store.all("retrofit_work_orders")
                       if w["retrofit_program_id"] == program["id"]]
        for type_id in types:
            if not any(w["status"] == "COMPLETED"
                       and (store.get("fleet_cars", w["lease_fleet_car_id"]) or {}).get("car_type_id") == type_id
                       for w in work_orders):
                raise invalid_state("Every covered car type needs a completed work order.")
        if any(w["status"] not in ("COMPLETED", "CANCELLED") for w in work_orders):
            raise invalid_state("Every work order must be completed or cancelled.")
        program["status"] = "COMPLETED"
        for car in cars_of_types(types):
            car["retrofit_required"] = False
            store.touch(car)
        recompute_program_cost(program)
        store.touch(program)
        return ok(view("retrofit_programs", program))

    @route(app, "/api/v1/retrofit-programs/{program_id}/void", "POST", RETROFITIST)
    def void_program(user_id, role, program_id):
        program = must_get("retrofit_programs", program_id, "retrofit program")
        body = json_body()
        if program["status"] != "IN_PROGRESS":
            raise invalid_state("Only an in-progress program may be voided.")
        program["status"] = "VOIDED"
        for wo in store.all("retrofit_work_orders"):
            if wo["retrofit_program_id"] == program["id"] and wo["status"] != "CANCELLED":
                wo["status"] = "CANCELLED"
                store.touch(wo)
        for car in cars_of_types(covered_car_types(program["id"])):
            car["retrofit_required"] = False
            store.touch(car)
        store.touch(program)
        return ok(view("retrofit_programs", program))

    @route(app, "/api/v1/retrofit-program-car-types", "POST", RETROFITIST)
    def create_program_car_type(user_id, role):
        body = json_body()
        program = fk(body, "retrofit_program_id", "retrofit_programs", "retrofit_program_id")
        car_type = fk(body, "car_type_id", "car_types", "car_type_id")
        for row in store.all("program_car_types"):
            if row["retrofit_program_id"] == program["id"] and row["car_type_id"] == car_type["id"]:
                raise duplicate_row("That car type is already covered by this program.")
        row = store.new_row({
            "retrofit_program_id": program["id"], "car_type_id": car_type["id"],
        })
        store.put("program_car_types", row)
        return created(view("program_car_types", row))

    @route(app, "/api/v1/retrofit-program-car-types", "GET", ALL_ROLES)
    def list_program_car_types(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("program_car_types")), request.args,
                        {"retrofit_program_id": "retrofit_program_id",
                         "car_type_id": "car_type_id"})
        return list_response(rows, limit, offset, lambda r: view("program_car_types", r))

    @route(app, "/api/v1/retrofit-program-car-types/{row_id}", "GET", ALL_ROLES)
    def get_program_car_type(user_id, role, row_id):
        row = must_get("program_car_types", row_id, "retrofit program car type")
        return ok(view("program_car_types", row))

    # ----------------------------------------------------------- retrofit work orders
    @route(app, "/api/v1/retrofit-work-orders", "POST", PLANNER_OR_RETROFITIST)
    def create_work_order(user_id, role):
        body = json_body()
        program = fk(body, "retrofit_program_id", "retrofit_programs", "retrofit_program_id")
        car = fk(body, "lease_fleet_car_id", "fleet_cars", "lease_fleet_car_id")
        shop_line = require_str(body, "shop_line")
        start = require_date(body, "scheduled_start_date")
        end = require_date(body, "scheduled_end_date")
        qty = require_int(body, "component_qty_consumed", minimum=1)

        # precedence 8: regulatory life, inclusive of the end date.  PRD 2.8
        # pins the comparison for retrofit scheduling to the current clock
        # date: "a car whose regulatory_life_end_date equals the current clock
        # date is still eligible for retrofit".
        life_end = car.get("regulatory_life_end_date") or calc.regulatory_life_end(car)
        if to_date(life_end) < clock.date:
            raise ApiError("ERR_REGULATORY_LIFE_EXCEEDED",
                           "The car is at or past the end of its regulatory life.")
        # precedence 9: the window must end on or before the compliance deadline
        if to_date(end) > to_date(program["compliance_deadline_date"]):
            raise ApiError("ERR_RETROFIT_DEADLINE_PASSED",
                           "The shop window ends after the mandate's compliance deadline.")
        # precedence 10: shop-line exclusivity, half-open windows
        for wo in store.all("retrofit_work_orders"):
            if wo["shop_line"] != shop_line or wo["status"] == "CANCELLED":
                continue
            if to_date(start) < to_date(wo["scheduled_end_date"]) and \
                    to_date(wo["scheduled_start_date"]) < to_date(end):
                raise ApiError("ERR_SHOP_SLOT_OVERLAP",
                               "The shop window collides with another work order on "
                               "this shop line.")
        # precedence 17: request shape
        if to_date(end) <= to_date(start):
            raise invalid_request("scheduled_end_date must be after scheduled_start_date.")
        width = (to_date(end) - to_date(start)).days
        if width != int(program["required_shop_days_per_car"]):
            raise invalid_request(
                "shop_days must equal the program's required_shop_days_per_car.")
        # precedence 21: car availability
        if car["status"] != "HELD":
            raise ApiError("ERR_CAR_NOT_HELD", "The car must be in HELD status.")
        # precedence 24: program coverage
        if car["car_type_id"] not in covered_car_types(program["id"]):
            raise ApiError("ERR_CAPACITY_EXCEEDED",
                           "The car's car type is not covered by this retrofit program.")

        row = store.new_row({
            "retrofit_program_id": program["id"], "lease_fleet_car_id": car["id"],
            "shop_line": shop_line, "scheduled_start_date": start,
            "scheduled_end_date": end, "shop_days": width,
            "component_qty_consumed": qty, "status": "SCHEDULED",
        })
        store.put("retrofit_work_orders", row)
        car["status"] = "UNDER_REPAIR"
        car["retrofit_required"] = True
        store.touch(car)
        return created(view("retrofit_work_orders", row))

    @route(app, "/api/v1/retrofit-work-orders", "GET", ALL_ROLES)
    def list_work_orders(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("retrofit_work_orders")), request.args,
                        {"status": "status", "shop_line": "shop_line",
                         "lease_fleet_car_id": "lease_fleet_car_id",
                         "retrofit_program_id": "retrofit_program_id"})
        return list_response(rows, limit, offset, lambda r: view("retrofit_work_orders", r))

    @route(app, "/api/v1/retrofit-work-orders/{work_order_id}", "GET", ALL_ROLES)
    def get_work_order(user_id, role, work_order_id):
        row = must_get("retrofit_work_orders", work_order_id, "retrofit work order")
        return ok(view("retrofit_work_orders", row))

    @route(app, "/api/v1/retrofit-work-orders/{work_order_id}/start", "POST", PLANNER)
    def start_work_order(user_id, role, work_order_id):
        wo = must_get("retrofit_work_orders", work_order_id, "retrofit work order")
        if wo["status"] != "SCHEDULED":
            raise invalid_state("Only a scheduled work order may be started.")
        # precedence 10: the half-open window must not overlap another window
        for other in store.all("retrofit_work_orders"):
            if other["id"] == wo["id"] or other["shop_line"] != wo["shop_line"]:
                continue
            if other["status"] == "CANCELLED":
                continue
            if to_date(wo["scheduled_start_date"]) < to_date(other["scheduled_end_date"]) and \
                    to_date(other["scheduled_start_date"]) < to_date(wo["scheduled_end_date"]):
                raise ApiError("ERR_SHOP_SLOT_OVERLAP",
                               "The shop window collides with another work order on "
                               "this shop line.")
        car = store.get("fleet_cars", wo["lease_fleet_car_id"])
        if car is None or car["status"] != "UNDER_REPAIR":
            raise invalid_state("The parent car must be UNDER_REPAIR.")
        wo["status"] = "IN_PROGRESS"
        program = store.get("retrofit_programs", wo["retrofit_program_id"])
        component = store.get("components", program.get("required_component_id")) \
            if program else None
        if component is not None:
            component["on_hand_qty"] = int(component["on_hand_qty"]) - int(wo["component_qty_consumed"])
            recompute_component(component)
            store.touch(component)
        store.touch(wo)
        return ok(view("retrofit_work_orders", wo))

    @route(app, "/api/v1/retrofit-work-orders/{work_order_id}/complete", "POST", PLANNER)
    def complete_work_order(user_id, role, work_order_id):
        wo = must_get("retrofit_work_orders", work_order_id, "retrofit work order")
        if wo["status"] != "IN_PROGRESS":
            raise invalid_state("Only an in-progress work order may be completed.")
        program = store.get("retrofit_programs", wo["retrofit_program_id"])
        if program is not None and to_date(wo["scheduled_end_date"]) > \
                to_date(program["compliance_deadline_date"]):
            raise ApiError("ERR_RETROFIT_DEADLINE_PASSED",
                           "The shop window is past the mandate's compliance deadline.")
        car = store.get("fleet_cars", wo["lease_fleet_car_id"])
        if car is None:
            raise invalid_state("The parent car must be UNDER_REPAIR.")
        wo["status"] = "COMPLETED"
        car["status"] = "HELD"
        car["built_date"] = fmt_date(clock.date)
        calc.recompute_car_derived(car)
        if program is not None:
            recompute_program_cost(program)
            store.touch(program)
        store.touch(wo)
        store.touch(car)
        return ok(view("retrofit_work_orders", wo))

    @route(app, "/api/v1/retrofit-work-orders/{work_order_id}/cancel", "POST", PLANNER)
    def cancel_work_order(user_id, role, work_order_id):
        wo = must_get("retrofit_work_orders", work_order_id, "retrofit work order")
        body = json_body()
        if wo["status"] != "SCHEDULED":
            raise invalid_state("Only a scheduled work order may be cancelled.")
        wo["status"] = "CANCELLED"
        program = store.get("retrofit_programs", wo["retrofit_program_id"])
        if program is not None:
            recompute_program_cost(program)
            store.touch(program)
        store.touch(wo)
        return ok(view("retrofit_work_orders", wo))

    # ---------------------------------------------------------- purchase orders
    @route(app, "/api/v1/component-purchase-orders", "POST", SUPPLY)
    def create_purchase_order(user_id, role):
        body = json_body()
        component = fk(body, "component_id", "components", "component_id")
        qty = require_int(body, "qty_ordered", minimum=1)
        unit_cost = require_int(body, "unit_cost_cents", minimum=0)
        order_date = require_date(body, "order_date")
        expected = require_date(body, "expected_receipt_date")
        row = store.new_row({
            "component_id": component["id"], "qty_ordered": qty,
            "unit_cost_cents": unit_cost, "order_date": order_date,
            "expected_receipt_date": expected, "status": "PLACED",
        })
        store.put("purchase_orders", row)
        return created(view("purchase_orders", row))

    @route(app, "/api/v1/component-purchase-orders", "GET", ALL_ROLES)
    def list_purchase_orders(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("purchase_orders")), request.args,
                        {"status": "status", "component_id": "component_id"})
        return list_response(rows, limit, offset, lambda r: view("purchase_orders", r))

    @route(app, "/api/v1/component-purchase-orders/{po_id}", "GET", ALL_ROLES)
    def get_purchase_order(user_id, role, po_id):
        row = must_get("purchase_orders", po_id, "component purchase order")
        return ok(view("purchase_orders", row))

    @route(app, "/api/v1/component-purchase-orders/{po_id}/confirm", "POST", SUPPLY)
    def confirm_purchase_order(user_id, role, po_id):
        po = must_get("purchase_orders", po_id, "component purchase order")
        if po["status"] != "PLACED":
            raise invalid_state("Only a placed purchase order may be confirmed.")
        po["status"] = "CONFIRMED"
        store.touch(po)
        return ok(view("purchase_orders", po))

    @route(app, "/api/v1/component-purchase-orders/{po_id}/cancel", "POST", SUPPLY)
    def cancel_purchase_order(user_id, role, po_id):
        po = must_get("purchase_orders", po_id, "component purchase order")
        body = json_body()
        if po["status"] != "PLACED":
            raise invalid_state("Only a placed purchase order may be cancelled.")
        po["status"] = "CANCELLED"
        store.touch(po)
        return ok(view("purchase_orders", po))

    # -------------------------------------------------------------- receipts
    @route(app, "/api/v1/component-receipts", "POST", SUPPLY)
    def create_receipt(user_id, role):
        body = json_body()
        po = fk(body, "component_purchase_order_id", "purchase_orders",
                "component_purchase_order_id")
        component = fk(body, "component_id", "components", "component_id")
        qty = require_int(body, "qty_received", minimum=1)
        receipt_date = require_date(body, "receipt_date")
        row = store.new_row({
            "component_purchase_order_id": po["id"], "component_id": component["id"],
            "qty_received": qty, "receipt_date": receipt_date,
        })
        store.put("component_receipts", row)
        return created(view("component_receipts", row))

    @route(app, "/api/v1/component-receipts", "GET", ALL_ROLES)
    def list_receipts(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("component_receipts")), request.args,
                        {"component_id": "component_id",
                         "component_purchase_order_id": "component_purchase_order_id"})
        return list_response(rows, limit, offset, lambda r: view("component_receipts", r))

    @route(app, "/api/v1/component-receipts/{receipt_id}", "GET", ALL_ROLES)
    def get_receipt(user_id, role, receipt_id):
        row = must_get("component_receipts", receipt_id, "component receipt")
        return ok(view("component_receipts", row))

    @route(app, "/api/v1/component-receipts/{receipt_id}/receive", "POST", SUPPLY)
    def receive_receipt(user_id, role, receipt_id):
        receipt = must_get("component_receipts", receipt_id, "component receipt")
        po = store.get("purchase_orders", receipt["component_purchase_order_id"])
        if po is None or po["status"] != "CONFIRMED":
            raise invalid_state("The parent purchase order must be CONFIRMED.")
        if to_date(receipt["receipt_date"]) < to_date(po["order_date"]):
            raise invalid_request("receipt_date must not be before the purchase order_date.")
        component = store.get("components", receipt["component_id"])
        po["status"] = "RECEIVED"
        if component is not None:
            component["on_hand_qty"] = int(component["on_hand_qty"]) + int(receipt["qty_received"])
            recompute_component(component)
            store.touch(component)
        store.touch(po)
        store.touch(receipt)
        return ok(view("component_receipts", receipt))
