"""Every derived quantity the PRD defines.

All arithmetic uses decimal.Decimal with ROUND_HALF_UP at the pinned decimal
place; no float ever participates in a stored value.
"""
from decimal import Decimal, ROUND_HALF_UP

import store
from store import dec

# ------------------------------------------------------------------ constants
FAULT_SETBACK_FT = Decimal("200")
MIN_AQUIFER_SEPARATION_FT = Decimal("5.0")
WETLAND_SETBACK_FT = Decimal("500")
SEISMIC_PGA_MAX = Decimal("0.10")

FOS_STATIC_MIN = Decimal("1.50")
FOS_SEISMIC_MIN = Decimal("1.00")
FOS_LIQUEFACTION_MIN = Decimal("1.20")

MIN_BACKGROUND_WELLS = 1
MIN_DOWNGRADIENT_WELLS = 3

NON_DETECT_FRACTION = Decimal("0.5")
VALUE_DECIMALS = 4

MIN_BACKGROUND_VALUES = 4
KAPPA_N_4_TO_5 = Decimal("3.187")
KAPPA_N_6_TO_7 = Decimal("2.752")
KAPPA_N_8_PLUS = Decimal("2.355")
LIMIT_DECIMALS = 4
MEAN_DECIMALS = 4
STDEV_DECIMALS = 6

GWPS_MG_PER_L = {
    "ARSENIC": Decimal("0.010"),
    "LITHIUM": Decimal("0.040"),
    "MOLYBDENUM": Decimal("0.100"),
    "RADIUM_226_228": Decimal("5.0"),
}

ASD_WINDOW_DAYS = 90
SEMIANNUAL_INTERVAL_DAYS = 182
QUARTERLY_INTERVAL_DAYS = 91
MIN_SAMPLE_INTERVAL_DAYS = 90

DISCOUNT_RATE = Decimal("0.03")
COST_TIE_BAND_PCT = Decimal("5.00")

TIER_1_CEILING_CENTS = 500000000
TIER_2_CEILING_CENTS = 2000000000
TIER_1_RATE = Decimal("0.20")
TIER_2_RATE = Decimal("0.15")
TIER_3_RATE = Decimal("0.10")
OVERSIGHT_FEE_RATE = Decimal("0.025")

BASE_CLOSURE_MONTHS = {"SURFACE_IMPOUNDMENT": 60, "LANDFILL": 30}
EXTENSION_CAP_MONTHS = {"SURFACE_IMPOUNDMENT": 60, "LANDFILL": 24}

CARE_BASE_YEARS = 30
DEFICIENCY_EXTENSION_MONTHS_EACH = 12
DEFICIENCY_EXTENSION_CAP_MONTHS = 60

MAX_SETTLEMENT_INCHES = Decimal("6.00")
MIN_VEGETATION_COVER_PCT = Decimal("70.00")
CAP_REPAIR_WINDOW_DAYS = 60

MAX_LOI_PCT = Decimal("6.00")
MAX_RETAINED_325_PCT = Decimal("34.00")
MIN_OXIDE_SUM_PCT = Decimal("70.00")
LOI_PENALTY_PER_PCT = Decimal("10")
FINENESS_PENALTY_PER_PCT = Decimal("2")
MARKET_PRICE_DIVISOR = Decimal("50")
WEIGHT_LOI = Decimal("0.30")
WEIGHT_FINENESS = Decimal("0.20")
WEIGHT_OXIDE = Decimal("0.35")
WEIGHT_MARKET = Decimal("0.15")
PRODUCT_BONUS = {
    "CONCRETE_POZZOLAN": Decimal("8"),
    "WALLBOARD": Decimal("4"),
    "STRUCTURAL_FILL": Decimal("0"),
    "ROADBASE": Decimal("0"),
}
HAUL_MID_MILES = 75
HAUL_FAR_MILES = 150
HAUL_PENALTY_MID = Decimal("5")
HAUL_PENALTY_FAR = Decimal("10")
MARKET_READY_SCORE_MIN = Decimal("50.00")
SCORE_DECIMALS = 2

POSTING_TYPE_ORDER = [
    "ANNUAL_GW_REPORT",
    "STABILITY_ASSESSMENT",
    "CLOSURE_PLAN",
    "SSI_NOTIFICATION",
    "EXTENSION_DEMONSTRATION",
]
STABILITY_POSTING_WINDOW_DAYS = 30
CLOSURE_PLAN_POSTING_WINDOW_DAYS = 60
SSI_NOTICE_WINDOW_DAYS = 30
EXTENSION_DEMONSTRATION_WINDOW_DAYS = 30


def rnd(value, places):
    """Round half-up to `places` decimals, returning a Decimal at that scale."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rnd_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def sqrt_exact(value):
    return dec(value).sqrt()


# ------------------------------------------------------- siting and stability
def location_restriction_verdict(unit):
    """Ordered first-match chain; frozen at unit creation."""
    if unit["unstable_area_flag"]:
        return "DISQUALIFIED"
    if dec(unit["fault_distance_ft"]) < FAULT_SETBACK_FT:
        return "DISQUALIFIED"
    if dec(unit["uppermost_aquifer_separation_ft"]) < MIN_AQUIFER_SEPARATION_FT:
        return "DISQUALIFIED"
    if (dec(unit["wetland_distance_ft"]) < WETLAND_SETBACK_FT
            and unit["hazard_potential_class"] in ("SIGNIFICANT", "HIGH")):
        return "RESTRICTED_DEMONSTRATION_REQUIRED"
    if (dec(unit["seismic_pga_g"]) > SEISMIC_PGA_MAX
            and unit["liner_class"] == "UNLINED"):
        return "RESTRICTED_DEMONSTRATION_REQUIRED"
    return "UNRESTRICTED"


def stability_assessment_verdict(row):
    criteria = []
    if dec(row["factor_of_safety_static"]) < FOS_STATIC_MIN:
        criteria.append("STATIC")
    if dec(row["factor_of_safety_seismic"]) < FOS_SEISMIC_MIN:
        criteria.append("SEISMIC")
    if dec(row["factor_of_safety_liquefaction"]) < FOS_LIQUEFACTION_MIN:
        criteria.append("LIQUEFACTION")
    return ("DEFICIENT" if criteria else "ADEQUATE"), criteria


def governing_stability_verdict(unit_id):
    """Latest assessed_on wins, ties broken by later created_at; id never used."""
    rows = [r for r in store.stability_assessments.values()
            if r["unit_id"] == unit_id]
    if not rows:
        return None, "UNASSESSED"
    governing = max(rows, key=lambda r: (r["assessed_on"], r["created_at"], r["_seq"]))
    for row in rows:
        row["superseded"] = row is not governing
    return governing, governing["verdict"]


# ------------------------------------------------------------ well network
def certified_well_counts(unit_id):
    background = 0
    downgradient = 0
    for well in store.wells.values():
        if well["unit_id"] != unit_id or well["well_status"] != "CERTIFIED":
            continue
        if well["well_role"] == "BACKGROUND":
            background += 1
        elif well["well_role"] == "DOWNGRADIENT":
            downgradient += 1
    return background, downgradient


def network_certification_readiness(program):
    background, downgradient = certified_well_counts(program["unit_id"])
    ready = (background >= MIN_BACKGROUND_WELLS
             and downgradient >= MIN_DOWNGRADIENT_WELLS
             and program["background_window_start_on"] is not None
             and program["background_window_end_on"] is not None)
    return background, downgradient, ready


def analytical_effective_value(detection_flag, concentration, reporting_limit):
    if detection_flag == "NON_DETECT":
        return rnd(dec(reporting_limit) * NON_DETECT_FRACTION, VALUE_DECIMALS)
    return rnd(concentration, VALUE_DECIMALS)


def next_sampling_due_date(program):
    validated = [e for e in store.sampling_events.values()
                 if e["program_id"] == program["id"] and e["status"] == "VALIDATED"]
    if not validated:
        return None, None
    last = max(validated, key=lambda e: (e["sampled_on"], e["created_at"], e["_seq"]))
    interval = (SEMIANNUAL_INTERVAL_DAYS
                if program["sampling_frequency"] == "SEMIANNUAL"
                else QUARTERLY_INTERVAL_DAYS)
    return last["id"], store.add_days(last["sampled_on"], interval)


def latest_validated_sampled_on(program_id):
    validated = [e for e in store.sampling_events.values()
                 if e["program_id"] == program_id and e["status"] == "VALIDATED"]
    if not validated:
        return None
    last = max(validated, key=lambda e: (e["sampled_on"], e["created_at"], e["_seq"]))
    return last["sampled_on"]


# ------------------------------------------------------------ statistics
def _results_for(event_ids, parameter_code, well_ids):
    values = []
    for row in store.ordered(store.analytical_results.values()):
        if row["sampling_event_id"] not in event_ids:
            continue
        if row["parameter_code"] != parameter_code:
            continue
        if row["well_id"] not in well_ids:
            continue
        values.append(dec(row["effective_value"]))
    return values


def background_values(program, parameter_code, compliance_well_id):
    """Values inside the program's closed background window (variant aware)."""
    start = program["background_window_start_on"]
    end = program["background_window_end_on"]
    event_ids = set()
    for event in store.sampling_events.values():
        if event["program_id"] != program["id"] or event["status"] != "VALIDATED":
            continue
        if start <= event["sampled_on"] <= end:
            event_ids.add(event["id"])
    if program["comparison_basis"] == "INTRAWELL":
        well_ids = {compliance_well_id}
    else:
        well_ids = {w["id"] for w in store.wells.values()
                    if w["unit_id"] == program["unit_id"]
                    and w["well_role"] == "BACKGROUND"
                    and w["well_status"] in ("CERTIFIED", "DECOMMISSIONED")}
    return _results_for(event_ids, parameter_code, well_ids)


def background_statistical_limit(program, values):
    """Returns (n, upper_limit, mean, stdev). Caller checks n first."""
    n = len(values)
    total = sum(values, Decimal(0))
    mean_exact = total / Decimal(n)
    var_exact = (sum(((v - mean_exact) ** 2 for v in values), Decimal(0))
                 / Decimal(n - 1))
    stdev_exact = sqrt_exact(var_exact)
    if program["statistical_method"] == "PARAMETRIC_PREDICTION_INTERVAL":
        if 4 <= n <= 5:
            kappa = KAPPA_N_4_TO_5
        elif 6 <= n <= 7:
            kappa = KAPPA_N_6_TO_7
        else:
            kappa = KAPPA_N_8_PLUS
        limit_exact = mean_exact + kappa * stdev_exact
    else:
        limit_exact = max(values)
    return (n,
            rnd(limit_exact, LIMIT_DECIMALS),
            rnd(mean_exact, MEAN_DECIMALS),
            rnd(stdev_exact, STDEV_DECIMALS))


def comparison_measurement(program, parameter_code, compliance_well_id):
    """Latest VALIDATED event strictly after the background window that carries
    a result for this well and parameter."""
    end = program["background_window_end_on"]
    candidates = []
    for event in store.sampling_events.values():
        if event["program_id"] != program["id"] or event["status"] != "VALIDATED":
            continue
        if event["sampled_on"] <= end:
            continue
        rows = [r for r in store.ordered(store.analytical_results.values())
                if r["sampling_event_id"] == event["id"]
                and r["well_id"] == compliance_well_id
                and r["parameter_code"] == parameter_code]
        if rows:
            candidates.append((event, rows[-1]))
    if not candidates:
        return None, None
    event, row = max(candidates,
                     key=lambda pair: (pair[0]["sampled_on"],
                                       pair[0]["created_at"], pair[0]["_seq"]))
    return event, dec(row["effective_value"])


def statistical_verdict(parameter_code, comparison_value, upper_limit,
                        retest_confirmed):
    gwps = GWPS_MG_PER_L.get(parameter_code)
    if comparison_value <= upper_limit:
        return "NO_SSI"
    if gwps is not None and comparison_value > gwps and retest_confirmed:
        return "SSL_EXCEEDANCE"
    return "SSI"


def asd_deadline_date(verdict, determined_on):
    if verdict in ("SSI", "SSL_EXCEEDANCE"):
        return store.add_days(determined_on, ASD_WINDOW_DAYS)
    return None


# ------------------------------------------------------------------ costing
def _care_pv(annual, years):
    """Per-year discounted care rounded to whole cents BEFORE summation."""
    total = 0
    base = Decimal(1) + DISCOUNT_RATE
    for year in range(1, years + 1):
        total += rnd_int(dec(annual) / (base ** year))
    return total


def closure_cost_present_value(plan):
    years = plan["care_period_years"]
    in_place_nominal = (plan["in_place_capital_usd_cents"]
                        + plan["in_place_annual_care_usd_cents"] * years)
    removal_nominal = (plan["removal_capital_usd_cents"]
                       + plan["removal_annual_care_usd_cents"] * years)
    in_place_pv = (plan["in_place_capital_usd_cents"]
                   + _care_pv(plan["in_place_annual_care_usd_cents"], years))
    removal_pv = (plan["removal_capital_usd_cents"]
                  + _care_pv(plan["removal_annual_care_usd_cents"], years))
    denominator = max(in_place_pv, removal_pv)
    variance = rnd(dec(abs(in_place_pv - removal_pv)) * Decimal(100)
                   / dec(denominator), 2)
    return {
        "in_place_nominal_usd_cents": in_place_nominal,
        "removal_nominal_usd_cents": removal_nominal,
        "in_place_pv_usd_cents": in_place_pv,
        "removal_pv_usd_cents": removal_pv,
        "cost_variance_pct": variance,
    }


def closure_method_recommendation(unit, totals):
    if unit["location_restriction_verdict"] == "DISQUALIFIED":
        return "CLOSURE_BY_REMOVAL"
    if unit["liner_class"] == "UNLINED" and unit["hazard_potential_class"] == "HIGH":
        return "CLOSURE_BY_REMOVAL"
    if dec(totals["cost_variance_pct"]) <= COST_TIE_BAND_PCT:
        return "CLOSURE_IN_PLACE"
    if totals["in_place_pv_usd_cents"] < totals["removal_pv_usd_cents"]:
        return "CLOSURE_IN_PLACE"
    return "CLOSURE_BY_REMOVAL"


def corrective_action_assurance_amount(base):
    if base < TIER_1_CEILING_CENTS:
        rate = TIER_1_RATE
    elif base < TIER_2_CEILING_CENTS:
        rate = TIER_2_RATE
    else:
        rate = TIER_3_RATE
    contingency = rnd_int(dec(base) * rate)
    subtotal = base + contingency
    oversight = rnd_int(dec(subtotal) * OVERSIGHT_FEE_RATE)
    return {
        "contingency_rate": rate,
        "contingency_usd_cents": contingency,
        "subtotal_usd_cents": subtotal,
        "oversight_fee_usd_cents": oversight,
        "assurance_amount_usd_cents": subtotal + oversight,
    }


# ------------------------------------------------------------- closure dates
def closure_deadline_date(unit):
    months = (BASE_CLOSURE_MONTHS[unit["unit_type"]]
              + unit["granted_extension_months"])
    return store.add_months(unit["cessation_date"], months)


def deficient_inspection_count(unit_id):
    return len([r for r in store.cap_inspections.values()
                if r["unit_id"] == unit_id and r["verdict"] == "DEFICIENT"])


def post_closure_care_end_date(unit):
    if unit["post_closure_care_start_on"] is None:
        return None
    count = deficient_inspection_count(unit["id"])
    extension = min(DEFICIENCY_EXTENSION_CAP_MONTHS,
                    count * DEFICIENCY_EXTENSION_MONTHS_EACH)
    return store.add_months(unit["post_closure_care_start_on"],
                            CARE_BASE_YEARS * 12 + extension)


def cap_inspection_verdict(row):
    criteria = []
    if row["erosion_severity"] != "NONE":
        criteria.append("EROSION")
    if dec(row["settlement_inches"]) > MAX_SETTLEMENT_INCHES:
        criteria.append("SETTLEMENT")
    if dec(row["vegetation_cover_pct"]) < MIN_VEGETATION_COVER_PCT:
        criteria.append("VEGETATION")
    return ("DEFICIENT" if criteria else "PASS"), criteria


# ------------------------------------------------------------- ash and reuse
def unit_agreements(unit_id):
    return [a for a in store.reuse_agreements.values() if a["unit_id"] == unit_id]


def agreement_shipped_tons(agreement_id):
    return sum(s["tons"] for s in store.reuse_shipments.values()
               if s["agreement_id"] == agreement_id and s["status"] == "SHIPPED")


def ash_in_place_balance(unit):
    shipped_out = 0
    for agreement in unit_agreements(unit["id"]):
        shipped_out += agreement_shipped_tons(agreement["id"])
    unit["ash_in_place_tons"] = unit["original_ash_in_place_tons"] - shipped_out
    unit["ash_mass_balance_ok"] = (
        unit["ash_in_place_tons"] + shipped_out
        == unit["original_ash_in_place_tons"])
    for agreement in unit_agreements(unit["id"]):
        agreement["shipped_tons_total"] = agreement_shipped_tons(agreement["id"])
    return unit["ash_in_place_tons"]


def reuse_commitment_exposure(candidate):
    peers = [p for p in store.reuse_agreements.values()
             if p["unit_id"] == candidate["unit_id"]
             and p["id"] != candidate["id"]
             and p["status"] in ("QUALIFIED", "ACTIVE")]
    overlapping = [p for p in peers
                   if p["commitment_start_on"] <= candidate["commitment_end_on"]
                   and candidate["commitment_start_on"] <= p["commitment_end_on"]]
    return sum(p["committed_tons"] for p in overlapping) + candidate["committed_tons"]


def ash_quality_and_reuse_score(agreement):
    loi = dec(agreement["loi_percent"])
    retained = dec(agreement["retained_325_percent"])
    oxide = dec(agreement["oxide_sum_percent"])
    meets = (loi <= MAX_LOI_PCT and retained <= MAX_RETAINED_325_PCT
             and oxide >= MIN_OXIDE_SUM_PCT)
    loi_component = max(Decimal(0), Decimal(100) - loi * LOI_PENALTY_PER_PCT)
    fineness_component = max(Decimal(0),
                             Decimal(100) - retained * FINENESS_PENALTY_PER_PCT)
    oxide_component = min(Decimal(100), oxide)
    market_component = min(Decimal(100),
                          dec(agreement["market_price_usd_cents_per_ton"])
                          / MARKET_PRICE_DIVISOR)
    weighted = (WEIGHT_LOI * loi_component
                + WEIGHT_FINENESS * fineness_component
                + WEIGHT_OXIDE * oxide_component
                + WEIGHT_MARKET * market_component)
    bonus = PRODUCT_BONUS.get(agreement["product_type"], Decimal(0))
    miles = agreement["haul_distance_miles"]
    if miles > HAUL_FAR_MILES:
        penalty = HAUL_PENALTY_FAR
    elif miles > HAUL_MID_MILES:
        penalty = HAUL_PENALTY_MID
    else:
        penalty = Decimal(0)
    raw = weighted + bonus - penalty
    score = rnd(min(Decimal("100.00"), max(Decimal("0.00"), raw)), SCORE_DECIMALS)
    return meets, score


# --------------------------------------------------------- public disclosure
def obligation_due_dates(unit):
    return {
        "STABILITY_ASSESSMENT": unit["stability_posting_due_date"],
        "CLOSURE_PLAN": unit["closure_plan_posting_due_date"],
        "SSI_NOTIFICATION": unit["ssi_notice_due_date"],
        "EXTENSION_DEMONSTRATION": unit["extension_demonstration_due_date"],
        "ANNUAL_GW_REPORT": None,
    }


def unit_postings(unit_id):
    return [p for p in store.public_postings.values() if p["unit_id"] == unit_id]


def posting_days_late(posting, due):
    if due is None or posting["status"] != "POSTED":
        return 0
    return max(0, store.day_diff(posting["posted_on"], due))


def refresh_postings(unit):
    """Recompute every posting projection plus the unit's rollups."""
    due_by_type = obligation_due_dates(unit)
    today = store.fmt_date(store.today())
    postings = unit_postings(unit["id"])
    late_count = 0
    for posting in postings:
        due = due_by_type.get(posting["posting_type"])
        posting["satisfied_obligation"] = (posting["status"] == "POSTED"
                                           and due is not None)
        posting["days_late"] = posting_days_late(posting, due)
        if posting["status"] == "POSTED" and posting["days_late"] > 0:
            late_count += 1
    satisfied_types = {p["posting_type"] for p in postings
                       if p["status"] == "POSTED"}
    overdue = [t for t in POSTING_TYPE_ORDER
               if due_by_type.get(t) is not None
               and t not in satisfied_types
               and today > due_by_type[t]]
    pending_upcoming = any(due_by_type.get(t) is not None
                           and t not in satisfied_types
                           and due_by_type[t] >= today
                           for t in POSTING_TYPE_ORDER)
    unit["overdue_posting_types"] = overdue
    unit["late_posting_count"] = late_count
    unit["_pending_obligation_due"] = pending_upcoming
    return overdue


def unit_program(unit_id):
    for program in store.ordered(store.programs.values()):
        if program["unit_id"] == unit_id:
            return program
    return None


def compliance_posture(unit):
    """FROZEN > RESTRICTED > WATCH > COMPLIANT, first match wins."""
    today = store.fmt_date(store.today())
    program = unit_program(unit["id"])
    refresh_postings(unit)
    frozen = (
        unit["governing_stability_verdict"] == "DEFICIENT"
        or (unit["cap_integrity_state"] == "DEFICIENT"
            and unit["cap_repair_due_date"] is not None
            and today > unit["cap_repair_due_date"])
        or (unit["closure_state"] == "ACTIVE"
            and today > unit["closure_deadline_date"])
        or len(unit["overdue_posting_types"]) > 0
    )
    if frozen:
        return "FROZEN"
    restricted = (
        (program is not None
         and program["phase"] in ("ASSESSMENT", "CORRECTIVE_ACTION"))
        or unit["location_restriction_verdict"] == "DISQUALIFIED"
    )
    if restricted:
        return "RESTRICTED"
    watch = (unit["cap_integrity_state"] == "DEFICIENT"
             or unit["demonstration_required"] is True
             or unit["_pending_obligation_due"])
    if watch:
        return "WATCH"
    return "COMPLIANT"
