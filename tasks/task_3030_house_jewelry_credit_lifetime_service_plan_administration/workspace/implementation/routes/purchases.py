"""Purchase tickets, the trade-up console and completion."""

from flask import request

from db import DB, iso
from middleware import guard
from response import (ApiError, Err, as_int, as_str, body, created_obj,
                      ensure_known, invalid_state, ok_list, ok_obj, pagination,
                      sorted_by_created)
from services import core

READ_ROLES = ["ChainAdmin", "StoreManager", "SalesAssociate", "CreditAnalyst", "CustomerService"]


def register(app):
    @app.route("/purchases", methods=["POST"])
    def create_purchase():
        guard(["SalesAssociate"])
        data = body()
        ensure_known(data, ["customer_id", "store_id", "base_price_cents", "diamond_id",
                            "bundle_id", "origin_purchase_id"],
                     optional=("diamond_id", "bundle_id", "origin_purchase_id"))
        customer_id = as_str(data, "customer_id")
        store_id = as_str(data, "store_id")
        base_price = as_int(data, "base_price_cents", required=True)
        diamond_id = as_str(data, "diamond_id", required=False)
        bundle_id = as_str(data, "bundle_id", required=False)
        origin_id = as_str(data, "origin_purchase_id", required=False)

        core.fetch("customers", customer_id, "customer")
        core.fetch("stores", store_id, "store")
        if diamond_id is not None:
            core.fetch("diamonds", diamond_id, "diamond")
        if bundle_id is not None:
            core.fetch("bundles", bundle_id, "protection bundle")
        if origin_id is not None:
            core.fetch("purchases", origin_id, "origin purchase")

        purchase = core.new_row(
            "purchases",
            customer_id=customer_id,
            store_id=store_id,
            diamond_id=diamond_id,
            bundle_id=bundle_id,
            base_price_cents=base_price,
            origin_purchase_id=origin_id,
            trade_up_credit_cents=0,
            trade_up_floor_cents=0,
            net_amount_cents=0,
            protection_fee_cents=0,
            purchase_status="PENDING",
            completed_at=None,
        )
        # The ticket's own trade_up_credit_cents is recomputed, never accepted
        # from the payload, so a supplied value cannot inflate the credit.
        core.recompute_purchase_amounts(purchase)
        return created_obj(purchase)

    @app.route("/purchases", methods=["GET"])
    def list_purchases():
        guard(READ_ROLES)
        limit, offset = pagination()
        rows = DB.all("purchases")
        for field in ("customer_id", "store_id", "diamond_id", "bundle_id",
                      "origin_purchase_id", "purchase_status"):
            value = request.args.get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/purchases/<ident>", methods=["GET"])
    def get_purchase(ident):
        guard(READ_ROLES)
        return ok_obj(core.fetch("purchases", ident, "purchase"))

    @app.route("/purchases/<ident>/trade-up-credit", methods=["POST"])
    def stamp_trade_up_credit(ident):
        guard(["CustomerService", "StoreManager"])
        data = body()
        ensure_known(data, ["additional_credit_cents"])
        additional = as_int(data, "additional_credit_cents", required=True)
        purchase = core.fetch("purchases", ident, "purchase")
        # Priority 26: only the leader of a console may be credited.
        if purchase.get("origin_purchase_id") or \
                purchase["purchase_status"] == "TRADE_UP_APPLIED":
            raise ApiError(Err.TRADE_UP_GUARDIAN_REFERENCE)
        purchase["trade_up_credit_cents"] = (purchase.get("trade_up_credit_cents") or 0) + additional
        core.touch(purchase)
        return ok_obj(purchase)

    @app.route("/purchases/<ident>/trade-up-preview", methods=["GET"])
    def trade_up_preview(ident):
        guard(["SalesAssociate", "StoreManager"])
        purchase = core.fetch("purchases", ident, "purchase")
        override = request.args.get("origin_purchase_id")
        origin = None
        if override:
            origin = core.fetch("purchases", override, "origin purchase")
        else:
            origin = core.resolve_origin(purchase)
        credit, net, fee, due = core.balance_due_after_trade_up(purchase, origin)
        if origin is None and purchase["trade_up_credit_cents"]:
            credit = purchase["trade_up_credit_cents"]
            net = max(0, purchase["base_price_cents"] - credit)
            due = net + fee
        return ok_obj({
            "trade_up_credit_cents": credit,
            "trade_up_floor_cents": core.trade_up_floor(origin) if origin else 0,
            "net_amount_cents": net,
            "balance_due_cents": due,
        })

    @app.route("/purchases/<ident>/complete", methods=["POST"])
    def complete_purchase(ident):
        guard(["SalesAssociate"])
        purchase = core.fetch("purchases", ident, "purchase")
        customer = core.fetch("customers", purchase["customer_id"], "customer")
        store = core.fetch("stores", purchase["store_id"], "store")

        # Priority 4: the ticket must be in PENDING or FINANCED.
        if purchase["purchase_status"] not in ("PENDING", "FINANCED"):
            raise invalid_state("This purchase cannot be completed from its status.")
        # Priority 6: the governing regulation must exist before state and
        # business rules run.
        if core.regulation_for_state(store["state_code"]) is None:
            raise ApiError(Err.REGULATION_TERMS_VIOLATION,
                           "No lifetime-plan regulation row exists for the store's state.")
        # Priority 8: frozen credit outranks every data-validity and fiscal
        # check that would otherwise fire on this request.
        if core.has_defaulted_plan(customer["id"]):
            raise ApiError(Err.CREDIT_FROZEN)
        # Priority 9: the account carrying the obligation must be OPEN.
        if customer["account_status"] != "OPEN":
            raise ApiError(Err.ACCOUNT_NOT_OPEN)

        origin = core.resolve_origin(purchase)
        credit, net, _fee, _due = core.balance_due_after_trade_up(purchase, origin)

        # Priority 20: an approved application must reach the ticket's net amount.
        ceiling = 0
        for application in DB.all("credit_applications"):
            if application["customer_id"] == customer["id"] and \
                    application["decision_status"] == "APPROVED":
                ceiling = max(ceiling, application["approved_limit_cents"])
        if net > ceiling:
            raise ApiError(Err.CREDIT_LIMIT_EXCEEDED)
        # Priority 24: when an origin is named the ticket must reach the floor.
        if origin is not None and purchase["base_price_cents"] < core.trade_up_floor(origin):
            raise ApiError(Err.TRADE_UP_FLOOR_NOT_MET)

        core.recompute_customer(customer, tier=False)
        if customer["outstanding_balance_cents"] + net > \
                customer["standalone_credit_limit_cents"]:
            raise ApiError(Err.CREDIT_LIMIT_EXCEEDED)

        # hop 1
        purchase["purchase_status"] = "COMPLETED"
        purchase["completed_at"] = iso(DB.now())
        core.recompute_purchase_amounts(purchase)
        core.touch(purchase)
        # hop 2
        customer["outstanding_balance_cents"] += purchase["net_amount_cents"]
        customer["lifetime_purchase_cents"] += purchase["base_price_cents"]
        # hop 3
        if purchase.get("diamond_id"):
            diamond = DB.get("diamonds", purchase["diamond_id"])
            if diamond is not None:
                diamond["owner_customer_id"] = customer["id"]
                diamond["custody_status"] = "IN_CASE"
                core.touch(diamond)
        # hop 4
        if origin is not None:
            _apply_trade_up_origin(origin, purchase)
        # hop 5
        _swap_covering_registration(origin, purchase, customer)
        # hop 6
        core.recompute_customer(customer)
        core.recompute_store(store)
        return ok_obj(purchase)


def _apply_trade_up_origin(origin, purchase):
    origin["purchase_status"] = "TRADE_UP_APPLIED"
    core.touch(origin)
    for plan in DB.all("promotional_plans"):
        if plan["purchase_id"] == origin["id"] and plan["plan_status"] in ("ACCRUING", "CAPITALIZED"):
            core.append_ledger_entry(plan, "TRADE_UP_CREDIT", "DECREASE",
                                     purchase["trade_up_credit_cents"], 0)
            plan["plan_status"] = "PAID"
            plan["paid_at"] = iso(DB.now())
            plan["deferred_interest_accrued_cents"] = 0
            plan["final_settlement_amount_cents"] = 0
            plan["total_paid_cents"] += purchase["trade_up_credit_cents"]
            core.touch(plan)
    if origin.get("diamond_id"):
        stone = DB.get("diamonds", origin["diamond_id"])
        if stone is not None:
            stone["custody_status"] = "IN_VAULT"
            core.touch(stone)


def _swap_covering_registration(origin, purchase, customer):
    """Terminate the origin's live registration and open exactly one fresh one."""
    if origin is None:
        return
    registrations = [g for g in DB.all("registrations")
                     if g["purchase_id"] == origin["id"]
                     and g["coverage_status"] not in ("TERMINATED", "VOID")]
    if not registrations:
        return
    for old in registrations:
        old["coverage_status"] = "TERMINATED"
        old["is_valid"] = False
        for visit in DB.all("visits"):
            if visit["registration_id"] == old["id"] and \
                    visit["inspection_status"] == "SCHEDULED":
                visit["inspection_status"] = "NO_SHOW"
                visit["result"] = "NO_SHOW"
                core.touch(visit)
        core.touch(old)
    template = registrations[0]
    fresh = core.new_row(
        "registrations",
        customer_id=customer["id"],
        purchase_id=purchase["id"],
        diamond_id=purchase.get("diamond_id"),
        store_id=purchase["store_id"],
        bundle_id=template["bundle_id"],
        registered_at=None,
        coverage_status="PENDING_INSPECTION",
        inspection_due_at=None,
        cure_expires_at=None,
        last_inspection_at=None,
        next_inspection_at=None,
        missed_inspection_count=0,
        plan_term_months=template["plan_term_months"],
        renewal_count=0,
        replacement_claims_used=0,
        is_valid=False,
    )
    core.schedule_registration(fresh, DB.now())