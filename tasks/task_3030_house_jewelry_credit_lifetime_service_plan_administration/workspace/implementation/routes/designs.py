"""Custom design commissions: deposits, CAD revisions, production and cancellation."""

from flask import request

from constants import CAD_REVISION_FEE_CENTS, DEPOSIT_PCT_MIN
from db import DB
from middleware import guard, require_owner
from response import (ApiError, Err, as_int, as_num, as_str, body, created_obj,
                      ensure_known, invalid_state, ok_list, ok_obj, pagination,
                      sorted_by_created)
from services import core

READ_ROLES = ["ChainAdmin", "StoreManager", "SalesAssociate", "CustomerService"]


def register(app):
    @app.route("/custom-design-orders", methods=["POST"])
    def create_design():
        guard(["SalesAssociate", "StoreManager"])
        data = body()
        ensure_known(data, ["customer_id", "store_id", "estimate_amount_cents",
                            "deposit_pct"],
                     optional=("deposit_pct",))
        customer_id = as_str(data, "customer_id")
        store_id = as_str(data, "store_id")
        estimate = as_int(data, "estimate_amount_cents", required=True)
        deposit_pct = as_num(data, "deposit_pct", default=0.30)

        customer = core.fetch("customers", customer_id, "customer")
        core.fetch("stores", store_id, "store")

        # Priority 8: frozen credit hazard.
        if core.has_defaulted_plan(customer["id"]):
            raise ApiError(Err.CREDIT_FROZEN)
        # Priority 9: the account carrying the obligation must be OPEN.
        if customer["account_status"] != "OPEN":
            raise ApiError(Err.ACCOUNT_NOT_OPEN)
        # Priority 29: the deposit percentage floor.
        if deposit_pct < DEPOSIT_PCT_MIN:
            raise ApiError(Err.INSUFFICIENT_DEPOSIT)
        from constants import DEPOSIT_PCT_MAX
        if deposit_pct > DEPOSIT_PCT_MAX:
            raise ApiError(Err.INSUFFICIENT_DEPOSIT,
                           "The deposit percentage exceeds the permitted ceiling.")

        design = core.new_row(
            "designs",
            customer_id=customer_id,
            store_id=store_id,
            estimate_amount_cents=estimate,
            deposit_cents=core.design_deposit(estimate, deposit_pct),
            deposit_pct=deposit_pct,
            revision_count=0,
            free_revisions_used=0,
            revision_fee_cents=0,
            design_status="DEPOSIT_PAID",
            approved_at=None,
            cancellation_fee_cents=0,
            non_refundable_deposit_cents=0,
            refundable_deposit_cents=0,
        )
        core.design_derived(design)
        return created_obj(design)

    @app.route("/custom-design-orders", methods=["GET"])
    def list_designs():
        guard(READ_ROLES)
        limit, offset = pagination()
        rows = DB.all("designs")
        for field in ("customer_id", "store_id", "design_status"):
            value = request.args.get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/custom-design-orders/<ident>", methods=["GET"])
    def get_design(ident):
        guard(READ_ROLES)
        return ok_obj(core.fetch("designs", ident, "custom design order"))

    @app.route("/custom-design-orders/<ident>/revisions", methods=["POST"])
    def request_revision(ident):
        user_id, role = guard(["Customer"])
        design = core.fetch("designs", ident, "custom design order")
        require_owner(user_id, role, design)
        if design["design_status"] not in ("DEPOSIT_PAID", "CAD_REVISION"):
            raise invalid_state("This commission cannot take a revision from its status.")
        # Priority 30: at most five revisions.
        if design["revision_count"] >= 5:
            raise ApiError(Err.REVISION_LIMIT_REACHED)
        design["revision_count"] += 1
        if design["revision_count"] <= 2:
            design["free_revisions_used"] += 1
        else:
            design["revision_fee_cents"] += CAD_REVISION_FEE_CENTS
        design["design_status"] = "CAD_REVISION"
        core.design_derived(design)
        core.touch(design)
        return ok_obj(design)

    @app.route("/custom-design-orders/<ident>/cad-approval", methods=["POST"])
    def approve_cad(ident):
        user_id, role = guard(["Customer"])
        design = core.fetch("designs", ident, "custom design order")
        require_owner(user_id, role, design)
        if design["design_status"] != "CAD_REVISION":
            raise invalid_state("Only a CAD_REVISION commission may be approved.")
        design["design_status"] = "CAD_APPROVED"
        design["approved_at"] = __import__("db").iso(DB.now())
        core.design_derived(design)
        core.touch(design)
        return ok_obj(design)

    @app.route("/custom-design-orders/<ident>/start-production", methods=["POST"])
    def start_production(ident):
        guard(["StoreManager"])
        design = core.fetch("designs", ident, "custom design order")
        if design["design_status"] != "CAD_APPROVED":
            raise invalid_state("Only a CAD_APPROVED commission may be released.")
        customer = core.fetch("customers", design["customer_id"], "customer")
        # Priority 8 then 9.
        if core.has_defaulted_plan(customer["id"]):
            raise ApiError(Err.CREDIT_FROZEN)
        if customer["account_status"] != "OPEN":
            raise ApiError(Err.ACCOUNT_NOT_OPEN)
        design["design_status"] = "IN_PRODUCTION"
        core.design_derived(design)
        core.touch(design)
        return ok_obj(design)

    @app.route("/custom-design-orders/<ident>/recall", methods=["POST"])
    def recall_design(ident):
        guard(["StoreManager"])
        data = body()
        ensure_known(data, ["variance_pct"])
        variance = as_num(data, "variance_pct", required=True)
        design = core.fetch("designs", ident, "custom design order")
        if design["design_status"] != "IN_PRODUCTION":
            raise invalid_state("Only an IN_PRODUCTION commission may be recalled.")
        if variance <= 0.10:
            raise invalid_state("The revised quote is inside the ten percent band.")
        # The recall reverts out of production; the customer declines the
        # variance, so the design settles back to DEPOSIT_PAID.
        design["design_status"] = "DEPOSIT_PAID"
        core.design_derived(design)
        core.touch(design)
        return ok_obj(design)

    @app.route("/custom-design-orders/<ident>/complete", methods=["POST"])
    def complete_design(ident):
        guard(["StoreManager"])
        design = core.fetch("designs", ident, "custom design order")
        if design["design_status"] != "IN_PRODUCTION":
            raise invalid_state("Only an IN_PRODUCTION commission may be completed.")
        customer = core.fetch("customers", design["customer_id"], "customer")
        if core.has_defaulted_plan(customer["id"]):
            raise ApiError(Err.CREDIT_FROZEN)
        required = design["estimate_amount_cents"] + design["revision_fee_cents"]
        ceiling = 0
        for application in DB.all("credit_applications"):
            if application["customer_id"] == customer["id"] and \
                    application["decision_status"] == "APPROVED":
                ceiling = max(ceiling, application["approved_limit_cents"])
        # Priority 20: the approved credit must reach estimate plus revision fees.
        if ceiling < required:
            raise ApiError(Err.CREDIT_LIMIT_EXCEEDED)

        design["design_status"] = "COMPLETED"
        core.design_derived(design)
        core.touch(design)
        purchase = core.new_row(
            "purchases",
            customer_id=design["customer_id"],
            store_id=design["store_id"],
            diamond_id=None,
            bundle_id=None,
            base_price_cents=required,
            origin_purchase_id=None,
            trade_up_credit_cents=0,
            trade_up_floor_cents=0,
            net_amount_cents=0,
            protection_fee_cents=0,
            purchase_status="PENDING",
            completed_at=None,
        )
        core.recompute_purchase_amounts(purchase)
        return ok_obj(design)

    @app.route("/custom-design-orders/<ident>/cancel", methods=["POST"])
    def cancel_design(ident):
        user_id, role = guard(["Customer", "StoreManager"])
        design = core.fetch("designs", ident, "custom design order")
        require_owner(user_id, role, design)
        current = design["design_status"]
        if current in ("IN_PRODUCTION", "COMPLETED", "CANCELLED"):
            if current == "CANCELLED":
                raise invalid_state("The commission is already CANCELLED.")
            if current == "COMPLETED":
                raise invalid_state("A completed commission cannot be cancelled.")

        before = current
        design["design_status"] = "CANCELLED"
        design["cancellation_fee_cents"] = core.cancellation_fee_for(design, before)
        non_refundable = core.non_refundable_for(design, before)
        design["non_refundable_deposit_cents"] = non_refundable
        design["refundable_deposit_cents"] = design["deposit_cents"] - non_refundable

        if before == "DEPOSIT_PAID" and design["refundable_deposit_cents"]:
            plan = _plan_for_design(design)
            if plan is not None:
                core.append_ledger_entry(plan, "TRADE_UP_CREDIT", "DECREASE",
                                         design["refundable_deposit_cents"], 0)
                core.touch(plan)
        core.touch(design)
        return ok_obj(design)


def _plan_for_design(design):
    for plan in DB.all("promotional_plans"):
        if plan["customer_id"] == design["customer_id"] and \
                plan["plan_status"] in ("ACCRUING", "CAPITALIZED"):
            return plan
    return None