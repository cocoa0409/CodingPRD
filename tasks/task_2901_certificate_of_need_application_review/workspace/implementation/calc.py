"""The six calculation rules of the programme (PRD §2.6, §3.2, §3.3, §3.7, §3.8)."""

from decimal import Decimal

import clock

# --- letter-of-intent review-threshold determination (PRD §3.3) ---------------
CAPITAL_COST_REVIEW_THRESHOLD_CENTS = 500000000
BED_DELTA_REVIEW_THRESHOLD = 10
LOOKBACK_MONTHS = 24
ALWAYS_REVIEWABLE_SERVICE_TYPES = ("OPEN_HEART_SURGERY", "MRI_UNIT", "NURSING_HOME_BEDS")

# --- comparative score (PRD §3.7) --------------------------------------------
CRITERIA = (
    ("need_conformity_score", Decimal("0.30")),
    ("financial_feasibility_score", Decimal("0.25")),
    ("cost_containment_score", Decimal("0.20")),
    ("access_underserved_score", Decimal("0.15")),
    ("quality_record_score", Decimal("0.10")),
)
MIN_SHEETS_FOR_DECISION = 2

# --- certificate money rules (PRD §3.8) --------------------------------------
OVERRUN_TOLERANCE_MULTIPLIER = Decimal("1.05")
MAX_SINGLE_EXTENSION_DAYS = 365
MAX_CUMULATIVE_EXTENSION_DAYS = 540
DAYS_PER_YEAR = 365
APPEAL_WINDOW_DAYS = 30


def review_threshold_determination(service_type, capital_cost_cents, bed_delta,
                                   filed_at, priors):
    """Both variants are always computed; the prior count alone selects the governor."""
    always = service_type in ALWAYS_REVIEWABLE_SERVICE_TYPES
    project_basis_reviewable = (
        capital_cost_cents >= CAPITAL_COST_REVIEW_THRESHOLD_CENTS
        or bed_delta >= BED_DELTA_REVIEW_THRESHOLD
        or always
    )
    aggregate_capital = capital_cost_cents + sum(p["capital_cost_cents"] for p in priors)
    aggregate_beds = bed_delta + sum(p["bed_delta"] for p in priors)
    aggregated_basis_reviewable = (
        aggregate_capital >= CAPITAL_COST_REVIEW_THRESHOLD_CENTS
        or aggregate_beds >= BED_DELTA_REVIEW_THRESHOLD
        or always
    )
    prior_count = len(priors)
    governing = "AGGREGATED_24_MONTH" if prior_count >= 1 else "PROJECT_BASED"
    governing_flag = (aggregated_basis_reviewable if governing == "AGGREGATED_24_MONTH"
                      else project_basis_reviewable)
    return {
        "project_basis_reviewable": project_basis_reviewable,
        "aggregated_basis_reviewable": aggregated_basis_reviewable,
        "aggregate_capital_cost_cents": aggregate_capital,
        "aggregate_bed_delta": aggregate_beds,
        "prior_window_loi_count": prior_count,
        "governing_review_basis": governing,
        "review_determination": "REVIEWABLE" if governing_flag else "NON_REVIEWABLE",
    }


def need_methodology(area, formula):
    """Five steps in a strictly pinned order; the tier is chosen exactly once."""
    projected_patient_days = clock.round_half_up(
        (clock.dec(area["population_projection"]) / Decimal(1000))
        * clock.dec(formula["use_rate_per_1000"])
        * clock.dec(formula["average_length_of_stay_days"]),
        4,
    )
    base_rate = clock.dec(formula["base_target_occupancy_rate"])
    provisional_required_beds = clock.round_half_up(
        projected_patient_days / (Decimal(DAYS_PER_YEAR) * base_rate), 4)
    if provisional_required_beds >= clock.dec(formula["high_volume_bed_threshold"]):
        selected = formula["high_volume_target_occupancy_rate"]
    else:
        selected = formula["base_target_occupancy_rate"]
    required_beds_final = clock.ceil_int(
        projected_patient_days / (Decimal(DAYS_PER_YEAR) * clock.dec(selected)))
    inventory = int(area["existing_licensed_beds"]) + int(area["approved_unimplemented_beds"])
    unmet = max(0, required_beds_final - inventory)
    return {
        "projected_patient_days": clock.num(projected_patient_days),
        "provisional_required_beds": clock.num(provisional_required_beds),
        "selected_target_occupancy_rate": selected,
        "required_beds_final": required_beds_final,
        "inventory_beds_at_open": inventory,
        "unmet_bed_need_at_open": unmet,
        "unallocated_bed_need": unmet,
    }


def comparative_score(sheets):
    """Per-criterion means rounded to whole points first, then weighted, then rounded."""
    count = len(sheets)
    if count == 0:
        return None, 0
    weighted = Decimal(0)
    for field, weight in CRITERIA:
        total = sum(int(sheet[field]) for sheet in sheets)
        mean = clock.dec(total) / clock.dec(count)
        points = clock.round_half_up(mean, 0)
        weighted += points * weight
    return clock.num(clock.round_half_up(weighted, 2)), count


def rank_candidates(candidates):
    """comparative_score DESC, requested_bed_count ASC, created_at ASC."""
    def key(app):
        score = app.get("comparative_score")
        score_key = clock.dec(score) if score is not None else Decimal(-1)
        return (-score_key, app["requested_bed_count"], app["created_at"], app["_seq"])
    return sorted(candidates, key=key)


def allocation_waterfall(candidates, pool):
    """Returns [(application, outcome, beds)] plus the remaining pool."""
    remaining = pool
    results = []
    for app in rank_candidates(candidates):
        if remaining >= app["requested_bed_count"]:
            beds = app["requested_bed_count"]
            results.append((app, "APPROVED", beds))
            remaining -= beds
        elif remaining > 0 and app.get("partial_award_acceptable"):
            beds = remaining
            results.append((app, "APPROVED_WITH_CONDITIONS", beds))
            remaining = 0
        else:
            results.append((app, "DENIED", 0))
    return results, remaining


def expenditure_ceiling(limit_cents):
    return int(clock.round_half_up(
        clock.dec(limit_cents) * OVERRUN_TOLERANCE_MULTIPLIER, 0))


def cumulative_expenditure(reports):
    cash = sum(int(r["disbursed_cents"]) for r in reports)
    accrual = sum(int(r["disbursed_cents"]) + int(r["obligated_cents"]) for r in reports)
    return cash, accrual


def latest_completion(reports):
    if not reports:
        return None
    chosen = max(reports, key=lambda r: (r["period_end_date"], r["created_at"], r["_seq"]))
    return chosen["physical_completion_pct"]


def expenditure_status(governing, limit_cents, ceiling_cents):
    if governing <= limit_cents:
        return "WITHIN_LIMIT"
    if governing <= ceiling_cents:
        return "OVER_LIMIT_PENDING_AMENDMENT"
    return "LIMIT_BREACHED"


def extension_grant(requested_days, granted_total):
    remaining_cap = MAX_CUMULATIVE_EXTENSION_DAYS - granted_total
    return min(requested_days, MAX_SINGLE_EXTENSION_DAYS, remaining_cap), remaining_cap
