"""Pure calculation rules (SCAFFOLD section 1.3 / PRD 2.10, 3.4-3.10).

Each function takes records already resolved by the caller and returns the
value the rule produces.  Nothing here mutates state.
"""
from decimal import Decimal

from config import (
    ANNOUNCED_WEIGHT,
    BAND_BASE_CENTS,
    CRITICAL_PENALTY_PER_FINDING,
    HOURLY_RATE_CENTS,
    MULTI_BRAND_DISCOUNT,
    MULTI_BRAND_MIN,
    MYSTERY_SHOP_WEIGHT,
    PASS_MIN,
    PRIORITY_HOURS_SCALE,
    SOURCE_MULTIPLIER,
    TRANSFER_FEE_RATE,
    VALUE_UNIT_CENTS,
    VALUE_UNIT_RATE_CENTS,
    WATCH_MIN,
)
from derived import agreement_of, brand_of, effective_royalty_rate, value_units_of
from money import (
    as_number,
    ceil_div,
    ceil_int,
    dec,
    round_cents,
    round_tenth,
)


# ---------------------------------------------------------------------------
# standards_audit_score_calculation
# ---------------------------------------------------------------------------
def standards_audit_score(audit):
    """weighted_score, clamped to [0, 100] BEFORE the half-up rounding to 1dp."""
    kind = audit.get("audit_kind")
    weight = dec(ANNOUNCED_WEIGHT if kind == "ANNOUNCED" else MYSTERY_SHOP_WEIGHT)
    if kind not in ("ANNOUNCED", "MYSTERY_SHOP"):
        weight = dec(ANNOUNCED_WEIGHT)
    raw = dec(audit.get("raw_score"))
    critical = int(audit.get("critical_findings_count") or 0)
    pre_clamp = (raw * weight) - (dec(CRITICAL_PENALTY_PER_FINDING) * critical)
    if pre_clamp < Decimal("0"):
        pre_clamp = Decimal("0")
    if pre_clamp > Decimal("100"):
        pre_clamp = Decimal("100")
    return round_tenth(pre_clamp)


def audit_outcome(weighted_score):
    """The bands are inclusive at the bottom: >=85 PASS, >=70 WATCH, else FAIL."""
    score = dec(weighted_score)
    if score >= dec(PASS_MIN):
        return "PASS"
    if score >= dec(WATCH_MIN):
        return "WATCH"
    return "FAIL"


# ---------------------------------------------------------------------------
# labor_charge_calculation
# ---------------------------------------------------------------------------
def labor_charge(work_order):
    """The pinned order: ceil the priority-scaled hours, apply the hourly rate,
    then scale by the source multiplier, and round half up exactly once."""
    hours = int(work_order.get("service_level_hours") or 0)
    priority = work_order.get("priority")
    scale = dec(PRIORITY_HOURS_SCALE.get(priority, "1.0"))
    step_1_hours = max(1, ceil_int(dec(hours) * scale))
    rate = int(HOURLY_RATE_CENTS.get(priority, HOURLY_RATE_CENTS["STANDARD"]))
    step_2_base = step_1_hours * rate
    multiplier = dec(SOURCE_MULTIPLIER.get(work_order.get("source"), "1.00"))
    step_3_adj = dec(step_2_base) * multiplier
    return round_cents(step_3_adj)


def sla_due_hours(service_level_hours, priority):
    """Dispatch deadline scaling: EMERGENCY 0.5, URGENT 0.75, STANDARD 1.0,
    rounded up to whole hours."""
    scale = dec(PRIORITY_HOURS_SCALE.get(priority, "1.0"))
    scaled = dec(service_level_hours) * scale
    return max(1, ceil_int(scaled))


def labor_step_trace(work_order):
    """Diagnostic breakdown of the pinned three-step labor computation."""
    hours = int(work_order.get("service_level_hours") or 0)
    priority = work_order.get("priority")
    scale = dec(PRIORITY_HOURS_SCALE.get(priority, "1.0"))
    step_1_hours = max(1, ceil_int(dec(hours) * scale))
    rate = int(HOURLY_RATE_CENTS.get(priority, HOURLY_RATE_CENTS["STANDARD"]))
    step_2_base = step_1_hours * rate
    multiplier = dec(SOURCE_MULTIPLIER.get(work_order.get("source"), "1.00"))
    return {
        "step_1_hours": step_1_hours,
        "step_2_base": step_2_base,
        "step_3_adj": as_number(dec(step_2_base) * multiplier),
    }


# ---------------------------------------------------------------------------
# lead_cost_calculation
# ---------------------------------------------------------------------------
def lead_cost(lead, receiving_franchisee):
    """Band base plus the value surcharge, then the portfolio discount on the
    whole subtotal (the pinned evaluation order)."""
    band = lead.get("household_income_band")
    base = int(BAND_BASE_CENTS.get(band, 0))
    units = value_units_of(lead)
    surcharge = units * VALUE_UNIT_RATE_CENTS
    subtotal = base + surcharge
    brands = int((receiving_franchisee or {}).get("active_brand_count") or 0)
    if brands >= MULTI_BRAND_MIN:
        return round_cents(dec(subtotal) * dec(MULTI_BRAND_DISCOUNT))
    return subtotal


# ---------------------------------------------------------------------------
# referral_fee_calculation
# ---------------------------------------------------------------------------
def referral_fee(referral):
    """Returns (fee_cents, variant).  Only settled_job_value_cents participates."""
    receiving_agreement = agreement_of(referral.get("receiving_agreement_id"))
    originating_agreement = agreement_of(referral.get("originating_agreement_id"))
    receiving_brand = brand_of((receiving_agreement or {}).get("brand_id"))
    originating_brand = brand_of((originating_agreement or {}).get("brand_id"))
    settled = int(referral.get("settled_job_value_cents") or 0)

    table = (receiving_brand or {}).get("cross_brand_fee_table") or {}
    key = (originating_brand or {}).get("brand_code")
    if key is not None and isinstance(table, dict) and key in table:
        entry = table[key]
        rate = _table_rate(entry)
        return round_cents(rate * dec(settled)), "TIERED_BRAND_PAIR"
    return round_cents(dec(referral.get("referral_fee_rate")) * dec(settled)), "FLAT_RATE"


def _table_rate(entry):
    """The tiered table may be a bare number or a banded object carrying `rate`."""
    if isinstance(entry, dict):
        if entry.get("rate") is not None:
            return dec(entry["rate"])
        for _, band in sorted(entry.items()):
            if isinstance(band, dict) and band.get("rate") is not None:
                return dec(band["rate"])
    return dec(entry)


# ---------------------------------------------------------------------------
# transfer_fee_calculation
# ---------------------------------------------------------------------------
def transfer_fee(application):
    """The scaffold and PRD name this rule but supply no formula or constants,
    so the franchisor transfer fee resolves to zero for every disposition kind."""
    kind = application.get("transfer_kind")
    return round_cents(dec(TRANSFER_FEE_RATE.get(kind, "0")) * dec(application.get("purchase_price_cents")))


# ---------------------------------------------------------------------------
# royalty_accrual_calculation
# ---------------------------------------------------------------------------
def royalty_components(statement):
    """(royalty_component, ad_fund_component), each rounded independently."""
    agreement = agreement_of(statement.get("agreement_id"))
    if agreement is None:
        return 0, 0
    brand = brand_of(agreement.get("brand_id"))
    gross = dec(statement.get("gross_revenue_cents"))
    royalty_component = round_cents(gross * effective_royalty_rate(agreement))
    ad_fund_component = round_cents(gross * dec((brand or {}).get("national_ad_fund_rate")))
    return royalty_component, ad_fund_component


def royalty_draft(statement):
    """DRAFT_PROPORTIONAL: no cross-brand netting at all."""
    royalty_component, ad_fund_component = royalty_components(statement)
    royalty_cents = max(0, royalty_component)
    ad_fund_cents = ad_fund_component
    return {
        "accrual_variant": "DRAFT_PROPORTIONAL",
        "royalty_cents": royalty_cents,
        "ad_fund_cents": ad_fund_cents,
        "referral_offset_cents": 0,
        "net_remittance_cents": royalty_cents + ad_fund_cents,
    }


def royalty_final(statement):
    """FINAL_NETTED: components rounded first, the floor applied to the total last."""
    royalty_component, ad_fund_component = royalty_components(statement)
    royalty_cents = max(0, royalty_component)
    ad_fund_cents = ad_fund_component
    offset = referral_offset(statement.get("agreement_id"),
                             statement.get("period_start"),
                             statement.get("period_end"))
    net = royalty_cents + ad_fund_cents - offset
    return {
        "accrual_variant": "FINAL_NETTED",
        "royalty_cents": royalty_cents,
        "ad_fund_cents": ad_fund_cents,
        "referral_offset_cents": offset,
        "net_remittance_cents": max(0, net),
    }


# ---------------------------------------------------------------------------
# referral_offset_calculation
# ---------------------------------------------------------------------------
def referral_offset(agreement_id, period_start, period_end):
    """Earned minus owed over SETTLED referrals in the half-open window.

    Exact integer sums, no rounding, and deliberately not floored -- the floor
    belongs to net_remittance_cents instead.
    """
    from store import db, parse_instant

    start = parse_instant(period_start) if isinstance(period_start, str) else period_start
    end = parse_instant(period_end) if isinstance(period_end, str) else period_end
    earned = 0
    owed = 0
    for r in db.referrals.values():
        if r.get("status") != "SETTLED":
            continue
        settled = parse_instant(r.get("settled_clock_iso")) if isinstance(
            r.get("settled_clock_iso"), str) else r.get("settled_clock_iso")
        if settled is None or start is None or end is None:
            continue
        if not (settled >= start and settled < end):
            continue
        fee = int(r.get("referral_fee_cents") or 0)
        if r.get("originating_agreement_id") == agreement_id:
            earned += fee
        if r.get("receiving_agreement_id") == agreement_id:
            owed += fee
    return earned - owed


# ---------------------------------------------------------------------------
# recipient_selection_calculation
# ---------------------------------------------------------------------------
def lead_ranking(lead):
    """(candidate_ids_in_rank_order, ranking_keys, selected_id_or_None).

    Eligibility predicate, ranking key and tie-break are exactly the scaffold's;
    no random identifier participates.
    """
    from store import db, now_dt, parse_instant

    clock = now_dt()
    brand_id = lead.get("brand_id")
    candidates = []
    for agreement in db.agreements.values():
        if agreement.get("brand_id") != brand_id:
            continue
        if agreement.get("lifecycle_status") != "ACTIVE":
            continue
        franchisee = db.franchisees.get(agreement.get("franchisee_id"))
        if franchisee is None:
            continue
        if franchisee.get("status") != "ACTIVE":
            continue
        if not franchisee.get("shared_services_enrolled"):
            continue
        blockers = [
            l for l in db.leads.values()
            if l.get("allocated_agreement_id") == agreement["id"]
            and l.get("status") == "ALLOCATED"
            and _hold_after(l.get("allocation_hold_until_iso"), clock)
        ]
        if blockers:
            continue
        candidates.append(agreement)

    def load(agreement):
        return len([
            l for l in db.leads.values()
            if l.get("allocated_agreement_id") == agreement["id"] and l.get("status") == "ALLOCATED"
        ])

    def key(agreement):
        return (load(agreement), _instant_key(agreement.get("created_at")), agreement.get("_seq") or 0)

    ranked = sorted(candidates, key=key)
    return [a["id"] for a in ranked], [load(a) for a in ranked], (ranked[0]["id"] if ranked else None)


def _hold_after(value, clock):
    from store import parse_instant
    if not isinstance(value, str):
        return False
    parsed = parse_instant(value)
    return parsed is not None and parsed > clock


def _instant_key(value):
    from store import parse_instant
    parsed = parse_instant(value) if isinstance(value, str) else None
    return parsed.isoformat() if parsed else ""


def commitment_attainment(accumulated_revenue_cents, annual_commitment_cents):
    from money import round_ten_thousandth
    commitment = int(annual_commitment_cents or 0)
    if commitment <= 0:
        return 0
    return as_number(round_ten_thousandth(dec(accumulated_revenue_cents) / dec(commitment)))