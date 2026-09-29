"""Family cost share, visit family-share and family ledger calculations."""
from decimal import Decimal

import domain as D
from errors import fail
from services import compute
from store import (db, dec, month_of, ordered, q, q1, round_half_up_int,
                   set_field, set_fields)

TIERS = (
    ("TIER_0", Decimal("250.0"), Decimal("0.00"), 0),
    ("TIER_1", Decimal("400.0"), Decimal("0.05"), 12000),
    ("TIER_2", Decimal("600.0"), Decimal("0.10"), 30000),
    ("TIER_3", None, Decimal("0.15"), 60000),
)


def fpl_threshold_cents(household_size):
    return (D.FPL_BASE_CENTS
            + (household_size - 1) * D.FPL_PER_ADDITIONAL_MEMBER_CENTS)


def fpl_percent(income_cents, threshold_cents):
    return q(Decimal(income_cents) * Decimal(100) / Decimal(threshold_cents), 1)


def tier_for(percent):
    for code, ceiling, rate, cap in TIERS:
        if ceiling is None or percent <= ceiling:
            return code, rate, cap
    return TIERS[-1][0], TIERS[-1][2], TIERS[-1][3]


def eligible_fee_lines(referral):
    """Lines of the case's ACTIVE plan that attract a family fee."""
    plan = compute.active_ifsp(referral)
    if plan is None:
        return []
    out = []
    for line in compute.ifsp_lines(plan["id"]):
        if line["status"] not in D.SERVICE_LIVE_STATUSES:
            continue
        if line["declined_by_family"]:
            continue
        if line["family_fee_exempt"]:
            continue
        out.append(line)
    return out


def monthly_raw_cents(referral, rate):
    """Per-line rounding before summation, in created_at order."""
    total = 0
    for line in eligible_fee_lines(referral):
        gross = (Decimal(line["frequency_per_month"])
                 * Decimal(line["units_per_session"])
                 * Decimal(line["unit_rate_cents"]))
        total += round_half_up_int(gross * rate)
    return total


def recompute_cost_share(cost_share, final):
    """calculation: family_cost_share (provisional and final variants)."""
    referral = db.referrals.get(cost_share["referral_id"])
    household = cost_share["household_size"]
    threshold = fpl_threshold_cents(household)
    income = (cost_share["verified_annual_gross_income_cents"] if final
              else cost_share["declared_annual_gross_income_cents"])
    percent = fpl_percent(income, threshold)
    tier_code, rate, cap = tier_for(percent)
    raw = monthly_raw_cents(referral, rate) if referral is not None else 0
    capped = min(raw, cap)
    values = {
        "fpl_threshold_cents": threshold,
        "fpl_percent": float(percent),
        "tier_code": tier_code,
        "coinsurance_rate": float(rate),
        "monthly_cap_cents": cap,
        "effective_coinsurance_rate": float(rate),
    }
    if final:
        # PRD 3.8: finalization recomputes fpl_percent, tier_code,
        # coinsurance_rate, monthly_cap_cents and effective_coinsurance_rate
        # only. assessed_monthly_fee_cents is the provisional-variant store and
        # is left exactly as determination time computed it.
        if cost_share["insurance_use_consent"] and cost_share["insurance_policy_id"]:
            offset = round_half_up_int(Decimal(capped)
                                       * Decimal(D.INSURANCE_OFFSET_RATE))
        else:
            offset = 0
        values["insurance_offset_cents"] = offset
        values["final_monthly_fee_cents"] = capped - offset
    else:
        values["assessed_monthly_fee_cents"] = capped
        values["insurance_offset_cents"] = 0
        values["final_monthly_fee_cents"] = None
    set_fields(cost_share, values)


def select_cost_share(referral_id, bucket):
    """The determination that governs charges in the given YYYY-MM bucket."""
    candidates = [c for c in compute.referral_cost_shares(referral_id)
                  if c["status"] in D.COST_SHARE_LIVE
                  and c["effective_month"] <= bucket]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["effective_month"], c["created_at"], c["_seq"]))
    return candidates[-1]


def compute_visit_share(visit, authorization, line, referral):
    """calculation: visit_family_share_cents -> (share_cents, billing_status, row)."""
    bucket = month_of(visit["scheduled_start"])
    selected = select_cost_share(referral["id"], bucket) if referral else None
    if selected is None:
        return 0, "EXEMPT", None
    rate = dec(selected["effective_coinsurance_rate"] or 0)
    if line["family_fee_exempt"] or rate == 0:
        return 0, "EXEMPT", selected
    raw = round_half_up_int(Decimal(visit["actual_units"])
                           * Decimal(authorization["unit_rate_cents"]) * rate)
    remainder = (selected["monthly_cap_cents"] or 0) - (selected["month_accrued_cents"] or 0)
    if remainder <= 0:
        return 0, "CAPPED", selected
    share = min(raw, remainder)
    billing = "CAPPED" if share < raw else "ACCRUED"
    return share, billing, selected


def apply_charge(cost_share, amount):
    if cost_share is None or amount == 0:
        return
    set_fields(cost_share, {
        "month_accrued_cents": (cost_share["month_accrued_cents"] or 0) + amount,
        "total_assessed_cents": (cost_share["total_assessed_cents"] or 0) + amount,
        "family_balance_cents": (cost_share["family_balance_cents"] or 0) + amount,
    })


def reverse_charge(cost_share, amount):
    if cost_share is None or amount == 0:
        return
    set_fields(cost_share, {
        "month_accrued_cents": (cost_share["month_accrued_cents"] or 0) - amount,
        "total_assessed_cents": (cost_share["total_assessed_cents"] or 0) - amount,
        "family_balance_cents": (cost_share["family_balance_cents"] or 0) - amount,
    })


def assert_ledger(cost_share):
    """calculation: family_ledger invariant."""
    if cost_share is None:
        return
    assessed = cost_share["total_assessed_cents"] or 0
    balance = cost_share["family_balance_cents"] or 0
    waived = cost_share["family_waived_cents"] or 0
    if balance < 0 or waived < 0 or assessed < 0 or assessed != balance + waived:
        fail("ERR_LEDGER_WOULD_UNBALANCE",
             "The family ledger identity would not hold after this write.")
