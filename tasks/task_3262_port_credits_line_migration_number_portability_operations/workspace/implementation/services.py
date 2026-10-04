"""Shared recomputation helpers for device installment plans."""

import calculations
import clock
import models


def plan_state_after_recompute(plan):
    """Derive plan_state from the plan's financing position (PRD 3.5).

    A plan that has been converted by a migration stays CONVERTED; a plan that has
    never been financed stays QUOTED; a financed plan is UPGRADE_ELIGIBLE once the
    logical clock reaches its upgrade instant and ACTIVE before that.
    """
    if plan["plan_state"] == "CONVERTED":
        return "CONVERTED"
    if plan["financed_at"] is None:
        return "QUOTED"
    eligible_at = clock.parse_instant(plan["upgrade_eligible_at"]) if plan.get(
        "upgrade_eligible_at") else None
    if eligible_at is not None and clock.now() >= eligible_at:
        return "UPGRADE_ELIGIBLE"
    return "ACTIVE"


def recompute_plan(plan):
    """Re-level the installments from the current remaining balance and restate state."""
    monthly, _first = calculations.level_installment_cents(
        plan["remaining_balance_cents"], plan["installment_months"]
    )
    plan["monthly_installment_cents"] = monthly
    plan["plan_state"] = plan_state_after_recompute(plan)
    models.touch(plan)
    return plan