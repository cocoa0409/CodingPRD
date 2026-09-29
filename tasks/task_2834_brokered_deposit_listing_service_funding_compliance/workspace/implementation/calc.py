"""Every calculation in the PRD, plus the derived-balance recompute pipeline."""

import db
import util
from errors import ApiError
from util import floor_div, round_half_up

# --- constants ------------------------------------------------------------
NATIONAL_SPREAD_BPS = 75
LOCAL_SPREAD_BPS = 75
NON_MATURITY_SPREAD_BPS = 50
DAY_COUNT_BASIS = 365
BPS_DENOM = 10000

VOLUME_TIER_1_CEILING_CENTS = 100000000
VOLUME_TIER_2_CEILING_CENTS = 500000000
VOLUME_TIER_1_BPS = 15
VOLUME_TIER_2_BPS = 10
VOLUME_TIER_3_BPS = 7

AML_WEIGHT = 35
FINANCIAL_WEIGHT = 30
INSURANCE_WEIGHT = 20
RECORDKEEPING_WEIGHT = 15
WEIGHT_DENOM = 100

DILIGENCE_APPROVE_MIN = 70
DILIGENCE_CONDITIONAL_MIN = 60
AML_FLOOR = 60

TWENTY_FIVE_PCT_BPS = 2500
ENABLING_TXN_MIN_BPS = 7500

REPORT_INTERVAL_DAYS = 90
MAX_INFO_REQUEST_ROUNDS = 2
MAX_RFI_ROUNDS = 2
MAX_AMENDMENT_ROUNDS = 2

RECIPROCAL_EXCLUSION_CAP_BPS = 2500
LADDER_WINDOW_DAYS = 15
LADDER_WINDOW_CAP_BPS = 3500
BUFFER_HORIZON_DAYS = 90
VARIANCE_MATERIAL_BPS = 25

TENOR_BUCKETS = ("NON_MATURITY", "DAYS_1_30", "DAYS_31_90", "DAYS_91_180",
                 "DAYS_181_365", "DAYS_366_PLUS")
NON_MATURITY_PRODUCTS = ("MONEY_MARKET", "SAVINGS", "NOW")

CALL_REPORT_LINE = {
    "BROKERED": "RC_E_M1_BROKERED",
    "LISTING_SERVICE_NON_BROKERED": "RC_E_M2_LISTING",
    "CORE": "RC_E_CORE",
    "RECIPROCAL_EXCLUDED": "RC_O_M_RECIPROCAL",
}

BUCKET_FIELD = {
    "BROKERED": "brokered_deposits_cents",
    "LISTING_SERVICE_NON_BROKERED": "listing_service_deposits_cents",
    "RECIPROCAL_EXCLUDED": "reciprocal_deposits_cents",
}

METRIC_ORDER = ("BROKERED_TO_TOTAL_DEPOSITS", "LISTING_TO_TOTAL_DEPOSITS",
                "WHOLESALE_TO_TOTAL_LIABILITIES", "SINGLE_BROKER_TO_TOTAL_DEPOSITS")

STAGE_MULTIPLIER_BPS = {
    "NONE": 0,
    "STAGE_1_MONITOR": 2500,
    "STAGE_2_CONTINGENT": 5000,
    "STAGE_3_CRISIS": 10000,
}

FUNDED_STATUSES = ("ACTIVE", "MATURED", "WITHDRAWN_EARLY", "ROLLED_OVER")


# --- simple derivations ---------------------------------------------------
def rate_cap_regime(capital_category):
    return "EXEMPT" if capital_category == "WELL_CAPITALIZED" else "CAPPED"


def tenor_bucket(product_type, tenor_days):
    if product_type in NON_MATURITY_PRODUCTS:
        return "NON_MATURITY"
    if tenor_days <= 30:
        return "DAYS_1_30"
    if tenor_days <= 90:
        return "DAYS_31_90"
    if tenor_days <= 180:
        return "DAYS_91_180"
    if tenor_days <= 365:
        return "DAYS_181_365"
    return "DAYS_366_PLUS"


# --- rate ceiling ---------------------------------------------------------
def select_rate_cap(bucket, as_of_date):
    """Latest publication for the bucket effective on or before as_of_date;
    ties on effective_date broken by the most recently created row."""
    pool = [c for c in db.national_rate_caps.values()
            if c["tenor_bucket"] == bucket and c["effective_date"] <= as_of_date]
    if not pool:
        return None
    pool.sort(key=lambda c: (c["effective_date"], c["created_at"], c["_seq"]))
    return pool[-1]


def effective_cap(institution, bucket, local_prevailing_rate_bps, as_of_date,
                  require=True):
    """Returns (effective_cap_bps or None, selected publication or None)."""
    if institution["rate_cap_regime"] == "EXEMPT":
        return None, select_rate_cap(bucket, as_of_date)
    pub = select_rate_cap(bucket, as_of_date)
    if pub is None:
        if require:
            raise ApiError("ERR_NO_RATE_CAP_PUBLISHED")
        return None, None
    national_leg = pub["published_national_rate_bps"] + NATIONAL_SPREAD_BPS
    if local_prevailing_rate_bps is None:
        combined = national_leg
    else:
        combined = max(national_leg, local_prevailing_rate_bps + LOCAL_SPREAD_BPS)
    if bucket == "NON_MATURITY":
        combined = min(combined, pub["published_national_rate_bps"] + NON_MATURITY_SPREAD_BPS)
    return combined, pub


# --- settlement arithmetic ------------------------------------------------
def accrued_interest(principal_cents, rate_bps, days):
    if days <= 0:
        return 0
    return round_half_up(principal_cents * rate_bps * days,
                         BPS_DENOM * DAY_COUNT_BASIS)


def contractual_penalty(principal_cents, rate_bps, penalty_days):
    if penalty_days <= 0:
        return 0
    return round_half_up(principal_cents * rate_bps * penalty_days,
                         BPS_DENOM * DAY_COUNT_BASIS)


def diligence_score(agreement):
    numerator = (AML_WEIGHT * agreement["aml_program_score"]
                 + FINANCIAL_WEIGHT * agreement["financial_condition_score"]
                 + INSURANCE_WEIGHT * agreement["insurance_coverage_score"]
                 + RECORDKEEPING_WEIGHT * agreement["recordkeeping_score"])
    return round_half_up(numerator, WEIGHT_DENOM)


# --- broker fee settlement (round each line, then sum) --------------------
def _line_fee(agreement, placement):
    structure = agreement["fee_structure"]
    if structure in ("FLAT_FEE", "PER_ACCOUNT_FEE"):
        return agreement["fee_flat_cents"]
    principal = placement["principal_cents"]
    if structure == "BASIS_POINT_FEE":
        return round_half_up(principal * agreement["fee_bps"], BPS_DENOM)
    # VOLUME_TIERED: the rate is selected by this one placement's own principal
    if principal < VOLUME_TIER_1_CEILING_CENTS:
        rate = VOLUME_TIER_1_BPS
    elif principal < VOLUME_TIER_2_CEILING_CENTS:
        rate = VOLUME_TIER_2_BPS
    else:
        rate = VOLUME_TIER_3_BPS
    return round_half_up(principal * rate, BPS_DENOM)


def fee_lines(agreement):
    """(placements, per-line fees, round-then-sum total) in placement created_at ASC."""
    contributing = []
    for placement in db.placements.values():
        if placement["funding_status"] != "ACTIVE":
            continue
        program = db.programs.get(placement["program_id"])
        if program is None or program.get("agreement_id") != agreement["id"]:
            continue
        contributing.append(placement)
    contributing = db.by_created(contributing)
    fees = [_line_fee(agreement, p) for p in contributing]
    return contributing, fees, sum(fees)


def recompute_agreement_fees(agreement):
    contributing, fees, total = fee_lines(agreement)
    for placement, fee in zip(contributing, fees):
        if placement["fee_accrual_cents"] != fee:
            placement["fee_accrual_cents"] = fee
            db.touch(placement)
    if agreement["accrued_fee_cents"] != total:
        agreement["accrued_fee_cents"] = total
        db.touch(agreement)
    return total


def recompute_fees_for_placement(placement):
    """Refresh the agreement fee position that this placement belongs to."""
    program = db.programs.get(placement["program_id"])
    if program is None:
        return
    agreement_id = program.get("agreement_id")
    if not agreement_id:
        if placement["fee_accrual_cents"] != 0:
            placement["fee_accrual_cents"] = 0
            db.touch(placement)
        return
    agreement = db.broker_agreements.get(agreement_id)
    if agreement is None:
        return
    recompute_agreement_fees(agreement)


# --- primary purpose tests ------------------------------------------------
def primary_purpose_tests(filing):
    filing["business_line_deposit_ratio_bps"] = floor_div(
        filing["deposits_placed_at_ifs_cents"] * BPS_DENOM,
        filing["total_customer_assets_cents"])
    filing["enabling_transaction_ratio_bps"] = floor_div(
        filing["enabling_transaction_count"] * BPS_DENOM,
        filing["total_transaction_count"])
    basis = filing["exception_basis"]
    if basis == "TWENTY_FIVE_PERCENT_TEST":
        qualified = filing["business_line_deposit_ratio_bps"] < TWENTY_FIVE_PCT_BPS
        filing["test_outcome"] = "QUALIFIED" if qualified else "NOT_QUALIFIED"
    elif basis == "ENABLING_TRANSACTIONS_TEST":
        qualified = filing["enabling_transaction_ratio_bps"] >= ENABLING_TXN_MIN_BPS
        filing["test_outcome"] = "QUALIFIED" if qualified else "NOT_QUALIFIED"
    else:
        filing["test_outcome"] = "NOT_EVALUATED"


# --- reciprocal exclusion capacity ---------------------------------------
def reciprocal_capacity(institution):
    cap = floor_div(RECIPROCAL_EXCLUSION_CAP_BPS * institution["total_liabilities_cents"],
                    BPS_DENOM)
    return max(0, cap - institution["reciprocal_deposits_cents"])


# --- classification determination -----------------------------------------
def determine_class(program, institution, exception):
    """Five branches, strictly top to bottom, first match wins."""
    if (program["funding_channel_claim"] == "RECIPROCAL_NETWORK"
            and reciprocal_capacity(institution) >= program["reciprocal_arrangement_cents"]):
        return "RECIPROCAL_EXCLUDED", "NOT_APPLICABLE"
    if not program.get("broker_id"):
        return "CORE", "NOT_APPLICABLE"
    if (exception is not None
            and exception["status"] in ("ACKNOWLEDGED", "GRANTED")
            and exception["test_outcome"] in ("QUALIFIED", "NOT_EVALUATED")):
        return "LISTING_SERVICE_NON_BROKERED", "NOT_APPLICABLE"
    broker = db.brokers.get(program["broker_id"])
    if (broker is not None and broker["broker_type"] == "LISTING_SERVICE"
            and not broker["has_placement_discretion"]):
        return "LISTING_SERVICE_NON_BROKERED", "NOT_APPLICABLE"
    if broker is not None and broker["has_placement_discretion"]:
        prong = "PLACEMENT_DISCRETION"
    elif broker is not None and broker["broker_type"] == "DEPOSIT_PLACEMENT_NETWORK":
        prong = "MATCHING_DRIVER"
    else:
        prong = "FEE_FOR_PLACEMENT"
    return "BROKERED", prong


# --- placement / institution navigation -----------------------------------
def program_of(placement):
    return db.programs.get(placement["program_id"])


def institution_of_placement(placement):
    program = program_of(placement)
    if program is None:
        return None
    return db.institutions.get(program["institution_id"])


def programs_of(institution_id):
    return db.by_created([p for p in db.programs.values()
                          if p["institution_id"] == institution_id])


def placements_of_program(program_id):
    return db.by_created([p for p in db.placements.values()
                          if p["program_id"] == program_id])


def placements_of(institution_id):
    rows = []
    for program in programs_of(institution_id):
        rows.extend(placements_of_program(program["id"]))
    return rows


def governing_class(program):
    if program is None or not program.get("governing_classification_id"):
        return None
    determination = db.classifications.get(program["governing_classification_id"])
    if determination is None:
        return None
    return determination["determined_class"]


def effective_class(placement):
    """classified_as once ACTIVE, otherwise the program's governing determination."""
    if placement["funding_status"] == "ACTIVE":
        return placement.get("classified_as")
    return governing_class(program_of(placement))


# --- balance rollup, ratios and posture -----------------------------------
def _metric_values(institution):
    total_deposits = institution["total_deposits_cents"]
    brokered = institution["brokered_deposits_cents"]
    listing = institution["listing_service_deposits_cents"]
    return {
        "BROKERED_TO_TOTAL_DEPOSITS": floor_div(brokered * BPS_DENOM, total_deposits),
        "LISTING_TO_TOTAL_DEPOSITS": floor_div(listing * BPS_DENOM, total_deposits),
        "WHOLESALE_TO_TOTAL_LIABILITIES": floor_div(
            (brokered + listing) * BPS_DENOM, institution["total_liabilities_cents"]),
        "SINGLE_BROKER_TO_TOTAL_DEPOSITS": institution["single_broker_max_ratio_bps"],
    }


def active_limits(institution_id):
    return db.by_created([l for l in db.concentration_limits.values()
                          if l["institution_id"] == institution_id
                          and l["status"] == "ACTIVE"])


def _breach_state(limit, value):
    if value >= limit["breach_threshold_bps"]:
        return "BREACH"
    if value >= limit["warning_threshold_bps"]:
        return "WARNING"
    return "WITHIN"


def _single_broker_max(institution):
    exposures = {}
    for program in programs_of(institution["id"]):
        broker_id = program.get("broker_id")
        if not broker_id:
            continue
        exposures.setdefault(broker_id, 0)
        for placement in placements_of_program(program["id"]):
            if placement["funding_status"] == "ACTIVE":
                exposures[broker_id] += placement["principal_cents"]
    if not exposures:
        return 0
    largest = max(exposures.values())
    return floor_div(largest * BPS_DENOM, institution["total_deposits_cents"])


def recompute_institution(institution):
    """Balance rollup, then the point-in-time ratio, then the posture — in that
    order (PRD 2.11).  Version is never advanced here."""
    if institution is None:
        return
    before = dict(institution)
    buckets = {"BROKERED": 0, "LISTING_SERVICE_NON_BROKERED": 0, "RECIPROCAL_EXCLUDED": 0}
    per_program = {}
    for program in programs_of(institution["id"]):
        outstanding = 0
        for placement in placements_of_program(program["id"]):
            if placement["funding_status"] != "ACTIVE":
                continue
            outstanding += placement["principal_cents"]
            klass = placement.get("classified_as")
            if klass in buckets:
                buckets[klass] += placement["principal_cents"]
        per_program[program["id"]] = outstanding

    institution["brokered_deposits_cents"] = buckets["BROKERED"]
    institution["listing_service_deposits_cents"] = buckets["LISTING_SERVICE_NON_BROKERED"]
    institution["reciprocal_deposits_cents"] = buckets["RECIPROCAL_EXCLUDED"]
    institution["total_deposits_cents"] = (institution["core_deposits_cents"]
                                           + buckets["BROKERED"]
                                           + buckets["LISTING_SERVICE_NON_BROKERED"]
                                           + buckets["RECIPROCAL_EXCLUDED"])
    institution["wholesale_funding_ratio_bps"] = floor_div(
        (buckets["BROKERED"] + buckets["LISTING_SERVICE_NON_BROKERED"]) * BPS_DENOM,
        institution["total_deposits_cents"])
    institution["single_broker_max_ratio_bps"] = _single_broker_max(institution)

    for program in programs_of(institution["id"]):
        value = per_program.get(program["id"], 0)
        if program["outstanding_principal_cents"] != value:
            program["outstanding_principal_cents"] = value
            db.touch(program)

    values = _metric_values(institution)
    breached = 0
    warning = 0
    for limit in db.concentration_limits.values():
        if limit["institution_id"] != institution["id"]:
            continue
        if limit["status"] != "ACTIVE":
            if limit["current_value_bps"] != 0 or limit["breach_state"] != "WITHIN":
                limit["current_value_bps"] = 0
                limit["breach_state"] = "WITHIN"
                db.touch(limit)
            continue
        value = values[limit["metric"]]
        state = _breach_state(limit, value)
        if limit["current_value_bps"] != value or limit["breach_state"] != state:
            limit["current_value_bps"] = value
            limit["breach_state"] = state
            db.touch(limit)
        if state == "BREACH":
            breached += 1
        elif state == "WARNING":
            warning += 1

    institution["breached_metric_count"] = breached
    if breached >= 1:
        institution["concentration_posture"] = "FROZEN"
    elif warning >= 1:
        institution["concentration_posture"] = "RESTRICTED"
    else:
        institution["concentration_posture"] = "OPEN"

    if any(before.get(k) != institution.get(k) for k in institution
           if not k.startswith("_") and k not in ("updated_at",)):
        db.touch(institution)


def _snapshot_values(institution):
    """Metric values computed from the live store without writing anything."""
    buckets = {"BROKERED": 0, "LISTING_SERVICE_NON_BROKERED": 0, "RECIPROCAL_EXCLUDED": 0}
    exposures = {}
    for program in programs_of(institution["id"]):
        broker_id = program.get("broker_id")
        if broker_id:
            exposures.setdefault(broker_id, 0)
        for placement in placements_of_program(program["id"]):
            if placement["funding_status"] != "ACTIVE":
                continue
            klass = placement.get("classified_as")
            if klass in buckets:
                buckets[klass] += placement["principal_cents"]
            if broker_id:
                exposures[broker_id] += placement["principal_cents"]
    total_deposits = (institution["core_deposits_cents"] + buckets["BROKERED"]
                      + buckets["LISTING_SERVICE_NON_BROKERED"]
                      + buckets["RECIPROCAL_EXCLUDED"])
    largest = max(exposures.values()) if exposures else 0
    return {
        "BROKERED_TO_TOTAL_DEPOSITS": floor_div(buckets["BROKERED"] * BPS_DENOM, total_deposits),
        "LISTING_TO_TOTAL_DEPOSITS": floor_div(
            buckets["LISTING_SERVICE_NON_BROKERED"] * BPS_DENOM, total_deposits),
        "WHOLESALE_TO_TOTAL_LIABILITIES": floor_div(
            (buckets["BROKERED"] + buckets["LISTING_SERVICE_NON_BROKERED"]) * BPS_DENOM,
            institution["total_liabilities_cents"]),
        "SINGLE_BROKER_TO_TOTAL_DEPOSITS": floor_div(largest * BPS_DENOM, total_deposits),
    }


def would_breach_on_activation(institution, placement, klass):
    """Priority 49: the value the matching metric would take AFTER this
    activation must stay strictly below the limit's breach_threshold_bps."""
    saved_status = placement["funding_status"]
    saved_class = placement.get("classified_as")
    placement["funding_status"] = "ACTIVE"
    placement["classified_as"] = klass
    try:
        values = _snapshot_values(institution)
    finally:
        placement["funding_status"] = saved_status
        placement["classified_as"] = saved_class
    for limit in active_limits(institution["id"]):
        if values[limit["metric"]] >= limit["breach_threshold_bps"]:
            return True
    return False


# --- brokered headroom (closed form) --------------------------------------
def brokered_headroom(institution):
    limit = None
    for row in active_limits(institution["id"]):
        if row["metric"] == "BROKERED_TO_TOTAL_DEPOSITS":
            limit = row
    if limit is None:
        return -1
    threshold = limit["breach_threshold_bps"]
    if threshold >= BPS_DENOM:
        return -1
    brokered = institution["brokered_deposits_cents"]
    total_deposits = institution["total_deposits_cents"]
    if brokered * BPS_DENOM >= threshold * total_deposits:
        return 0
    numerator = threshold * total_deposits - BPS_DENOM * brokered
    divisor = BPS_DENOM - threshold
    return floor_div(numerator - 1, divisor)


# --- maturity ladder ------------------------------------------------------
def maturity_window_exposure(institution, candidate_maturity_date,
                             candidate_principal_cents, exclude_ids=()):
    lower = util.add_days(candidate_maturity_date, -LADDER_WINDOW_DAYS)
    upper = util.add_days(candidate_maturity_date, LADDER_WINDOW_DAYS)
    exposure = candidate_principal_cents
    for placement in placements_of(institution["id"]):
        if placement["id"] in exclude_ids:
            continue
        if placement["funding_status"] not in ("PENDING", "ACTIVE"):
            continue
        if effective_class(placement) not in ("BROKERED", "LISTING_SERVICE_NON_BROKERED"):
            continue
        if not (lower <= placement["maturity_date"] <= upper):
            continue
        exposure += placement["principal_cents"]
    cap = floor_div(LADDER_WINDOW_CAP_BPS * institution["total_deposits_cents"], BPS_DENOM)
    return exposure, cap


# --- average-daily wholesale ratio ---------------------------------------
def average_daily(institution, period_start, period_end):
    day_count = util.day_diff(period_end, period_start) + 1
    if day_count <= 0:
        return 0, 0, 0
    daily_total = 0
    for placement in placements_of(institution["id"]):
        if placement["funding_status"] not in FUNDED_STATUSES:
            continue
        if effective_class(placement) not in ("BROKERED", "LISTING_SERVICE_NON_BROKERED"):
            continue
        start = max(placement["issue_date"], period_start)
        settlement = placement.get("settlement_date") or period_end
        end = min(period_end, settlement)
        days = util.day_diff(end, start) + 1
        if days <= 0:
            continue
        daily_total += placement["principal_cents"] * days
    avg_wholesale = floor_div(daily_total, day_count)
    ratio = floor_div(avg_wholesale * BPS_DENOM, institution["total_deposits_cents"])
    return avg_wholesale, ratio, day_count


# --- contingency stage and buffer ----------------------------------------
def stage_for(plan, ratio_bps):
    if ratio_bps >= plan["stage_3_trigger_bps"]:
        return "STAGE_3_CRISIS"
    if ratio_bps >= plan["stage_2_trigger_bps"]:
        return "STAGE_2_CONTINGENT"
    if ratio_bps >= plan["stage_1_trigger_bps"]:
        return "STAGE_1_MONITOR"
    return "NONE"


def maturing_soon_cents(institution):
    today = util.clock_date().isoformat()
    horizon = util.add_days(today, BUFFER_HORIZON_DAYS)
    total = 0
    for placement in placements_of(institution["id"]):
        if placement["funding_status"] != "ACTIVE":
            continue
        if placement.get("classified_as") not in ("BROKERED", "LISTING_SERVICE_NON_BROKERED"):
            continue
        if today <= placement["maturity_date"] <= horizon:
            total += placement["principal_cents"]
    return total


def activate_plan_figures(plan, institution):
    stage = stage_for(plan, institution["wholesale_funding_ratio_bps"])
    wall = maturing_soon_cents(institution)
    required = round_half_up(wall * STAGE_MULTIPLIER_BPS[stage], BPS_DENOM)
    shortfall = max(0, required - institution["liquidity_buffer_cents"])
    plan["activation_stage"] = stage
    plan["required_buffer_cents"] = required
    plan["buffer_shortfall_cents"] = shortfall


# --- call report variance -------------------------------------------------
def call_report_variance(filing, institution):
    filing["computed_brokered_cents"] = institution["brokered_deposits_cents"]
    filing["computed_listing_cents"] = institution["listing_service_deposits_cents"]
    filing["computed_core_cents"] = institution["core_deposits_cents"]
    variance = abs(filing["rc_e_brokered_reported_cents"] - filing["computed_brokered_cents"])
    filing["variance_cents"] = variance
    filing["variance_bps"] = floor_div(variance * BPS_DENOM,
                                       institution["total_deposits_cents"])
    if variance == 0:
        filing["accuracy_status"] = "ACCURATE"
    elif filing["variance_bps"] < VARIANCE_MATERIAL_BPS:
        filing["accuracy_status"] = "VARIANCE_MINOR"
    else:
        filing["accuracy_status"] = "VARIANCE_MATERIAL"


def examiner_lock(institution_id):
    for filing in db.call_report_filings.values():
        if (filing["institution_id"] == institution_id
                and filing["status"] == "UNDER_EXAMINER_REVIEW"):
            return True
    return False
