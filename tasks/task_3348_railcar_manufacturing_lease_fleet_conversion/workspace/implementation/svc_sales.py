"""Secondary-market sales, the portfolio ledger and the logical clock.

Covers PRD sections 3.9 and 2.5.
"""

from flask import request

from store import store, clock, to_date
from errors import ApiError, invalid_state, already_terminal, invalid_request
import calc
from calc import sale_gain_loss, recompute_lessee_balance, recompute_ledger_nbv
from serialize import view, portfolio_ledger, ledger_reconciliation
from web import (route, json_body, ok, created, list_response, parse_pagination,
                 filtered, must_get, require_int, require_str, require_date,
                 optional_int, fk)

ALL_ROLES = ("PlatformAdmin", "SupplyChainCoordinator", "ProductionPlanner",
             "LeaseAdministrator", "PortfolioManager", "RegulatoryRetrofitist",
             "Lessee")
PORTFOLIO = ("PortfolioManager",)


def register(app):
    @route(app, "/api/v1/lease-fleet-sales", "POST", PORTFOLIO)
    def create_sale(user_id, role):
        body = json_body()
        car = fk(body, "lease_fleet_car_id", "fleet_cars", "lease_fleet_car_id")
        contract = fk(body, "lease_contract_id", "lease_contracts",
                      "lease_contract_id", required=False)
        lessee = fk(body, "lessee_id", "lessees", "lessee_id", required=False)
        sale_date = require_date(body, "sale_date")

        # precedence 8: regulatory life, inclusive of the end date
        life_end = car.get("regulatory_life_end_date") or calc.regulatory_life_end(car)
        if to_date(life_end) < to_date(sale_date):
            raise ApiError("ERR_REGULATORY_LIFE_EXCEEDED",
                           "The car is at or past the end of its regulatory life and "
                           "may only be scrapped.")

        # precedence 17: request shape
        buyer_name = require_str(body, "buyer_name")
        sale_price = require_int(body, "sale_price_cents", minimum=0)
        writeback = require_int(body, "writeback_liability_cents", minimum=0)
        optional_int(body, "net_book_value_cents", minimum=0)
        # precedence 21: car availability
        if car["status"] != "HELD":
            raise ApiError("ERR_CAR_NOT_HELD", "The car must be in HELD status.")
        # precedence 22: lessee correspondence
        terminated = contract or store.get("lease_contracts", car.get("lease_contract_id"))
        if lessee is not None and terminated is not None and \
                lessee["id"] != terminated["lessee_id"]:
            raise ApiError("ERR_LESSEE_MISMATCH",
                           "The lessee named in the request is not the lessee of the "
                           "sold car's terminated contract.")

        book, gain = sale_gain_loss(car, sale_price, writeback, sale_date)
        row = store.new_row({
            "lease_fleet_car_id": car["id"],
            "lease_contract_id": terminated["id"] if terminated is not None else None,
            "lessee_id": (lessee or (store.get("lessees", terminated["lessee_id"])
                                     if terminated is not None else None) or {}).get("id")
            if (lessee is not None or terminated is not None) else None,
            "buyer_name": buyer_name, "sale_price_cents": sale_price,
            "net_book_value_cents": book, "writeback_liability_cents": writeback,
            "sale_date": sale_date, "status": "PENDING_SETTLEMENT",
            "gain_loss_cents": gain,
        })
        store.put("fleet_sales", row)
        car["status"] = "SOLD"
        car["lease_contract_id"] = None
        store.touch(car)
        recompute_ledger_nbv()
        if row.get("lessee_id"):
            target = store.get("lessees", row["lessee_id"])
            if target is not None:
                recompute_lessee_balance(target)
        return created(view("fleet_sales", row))

    @route(app, "/api/v1/lease-fleet-sales", "GET", ALL_ROLES)
    def list_sales(user_id, role):
        limit, offset = parse_pagination(request.args)
        rows = filtered(store.sorted_rows(store.all("fleet_sales")), request.args,
                        {"status": "status", "lease_fleet_car_id": "lease_fleet_car_id",
                         "lease_contract_id": "lease_contract_id"})
        return list_response(rows, limit, offset, lambda r: view("fleet_sales", r))

    @route(app, "/api/v1/lease-fleet-sales/{sale_id}", "GET", ALL_ROLES)
    def get_sale(user_id, role, sale_id):
        row = must_get("fleet_sales", sale_id, "lease fleet sale")
        return ok(view("fleet_sales", row))

    @route(app, "/api/v1/lease-fleet-sales/{sale_id}/settle", "POST", PORTFOLIO)
    def settle_sale(user_id, role, sale_id):
        sale = must_get("fleet_sales", sale_id, "lease fleet sale")
        if sale["status"] in ("SETTLED", "VOIDED"):
            raise already_terminal()
        if sale["status"] != "PENDING_SETTLEMENT":
            raise invalid_state("Only a pending sale may be settled.")
        contract = store.get("lease_contracts", sale.get("lease_contract_id"))
        if contract is not None and contract["status"] != "TERMINATED":
            raise invalid_state("The lease contract of the sold car must be TERMINATED.")
        # precedence 20: the settlement must be internally balanced
        if int(sale["gain_loss_cents"]) < 0:
            raise ApiError("ERR_SETTLEMENT_UNBALANCED",
                           "The writeback liability exceeds the gain over book value, "
                           "so the settlement cannot balance.")
        sale["status"] = "SETTLED"
        ledger = store.ledger
        ledger["realized_gain_cents"] = int(ledger["realized_gain_cents"]) + \
            int(sale["gain_loss_cents"])
        recompute_ledger_nbv()
        store.touch(ledger)
        if contract is not None and contract["liability_bearer"] == "LESSEE" and \
                sale.get("lessee_id"):
            lessee = store.get("lessees", sale["lessee_id"])
            if lessee is not None:
                recompute_lessee_balance(lessee)
        store.touch(sale)
        return ok(view("fleet_sales", sale))

    @route(app, "/api/v1/lease-fleet-sales/{sale_id}/void", "POST", PORTFOLIO)
    def void_sale(user_id, role, sale_id):
        sale = must_get("fleet_sales", sale_id, "lease fleet sale")
        body = json_body()
        if sale["status"] != "PENDING_SETTLEMENT":
            raise invalid_state("Only a pending sale may be voided.")
        sale["status"] = "VOIDED"
        car = store.get("fleet_cars", sale["lease_fleet_car_id"])
        if car is not None:
            car["status"] = "HELD"
            store.touch(car)
        # the void is an erasure: realized_gain_cents is left exactly where it stood
        recompute_ledger_nbv()
        store.touch(sale)
        return ok(view("fleet_sales", sale))

    @route(app, "/api/v1/portfolio-ledger", "GET", ALL_ROLES)
    def get_ledger(user_id, role):
        return ok(portfolio_ledger(store.ledger))

    @route(app, "/api/v1/portfolio-ledger/reconciliation", "GET", ALL_ROLES)
    def get_reconciliation(user_id, role):
        return ok(ledger_reconciliation())

    # ------------------------------------------------------------------- clock
    @route(app, "/api/v1/_clock/set_current_utc", "POST", ("PlatformAdmin",))
    def set_clock(user_id, role):
        body = json_body()
        target = body.get("to_iso8601")
        if target is None or str(target).strip() == "":
            raise invalid_request("to_iso8601 is required.")
        try:
            clock.set(target)
        except (ValueError, TypeError):
            raise invalid_request("to_iso8601 must be an ISO 8601 instant.")
        calc.refresh_enrolled_flags()
        return ok({"current_utc": clock.iso()})

    @route(app, "/api/v1/_clock/current", "GET", ALL_ROLES)
    def get_clock(user_id, role):
        return ok({"current_utc": clock.iso()})
