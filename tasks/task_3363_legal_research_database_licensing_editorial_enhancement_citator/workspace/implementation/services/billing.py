"""Billing services: lazy OVERDUE materialization, auto-resume, invoice total
calculation, and cost-recovery allocation (PRD 2.4, 2.7, 3.6)."""

from decimal import ROUND_HALF_UP, Decimal

from db import iso_now, store, touch
from util import day_start


def materialize_overdue():
    """Lazy OVERDUE materialization (PRD 2.4): flip every ISSUED invoice whose
    due_at is earlier than the logical clock, and suspend its subscription."""
    now = store.clock
    for inv in store.invoices.values():
        if inv["status"] != "ISSUED":
            continue
        if inv["_due_dt"] is None or not (inv["_due_dt"] < now):
            continue
        inv["status"] = "OVERDUE"
        touch(inv)
        sub = store.subscriptions.get(inv["subscription_id"])
        if sub is not None and sub["status"] == "ACTIVE":
            sub["status"] = "SUSPENDED"
            sub["suspension_reason"] = "INVOICE_OVERDUE"
            touch(sub)


def eval_auto_resume(subscription_id):
    """System resume (PRD 3.6): a subscription suspended for INVOICE_OVERDUE
    returns to ACTIVE once no ISSUED or OVERDUE invoice remains on it."""
    sub = store.subscriptions.get(subscription_id)
    if sub is None:
        return
    if sub["status"] != "SUSPENDED" or sub["suspension_reason"] != "INVOICE_OVERDUE":
        return
    outstanding = any(
        inv["subscription_id"] == sub["id"] and inv["status"] in ("ISSUED", "OVERDUE")
        for inv in store.invoices.values()
    )
    if outstanding:
        return
    sub["status"] = "ACTIVE"
    sub["suspension_reason"] = None
    touch(sub)


def events_in_window(subscription_id, period_start, period_end):
    """UsageEvents of the subscription with occurred_at in the half-open
    billing window [period_start, period_end); in-scope and out-of-scope alike."""
    start_dt = day_start(period_start)
    end_dt = day_start(period_end)
    return [
        e
        for e in store.usage_events.values()
        if e["subscription_id"] == subscription_id
        and start_dt <= e["_occurred_dt"] < end_dt
    ]


def compute_invoice_fields(subscription, period_start, period_end):
    """invoice_total_calculation (PRD 3.6 / 2.7). Reads the subscription's
    CURRENT plan at generation time. Returns the computed invoice fields."""
    plan = store.plans[subscription["plan_id"]]
    events = events_in_window(subscription["id"], period_start, period_end)
    search_count = sum(1 for e in events if e["event_type"] == "SEARCH")
    doc_view_count = sum(1 for e in events if e["event_type"] == "DOC_VIEW")
    billing_model = plan["billing_model"]

    if billing_model == "FLAT_RATE":
        base_fee = plan["monthly_fee_cents"]
        overage_search = max(0, search_count - plan["included_searches"])
        overage_view = max(0, doc_view_count - plan["included_doc_views"])
        if overage_search + overage_view >= plan["discount_threshold_overage_units"]:
            # Rounding order is pinned: round EACH component half-up first, then sum.
            factor = Decimal(1) - Decimal(str(plan["volume_discount_pct"]))
            search_component = int(
                (Decimal(overage_search) * Decimal(plan["overage_search_fee_cents"]) * factor)
                .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
            view_component = int(
                (Decimal(overage_view) * Decimal(plan["overage_doc_view_fee_cents"]) * factor)
                .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
        else:
            search_component = overage_search * plan["overage_search_fee_cents"]
            view_component = overage_view * plan["overage_doc_view_fee_cents"]
        overage_fee = search_component + view_component
        total = base_fee + overage_fee
    else:  # TRANSACTIONAL: pure per-event fees, no base / quota / discount
        base_fee = 0
        overage_search = 0
        overage_view = 0
        overage_fee = 0
        total = (
            search_count * plan["per_search_fee_cents"]
            + doc_view_count * plan["per_doc_view_fee_cents"]
        )

    account = store.accounts.get(subscription["account_id"])
    if account is not None and account["cost_recovery_enabled"]:
        allocation = compute_cost_recovery_allocation(events, total)
    else:
        allocation = []

    return {
        "billing_model": billing_model,
        "base_fee_cents": base_fee,
        "search_count": search_count,
        "doc_view_count": doc_view_count,
        "overage_search_units": overage_search,
        "overage_view_units": overage_view,
        "overage_fee_cents": overage_fee,
        "total_cents": total,
        "cost_recovery_allocation": allocation,
    }


def compute_cost_recovery_allocation(events, total_cents):
    """cost_recovery_allocation (PRD 3.6): floor first pass, then distribute
    leftover cents one at a time by (event_count DESC, matter_code ASC)."""
    counts = {}
    for event in events:
        counts[event["matter_code"]] = counts.get(event["matter_code"], 0) + 1
    if not counts:
        return []
    matters = sorted(counts.keys())
    total_events = sum(counts.values())
    amounts = {m: (total_cents * counts[m]) // total_events for m in matters}
    remainder = total_cents - sum(amounts.values())
    for matter in sorted(matters, key=lambda m: (-counts[m], m)):
        if remainder <= 0:
            break
        amounts[matter] += 1
        remainder -= 1
    return [
        {"matter_code": m, "event_count": counts[m], "amount_cents": amounts[m]}
        for m in matters
    ]
