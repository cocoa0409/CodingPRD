"""Derived analytics: calibration index, face value vs revenue, fee breakeven."""

import math

import store
from envelope import rhu

# Decisions that enter the calibration set; EXPIRED is excluded outright.
INCLUDED_STATUSES = ("NEEDS_SNAPSHOT", "ELIGIBLE", "INELIGIBLE", "PREQUALIFIED",
                     "CONSENTED", "CONSUMED")


def programs_of_item(item_id):
    return [p for p in store.lender_programs.values()
            if p["product_catalog_item_id"] == item_id]


def decisions_of_item(item_id):
    program_ids = {p["id"] for p in programs_of_item(item_id)}
    return [d for d in store.pre_qual_decisions.values()
            if d["lender_program_id"] in program_ids]


def outcome_of_decision(dec):
    """FUNDED => success, REVERSED/DECLINED => failure, otherwise no outcome."""
    for ref in store.referrals.values():
        if ref["decision_id"] != dec["id"]:
            continue
        if ref["status"] == "FUNDED":
            return "success"
        if ref["status"] in ("REVERSED", "DECLINED"):
            return "failure"
    return None


def calibration_index(item_id, variant):
    """compute_calibration_index; null when the set or the successes are empty."""
    considered = [d for d in decisions_of_item(item_id)
                  if d["decision_status"] in INCLUDED_STATUSES]
    if variant == "settled_only":
        considered = [d for d in considered if d.get("modeled_odds_settled")]
    total = len(considered)
    successes = sum(1 for d in considered if outcome_of_decision(d) == "success")
    if total == 0 or successes == 0:
        return {
            "approval_odds_calibration_index": None,
            "calibration_variant": variant,
            "decision_count": total,
            "modeled_odds_mean": None,
            "realized_rate": 0.0,
        }
    odds = [d.get("modeled_odds_pct") for d in considered
            if d.get("modeled_odds_pct") is not None]
    mean_odds = rhu(sum(odds) / float(total), 4)
    realized_rate = rhu(successes / float(total), 4)
    if realized_rate == 0:
        index = None
    else:
        index = rhu(mean_odds / realized_rate, 4)
    return {
        "approval_odds_calibration_index": index,
        "calibration_variant": variant,
        "decision_count": total,
        "modeled_odds_mean": mean_odds,
        "realized_rate": realized_rate,
    }


def face_value_vs_revenue(item_id):
    """face_value is summed first; platform_revenue floors each referral."""
    total_face = 0
    total_revenue = 0
    for ref in store.referrals.values():
        if ref["status"] not in ("FUNDED", "REVERSED"):
            continue
        amount = ref.get("funded_amount_cents")
        if amount is None:
            continue
        dec = store.pre_qual_decisions.get(ref["decision_id"])
        if dec is None:
            continue
        prog = store.lender_programs.get(dec["lender_program_id"])
        if prog is None or prog["product_catalog_item_id"] != item_id:
            continue
        bps = ref.get("revenue_share_bps") or 0
        total_face += int(amount)
        total_revenue += (int(amount) * int(bps)) // 10000
    return total_face, total_revenue


def fee_breakeven_months(prog, card_balance_cents):
    """Single ceil at the end; null when no balance was supplied."""
    if prog is None:
        return None, "balance_unknown"
    annual_fee = int(prog.get("annual_fee_cents") or 0)
    intro_apr = int(prog.get("intro_apr_bps") or 0)
    if annual_fee == 0:
        return 0, "with_balance"
    if not card_balance_cents:
        return None, "balance_unknown"
    monthly_interest_saved = (int(card_balance_cents) * intro_apr) // 10000 // 12
    if monthly_interest_saved == 0:
        return None, "balance_unknown"
    return int(math.ceil(annual_fee / float(monthly_interest_saved))), "with_balance"


def first_program_of_item(item_id):
    progs = programs_of_item(item_id)
    progs.sort(key=lambda p: (p["created_at"], p["id"]))
    return progs[0] if progs else None