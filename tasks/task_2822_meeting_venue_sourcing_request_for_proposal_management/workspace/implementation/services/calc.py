"""Deterministic calculation rules (PRD section 3 and the calculations table)."""
from datetime import timedelta
from decimal import Decimal

from money import D, q2, q4, floor_int, ceil_int

ONE = Decimal("1")

# proposal_total_cost_model
AV_TIER_1_CEILING = Decimal("10000.00")
AV_TIER_2_CEILING = Decimal("25000.00")
AV_TIER_1_FACTOR = Decimal("1.00")
AV_TIER_2_FACTOR = Decimal("0.95")
AV_TIER_3_FACTOR = Decimal("0.90")
CONCESSION_CAP_PCT = Decimal("0.08")
ACTUALIZED_PICKUP_SHRINK_PCT = Decimal("0.12")
ATTRITION_DAMAGE_RATE_PCT = Decimal("0.80")

# rate_benchmark_compliance
MAX_PROGRAM_PREMIUM_PCT = Decimal("0.1000")

# contract_volume_rebate
REBATE_TIER_1_CEILING = Decimal("150000.00")
REBATE_TIER_2_CEILING = Decimal("400000.00")
REBATE_PCT_TIER_0 = Decimal("0.000")
REBATE_PCT_TIER_1 = Decimal("0.020")
REBATE_PCT_TIER_2 = Decimal("0.035")

# deposit_schedule_allocation
DEPOSIT_TOTAL_PCT = Decimal("0.30")
DEPOSIT_WEIGHTS = (Decimal("0.34"), Decimal("0.33"), Decimal("0.33"))
DEPOSIT_OFFSET_DAYS = (180, 90, 30)

# approval_route_generation
VP_THRESHOLD_USD = Decimal("250000.00")
LEGAL_THRESHOLD_USD = Decimal("500000.00")
PROGRAM_COMPLIANCE_STATUSES = ("NONE", "CONDITIONAL")

# venue_performance_score
WEIGHT_SERVICE = Decimal("0.35")
WEIGHT_VALUE = Decimal("0.25")
WEIGHT_AV = Decimal("0.20")
WEIGHT_RESPONSIVENESS = Decimal("0.20")
RECENCY_DECAY = Decimal("0.7")


def comp_and_paid_nights(room_nights_offered, comp_room_ratio):
    """floor division; a ratio of zero yields no complimentary nights."""
    if comp_room_ratio == 0:
        comp = 0
    else:
        comp = floor_int(D(room_nights_offered) / D(comp_room_ratio))
    return comp, room_nights_offered - comp


def net_adr(room_rate_usd, rate_type, commission_pct):
    if rate_type == "GROSS":
        return q2(D(room_rate_usd) * (ONE - D(commission_pct)))
    return q2(D(room_rate_usd))


def av_adjusted(av_estimate_usd):
    av = D(av_estimate_usd)
    if av <= AV_TIER_1_CEILING:
        return q2(av * AV_TIER_1_FACTOR)
    if av <= AV_TIER_2_CEILING:
        return q2(av * AV_TIER_2_FACTOR)
    return q2(av * AV_TIER_3_FACTOR)


def cost_model(proposal, basis):
    """Both variants of proposal_total_cost_model in the pinned order."""
    comp_nights, paid_nights = comp_and_paid_nights(
        proposal["room_nights_offered"], proposal["comp_room_ratio"]
    )
    adr = net_adr(
        proposal["room_rate_usd"], proposal["rate_type"], proposal["commission_pct"]
    )
    av_value = av_adjusted(proposal["av_estimate_usd"])

    if basis == "ACTUALIZED_BASIS":
        projected = ceil_int(D(paid_nights) * (ONE - ACTUALIZED_PICKUP_SHRINK_PCT))
        allowance_floor = floor_int(
            D(paid_nights) * (ONE - D(proposal["attrition_allowance_pct"]))
        )
        shortfall = allowance_floor - projected
        if shortfall < 0:
            shortfall = 0
        damages = q2(D(shortfall) * adr * ATTRITION_DAMAGE_RATE_PCT)
        nights_used = projected
    else:
        shortfall = 0
        damages = q2(0)
        nights_used = paid_nights

    room_revenue = q2(adr * D(nights_used))
    resort_fee_total = q2(D(proposal["resort_fee_usd_per_night"]) * D(nights_used))
    fnb = q2(proposal["fnb_minimum_usd"])
    service_charge = q2(
        (room_revenue + fnb + av_value) * D(proposal["service_charge_pct"])
    )
    tax = q2(
        (room_revenue + resort_fee_total + fnb + av_value + service_charge)
        * D(proposal["tax_pct"])
    )
    gross = room_revenue + resort_fee_total + fnb + av_value + service_charge + tax
    concession_cap = q2(CONCESSION_CAP_PCT * room_revenue)
    concession_applied = min(q2(proposal["concession_credit_usd"]), concession_cap)
    total = q2(gross - concession_applied + damages)

    return {
        "basis": basis,
        "comp_room_nights": comp_nights,
        "paid_room_nights": paid_nights,
        "net_adr_usd": adr,
        "av_adjusted_usd": av_value,
        "paid_room_nights_used": nights_used,
        "attrition_shortfall_nights": shortfall,
        "attrition_damages_usd": damages,
        "room_revenue_usd": room_revenue,
        "resort_fee_total_usd": resort_fee_total,
        "fnb_usd": fnb,
        "service_charge_usd": service_charge,
        "tax_usd": tax,
        "gross_usd": gross,
        "concession_cap_usd": concession_cap,
        "concession_applied_usd": concession_applied,
        "total_cost_usd": total,
    }


def benchmark_compliance(adr, benchmark_adr_usd, preferred_supplier_status):
    """rate_benchmark_compliance -> (variance 4dp, compliance_status)."""
    benchmark_adr = D(benchmark_adr_usd)
    variance = q4((D(adr) - benchmark_adr) / benchmark_adr)
    if preferred_supplier_status == "SUSPENDED":
        return variance, "NON_COMPLIANT"
    if preferred_supplier_status in ("PREFERRED", "CONDITIONAL"):
        if variance <= Decimal("0.0000"):
            return variance, "COMPLIANT"
        if variance <= MAX_PROGRAM_PREMIUM_PCT:
            return variance, "COMPLIANT_WITH_VARIANCE"
        return variance, "NON_COMPLIANT"
    # preferred_supplier_status == NONE
    if variance <= Decimal("0.0000"):
        return variance, "COMPLIANT_WITH_VARIANCE"
    return variance, "NON_COMPLIANT"


def volume_rebate(pre_rebate_total_usd):
    """contract_volume_rebate -> (pct, rebate, contracted_total)."""
    pre = q2(pre_rebate_total_usd)
    if pre < REBATE_TIER_1_CEILING:
        pct = REBATE_PCT_TIER_0
    elif pre < REBATE_TIER_2_CEILING:
        pct = REBATE_PCT_TIER_1
    else:
        pct = REBATE_PCT_TIER_2
    rebate = q2(pre * pct)
    return pct, rebate, q2(pre - rebate)


def deposit_allocation(contracted_total_usd, start_date):
    """deposit_schedule_allocation -> (deposit_total, [installment dicts])."""
    deposit_total = q2(D(contracted_total_usd) * DEPOSIT_TOTAL_PCT)
    amounts = [q2(deposit_total * weight) for weight in DEPOSIT_WEIGHTS]
    residual = q2(deposit_total - sum(amounts, q2(0)))
    amounts[-1] = q2(amounts[-1] + residual)
    rows = []
    for index, weight in enumerate(DEPOSIT_WEIGHTS):
        rows.append({
            "installment_seq": index + 1,
            "weight_pct": weight,
            "amount_usd": amounts[index],
            "due_date": start_date - timedelta(days=DEPOSIT_OFFSET_DAYS[index]),
        })
    return deposit_total, rows


def days_to_arrival(start_instant, now_instant):
    seconds = (start_instant - now_instant).total_seconds()
    return floor_int(D(seconds) / D(86400))


def cancellation_fee(schedule, contracted_room_revenue_usd, rebooking_credit_pct,
                     days_out):
    """contract_cancellation_fee -> (fee, rebooking_credit)."""
    tier = None
    for candidate in schedule or []:
        if candidate["days_before_arrival_min"] <= days_out:
            if tier is None or (candidate["days_before_arrival_min"]
                               > tier["days_before_arrival_min"]):
                tier = candidate
    if tier is None:
        fee = q2(0)
    else:
        fee = q2(D(contracted_room_revenue_usd) * D(tier["fee_pct"]))
    credit = q2(fee * D(rebooking_credit_pct))
    return fee, credit


def approval_route(preferred_supplier_status, contracted_total_usd,
                   force_majeure_scope):
    """approval_route_generation -> ordered list of (level, required_role)."""
    total = D(contracted_total_usd)
    levels = []
    if preferred_supplier_status in PROGRAM_COMPLIANCE_STATUSES:
        levels.append("PROGRAM_COMPLIANCE")
    levels.append("MANAGER")
    if total >= VP_THRESHOLD_USD:
        levels.append("VP")
    if total >= LEGAL_THRESHOLD_USD or force_majeure_scope == "NARROW":
        levels.append("LEGAL")
    return [(level, required_role_for(level)) for level in levels]


def required_role_for(level):
    return "ProgramAdmin" if level == "PROGRAM_COMPLIANCE" else "ContractApprover"


def composite_score(service, value, av_quality, responsiveness):
    return q2(
        WEIGHT_SERVICE * D(service)
        + WEIGHT_VALUE * D(value)
        + WEIGHT_AV * D(av_quality)
        + WEIGHT_RESPONSIVENESS * D(responsiveness)
    )


def performance_scores(reviews):
    """venue_performance_score -> (recency weighted, simple mean).

    Reviews are ranked created_at DESC then composite_score DESC; rank 1 gets
    weight 0.7**0.  The weighted quotient is formed before rounding.
    """
    if not reviews:
        return None, None
    ranked = sorted(
        reviews,
        key=lambda r: (r["created_at"], r["composite_score"]),
        reverse=True,
    )
    weighted_sum = Decimal("0")
    weight_sum = Decimal("0")
    plain_sum = Decimal("0")
    for index, review in enumerate(ranked):
        weight = RECENCY_DECAY ** index
        weighted_sum += weight * D(review["composite_score"])
        weight_sum += weight
        plain_sum += D(review["composite_score"])
    return q2(weighted_sum / weight_sum), q2(plain_sum / D(len(ranked)))


def post_event_savings(contract, event, benchmark_adr_usd, actual_room_nights,
                       actual_fnb_usd, actual_av_usd):
    """post_event_savings.  The realized resort fee is an intermediate only."""
    contracted_nights = contract["contracted_paid_room_nights"]
    rate = D(contract["contracted_room_rate_usd"])
    allowed = floor_int(
        D(contracted_nights) * (ONE - D(contract["attrition_allowance_pct"]))
    )
    shortfall = allowed - actual_room_nights
    if shortfall < 0:
        shortfall = 0
    attrition_charge = q2(D(shortfall) * rate * ATTRITION_DAMAGE_RATE_PCT)

    actual_room_cost = q2(rate * D(actual_room_nights))
    actual_resort_fee = q2(
        D(contract["resort_fee_usd_per_night"]) * D(actual_room_nights)
    )
    fnb = q2(actual_fnb_usd)
    av = q2(actual_av_usd)
    realized_service_charge = q2(
        (actual_room_cost + fnb + av) * D(contract["service_charge_pct"])
    )
    realized_tax = q2(
        (actual_room_cost + actual_resort_fee + fnb + av + realized_service_charge)
        * D(contract["tax_pct"])
    )
    realized_total = q2(
        actual_room_cost
        + actual_resort_fee
        + fnb
        + av
        + realized_service_charge
        + realized_tax
        + attrition_charge
        - D(contract["concession_applied_usd"])
    )
    benchmark_room_cost = q2(D(benchmark_adr_usd) * D(actual_room_nights))
    return {
        "attrition_allowed_nights": allowed,
        "attrition_shortfall_nights": shortfall,
        "attrition_charge_usd": attrition_charge,
        "actual_room_cost_usd": actual_room_cost,
        "realized_resort_fee_usd": actual_resort_fee,
        "realized_service_charge_usd": realized_service_charge,
        "realized_tax_usd": realized_tax,
        "realized_total_usd": realized_total,
        "benchmark_room_cost_usd": benchmark_room_cost,
        "savings_vs_benchmark_usd": q2(benchmark_room_cost - actual_room_cost),
        "savings_vs_budget_usd": q2(D(event["budget_ceiling_usd"]) - realized_total),
    }


def peak_rooms_per_night(contracted_paid_room_nights, nights_span):
    if not nights_span:
        return contracted_paid_room_nights
    return ceil_int(D(contracted_paid_room_nights) / D(nights_span))
