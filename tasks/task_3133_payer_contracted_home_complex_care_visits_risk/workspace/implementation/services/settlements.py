"""Settlement calculations per PRD §3.7 and SCAFFOLD §1.3.

Evaluation order is pinned: per-member delta → pool → split → withhold →
release. There is no true cycle; the order is pinned so a reader cannot
accidentally compute the withhold before the pool.
"""
from decimal import Decimal

from db import db
from services.calculations import round_cents


def enrolled_members_for_period(contract, period_index, settlements_for_contract):
    """PRD §3.7 / enrolled_member_months: distinct members attributed to this
    contract with a MemberEnrollment ACTIVE at any point during the period.

    Period boundaries: for the first settlement, [program creation,
    current_period_index]; for later settlements, (previous settlement's
    period_index, current period_index].
    """
    prior_indices = [s["period_index"] for s in settlements_for_contract]
    lower = max(prior_indices) if prior_indices else None

    member_ids = set()
    for member in db.members.values():
        if member.get("payer_contract_id") != contract.get("id"):
            continue
        for enr in db.enrollments.values():
            if enr.get("member_id") != member.get("id"):
                continue
            activated = enr.get("activated_period_index")
            disenrolled = enr.get("disenrolled_period_index")
            if activated is None:
                continue
            if activated > period_index:
                continue
            if lower is not None and disenrolled is not None and disenrolled <= lower:
                continue
            member_ids.add(member["id"])
            break
    return [db.members[mid] for mid in member_ids]


def compute_settlement_amounts(contract, period_index, settlements_for_contract):
    """Compute gross/withhold for the settlement at creation (PROVISIONAL).

    withhold_released_cents and net_payment_cents remain null until FINALIZED.
    Returns a dict of computed fields.
    """
    members = enrolled_members_for_period(contract, period_index,
                                          settlements_for_contract)
    enrolled_count = len(members)

    result = {
        "enrolled_member_count": enrolled_count,
        "gross_capitation_cents": None,
        "gross_savings_share_cents": None,
        "quality_withhold_cents": 0,
        "withhold_released_cents": None,
        "net_payment_cents": None,
    }

    withhold_pct = Decimal(str(contract.get("quality_withhold_pct", 0.10)))

    if contract.get("payment_model") == "CAPITATED":
        gross = enrolled_count * int(contract.get("pmpm_rate_cents") or 0)
        result["gross_capitation_cents"] = gross
        result["quality_withhold_cents"] = round_cents(Decimal(gross) * withhold_pct)
    else:
        # SHARED_SAVINGS — pinned multi-step order
        baseline = int(contract.get("shared_savings_baseline_pmpm_cents") or 0)
        pooled = 0
        for member in members:
            actual = 0
            for cost in db.medical_costs.values():
                if (cost.get("member_id") == member["id"]
                        and cost.get("period_index") == period_index):
                    actual += int(cost.get("amount_cents") or 0)
            pooled += baseline - actual
        if pooled <= 0:
            gross_share = 0
        else:
            split_pct = Decimal(str(contract.get("shared_savings_split_pct")))
            gross_share = round_cents(Decimal(pooled) * split_pct)
        result["gross_savings_share_cents"] = gross_share
        result["quality_withhold_cents"] = round_cents(
            Decimal(gross_share) * withhold_pct)

    return result


def finalize_settlement(contract, settlement):
    """Compute withhold release and net payment at finalize time."""
    enrolled_count = int(settlement.get("enrolled_member_count") or 0)
    threshold = Decimal(str(contract.get("min_performance_threshold", 0.80)))

    qualifying = 0
    for m in db.measurements.values():
        if m.get("payer_contract_id") != contract.get("id"):
            continue
        if m.get("period_index") != settlement.get("period_index"):
            continue
        score = m.get("composite_score")
        if score is not None and Decimal(str(score)) >= threshold:
            qualifying += 1

    if enrolled_count > 0:
        release_fraction = Decimal(qualifying) / Decimal(enrolled_count)
    else:
        release_fraction = Decimal(0)

    withhold = int(settlement.get("quality_withhold_cents") or 0)
    released = round_cents(Decimal(withhold) * release_fraction)

    if contract.get("payment_model") == "CAPITATED":
        gross = int(settlement.get("gross_capitation_cents") or 0)
    else:
        gross = int(settlement.get("gross_savings_share_cents") or 0)

    net = gross - withhold + released
    settlement["withhold_released_cents"] = released
    settlement["net_payment_cents"] = net
