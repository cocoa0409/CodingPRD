"""Promotional financing: opening, capitalizing, paying off, voiding, defaulting."""

import datetime

from flask import request

from db import DB, iso, parse_dt
from middleware import guard
from response import (ApiError, Err, as_enum, as_int, as_str, body, created_obj,
                      ensure_known, invalid_state, ok_list, ok_obj, pagination,
                      sorted_by_created)
from services import core

READ_ROLES = ["ChainAdmin", "CreditAnalyst", "StoreManager", "SalesAssociate", "CustomerService"]


def register(app):
    @app.route("/promotional-plans", methods=["POST"])
    def create_plan():
        guard(["SalesAssociate", "CustomerService"])
        data = body()
        ensure_known(data, ["customer_id", "purchase_id", "plan_code",
                            "expected_purchase_version"])
        customer_id = as_str(data, "customer_id")
        purchase_id = as_str(data, "purchase_id")
        plan_code = as_enum(data, "plan_code", ("PROMO_12_6M", "PROMO_18_6M", "PROMO_24_12M"))
        expected = as_int(data, "expected_purchase_version", required=True)

        # Priority 3: the body's foreign keys resolve left to right.
        core.fetch("customers", customer_id, "customer")
        purchase = core.fetch("purchases", purchase_id, "purchase")
        # Priority 4: the purchase must be in a state from which FINANCED is
        # declared -- FINANCED is not one of them, so a second financing code
        # on the same ticket surfaces as INVALID_STATE.
        if purchase["purchase_status"] not in ("PENDING", "FINANCED"):
            raise invalid_state("This purchase cannot take a financing plan.")
        if purchase["customer_id"] != customer_id:
            invalid_state("The plan's customer does not own this purchase.")
        # Priority 5: OCC, the mechanism that separates two financing writes.
        if purchase["version"] != expected:
            raise ApiError(Err.STALE_VERSION)
        # Priority 8: frozen credit outranks every fiscal check below it.
        if core.has_defaulted_plan(customer_id):
            raise ApiError(Err.CREDIT_FROZEN)
        # Priority 18: only one live plan may reference a purchase.
        for other in DB.all("promotional_plans"):
            if other["purchase_id"] == purchase_id and \
                    other["plan_status"] not in ("PAID", "VOIDED"):
                raise ApiError(Err.PLAN_ALREADY_EXISTS)

        apr, deferred_months, simplicity_months, _bps = core.plan_terms_for(plan_code)
        fee = core.purchase_protection_fee(purchase)
        principal = purchase["net_amount_cents"] + fee
        quarter = core.installment_quarter(principal, simplicity_months)

        plan = core.new_row(
            "promotional_plans",
            customer_id=customer_id,
            purchase_id=purchase_id,
            plan_code=plan_code,
            promotional_apr_pct=apr,
            deferred_months=deferred_months,
            simplicity_months=simplicity_months,
            deferral_basis_points=_bps,
            installment_amount_cents=quarter,
            principal_cents=principal,
            installment_quarter_cents=quarter,
            deferred_interest_accrued_cents=0,
            final_settlement_amount_cents=principal,
            merchant_deferral_fee_cents=core.merchant_deferral_fee(principal, simplicity_months),
            plan_status="ACCRUING",
            total_paid_cents=0,
            simplicity_expires_at=iso(DB.now() + _months(simplicity_months)),
            paid_at=None,
        )
        purchase["purchase_status"] = "FINANCED"
        core.touch(purchase)

        customer = DB.get("customers", customer_id)
        core.recompute_customer(customer)
        return created_obj(plan)

    @app.route("/promotional-plans", methods=["GET"])
    def list_plans():
        guard(READ_ROLES)
        limit, offset = pagination()
        rows = DB.all("promotional_plans")
        for field in ("customer_id", "purchase_id", "plan_status"):
            value = request.args.get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        rows = sorted_by_created(rows)
        for plan in rows:
            core.recompute_plan_derived(plan)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/promotional-plans/<ident>", methods=["GET"])
    def get_plan(ident):
        guard(READ_ROLES)
        plan = core.fetch("promotional_plans", ident, "promotional plan")
        core.recompute_plan_derived(plan)
        return ok_obj(plan)

    @app.route("/promotional-plans/<ident>/payoff", methods=["POST"])
    def payoff_plan(ident):
        guard(["CustomerService", "SalesAssociate"])
        data = body()
        ensure_known(data, ["amount_cents", "expected_plan_version"])
        amount = as_int(data, "amount_cents", required=True)
        expected = as_int(data, "expected_plan_version", required=True)

        plan = core.fetch("promotional_plans", ident, "promotional plan")
        if plan["plan_status"] not in ("ACCRUING", "CAPITALIZED"):
            raise invalid_state("This plan is not in a state from which payoff is declared.")
        if plan["version"] != expected:
            raise ApiError(Err.STALE_VERSION)

        if plan["plan_status"] == "ACCRUING":
            expires = parse_dt(plan.get("simplicity_expires_at"))
            if expires is not None and DB.now() > expires:
                raise ApiError(Err.WINDOW_EXPIRED,
                               "The plan's simplicity window has passed.")
            settlement = core.final_settlement(plan)
        else:
            settlement = plan["principal_cents"]
        if amount < settlement:
            raise ApiError(Err.INSUFFICIENT_PAYOFF)

        entry_amount = amount if plan["plan_status"] == "ACCRUING" else plan["principal_cents"]
        core.append_ledger_entry(plan, "LUMPSUM_PAYOFF", "DECREASE", entry_amount,
                                 -amount, "PROMOTIONAL")
        plan["total_paid_cents"] += amount
        plan["plan_status"] = "PAID"
        plan["paid_at"] = iso(DB.now())
        plan["deferred_interest_accrued_cents"] = 0
        plan["final_settlement_amount_cents"] = 0
        plan["merchant_deferral_fee_cents"] = 0
        core.touch(plan)

        customer = DB.get("customers", plan["customer_id"])
        if customer is not None:
            core.recompute_customer(customer)
        return ok_obj(plan)

    @app.route("/promotional-plans/<ident>/reinstate", methods=["POST"])
    def reinstate_plan(ident):
        guard(["CreditAnalyst"])
        data = body()
        ensure_known(data, ["expected_plan_version"])
        expected = as_int(data, "expected_plan_version", required=True)

        plan = core.fetch("promotional_plans", ident, "promotional plan")
        if plan["plan_status"] != "DEFAULTED":
            raise invalid_state("Only a DEFAULTED plan may be reinstated.")
        if plan["version"] != expected:
            raise ApiError(Err.STALE_VERSION)
        customer = core.fetch("customers", plan["customer_id"], "customer")
        if customer["account_status"] != "SUSPENDED":
            raise invalid_state("The cardholder's account is not SUSPENDED.")

        plan["plan_status"] = "ACCRUING"
        plan["simplicity_expires_at"] = iso(DB.now() + _months(plan["simplicity_months"]))
        customer["account_status"] = "OPEN"
        customer["standalone_credit_limit_cents"] = core.registry_limit_for_customer(customer)
        core.recompute_customer(customer)
        core.touch(plan)
        core.touch(customer)
        return ok_obj(plan)

    @app.route("/promotional-plans/<ident>/cancel", methods=["POST"])
    def cancel_plan(ident):
        guard(["CustomerService"])
        plan = core.fetch("promotional_plans", ident, "promotional plan")
        if plan["plan_status"] != "ACCRUING":
            raise invalid_state("Only an ACCRUING plan may be voided.")
        if plan["total_paid_cents"] != 0:
            raise invalid_state("The plan has taken a payment.")
        if core.ledger_entries_of(plan["id"]):
            raise invalid_state("The plan already carries a ledger entry.")
        plan["plan_status"] = "VOIDED"
        plan["merchant_deferral_fee_cents"] = 0
        plan["deferred_interest_accrued_cents"] = 0
        plan["final_settlement_amount_cents"] = 0
        purchase = DB.get("purchases", plan["purchase_id"])
        if purchase is not None and purchase["purchase_status"] == "FINANCED":
            purchase["purchase_status"] = "PENDING"
            core.touch(purchase)
        core.touch(plan)
        customer = DB.get("customers", plan["customer_id"])
        if customer is not None:
            core.recompute_customer(customer)
        return ok_obj(plan)

    @app.route("/plans/capitalize-due", methods=["POST"])
    def capitalize_due():
        guard(["CreditAnalyst"])
        capitalized = []
        for plan in sorted_by_created(DB.all("promotional_plans")):
            if plan["plan_status"] != "ACCRUING":
                continue
            expires = parse_dt(plan.get("simplicity_expires_at"))
            if expires is None or DB.now() <= expires:
                continue
            interest = core.promo_interest_accrual(plan)
            core.append_ledger_entry(plan, "CAPITALIZATION", "INCREASE", interest, interest)
            plan["principal_cents"] += interest
            plan["deferred_interest_accrued_cents"] = 0
            plan["final_settlement_amount_cents"] = plan["principal_cents"]
            plan["plan_status"] = "CAPITALIZED"
            plan["merchant_deferral_fee_cents"] = 0
            core.touch(plan)
            customer = DB.get("customers", plan["customer_id"])
            if customer is not None:
                customer["outstanding_balance_cents"] = core.outstanding_balance(customer)
                customer["revolving_utilization_bps"] = core.revolving_utilization_bps(customer)
            capitalized.append(plan["id"])
        return ok_obj({"capitalized_count": len(capitalized),
                       "capitalized_plan_ids": capitalized})

    @app.route("/plans/default-due", methods=["POST"])
    def default_due():
        guard(["CreditAnalyst"])
        defaulted = []
        suspended = []
        for plan in sorted_by_created(DB.all("promotional_plans")):
            if plan["plan_status"] not in ("ACCRUING", "CAPITALIZED"):
                continue
            expires = parse_dt(plan.get("simplicity_expires_at"))
            if expires is None:
                continue
            if DB.now() <= expires + datetime.timedelta(days=90):
                continue
            if plan["total_paid_cents"] >= plan["principal_cents"]:
                continue
            # hop 1
            plan["plan_status"] = "DEFAULTED"
            core.touch(plan)
            defaulted.append(plan["id"])
            customer = DB.get("customers", plan["customer_id"])
            if customer is None:
                continue
            # hop 2
            customer["account_status"] = "SUSPENDED"
            customer["credit_tier"] = "NO_FILE"
            customer["standalone_credit_limit_cents"] = 0
            customer["revolving_utilization_bps"] = 10000
            # hop 3
            for application in DB.all("credit_applications"):
                if application["customer_id"] == customer["id"] and \
                        application["decision_status"] in ("PENDING", "COUNTERED"):
                    application["decision_status"] = "DECLINED"
                    core.touch(application)
            # hop 4
            for registration in DB.all("registrations"):
                if registration["customer_id"] == customer["id"] and \
                        registration["coverage_status"] in ("PENDING_INSPECTION", "REMINDER_ISSUED"):
                    registration["coverage_status"] = "LAPSED"
                    registration["is_valid"] = False
                    registration["missed_inspection_count"] += 1
                    for visit in DB.all("visits"):
                        if visit["registration_id"] == registration["id"] and \
                                visit["inspection_status"] == "SCHEDULED":
                            visit["inspection_status"] = "NO_SHOW"
                            visit["result"] = "NO_SHOW"
                            core.touch(visit)
                    core.touch(registration)
                    store = DB.get("stores", registration["store_id"])
                    if store is not None:
                        store["open_inspection_count"] = max(
                            0, store["open_inspection_count"] - 1)
            # hop 5
            customer["lost_inspection_streak"] = sum(
                1 for registration in DB.all("registrations")
                if registration["customer_id"] == customer["id"]
                and registration["coverage_status"] in
                ("LAPSED", "RENEWED", "TERMINATED", "VOID")
                and registration["missed_inspection_count"] > 0)
            # hop 6: the tier rule alone re-runs, so the streak increment from
            # hop 5 is visible and the pinned utilization figure is untouched.
            customer["outstanding_balance_cents"] = core.outstanding_balance(customer)
            customer["lifetime_purchase_cents"] = sum(
                p["base_price_cents"] for p in DB.all("purchases")
                if p["customer_id"] == customer["id"]
                and p["purchase_status"] in ("COMPLETED", "TRADE_UP_APPLIED"))
            core.recompute_tier(customer)
            core.recompute_stores_of_customer(customer["id"])
            if customer["id"] not in suspended:
                suspended.append(customer["id"])
        return ok_obj({"defaulted_count": len(defaulted),
                       "defaulted_plan_ids": defaulted,
                       "suspended_customer_ids": suspended})


def _months(count):
    """simplicity_months is a calendar-month offset: PROMO_12_6M's window closes
    exactly twelve calendar months after creation, so a plan created on
    2026-09-01 is still inside its window at 2027-09-01 and outside it a day later."""
    now = DB.now()
    month_index = now.month - 1 + count
    year = now.year + month_index // 12
    month = month_index % 12 + 1
    day = min(now.day, _days_in_month(year, month))
    return datetime.datetime(year, month, day, now.hour, now.minute, now.second,
                             now.microsecond, tzinfo=now.tzinfo) - now


def _days_in_month(year, month):
    import calendar
    return calendar.monthrange(year, month)[1]