"""The actuarial block of a rate filing and the severity trend read (PRD 3.1, 3.9)."""
from decimal import Decimal

import constants as C
from store import db, sorted_records, touch
from val import ZERO, d, r2, r4

from services import rating

ONE = Decimal("1")
HUNDRED = Decimal("100")


def insureds_in_class(specialty_class_id):
    return sorted_records(
        [i for i in db.insureds.values() if i["specialty_class_id"] == specialty_class_id]
    )


def claim_scope(filing):
    """Claims of the class, COVERED or RESERVED_RIGHTS, reported inside the period."""
    start = d(filing["experience_period_start"])
    end = d(filing["experience_period_end"])
    scope = []
    for insured in insureds_in_class(filing["specialty_class_id"]):
        for claim in rating.claims_of(insured["id"]):
            if claim["coverage_status"] not in ("COVERED", "RESERVED_RIGHTS"):
                continue
            report = d(claim["report_date"])
            if report < start or report > end:
                continue
            scope.append(claim)
    return sorted_records(scope)


def premium_scope(filing):
    start = d(filing["experience_period_start"])
    end = d(filing["experience_period_end"])
    terms = []
    for insured in insureds_in_class(filing["specialty_class_id"]):
        for policy in rating.policies_of(insured["id"]):
            for term in rating.terms_of(policy["id"]):
                if term["status"] not in ("IN_FORCE", "EXPIRED", "CANCELLED_PRO_RATA"):
                    continue
                if d(term["effective_date"]) > end:
                    continue
                if d(term["expiration_date"]) <= start:
                    continue
                terms.append(term)
    return sorted_records(terms)


def run_block(filing):
    """Recompute the whole actuarial block from current data."""
    specialty = db.specialty_classes[filing["specialty_class_id"]]
    claims = claim_scope(filing)
    filing["claim_count_in_scope"] = len(claims)

    required = ZERO
    carried = ZERO
    incurred = ZERO
    for claim in claims:
        venue_factor = C.VENUE_SEVERITY_FACTOR[claim["venue_code"]]
        required += r2(
            claim["demand_amount"]
            * claim["severity_band_factor"]
            * venue_factor
            * C.EXPENSE_LOADED_FACTOR
        )
        carried += r2(claim["indemnity_reserve"] + claim["expense_reserve"])
        incurred += claim["actuarial_incurred"]
    filing["required_reserve_total"] = r2(required)
    filing["carried_reserve_total"] = r2(carried)
    filing["actuarial_incurred_total"] = r2(incurred)

    if filing["required_reserve_total"] == ZERO:
        filing["reserve_adequacy_ratio"] = None
        filing["adequacy_flag"] = "NOT_EVALUABLE"
    else:
        ratio = r4(filing["carried_reserve_total"] / filing["required_reserve_total"])
        filing["reserve_adequacy_ratio"] = ratio
        if ratio < C.ADEQUACY_DEFICIENT_MAX:
            filing["adequacy_flag"] = "DEFICIENT"
        elif ratio <= C.ADEQUACY_REDUNDANT_MIN:
            filing["adequacy_flag"] = "ADEQUATE"
        else:
            filing["adequacy_flag"] = "REDUNDANT"

    premium = ZERO
    for term in premium_scope(filing):
        premium += term["premium_net"]
    filing["in_scope_premium_total"] = r2(premium)

    count = filing["claim_count_in_scope"]
    if filing["in_scope_premium_total"] == ZERO:
        filing["experience_loss_ratio"] = None
        filing["indicated_change_pct"] = None
    else:
        loss_ratio = r4(
            filing["actuarial_incurred_total"] / filing["in_scope_premium_total"]
        )
        filing["experience_loss_ratio"] = loss_ratio
        if filing["indication_method"] == "LOSS_RATIO_METHOD":
            filing["indicated_change_pct"] = r2(
                (loss_ratio / C.PERMISSIBLE_LOSS_RATIO - ONE) * HUNDRED
            )
        else:
            if count == 0:
                filing["indicated_change_pct"] = None
            else:
                pure_premium = r2(filing["actuarial_incurred_total"] / Decimal(count))
                target_premium = r2(filing["in_scope_premium_total"] / Decimal(count))
                denominator = target_premium * C.PERMISSIBLE_LOSS_RATIO
                if denominator == ZERO:
                    filing["indicated_change_pct"] = None
                else:
                    filing["indicated_change_pct"] = r2(
                        (pure_premium / denominator - ONE) * HUNDRED
                    )

    if count >= C.CREDIBILITY_FULL_CLAIMS:
        weight = C.CREDIBILITY_FULL
    elif count >= C.CREDIBILITY_PARTIAL_CLAIMS:
        weight = C.CREDIBILITY_PARTIAL
    else:
        weight = C.CREDIBILITY_LOW
    filing["credibility_weight"] = weight

    indicated = filing["indicated_change_pct"]
    if indicated is None:
        filing["credibility_weighted_indication_pct"] = None
    else:
        filing["credibility_weighted_indication_pct"] = r2(
            weight * indicated + (ONE - weight) * C.TREND_COMPLEMENT_PCT
        )
    return filing


# --- PRD 3.9: severity trend analysis --------------------------------------
def severity_trend(specialty_class_id, venue_code, from_report_date, to_report_date):
    specialty = db.specialty_classes[specialty_class_id]
    severity = []
    verdicts = []
    for insured in insureds_in_class(specialty_class_id):
        for claim in rating.claims_of(insured["id"]):
            if claim["claim_status"] not in ("RESOLVED", "CLOSED"):
                continue
            if venue_code is not None and claim["venue_code"] != venue_code:
                continue
            report = d(claim["report_date"])
            if from_report_date is not None and report < d(from_report_date):
                continue
            if to_report_date is not None and report > d(to_report_date):
                continue
            if claim["disposition"] in ("SETTLED", "PLAINTIFF_VERDICT"):
                severity.append(claim)
            if claim["disposition"] in ("DEFENSE_VERDICT", "PLAINTIFF_VERDICT"):
                verdicts.append(claim)
    severity = sorted_records(severity)

    paid_total = ZERO
    for claim in severity:
        paid_total += claim["paid_indemnity"]
    paid_total = r2(paid_total)

    count = len(severity)
    if count == 0:
        average = None
        trend_index = None
        top_category = None
    else:
        average = r2(paid_total / Decimal(count))
        trend_index = r4(average / specialty["benchmark_severity"])
        tally = {}
        for claim in severity:
            tally.setdefault(claim["allegation_category"], []).append(claim)
        best = None
        for category, members in tally.items():
            key = (-len(members), members[0]["created_at"], members[0]["_seq"])
            if best is None or key < best[0]:
                best = (key, category)
        top_category = best[1]

    defense_count = sum(1 for c in verdicts if c["disposition"] == "DEFENSE_VERDICT")
    plaintiff_count = sum(1 for c in verdicts if c["disposition"] == "PLAINTIFF_VERDICT")
    tried = defense_count + plaintiff_count
    win_rate = (
        r4(Decimal(defense_count) / Decimal(tried)) if tried > 0 else None
    )

    return {
        "specialty_class_id": specialty_class_id,
        "venue_code": venue_code,
        "closed_severity_claim_count": count,
        "paid_indemnity_total": paid_total,
        "paid_severity_avg": average,
        "benchmark_severity": specialty["benchmark_severity"],
        "trend_index": trend_index,
        "defense_verdict_count": defense_count,
        "plaintiff_verdict_count": plaintiff_count,
        "defense_win_rate": win_rate,
        "top_allegation_category": top_category,
    }
