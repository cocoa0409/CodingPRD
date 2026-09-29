"""The pinned calculations of PRD section 3.

Every monetary result is an integer number of cents and every rounding step
uses ROUND_HALF_UP at exactly the point the PRD pins it.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

import config
from store import parse_date, days_between, add_days

ZERO = Decimal(0)


def half_up(value):
    """ROUND_HALF_UP to a whole unit, returned as int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def q3(value):
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def q2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num3(value):
    """A 3-decimal Decimal rendered for JSON."""
    return float(q3(value))


def num2(value):
    return float(q2(value))


# --------------------------------------------------------------------------
# 1. effective_monthly_dues (PRD 3.3)
# --------------------------------------------------------------------------
def effective_monthly_dues(base_cents, discount_pct, corporate_credit_pct, multi_club_access):
    base = Decimal(base_cents)
    promo = half_up(base * discount_pct) if discount_pct is not None else 0
    corporate = half_up(base * corporate_credit_pct) if corporate_credit_pct is not None else 0
    multi = half_up(base * config.MULTI_CLUB_CREDIT_PCT) if multi_club_access else 0
    total_discount = promo + corporate + multi
    return {
        "promo_discount_cents": promo,
        "corporate_credit_cents": corporate,
        "multi_club_credit_cents": multi,
        "total_discount_cents": total_discount,
        "gross_monthly_dues_cents": base_cents - total_discount,
    }


# --------------------------------------------------------------------------
# 2. royalty_due (PRD 3.9)
# --------------------------------------------------------------------------
def royalty_from_basis(basis_cents, royalty_rate_bps):
    return half_up(Decimal(basis_cents) * Decimal(royalty_rate_bps) / Decimal(10000))


def variance_pct(reported_member_count, verified_member_count):
    if verified_member_count == 0:
        return Decimal("0.00") if reported_member_count == 0 else Decimal("100.00")
    raw = (Decimal(reported_member_count) - Decimal(verified_member_count)) * Decimal(100) \
        / Decimal(verified_member_count)
    return q2(raw)


# --------------------------------------------------------------------------
# 3. inspection_score (PRD 3.9)
# --------------------------------------------------------------------------
def refresh_variant(club):
    accelerated = (club["opened_on"] < config.ACCELERATED_MANDATE_DATE
                   or club["equipment_compliance_state"] == "WATCH")
    if accelerated:
        return "ACCELERATED_CYCLE", config.ACCELERATED_REFRESH_CYCLE_MONTHS
    return "STANDARD_CYCLE", config.BRAND_REFRESH_CYCLE_MONTHS


def refresh_points(equipment_age_months_max, cycle_months):
    used = half_up(Decimal(100) * Decimal(equipment_age_months_max) / Decimal(cycle_months))
    return max(0, 100 - used)


def inspection_score(equipment_condition_pts, cleanliness_pts, safety_pts, refresh_pts):
    total = (Decimal(equipment_condition_pts) * Decimal("0.40")
             + Decimal(cleanliness_pts) * Decimal("0.25")
             + Decimal(safety_pts) * Decimal("0.20")
             + Decimal(refresh_pts) * Decimal("0.15"))
    return half_up(total)


def compliance_state_for(score):
    if score >= 85:
        return "COMPLIANT"
    if score >= 70:
        return "WATCH"
    return "NON_COMPLIANT"


# --------------------------------------------------------------------------
# 4. usage_settlement_net (PRD 3.7)
# --------------------------------------------------------------------------
def usage_settlement_net(gross_fee_cents):
    admin_hold = half_up(Decimal(gross_fee_cents) * config.ADMIN_HOLD_PCT)
    net_before = gross_fee_cents - admin_hold
    if net_before < config.REBATE_TIER_1_FLOOR:
        rebate_pct = Decimal("0.00")
    elif net_before < config.REBATE_TIER_2_FLOOR:
        rebate_pct = Decimal("0.03")
    else:
        rebate_pct = Decimal("0.06")
    volume_rebate = half_up(Decimal(net_before) * rebate_pct)
    return {
        "gross_fee_cents": gross_fee_cents,
        "admin_hold_cents": admin_hold,
        "net_before_rebate_cents": net_before,
        "rebate_pct": float(rebate_pct.quantize(Decimal("0.01"))),
        "volume_rebate_cents": volume_rebate,
        "net_payable_cents": net_before - volume_rebate,
    }


# --------------------------------------------------------------------------
# 6. cancellation_settlement (PRD 3.5)
# --------------------------------------------------------------------------
def notice_refund(effective_monthly_dues_cents, dues_paid_cents, signed_on,
                  cancellation_effective_on, prorates):
    """Branch B refund."""
    if effective_monthly_dues_cents <= 0:
        periods = 0
    else:
        periods = dues_paid_cents // effective_monthly_dues_cents
    paid_through = add_days(parse_date(signed_on), 30 * periods)
    unused_days = days_between(paid_through, parse_date(cancellation_effective_on))
    if prorates and unused_days > 0:
        refund = half_up(Decimal(effective_monthly_dues_cents) * Decimal(unused_days)
                         / Decimal(30))
    else:
        refund = 0
    return refund, unused_days, paid_through.isoformat()


def early_termination_fee(effective_monthly_dues_cents, cancellation_effective_on, term_end_on):
    days = days_between(parse_date(term_end_on), parse_date(cancellation_effective_on))
    if days <= 0:
        remaining_months = 0
    else:
        remaining_months = int((Decimal(days) / Decimal(30))
                               .quantize(Decimal("1"), rounding=ROUND_CEILING))
    monthly = half_up(Decimal(effective_monthly_dues_cents) * config.EARLY_TERM_MONTHLY_PCT)
    product = monthly * remaining_months
    return min(product, config.EARLY_TERM_FEE_CAP_CENTS), remaining_months


# --------------------------------------------------------------------------
# 7. transfer_fee (PRD 3.6)
# --------------------------------------------------------------------------
def transfer_fee(from_club, to_club, effective_monthly_dues_cents):
    if from_club["franchisee_id"] == to_club["franchisee_id"]:
        return 0
    component = half_up(Decimal(effective_monthly_dues_cents) * config.CROSS_FRANCHISE_TRANSFER_PCT)
    return config.TRANSFER_FEE_BASE_CENTS + component


# --------------------------------------------------------------------------
# 8. territory_encroachment_slack (PRD 3.1)
# --------------------------------------------------------------------------
def encroachment_clearance(lat, lng, radius_km, candidates):
    """Smallest clearance across candidates, or None when there are none."""
    best = None
    for cand in candidates:
        dlat = (Decimal(str(lat)) - Decimal(str(cand["center_lat"]))) * config.KM_PER_DEG_LAT
        dlng = (Decimal(str(lng)) - Decimal(str(cand["center_lng"]))) * config.KM_PER_DEG_LNG
        distance = q3((dlat * dlat + dlng * dlng).sqrt())
        required = (Decimal(str(radius_km)) + Decimal(str(cand["protected_radius_km"]))
                    + config.PROTECTION_BUFFER_KM)
        clearance = q3(distance - required)
        if best is None or clearance < best:
            best = clearance
    return best


# --------------------------------------------------------------------------
# 11. corporate_allocation (PRD 3.8)
# --------------------------------------------------------------------------
def allocate_pool(pool_cents, eligible):
    """`eligible` is a list of dicts {franchisee, weight}; returns {id: share}."""
    total_weight = sum(e["weight"] for e in eligible)
    shares = {}
    base_total = 0
    for e in eligible:
        share = (pool_cents * e["weight"]) // total_weight
        shares[e["franchisee"]["id"]] = share
        base_total += share
    remainder = pool_cents - base_total
    order = sorted(eligible, key=lambda e: (-e["weight"], e["franchisee"]["created_at"],
                                            e["franchisee"]["_seq"]))
    for i in range(remainder):
        shares[order[i]["franchisee"]["id"]] += 1
    return shares
