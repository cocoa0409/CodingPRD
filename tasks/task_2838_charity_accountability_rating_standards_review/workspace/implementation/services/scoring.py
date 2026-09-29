"""Cycle level scoring: dimension rows, both composite variants, recomputes."""

from db import (
    DIMENSIONS,
    collection,
    d,
    lookup,
    new_row,
    q2,
    q4,
    rows,
    store,
    touch,
)
from services import calc


# ---------------------------------------------------------------- lookups


def profile_for_cycle(cycle):
    for profile in rows("GovernanceProfile"):
        if profile["rating_cycle_id"] == cycle["id"]:
            return profile
    return None


def standard_rows(profile):
    out = [
        s
        for s in rows("StandardEvaluation")
        if s["governance_profile_id"] == profile["id"]
    ]
    out.sort(key=lambda s: (s["standard_code"], s["_seq"]))
    return out


def dimension_rows(cycle):
    found = {}
    for row in rows("DimensionScore"):
        if row["rating_cycle_id"] == cycle["id"]:
            found[row["dimension"]] = row
    return [found[dim] for dim in DIMENSIONS if dim in found]


def dimension_row(cycle, dimension):
    for row in rows("DimensionScore"):
        if row["rating_cycle_id"] == cycle["id"] and row["dimension"] == dimension:
            return row
    return None


def methodology_for(cycle):
    return lookup("MethodologyVersion", cycle["methodology_version_id"])


def accountability_penalty_total(cycle):
    total = 0
    for complaint in rows("Complaint"):
        if (
            complaint["status"] == "SUBSTANTIATED"
            and complaint.get("penalized_rating_cycle_id") == cycle["id"]
        ):
            total += int(complaint.get("penalty_points_applied") or 0)
    return total


def refresh_profile_counts(profile):
    tally = {"MET": 0, "NOT_MET": 0, "WAIVED": 0, "NOT_APPLICABLE": 0}
    for row in standard_rows(profile):
        if row["result"] in tally:
            tally[row["result"]] += 1
    profile["standards_met_count"] = tally["MET"]
    profile["standards_not_met_count"] = tally["NOT_MET"]
    profile["standards_waived_count"] = tally["WAIVED"]
    profile["standards_not_applicable_count"] = tally["NOT_APPLICABLE"]


# ---------------------------------------------------------------- composites


def finalize_scores(cycle, write_provisional=True, write_final=True):
    """Recompute both variants; write whichever family the caller allows.

    standards_penalty_points always mirrors the final variant's penalty, even on
    a stale-only recompute, exactly as PRD 3.8 hop three requires.
    """
    methodology = methodology_for(cycle)
    if methodology is None:
        return None, None
    weights = calc.declared_weights(methodology)
    floor = d(methodology["dimension_floor_score"])
    current = dimension_rows(cycle)
    failed = int(cycle["failed_standard_count"] or 0)
    completeness = cycle["data_completeness_pct"]

    provisional = calc.composite(
        weights, floor, current, failed, completeness, "provisional"
    )
    final = calc.composite(weights, floor, current, failed, completeness, "final")

    if write_provisional:
        cycle["weighted_sum_provisional"] = provisional["weighted_sum"]
        cycle["provisional_composite_score"] = provisional["composite"]
        cycle["provisional_grade"] = provisional["grade"]
    if write_final:
        cycle["weighted_sum_final"] = final["weighted_sum"]
        cycle["final_composite_score"] = final["composite"]
        cycle["grade"] = final["grade"]
    cycle["standards_penalty_points"] = final["penalty"]
    return provisional, final


def refresh_row_weights(cycle):
    """weight_applied and weighted_contribution always mirror the FINAL variant."""
    methodology = methodology_for(cycle)
    if methodology is None:
        return
    weights = calc.declared_weights(methodology)
    floor = d(methodology["dimension_floor_score"])
    current = dimension_rows(cycle)
    final = calc.composite(
        weights,
        floor,
        current,
        int(cycle["failed_standard_count"] or 0),
        cycle["data_completeness_pct"],
        "final",
    )
    for row in current:
        applied = final["weights"].get(row["dimension"], q4(0))
        row["weight_applied"] = applied
        row["weighted_contribution"] = q2(d(row["normalized_score"]) * applied)


# ---------------------------------------------------------------- full score


def score_cycle(cycle):
    """POST /rating-cycles/{id}/score - the whole pipeline, in pinned order."""
    organization = lookup("Organization", cycle["organization_id"])
    methodology = methodology_for(cycle)
    profile = profile_for_cycle(cycle)
    filing = calc.winning_filing(cycle["organization_id"], cycle["fiscal_year"])

    ratio = calc.program_expense_ratio(filing, organization["org_type"])
    efficiency = calc.fundraising_efficiency(
        cycle["organization_id"], cycle["fiscal_year"]
    )
    reserve = calc.months_of_reserve(filing)
    cycle["program_expense_ratio"] = ratio
    cycle["fundraising_efficiency"] = efficiency
    cycle["months_of_reserve"] = reserve

    cycle["failed_standard_count"] = int(profile["standards_not_met_count"] or 0)
    cycle["accountability_penalty_points"] = accountability_penalty_total(cycle)

    completeness = calc.dimension_completeness(cycle, profile)
    weights = calc.declared_weights(methodology)
    cycle["data_completeness_pct"] = calc.cycle_completeness(completeness, weights)

    raw_points = {
        "FINANCIAL_HEALTH": calc.financial_health_points(ratio, efficiency, reserve),
        "ACCOUNTABILITY": max(
            0,
            calc.accountability_base_points(profile)
            - int(cycle["accountability_penalty_points"] or 0),
        ),
        "TRANSPARENCY": calc.transparency_points(cycle, profile),
        "IMPACT": calc.impact_points(profile),
    }
    max_points = {
        "FINANCIAL_HEALTH": 40,
        "ACCOUNTABILITY": calc.accountability_max_points(profile),
        "TRANSPARENCY": 20,
        "IMPACT": 12,
    }

    for dimension in DIMENSIONS:
        row = dimension_row(cycle, dimension)
        payload = {
            "raw_points": raw_points[dimension],
            "max_points": max_points[dimension],
            "normalized_score": calc.normalized(
                raw_points[dimension], max_points[dimension]
            ),
            "data_completeness_pct": completeness[dimension],
            "penalty_points": (
                int(cycle["accountability_penalty_points"] or 0)
                if dimension == "ACCOUNTABILITY"
                else 0
            ),
            "status": "COMPUTED",
            "override_reason": None,
            "overridden_by_user_id": None,
        }
        if row is None:
            new_row(
                "DimensionScore",
                dict(
                    rating_cycle_id=cycle["id"],
                    dimension=dimension,
                    weight_applied=None,
                    weighted_contribution=None,
                    **payload
                ),
            )
        else:
            row.update(payload)
            touch(row)

    refresh_row_weights(cycle)
    finalize_scores(cycle, True, True)


def recompute_accountability_row(cycle):
    """Used by waive / revoke-waiver / complaint substantiation and reversal."""
    row = dimension_row(cycle, "ACCOUNTABILITY")
    if row is None or row["status"] not in ("COMPUTED", "OVERRIDDEN"):
        return False
    profile = profile_for_cycle(cycle)
    base = calc.accountability_base_points(profile)
    row["raw_points"] = max(0, base - int(cycle["accountability_penalty_points"] or 0))
    row["normalized_score"] = calc.normalized(row["raw_points"], row["max_points"])
    refresh_row_weights(cycle)
    return True


def mark_rows_stale(cycle):
    """COMPUTED or OVERRIDDEN dimension rows go STALE, each bumping its own version."""
    changed = False
    for row in dimension_rows(cycle):
        if row["status"] in ("COMPUTED", "OVERRIDDEN"):
            row["status"] = "STALE"
            touch(row)
            changed = True
    return changed


def has_stale_row(cycle):
    return any(row["status"] == "STALE" for row in dimension_rows(cycle))
