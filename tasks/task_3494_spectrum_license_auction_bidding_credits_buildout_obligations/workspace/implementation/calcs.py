"""Calculation rules and constants (SCAFFOLD §1.3, PRD §3). All money is
integer cents; all eligibility/activity values are integer MHz-pop units;
comparisons use integer cross-multiplication; round-half-up is the only
rounding mode and is applied exactly where the rules say."""
import store

# --- constants ----------------------------------------------------------------
UPFRONT_CENTS_PER_ELIGIBILITY_UNIT = 2500

ATTRIBUTABLE_STAKE_PCT = 25            # strictly greater; == 25 not attributable
SMALL_BIZ_TIER1_MAX_REVENUE_CENTS = 400000000
SMALL_BIZ_TIER1_CREDIT_PCT = 35
SMALL_BIZ_TIER2_MAX_REVENUE_CENTS = 2000000000
SMALL_BIZ_TIER2_CREDIT_PCT = 25
SMALL_BIZ_TIER3_MAX_REVENUE_CENTS = 5500000000
SMALL_BIZ_TIER3_CREDIT_PCT = 15
RURAL_SERVICE_POPULATION_CAP = 250000
RURAL_CREDIT_PCT = 15

CLOCK_INCREMENT_TIER1_NUM, CLOCK_INCREMENT_TIER1_DEN = 3, 2   # d/s >= 1.5 -> 15%
CLOCK_INCREMENT_TIER1_PCT = 15
CLOCK_INCREMENT_TIER2_NUM, CLOCK_INCREMENT_TIER2_DEN = 6, 5   # d/s >= 1.2 -> 10%
CLOCK_INCREMENT_TIER2_PCT = 10
CLOCK_INCREMENT_TIER3_NUM, CLOCK_INCREMENT_TIER3_DEN = 1, 1   # d/s >= 1.0 -> 5%
CLOCK_INCREMENT_TIER3_PCT = 5

STAGE1_ACTIVITY_MILLI = 800
STAGE2_ACTIVITY_MILLI = 950
STAGE2_START_ROUND = 4          # stage 1 when round_number < 4 else 2

PAYMENT_DEADLINE_DAYS = 30
LICENSE_TERM_DAYS = 3650
RENEWAL_WINDOW_DAYS = 365
RENEWAL_EXTENSION_DAYS = 3650
INCUMBENT_TRANSITION_BUFFER_DAYS = 30

UNJUST_ENRICHMENT_DAYS_PER_YEAR = 365
UNJUST_ENRICHMENT_PERIOD_YEARS = 5
UNJUST_ENRICHMENT_SCHEDULE = {0: 100, 1: 80, 2: 60, 3: 40, 4: 20, 5: 0}

INTERIM_COVERAGE_PCT = 40
FINAL_COVERAGE_PCT = 70
INTERIM_MILESTONE_DAYS = 1095
FINAL_MILESTONE_DAYS = 2190
INTERIM_MISS_ACCELERATION_DAYS = 365


def round_half_up_ratio(num, den):
    """round_half_up(num / den) for non-negative integers, exact integer math."""
    return (num * 2 + den) // (2 * den)


def pct_of(amount_cents, pct):
    """round_half_up(amount_cents * pct / 100)."""
    return round_half_up_ratio(amount_cents * pct, 100)


# --- product helpers -----------------------------------------------------------
def areas_of_plan(plan_id):
    return [a for a in store.DB["areas"].values() if a["band_plan_id"] == plan_id]


def blocks_of_plan(plan_id):
    return [b for b in store.DB["blocks"].values() if b["band_plan_id"] == plan_id]


def find_area_by_code(plan_id, area_code):
    for a in store.DB["areas"].values():
        if a["band_plan_id"] == plan_id and a["area_code"] == area_code:
            return a
    return None


def find_block_by_category(plan_id, category):
    for b in store.DB["blocks"].values():
        if b["band_plan_id"] == plan_id and b["category"] == category:
            return b
    return None


def products_of_plan(plan_id):
    """Every (area, block) product of the plan, in deterministic creation
    order (area created_at ASC, then block created_at ASC)."""
    products = []
    for area in sorted(areas_of_plan(plan_id), key=store.created_key):
        for block in sorted(blocks_of_plan(plan_id), key=store.created_key):
            products.append((area, block))
    return products


def bidding_units(block, area):
    return block["mhz_size"] * area["population"]


def opening_price(block, area):
    return block["mhz_size"] * area["population"] * block["price_per_mhz_pop_cents"]


# --- qualification (PRD §3.3) ---------------------------------------------------
def ownership_total(interests):
    return sum(oi["stake_pct"] for oi in interests)


def compute_attributable_revenue(appl):
    total = appl["own_annual_revenue_cents"]
    for oi in appl["ownership_interests"]:
        if oi["stake_pct"] > ATTRIBUTABLE_STAKE_PCT:
            total += oi["holder_annual_revenue_cents"]
    return total


def compute_credit_pct(appl, attributable_revenue_cents):
    if appl["claims_small_business"]:
        if attributable_revenue_cents <= SMALL_BIZ_TIER1_MAX_REVENUE_CENTS:
            return SMALL_BIZ_TIER1_CREDIT_PCT
        if attributable_revenue_cents <= SMALL_BIZ_TIER2_MAX_REVENUE_CENTS:
            return SMALL_BIZ_TIER2_CREDIT_PCT
        if attributable_revenue_cents <= SMALL_BIZ_TIER3_MAX_REVENUE_CENTS:
            return SMALL_BIZ_TIER3_CREDIT_PCT
        return 0
    if appl["claims_rural_credit"]:
        if appl["service_population"] <= RURAL_SERVICE_POPULATION_CAP:
            return RURAL_CREDIT_PCT
        return 0
    return 0


def eligibility_for(held_cents):
    return held_cents // UPFRONT_CENTS_PER_ELIGIBILITY_UNIT


# --- clock price increment (PRD §3.5) -------------------------------------------
def increment_pct(demand, supply):
    """Tiered increment; boundaries inclusive on the lower side. Returns the
    percentage, or None when the product closes (demand < supply)."""
    if demand * CLOCK_INCREMENT_TIER1_DEN >= CLOCK_INCREMENT_TIER1_NUM * supply:
        return CLOCK_INCREMENT_TIER1_PCT
    if demand * CLOCK_INCREMENT_TIER2_DEN >= CLOCK_INCREMENT_TIER2_NUM * supply:
        return CLOCK_INCREMENT_TIER2_PCT
    if demand * CLOCK_INCREMENT_TIER3_DEN >= CLOCK_INCREMENT_TIER3_NUM * supply:
        return CLOCK_INCREMENT_TIER3_PCT
    return None


def stage_of(round_number):
    return 1 if round_number < STAGE2_START_ROUND else 2


# --- settlement pricing (PRD §3.6) ----------------------------------------------
def settlement_fields(gross_clock_price_cents, assignment_bid_cents, credit_pct):
    gross_final = gross_clock_price_cents + assignment_bid_cents
    provisional_net = pct_of(gross_clock_price_cents, 100 - credit_pct)
    net = pct_of(gross_final, 100 - credit_pct)
    credit_amount = gross_final - net
    return {
        "gross_final_price_cents": gross_final,
        "provisional_net_price_cents": provisional_net,
        "net_price_cents": net,
        "credit_amount_cents": credit_amount,
    }


# --- unjust enrichment (PRD §3.9) -----------------------------------------------
def unjust_enrichment(license_, transferee, now):
    credit_amount = license_["credit_amount_cents"]
    if credit_amount == 0:
        return 0
    delta_days = (now - license_["grant_date"]).days
    if delta_days < 0:
        delta_days = 0
    years = delta_days // UNJUST_ENRICHMENT_DAYS_PER_YEAR
    if transferee["credit_pct"] < license_["credit_pct"]:
        schedule_pct = 100
    else:
        schedule_pct = UNJUST_ENRICHMENT_SCHEDULE[
            min(years, UNJUST_ENRICHMENT_PERIOD_YEARS)]
    return pct_of(credit_amount, schedule_pct)


# --- relocation cost shares (PRD §3.7) -------------------------------------------
def relocation_shares(licenses, cost_cents):
    """licenses: ACTIVE licenses of the area. Returns (shares_proportional,
    shares_equal), each a list of {license_id, amount_cents} ordered by units
    DESC, tie-break License.created_at ASC (creation sequence breaks exact
    ties, never id). Remainder cents go one at a time in that order."""
    if not licenses:
        return [], []

    def units_of(lic):
        return lic["_units"]

    ordered = sorted(
        licenses,
        key=lambda l: (-units_of(l), l["created_at"], l["_seq"]))
    n = len(ordered)
    total_units = sum(units_of(l) for l in ordered)

    prop_base = [(cost_cents * units_of(l)) // total_units for l in ordered]
    prop_remainder = cost_cents - sum(prop_base)
    equal_base = [cost_cents // n for _ in ordered]
    equal_remainder = cost_cents - cost_cents // n * n

    prop, equal = [], []
    for i, lic in enumerate(ordered):
        p = prop_base[i] + (1 if i < prop_remainder else 0)
        q = equal_base[i] + (1 if i < equal_remainder else 0)
        prop.append({"license_id": lic["id"], "amount_cents": p})
        equal.append({"license_id": lic["id"], "amount_cents": q})
    return prop, equal
