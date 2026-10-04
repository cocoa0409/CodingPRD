"""Production catalogue, order backlog, line scheduling and endorsements.

Covers PRD sections 3.1-3.4 plus the endorsement cycle of 3.3.  Every handler
runs its checks in the fixed precedence order of PRD section 2.11.
"""

from flask import request

from store import store, clock, to_date, fmt_date, add_days
from errors import (ApiError, invalid_state, already_terminal, stale_version,
                    invalid_request, duplicate_row, not_found, fk_not_found,
                    prerequisite_not_met)
import calc
from calc import (production_feasibility_gate, order_price_quote, effective_qty,
                  substitution_for_row, bom_rows_for, component_of,
                  recompute_all_components, recompute_component,
                  capital_allocation_for_order, LIVE_FLEET_STATES)
from serialize import view
from web import (route, json_body, ok, created, list_response, parse_pagination,
                 filtered, must_get, require_int, require_enum, require_str,
                 require_date, optional_date, optional_int, optional_bool, fk,
                 body_get)

ALL_ROLES = ("PlatformAdmin", "SupplyChainCoordinator", "ProductionPlanner",
             "LeaseAdministrator", "PortfolioManager", "RegulatoryRetrofitist",
             "Lessee")
PLANNER = ("ProductionPlanner",)
PLANNER_OR_RETROFITIST = ("ProductionPlanner", "RegulatoryRetrofitist")

CAR_CLASSES = ("BOXCAR", "TANK", "HOPPER", "FLATCARS", "GONDOLA")
COMPONENT_CLASSES = ("WHEELSET", "CASTING", "COATING")
DISPOSITIONS = ("SOLD", "RETAINED")
GATED = ("WHEELSET", "CASTING")


def committed_component(order, row):
    """The component actually committed for a requirement row (substitute if any)."""
    sub = substitution_for_row(order["id"], row["component_id"])
    if sub is not None:
        return store.get("components", sub["substitute_component_id"]), sub
    return store.get("components", row["component_id"]), None


def covered_rows(order):
    """Requirement rows of the order's car type, in part_number order."""
    rows = bom_rows_for(order["car_type_id"])
    return sorted(rows, key=lambda r: (
        (component_of(r) or {}).get("part_number", ""), r.get("created_at", ""), r.get("_seq", 0)))


def live_fleet_count():
    return len([c for c in store.all("fleet_cars") if c["status"] in LIVE_FLEET_STATES])


def register(app):
    # ------------------------------------------------------------------ car types
    @route(app, "/api/v1/car-types", "POST", PLANNER_OR_RETROFITIST)
    def create_car_type(user_id, role):
        body = json_body()
        model_code = body.get("model_code")
        if model_code is not None and any(ct["model_code"] == model_code
                                          for ct in store.all("car_types")):
            raise duplicate_row("model_code %r already exists." % (model_code,))
        model_code = require_str(body, "model_code")
        car_class = require_enum(body, "car_class", CAR_CLASSES)
        build_hours = require_int(body, "build_hours", minimum=1)
        life_years = require_int(body, "regulatory_life_years", minimum=10)
        family = require_str(body, "line_count_family")
        row = store.new_row({
            "model_code": model_code, "car_class": car_class,
            "build_hours": build_hours, "regulatory_life_years": life_years,
            "line_count_family": family, "status": "ACTIVE",
        })
        store.put("car_types", row)
        return created(view("car_types", row))

    @route(app, "/api/v1/car-types/{car_type_id}", "GET", ALL_ROLES)
    def get_car_type(user_id, role, car_type_id):
        row = must_get("car_types", car_type_id, "car type")
        return ok(view("car_types", row))

    # ------------------------------------------------------------------ components
    @route(app, "/api/v1/components", "POST", ("SupplyChainCoordinator",))
    def create_component(user_id, role):
        body = json_body()
        part_number = body.get("part_number")
        if part_number is not None and any(c["part_number"] == part_number
                                           for c in store.all("components")):
            raise duplicate_row("part_number %r already exists." % (part_number,))
        part_number = require_str(body, "part_number")
        comp_class = require_enum(body, "component_class", COMPONENT_CLASSES)
        unit_cost = require_int(body, "unit_cost_cents", minimum=0)
        lead_time = require_int(body, "lead_time_days", minimum=0)
        on_hand = optional_int(body, "on_hand_qty", default=0, minimum=0)
        row = store.new_row({
            "part_number": part_number, "component_class": comp_class,
            "unit_cost_cents": unit_cost, "lead_time_days": lead_time,
            "on_hand_qty": on_hand, "reserved_qty": 0, "shortfall_qty": 0,
        })
        store.put("components", row)
        recompute_component(row)
        return created(view("components", row))

    @route(app, "/api/v1/components/{component_id}", "GET", ALL_ROLES)
    def get_component(user_id, role, component_id):
        row = must_get("components", component_id, "component")
        return ok(view("components", row))

    # ------------------------------------------------------------- bill of material
    @route(app, "/api/v1/car-type-component-requirements", "POST", PLANNER)
    def create_bom_row(user_id, role):
        body = json_body()
        car_type = fk(body, "car_type_id", "car_types", "car_type_id")
        component = fk(body, "component_id", "components", "component_id")
        qty = require_int(body, "qty_per_car", minimum=1)
        for row in store.all("bom_rows"):
            if row["car_type_id"] == car_type["id"] and row["component_id"] == component["id"]:
                raise duplicate_row("This car type already requires that component.")
        row = store.new_row({
            "car_type_id": car_type["id"], "component_id": component["id"],
            "qty_per_car": qty,
        })
        store.put("bom_rows", row)
        recompute_all_components()
        return created(view("bom_rows", row))

    @route(app, "/api/v1/car-type-component-requirements", "GET", ALL_ROLES)
    def list_bom_rows(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("bom_rows")), request.args,
                        {"car_type_id": "car_type_id", "component_id": "component_id"})
        return list_response(rows, limit, offset, lambda r: view("bom_rows", r))

    @route(app, "/api/v1/car-type-component-requirements/{row_id}", "GET", ALL_ROLES)
    def get_bom_row(user_id, role, row_id):
        row = must_get("bom_rows", row_id, "car-type-component-requirement")
        return ok(view("bom_rows", row))

    # -------------------------------------------------------------- production orders
    @route(app, "/api/v1/production-orders", "POST", PLANNER)
    def create_production_order(user_id, role):
        body = json_body()
        car_type = fk(body, "car_type_id", "car_types", "car_type_id")
        fk(body, "lessee_id", "lessees", "lessee_id", required=False)
        fk(body, "supersedes_production_order_id", "production_orders",
           "supersedes_production_order_id", required=False)

        order_date = optional_date(body, "order_date")
        required_date = optional_date(body, "required_delivery_date")
        # precedence 14 (lead-time feasibility) is evaluated before 17 (shape)
        if order_date and required_date:
            probe = {"car_type_id": car_type["id"], "order_date": order_date,
                     "required_delivery_date": required_date}
            feasible, worst = production_feasibility_gate(probe)
            if not feasible:
                raise ApiError("ERR_LEAD_TIME_INFEASIBLE",
                               "The order-to-delivery horizon is shorter than the worst "
                               "gated component lead time (%d days)." % worst)

        quantity = require_int(body, "quantity", minimum=1)
        priority_rank = require_int(body, "priority_rank", minimum=1)
        planned = require_int(body, "planned_shop_days", minimum=1)
        disposition = require_enum(body, "disposition", DISPOSITIONS)
        if not order_date:
            raise invalid_request("order_date is required.")
        if not required_date:
            raise invalid_request("required_delivery_date is required.")
        if planned != int(car_type["build_hours"]) * quantity:
            raise invalid_request(
                "planned_shop_days must equal build_hours * quantity.")

        row = store.new_row({
            "car_type_id": car_type["id"], "quantity": quantity, "completed_qty": 0,
            "unit_price_cents": 0, "planned_shop_days": planned,
            "disposition": disposition, "priority_rank": priority_rank,
            "order_date": order_date, "required_delivery_date": required_date,
            "status": "DRAFT",
            "supersedes_production_order_id": body.get("supersedes_production_order_id"),
            "retention_reason": body.get("retention_reason"),
            "lessee_id": body.get("lessee_id"),
        })
        store.put("production_orders", row)
        row["unit_price_cents"] = order_price_quote(row)
        return created(view("production_orders", row))

    @route(app, "/api/v1/production-orders", "GET", ALL_ROLES)
    def list_production_orders(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("production_orders")), request.args,
                        {"status": "status", "car_type_id": "car_type_id",
                         "supersedes_production_order_id": "supersedes_production_order_id"})
        return list_response(rows, limit, offset, lambda r: view("production_orders", r))

    @route(app, "/api/v1/production-orders/{order_id}", "GET", ALL_ROLES)
    def get_production_order(user_id, role, order_id):
        row = must_get("production_orders", order_id, "production order")
        return ok(view("production_orders", row))

    @route(app, "/api/v1/production-orders/{order_id}/superseding-orders", "GET", ALL_ROLES)
    def list_superseding_orders(user_id, role, order_id):
        parent = must_get("production_orders", order_id, "production order")
        limit, offset = parse_pagination(request.args)
        rows = [o for o in store.all("production_orders")
                if o.get("supersedes_production_order_id") == parent["id"]]
        rows = store.sorted_rows(rows)
        return list_response(rows, limit, offset, lambda r: view("production_orders", r))

    @route(app, "/api/v1/production-orders/{order_id}/reserve-components", "POST", PLANNER)
    def reserve_components(user_id, role, order_id):
        order = must_get("production_orders", order_id, "production order")
        if order["status"] != "DRAFT":
            raise invalid_state("Components may only be reserved from DRAFT.")
        rows = covered_rows(order)
        if not rows:
            raise prerequisite_not_met("The car type has no bill-of-material rows.")

        # automatic endorsement branch: a PENDING endorsement naming the short
        # component, with enough substitute stock, is approved by the system.
        for row in rows:
            comp = component_of(row)
            if comp is None or comp["component_class"] not in GATED:
                continue
            if int(comp["on_hand_qty"]) < effective_qty(order, row) * int(order["quantity"]):
                for endo in calc.endorsements_of_order(order["id"], ("PENDING",)):
                    if endo["original_component_id"] != row["component_id"]:
                        continue
                    sub = store.get("components", endo["substitute_component_id"])
                    if sub is not None and int(sub["on_hand_qty"]) >= \
                            int(endo["substitute_qty_per_car"]) * int(order["quantity"]):
                        endo["status"] = "APPROVED"
                        store.touch(endo)
                        break

        # precedence 13: component sufficiency over the committed composition
        for row in rows:
            comp, _ = committed_component(order, row)
            if comp is None or comp["component_class"] not in GATED:
                continue
            if int(comp["on_hand_qty"]) < effective_qty(order, row) * int(order["quantity"]):
                raise ApiError("ERR_COMPONENT_SHORTAGE",
                               "On-hand %s stock is below the effective per-car "
                               "requirement times the order quantity." % comp["part_number"])

        # precedence 14: lead-time feasibility re-evaluated at reservation
        feasible, worst = production_feasibility_gate(order)
        if not feasible:
            raise ApiError("ERR_LEAD_TIME_INFEASIBLE",
                           "The order-to-delivery horizon is shorter than the worst "
                           "gated component lead time (%d days)." % worst)

        order["status"] = "COMPONENT_RESERVED"
        for row in rows:
            comp, endo = committed_component(order, row)
            if comp is None or comp["component_class"] not in GATED:
                continue
            comp["on_hand_qty"] = int(comp["on_hand_qty"]) - \
                effective_qty(order, row) * int(order["quantity"])
            if endo is not None:
                endo["_committed_component_id"] = comp["id"]
        recompute_all_components()
        order["unit_price_cents"] = order_price_quote(order)
        store.touch(order)
        return ok(view("production_orders", order))

    @route(app, "/api/v1/production-orders/{order_id}/release", "POST", PLANNER)
    def release_order(user_id, role, order_id):
        order = must_get("production_orders", order_id, "production order")
        body = json_body()
        contract = fk(body, "lease_contract_id", "lease_contracts",
                      "lease_contract_id", required=False)
        if order["status"] != "COMPONENT_RESERVED":
            raise invalid_state("Only a component-reserved order may be released.")

        # every requirement row must have committed supply
        for row in covered_rows(order):
            comp = component_of(row)
            if comp is None or comp["component_class"] != "COATING":
                continue
            ok_po = [p for p in store.all("purchase_orders")
                     if p["component_id"] == comp["id"]
                     and p["status"] in ("CONFIRMED", "RECEIVED")
                     and to_date(p["expected_receipt_date"]) <=
                     to_date(order["required_delivery_date"])]
            if not ok_po:
                raise prerequisite_not_met(
                    "No confirmed purchase order covers the coating requirement.")

        # no higher-priority order on the same line family may be preempted
        car_type = store.get("car_types", order["car_type_id"])
        family = car_type["line_count_family"] if car_type else None
        for other in store.all("production_orders"):
            if other["id"] == order["id"] or other["status"] != "IN_PRODUCTION":
                continue
            oct_ = store.get("car_types", other["car_type_id"])
            if oct_ is None or oct_["line_count_family"] != family:
                continue
            if backlog_key(other) < backlog_key(order):
                raise invalid_state(
                    "A higher-priority order on this line family is already in production.")

        # precedence 19: fleet cap, evaluated on release
        if order["disposition"] == "RETAINED" and contract is not None:
            if live_fleet_count() + int(order["quantity"]) > int(contract["fleet_car_cap"]):
                raise ApiError("ERR_FLEET_CAP_EXCEEDED",
                               "The fleet's live car count plus this order's cars "
                               "exceeds the contract's fleet_car_cap.")

        # precedence 15: material endorsement closure.  PRD 2.11: "no endorsement
        # on the order with decides_material true may remain in APPROVED status
        # when the order is released".  The check runs before the apply step so
        # a material substitution cannot be slipped through by the release.
        for endo in calc.endorsements_of_order(order["id"], ("APPROVED",)):
            if endo.get("decides_material"):
                raise ApiError(
                    "ERR_MATERIAL_ENDORSEMENT_PENDING",
                    "A material endorsement on this order is still in flight.")

        order["status"] = "RELEASED"
        order["_lease_contract_id"] = contract["id"] if contract is not None else \
            order.get("_lease_contract_id")
        if order["disposition"] == "RETAINED":
            order["retention_reason"] = body.get("retention_reason", order.get("retention_reason"))
            # the contract named at release is the account the retained cars
            # are capitalized against, so the order is attributed to its lessee
            if contract is not None and not order.get("lessee_id"):
                order["lessee_id"] = contract["lessee_id"]

        # apply every APPROVED endorsement, swapping the committed stock
        for endo in calc.endorsements_of_order(order["id"], ("APPROVED",)):
            row = next((r for r in covered_rows(order)
                        if r["component_id"] == endo["original_component_id"]), None)
            if row is not None:
                original = store.get("components", endo["original_component_id"])
                substitute = store.get("components", endo["substitute_component_id"])
                if substitute is not None and endo.get("_committed_component_id") != substitute["id"]:
                    if original is not None:
                        original["on_hand_qty"] = int(original["on_hand_qty"]) + \
                            int(row["qty_per_car"]) * int(order["quantity"])
                    substitute["on_hand_qty"] = int(substitute["on_hand_qty"]) - \
                        int(endo["substitute_qty_per_car"]) * int(order["quantity"])
                    endo["_committed_component_id"] = substitute["id"]
            endo["status"] = "APPLIED"
            store.touch(endo)
        recompute_all_components()

        order["unit_price_cents"] = order_price_quote(order)
        if order["disposition"] == "RETAINED" and order.get("_lease_contract_id"):
            target = store.get("lease_contracts", order["_lease_contract_id"])
            if target is not None:
                target["capital_allocation_cents"] = capital_allocation_for_order(order)
                store.touch(target)
        store.touch(order)
        return ok(view("production_orders", order))

    @route(app, "/api/v1/production-lines/{line}/changeover", "POST", PLANNER)
    def changeover(user_id, role, line):
        # path resolution: `line` names a production line family in the catalogue
        if not any(ct["line_count_family"] == line for ct in store.all("car_types")):
            raise not_found("production line")
        body = json_body()
        order = fk(body, "production_order_id", "production_orders", "production_order_id")
        start = require_date(body, "scheduled_start_date")
        end = require_date(body, "scheduled_end_date")
        if order["status"] != "RELEASED":
            raise invalid_state("Only a released order may start production.")
        car_type = store.get("car_types", order["car_type_id"])
        if car_type is None or car_type["line_count_family"] != line:
            raise invalid_state("The order does not belong to this production line family.")
        if head_of_backlog(car_type["line_count_family"])["id"] != order["id"]:
            raise invalid_state("The order is not the head of the backlog schedule.")
        if to_date(end) <= to_date(start):
            raise invalid_request("scheduled_end_date must be after scheduled_start_date.")
        # precedence 12: line exclusivity, half-open windows
        for co in store.all("changeovers"):
            if co["line_count_family"] != car_type["line_count_family"]:
                continue
            if to_date(start) < to_date(co["scheduled_end_date"]) and \
                    to_date(co["scheduled_start_date"]) < to_date(end):
                raise ApiError("ERR_CHANGEOVER_CONFLICT",
                               "The changeover window collides with another changeover "
                               "on this production line family.")
        width = (to_date(end) - to_date(start)).days
        if width != int(car_type["build_hours"]) * int(order["quantity"]):
            raise invalid_request(
                "The changeover window width must equal build_hours * quantity.")
        store.put("changeovers", store.new_row({
            "line": line, "line_count_family": car_type["line_count_family"],
            "production_order_id": order["id"],
            "scheduled_start_date": start, "scheduled_end_date": end,
        }))
        order["status"] = "IN_PRODUCTION"
        order["planned_shop_days"] = width
        store.touch(order)
        return ok(view("production_orders", order))

    @route(app, "/api/v1/production-orders/{order_id}/complete", "POST", PLANNER)
    def complete_order(user_id, role, order_id):
        order = must_get("production_orders", order_id, "production order")
        body = json_body()
        lessee = fk(body, "lessee_id", "lessees", "lessee_id", required=False)
        completion_date = optional_date(body, "completion_date", default=None)
        if order["status"] in ("COMPLETED", "CANCELLED"):
            raise already_terminal()
        if order["status"] != "IN_PRODUCTION":
            raise invalid_state("Only an in-production order may be completed.")
        delta = require_int(body, "completed_qty", minimum=0)
        if int(order["completed_qty"]) + delta != int(order["quantity"]):
            raise invalid_request(
                "completed_qty plus the quantity already finished must equal quantity.")
        done_date = completion_date or fmt_date(clock.date)
        contract = store.get("lease_contracts", order.get("_lease_contract_id"))

        if order["disposition"] == "RETAINED":
            live = live_fleet_count()
            cap = int(contract["fleet_car_cap"]) if contract is not None else None
            car_type = store.get("car_types", order["car_type_id"])
            for _ in range(int(order["quantity"])):
                # compensating path: an overflow car is born scrapped, the order
                # still reports COMPLETED with completed_qty == quantity.
                overflow = cap is not None and live >= cap
                car = store.new_row({
                    "car_type_id": car_type["id"] if car_type else order["car_type_id"],
                    "production_order_id": order["id"],
                    "lease_contract_id": None,
                    "acquisition_cost_cents": int(order["unit_price_cents"]),
                    "accumulated_mileage": 0,
                    "status": "SCRAPPED" if overflow else "HELD",
                    "built_date": done_date,
                    "regulatory_life_end_date": None,
                    "retrofit_required": False,
                })
                store.put("fleet_cars", car)
                calc.recompute_car_derived(car)
                if not overflow:
                    live += 1
            ledger = store.ledger
            ledger["committed_capital_cents"] = int(ledger["committed_capital_cents"]) + \
                int(order["unit_price_cents"]) * delta
            calc.recompute_ledger_nbv()
            store.touch(ledger)
            if contract is not None:
                contract["capital_allocation_cents"] = capital_allocation_for_order(order)
                store.touch(contract)
        else:
            target_lessee = lessee
            if target_lessee is None and order.get("lessee_id"):
                target_lessee = store.get("lessees", order["lessee_id"])
            if target_lessee is None:
                target_lessee = default_lessor_liable_lessee()
            if target_lessee is not None:
                order["lessee_id"] = target_lessee["id"]

        order["completed_qty"] = int(order["quantity"])
        order["status"] = "COMPLETED"
        store.touch(order)
        recompute_all_components()
        for less in store.all("lessees"):
            calc.recompute_lessee_balance(less)
        return ok(view("production_orders", order))

    @route(app, "/api/v1/production-orders/{order_id}/cancel", "POST", PLANNER)
    def cancel_order(user_id, role, order_id):
        order = must_get("production_orders", order_id, "production order")
        body = json_body()
        prior = order["status"]
        if prior not in ("DRAFT", "COMPONENT_RESERVED"):
            raise invalid_state("Only a draft or component-reserved order may be cancelled.")
        order["status"] = "CANCELLED"
        if prior == "COMPONENT_RESERVED":
            for row in covered_rows(order):
                comp, _ = committed_component(order, row)
                if comp is None or comp["component_class"] not in GATED:
                    continue
                comp["on_hand_qty"] = int(comp["on_hand_qty"]) + \
                    effective_qty(order, row) * int(order["quantity"])
            for endo in calc.endorsements_of_order(order["id"],
                                                   ("PENDING", "APPROVED", "APPLIED")):
                endo["status"] = "SUPERSEDED"
                store.touch(endo)
        recompute_all_components()
        store.touch(order)
        return ok(view("production_orders", order))

    # ------------------------------------------------------------ endorsements
    @route(app, "/api/v1/substitution-endorsements", "POST", PLANNER_OR_RETROFITIST)
    def create_endorsement(user_id, role):
        body = json_body()
        order = fk(body, "production_order_id", "production_orders", "production_order_id")
        original = fk(body, "original_component_id", "components", "original_component_id")
        substitute = fk(body, "substitute_component_id", "components", "substitute_component_id")
        # precedence 7: optimistic concurrency guard
        expected = body.get("expected_production_order_version")
        if expected is not None and str(expected) != "":
            try:
                expected_int = int(expected)
            except (TypeError, ValueError):
                raise invalid_request("expected_production_order_version must be an integer.")
            if expected_int != int(order["version"]):
                raise stale_version()
        qty = require_int(body, "substitute_qty_per_car", minimum=1)
        decides_material = optional_bool(body, "decides_material", default=False)
        if expected is None or str(expected) == "":
            raise invalid_request("expected_production_order_version is required.")
        for endo in calc.endorsements_of_order(order["id"], ("PENDING",)):
            if endo["original_component_id"] == original["id"]:
                endo["status"] = "SUPERSEDED"
                store.touch(endo)
        row = store.new_row({
            "production_order_id": order["id"],
            "original_component_id": original["id"],
            "substitute_component_id": substitute["id"],
            "substitute_qty_per_car": qty,
            "status": "PENDING",
            "decides_material": decides_material,
            "created_by_user_id": user_id,
            "_rejections": 0,
            "_returns": 0,
        })
        store.put("endorsements", row)
        store.touch(order)
        return created(view("endorsements", row))

    @route(app, "/api/v1/substitution-endorsements", "GET", ALL_ROLES)
    def list_endorsements(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("endorsements")), request.args,
                        {"production_order_id": "production_order_id", "status": "status",
                         "original_component_id": "original_component_id",
                         "substitute_component_id": "substitute_component_id"})
        return list_response(rows, limit, offset, lambda r: view("endorsements", r))

    @route(app, "/api/v1/substitution-endorsements/{endorsement_id}", "GET", ALL_ROLES)
    def get_endorsement(user_id, role, endorsement_id):
        row = must_get("endorsements", endorsement_id, "substitution endorsement")
        return ok(view("endorsements", row))

    @route(app, "/api/v1/substitution-endorsements/{endorsement_id}/approve", "POST",
           ("LeaseAdministrator",))
    def approve_endorsement(user_id, role, endorsement_id):
        endo = must_get("endorsements", endorsement_id, "substitution endorsement")
        if endo["status"] != "PENDING":
            raise invalid_state("Only a pending endorsement may be approved.")
        if endo.get("created_by_user_id") == user_id:
            raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN",
                           "The operator who created an endorsement may not approve it.")
        order = store.get("production_orders", endo["production_order_id"])
        substitute = store.get("components", endo["substitute_component_id"])
        if substitute is not None and order is not None:
            need = int(endo["substitute_qty_per_car"]) * int(order["quantity"])
            if int(substitute["on_hand_qty"]) < need:
                raise ApiError("ERR_COMPONENT_SHORTAGE",
                               "The substitute's on-hand stock cannot cover the order.")
        endo["status"] = "APPROVED"
        if order is not None:
            order["unit_price_cents"] = order_price_quote(order)
        store.touch(endo)
        return ok(view("endorsements", endo))

    @route(app, "/api/v1/substitution-endorsements/{endorsement_id}", "PATCH",
           ("LeaseAdministrator", "ProductionPlanner"))
    def patch_endorsement(user_id, role, endorsement_id):
        endo = must_get("endorsements", endorsement_id, "substitution endorsement")
        body = json_body()
        target = require_enum(body, "status", ("REJECTED", "PENDING"))
        expected = body.get("expected_substitution_endorsement_version")
        if expected is not None and str(expected) != "":
            try:
                expected_int = int(expected)
            except (TypeError, ValueError):
                raise invalid_request("expected_substitution_endorsement_version must be an integer.")
            if expected_int != int(endo["version"]):
                raise stale_version()
        if target == "REJECTED":
            if endo["status"] != "PENDING":
                raise invalid_state("Only a pending endorsement may be rejected.")
            endo["status"] = "REJECTED"
            endo["_rejections"] = int(endo.get("_rejections", 0)) + 1
        else:
            if endo["status"] != "REJECTED":
                raise invalid_state("Only a rejected endorsement may return to pending.")
            if int(endo.get("_returns", 0)) >= 1:
                raise ApiError("ERR_ENDORSEMENT_RETRY_EXHAUSTED",
                               "This endorsement has already been returned to pending once.")
            endo["status"] = "PENDING"
            endo["_returns"] = int(endo.get("_returns", 0)) + 1
            endo.pop("_committed_component_id", None)
        store.touch(endo)
        return ok(view("endorsements", endo))


def backlog_key(order):
    """Backlog position: lowest priority_rank, then earliest order_date, then created_at."""
    return (int(order["priority_rank"]), to_date(order["order_date"]),
            order.get("created_at", ""), order.get("_seq", 0))


def head_of_backlog(family):
    candidates = []
    for order in store.all("production_orders"):
        if order["status"] != "RELEASED":
            continue
        car_type = store.get("car_types", order["car_type_id"])
        if car_type is None or car_type["line_count_family"] != family:
            continue
        candidates.append(order)
    if not candidates:
        raise invalid_state("No released order is waiting on this production line family.")
    return sorted(candidates, key=backlog_key)[0]


def default_lessor_liable_lessee():
    """The lessee of the only LESSOR-liable contract in ACTIVE status, if unique."""
    matches = [c for c in store.all("lease_contracts")
               if c["status"] == "ACTIVE" and c["liability_bearer"] == "LESSOR"]
    if len(matches) == 1:
        return store.get("lessees", matches[0]["lessee_id"])
    return None
