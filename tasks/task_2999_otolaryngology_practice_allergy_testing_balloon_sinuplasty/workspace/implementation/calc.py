"""The twelve calculations of the PRD, plus the shared constant tables."""
from decimal import Decimal, ROUND_HALF_UP

import store

# --- enum vocabularies -------------------------------------------------------
PANEL_CODES = ("ENV_36", "FOOD_24", "MOLD_12", "VENOM_5")
METHODS = ("SKIN_PRICK", "INTRADERMAL", "SERUM_IGE")
SKIN_METHODS = ("SKIN_PRICK", "INTRADERMAL")
ORDER_STATUSES = ("ORDERED", "ADMINISTERED", "SERUM_PENDING", "READ", "ABORTED")
ABORT_REASONS = ("DERMATOGRAPHISM_DETECTED", "SYSTEMIC_REACTION")
RISK_VARIANTS = ("PROVISIONAL", "POST_REACTION")
SUPERVISION_TIERS = ("STANDARD", "PHYSICIAN_PRESENT")
IMMUNO_STATUSES = ("NONE", "BUILD_UP", "MAINTENANCE", "HELD")
DILUTION_CODES = ("YELLOW_1_10", "BLUE_1_100", "GREEN_1_1000", "SILVER_1_10000")
VIAL_STATUSES = ("MIXED", "LABEL_VERIFIED", "IN_USE", "EXHAUSTED", "DISCARDED")
DISCARD_REASONS_INPUT = ("BEYOND_USE_DATE", "CONTAMINATION")
DOSE_STATUSES = ("ADMINISTERED", "CLEARED", "VOIDED", "REACTION_HELD")
VOID_REASONS = ("DRAWN_IN_ERROR", "WRONG_VIAL", "PATIENT_DEFERRED")
LATERALITIES = ("LEFT", "RIGHT", "BILATERAL")
SINUSES = ("MAXILLARY", "FRONTAL", "SPHENOID")
THERAPY_CODES = ("INCS", "ABX", "SALINE", "ORAL_STEROID")
CRITERIA_CODES = (
    "CT_OPACIFICATION",
    "SNOT22_GE_20",
    "FAILED_INCS",
    "FAILED_ABX",
    "FAILED_SALINE",
    "ENDOSCOPY_FINDING",
)
CASE_STATUSES = (
    "DRAFT",
    "DOCUMENTED",
    "AUTH_SUBMITTED",
    "INFO_REQUESTED",
    "AUTHORIZED",
    "AUTH_EXPIRED",
    "DENIED",
    "SCHEDULED",
    "COMPLETED",
)
CANDIDACY_STATUSES = ("UNDETERMINED", "ELIGIBLE", "INELIGIBLE")
EVALUATION_VARIANTS = ("POLICY_STRICT", "CLINICAL_BROAD")
DECISIONS = ("APPROVED", "DENIED", "INFO_REQUESTED")
STUDY_TYPES = ("AUDIOMETRY", "SLEEP_HSAT", "SLEEP_PSG")
STUDY_STATUSES = ("ORDERED", "PERFORMED", "INTERPRETED")
RECOMMENDATIONS = ("HEARING_AID", "ORAL_APPLIANCE", "CPAP", "OBSERVATION")
DEVICE_TYPES = ("HEARING_AID", "ORAL_APPLIANCE")
EARS = ("LEFT", "RIGHT", "BOTH", "NA")
FIT_STATUSES = ("FITTED", "ADJUSTED", "FINALIZED", "RETURNED")
BILLING_STATUSES = ("INVOICED", "REFUND_PENDING", "REFUNDED", "RETAINED")
RETURN_REASONS = ("DISSATISFIED", "POOR_FIT", "MEDICAL_CHANGE")
REFUND_VARIANTS = ("IN_TRIAL", "POST_TRIAL")
SCOPE_STATUSES = ("READY", "IN_USE", "SOILED", "REPROCESSING", "QUARANTINED", "RETIRED")
ITEM_TYPES = (
    "BALLOON_DEVICE",
    "TYMPANOSTOMY_TUBE",
    "ALLERGEN_CONCENTRATE",
    "HEARING_AID",
    "ORAL_APPLIANCE",
)
LOT_STATUSES = ("ACTIVE", "EXHAUSTED", "QUARANTINED")
ADJUSTMENT_REASONS = ("RECEIVE", "WRITE_OFF", "QUARANTINE")
BLOCK_STATUSES = ("OPEN", "FULL", "CLOSED")
PROCEDURE_TYPES = (
    "BALLOON_SINUPLASTY",
    "DIAGNOSTIC_ENDOSCOPY",
    "TYMPANOSTOMY_TUBES",
    "TONSILLECTOMY",
)
VENUES = ("IN_OFFICE_SUITE", "SURGERY_CENTER")
BOOKING_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
CANCEL_REASONS = (
    "PATIENT_REQUEST",
    "CLINICAL_HOLD",
    "SUPPLY_SHORTAGE",
    "SCOPE_UNAVAILABLE",
)

# --- constant tables ---------------------------------------------------------
PANEL_ANTIGEN_COUNT = {"ENV_36": 36, "FOOD_24": 24, "MOLD_12": 12, "VENOM_5": 5}
METHOD_UNIT_CENTS = {"SKIN_PRICK": 1775, "INTRADERMAL": 2240, "SERUM_IGE": 3310}
OBSERVATION_BASE = {"SKIN_PRICK": 30, "INTRADERMAL": 40, "IMMUNO_DOSE": 30}
SCHEDULE_ML = {
    1: "0.05", 2: "0.10", 3: "0.20", 4: "0.30", 5: "0.40", 6: "0.50",
    7: "0.05", 8: "0.10", 9: "0.20", 10: "0.30", 11: "0.40", 12: "0.50",
}
MIN_DOSE_ML = Decimal("0.05")
HLD_SHELF_HOURS = 168
REPROCESSING_BUFFER_MINUTES = 45
WEAR_CENTS_PER_DAY = 350
WASHOUT_HOURS = 72
VOID_WINDOW_MINUTES = 15
RISK_OBSERVATION_THRESHOLD = 45
RISK_SUPERVISION_THRESHOLD = 60
PEDIATRIC_RISK_AGE_MONTHS = 72
PEDIATRIC_VENUE_AGE_MONTHS = 36
CENTS = Decimal("1")
TWO_PLACES = Decimal("0.01")


def round_half_up(value):
    return int(Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))


def vol_out(value):
    """Two-decimal millilitre figure rendered for JSON."""
    return float(Decimal(value).quantize(TWO_PLACES))


# --- 1. patient_age_months ---------------------------------------------------
def age_months(patient):
    dob = store.parse_date(patient["date_of_birth"])
    clock = store.today()
    months = (clock.year - dob.year) * 12 + (clock.month - dob.month)
    if clock.day < dob.day:
        months -= 1
    return months


# --- 2. allergy_panel_billing ------------------------------------------------
def tier_factor(antigen_count):
    if antigen_count <= 12:
        return Decimal("1.0000")
    if antigen_count <= 30:
        return Decimal("0.9250")
    return Decimal("0.8500")


def billed_units_for(method, antigen_count):
    if method == "SERUM_IGE":
        return -(-antigen_count // 4)
    return antigen_count


def panel_billing(panel_code, method, covered_pct_bps):
    antigen_count = PANEL_ANTIGEN_COUNT[panel_code]
    unit_cents = METHOD_UNIT_CENTS[method]
    per_unit_gross = round_half_up(dec(unit_cents) * tier_factor(antigen_count))
    units = billed_units_for(method, antigen_count)
    practice_charge = per_unit_gross * units
    per_unit_patient = round_half_up(
        dec(per_unit_gross) * dec(10000 - covered_pct_bps) / dec(10000)
    )
    return {
        "billed_units": units,
        "practice_charge_cents": practice_charge,
        "patient_responsibility_cents": per_unit_patient * units,
    }


# --- 3. patient_anaphylaxis_risk_score ---------------------------------------
def _decay_factor(days_ago):
    if days_ago <= 30:
        return Decimal("1.00")
    if days_ago <= 90:
        return Decimal("0.60")
    if days_ago <= 180:
        return Decimal("0.30")
    return Decimal("0.00")


def event_patient_id(event):
    order_id = event.get("allergy_test_order_id")
    if order_id:
        order = store.db["allergy_test_orders"].get(order_id)
        return order["patient_id"] if order else None
    dose_id = event.get("immunotherapy_dose_id")
    if dose_id:
        dose = store.db["immunotherapy_doses"].get(dose_id)
        if not dose:
            return None
        vial = store.db["immunotherapy_vials"].get(dose["immunotherapy_vial_id"])
        return vial["patient_id"] if vial else None
    return None


def patient_reaction_events(patient_id):
    found = [e for e in store.rows("reaction_events")
             if event_patient_id(e) == patient_id]
    found.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))
    return found


def event_term(patient):
    total = 0
    now = store.now()
    for event in patient_reaction_events(patient["id"]):
        occurred = store.parse_instant(event["occurred_at"])
        days_ago = store.whole_days_between(occurred, now)
        factor = _decay_factor(days_ago)
        total += round_half_up(dec(20 * event["systemic_grade"]) * factor)
    return total


def risk_score(patient):
    total = 5
    total += 15 * min(patient["prior_systemic_reaction_count"], 3)
    total += min(20, patient["sensitized_antigen_count"])
    if age_months(patient) < PEDIATRIC_RISK_AGE_MONTHS:
        total += 8
    if not patient["epinephrine_on_file"]:
        total += 10
    if patient["risk_score_variant"] == "POST_REACTION":
        total += event_term(patient)
    return max(0, min(100, total))


def tier_for_score(score):
    return "PHYSICIAN_PRESENT" if score >= RISK_SUPERVISION_THRESHOLD else "STANDARD"


def rescore_patient(patient):
    patient["risk_score"] = risk_score(patient)
    patient["supervision_tier"] = tier_for_score(patient["risk_score"])


# --- 4. observation_minutes_required -----------------------------------------
def observation_minutes(patient, policy, context, step=None):
    if context == "SERUM_IGE":
        return 0
    candidate = OBSERVATION_BASE[context]
    if patient["risk_score"] >= RISK_OBSERVATION_THRESHOLD:
        candidate = max(candidate, 60)
    if context == "IMMUNO_DOSE" and step is not None and step >= 9:
        candidate = max(candidate, 45)
    if patient["supervision_tier"] == "PHYSICIAN_PRESENT":
        candidate = max(candidate, 90)
    candidate = max(candidate, policy["observation_floor_minutes"])
    return candidate


# --- 5. immunotherapy_next_dose_volume ---------------------------------------
def next_dose_plan(patient):
    pre_step = patient["immunotherapy_escalation_step"]
    required_dilution = "BLUE_1_100" if pre_step <= 6 else "YELLOW_1_10"
    last = patient["last_dose_administered_at"]
    if last is None:
        gap_days = 0
    else:
        gap_days = store.whole_days_between(store.parse_instant(last), store.now())
    effective = pre_step
    if pre_step <= 6 and gap_days >= 14:
        effective = max(1, pre_step - 2)
    elif pre_step >= 7 and gap_days >= 28:
        effective = max(1, pre_step - 3)
    volume = Decimal(SCHEDULE_ML[effective])
    return {
        "pre_step": pre_step,
        "required_dilution": required_dilution,
        "gap_days": gap_days,
        "effective_step": effective,
        "volume": volume,
    }


# --- 6. sinuplasty_candidacy_evaluation --------------------------------------
def _therapy_span(item):
    start = store.parse_date(item["start_date"])
    end = store.parse_date(item["end_date"])
    return (end - start).days + 1


def management_days(therapies):
    parsed = []
    for item in therapies:
        parsed.append((
            store.parse_date(item["start_date"]),
            store.parse_date(item["end_date"]),
            item["therapy_code"],
        ))
    parsed.sort(key=lambda t: (t[0], t[1]))
    cumulative = sum((end - start).days + 1 for start, end, _c in parsed)
    merged = []
    for start, end, _c in parsed:
        if not merged:
            merged.append([start, end])
            continue
        cur = merged[-1]
        if (start - cur[1]).days > 1:
            merged.append([start, end])
        else:
            if end > cur[1]:
                cur[1] = end
    contiguous = 0
    for start, end in merged:
        span = (end - start).days + 1
        if span > contiguous:
            contiguous = span
    return cumulative, contiguous


def candidacy_evaluation(case, policy):
    therapies = case.get("documented_therapies") or []
    cumulative, contiguous = management_days(therapies)
    codes = []
    for code in (case.get("documented_criteria_codes") or []):
        if code not in codes:
            codes.append(code)
    variant = case["evaluation_variant"]
    present_codes = set(item["therapy_code"] for item in therapies)
    admissible = []
    for code in codes:
        if variant == "CLINICAL_BROAD":
            admissible.append(code)
            continue
        if code == "FAILED_INCS":
            if "INCS" in present_codes:
                admissible.append(code)
        elif code == "FAILED_ABX":
            if "ABX" in present_codes:
                admissible.append(code)
        elif code == "FAILED_SALINE":
            if "SALINE" in present_codes:
                admissible.append(code)
        elif code == "CT_OPACIFICATION":
            ct = case.get("ct_study_date")
            if ct is not None:
                allowance = policy["requires_ct_within_months"] * 30
                age_days = (store.today() - store.parse_date(ct)).days
                if age_days <= allowance:
                    admissible.append(code)
        else:
            admissible.append(code)
    metric = contiguous if variant == "POLICY_STRICT" else cumulative
    count = len(admissible)
    eligible = (
        count >= policy["min_documented_criteria"]
        and metric >= policy["min_medical_management_days"]
    )
    return {
        "evaluation_variant": variant,
        "criteria_met_count": count,
        "admissible_criteria_codes": admissible,
        "contiguous_management_days": contiguous,
        "cumulative_management_days": cumulative,
        "management_days_metric": metric,
        "min_documented_criteria_required": policy["min_documented_criteria"],
        "min_medical_management_days_required": policy["min_medical_management_days"],
        "candidacy_status": "ELIGIBLE" if eligible else "INELIGIBLE",
    }


# --- 7. device_trial_refund --------------------------------------------------
def trial_refund(dispense, policy):
    dispensed_at = store.parse_instant(dispense["dispensed_at"])
    trial_end_at = store.parse_instant(dispense["trial_end_at"])
    now = store.now()
    days_used = store.whole_days_between(dispensed_at, now) + 1
    if now < trial_end_at:
        variant = "IN_TRIAL"
        proportional = round_half_up(
            dec(dispense["price_cents"]) * dec(policy["restock_fee_bps"]) / dec(10000)
        )
        fee = max(policy["restock_fee_floor_cents"], proportional)
        wear = WEAR_CENTS_PER_DAY * days_used
        refund = max(0, dispense["price_cents"] - fee - wear)
        billing = "REFUND_PENDING"
    else:
        variant = "POST_TRIAL"
        fee = 0
        refund = 0
        billing = "RETAINED"
    return {
        "days_used": days_used,
        "refund_variant": variant,
        "restock_fee_cents": fee,
        "refund_cents": refund,
        "billing_status": billing,
    }


# --- 8. study_recommendation -------------------------------------------------
def study_recommendation(study):
    if study["study_type"] == "AUDIOMETRY":
        return "HEARING_AID" if study["pta_db_hl"] >= 40 else "OBSERVATION"
    ahi = study["ahi"]
    if ahi < 5:
        return "OBSERVATION"
    if ahi <= 30:
        return "ORAL_APPLIANCE"
    return "CPAP"


RECOMMENDED_DEVICE = {"HEARING_AID": "HEARING_AID", "ORAL_APPLIANCE": "ORAL_APPLIANCE"}


# --- 9. surgery_block_utilization -------------------------------------------
BLOCK_COUNTED_BOOKINGS = ("SCHEDULED", "IN_PROGRESS", "COMPLETED")


def block_bookings(block_id):
    return [b for b in store.rows("procedure_bookings")
            if b["surgery_center_block_id"] == block_id
            and b["status"] in BLOCK_COUNTED_BOOKINGS]


def recompute_block(block):
    booked = 0
    count = 0
    for booking in block_bookings(block["id"]):
        booked += booking["duration_minutes"]
        count += 1
    block["booked_minutes"] = booked
    block["booked_case_count"] = count
    capacity = block["capacity_minutes"]
    if capacity == 0:
        block["utilization_bps"] = 0
    else:
        block["utilization_bps"] = round_half_up(
            dec(booked) * dec(10000) / dec(capacity)
        )
    if block["status"] == "OPEN" and block["utilization_bps"] >= 10000:
        block["status"] = "FULL"
    elif block["status"] == "FULL" and block["utilization_bps"] < 10000:
        block["status"] = "OPEN"


# --- 10. supply_lot_availability --------------------------------------------
RESERVING_BOOKINGS = ("SCHEDULED", "IN_PROGRESS")


def lot_reserved(lot_id):
    total = 0
    for booking in store.rows("procedure_bookings"):
        if booking["supply_lot_id"] == lot_id and booking["status"] in RESERVING_BOOKINGS:
            total += booking["planned_device_count"]
    return total


def refresh_lot(lot):
    lot["quantity_reserved"] = lot_reserved(lot["id"])
    lot["available_quantity"] = max(0, lot["quantity_on_hand"] - lot["quantity_reserved"])
    return lot["available_quantity"]


def lot_available(lot):
    return max(0, lot["quantity_on_hand"] - lot_reserved(lot["id"]))


# --- 11. immunotherapy_vial_volume_ledger ------------------------------------
DISPENSING_DOSES = ("ADMINISTERED", "CLEARED", "REACTION_HELD")


def vial_dispensed_total(vial_id):
    total = Decimal("0.00")
    doses = [d for d in store.rows("immunotherapy_doses")
             if d["immunotherapy_vial_id"] == vial_id
             and d["status"] in DISPENSING_DOSES]
    doses.sort(key=lambda d: (d["administered_at"], d["created_at"], d["_seq"]))
    for dose in doses:
        total += dec(dose["volume_ml"])
    return total


def refresh_vial_ledger(vial):
    dispensed = vial_dispensed_total(vial["id"])
    wasted = dec(vial["volume_ml_wasted"])
    remaining = dec(vial["volume_ml_initial"]) - dispensed - wasted
    vial["volume_ml_dispensed_total"] = vol_out(dispensed)
    vial["volume_ml_remaining"] = vol_out(remaining)
    return remaining


# --- 12. scope_reprocessing_due ---------------------------------------------
def mec_test_due(cycle_count):
    return (cycle_count + 1) % 10 == 0


def scope_shelf_valid(scope):
    if scope["last_reprocessed_at"] is None:
        return True
    expires = store.parse_instant(scope["hld_expires_at"])
    if expires is None:
        return True
    return store.now() < expires
