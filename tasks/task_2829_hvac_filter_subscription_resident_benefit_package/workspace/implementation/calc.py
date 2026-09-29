"""Every pinned calculation of PRD 3.3 - 3.9. All money arithmetic is exact
rational until the rounding the specification names."""
from fractions import Fraction

import clock
from errors import fail
from money import round_half_up
from store import db, sorted_rows

# ---- sku_selection --------------------------------------------------------
REQUIRED_MIN_MERV_BASE = 8
REQUIRED_MIN_MERV_ALLERGY = 11
PACK_SLACK_PACKS = 2

# ---- ship_cadence_days ----------------------------------------------------
BASE_CADENCE_BY_SYSTEM = {
    "SINGLE_STAGE": 90,
    "TWO_STAGE": 75,
    "VARIABLE_SPEED": 60,
    "HEAT_PUMP": 60,
}
LOAD_PENALTY_DAYS_PER_POINT = 10
CADENCE_FLOOR_DAYS = 30
CADENCE_CEILING_DAYS = 120
CADENCE_GRID_DAYS = 15

# ---- benefit set / pricing ------------------------------------------------
TIER_CODES = {
    "BASIC": ["CREDIT_REPORTING"],
    "PLUS": ["CREDIT_REPORTING", "RENTERS_INSURANCE"],
    "PREMIUM": ["CREDIT_REPORTING", "RENTERS_INSURANCE", "AIR_QUALITY_GUARANTEE"],
}
BENEFIT_ANNUAL_CENTS = {
    "CREDIT_REPORTING": 3600,
    "RENTERS_INSURANCE": 15600,
    "DAMAGE_WAIVER": 7200,
    "AIR_QUALITY_GUARANTEE": 4800,
}
MARKUP_PCT = Fraction(35, 100)
SHIP_HANDLING_CENTS = 495
WEIGHT_FREE_OZ = 32
WEIGHT_SURCHARGE_CENTS_PER_OZ = 6
DAYS_PER_YEAR = 365
ENROLLMENT_FEE_CENTS = 2500

# ---- evidence scoring -----------------------------------------------------
RUNTIME_EXPECTED_MINUTES_PER_DAY = 480
PRESSURE_DRIFT_SATURATION_PCT = Fraction(25, 100)
PRESSURE_WEIGHT = Fraction(6, 10)
RUNTIME_WEIGHT = Fraction(4, 10)
SUSPECT_THRESHOLD = {"RUNTIME_ANALYTICS": 40, "RENEWAL_SURVEY": 55}
CONFIRM_THRESHOLD = {"RUNTIME_ANALYTICS": 60, "RENEWAL_SURVEY": 80}
SURVEY_NOT_INSTALLED_POINTS = 70
SURVEY_EXCESS_POINTS_PER_FILTER = 10
SURVEY_EXCESS_POINTS_MAX_FILTERS = 3
SURVEY_STALE_CHANGE_POINTS = 15
SURVEY_STALE_CHANGE_MULTIPLIER = 2
REMEDIATION_GRACE_DAYS = 21

# ---- claims ---------------------------------------------------------------
DAMAGE_WAIVER_DEDUCTIBLE_CENTS = 5000
DAMAGE_WAIVER_PER_INCIDENT_CAP_CENTS = 30000
AQG_MONTHS_CAP = 12
AQG_DAYS_PER_MONTH = 30
NON_INSTALL_HAIRCUT_PCT = Fraction(1, 2)
CLAIM_HARD_CAP_CENTS = 100000
CLAIM_FILING_WINDOW_DAYS = 60
MAX_INFO_REQUEST_ROUNDS = 2

# ---- fulfilment / settlement ---------------------------------------------
UNRETURNED_FEE_CAP_CENTS = 2500
TURNOVER_BUFFER_DAYS = 3
WAIVER_CREDIT_TIERS = [(10000, Fraction(75, 100)), (5000, Fraction(50, 100)),
                       (1000, Fraction(25, 100)), (0, Fraction(0, 1))]

DELIVERED_STATUSES = ("DELIVERED", "RETURN_REQUESTED", "RETURNED",
                      "UNRETURNED_WRITTEN_OFF")
LIVE_SUBSCRIPTION_STATUSES = ("PENDING_SETUP", "ACTIVE", "SUSPENDED",
                              "TRANSFER_PENDING")


def effective_size_code(unit):
    return unit["actual_measured_size_code"] or unit["nominal_size_code"]


def select_sku(unit, resident):
    """PRD 3.3 selector. Ranked merv ASC, unit_cost_cents ASC, created_at ASC;
    the SKU id is never consulted."""
    target_size = effective_size_code(unit)
    floor_merv = (REQUIRED_MIN_MERV_ALLERGY if resident["allergy_flag"]
                  else REQUIRED_MIN_MERV_BASE)
    slack = unit["filter_slot_count"] + PACK_SLACK_PACKS
    candidates = [s for s in db.skus.values()
                  if s["status"] == "ACTIVE"
                  and s["size_code"] == target_size
                  and s["merv_rating"] >= floor_merv
                  and s["pack_quantity"] <= slack]
    if not candidates:
        fail("ERR_NO_ELIGIBLE_SKU")
    candidates.sort(key=lambda s: (s["merv_rating"], s["unit_cost_cents"],
                                   s["created_at"], s["_seq"]))
    return candidates[0]


def ship_cadence_days(unit, sku, resident):
    base = BASE_CADENCE_BY_SYSTEM[unit["hvac_system_type"]]
    thickness = sku["thickness_inches"]
    bonus = 30 if thickness >= 4 else (15 if thickness >= 2 else 0)
    points = 0
    if resident["household_size"] >= 4:
        points += 1
    if resident["household_size"] >= 6:
        points += 1
    if resident["has_pets"]:
        points += 2
    if resident["smoker"]:
        points += 1
    if resident["allergy_flag"]:
        points += 1
    raw = base + bonus - LOAD_PENALTY_DAYS_PER_POINT * points
    clamped = max(CADENCE_FLOOR_DAYS, min(CADENCE_CEILING_DAYS, raw))
    snapped = CADENCE_GRID_DAYS * (clamped // CADENCE_GRID_DAYS)
    return max(CADENCE_FLOOR_DAYS, snapped)


def filters_per_shipment(unit, sku):
    pack = sku["pack_quantity"]
    slots = unit["filter_slot_count"]
    packs = -(-slots // pack)
    return packs * pack


def benefit_codes(prop, billing_party, posture):
    codes = set(TIER_CODES[prop["benefit_tier"]])
    if prop["damage_waiver_enabled"]:
        codes.add("DAMAGE_WAIVER")
    if prop["aqg_enabled"]:
        codes.add("AIR_QUALITY_GUARANTEE")
    if billing_party == "RESIDENT" and prop["billing_mode"] == "PM_BILLED":
        codes.discard("RENTERS_INSURANCE")
    if posture == "NON_INSTALL_CONFIRMED":
        codes.discard("DAMAGE_WAIVER")
        codes.discard("AIR_QUALITY_GUARANTEE")
    return sorted(codes)


def monthly_fee_cents(sku, quantity, cadence_days, codes):
    """Three annual components, each divided by twelve and rounded on its own,
    then added with plain integer addition."""
    shipments_per_year = Fraction(DAYS_PER_YEAR, cadence_days)
    per_ship_weight = sku["ship_weight_oz"] * quantity
    surcharge = max(0, per_ship_weight - WEIGHT_FREE_OZ) * WEIGHT_SURCHARGE_CENTS_PER_OZ
    annual_filter = (Fraction(sku["unit_cost_cents"] * quantity)
                     * shipments_per_year * (1 + MARKUP_PCT))
    annual_logistics = Fraction(SHIP_HANDLING_CENTS + surcharge) * shipments_per_year
    annual_benefit = Fraction(sum(BENEFIT_ANNUAL_CENTS[c] for c in codes))
    m_filter = round_half_up(annual_filter / 12)
    m_logistics = round_half_up(annual_logistics / 12)
    m_benefit = round_half_up(annual_benefit / 12)
    return m_filter + m_logistics + m_benefit


def first_month_fee_cents(monthly, on_date):
    days_in_period = clock.days_in_month(on_date)
    billable = days_in_period - on_date.day + 1
    return round_half_up(Fraction(monthly * billable, days_in_period))


# --------------------------------------------------------------------------
# reverse-lookup helpers
# --------------------------------------------------------------------------
def shipments_of(subscription_id):
    return sorted_rows([s for s in db.shipments.values()
                        if s["subscription_id"] == subscription_id])


def surveys_of(subscription_id):
    return sorted_rows([s for s in db.surveys.values()
                        if s["subscription_id"] == subscription_id])


def readings_of(unit_id):
    return sorted_rows([r for r in db.readings.values() if r["unit_id"] == unit_id])


def entitlements_of(subscription_id):
    return sorted_rows([e for e in db.entitlements.values()
                        if e["subscription_id"] == subscription_id])


def ledger_of(subscription_id):
    rows = [le for le in db.ledger.values()
            if le["subscription_id"] == subscription_id]
    return sorted(rows, key=lambda r: (r["created_at"], r["period_start"], r["_seq"]))


def subscriptions_of_unit(unit_id):
    return sorted_rows([s for s in db.subscriptions.values()
                        if s["unit_id"] == unit_id])


def subscriptions_of_property(property_id):
    return sorted_rows([s for s in db.subscriptions.values()
                        if s["property_id"] == property_id])


def cases_of(subscription_id):
    return sorted_rows([c for c in db.cases.values()
                        if c["subscription_id"] == subscription_id])


def units_of(property_id):
    return sorted_rows([u for u in db.units.values()
                        if u["property_id"] == property_id])


def unit_count(property_id):
    return len([u for u in db.units.values()
                if u["property_id"] == property_id
                and u["status"] in ("AVAILABLE", "OCCUPIED")])


def next_ship_date(subscription_id):
    live = [s for s in shipments_of(subscription_id)
            if s["status"] in ("SCHEDULED", "SHIPPED")]
    if not live:
        return None
    live.sort(key=lambda s: (s["scheduled_ship_date"], s["created_at"], s["_seq"]))
    return live[-1]["scheduled_ship_date"]


# --------------------------------------------------------------------------
# pricing chain
# --------------------------------------------------------------------------
def derive_pricing(unit, resident, prop, billing_party, posture):
    """The full chain of PRD 3.3 in the pinned order: SKU selection, cadence,
    filters per shipment, benefit set, monthly fee."""
    sku = select_sku(unit, resident)
    cadence = ship_cadence_days(unit, sku, resident)
    quantity = filters_per_shipment(unit, sku)
    codes = benefit_codes(prop, billing_party, posture)
    fee = monthly_fee_cents(sku, quantity, cadence, codes)
    return {
        "assigned_sku_id": sku["id"],
        "ship_cadence_days": cadence,
        "filters_per_shipment": quantity,
        "entitled_benefit_codes": codes,
        "monthly_fee_cents": fee,
    }


def reprice_without_benefit_change(unit, resident, sub):
    """Filter-size capture re-derivation: SKU, cadence, filters per shipment and
    then the monthly fee, leaving the entitled benefit set untouched."""
    sku = select_sku(unit, resident)
    cadence = ship_cadence_days(unit, sku, resident)
    quantity = filters_per_shipment(unit, sku)
    fee = monthly_fee_cents(sku, quantity, cadence, sub["entitled_benefit_codes"])
    return {
        "assigned_sku_id": sku["id"],
        "ship_cadence_days": cadence,
        "filters_per_shipment": quantity,
        "monthly_fee_cents": fee,
    }


def recompute_fee(sub):
    sku = db.skus[sub["assigned_sku_id"]]
    return monthly_fee_cents(sku, sub["filters_per_shipment"],
                             sub["ship_cadence_days"], sub["entitled_benefit_codes"])


# --------------------------------------------------------------------------
# occupancy conflict (PRD 3.3, reused by transfer opening)
# --------------------------------------------------------------------------
def occupancy_conflict(unit_id, start, end, ignore_subscription_ids=()):
    """Closed intervals on both ends plus a mandatory three-day turnover buffer.
    A gap of exactly three days still conflicts."""
    for sub in subscriptions_of_unit(unit_id):
        if sub["id"] in ignore_subscription_ids:
            continue
        if sub["status"] not in LIVE_SUBSCRIPTION_STATUSES:
            continue
        other_start = clock.parse_date(sub["lease_start_date"])
        other_end = clock.parse_date(sub["lease_end_date"])
        legal = ((start - other_end).days > TURNOVER_BUFFER_DAYS
                 or (other_start - end).days > TURNOVER_BUFFER_DAYS)
        if not legal:
            return True
    return False


# --------------------------------------------------------------------------
# fees and settlements
# --------------------------------------------------------------------------
def unreturned_shipment_fee(shipment):
    sku = db.skus[shipment["sku_id"]]
    return min(sku["unit_cost_cents"] * shipment["quantity"], UNRETURNED_FEE_CAP_CENTS)


def waiver_credit_pct(gross):
    for threshold, pct in WAIVER_CREDIT_TIERS:
        if gross >= threshold:
            return pct
    return Fraction(0, 1)


def pct_string(pct):
    return "%.2f" % (float(pct),)


def cancellation_settlement(sub, effective_date):
    """The five-step waterfall of PRD 3.9. Exactly two roundings: step 1 and
    step 4. The relief tier is keyed only on step 1's output."""
    days_in_period = clock.days_in_month(effective_date)
    used_days = effective_date.day - 1
    unused_days = days_in_period - used_days
    gross_credit = round_half_up(
        Fraction(sub["monthly_fee_cents"] * unused_days, days_in_period))
    exposed = [sh for sh in shipments_of(sub["id"])
               if sh["status"] in ("SHIPPED", "DELIVERED", "RETURN_REQUESTED")]
    gross_fee = sum(unreturned_shipment_fee(sh) for sh in exposed)
    pct = waiver_credit_pct(gross_credit)
    net_fee = round_half_up(Fraction(gross_fee) * (1 - pct))
    return {
        "period_start": clock.fmt_date(clock.first_of_month(effective_date)),
        "period_end": clock.fmt_date(clock.last_of_month(effective_date)),
        "used_days": used_days,
        "unused_days": unused_days,
        "gross_prorated_credit_cents": gross_credit,
        "exposed_shipment_count": len(exposed),
        "unreturned_fee_gross_cents": gross_fee,
        "waiver_credit_pct": pct,
        "unreturned_fee_net_cents": net_fee,
        "net_settlement_cents": gross_credit - net_fee,
    }


def transfer_proration(outgoing_fee, successor_fee, effective_date):
    days_in_period = clock.days_in_month(effective_date)
    remaining_days = days_in_period - (effective_date.day - 1)
    credit = round_half_up(Fraction(outgoing_fee * remaining_days, days_in_period))
    charge = round_half_up(Fraction(successor_fee * remaining_days, days_in_period))
    return {
        "proration_credit_cents": credit,
        "proration_charge_cents": charge,
        "net_adjustment_cents": charge - credit,
    }


def waiver_reversal_credit(benefit_code, on_date):
    days_in_period = clock.days_in_month(on_date)
    remaining_days = days_in_period - on_date.day + 1
    monthly = Fraction(BENEFIT_ANNUAL_CENTS[benefit_code], 12)
    return round_half_up(monthly * Fraction(remaining_days, days_in_period))


# --------------------------------------------------------------------------
# evidence scoring (PRD 3.6)
# --------------------------------------------------------------------------
def latest_delivered_shipment(subscription_id):
    rows = [s for s in shipments_of(subscription_id)
            if s["status"] in DELIVERED_STATUSES and s["delivered_at"]]
    if not rows:
        return None
    rows.sort(key=lambda s: (s["delivered_at"], s["created_at"], s["_seq"]))
    return rows[-1]


def runtime_evidence(sub):
    shipment = latest_delivered_shipment(sub["id"])
    if shipment is None:
        return []
    cutoff = clock.parse_instant(shipment["delivered_at"])
    rows = [r for r in readings_of(sub["unit_id"])
            if clock.parse_instant(r["window_start"]) >= cutoff]
    rows.sort(key=lambda r: (r["window_start"], r["created_at"], r["_seq"]))
    return rows


def runtime_analytics_score(sub):
    readings = runtime_evidence(sub)
    if len(readings) < 2:
        fail("ERR_NO_EVIDENCE_FOR_METHOD")
    first, last = readings[0], readings[-1]
    span_seconds = (clock.parse_instant(last["window_end"])
                    - clock.parse_instant(first["window_start"])).total_seconds()
    window_days = Fraction(int(round(span_seconds)), 86400)
    total_runtime = sum(r["runtime_minutes"] for r in readings)
    drift_pct = Fraction(last["static_pressure_delta_pa"]
                         - first["static_pressure_delta_pa"],
                         first["static_pressure_delta_pa"])
    drift_term = drift_pct / PRESSURE_DRIFT_SATURATION_PCT
    if drift_term < 0:
        drift_term = Fraction(0)
    if drift_term > 1:
        drift_term = Fraction(1)
    expected = Fraction(RUNTIME_EXPECTED_MINUTES_PER_DAY) * window_days
    runtime_term = Fraction(total_runtime) / expected
    if runtime_term > 1:
        runtime_term = Fraction(1)
    raw = PRESSURE_WEIGHT * drift_term + RUNTIME_WEIGHT * runtime_term
    if raw < 0:
        raw = Fraction(0)
    if raw > 1:
        raw = Fraction(1)
    return round_half_up(raw * 100)


def latest_survey(subscription_id):
    rows = surveys_of(subscription_id)
    if not rows:
        return None
    rows.sort(key=lambda s: (s["submitted_at"], s["created_at"], s["_seq"]))
    return rows[-1]


def renewal_survey_score(sub):
    survey = latest_survey(sub["id"])
    if survey is None:
        fail("ERR_NO_EVIDENCE_FOR_METHOD")
    delivered_filters = sum(sh["quantity"] for sh in shipments_of(sub["id"])
                            if sh["status"] in DELIVERED_STATUSES)
    expected_on_hand = max(0, delivered_filters - sub["filters_per_shipment"])
    score = 0
    if survey["installed_last_shipment"] is False:
        score += SURVEY_NOT_INSTALLED_POINTS
    excess = max(0, survey["filters_on_hand_count"] - expected_on_hand)
    score += SURVEY_EXCESS_POINTS_PER_FILTER * min(SURVEY_EXCESS_POINTS_MAX_FILTERS,
                                                   excess)
    stale_edge = clock.plus_days(
        clock.today(), -SURVEY_STALE_CHANGE_MULTIPLIER * sub["ship_cadence_days"])
    change_date = survey["self_reported_change_date"]
    if change_date is None or clock.parse_date(change_date) < stale_edge:
        score += SURVEY_STALE_CHANGE_POINTS
    return min(100, score)


def evidence_score(sub, detection_method):
    if detection_method == "RUNTIME_ANALYTICS":
        return runtime_analytics_score(sub)
    return renewal_survey_score(sub)


# --------------------------------------------------------------------------
# claim settlement (PRD 3.7)
# --------------------------------------------------------------------------
def claim_base_cents(claim, sub):
    if claim["claim_type"] == "DAMAGE_WAIVER":
        after_deductible = max(0, claim["requested_amount_cents"]
                               - DAMAGE_WAIVER_DEDUCTIBLE_CENTS)
        return min(after_deductible, DAMAGE_WAIVER_PER_INCIDENT_CAP_CENTS)
    activated = clock.parse_instant(sub["activated_at"]).date()
    incident = clock.parse_date(claim["incident_date"])
    elapsed_days = (incident - activated).days
    months_elapsed = elapsed_days // AQG_DAYS_PER_MONTH
    months_covered = min(AQG_MONTHS_CAP, max(0, months_elapsed))
    entitled = sub["monthly_fee_cents"] * months_covered
    return min(claim["requested_amount_cents"], entitled)


def provisional_amount(claim, sub):
    """Triage-time variant: the shared base, with no non-install reduction."""
    return claim_base_cents(claim, sub)


def approved_amount(claim, sub):
    """Decision-time variant: re-reads posture and applies the haircut."""
    base = claim_base_cents(claim, sub)
    haircut = (NON_INSTALL_HAIRCUT_PCT
               if sub["installation_posture"] == "NON_INSTALL_SUSPECTED"
               else Fraction(0))
    return round_half_up(Fraction(base) * (1 - haircut))
