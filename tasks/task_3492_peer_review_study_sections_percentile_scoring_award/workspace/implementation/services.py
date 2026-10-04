"""Domain logic: derived counters, calculations (§1.3), cascades."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    AWARD_PERIOD_DAYS,
    CAREER_STAGE_ESI,
    CRITERION_MEAN_DECIMALS,
    ESI_PAYLINE_BONUS,
    JIT_ITEM_BUDGET_JUSTIFICATION,
    JIT_ITEM_IACUC,
    JIT_ITEM_IRB,
    JIT_ITEM_OTHER_SUPPORT,
    JIT_RESPONSE_WINDOW_DAYS,
    LIVE_ASSIGNMENT_STATUSES,
    MIN_CRITIQUES_TO_SCORE,
    MIN_EFFECTIVE_PERCENTILE,
    MIN_LIVE_ASSIGNMENTS,
    PERCENTILE_DECIMALS,
    PRIMARY_WEIGHT,
    SECONDARY_WEIGHT,
    TERM_STANDARD,
)
from db import STORE, clock_now, new_entity, touch


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def rhu(value, places=0):
    """Round half up to `places` decimal places; returns Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to a whole integer; returns int."""
    return int(rhu(Decimal(value), 0))


def dec(value):
    """Exact Decimal view of a JSON number (avoids binary float noise)."""
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Derived counters (single source of truth: recomputed from base data)
# ---------------------------------------------------------------------------
def live_assignment_count(application_id):
    return sum(
        1
        for a in STORE["assignments"].values()
        if a["application_id"] == application_id and a["status"] in LIVE_ASSIGNMENT_STATUSES
    )


def active_assignment_count(reviewer_id):
    return sum(
        1
        for a in STORE["assignments"].values()
        if a["reviewer_id"] == reviewer_id and a["status"] in ("ASSIGNED", "ACCEPTED")
    )


def section_assigned_count(section_id):
    return sum(
        1
        for a in STORE["applications"].values()
        if a["study_section_id"] == section_id and a["status"] in ("REFERRED", "UNDER_REVIEW")
    )


def submitted_critiques(application_id):
    return [
        a
        for a in STORE["assignments"].values()
        if a["application_id"] == application_id and a["status"] == "CRITIQUE_SUBMITTED"
    ]


def get(collection, entity_id):
    return STORE[collection].get(entity_id)


# ---------------------------------------------------------------------------
# impact_score + percentile_scoring (calculations.impact_score / .percentile_scoring)
# ---------------------------------------------------------------------------
def _compute_impact_for(app):
    """Score one UNDER_REVIEW application at release time."""
    critiques = submitted_critiques(app["id"])
    if len(critiques) < MIN_CRITIQUES_TO_SCORE:
        app["status"] = "UNSCORED"
        touch(app)
        return
    weight_sum = Decimal(0)
    weighted_total = Decimal(0)
    approach = []
    significance = []
    innovation = []
    for c in sorted(critiques, key=lambda c: c["_seq"]):
        w = PRIMARY_WEIGHT if c["role"] == "PRIMARY" else SECONDARY_WEIGHT
        weight_sum += w
        weighted_total += dec(c["overall_impact_score"]) * w
        approach.append(c["approach_score"])
        significance.append(c["significance_score"])
        innovation.append(c["innovation_score"])
    weighted_mean = weighted_total / weight_sum
    app["impact_score"] = int(rhu(weighted_mean * 10, 0))
    n = len(critiques)
    app["approach_mean"] = float(
        rhu(dec(sum(approach)) / n, CRITERION_MEAN_DECIMALS)
    )
    app["significance_mean"] = float(
        rhu(dec(sum(significance)) / n, CRITERION_MEAN_DECIMALS)
    )
    app["innovation_mean"] = float(
        rhu(dec(sum(innovation)) / n, CRITERION_MEAN_DECIMALS)
    )
    app["status"] = "SCORED"
    touch(app)


def _percentile(rank, pool_size):
    return float(
        rhu(dec(100) * (dec(rank) - dec("0.5")) / pool_size, PERCENTILE_DECIMALS)
    )


def _recompute_raw_percentiles(section_id):
    pool = [
        a
        for a in STORE["applications"].values()
        if a["study_section_id"] == section_id and a["status"] == "SCORED"
    ]
    pool.sort(
        key=lambda a: (
            a["impact_score"],
            a["approach_mean"],
            a["significance_mean"],
            a["innovation_mean"],
            a["created_at"],
            a["_seq"],
        )
    )
    n = len(pool)
    for idx, app in enumerate(pool, start=1):
        app["percentile_raw"] = _percentile(idx, n)


def _recompute_normalized_pools():
    """Re-rank every activity-code pool across all sections (derived-field
    reconciliation: a later release rewrites earlier sections' values)."""
    scored = [a for a in STORE["applications"].values() if a["status"] == "SCORED"]
    by_code = {}
    for app in scored:
        foa = get("funding_opportunities", app["foa_id"])
        code = foa["activity_code"] if foa else None
        by_code.setdefault(code, []).append(app)
    for pool in by_code.values():
        section_means = {}
        by_section = {}
        for app in pool:
            by_section.setdefault(app["study_section_id"], []).append(app)
        for sid, members in by_section.items():
            mean = sum(m["impact_score"] for m in members) / len(members)
            section_means[sid] = rhu(dec(mean), PERCENTILE_DECIMALS)
        pool_mean = rhu(
            dec(sum(a["impact_score"] for a in pool)) / len(pool),
            PERCENTILE_DECIMALS,
        )
        for app in pool:
            adjusted = (
                dec(app["impact_score"])
                - section_means[app["study_section_id"]]
                + pool_mean
            )
            app["_adjusted_score"] = adjusted
        pool.sort(
            key=lambda a: (a["_adjusted_score"], a["impact_score"], a["created_at"], a["_seq"])
        )
        m = len(pool)
        for idx, app in enumerate(pool, start=1):
            app["percentile_normalized"] = _percentile(idx, m)
            app.pop("_adjusted_score", None)


def release_section_scores(section):
    """MEETING_HELD -> SCORES_RELEASED with full scoring fan-out."""
    for app in STORE["applications"].values():
        if app["study_section_id"] == section["id"] and app["status"] == "UNDER_REVIEW":
            _compute_impact_for(app)
    _recompute_raw_percentiles(section["id"])
    _recompute_normalized_pools()
    section["status"] = "SCORES_RELEASED"
    touch(section)


# ---------------------------------------------------------------------------
# projected_cost (payline walk + select pay share this pre-JIT estimate)
# ---------------------------------------------------------------------------
def projected_cost(app, foa, institute):
    rate = dec(institute["indirect_cost_rate"])
    total = 0
    for y in range(app["requested_years"]):
        capped = min(app["direct_cents_per_year"][y], foa["max_direct_cents_per_year"])
        indirect = int(rhu(dec(capped) * rate, 0))
        total += capped + indirect
    return total


# ---------------------------------------------------------------------------
# JIT
# ---------------------------------------------------------------------------
def create_jit_for(app):
    jit = new_entity()
    required = [JIT_ITEM_OTHER_SUPPORT, JIT_ITEM_BUDGET_JUSTIFICATION]
    if app["human_subjects_involved"]:
        required.append(JIT_ITEM_IRB)
    if app["vertebrate_animals_involved"]:
        required.append(JIT_ITEM_IACUC)
    jit.update(
        {
            "application_id": app["id"],
            "required_items": required,
            "submitted_items": [],
            "due_date": clock_now() + timedelta(days=JIT_RESPONSE_WINDOW_DAYS),
            "budget_cut_pct": 0,
            "status": "ISSUED",
        }
    )
    STORE["jit_requests"][jit["id"]] = jit
    return jit


def fund_application(app):
    """COUNCIL_REVIEWED -> JIT_PENDING with an auto-created ISSUED JitRequest."""
    app["status"] = "JIT_PENDING"
    create_jit_for(app)
    touch(app)


def expire_jit(jit):
    """Lazy expiry: request -> EXPIRED, application -> NOT_FUNDED."""
    jit["status"] = "EXPIRED"
    touch(jit)
    app = get("applications", jit["application_id"])
    if app is not None and app["status"] == "JIT_PENDING":
        app["status"] = "NOT_FUNDED"
        touch(app)


def jit_is_past_due(jit):
    return clock_now() > jit["due_date"]


# ---------------------------------------------------------------------------
# payline_determination (calculations.payline_determination)
# ---------------------------------------------------------------------------
def run_payline_walk(institute, base_payline):
    committable = (
        institute["appropriation_cents"]
        - institute["committed_cents"]
        - institute["disbursed_cents"]
        - institute["reserve_cents"]
    )
    candidates = [
        a
        for a in STORE["applications"].values()
        if a["institute_id"] == institute["id"] and a["status"] == "COUNCIL_REVIEWED"
    ]

    def effective_pctl(app):
        applicant = get("applicants", app["applicant_id"])
        bonus = (
            dec(ESI_PAYLINE_BONUS)
            if applicant and applicant["career_stage"] == CAREER_STAGE_ESI
            else dec(0)
        )
        effective = dec(app["percentile_normalized"]) - bonus
        return max(effective, dec(MIN_EFFECTIVE_PERCENTILE))

    eligible = []
    for app in candidates:
        eff = effective_pctl(app)
        if eff <= dec(base_payline):
            eligible.append((app, eff))
    eligible.sort(
        key=lambda pair: (
            pair[1],
            dec(pair[0]["percentile_raw"]),
            pair[0]["impact_score"],
            pair[0]["created_at"],
            pair[0]["_seq"],
        )
    )
    cumulative = 0
    funded = []
    for app, _eff in eligible:
        foa = get("funding_opportunities", app["foa_id"])
        cost = projected_cost(app, foa, institute)
        if cumulative + cost <= committable:
            cumulative += cost
            funded.append(app)
        else:
            break  # stop at the first candidate that would exceed; no skipping
    return funded


# ---------------------------------------------------------------------------
# award_budget_build (calculations.award_budget_build)
# ---------------------------------------------------------------------------
def build_award_budget(app, foa, institute, budget_cut_pct):
    cut = dec(budget_cut_pct)
    rate = dec(institute["indirect_cost_rate"])
    period_totals = []
    for y in range(app["requested_years"]):
        capped = min(app["direct_cents_per_year"][y], foa["max_direct_cents_per_year"])
        direct_y = int(rhu(dec(capped) * (dec(1) - cut), 0))
        indirect_y = int(rhu(dec(direct_y) * rate, 0))
        period_totals.append(direct_y + indirect_y)
    return period_totals, sum(period_totals)


def accepted_jit_for(application_id):
    accepted = [
        j
        for j in STORE["jit_requests"].values()
        if j["application_id"] == application_id and j["status"] == "ACCEPTED"
    ]
    if not accepted:
        return None
    accepted.sort(key=lambda j: j["_seq"])
    return accepted[-1]


# ---------------------------------------------------------------------------
# Post-award helpers
# ---------------------------------------------------------------------------
def period_end(award, period_year):
    """End instant of 1-based budget period p (365-day periods)."""
    return award["start_date"] + timedelta(days=AWARD_PERIOD_DAYS * period_year)


def apply_carryover(award, amount, from_period):
    from_idx = from_period - 1
    current_idx = award["current_period"] - 1
    while len(award["period_total_cents"]) <= current_idx:
        award["period_total_cents"].append(0)
    while len(award["carried_out_per_period_cents"]) <= from_idx:
        award["carried_out_per_period_cents"].append(0)
    award["period_total_cents"][from_idx] -= amount
    award["carried_out_per_period_cents"][from_idx] += amount
    award["period_total_cents"][current_idx] += amount
    touch(award)


def unobligated(award, from_period):
    from_idx = from_period - 1
    total = award["period_total_cents"][from_idx]
    disbursed = (
        award["disbursed_per_period_cents"][from_idx]
        if from_idx < len(award["disbursed_per_period_cents"])
        else 0
    )
    return total - disbursed
