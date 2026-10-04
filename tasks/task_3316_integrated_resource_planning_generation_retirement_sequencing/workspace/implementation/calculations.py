"""Calculation engine: load forecasting, capacity accreditation, derating,
capacity margin, screening levelized cost, retirement analysis, sensitivity
scoring, deviation measurement, and the accreditation waterfall.

All formulas and constants come from SCAFFOLD.yaml §1.3 and PRD §3.
All rounding is ROUND_HALF_UP (PRD §2.7).
"""

from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import ERR_INVALID_REQUEST, raise_error
from helpers import D, num0, num2, round_half_up


# ---------------------------------------------------------------------------
# Constants (SCAFFOLD.yaml §1.3)
# ---------------------------------------------------------------------------
INDUSTRIAL_COINCIDENCE = D("0.95")
ELECTRIFICATION_COINCIDENT = D("1.00")
ELECTRIFICATION_NET_PEAK = D("0.60")

ACCREDITATION = {
    "COAL": D("0.90"),
    "GAS_CC": D("0.88"),
    "GAS_CT": D("0.85"),
    "NUCLEAR": D("0.95"),
    "HYDRO": D("0.80"),
    "SOLAR": D("0.40"),
    "WIND": D("0.15"),
    "STORAGE": D("0.75"),
    "DEMAND_RESPONSE": D("0.70"),
}

COAL_DERATE_START_AGE = 40
COAL_DERATE_FLOOR_AGE = 50
COAL_DERATE_FLOOR = D("0.90")
STORAGE_DERATE_CYCLE = 20
STORAGE_DERATE_FLOOR = D("0.75")
DR_STEP_YEAR = 2030
DR_PRE_STEP = D("0.85")

RESERVE_MARGIN_PCT = D("0.15")

DISCOUNT_RATE = D("0.07")
ASSET_LIFE_YEARS = 25

COAL_COMPLIANCE_BASE = D("42000")          # $/MW-year
COAL_COMPLIANCE_STEP = D("8000")           # $/MW-year per year past 2030
GAS_CT_COMPLIANCE = D("6000")              # $/MW-year flat
FIXED_OM_COAL = D("38000")                 # $/MW-year
FIXED_OM_GAS_CT = D("14000")               # $/MW-year
FIXED_OM_DEFAULT = D("9000")               # $/MW-year
ANALYSIS_WINDOW_YEARS = 10

FUEL_SHARE_COST_PLUS = D("0.35")
POLICY_FACTOR = D("0.5")
ROBUST_TOLERANCE_PCT = D("0.10")

DEVIATION_THRESHOLD_PCT = D("0.05")

MIN_RETIREMENT_LEAD_YEARS = 2
REOPEN_LIMIT = 2
COMMENT_WINDOW_DAYS = 30
CYCLE_DEADLINE_MONTH_DAY = "09-01"

RESOURCE_TYPES = {
    "COAL", "GAS_CC", "GAS_CT", "NUCLEAR", "HYDRO",
    "SOLAR", "WIND", "STORAGE", "DEMAND_RESPONSE",
}
FUEL_TYPES = {"COAL", "NATURAL_GAS", "URANIUM", "WATER", "SUN", "WIND", "NONE"}
SCENARIO_TAGS = {"BASE", "HIGH_ELECTRIFICATION", "LOW_GROWTH"}


# ---------------------------------------------------------------------------
# load_forecasting (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def compute_forecast_totals(residential, commercial, industrial, electrification):
    """Return (total_peak_mw, effective_load_mw_coincident) at 2dp half-up."""
    r, c, i, e = D(residential), D(commercial), D(industrial), D(electrification)
    total = r + c + i + e
    effective = r + c + i * INDUSTRIAL_COINCIDENCE + e * ELECTRIFICATION_COINCIDENT
    return num2(total), num2(effective)


def effective_load_for(residential, commercial, industrial, electrification, variant):
    """Effective load under the requested variant (COINCIDENT | NET_PEAK)."""
    r, c, i, e = D(residential), D(commercial), D(industrial), D(electrification)
    factor = ELECTRIFICATION_NET_PEAK if variant == "NET_PEAK" else ELECTRIFICATION_COINCIDENT
    return round_half_up(r + c + i * INDUSTRIAL_COINCIDENCE + e * factor, 2)


# ---------------------------------------------------------------------------
# derating_factor (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def derating_factor(resource_type: str, forecast_year: int, *,
                    in_service_year: int = None, online_year: int = None,
                    is_decided: bool = False, retirement_year: int = None) -> Decimal:
    """Per-unit derating factor for a forecast year.

    Fleet units pass in_service_year; candidate units pass online_year and are
    treated as age/cycle 0 relative to their online year.
    A DECIDED unit's age is evaluated as of min(forecast_year, retirement_year).
    """
    if resource_type == "COAL":
        if in_service_year is not None:
            age_base_year = forecast_year
            if is_decided and retirement_year is not None:
                age_base_year = min(forecast_year, retirement_year)
            age = age_base_year - in_service_year
        else:
            age = 0  # candidates are age 0
        if age <= COAL_DERATE_START_AGE:
            return D("1.00")
        if age >= COAL_DERATE_FLOOR_AGE:
            return COAL_DERATE_FLOOR
        return D("1.00") - D("0.01") * (age - COAL_DERATE_START_AGE)
    if resource_type == "STORAGE":
        cycles = forecast_year - (online_year if online_year is not None else (in_service_year or forecast_year))
        return STORAGE_DERATE_FLOOR if cycles >= STORAGE_DERATE_CYCLE else D("1.00")
    if resource_type == "DEMAND_RESPONSE":
        return D("1.00") if forecast_year >= DR_STEP_YEAR else DR_PRE_STEP
    return D("1.00")


# ---------------------------------------------------------------------------
# capacity_accreditation (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def accredited_supply(portfolio: dict, forecast_year: int,
                      accreditation_mode: str = "DECIDED_EXCLUSIVE") -> Decimal:
    """Sum of accredited MW over active fleet Resources and selected Positions.

    Each per-unit term (mw * base_factor * der) is rounded to 2dp half-up
    before summation (PRD §2.7).
    """
    total = Decimal(0)
    # Fleet resources (all registered units are potentially contributing; the
    # fleet registry is flat and not plan-scoped).
    for r in store.resources.values():
        rtype = r["resource_type"]
        base = ACCREDITATION[rtype]
        status = r["status"]
        if accreditation_mode == "DECIDED_INCLUSIVE" and status == "DECIDED":
            contributed = True
        else:
            contributed = (status == "ACTIVE") or (
                status == "DECIDED"
                and r.get("retirement_year") is not None
                and forecast_year < r["retirement_year"]
            )
        if not contributed:
            continue
        der = derating_factor(
            rtype, forecast_year,
            in_service_year=r["in_service_year"],
            online_year=r["in_service_year"],
            is_decided=(status == "DECIDED"),
            retirement_year=r.get("retirement_year"),
        )
        term = round_half_up(D(r["nameplate_mw"]) * base * der, 2)
        total += term
    # Selected positions of this portfolio.
    for pos in store.positions.values():
        if pos["portfolio_id"] != portfolio["id"] or not pos.get("selected", True):
            continue
        cand = store.candidates.get(pos["candidate_id"])
        if cand is None:
            continue
        if cand["online_year"] > forecast_year:
            continue
        rtype = cand["resource_type"]
        base = ACCREDITATION[rtype]
        der = derating_factor(rtype, forecast_year, online_year=cand["online_year"])
        term = round_half_up(D(pos["committed_mw"]) * base * der, 2)
        total += term
    return round_half_up(total, 2)


# ---------------------------------------------------------------------------
# capacity_margin (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def capacity_margin(accredited: Decimal, load: Decimal) -> Decimal:
    return round_half_up(accredited - load * (1 + RESERVE_MARGIN_PCT), 2)


def find_forecast_load(plan_id: str, scenario_tag: str, forecast_year: int, variant: str):
    """Return the effective load (Decimal, 2dp) for (plan, scenario, year, variant).

    Uses the stored LoadForecast row. When scenario_tag is HIGH_ELECTRIFICATION
    and no such row exists, falls back to the BASE row for that year (the
    scenario override applies the NET_PEAK factor to the same class inputs).
    Returns None when no usable forecast row exists.
    """
    row = None
    for f in store.forecasts.values():
        if f["plan_id"] == plan_id and f["scenario_tag"] == scenario_tag and f["forecast_year"] == forecast_year:
            row = f
            break
    if row is None and scenario_tag != "BASE":
        for f in store.forecasts.values():
            if f["plan_id"] == plan_id and f["scenario_tag"] == "BASE" and f["forecast_year"] == forecast_year:
                row = f
                break
    if row is None:
        return None
    return effective_load_for(
        row["residential_mw"], row["commercial_mw"],
        row["industrial_mw"], row["electrification_mw"], variant,
    )


# ---------------------------------------------------------------------------
# screening_levelized_cost (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def capital_recovery_factor() -> Decimal:
    one_plus = 1 + DISCOUNT_RATE
    p = one_plus ** ASSET_LIFE_YEARS
    return DISCOUNT_RATE * p / (p - 1)


def levelized_cost_per_mw_year(candidate: dict) -> Decimal:
    """Full-precision levelized cost per MW-year for ranking."""
    crf = capital_recovery_factor()
    capex = D(candidate["capex_usd_per_kw"]) * crf * 1000      # $/MW-year
    fixed_om = D(candidate["fixed_om_usd_per_kw_year"]) * 1000  # $/MW-year
    return capex + fixed_om


def levelized_cost_for_mw(candidate: dict, mw: Decimal) -> Decimal:
    """Full-precision levelized annual cost for a given MW allocation."""
    crf = capital_recovery_factor()
    capex = D(candidate["capex_usd_per_kw"]) * crf * mw * 1000
    fixed_om = D(candidate["fixed_om_usd_per_kw_year"]) * mw * 1000
    return capex + fixed_om


def candidate_feasible(candidate: dict, delivery_year: int, decision_year: int) -> bool:
    """Feasibility filter: online_year <= delivery_year AND lead fits the gap."""
    if candidate["online_year"] > delivery_year:
        return False
    if candidate["build_lead_years"] > (delivery_year - decision_year):
        return False
    return True


def unit_accredited_mw_at_year(resource: dict, year: int) -> Decimal:
    """The unit's own accredited MW in a year (nameplate * base * der), 2dp."""
    base = ACCREDITATION[resource["resource_type"]]
    der = derating_factor(
        resource["resource_type"], year,
        in_service_year=resource["in_service_year"],
        online_year=resource["in_service_year"],
        is_decided=True,
        retirement_year=resource.get("retirement_year"),
    )
    return round_half_up(D(resource["nameplate_mw"]) * base * der, 2)


def replacement_cost_for_year(required_mw: Decimal, year: int, decision_year: int) -> Decimal:
    """Greedy waterfall allocation for one year; whole-dollar, half-up."""
    if required_mw <= 0:
        return Decimal(0)
    feasible = [
        c for c in store.candidates.values()
        if candidate_feasible(c, year, decision_year)
    ]
    feasible.sort(key=lambda c: (levelized_cost_per_mw_year(c), c["global_sequence_index"]))
    remaining = D(required_mw)
    total = Decimal(0)
    for c in feasible:
        if remaining <= 0:
            break
        alloc = min(remaining, D(c["nameplate_mw"]))
        total += levelized_cost_for_mw(c, alloc)  # full precision within the year
        remaining -= alloc
    # Round the per-year component to whole dollars before the window sum.
    return round_half_up(total, 0)


# ---------------------------------------------------------------------------
# retirement_analysis (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def compliance_cost_for_year(resource: dict, year: int) -> Decimal:
    """Per-year compliance cost in whole dollars (round-half-up)."""
    rtype = resource["resource_type"]
    if rtype == "COAL":
        if year >= 2030:
            rate = COAL_COMPLIANCE_BASE + COAL_COMPLIANCE_STEP * (year - 2030)
            if rate < COAL_COMPLIANCE_BASE:
                rate = COAL_COMPLIANCE_BASE
        else:
            rate = COAL_COMPLIANCE_BASE
    elif rtype == "GAS_CT":
        rate = GAS_CT_COMPLIANCE
    else:
        rate = Decimal(0)
    return round_half_up(rate * D(resource["nameplate_mw"]), 0)


def fixed_om_rate(resource: dict) -> Decimal:
    rtype = resource["resource_type"]
    if rtype == "COAL":
        return FIXED_OM_COAL
    if rtype == "GAS_CT":
        return FIXED_OM_GAS_CT
    return FIXED_OM_DEFAULT


def compute_retirement_analysis(resource: dict, snapshot: dict, decision_year: int) -> dict:
    """Compute the four cost fields and the recommendation.

    Window: [retirement_year, retirement_year + 9] inclusive.
    Round-per-component-then-sum at whole dollars.
    """
    ry = resource.get("retirement_year")
    if ry is None:
        raise_error(ERR_INVALID_REQUEST, "Resource has no retirement_year set")
    window = list(range(ry, ry + ANALYSIS_WINDOW_YEARS))
    compliance = sum((compliance_cost_for_year(resource, y) for y in window), Decimal(0))
    fixed_om = sum(
        (round_half_up(fixed_om_rate(resource) * D(resource["nameplate_mw"]), 0) for y in window),
        Decimal(0),
    )
    required = unit_accredited_mw_at_year(resource, ry)
    replacement = sum(
        (replacement_cost_for_year(required, y, decision_year) for y in window),
        Decimal(0),
    )
    compliance = round_half_up(compliance, 0)
    fixed_om = round_half_up(fixed_om, 0)
    replacement = round_half_up(replacement, 0)
    net = compliance + fixed_om - replacement
    return {
        "compliance_cost_usd": int(compliance),
        "replacement_cost_usd": int(replacement),
        "fixed_om_avoided_usd": int(fixed_om),
        "net_retirement_benefit_usd": int(net),
        "recommendation": "RETIRE" if net > 0 else "KEEP",
    }


# ---------------------------------------------------------------------------
# sensitivity_scoring (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def portfolio_base_score(snapshot: dict) -> dict:
    """Per-position base score breakdown at the snapshot's forecast year.

    Returns dict with 'total' (Decimal full precision) and per-position parts.
    """
    portfolio = store.portfolios.get(snapshot["portfolio_id"])
    year = snapshot["forecast_year"]
    parts = []
    total = Decimal(0)
    if portfolio is not None:
        for pos in store.positions.values():
            if pos["portfolio_id"] != portfolio["id"] or not pos.get("selected", True):
                continue
            cand = store.candidates.get(pos["candidate_id"])
            if cand is None:
                continue
            mw = D(pos["committed_mw"])
            crf = capital_recovery_factor()
            capex_term = D(cand["capex_usd_per_kw"]) * crf * mw * 1000
            om_term = D(cand["fixed_om_usd_per_kw_year"]) * mw * 1000
            parts.append({
                "candidate": cand,
                "capex_term": capex_term,
                "om_term": om_term,
                "total": capex_term + om_term,
            })
            total += capex_term + om_term
    return {"total": total, "parts": parts}


def compute_sensitivity(snapshot: dict, dimension: str, delta_pct: Decimal,
                        scoring_variant: str) -> dict:
    """Compute base/adjusted scores and robust_flag (whole dollars, half-up)."""
    delta = D(delta_pct)
    base_info = portfolio_base_score(snapshot)
    base = base_info["total"]
    if dimension == "FUEL_PRICE":
        if scoring_variant == "MARKET":
            adjusted = base * (1 + delta)
        else:  # COST_PLUS default
            adjusted = base * (1 + FUEL_SHARE_COST_PLUS * delta)
    elif dimension == "POLICY":
        fossil_types = {"COAL", "GAS_CC", "GAS_CT"}
        fossil = sum(
            (p["total"] for p in base_info["parts"]
             if p["candidate"]["resource_type"] in fossil_types),
            Decimal(0),
        )
        clean = base - fossil
        adjusted = clean + fossil * (1 + POLICY_FACTOR * delta)
    elif dimension == "TECHNOLOGY_COST":
        capex_total = sum((p["capex_term"] for p in base_info["parts"]), Decimal(0))
        om_total = sum((p["om_term"] for p in base_info["parts"]), Decimal(0))
        adjusted = capex_total * (1 + delta) + om_total
    else:
        raise_error(ERR_INVALID_REQUEST, f"Unknown dimension: {dimension}")
    base_r = round_half_up(base, 0)
    adjusted_r = round_half_up(adjusted, 0)
    robust = abs(adjusted_r - base_r) <= ROBUST_TOLERANCE_PCT * base_r
    return {
        "base_score_usd": int(base_r),
        "adjusted_score_usd": int(adjusted_r),
        "robust_flag": bool(robust),
    }


# ---------------------------------------------------------------------------
# deviation_measurement (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def compute_deviation_report(plan: dict, report_year: int, actual_load_mw) -> dict:
    from errors import ERR_INVALID_REQUEST, ERR_SNAPSHOT_NOT_FOUND
    approved_id = plan.get("approved_snapshot_id")
    baseline = None
    if approved_id:
        snap = store.snapshots.get(approved_id)
        if snap is not None:
            if snap["forecast_year"] == report_year:
                baseline = D(snap["load_mw"])
            else:
                # use approved snapshot's portfolio's snapshot for report_year
                for s in store.snapshots.values():
                    if (s["portfolio_id"] == snap["portfolio_id"]
                            and s["forecast_year"] == report_year):
                        baseline = D(s["load_mw"])
                        break
    if baseline is None:
        raise_error(ERR_SNAPSHOT_NOT_FOUND,
                    "No snapshot exists for the report year on the approved portfolio")
    if baseline == 0:
        raise_error(ERR_INVALID_REQUEST, "baseline_load_mw is zero")
    actual = D(actual_load_mw)
    deviation = (actual - baseline) / baseline
    deviation_q = round_half_up(deviation, 4)
    committed = sum(
        (D(c["committed_mw"]) for c in store.commitments.values()
         if c["plan_id"] == plan["id"] and c["status"] in ("ISSUED", "AWARDED")),
        Decimal(0),
    )
    required = sum(
        (D(c["required_procurement_mw"]) for c in store.conditions.values()
         if c["plan_id"] == plan["id"] and c["status"] == "OPEN"),
        Decimal(0),
    )
    proc_dev = round_half_up(committed - required, 2)
    breach = (abs(deviation_q) > DEVIATION_THRESHOLD_PCT) or (proc_dev < 0)
    return {
        "baseline_load_mw": num2(baseline),
        "load_deviation_pct": float(deviation_q),
        "committed_procurement_mw": num2(committed),
        "required_procurement_mw": num2(required),
        "procurement_deviation_mw": float(proc_dev),
        "material_breach": bool(breach),
    }


# ---------------------------------------------------------------------------
# accreditation_waterfall (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------

def committed_aggregate(candidate_id: str) -> Decimal:
    return sum(
        (D(c["committed_mw"]) for c in store.commitments.values()
         if c["candidate_id"] == candidate_id and c["status"] in ("ISSUED", "AWARDED")),
        Decimal(0),
    )


def waterfall_select(requested_mw: Decimal, clock_year: int):
    """Pick a candidate via the accreditation waterfall.

    Returns the selected candidate dict. Raises ERR_NO_ELIGIBLE_CANDIDATE when
    the eligible set cannot cover the requested block.
    """
    from errors import ERR_NO_ELIGIBLE_CANDIDATE
    eligible = []
    for c in store.candidates.values():
        # online_year <= clock_year + build_lead_years  (lead-time feasible)
        if c["online_year"] > clock_year + c["build_lead_years"]:
            continue
        agg = committed_aggregate(c["id"])
        if agg >= D(c["nameplate_mw"]):
            continue
        eligible.append((c, D(c["nameplate_mw"]) - agg))
    eligible.sort(key=lambda t: (levelized_cost_per_mw_year(t[0]),
                                 t[0]["global_sequence_index"]))
    remaining = D(requested_mw)
    selected = None
    for c, available in eligible:
        if remaining <= 0:
            break
        alloc = min(remaining, available)
        if alloc <= 0:
            continue
        if selected is None:
            selected = c
        remaining -= alloc
    if selected is None or remaining > 0:
        raise_error(ERR_NO_ELIGIBLE_CANDIDATE,
                    "No feasible candidate set can cover the requested MW")
    return selected
