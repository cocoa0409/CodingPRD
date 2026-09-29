"""Every calculation in the specification, with exact rational arithmetic."""
import calendar
import datetime
from fractions import Fraction as Q

import store
from common import clock_date, clock_year, fail, rhu

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
WEIGHT_FENCED = 1
WEIGHT_LIGHTING = 1
WEIGHT_ALARM_MONITORED = 1
WEIGHT_GUARDED_24H = 2
TIER_3_MIN_SCORE = 5
TIER_2_MIN_SCORE = 3
TIER_1_MIN_SCORE = 1

ANNUAL_DEPRECIATION_BP = 800
DEPRECIATION_FLOOR_BP = 2000

VALUATION_FACTOR_BP = {
    "ACV": 10000, "REPLACEMENT_COST": 11500, "AGREED_VALUE": 12500, "STATED_AMOUNT": 10800,
}
THEFT_FACTOR_BP = {"A": 11800, "B": 11000, "C": 10400, "D": 10000}
GEO_CREDIT_BP_HIGH_HAZARD = 1500
GEO_CREDIT_BP_LOW_HAZARD = 500
SECURITY_CREDIT_BP = {"TIER_0": 0, "TIER_1": 300, "TIER_2": 700, "TIER_3": 1200}
CREDIT_CAP_BP = 2500

BLANKET_LOAD_BP = 10600
BLANKET_COINSURANCE_CREDIT_BP = 500
BLANKET_COINSURANCE_MIN_BP = 9000

EXPENSE_LOAD_BP = {
    "T1_COASTAL": 10800, "T2_URBAN": 10400, "T3_INLAND": 10200, "T4_REMOTE": 11200,
}
REFERRAL_PREMIUM_THRESHOLD_CENTS = 5000000
REFERRAL_TIV_THRESHOLD_CENTS = 50000000

TRANSIT_OWNED_RATE_BP = 65
TRANSIT_HIRED_RATE_BP = 95
CAT_TIER_2_MIN_CENTS = 65000
CAT_TIER_3_MIN_CENTS = 300000
CAT_SURCHARGE_BP = {"CAT_TIER_1": 400, "CAT_TIER_2": 900, "CAT_TIER_3": 1400}

INSTALLATION_RATE_BP = 140
INSTALLATION_SECURITY_FACTOR_BP = {
    "TIER_0": 12500, "TIER_1": 11000, "TIER_2": 10000, "TIER_3": 9500,
}
DAYS_PER_YEAR = 365

REPORTING_GRACE_DAYS = 15
LATE_REPORTING_PENALTY_BP = 1000
FULL_REPORTING_THRESHOLD_BP = 9000
CONSTRUCTIVE_TOTAL_LOSS_BP = 7500
SHORT_RATE_BP = 9000
TRANSIT_TURNAROUND_HOURS = 4

TERRITORIES = ("T1_COASTAL", "T2_URBAN", "T3_INLAND", "T4_REMOTE")
EQUIPMENT_TYPES = ("EXCAVATOR", "CRANE", "LOADER", "DOZER", "GENERATOR",
                   "COMPRESSOR", "SCAFFOLDING", "SURVEY_INSTRUMENT")
VALUATION_BASES = ("ACV", "REPLACEMENT_COST", "AGREED_VALUE", "STATED_AMOUNT")
PART_TYPES = ("SCHEDULED_EQUIPMENT", "BLANKET_EQUIPMENT", "RENTED_LEASED",
              "INSTALLATION_FLOATER", "TRANSIT", "REPORTING_FORM")
EQUIPMENT_PART_TYPES = ("SCHEDULED_EQUIPMENT", "BLANKET_EQUIPMENT",
                        "RENTED_LEASED", "REPORTING_FORM")
MUTABLE_POLICY_STATUSES = ("DRAFT", "QUOTED", "REFERRED", "BOUND", "IN_FORCE", "SUSPENDED")
ON_SCHEDULE_STATUSES = ("RATED", "ACTIVE")


# --------------------------------------------------------------------------
# jobsite_security_tier
# --------------------------------------------------------------------------
def jobsite_security_score(fenced, lighting, alarm_monitored, guarded_24h):
    return ((WEIGHT_FENCED if fenced else 0)
            + (WEIGHT_LIGHTING if lighting else 0)
            + (WEIGHT_ALARM_MONITORED if alarm_monitored else 0)
            + (WEIGHT_GUARDED_24H if guarded_24h else 0))


def jobsite_security_tier(score):
    if score >= TIER_3_MIN_SCORE:
        return "TIER_3"
    if score >= TIER_2_MIN_SCORE:
        return "TIER_2"
    if score >= TIER_1_MIN_SCORE:
        return "TIER_1"
    return "TIER_0"


# --------------------------------------------------------------------------
# rate_rule_selection
# --------------------------------------------------------------------------
def rating_territory(item, policy):
    jobsite = store.maybe(store.jobsites, item.get("assigned_jobsite_id"))
    if jobsite is not None:
        return jobsite["territory_code"]
    return policy["territory_code"]


def age_years_at_rating(model_year):
    return max(0, clock_year() - model_year)


def select_rate_rule(equipment_type, territory, age_years, required=True):
    candidates = [r for r in store.rate_rules.values()
                  if r["status"] == "PUBLISHED"
                  and r["equipment_type"] == equipment_type
                  and r["territory_code"] == territory
                  and r["age_band_min_years"] <= age_years <= r["age_band_max_years"]]
    if not candidates:
        if required:
            fail("ERR_NO_PUBLISHED_RATE_RULE",
                 "No PUBLISHED rate rule prices %s in %s at age %d"
                 % (equipment_type, territory, age_years))
        return None
    candidates = store.order(candidates)
    candidates.sort(key=lambda r: r["published_at"], reverse=True)
    return candidates[0]


# --------------------------------------------------------------------------
# equipment_insured_value / equipment_item_premium
# --------------------------------------------------------------------------
def equipment_insured_value(item, rule, age_years):
    basis = item["valuation_basis"]
    cost = item["original_cost_cents"]
    if basis == "ACV":
        depreciation_bp = age_years * ANNUAL_DEPRECIATION_BP
        retained_bp = max(DEPRECIATION_FLOOR_BP, 10000 - depreciation_bp)
        return rhu(Q(cost * retained_bp, 10000))
    if basis == "REPLACEMENT_COST":
        return rhu(Q(cost * rule["replacement_cost_index_bp"], 10000))
    if basis == "AGREED_VALUE":
        return item["stated_value_cents"]
    indexed = rhu(Q(cost * rule["replacement_cost_index_bp"], 10000))
    return min(item["stated_value_cents"], indexed)


def security_credit_for(item):
    jobsite = store.maybe(store.jobsites, item.get("assigned_jobsite_id"))
    if jobsite is None:
        return 0
    if jobsite["status"] == "RELEASED":
        # A released site is no longer treated as secured: the credit is zero.
        return 0
    return SECURITY_CREDIT_BP[jobsite["security_tier"]]


def rate_equipment_item(item, policy, required=True):
    """Return the full rating outcome for one item without mutating it."""
    territory = rating_territory(item, policy)
    age = age_years_at_rating(item["model_year"])
    rule = select_rate_rule(item["equipment_type"], territory, age, required=required)
    if rule is None:
        return None
    insured_value = equipment_insured_value(item, rule, age)
    basis = item["valuation_basis"]
    valuation_factor_bp = VALUATION_FACTOR_BP[basis]
    grade = rule["theft_hazard_grade"]
    theft_factor_bp = THEFT_FACTOR_BP[grade]
    geo_credit_bp = 0
    if item["geo_tracker_installed"]:
        geo_credit_bp = (GEO_CREDIT_BP_HIGH_HAZARD if grade in ("A", "B")
                         else GEO_CREDIT_BP_LOW_HAZARD)
    security_credit_bp = security_credit_for(item)
    applied_credit_bp = min(CREDIT_CAP_BP, geo_credit_bp + security_credit_bp)
    premium = rhu(Q(insured_value * rule["base_rate_bp"] * valuation_factor_bp
                    * theft_factor_bp * (10000 - applied_credit_bp),
                    10000 ** 4))
    return {
        "applied_rate_rule_id": rule["id"],
        "age_years_at_rating": age,
        "insured_value_cents": insured_value,
        "applied_base_rate_bp": rule["base_rate_bp"],
        "applied_credit_bp": applied_credit_bp,
        "rated_premium_cents": premium,
        "theft_hazard_grade": grade,
    }


def apply_rating(item, outcome):
    item["applied_rate_rule_id"] = outcome["applied_rate_rule_id"]
    item["age_years_at_rating"] = outcome["age_years_at_rating"]
    item["insured_value_cents"] = outcome["insured_value_cents"]
    item["applied_base_rate_bp"] = outcome["applied_base_rate_bp"]
    item["applied_credit_bp"] = outcome["applied_credit_bp"]
    item["rated_premium_cents"] = outcome["rated_premium_cents"]
    store.touch(item)


# --------------------------------------------------------------------------
# Date helpers
# --------------------------------------------------------------------------
def days_between(a, b):
    return (b - a).days


def add_months(d, n):
    total = d.month - 1 + n
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def policy_term_days(policy):
    return days_between(policy["effective_date"], policy["expiration_date"])


# --------------------------------------------------------------------------
# coverage_part_equipment_premium
# --------------------------------------------------------------------------
def schedule_items(part):
    return [i for i in store.items_of_part(part["id"])
            if i["status"] in ON_SCHEDULE_STATUSES]


def blanket_variant_premium(part, items):
    if part.get("blanket_limit_cents") is None:
        return 0
    total_iv = sum(i["insured_value_cents"] or 0 for i in items)
    if total_iv == 0:
        weighted_rate_bp = 0
    else:
        weighted_rate_bp = rhu(Q(sum((i["insured_value_cents"] or 0)
                                     * (i["applied_base_rate_bp"] or 0) for i in items),
                                 total_iv))
    coins = part.get("coinsurance_pct_bp")
    coins_credit_bp = (BLANKET_COINSURANCE_CREDIT_BP
                       if coins is not None and coins >= BLANKET_COINSURANCE_MIN_BP else 0)
    return rhu(Q(part["blanket_limit_cents"] * weighted_rate_bp
                 * VALUATION_FACTOR_BP[part["valuation_basis"]] * BLANKET_LOAD_BP
                 * (10000 - coins_credit_bp),
                 10000 ** 4))


# --------------------------------------------------------------------------
# transit_coverage_premium / transit_applicable_limit
# --------------------------------------------------------------------------
def transit_coverage_premium(part):
    owned_limit = part.get("transit_owned_limit_cents") or 0
    hired_limit = part.get("transit_hired_limit_cents") or 0
    cat_limit = part.get("catastrophe_limit_cents") or 0
    owned_component = rhu(Q(owned_limit * TRANSIT_OWNED_RATE_BP, 10000))
    hired_component = rhu(Q(hired_limit * TRANSIT_HIRED_RATE_BP, 10000))
    base = owned_component + hired_component
    if base < CAT_TIER_2_MIN_CENTS:
        tier = "CAT_TIER_1"
    elif base < CAT_TIER_3_MIN_CENTS:
        tier = "CAT_TIER_2"
    else:
        tier = "CAT_TIER_3"
    surcharge = rhu(Q(cat_limit * CAT_SURCHARGE_BP[tier], 10000))
    return base + surcharge


def transit_applicable_limit(part, vehicle, origin, destination):
    catastrophe_zone = (origin == "T1_COASTAL") or (destination == "T1_COASTAL")
    if vehicle["ownership"] == "OWNED":
        conveyance_limit = part.get("transit_owned_limit_cents")
    else:
        conveyance_limit = part.get("transit_hired_limit_cents")
    candidates = [conveyance_limit, vehicle["per_conveyance_limit_cents"]]
    if catastrophe_zone:
        candidates.append(part.get("catastrophe_limit_cents"))
    else:
        candidates.append(conveyance_limit)
    usable = [c for c in candidates if c is not None]
    limit = min(usable) if usable else None
    return catastrophe_zone, limit


# --------------------------------------------------------------------------
# installation floater premium / termination
# --------------------------------------------------------------------------
def installation_floater_premium(installed_value_limit_cents, security_tier, term_days):
    return rhu(Q(installed_value_limit_cents * INSTALLATION_RATE_BP
                 * INSTALLATION_SECURITY_FACTOR_BP[security_tier] * term_days,
                 10000 * 10000 * DAYS_PER_YEAR))


def floater_term_days(start, end):
    return days_between(start, end) + 1


def apply_floater_termination(floater, trigger, termination_date):
    rated = floater["rated_premium_cents"]
    term_days = floater["term_days"]
    elapsed_days = days_between(floater["coverage_start_date"], termination_date) + 1
    if trigger == "ACCEPTANCE":
        earned = rhu(Q(rated * elapsed_days, term_days))
        unearned = rated - earned
    elif trigger == "OCCUPANCY":
        earned, unearned = rated, 0
    elif trigger == "EXPIRY":
        earned, unearned = rated, 0
    else:  # CANCELLATION
        earned = rhu(Q(rated * elapsed_days, term_days))
        unearned = 0
    floater["earned_premium_cents"] = earned
    floater["unearned_return_cents"] = unearned
    floater["termination_trigger"] = trigger
    floater["termination_date"] = termination_date
    return earned, unearned


def coverage_part_floater_premium(part):
    return sum(f["rated_premium_cents"] - f["unearned_return_cents"]
               for f in store.floaters_of_part(part["id"]))


# --------------------------------------------------------------------------
# Part / policy roll-ups
# --------------------------------------------------------------------------
def part_variants(part):
    part_type = part["part_type"]
    if part_type in EQUIPMENT_PART_TYPES:
        items = schedule_items(part)
        scheduled = sum(i["rated_premium_cents"] or 0 for i in items)
        blanket = blanket_variant_premium(part, items)
        return scheduled, blanket
    if part_type == "TRANSIT":
        value = transit_coverage_premium(part)
        return value, value
    if part_type == "INSTALLATION_FLOATER":
        value = coverage_part_floater_premium(part)
        return value, value
    return 0, 0


def charged_variant(part, scheduled, blanket):
    if (part["part_type"] in ("SCHEDULED_EQUIPMENT", "BLANKET_EQUIPMENT")
            and part["rating_basis"] == "BLANKET"):
        return blanket
    return scheduled


def recompute_part(part):
    scheduled, blanket = part_variants(part)
    part["_scheduled_variant_cents"] = scheduled
    part["_blanket_variant_cents"] = blanket
    part["rated_premium_cents"] = charged_variant(part, scheduled, blanket)
    store.touch(part)
    return part["rated_premium_cents"]


def policy_total_insured_value(policy):
    total = 0
    for part in store.parts_of_policy(policy["id"]):
        for item in store.items_of_part(part["id"]):
            if item["status"] in ON_SCHEDULE_STATUSES:
                total += item["insured_value_cents"] or 0
    return total


def policy_rollup(policy):
    """Pure derivation of the premium roll-up; does not mutate the policy."""
    active = [p for p in store.parts_of_policy(policy["id"]) if p["status"] == "ACTIVE"]
    load_bp = EXPENSE_LOAD_BP[policy["territory_code"]]
    minimum = policy["minimum_premium_cents"]
    sum_parts = sum(p["rated_premium_cents"] or 0 for p in active)
    loaded = rhu(Q(sum_parts * load_bp, 10000))
    written = max(loaded, minimum)
    sched_sum = sum(p.get("_scheduled_variant_cents") or 0 for p in active)
    blanket_sum = sum(p.get("_blanket_variant_cents") or 0 for p in active)
    scheduled_basis = max(minimum, rhu(Q(sched_sum * load_bp, 10000)))
    blanket_basis = max(minimum, rhu(Q(blanket_sum * load_bp, 10000)))
    tiv = policy_total_insured_value(policy)
    return {
        "sum_of_part_premiums_cents": sum_parts,
        "expense_load_bp": load_bp,
        "loaded_cents": loaded,
        "written_premium_cents": written,
        "scheduled_basis_premium_cents": scheduled_basis,
        "blanket_basis_premium_cents": blanket_basis,
        "minimum_premium_applied": loaded < minimum,
        "total_insured_value_cents": tiv,
        "referral_required": (written >= REFERRAL_PREMIUM_THRESHOLD_CENTS
                              or tiv > REFERRAL_TIV_THRESHOLD_CENTS),
    }


def reroll_policy(policy):
    roll = policy_rollup(policy)
    for key in ("sum_of_part_premiums_cents", "written_premium_cents",
                "scheduled_basis_premium_cents", "blanket_basis_premium_cents",
                "total_insured_value_cents", "referral_required"):
        policy[key] = roll[key]
    store.touch(policy)
    return roll


# --------------------------------------------------------------------------
# Reporting form
# --------------------------------------------------------------------------
def reporting_due_date(period_end_date):
    return period_end_date + datetime.timedelta(days=REPORTING_GRACE_DAYS)


def reporting_period_days(period_start_date, period_end_date):
    return days_between(period_start_date, period_end_date) + 1


def reporting_period_earned_premium(reported_value_cents, annual_rate_bp, period_days):
    return rhu(Q(reported_value_cents * annual_rate_bp * period_days,
                 10000 * DAYS_PER_YEAR))


def reporting_late_penalty(period_earned_premium_cents):
    return rhu(Q(period_earned_premium_cents * LATE_REPORTING_PENALTY_BP, 10000))


def reporting_periods(policy, frequency):
    """The canonical tiling of the policy term, forward from effective_date."""
    step = 1 if frequency == "MONTHLY" else 3
    periods = []
    start = policy["effective_date"]
    expiration = policy["expiration_date"]
    guard = 0
    while start < expiration and guard < 4000:
        nxt = add_months(start, step)
        end = nxt - datetime.timedelta(days=1)
        if end > expiration:
            end = expiration
        periods.append((start, end))
        if nxt <= start:
            break
        start = nxt
        guard += 1
    return periods


def underreporting_penalty_factor(claim, part):
    if part["part_type"] != "REPORTING_FORM":
        return 10000
    loss_date = claim["loss_date"]
    governing = None
    for report in store.reports_of_part(part["id"]):
        if report["status"] not in ("ACCEPTED", "PENALIZED"):
            continue
        if report["period_start_date"] <= loss_date <= report["period_end_date"]:
            governing = report
    if governing is None:
        return 10000
    actual = claim.get("actual_value_at_loss_cents")
    if not actual:
        return 10000
    ratio_bp = rhu(Q(governing["reported_value_cents"] * 10000, actual))
    return 10000 if ratio_bp >= FULL_REPORTING_THRESHOLD_BP else ratio_bp


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
def claim_subject(claim):
    if claim.get("equipment_item_id"):
        return "equipment_item", store.equipment_items.get(claim["equipment_item_id"])
    if claim.get("transit_shipment_id"):
        return "transit_shipment", store.transit_shipments.get(claim["transit_shipment_id"])
    if claim.get("installation_floater_id"):
        return "installation_floater", store.installation_floaters.get(
            claim["installation_floater_id"])
    return None, None


def claim_valuation_at_loss(claim):
    kind, subject = claim_subject(claim)
    if kind == "equipment_item":
        return subject["insured_value_cents"]
    if kind == "transit_shipment":
        return subject["declared_value_cents"]
    if kind == "installation_floater":
        return subject["installed_value_limit_cents"]
    # A reporting-form claim names no subject: the reported actual value stands in.
    return claim.get("actual_value_at_loss_cents")


def constructive_total_loss_threshold(valuation_at_loss_cents):
    if valuation_at_loss_cents is None:
        return None
    return rhu(Q(valuation_at_loss_cents * CONSTRUCTIVE_TOTAL_LOSS_BP, 10000))


def claim_limit(claim, part):
    part_type = part["part_type"]
    if part_type in ("SCHEDULED_EQUIPMENT", "RENTED_LEASED"):
        return part.get("per_item_limit_cents")
    if part_type == "BLANKET_EQUIPMENT":
        return part.get("blanket_limit_cents")
    if part_type == "REPORTING_FORM":
        return part.get("reporting_limit_cents")
    if part_type == "TRANSIT":
        shipment = store.transit_shipments.get(claim.get("transit_shipment_id"))
        return shipment["applicable_limit_cents"] if shipment else None
    floater = store.installation_floaters.get(claim.get("installation_floater_id"))
    return floater["installed_value_limit_cents"] if floater else None


def loss_of_use_eligible(claim, part):
    if part["part_type"] != "RENTED_LEASED":
        return False
    kind, subject = claim_subject(claim)
    if kind != "equipment_item" or subject is None:
        return False
    return subject["ownership"] in ("RENTED", "LEASED")


def loss_of_use_paid(claim, part):
    if not loss_of_use_eligible(claim, part):
        return 0
    days_claimed = claim.get("loss_of_use_days_claimed") or 0
    max_days = part.get("loss_of_use_max_days")
    payable_days = days_claimed if max_days is None else min(days_claimed, max_days)
    daily = part.get("loss_of_use_daily_limit_cents") or 0
    return payable_days * daily


def _cap(gross, limit):
    return gross if limit is None else min(gross, limit)


def claim_settlement_variants(claim, part, valuation, factor_bp, limit, lou_paid):
    deductible = part.get("deductible_cents") or 0
    repair_estimate = claim.get("repair_estimate_cents")
    repair = None
    if repair_estimate is not None:
        repair_loss = _cap(rhu(Q(repair_estimate * factor_bp, 10000)), limit)
        repair = max(0, repair_loss - deductible) + lou_paid
    total = None
    if valuation is not None:
        total_loss = _cap(rhu(Q(valuation * factor_bp, 10000)), limit)
        total = max(0, total_loss - deductible)
    return repair, total


# --------------------------------------------------------------------------
# Endorsements and cancellation
# --------------------------------------------------------------------------
def endorsement_prorated_amount(policy, base_premium_cents):
    remaining_days = days_between(clock_date(), policy["expiration_date"])
    if remaining_days <= 0:
        return 0
    term_days = policy_term_days(policy)
    if term_days <= 0:
        return 0
    return rhu(Q(base_premium_cents * remaining_days, term_days))


def policy_cancellation_return(policy, cancel_effective_date, reason):
    unearned_days = days_between(cancel_effective_date, policy["expiration_date"])
    term_days = policy_term_days(policy)
    if term_days <= 0:
        pro_rata = 0
    else:
        pro_rata = rhu(Q(policy["written_premium_cents"] * unearned_days, term_days))
    if reason == "INSURED_REQUEST":
        return rhu(Q(pro_rata * SHORT_RATE_BP, 10000))
    return pro_rata
