"""Every calculation the PRD pins (sections 3.3 - 3.9).

All arithmetic runs through decimal.Decimal with ROUND_HALF_UP.  The order in
which values are rounded is part of the contract, so each helper rounds exactly
where the PRD says it rounds and nowhere else.
"""

from decimal import Decimal

from db import (
    BOARD_INDEPENDENCE_MIN,
    BOARD_MEETINGS_MIN,
    BOARD_SIZE_MIN,
    COI_REVIEW_MAX_AGE_DAYS,
    DIMENSIONS,
    OUTCOME_MEASURE_CAP,
    STANDARD_CODES,
    STANDARD_MET_POINTS,
    STANDARD_WAIVED_POINTS,
    d,
    fmt_dt,
    q2,
    q4,
    rows,
    store,
)

MONTHS_PER_YEAR = 12
FINANCIAL_HISTORY_YEARS = 3

DIMENSION_MAX = {
    "FINANCIAL_HEALTH": 40,
    "ACCOUNTABILITY": 24,
    "TRANSPARENCY": 20,
    "IMPACT": 12,
}

DECLARED_YEAR_WEIGHTS = [Decimal("0.50"), Decimal("0.30"), Decimal("0.20")]

BAND_PENALTY_RATE = {
    "A": Decimal("2.0"),
    "B": Decimal("1.5"),
    "C": Decimal("1.0"),
    "D": Decimal("0.5"),
}


# ---------------------------------------------------------------- filings


def winning_filing(organization_id, fiscal_year):
    """VALIDATED only, ranked by source_precedence then created_at.  The id is
    never consulted; equal timestamps fall back to insertion order."""
    candidates = [
        f
        for f in rows("FilingRecord")
        if f["organization_id"] == organization_id
        and f["fiscal_year"] == fiscal_year
        and f["status"] == "VALIDATED"
    ]
    candidates.sort(key=lambda f: (f["source_precedence"], f["created_at"], f["_seq"]))
    return candidates[0] if candidates else None


def has_validated_filing(organization_id, fiscal_year=None, source_kind=None):
    for f in rows("FilingRecord"):
        if f["organization_id"] != organization_id or f["status"] != "VALIDATED":
            continue
        if fiscal_year is not None and f["fiscal_year"] != fiscal_year:
            continue
        if source_kind is not None and f["source_kind"] != source_kind:
            continue
        return True
    return False


# ---------------------------------------------------------------- financials


def program_expense_ratio(filing, org_type):
    program = d(filing["program_expense_cents"])
    total = d(filing["total_expense_cents"])
    grants = d(filing["grants_paid_cents"] or 0)
    member = d(filing["membership_services_cents"] or 0)
    joint = d(filing["joint_cost_allocated_cents"] or 0)

    if org_type in ("PUBLIC_CHARITY", "DONOR_ADVISED_SPONSOR"):
        adjusted_program = program - joint
    elif org_type == "PRIVATE_FOUNDATION":
        adjusted_program = program + grants
    elif org_type == "MEMBERSHIP_ASSOCIATION":
        adjusted_program = program + member
    else:  # RELIGIOUS_CONGREGATION
        adjusted_program = program

    if org_type == "PRIVATE_FOUNDATION":
        adjusted_total = total + grants
    elif org_type == "DONOR_ADVISED_SPONSOR":
        adjusted_total = total - grants
    else:
        adjusted_total = total

    if adjusted_program < 0:
        adjusted_program = Decimal(0)
    if adjusted_total <= 0:
        return q4(0)
    return q4(adjusted_program / adjusted_total)


def fundraising_efficiency(organization_id, fiscal_year):
    available = []
    for index in range(FINANCIAL_HISTORY_YEARS):
        year = fiscal_year - index
        filing = winning_filing(organization_id, year)
        if filing is None:
            continue
        contributions = d(filing["contributions_cents"])
        if contributions == 0:
            ratio = q4(1)
        else:
            ratio = q4(d(filing["fundraising_expense_cents"]) / contributions)
        available.append((ratio, DECLARED_YEAR_WEIGHTS[index]))
    if not available:
        return q4(1)
    pool = sum((w for _, w in available), Decimal(0))
    total = Decimal(0)
    for ratio, weight in available:
        renormalised = q4(d(weight) / pool)
        total += q4(ratio * renormalised)
    return q4(total)


def years_available(organization_id, fiscal_year):
    return sum(
        1
        for index in range(FINANCIAL_HISTORY_YEARS)
        if winning_filing(organization_id, fiscal_year - index) is not None
    )


def months_of_reserve(filing):
    total = d(filing["total_expense_cents"])
    if total <= 0:
        return q2(0)
    return q2(d(filing["net_assets_cents"]) * MONTHS_PER_YEAR / total)


# ---------------------------------------------------------------- standards


def independence_ratio(profile):
    board = profile["board_member_count"]
    if board == 0:
        return q4(0)
    return q4(d(profile["independent_board_member_count"]) / d(board))


def _bool_text(value):
    return "true" if value else "false"


def standards_evaluation(profile, org_type):
    """Return the eight (code, result, observed, required) tuples."""
    now = store.now()
    ratio = independence_ratio(profile)
    religious = org_type == "RELIGIOUS_CONGREGATION"
    reviewed = profile.get("coi_policy_reviewed_at")

    coi_current = False
    if reviewed is not None:
        from datetime import timedelta

        coi_current = reviewed >= now - timedelta(days=COI_REVIEW_MAX_AGE_DAYS)

    table = {
        "BOARD_SIZE_MIN": (
            False,
            profile["board_member_count"] >= BOARD_SIZE_MIN,
            str(profile["board_member_count"]),
            "5",
        ),
        "BOARD_INDEPENDENCE": (
            False,
            ratio >= BOARD_INDEPENDENCE_MIN,
            str(ratio),
            "0.5000",
        ),
        "COI_POLICY": (
            False,
            bool(profile["conflict_of_interest_policy_on_file"]),
            _bool_text(profile["conflict_of_interest_policy_on_file"]),
            "true",
        ),
        "COI_POLICY_CURRENCY": (
            religious,
            coi_current,
            fmt_dt(reviewed) if reviewed is not None else "null",
            "reviewed within 730 days",
        ),
        "BOARD_MEETING_FREQUENCY": (
            False,
            profile["board_meetings_last_year"] >= BOARD_MEETINGS_MIN,
            str(profile["board_meetings_last_year"]),
            "3",
        ),
        "AUDIT_COMMITTEE": (
            religious,
            bool(profile["audit_committee_exists"]),
            _bool_text(profile["audit_committee_exists"]),
            "true",
        ),
        "WHISTLEBLOWER_POLICY": (
            False,
            bool(profile["whistleblower_policy"]),
            _bool_text(profile["whistleblower_policy"]),
            "true",
        ),
        "CEO_COMP_REVIEW": (
            religious,
            bool(profile["ceo_compensation_reviewed"]),
            _bool_text(profile["ceo_compensation_reviewed"]),
            "true",
        ),
    }

    out = []
    for code in STANDARD_CODES:
        not_applicable, met, observed, required = table[code]
        if not_applicable:
            result = "NOT_APPLICABLE"
        elif met:
            result = "MET"
        else:
            result = "NOT_MET"
        out.append((code, result, observed, required))
    return ratio, out


# ---------------------------------------------------------------- dimensions


def accountability_base_points(profile):
    if profile is None:
        return 0
    return min(
        24,
        STANDARD_MET_POINTS * int(profile["standards_met_count"] or 0)
        + STANDARD_WAIVED_POINTS * int(profile["standards_waived_count"] or 0),
    )


def accountability_max_points(profile):
    if profile is None:
        return 0
    return min(
        24,
        STANDARD_MET_POINTS * (8 - int(profile["standards_not_applicable_count"] or 0)),
    )


def financial_health_points(ratio, efficiency, reserve):
    ratio = d(ratio or 0)
    efficiency = d(efficiency if efficiency is not None else 1)
    reserve = d(reserve or 0)

    if ratio >= Decimal("0.85"):
        ratio_points = 20
    elif ratio >= Decimal("0.75"):
        ratio_points = 15
    elif ratio >= Decimal("0.65"):
        ratio_points = 10
    elif ratio >= Decimal("0.50"):
        ratio_points = 5
    else:
        ratio_points = 0

    if efficiency <= Decimal("0.10"):
        efficiency_points = 12
    elif efficiency <= Decimal("0.20"):
        efficiency_points = 9
    elif efficiency <= Decimal("0.35"):
        efficiency_points = 5
    else:
        efficiency_points = 0

    if reserve >= 12:
        reserve_points = 8
    elif reserve >= 6:
        reserve_points = 5
    elif reserve >= 3:
        reserve_points = 2
    else:
        reserve_points = 0

    return ratio_points + efficiency_points + reserve_points


def transparency_points(cycle, profile):
    org_id = cycle["organization_id"]
    if has_validated_filing(org_id, cycle["fiscal_year"], "AUDITED_STATEMENT"):
        source_points = 8
    elif has_validated_filing(org_id, cycle["fiscal_year"], "PUBLIC_FILING"):
        source_points = 4
    else:
        source_points = 0
    total = source_points
    if profile is not None:
        if profile["evaluation_status"] == "EVALUATED":
            total += 6
        if profile["conflict_of_interest_policy_on_file"]:
            total += 3
        if profile["whistleblower_policy"]:
            total += 3
    return total


def impact_points(profile):
    if profile is None:
        return 0
    total = 5 if profile["impact_report_on_file"] else 0
    total += min(OUTCOME_MEASURE_CAP, int(profile["outcome_measures_count"] or 0))
    total += 3 if profile["third_party_evaluation_on_file"] else 0
    return total


def normalized(raw_points, max_points):
    if not max_points:
        return q2(0)
    return q2(d(raw_points) * 100 / d(max_points))


def dimension_completeness(cycle, profile):
    org_id = cycle["organization_id"]
    out = {}
    available = years_available(org_id, cycle["fiscal_year"])
    out["FINANCIAL_HEALTH"] = q2(
        Decimal("100.00") * available / FINANCIAL_HISTORY_YEARS
    )
    evaluated = profile is not None and profile["evaluation_status"] == "EVALUATED"
    out["ACCOUNTABILITY"] = q2(100) if evaluated else q2(0)
    out["TRANSPARENCY"] = (
        q2(100) if (evaluated and has_validated_filing(org_id)) else q2(0)
    )
    if profile is not None and (
        profile["impact_report_on_file"]
        or int(profile["outcome_measures_count"] or 0) > 0
        or profile["third_party_evaluation_on_file"]
    ):
        out["IMPACT"] = q2(100)
    else:
        out["IMPACT"] = q2(0)
    return out


def declared_weights(methodology):
    return {
        "FINANCIAL_HEALTH": q4(methodology["weight_financial_health"]),
        "ACCOUNTABILITY": q4(methodology["weight_accountability"]),
        "TRANSPARENCY": q4(methodology["weight_transparency"]),
        "IMPACT": q4(methodology["weight_impact"]),
    }


def cycle_completeness(completeness_by_dimension, weights):
    total = Decimal(0)
    for dimension in DIMENSIONS:
        total += d(completeness_by_dimension[dimension]) * weights[dimension]
    return q2(total)


# ---------------------------------------------------------------- composite


def band_for(weighted_sum):
    value = d(weighted_sum)
    if value >= 90:
        return "A"
    if value >= 75:
        return "B"
    if value >= 60:
        return "C"
    return "D"


def composite(
    weights_declared,
    floor_score,
    dimension_rows,
    failed_standard_count,
    completeness_pct,
    variant,
):
    """The six pinned steps of composite_score_with_penalty."""
    by_dimension = {row["dimension"]: row for row in dimension_rows}

    if variant == "final":
        included = [
            dim
            for dim in DIMENSIONS
            if dim in by_dimension
            and d(by_dimension[dim]["data_completeness_pct"]) != 0
        ]
    else:
        included = [dim for dim in DIMENSIONS if dim in by_dimension]

    weights = {dim: q4(0) for dim in DIMENSIONS}
    if variant == "final":
        pool = sum((weights_declared[dim] for dim in included), Decimal(0))
        if pool > 0:
            for dim in included:
                weights[dim] = q4(weights_declared[dim] / pool)
    else:
        for dim in included:
            weights[dim] = q4(weights_declared[dim])

    # step 2 - round each term, sum, round the sum
    weighted_sum = Decimal(0)
    for dim in included:
        weighted_sum += q2(d(by_dimension[dim]["normalized_score"]) * weights[dim])
    weighted_sum = q2(weighted_sum)

    # step 3 - band from the pre-penalty sum
    band = band_for(weighted_sum)

    # step 4 - penalty
    penalty = q2(BAND_PENALTY_RATE[band] * d(failed_standard_count or 0))

    # step 5 - composite from the post-penalty figure, floored at zero
    net = weighted_sum - penalty
    if net < 0:
        net = Decimal(0)
    composite_score = q2(net)

    # step 6 - grade
    floor_ok = True
    if included:
        floor_ok = min(
            d(by_dimension[dim]["normalized_score"]) for dim in included
        ) >= d(floor_score)

    if completeness_pct is not None and d(completeness_pct) < Decimal("60.00"):
        grade = "UNRATED"
    elif composite_score >= 85 and floor_ok:
        grade = "ACCREDITED"
    elif composite_score >= 70 and floor_ok:
        grade = "MEETS_STANDARDS"
    elif composite_score >= 55:
        grade = "NEEDS_IMPROVEMENT"
    else:
        grade = "DOES_NOT_MEET"

    return {
        "included": included,
        "weights": weights,
        "weighted_sum": weighted_sum,
        "band": band,
        "penalty": penalty,
        "composite": composite_score,
        "grade": grade,
        "floor_ok": floor_ok,
    }


# ---------------------------------------------------------------- complaints

KIND_POINTS = {"DONOR": 30, "BENEFICIARY": 25, "EMPLOYEE": 35, "ANONYMOUS": 10}
CATEGORY_POINTS = {
    "MISUSE_OF_FUNDS": 30,
    "GOVERNANCE": 25,
    "SOLICITATION_PRACTICE": 20,
    "TRANSPARENCY": 15,
    "OTHER": 5,
}
DOCUMENT_POINTS = 8
DOCUMENT_CAP = 3
SEVERITY_CAP = {"HIGH": 15, "MEDIUM": 10, "LOW": 5}


def credibility_score(complaint, variant, finding=None):
    base = Decimal(KIND_POINTS.get(complaint["complainant_kind"], 0))
    base += Decimal(CATEGORY_POINTS.get(complaint["category"], 0))
    documents = min(DOCUMENT_CAP, int(complaint.get("corroborating_document_count") or 0))
    base += Decimal(DOCUMENT_POINTS * documents)

    if variant == "investigated":
        prior = 0
        for other in rows("Complaint"):
            if other["id"] == complaint["id"]:
                continue
            if other["organization_id"] != complaint["organization_id"]:
                continue
            if other["status"] == "SUBSTANTIATED":
                prior += 1
        base += Decimal(min(20, 5 * prior))
        if finding == "SUBSTANTIATED":
            base += Decimal(10)
        elif finding == "UNSUBSTANTIATED":
            base -= Decimal(15)

    if base < 0:
        base = Decimal(0)
    if base > 100:
        base = Decimal(100)
    return q2(base)


def severity_tier(score):
    value = d(score)
    if value >= Decimal("80.00"):
        return "HIGH"
    if value >= Decimal("50.00"):
        return "MEDIUM"
    return "LOW"


def penalty_target_cycle(organization_id):
    candidates = [
        c
        for c in rows("RatingCycle")
        if c["organization_id"] == organization_id
        and c["status"] not in ("PUBLISHED", "WITHDRAWN")
    ]
    candidates.sort(key=lambda c: (-c["fiscal_year"], c["created_at"], c["_seq"]))
    return candidates[0] if candidates else None
