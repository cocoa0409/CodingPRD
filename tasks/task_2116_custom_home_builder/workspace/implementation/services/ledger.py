"""The project ledger, its derived fields and the freeze/thaw cascade (PRD 2.6)."""
from decimal import Decimal

from store import db, now, bump, touch_time, ordered
from util import q2, dsum
from services.constants import (
    ALLOWANCE_OVERRUN_PCT,
    LEDGER_COST_STATUSES,
    ELIGIBLE_POOL_STATUSES,
    PENDING_DRAW_STATUSES,
)

ZERO = Decimal("0")


# --------------------------------------------------------------- collections
def project_allowance_items(project_id):
    return ordered([a for a in db.allowance_items.values() if a["project_id"] == project_id])


def project_change_orders(project_id):
    return ordered([c for c in db.change_orders.values() if c["project_id"] == project_id])


def project_schedule_tasks(project_id):
    return ordered([t for t in db.schedule_tasks.values() if t["project_id"] == project_id])


def project_cost_entries(project_id):
    return ordered([c for c in db.cost_entries.values() if c["project_id"] == project_id])


def project_draw_requests(project_id):
    return ordered([d for d in db.draw_requests.values() if d["project_id"] == project_id])


def project_defect_tickets(project_id):
    return ordered([d for d in db.defect_tickets.values() if d["project_id"] == project_id])


def draw_lien_waivers(draw_id):
    return ordered([w for w in db.lien_waivers.values() if w["draw_request_id"] == draw_id])


def draw_cost_entries(draw_id):
    return ordered([c for c in db.cost_entries.values() if c["draw_request_id"] == draw_id])


# ------------------------------------------------------------------ ledger
def compute_ledger(project):
    """calculations.project_contract_position - pure, no mutation."""
    pid = project["id"]

    approved_change_order_total = q2(dsum(
        co["priced_amount"] for co in db.change_orders.values()
        if co["project_id"] == pid and co["status"] == "APPROVED"
    ))

    variance = ZERO
    for item in db.allowance_items.values():
        if item["project_id"] != pid:
            continue
        if item["status"] == "RECONCILED":
            variance += item["final_variance_amount"] or ZERO
        elif item["status"] in ("SELECTED", "LOCKED"):
            variance += item["provisional_variance_amount"] or ZERO
    allowance_variance_total = q2(variance)

    contract_sum_current = q2(
        project["base_contract_amount"] + approved_change_order_total + allowance_variance_total
    )

    cost_to_date = q2(dsum(
        ce["amount"] for ce in db.cost_entries.values()
        if ce["project_id"] == pid and ce["status"] in LEDGER_COST_STATUSES
    ))
    eligible_cost_pool = q2(dsum(
        ce["amount"] for ce in db.cost_entries.values()
        if ce["project_id"] == pid and ce["status"] in ELIGIBLE_POOL_STATUSES
    ))
    pending_draw_amount = q2(dsum(
        d["requested_amount"] for d in db.draw_requests.values()
        if d["project_id"] == pid and d["status"] in PENDING_DRAW_STATUSES
    ))
    funded_to_date = q2(dsum(
        d["net_funding_amount"] for d in db.draw_requests.values()
        if d["project_id"] == pid and d["status"] == "FUNDED"
    ))
    retainage_held = q2(dsum(
        d["retainage_amount"] for d in db.draw_requests.values()
        if d["project_id"] == pid and d["status"] == "FUNDED"
    ))

    return {
        "approved_change_order_total": approved_change_order_total,
        "allowance_variance_total": allowance_variance_total,
        "contract_sum_current": contract_sum_current,
        "cost_to_date": cost_to_date,
        "eligible_cost_pool": eligible_cost_pool,
        "pending_draw_amount": pending_draw_amount,
        "funded_to_date": funded_to_date,
        "retainage_held": retainage_held,
    }


def posture_for(project, contract_sum_current, allowance_variance_total):
    """calculations.project_budget_posture - strictly ordered test (PRD 2.6)."""
    gmp_cap = project.get("gmp_cap")
    if gmp_cap is not None and contract_sum_current > gmp_cap:
        return "OVER_GMP"
    threshold = q2(project["base_contract_amount"] * ALLOWANCE_OVERRUN_PCT)
    if allowance_variance_total > threshold:
        return "ALLOWANCE_OVERRUN"
    return "WITHIN_BUDGET"


def recompute_project(project):
    """Refresh every derived ledger field and run the freeze/thaw cascade."""
    values = compute_ledger(project)
    changed = any(project.get(k) != v for k, v in values.items())
    project.update(values)

    previous = project.get("budget_posture")
    current = posture_for(project, values["contract_sum_current"],
                          values["allowance_variance_total"])
    project["budget_posture"] = current
    if changed or previous != current:
        touch_time(project)

    if current == "OVER_GMP" and previous != "OVER_GMP":
        for item in project_allowance_items(project["id"]):
            if item["status"] == "OPEN":
                item["status"] = "FROZEN"
                item["frozen_at"] = now()
                bump(item)
    elif previous == "OVER_GMP" and current != "OVER_GMP":
        for item in project_allowance_items(project["id"]):
            if item["status"] == "FROZEN":
                item["status"] = "OPEN"
                item["frozen_at"] = None
                bump(item)
    return project


def contract_position(project):
    """The variant-specific owner-billable position (PRD 3.5)."""
    values = compute_ledger(project)
    contract_sum_current = values["contract_sum_current"]
    cost_to_date = values["cost_to_date"]
    gmp_cap = project.get("gmp_cap")

    if project["contract_type"] == "COST_PLUS":
        variant = "COST_PLUS"
        fee = project.get("builder_fee_pct")
        fee = fee if fee is not None else Decimal("0")
        raw = q2(cost_to_date * (Decimal("1") + fee))
        owner_billable = raw if gmp_cap is None else min(raw, gmp_cap)
        owner_billable = q2(owner_billable)
        builder_margin = q2(owner_billable - cost_to_date)
    else:
        variant = "FIXED_PRICE"
        owner_billable = contract_sum_current
        builder_margin = q2(contract_sum_current - cost_to_date)

    return {
        "contract_type": project["contract_type"],
        "variant_applied": variant,
        "contract_sum_current": contract_sum_current,
        "approved_change_order_total": values["approved_change_order_total"],
        "allowance_variance_total": values["allowance_variance_total"],
        "cost_to_date": cost_to_date,
        "owner_billable_amount": owner_billable,
        "builder_margin_amount": builder_margin,
        "gmp_headroom": None if gmp_cap is None else q2(gmp_cap - contract_sum_current),
    }
