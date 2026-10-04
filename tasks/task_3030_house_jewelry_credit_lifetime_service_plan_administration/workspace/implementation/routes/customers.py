"""Customer files: create, read, reinstate and close."""

from flask import request

from db import DB
from middleware import guard
from response import (ApiError, Err, as_str, body, created_obj, ensure_known,
                      invalid_state, ok_list, ok_obj, pagination, sorted_by_created)
from services import core

ALL_ROLES = ["ChainAdmin", "StoreManager", "CreditAnalyst", "SalesAssociate", "CustomerService"]


def register(app):
    @app.route("/customers", methods=["POST"])
    def create_customer():
        guard(["SalesAssociate", "CustomerService", "ChainAdmin"])
        data = body()
        ensure_known(data, ["full_name", "email", "state_code", "phone"],
                     optional=("phone",))
        email = as_str(data, "email")
        if any(c["email"] == email for c in DB.all("customers")):
            raise ApiError(Err.DUPLICATE_EMAIL)
        customer = core.new_row(
            "customers",
            full_name=as_str(data, "full_name"),
            email=email,
            phone=as_str(data, "phone", required=False),
            state_code=as_str(data, "state_code"),
            account_status="NO_FILE",
            credit_tier="NO_FILE",
            standalone_credit_limit_cents=0,
            revolving_utilization_bps=0,
            lifetime_purchase_cents=0,
            outstanding_balance_cents=0,
            lost_inspection_streak=0,
        )
        return created_obj(customer)

    @app.route("/customers", methods=["GET"])
    def list_customers():
        guard(ALL_ROLES)
        limit, offset = pagination()
        rows = DB.all("customers")
        for field in ("state_code", "account_status", "credit_tier"):
            value = request.args.get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/customers/<ident>", methods=["GET"])
    def get_customer(ident):
        guard(ALL_ROLES)
        return ok_obj(core.fetch("customers", ident, "customer"))

    @app.route("/customers/<ident>/reinstate", methods=["POST"])
    def reinstate_customer(ident):
        guard(["CreditAnalyst"])
        customer = core.fetch("customers", ident, "customer")
        if customer["account_status"] != "SUSPENDED":
            raise invalid_state("Only a SUSPENDED account may be reinstated.")
        if core.has_defaulted_plan(customer["id"]):
            raise ApiError(Err.INVALID_STATE,
                           "A promotional plan of this customer is still DEFAULTED.")
        customer["account_status"] = "OPEN"
        customer["standalone_credit_limit_cents"] = core.registry_limit_for_customer(customer)
        core.recompute_customer(customer)
        core.touch(customer)
        return ok_obj(customer)

    @app.route("/customers/<ident>/close", methods=["POST"])
    def close_customer(ident):
        guard(["CustomerService"])
        customer = core.fetch("customers", ident, "customer")
        if customer["account_status"] == "CLOSED":
            raise invalid_state("The customer file is already CLOSED.")
        core.recompute_customer(customer, tier=False)
        if customer["outstanding_balance_cents"] != 0:
            raise ApiError(Err.CUSTOMER_ACTIVE_OBLIGATIONS,
                           "The customer still carries an outstanding balance.")
        for repair in DB.all("repairs"):
            if repair["customer_id"] == customer["id"] and \
                    repair["repair_status"] in core.CLOSE_BLOCKING_REPAIR_STATES:
                raise ApiError(Err.CUSTOMER_ACTIVE_OBLIGATIONS,
                               "The customer holds a non-terminal repair.")
        for registration in DB.all("registrations"):
            if registration["customer_id"] == customer["id"] and \
                    registration["coverage_status"] in core.CLOSE_BLOCKING_REGISTRATION_STATES:
                raise ApiError(Err.CUSTOMER_ACTIVE_OBLIGATIONS,
                               "The customer holds a live service-plan registration.")

        customer["account_status"] = "CLOSED"
        for registration in DB.all("registrations"):
            if registration["customer_id"] == customer["id"] and \
                    registration["coverage_status"] == "ACTIVE":
                registration["coverage_status"] = "TERMINATED"
                registration["is_valid"] = False
                core.touch(registration)
        for application in DB.all("credit_applications"):
            if application["customer_id"] == customer["id"] and \
                    application["decision_status"] == "PENDING":
                application["decision_status"] = "DECLINED"
                core.touch(application)
        core.touch(customer)
        core.recompute_stores_of_customer(customer["id"])
        return ok_obj(customer)