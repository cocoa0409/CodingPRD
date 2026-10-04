"""Counter credit applications, decisioning and the validity sweep."""

import datetime

from flask import request

from constants import DECISION_VALIDITY_HOURS
from db import DB, iso, parse_dt
from middleware import guard, require_owner
from response import (ApiError, Err, as_enum, as_int, as_str, body, created_obj,
                      ensure_known, invalid_state, ok_list, ok_obj, pagination,
                      sorted_by_created)
from services import core

READ_ROLES = ["ChainAdmin", "CreditAnalyst", "StoreManager", "SalesAssociate", "CustomerService"]


def register(app):
    @app.route("/credit-applications", methods=["POST"])
    def create_application():
        guard(["SalesAssociate", "CustomerService"])
        data = body()
        ensure_known(data, ["customer_id", "store_id", "requested_limit_cents",
                            "requested_purchase_amount_cents", "down_payment_cents",
                            "declared_annual_income_cents", "minimum_down_payment_cents"],
                     optional=("down_payment_cents", "declared_annual_income_cents",
                               "minimum_down_payment_cents"))
        customer_id = as_str(data, "customer_id")
        store_id = as_str(data, "store_id")
        # Priority 3: the flat entity's foreign keys resolve left to right in
        # the order the endpoint's input list declares them.
        core.fetch("customers", customer_id, "customer")
        core.fetch("stores", store_id, "store")

        requested_limit = as_int(data, "requested_limit_cents", required=True)
        purchase_amount = as_int(data, "requested_purchase_amount_cents", required=True)
        down_payment = as_int(data, "down_payment_cents", default=0)
        income = as_int(data, "declared_annual_income_cents", default=None)

        application = core.new_row(
            "credit_applications",
            customer_id=customer_id,
            store_id=store_id,
            requested_limit_cents=requested_limit,
            requested_purchase_amount_cents=purchase_amount,
            declared_annual_income_cents=income,
            down_payment_cents=down_payment,
            minimum_down_payment_cents=as_int(data, "minimum_down_payment_cents", default=0),
            policy_tier=core.policy_tier_for(requested_limit, income),
            decision_status="PENDING",
            decision_tier=None,
            approved_limit_cents=0,
            min_down_payment_required_cents=0,
            down_payment_shortfall_cents=0,
            expires_at=iso(DB.now() + datetime.timedelta(hours=DECISION_VALIDITY_HOURS)),
            decision_rule_id=None,
        )
        return created_obj(application)

    @app.route("/credit-applications", methods=["GET"])
    def list_applications():
        guard(READ_ROLES)
        limit, offset = pagination()
        rows = DB.all("credit_applications")
        for field in ("customer_id", "store_id", "decision_status"):
            value = request.args.get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/credit-applications/<ident>", methods=["GET"])
    def get_application(ident):
        guard(READ_ROLES)
        return ok_obj(core.fetch("credit_applications", ident, "credit application"))

    @app.route("/credit-applications/<ident>/decision", methods=["POST"])
    def decide_application(ident):
        guard(["CreditAnalyst"])
        data = body()
        ensure_known(data, ["decision"])
        decision = as_enum(data, "decision", ("APPROVE_FULL", "APPROVE_COUNTERED", "DECLINE"))
        application = core.fetch("credit_applications", ident, "credit application")
        customer = core.fetch("customers", application["customer_id"], "customer")
        store = core.fetch("stores", application["store_id"], "store")

        if application["decision_status"] != "PENDING":
            raise invalid_state("Only a PENDING application may be decided.")
        if decision == "DECLINE":
            application["decision_status"] = "DECLINED"
            core.touch(application)
            return ok_obj(application)

        expires = parse_dt(application.get("expires_at"))
        if expires is not None and DB.now() > expires:
            raise ApiError(Err.WINDOW_EXPIRED,
                           "The application's decision validity window has passed.")
        # Priority 6: the governing regulation must exist before any state or
        # business rule is evaluated.
        if core.regulation_for_state(store["state_code"]) is None:
            raise ApiError(Err.REGULATION_TERMS_VIOLATION,
                           "No lifetime-plan regulation row exists for the store's state.")

        if decision == "APPROVE_FULL":
            if store["store_status"] != "ACTIVE":
                raise invalid_state("The store is not ACTIVE.")
            tier = application["policy_tier"]
        else:
            tier = "TIER_1"

        row = core.select_registry_row(customer["state_code"], tier,
                                       application["requested_limit_cents"])
        if row is None:
            raise ApiError(Err.REGISTRY_ROW_MISSING)
        # Priority 20: the granted ceiling may not exceed the standalone limit
        # implied by the tier priced.
        implied = core.select_registry_row(customer["state_code"], tier,
                                           application["requested_limit_cents"])
        if implied is not None and application["requested_limit_cents"] > implied["base_limit_cents"]:
            raise ApiError(Err.CREDIT_LIMIT_EXCEEDED)

        approved = min(row["base_limit_cents"], application["requested_limit_cents"])
        required = _ceil(row["min_down_payment_pct"],
                         application["requested_purchase_amount_cents"])
        application["decision_tier"] = tier
        application["approved_limit_cents"] = approved
        application["min_down_payment_required_cents"] = required
        application["down_payment_shortfall_cents"] = max(
            0, required - application["down_payment_cents"])
        application["decision_rule_id"] = row["id"]

        if decision == "APPROVE_FULL":
            application["decision_status"] = "APPROVED"
            customer["credit_tier"] = tier
            if customer["account_status"] == "NO_FILE":
                customer["account_status"] = "OPEN"
            customer["standalone_credit_limit_cents"] = approved
        else:
            application["decision_status"] = "COUNTERED"

        core.recompute_customer(customer, tier=False)
        core.touch(application)
        return ok_obj(application)

    @app.route("/credit-applications/<ident>/accept", methods=["POST"])
    def accept_application(ident):
        user_id, role = guard(["Customer"])
        application = core.fetch("credit_applications", ident, "credit application")
        require_owner(user_id, role, application)
        if application["decision_status"] != "COUNTERED":
            raise invalid_state("Only a COUNTERED application may be accepted.")
        expires = parse_dt(application.get("expires_at"))
        if expires is not None and DB.now() > expires:
            raise ApiError(Err.WINDOW_EXPIRED,
                           "The application's validity window has passed.")
        customer = core.fetch("customers", application["customer_id"], "customer")
        application["decision_status"] = "APPROVED"
        customer["credit_tier"] = "TIER_1"
        if customer["account_status"] == "NO_FILE":
            customer["account_status"] = "OPEN"
        customer["standalone_credit_limit_cents"] = application["approved_limit_cents"]
        core.recompute_customer(customer, tier=False)
        core.touch(application)
        return ok_obj(application)

    @app.route("/credit-applications/<ident>/decline-counter", methods=["POST"])
    def decline_counter(ident):
        user_id, role = guard(["Customer"])
        application = core.fetch("credit_applications", ident, "credit application")
        require_owner(user_id, role, application)
        if application["decision_status"] != "COUNTERED":
            raise invalid_state("Only a COUNTERED application may be declined.")
        application["decision_status"] = "DECLINED"
        return ok_obj(application)

    @app.route("/credit-applications/expire-due", methods=["POST"])
    def expire_due():
        guard(["CreditAnalyst"])
        expired = []
        for application in sorted_by_created(DB.all("credit_applications")):
            if application["decision_status"] not in ("PENDING", "COUNTERED"):
                continue
            expires = parse_dt(application.get("expires_at"))
            if expires is not None and DB.now() > expires:
                application["decision_status"] = "EXPIRED"
                core.touch(application)
                expired.append(application["id"])
        return ok_obj({"expired_count": len(expired), "expired_application_ids": expired})


def _ceil(pct, amount):
    from decimal import Decimal, ROUND_CEILING
    value = Decimal(str(pct)) * Decimal(amount)
    return int(value.quantize(Decimal("1"), rounding=ROUND_CEILING))