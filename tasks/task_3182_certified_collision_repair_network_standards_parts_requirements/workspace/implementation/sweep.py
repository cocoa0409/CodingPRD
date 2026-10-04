"""Posture cascades and the time-gated clock sweep."""
from datetime import timedelta

import calc
from calc import (DECERTIFY_GRACE_DAYS, DELIVERY_GRACE_HOURS, REFERRAL_TTL_HOURS,
                  WARRANTY_MONTHS, CLAIM_CLOSE_DAYS)
from db import db
from util import bump, iso_ms, parse_dt


def recompute_locator_hidden(shop):
    """locator_hidden = True when status != CERTIFIED, or an active audit of the
    shop is in VERIFICATION with a CRITICAL finding outstanding."""
    hidden = shop["certification_status"] != "CERTIFIED"
    if not hidden:
        for audit in db.audits.values():
            if audit["status"] != "VERIFICATION":
                continue
            cycle = db.cycles.get(audit["cycle_id"])
            if not cycle or cycle["shop_id"] != shop["id"]:
                continue
            if any(a["audit_id"] == audit["id"]
                   and a["finding_severity"] == "CRITICAL"
                   and a["status"] in ("OPEN", "SUBMITTED", "REJECTED")
                   for a in db.corrective_actions.values()):
                hidden = True
                break
    if shop.get("locator_hidden") != hidden:
        shop["locator_hidden"] = hidden
        bump(shop)


def recompute_steering(shop):
    for rel in db.insurer_relations.values():
        if rel["shop_id"] != shop["id"]:
            continue
        enabled = (rel["status"] == "ACTIVE"
                   and shop["certification_status"] in ("CERTIFIED", "PROBATION"))
        if rel.get("steering_enabled") != enabled:
            rel["steering_enabled"] = enabled
            bump(rel)


def force_decline_routed_referrals(shop):
    for ref in db.referrals.values():
        if ref["routed_shop_id"] == shop["id"] and ref["status"] == "ROUTED":
            ref["status"] = "DECLINED"
            bump(ref)
            shop["pending_referral_count"] = max(0, shop["pending_referral_count"] - 1)
            bump(shop)


def suspend_cascade(shop):
    recompute_locator_hidden(shop)
    recompute_steering(shop)
    force_decline_routed_referrals(shop)


def decertify_cascade(shop):
    for rel in db.insurer_relations.values():
        if rel["shop_id"] == shop["id"] and rel["status"] == "ACTIVE":
            rel["status"] = "TERMINATED"
            rel["steering_enabled"] = False
            bump(rel)
    force_decline_routed_referrals(shop)
    recompute_locator_hidden(shop)


def set_shop_posture(shop, new_status):
    """Transition certification_status and run the matching cascade."""
    old = shop["certification_status"]
    if old == new_status:
        return
    shop["certification_status"] = new_status
    if new_status == "SUSPENDED":
        shop["_suspended_at"] = db.clock
    bump(shop)
    if new_status == "CERTIFIED":
        recompute_locator_hidden(shop)
        recompute_steering(shop)
    elif new_status == "PROBATION":
        recompute_locator_hidden(shop)
        recompute_steering(shop)
    elif new_status == "SUSPENDED":
        suspend_cascade(shop)
    elif new_status == "EXPIRED":
        recompute_locator_hidden(shop)
        recompute_steering(shop)
    elif new_status == "DECERTIFIED":
        decertify_cascade(shop)


def apply_pass_posture(shop, cycle, grade):
    """Shop posture transitions on a cycle close with result PASS, per the
    Shop state machine in the scaffold/PRD."""
    status = shop["certification_status"]
    if status == "APPLICANT":
        if cycle["cycle_index"] == 1 and grade in ("A", "B"):
            set_shop_posture(shop, "CERTIFIED")
    elif status == "CERTIFIED":
        if grade == "C":
            set_shop_posture(shop, "PROBATION")
        elif grade == "F":
            set_shop_posture(shop, "SUSPENDED")
    elif status == "PROBATION":
        if grade in ("A", "B"):
            set_shop_posture(shop, "CERTIFIED")
        elif grade in ("C", "F"):
            set_shop_posture(shop, "SUSPENDED")
    elif status == "SUSPENDED":
        if grade in ("A", "B"):
            set_shop_posture(shop, "CERTIFIED")
        elif grade in ("C", "F"):
            set_shop_posture(shop, "SUSPENDED")
    elif status == "EXPIRED":
        set_shop_posture(shop, "CERTIFIED")


# ---------------------------------------------------------------------------
# Clock sweep
# ---------------------------------------------------------------------------
def run_sweep():
    """Apply every time-gated transition at the current logical clock.
    Returns a dict of swept counts."""
    now = db.clock
    counts = {
        "course_completions_expired": 0,
        "technicians_status_changed": 0,
        "referrals_expired": 0,
        "corrective_actions_overdue": 0,
        "audits_failed": 0,
        "cycles_closed_fail": 0,
        "cycles_expired": 0,
        "orders_warranty_active": 0,
        "orders_closed": 0,
        "claims_closed": 0,
        "shops_posture_changed": 0,
    }

    # 1) CourseCompletion CURRENT -> EXPIRED
    for cc in list(db.completions.values()):
        if cc["status"] != "CURRENT":
            continue
        course = db.courses.get(cc["course_id"])
        if not course:
            continue
        expiry = calc.add_months(parse_dt(cc["completed_at"], "completed_at"),
                                 course["validity_months"])
        if expiry <= now:
            cc["status"] = "EXPIRED"
            bump(cc)
            counts["course_completions_expired"] += 1
    for tech in list(db.technicians.values()):
        before = tech["status"]
        calc.recompute_technician(tech)
        if tech["status"] != before:
            counts["technicians_status_changed"] += 1

    # 2) Referral TTL expiry: ROUTED and routed_at + 72h <= now
    for ref in list(db.referrals.values()):
        if ref["status"] != "ROUTED" or not ref.get("routed_at"):
            continue
        expiry = parse_dt(ref["routed_at"], "routed_at") + timedelta(hours=REFERRAL_TTL_HOURS)
        if now >= expiry:
            ref["status"] = "EXPIRED"
            bump(ref)
            shop = db.shops.get(ref["routed_shop_id"])
            if shop:
                shop["pending_referral_count"] = max(0, shop["pending_referral_count"] - 1)
                bump(shop)
            counts["referrals_expired"] += 1

    # 3) Warranty claim auto-close 30 days after resolution
    for claim in list(db.warranty_claims.values()):
        if claim["status"] in ("RESOLVED_ACCEPTED", "RESOLVED_DENIED"):
            resolved_at = claim.get("_resolved_at")
            if resolved_at and now >= resolved_at + timedelta(days=CLAIM_CLOSE_DAYS):
                claim["status"] = "CLOSED"
                bump(claim)
                counts["claims_closed"] += 1

    # 4) RepairOrder COMPLETE -> WARRANTY_ACTIVE after 24h grace without a claim
    for order in list(db.repair_orders.values()):
        if order["status"] != "COMPLETE" or not order.get("completed_at"):
            continue
        grace = parse_dt(order["completed_at"], "completed_at") + timedelta(hours=DELIVERY_GRACE_HOURS)
        if now < grace:
            continue
        has_claim = any(c["repair_order_id"] == order["id"]
                        for c in db.warranty_claims.values())
        if has_claim:
            continue
        accrual = calc.compute_reserve_accrual(order)
        order["status"] = "WARRANTY_ACTIVE"
        order["_reserve_accrual"] = accrual
        order["_reserve_remaining"] = accrual
        bump(order)
        shop = db.shops.get(order["shop_id"])
        if shop:
            shop["warranty_reserve_cents"] = shop.get("warranty_reserve_cents", 0) + accrual
            bump(shop)
        counts["orders_warranty_active"] += 1

    # 5) RepairOrder WARRANTY_ACTIVE -> CLOSED after 12 months with no open claims
    for order in list(db.repair_orders.values()):
        if order["status"] != "WARRANTY_ACTIVE" or not order.get("completed_at"):
            continue
        wend = calc.add_months(parse_dt(order["completed_at"], "completed_at"),
                               WARRANTY_MONTHS)
        if now <= wend:
            continue
        open_claim = any(c["repair_order_id"] == order["id"]
                         and c["status"] in ("FILED", "UNDER_REVIEW", "ESCALATED")
                         for c in db.warranty_claims.values())
        if open_claim:
            continue
        remaining = order.get("_reserve_remaining", 0)
        order["status"] = "CLOSED"
        bump(order)
        if remaining:
            shop = db.shops.get(order["shop_id"])
            if shop:
                shop["warranty_reserve_cents"] = max(
                    0, shop.get("warranty_reserve_cents", 0) - remaining)
                bump(shop)
            order["_reserve_remaining"] = 0
        counts["orders_closed"] += 1

    # 6) Corrective actions overdue: OPEN past due_at
    overdue_critical_by_shop = {}
    for action in list(db.corrective_actions.values()):
        if action["status"] == "OPEN" and parse_dt(action["due_at"], "due_at") < now:
            counts["corrective_actions_overdue"] += 1
            if action["finding_severity"] == "CRITICAL":
                audit = db.audits.get(action["audit_id"])
                cycle = db.cycles.get(audit["cycle_id"]) if audit else None
                if cycle:
                    overdue_critical_by_shop[cycle["shop_id"]] = True
        # VERIFICATION fail: OPEN or SUBMITTED past due_at
        if action["status"] in ("OPEN", "SUBMITTED") and parse_dt(action["due_at"], "due_at") < now:
            audit = db.audits.get(action["audit_id"])
            if audit and audit["status"] == "VERIFICATION":
                audit["status"] = "FAILED"
                bump(audit)
                counts["audits_failed"] += 1
                cycle = db.cycles.get(audit["cycle_id"])
                if cycle and cycle["status"] == "CORRECTIVE_ACTION":
                    cycle["status"] = "CLOSED_FAIL"
                    bump(cycle)
                    counts["cycles_closed_fail"] += 1
                    shop = db.shops.get(cycle["shop_id"])
                    if shop and shop["certification_status"] in ("CERTIFIED", "PROBATION"):
                        set_shop_posture(shop, "SUSPENDED")
                        counts["shops_posture_changed"] += 1

    # 7) Overdue CRITICAL corrective action suspends CERTIFIED/PROBATION shops
    for shop_id in overdue_critical_by_shop:
        shop = db.shops.get(shop_id)
        if shop and shop["certification_status"] in ("CERTIFIED", "PROBATION"):
            set_shop_posture(shop, "SUSPENDED")
            counts["shops_posture_changed"] += 1

    # 8) Cycle window expiry: clock past the shop's LATEST cycle's window_end
    # with no active audit of that cycle. The latest cycle defines the shop's
    # current certification window whether it is open or already closed.
    cycles_by_shop = {}
    for cycle in db.cycles.values():
        cur = cycles_by_shop.get(cycle["shop_id"])
        if cur is None or (cycle["created_at"], cycle["_seq"]) > (cur["created_at"], cur["_seq"]):
            cycles_by_shop[cycle["shop_id"]] = cycle
    for shop_id, cycle in cycles_by_shop.items():
        wend = parse_dt(cycle["window_end"], "window_end")
        if now <= wend:
            continue
        active_audit = any(a["cycle_id"] == cycle["id"]
                           and a["status"] in ("SCHEDULED", "IN_PROGRESS",
                                               "FINDINGS_ISSUED", "VERIFICATION")
                           for a in db.audits.values())
        if active_audit:
            continue
        shop = db.shops.get(shop_id)
        if shop and shop["certification_status"] == "CERTIFIED":
            set_shop_posture(shop, "EXPIRED")
            counts["shops_posture_changed"] += 1
            counts["cycles_expired"] += 1

    # 9) locator_hidden refresh for shops whose audits moved in/out of VERIFICATION
    for shop in db.shops.values():
        recompute_locator_hidden(shop)

    return counts
