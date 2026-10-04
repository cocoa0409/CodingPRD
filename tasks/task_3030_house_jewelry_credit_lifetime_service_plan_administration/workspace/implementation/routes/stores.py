"""Stores: open, read, activate, suspend and reinstate."""

from db import DB
from middleware import guard
from response import (ApiError, Err, as_bool, as_int, as_str, body, created_obj,
                      ensure_known, invalid_state, ok_obj, sorted_by_created)
from services import core

ALL_ROLES = ["ChainAdmin", "StoreManager", "CreditAnalyst", "SalesAssociate", "CustomerService"]


def register(app):
    @app.route("/stores", methods=["POST"])
    def create_store():
        guard(["ChainAdmin"])
        data = body()
        ensure_known(data, ["store_code", "name", "state_code", "credit_capacity_cents",
                            "credit_enabled", "store_hold_days"],
                     optional=("credit_enabled", "store_hold_days"))
        store = core.new_row(
            "stores",
            store_code=as_str(data, "store_code"),
            name=as_str(data, "name"),
            state_code=as_str(data, "state_code"),
            credit_capacity_cents=as_int(data, "credit_capacity_cents", required=True),
            credit_enabled=as_bool(data, "credit_enabled", default=True),
            store_status="OPEN",
            store_hold_days=as_int(data, "store_hold_days", default=30),
            available_credit_capacity_cents=0,
            store_absorbed_total_cents=0,
            open_repair_liability_cents=0,
            open_inspection_count=0,
        )
        core.recompute_store(store)
        return created_obj(store)

    @app.route("/stores", methods=["GET"])
    def list_stores():
        guard(ALL_ROLES)
        from response import pagination
        limit, offset = pagination()
        rows = core.DB.all("stores")
        status = request_arg("store_status")
        if status:
            rows = [r for r in rows if r["store_status"] == status]
        state = request_arg("state_code")
        if state:
            rows = [r for r in rows if r["state_code"] == state]
        from response import ok_list
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/stores/<ident>", methods=["GET"])
    def get_store(ident):
        guard(ALL_ROLES)
        store = core.fetch("stores", ident, "store")
        core.recompute_store(store)
        return ok_obj(store)

    @app.route("/stores/<ident>/activate", methods=["POST"])
    def activate_store(ident):
        guard(["ChainAdmin"])
        store = core.fetch("stores", ident, "store")
        if store["store_status"] != "OPEN":
            raise invalid_state("Only an OPEN store may be activated.")
        has_row = any(row["registry_key"] == store["state_code"] for row in DB.all("registry")) \
            or any(row["registry_key"] == row["all_states_key"] for row in DB.all("registry"))
        if not has_row:
            raise ApiError(Err.REGISTRY_ROW_MISSING,
                           "No registry row is available on this state or the global fallback.")
        store["store_status"] = "ACTIVE"
        core.touch(store)
        return ok_obj(store)

    @app.route("/stores/<ident>/suspend", methods=["POST"])
    def suspend_store(ident):
        guard(["ChainAdmin"])
        store = core.fetch("stores", ident, "store")
        core.recompute_store(store)
        if store["store_status"] != "ACTIVE":
            raise invalid_state("Only an ACTIVE store may be suspended.")
        if store["open_repair_liability_cents"] <= store["available_credit_capacity_cents"]:
            raise ApiError(Err.INVALID_STATE,
                           "The store's liability has not outrun its credit capacity.")
        store["store_status"] = "SUSPENDED"
        for application in DB.all("credit_applications"):
            if application["store_id"] == store["id"] and application["decision_status"] == "PENDING":
                application["decision_status"] = "DECLINED"
                core.touch(application)
        core.touch(store)
        return ok_obj(store)

    @app.route("/stores/<ident>/reinstate", methods=["POST"])
    def reinstate_store(ident):
        guard(["ChainAdmin"])
        store = core.fetch("stores", ident, "store")
        core.recompute_store(store)
        if store["store_status"] != "SUSPENDED":
            raise invalid_state("Only a SUSPENDED store may be reinstated.")
        if store["open_repair_liability_cents"] > store["available_credit_capacity_cents"]:
            raise ApiError(Err.INVALID_STATE,
                           "The store's liability is still outside its credit capacity.")
        store["store_status"] = "ACTIVE"
        core.touch(store)
        return ok_obj(store)


def request_arg(name):
    from flask import request
    return request.args.get(name)