"""Lease contracts, lessee ledgers, fleet cars, placements and returns.

Covers PRD sections 3.5-3.7.  Checks run in the precedence order of section 2.11.
"""

from datetime import timedelta

from flask import request

from store import store, clock, to_date, fmt_date
from errors import (ApiError, invalid_state, stale_version, invalid_request,
                    duplicate_row, forbidden)
import calc
from calc import (LIVE_FLEET_STATES, CONDITION_PARTS_CENTS, maintenance_split,
                  mileage_true_up, recompute_lessee_balance, per_diem_accrued_open)
from serialize import view, lessee_balance
from web import (route, json_body, ok, created, list_response, parse_pagination,
                 filtered, must_get, require_int, require_enum, require_str,
                 require_date, optional_date, optional_int, fk)

ALL_ROLES = ("PlatformAdmin", "SupplyChainCoordinator", "ProductionPlanner",
             "LeaseAdministrator", "PortfolioManager", "RegulatoryRetrofitist",
             "Lessee")
LEASE_ADMIN = ("LeaseAdministrator",)
PLANNER = ("ProductionPlanner",)
PORTFOLIO = ("PortfolioManager",)

LEASE_TYPES = ("FULL_SERVICE", "NET")
LIABILITY_BEARERS = ("LESSOR", "LESSEE")
CREDIT_TIERS = ("A", "B", "C", "D")
CONDITION_GRADES = ("A", "B", "C", "D")


def intervals_collide(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: touching at a boundary is legal."""
    return to_date(a_start) < to_date(b_end) and to_date(b_start) < to_date(a_end)


def buffered_collision(new_start, new_end, other_start, other_end):
    """Placement rule: a one-day buffer is required between placements.

    A placement that ends exactly when another begins is legal under the
    half-open convention, but a start_date equal to a prior end_date plus zero
    or one day is rejected, so the required gap is two days.
    """
    if to_date(new_end) <= to_date(other_start):
        return False
    return to_date(new_start) < to_date(other_end) + timedelta(days=2)


def projected_placement_charge(contract, lessee, start, end):
    """The projected per-diem charge a placement would add (PRD section 2.9)."""
    days = (to_date(end) - to_date(start)).days
    if days < 0:
        days = 0
    gross = days * int(contract["per_diem_rate_cents"])
    credit = 0
    if lessee is not None and int(lessee["utilization_threshold_pct"]) <= 0:
        credit = (gross * calc.UTILIZATION_CREDIT_PCT) // 100
    return gross - credit


def register(app):
    # ------------------------------------------------------------------- lessees
    @route(app, "/api/v1/lessees", "POST", LEASE_ADMIN)
    def create_lessee(user_id, role):
        body = json_body()
        legal_name = body.get("legal_name")
        if legal_name is not None and any(l["legal_name"] == legal_name
                                          for l in store.all("lessees")):
            raise duplicate_row("legal_name %r already exists." % (legal_name,))
        legal_name = require_str(body, "legal_name")
        credit_tier = require_enum(body, "credit_tier", CREDIT_TIERS)
        threshold = require_int(body, "utilization_threshold_pct", minimum=0, maximum=100)
        ceiling = require_int(body, "credit_ceiling_cents", minimum=0)
        row = store.new_row({
            "legal_name": legal_name, "credit_tier": credit_tier,
            "utilization_threshold_pct": threshold,
            "credit_ceiling_cents": ceiling,
            "outstanding_balance_cents": 0, "status": "ACTIVE",
        })
        store.put("lessees", row)
        return created(view("lessees", row))

    @route(app, "/api/v1/lessees/{lessee_id}/outstanding-balance", "GET", ALL_ROLES)
    def outstanding_balance(user_id, role, lessee_id):
        row = must_get("lessees", lessee_id, "lessee")
        if role == "Lessee" and user_id != row["id"]:
            raise forbidden("A lessee may read the outstanding balance only for its own id.")
        return ok(lessee_balance(row["id"]))

    # ------------------------------------------------------------- lease contracts
    @route(app, "/api/v1/lease-contracts", "POST", LEASE_ADMIN)
    def create_contract(user_id, role):
        body = json_body()
        lessee = fk(body, "lessee_id", "lessees", "lessee_id")
        lease_type = require_enum(body, "lease_type", LEASE_TYPES)
        rate = require_int(body, "per_diem_rate_cents", minimum=0)
        bearer = require_enum(body, "liability_bearer", LIABILITY_BEARERS)
        start = require_date(body, "term_start_date")
        end = require_date(body, "term_end_date")
        cap = require_int(body, "fleet_car_cap", minimum=0)
        if to_date(end) <= to_date(start):
            raise invalid_request("term_end_date must be after term_start_date.")
        row = store.new_row({
            "lessee_id": lessee["id"], "lease_type": lease_type,
            "per_diem_rate_cents": rate, "liability_bearer": bearer,
            "term_start_date": start, "term_end_date": end,
            "status": "DRAFT", "amendment_seq": 0,
            "capital_allocation_cents": 0, "fleet_car_cap": cap,
            "draft_per_diem_rate_cents": None, "draft_liability_bearer": None,
        })
        store.put("lease_contracts", row)
        return created(view("lease_contracts", row))

    @route(app, "/api/v1/lease-contracts", "GET", ALL_ROLES)
    def list_contracts(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("lease_contracts")), request.args,
                        {"status": "status", "lessee_id": "lessee_id"})
        return list_response(rows, limit, offset, lambda r: view("lease_contracts", r))

    @route(app, "/api/v1/lease-contracts/{contract_id}", "GET", ALL_ROLES)
    def get_contract(user_id, role, contract_id):
        row = must_get("lease_contracts", contract_id, "lease contract")
        return ok(view("lease_contracts", row))

    @route(app, "/api/v1/lease-contracts/{contract_id}/activate", "POST", LEASE_ADMIN)
    def activate_contract(user_id, role, contract_id):
        contract = must_get("lease_contracts", contract_id, "lease contract")
        if contract["status"] != "DRAFT":
            raise invalid_state("Only a drafted contract may be activated.")
        if to_date(contract["term_end_date"]) <= clock.date:
            raise invalid_state("A lapsed term can never be activated.")
        placements = [a for a in store.all("car_assignments")
                      if a["lease_contract_id"] == contract["id"]]
        for i, first in enumerate(placements):
            for second in placements[i + 1:]:
                if intervals_collide(first["start_date"], first["end_date"],
                                     second["start_date"], second["end_date"]):
                    raise ApiError("ERR_ASSIGNMENT_OVERLAP",
                                   "Placements under this contract hold overlapping "
                                   "date intervals.")
        contract["status"] = "ACTIVE"
        store.touch(contract)
        return ok(view("lease_contracts", contract))

    @route(app, "/api/v1/lease-contracts/{contract_id}/amendments", "POST", LEASE_ADMIN)
    def draft_amendment(user_id, role, contract_id):
        contract = must_get("lease_contracts", contract_id, "lease contract")
        body = json_body()
        # a contract still in AMENDMENT_DRAFTED may legitimately be redrafted
        if contract["status"] not in ("ACTIVE", "AMENDMENT_DRAFTED"):
            raise invalid_state("Only an active or amendment-drafted contract may be amended.")
        expected = body.get("expected_lease_version")
        if expected is None or str(expected) == "":
            raise invalid_request("expected_lease_version is required.")
        try:
            expected_int = int(expected)
        except (TypeError, ValueError):
            raise invalid_request("expected_lease_version must be an integer.")
        if expected_int != int(contract["version"]):
            raise stale_version()
        rate = require_int(body, "per_diem_rate_cents", minimum=0)
        bearer = require_enum(body, "liability_bearer", LIABILITY_BEARERS)
        # PRD 3.5: "A successful draft stores the proposed rate and bearer on
        # the contract draft" -- the drafted terms live on the contract row, so
        # a second draft's terms supersede the first's before ratification.
        contract["status"] = "AMENDMENT_DRAFTED"
        contract["per_diem_rate_cents"] = rate
        contract["liability_bearer"] = bearer
        contract["draft_per_diem_rate_cents"] = rate
        contract["draft_liability_bearer"] = bearer
        store.touch(contract)
        return ok(view("lease_contracts", contract))

    @route(app, "/api/v1/lease-contracts/{contract_id}/amendments/ratify", "POST", LEASE_ADMIN)
    def ratify_amendment(user_id, role, contract_id):
        contract = must_get("lease_contracts", contract_id, "lease contract")
        body = json_body()
        if contract["status"] != "AMENDMENT_DRAFTED":
            raise invalid_state("Only an amendment-drafted contract may be ratified.")
        expected = body.get("expected_lease_version")
        if expected is None or str(expected) == "":
            raise invalid_request("expected_lease_version is required.")
        try:
            expected_int = int(expected)
        except (TypeError, ValueError):
            raise invalid_request("expected_lease_version must be an integer.")
        if expected_int != int(contract["version"]):
            raise stale_version()
        if contract.get("draft_per_diem_rate_cents") is not None:
            contract["per_diem_rate_cents"] = contract["draft_per_diem_rate_cents"]
        if contract.get("draft_liability_bearer"):
            contract["liability_bearer"] = contract["draft_liability_bearer"]
        contract["status"] = "ACTIVE"
        contract["amendment_seq"] = int(contract["amendment_seq"]) + 1

        for assignment in store.all("car_assignments"):
            if assignment["lease_contract_id"] != contract["id"]:
                continue
            if assignment["status"] == "ACTIVE":
                assignment["per_diem_rate_cents"] = contract["per_diem_rate_cents"]
                assignment["per_diem_accrued_cents"] = calc.per_diem_accrued_restated(assignment)
            ret = latest_return_for_assignment(assignment["id"])
            if ret is None:
                assignment["maintenance_cost_cents"] = 0
            else:
                parts = CONDITION_PARTS_CENTS[ret["condition_grade"]]
                lessor_share, _ = maintenance_split(parts, contract)
                assignment["maintenance_cost_cents"] = lessor_share
            store.touch(assignment)
        store.touch(contract)
        return ok(view("lease_contracts", contract))

    @route(app, "/api/v1/lease-contracts/{contract_id}/terminate", "POST", LEASE_ADMIN)
    def terminate_contract(user_id, role, contract_id):
        contract = must_get("lease_contracts", contract_id, "lease contract")
        body = json_body()
        if contract["status"] != "ACTIVE":
            raise invalid_state("Only an active contract may be terminated.")
        live = [a for a in store.all("car_assignments")
                if a["lease_contract_id"] == contract["id"]
                and a["status"] in ("ACTIVE", "SUSPENDED")]
        enumerated = body.get("cascade_assignment_ids") or []
        if not isinstance(enumerated, list):
            raise invalid_request("cascade_assignment_ids must be a list.")
        if live and set(a["id"] for a in live) - set(str(x) for x in enumerated):
            raise invalid_state(
                "Every live placement of this contract must be enumerated in "
                "cascade_assignment_ids.")
        contract["status"] = "TERMINATED"
        for assignment in live:
            assignment["status"] = "COMPLETED"
            store.touch(assignment)
            car = store.get("fleet_cars", assignment["lease_fleet_car_id"])
            if car is not None:
                car["status"] = "HELD"
                store.touch(car)
        store.touch(contract)
        return ok(view("lease_contracts", contract))

    # ---------------------------------------------------------------- fleet cars
    @route(app, "/api/v1/lease-fleet-cars", "GET", ALL_ROLES)
    def list_fleet_cars(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("fleet_cars")), request.args,
                        {"status": "status", "car_type_id": "car_type_id",
                         "lease_contract_id": "lease_contract_id",
                         "production_order_id": "production_order_id"})
        return list_response(rows, limit, offset, lambda r: view("fleet_cars", r))

    @route(app, "/api/v1/lease-fleet-cars/{car_id}", "GET", ALL_ROLES)
    def get_fleet_car(user_id, role, car_id):
        row = must_get("fleet_cars", car_id, "lease fleet car")
        return ok(view("fleet_cars", row))

    @route(app, "/api/v1/lease-fleet-cars/{car_id}/settle-returns", "POST", PLANNER)
    def settle_returns(user_id, role, car_id):
        car = must_get("fleet_cars", car_id, "lease fleet car")
        if car["status"] != "UNDER_REPAIR":
            raise invalid_state("Only a car under repair may leave the repair queue.")
        pending = [r for r in store.all("car_returns")
                   if r["lease_fleet_car_id"] == car["id"] and r["settlement_status"] != "SETTLED"]
        if pending:
            raise ApiError("ERR_UNSETTLED_RETURNS",
                           "Every return of this car must be settled first.")
        car["status"] = "HELD"
        car["lease_contract_id"] = None
        calc.recompute_car_derived(car)
        store.touch(car)
        return ok(view("fleet_cars", car))

    @route(app, "/api/v1/lease-fleet-cars/{car_id}/scrap", "POST", PORTFOLIO)
    def scrap_car(user_id, role, car_id):
        car = must_get("fleet_cars", car_id, "lease fleet car")
        body = json_body()
        if car["status"] != "HELD":
            raise ApiError("ERR_CAR_NOT_HELD", "Only a car in HELD status may be scrapped.")
        car["status"] = "SCRAPPED"
        order = store.get("production_orders", car.get("production_order_id"))
        if order is not None:
            contract_id = order.get("_lease_contract_id") or car.get("lease_contract_id")
            contract = store.get("lease_contracts", contract_id)
            if contract is not None:
                contract["capital_allocation_cents"] = calc.capital_allocation_for_order(order)
                store.touch(contract)
        for wo in list(store.all("retrofit_work_orders")):
            if wo["lease_fleet_car_id"] != car["id"]:
                continue
            if wo["status"] == "SCHEDULED":
                store.delete("retrofit_work_orders", wo["id"])
            else:
                wo["status"] = "CANCELLED"
                store.touch(wo)
        store.touch(car)
        return ok(view("fleet_cars", car))

    # ---------------------------------------------------------------- assignments
    @route(app, "/api/v1/car-assignments", "POST", LEASE_ADMIN)
    def create_assignment(user_id, role):
        body = json_body()
        car = fk(body, "lease_fleet_car_id", "fleet_cars", "lease_fleet_car_id")
        contract = fk(body, "lease_contract_id", "lease_contracts", "lease_contract_id")
        lessee = fk(body, "lessee_id", "lessees", "lessee_id")
        start = require_date(body, "start_date")
        end = require_date(body, "end_date")
        allowance = require_int(body, "mileage_allowance", minimum=0)

        if contract["status"] != "ACTIVE":
            raise invalid_state("The target contract must be ACTIVE.")
        if calc.car_is_enrolled(car):
            raise invalid_state("A car enrolled in a retrofit program cannot be placed.")
        # precedence 8: regulatory life, inclusive of the end date
        life_end = car.get("regulatory_life_end_date") or calc.regulatory_life_end(car)
        if to_date(life_end) < to_date(start):
            raise ApiError("ERR_REGULATORY_LIFE_EXCEEDED",
                           "The car is at or past the end of its regulatory life.")
        # precedence 11: placement buffering
        for other in store.all("car_assignments"):
            if other["lease_fleet_car_id"] != car["id"]:
                continue
            if buffered_collision(start, end, other["start_date"], other["end_date"]):
                raise ApiError("ERR_ASSIGNMENT_OVERLAP",
                               "The placement interval collides with another placement "
                               "of this car, or violates the one-day buffer.")
        # precedence 18: credit exposure
        projected = projected_placement_charge(contract, lessee, start, end)
        if int(lessee["outstanding_balance_cents"]) + projected > int(lessee["credit_ceiling_cents"]):
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                           "The lessee's balance plus the projected charge exceeds its "
                           "credit ceiling.")
        # precedence 21: car availability
        if car["status"] != "HELD":
            raise ApiError("ERR_CAR_NOT_HELD", "The car must be in HELD status.")
        # precedence 22: lessee correspondence
        if lessee["id"] != contract["lessee_id"]:
            raise ApiError("ERR_LESSEE_MISMATCH",
                           "The lessee named in the request is not the lessee of the "
                           "referenced contract.")

        row = store.new_row({
            "lease_fleet_car_id": car["id"], "lease_contract_id": contract["id"],
            "start_date": start, "end_date": end,
            "per_diem_rate_cents": int(contract["per_diem_rate_cents"]),
            "mileage_allowance": allowance, "mileage_used": 0,
            "per_diem_accrued_cents": 0, "mileage_charge_cents": 0,
            "maintenance_cost_cents": 0, "status": "ACTIVE",
        })
        store.put("car_assignments", row)
        row["per_diem_accrued_cents"] = per_diem_accrued_open(row)
        car["status"] = "ASSIGNED"
        car["lease_contract_id"] = contract["id"]
        store.touch(car)
        return created(view("car_assignments", row))

    @route(app, "/api/v1/car-assignments", "GET", ALL_ROLES)
    def list_assignments(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("car_assignments")), request.args,
                        {"status": "status", "lease_fleet_car_id": "lease_fleet_car_id",
                         "lease_contract_id": "lease_contract_id"})
        return list_response(rows, limit, offset, lambda r: view("car_assignments", r))

    @route(app, "/api/v1/car-assignments/{assignment_id}", "GET", ALL_ROLES)
    def get_assignment(user_id, role, assignment_id):
        row = must_get("car_assignments", assignment_id, "car assignment")
        return ok(view("car_assignments", row))

    @route(app, "/api/v1/car-assignments/{assignment_id}/suspend", "POST", LEASE_ADMIN)
    def suspend_assignment(user_id, role, assignment_id):
        assignment = must_get("car_assignments", assignment_id, "car assignment")
        body = json_body()
        suspend_date = optional_date(body, "suspend_date", default=None)
        car = store.get("fleet_cars", assignment["lease_fleet_car_id"])
        contract = store.get("lease_contracts", assignment["lease_contract_id"])
        if assignment["status"] != "ACTIVE":
            raise invalid_state("Only an active placement may be suspended.")
        if car is None or car["status"] != "ASSIGNED":
            raise invalid_state("The parent car must be ASSIGNED.")
        if contract is None or contract["status"] != "ACTIVE":
            raise invalid_state("The governing contract must be ACTIVE.")
        assignment["status"] = "SUSPENDED"
        assignment["per_diem_accrued_cents"] = per_diem_accrued_open(assignment, suspend_date)
        car["status"] = "HELD"
        store.touch(assignment)
        store.touch(car)
        return ok(view("car_assignments", assignment))

    @route(app, "/api/v1/car-assignments/{assignment_id}/resume", "POST", LEASE_ADMIN)
    def resume_assignment(user_id, role, assignment_id):
        assignment = must_get("car_assignments", assignment_id, "car assignment")
        car = store.get("fleet_cars", assignment["lease_fleet_car_id"])
        contract = store.get("lease_contracts", assignment["lease_contract_id"])
        if assignment["status"] not in ("SUSPENDED", "REASSIGNED"):
            raise invalid_state("Only a suspended or reassigned placement may be resumed.")
        if contract is None or contract["status"] != "ACTIVE":
            raise invalid_state("The governing contract must be ACTIVE.")
        if car is None or car["status"] != "HELD":
            raise invalid_state("The parent car must be HELD.")
        assignment["status"] = "ACTIVE"
        car["status"] = "ASSIGNED"
        store.touch(assignment)
        store.touch(car)
        return ok(view("car_assignments", assignment))

    @route(app, "/api/v1/car-assignments/{assignment_id}/reassign", "POST", LEASE_ADMIN)
    def reassign_assignment(user_id, role, assignment_id):
        assignment = must_get("car_assignments", assignment_id, "car assignment")
        body = json_body()
        target = fk(body, "target_lease_fleet_car_id", "fleet_cars",
                    "target_lease_fleet_car_id")
        source_car = store.get("fleet_cars", assignment["lease_fleet_car_id"])
        if assignment["status"] != "ACTIVE":
            raise invalid_state("Only an active placement may be reassigned.")
        # PRD 2.11 enumerates ERR_CAR_NOT_HELD for sale creation, placement
        # creation, retrofit work-order creation and scrapping only; the
        # reassignment target's HELD precondition is a state-legality breach.
        if target["status"] != "HELD":
            raise invalid_state("The target car must be in HELD status.")
        if target.get("lease_contract_id") != assignment["lease_contract_id"]:
            raise invalid_state(
                "The target car must carry the same lease_contract_id as the source car.")
        assignment["status"] = "REASSIGNED"
        store.touch(assignment)
        if source_car is not None:
            source_car["status"] = "HELD"
            store.touch(source_car)
        contract = store.get("lease_contracts", assignment["lease_contract_id"])
        replacement = store.new_row({
            "lease_fleet_car_id": target["id"],
            "lease_contract_id": assignment["lease_contract_id"],
            "start_date": assignment["end_date"], "end_date": assignment["end_date"],
            "per_diem_rate_cents": int(contract["per_diem_rate_cents"]) if contract else
            int(assignment["per_diem_rate_cents"]),
            "mileage_allowance": assignment["mileage_allowance"], "mileage_used": 0,
            "per_diem_accrued_cents": 0, "mileage_charge_cents": 0,
            "maintenance_cost_cents": 0, "status": "ACTIVE",
        })
        store.put("car_assignments", replacement)
        replacement["per_diem_accrued_cents"] = per_diem_accrued_open(replacement)
        target["status"] = "ASSIGNED"
        target["lease_contract_id"] = assignment["lease_contract_id"]
        store.touch(target)
        return ok(view("car_assignments", assignment))

    # -------------------------------------------------------------------- returns
    @route(app, "/api/v1/car-returns", "POST", LEASE_ADMIN)
    def create_return(user_id, role):
        body = json_body()
        car = fk(body, "lease_fleet_car_id", "fleet_cars", "lease_fleet_car_id")
        assignment = fk(body, "car_assignment_id", "car_assignments", "car_assignment_id")
        return_date = require_date(body, "return_date")
        mileage = require_int(body, "mileage_since_last", minimum=0)
        grade = require_enum(body, "condition_grade", CONDITION_GRADES)

        if assignment["status"] not in ("ACTIVE", "SUSPENDED"):
            raise invalid_state("Only an active or suspended placement may be closed.")
        if to_date(return_date) <= to_date(assignment["start_date"]):
            raise invalid_request("return_date must be strictly later than the "
                                  "placement's start_date.")
        for other in store.all("car_assignments"):
            if other["id"] == assignment["id"] or other["lease_fleet_car_id"] != car["id"]:
                continue
            if intervals_collide(assignment["start_date"], return_date,
                                 other["start_date"], other["end_date"]):
                raise ApiError("ERR_ASSIGNMENT_OVERLAP",
                               "Another placement of this car overlaps the interval "
                               "being closed.")
        contract = store.get("lease_contracts", assignment["lease_contract_id"])
        lessee = store.get("lessees", contract["lessee_id"]) if contract else None

        projected_used = int(assignment["mileage_used"]) + mileage
        probe = dict(assignment)
        probe["mileage_used"] = projected_used
        projected_charge = mileage_true_up(probe)
        if lessee is not None and int(lessee["outstanding_balance_cents"]) + projected_charge \
                > int(lessee["credit_ceiling_cents"]):
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                           "The lessee's balance plus the projected mileage charge "
                           "exceeds its credit ceiling.")

        parts = CONDITION_PARTS_CENTS[grade]
        lessor_share, _ = maintenance_split(parts, contract)
        row = store.new_row({
            "lease_fleet_car_id": car["id"], "car_assignment_id": assignment["id"],
            "return_date": return_date, "mileage_since_last": mileage,
            "condition_grade": grade, "maintenance_parts_cents": parts,
            "mileage_overage_cents": projected_charge, "settlement_status": "PENDING",
        })
        store.put("car_returns", row)

        assignment["mileage_used"] = projected_used
        assignment["mileage_charge_cents"] = projected_charge
        assignment["maintenance_cost_cents"] = lessor_share
        assignment["status"] = "COMPLETED"
        # PRD 3.6: a restated accrual is produced at a return, because closing
        # the placement rewrites its history rather than merely continuing it.
        calc.recompute_assignment_accrual(assignment, restated=True)
        car["status"] = "UNDER_REPAIR"
        calc.recompute_car_derived(car)
        store.touch(assignment)
        store.touch(car)
        if lessee is not None:
            recompute_lessee_balance(lessee)
        return created(view("car_returns", row))

    @route(app, "/api/v1/car-returns", "GET", ALL_ROLES)
    def list_returns(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("car_returns")), request.args,
                        {"lease_fleet_car_id": "lease_fleet_car_id",
                         "car_assignment_id": "car_assignment_id",
                         "settlement_status": "settlement_status"})
        return list_response(rows, limit, offset, lambda r: view("car_returns", r))

    @route(app, "/api/v1/car-returns/{return_id}", "GET", ALL_ROLES)
    def get_return(user_id, role, return_id):
        row = must_get("car_returns", return_id, "car return")
        return ok(view("car_returns", row))

    @route(app, "/api/v1/car-returns/{return_id}/settle", "POST", PORTFOLIO)
    def settle_return(user_id, role, return_id):
        row = must_get("car_returns", return_id, "car return")
        if row["settlement_status"] != "PENDING":
            raise invalid_state("Only a pending return may be settled.")
        row["settlement_status"] = "SETTLED"
        assignment = store.get("car_assignments", row["car_assignment_id"])
        contract = store.get("lease_contracts", assignment["lease_contract_id"]) \
            if assignment else None
        if contract is not None:
            lessee = store.get("lessees", contract["lessee_id"])
            if lessee is not None:
                recompute_lessee_balance(lessee)
        store.touch(row)
        return ok(view("car_returns", row))


def latest_return_for_assignment(assignment_id):
    rows = store.sorted_rows([r for r in store.all("car_returns")
                              if r["car_assignment_id"] == assignment_id])
    return rows[-1] if rows else None
