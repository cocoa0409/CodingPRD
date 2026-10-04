"""FinancingPlan: origination, installments, delinquency and the safety floor.

The plan's state machine is cyclic (DELINQUENT hops back to CURRENT) with a
terminal DEFAULTED and PAID_OFF.  Every path leaves safety_disable_latched
false and the parent's safety_gate_open true (PRD sections 2.7 and 3.5).
"""

import clock
import db
from errors import api_error
from services import calc
from services.common import (
    field_int,
    field_str,
    reject_unknown,
)


def create(payload):
    reject_unknown(
        payload,
        {"membership_id", "order_id", "principal_cents", "term_months", "apr_bps"},
    )
    membership_id = field_str(payload, "membership_id")
    order_id = field_str(payload, "order_id")
    principal_cents = field_int(payload, "principal_cents", minimum=0)
    term_months = field_int(payload, "term_months")
    apr_bps = field_int(payload, "apr_bps", minimum=0)

    # Every body foreign key must resolve before any state rule runs.
    membership = db.require("memberships", membership_id)
    order = db.require("hardware_orders", order_id)

    if term_months not in calc.TERMS_ALLOWED:
        raise api_error(
            "ERR_INSTALLMENT_COUNT_EXCEEDED",
            "term_months must be one of 6, 12 or 24.",
        )
    if order["membership_id"] != membership["id"]:
        raise api_error(
            "ERR_ORDER_MEMBERSHIP_MISMATCH",
            "The financing plan's order and membership do not agree.",
        )
    if membership["status"] == "TERMINATED":
        raise api_error("ERR_ALREADY_TERMINAL", "The membership has been terminated.")

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    if membership["posture"] in ("RESTRICTED", "FROZEN"):
        raise api_error(
            "ERR_POSTURE_RESTRICTED",
            "A membership in RESTRICTED or FROZEN posture may not originate a new financing plan.",
        )
    if membership["unpaid_financing_count"] >= 1:
        raise api_error(
            "ERR_UNPAID_FINANCING_BLOCK",
            "A household already carrying a DELINQUENT or DEFAULTED plan may not originate another.",
        )

    plan = db.create("financing_plans", {
        "membership_id": membership_id,
        "order_id": order_id,
        "principal_cents": principal_cents,
        "term_months": term_months,
        "apr_bps": apr_bps,
        "monthly_installment_cents": 0,
        "installments_paid": 0,
        "installments_late": 0,
        "retry_count": 0,
        "status": "ORIGINATED",
        "delinquency_count": 0,
        "safety_disable_latched": False,
        # Internal marker for the DEFAULT_GRACE_DAYS cure window.  Not part of
        # the declared field set, so it is not serialised.
        "last_failure_at": None,
    })
    amounts = calc.installment_amounts(principal_cents, apr_bps, term_months, 0)
    plan["monthly_installment_cents"] = amounts["monthly_installment_cents"]
    return plan


def _membership_of(plan):
    return db.require("memberships", plan["membership_id"])


def _within_default_grace(plan):
    """A cure payment must arrive within DEFAULT_GRACE_DAYS of the last failure."""
    last_failure = plan.get("last_failure_at")
    if last_failure is None:
        return True
    return (clock.now() - last_failure).days <= calc.DEFAULT_GRACE_DAYS


def pay(plan):
    membership = _membership_of(plan)
    status = plan["status"]
    installments_paid = plan["installments_paid"]
    term_months = plan["term_months"]

    if status == "PAID_OFF":
        raise api_error("ERR_PLAN_ALREADY_PAID_OFF", "The financing plan is already settled.")
    if status not in ("ORIGINATED", "CURRENT", "DELINQUENT", "DEFAULTED"):
        raise api_error("ERR_INVALID_STATE", "The plan does not admit an installment payment.")

    if status == "DEFAULTED":
        # A payment arriving within DEFAULT_GRACE_DAYS of the most recent
        # installment failure cures the default.  The scaffold's DEFAULTED →
        # CURRENT transition carries no installment-count ceiling, so a plan
        # that had already collected its term settles here.
        if not _within_default_grace(plan):
            raise api_error(
                "ERR_INVALID_STATE",
                "A default may only be cured by a payment within 30 days of the most "
                "recent installment failure.",
            )
        plan["status"] = "PAID_OFF" if installments_paid >= term_months else "CURRENT"
        plan["installments_late"] = plan["installments_late"] + 1
        plan["safety_disable_latched"] = False
        if installments_paid < term_months:
            plan["installments_paid"] = installments_paid + 1
        plan["monthly_installment_cents"] = calc.installment_amounts(
            plan["principal_cents"], plan["apr_bps"], term_months, plan["installments_paid"]
        )["monthly_installment_cents"]
        db.touch(plan)
        calc.recompute_membership(membership, bump=True)
        return plan

    if status == "ORIGINATED":
        if installments_paid + 1 > term_months:
            raise api_error(
                "ERR_INSTALLMENT_COUNT_EXCEEDED",
                "Paying this installment would exceed the plan's term.",
            )
        plan["installments_paid"] = installments_paid + 1
        plan["status"] = "CURRENT"
    elif status == "CURRENT":
        if installments_paid >= term_months:
            raise api_error(
                "ERR_INSTALLMENT_COUNT_EXCEEDED",
                "The plan has already collected every installment of its term.",
            )
        plan["installments_paid"] = installments_paid + 1
        if plan["installments_paid"] == term_months:
            plan["status"] = "PAID_OFF"
    elif status == "DELINQUENT":
        if installments_paid + 1 > term_months:
            raise api_error(
                "ERR_INSTALLMENT_COUNT_EXCEEDED",
                "Paying this installment would exceed the plan's term.",
            )
        plan["installments_paid"] = installments_paid + 1
        plan["installments_late"] = plan["installments_late"] + 1
        plan["retry_count"] = 0
        if plan["installments_paid"] == term_months:
            plan["status"] = "PAID_OFF"
        else:
            plan["status"] = "CURRENT"

    plan["monthly_installment_cents"] = calc.installment_amounts(
        plan["principal_cents"], plan["apr_bps"], term_months, plan["installments_paid"]
    )["monthly_installment_cents"]
    plan["safety_disable_latched"] = False
    db.touch(plan)

    calc.recompute_membership(membership, bump=False)
    if (
        membership["status"] == "DELINQUENT"
        and membership["unpaid_financing_count"] == 0
    ):
        membership["status"] = "ACTIVE"
    calc.recompute_membership(membership, bump=True)
    return plan


def fail(plan):
    membership = _membership_of(plan)

    if plan["status"] != "CURRENT":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a CURRENT financing plan may record a failed installment.",
        )

    plan["retry_count"] = plan["retry_count"] + 1
    if plan["retry_count"] >= calc.DELINQUENT_RETRY_THRESHOLD:
        plan["status"] = "DELINQUENT"
        plan["delinquency_count"] = plan["delinquency_count"] + 1
        plan["last_failure_at"] = clock.now()
    else:
        plan["last_failure_at"] = clock.now()
    # Delinquency never disables hardware safety functions.
    plan["safety_disable_latched"] = False
    db.touch(plan)

    calc.recompute_membership(membership, bump=False)
    if (
        membership["unpaid_financing_count"] >= 1
        and membership["status"] in ("ACTIVE", "REACTIVATED")
    ):
        membership["status"] = "DELINQUENT"
    calc.recompute_membership(membership, bump=True)
    return plan


def rolling_correction(plan):
    membership = _membership_of(plan)

    if plan["status"] != "CURRENT":
        raise api_error(
            "ERR_INVALID_STATE",
            "A rolling correction applies only to a CURRENT financing plan.",
        )
    if plan["installments_paid"] < 1:
        raise api_error(
            "ERR_INVALID_STATE",
            "A rolling correction requires at least one paid installment.",
        )

    plan["installments_paid"] = plan["installments_paid"] - 1
    plan["status"] = "CURRENT"
    plan["monthly_installment_cents"] = calc.installment_amounts(
        plan["principal_cents"], plan["apr_bps"], plan["term_months"],
        plan["installments_paid"],
    )["monthly_installment_cents"]
    plan["safety_disable_latched"] = False
    db.touch(plan)

    calc.recompute_membership(membership, bump=True)
    return plan


def owned_by(caller, plan):
    membership = db.STORE["memberships"].get(plan["membership_id"])
    if caller.is_owner and membership is not None and membership["id"] != caller.user_id:
        raise api_error("ERR_UNAUTHORIZED")
    return plan