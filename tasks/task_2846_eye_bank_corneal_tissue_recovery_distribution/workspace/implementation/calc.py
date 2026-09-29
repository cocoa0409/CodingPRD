"""The fifteen calculations of PRD section 3, implemented literally."""

from decimal import Decimal

import store

# ------------------------------------------------------------------ 1. window

BASIS_BASE_MINUTES = {"ASYSTOLE": 720, "PRONOUNCED": 660}
WINDOW_FLOOR_MINUTES = 360
AGE_PENALTY_THRESHOLD = 71
AGE_PENALTY_MINUTES = 60


def cooling_delay_minutes(donor):
    if donor["body_cooled_at"] is None:
        return None
    return store.floor_minutes(donor["death_at"], donor["body_cooled_at"])


def donor_recovery_window(donor):
    """Returns (recovery_window_minutes, recovery_deadline_at)."""
    base = BASIS_BASE_MINUTES[donor["death_time_basis"]]
    delay = cooling_delay_minutes(donor)
    if delay is None:
        credit = 0
    elif delay <= 240:
        credit = 240
    elif delay <= 480:
        credit = 120
    else:
        credit = 0
    penalty = AGE_PENALTY_MINUTES if donor["age_years"] >= AGE_PENALTY_THRESHOLD else 0
    minutes = max(WINDOW_FLOOR_MINUTES, base + credit - penalty)
    return minutes, store.add_minutes(donor["death_at"], minutes)


def apply_recovery_window(donor):
    minutes, deadline = donor_recovery_window(donor)
    donor["recovery_window_minutes"] = minutes
    donor["recovery_deadline_at"] = deadline


# ----------------------------------------------------------- 2. screening risk

SCREENING_WEIGHTS = {
    "CJD_FAMILY": 60,
    "UNEXPLAINED_NEURO": 50,
    "IV_DRUG_USE": 40,
    "HIV_RISK": 35,
    "HEP_B_C_HISTORY": 30,
    "SEPSIS": 25,
    "INCARCERATION_12M": 15,
    "TATTOO_12M": 10,
}
SCREENING_RISK_CEILING = 50
HEMODILUTION_THRESHOLD = Decimal("50.00")


def donor_screening_records(donor_id):
    rows = [r for r in store.DB["screening_records"].values() if r["donor_id"] == donor_id]
    return store.by_created(rows)


def current_resulted_panel(donor_id):
    """The single RESULTED, non-INVALIDATED panel of a donor, when one exists."""
    rows = [
        p
        for p in store.DB["serology_panels"].values()
        if p["donor_id"] == donor_id and p["status"] == "RESULTED"
    ]
    rows = store.by_created(rows)
    return rows[-1] if rows else None


def recompute_screening_risk(donor):
    """Rewrites weight_applied on every row of the donor and the donor's score."""
    rows = donor_screening_records(donor["id"])
    yes_sum = 0
    unknown_sum = 0
    for row in rows:
        weight = SCREENING_WEIGHTS[row["question_code"]]
        if row["response"] == "YES":
            yes_sum += weight
        elif row["response"] == "UNKNOWN":
            unknown_sum += weight

    panel = current_resulted_panel(donor["id"])
    if panel is None:
        variant = "INTERVIEW_ONLY"
        charge_unknown = False
    else:
        variant = "POST_SEROLOGY_RECONCILED"
        charge_unknown = (
            panel["overall_result"] == "INDETERMINATE"
            or panel["hemodilution_pct"] > HEMODILUTION_THRESHOLD
        )

    raw = yes_sum + unknown_sum if charge_unknown else yes_sum
    for row in rows:
        weight = SCREENING_WEIGHTS[row["question_code"]]
        if row["response"] == "YES":
            row["weight_applied"] = weight
        elif row["response"] == "UNKNOWN" and charge_unknown:
            row["weight_applied"] = weight
        else:
            row["weight_applied"] = 0

    donor["screening_risk_variant"] = variant
    # The transplant risk ceiling of 50 is a threshold the score is COMPARED against,
    # never a cap applied to the score itself: the stored figure is the raw weighted sum.
    donor["screening_risk_score"] = raw
    return donor["screening_risk_score"]


# ---------------------------------------------------------- 3. serology result

MARKER_FIELDS = ("hiv_result", "hbv_result", "hcv_result", "syphilis_result")
DONOR_SEROLOGY_FROM_OVERALL = {
    "NON_REACTIVE": "NEGATIVE",
    "REACTIVE": "REACTIVE",
    "INDETERMINATE": "INDETERMINATE",
}


def serology_overall_result(markers, hemodilution_pct):
    values = list(markers)
    if any(v == "REACTIVE" for v in values):
        return "REACTIVE"
    if hemodilution_pct > HEMODILUTION_THRESHOLD:
        return "INDETERMINATE"
    if any(v == "INDETERMINATE" for v in values):
        return "INDETERMINATE"
    return "NON_REACTIVE"


# ------------------------------------------------------- 4. recovery time band


def recovery_time_limit(death_at, preservation_at):
    minutes = store.floor_minutes(death_at, preservation_at)
    if minutes <= 720:
        band = "WITHIN_STANDARD"
    elif minutes <= 900:
        band = "WITHIN_EXTENDED"
    else:
        band = "EXCEEDED"
    return minutes, band


# -------------------------------------------------- 5. technician occupation

TURNAROUND_MINUTES = 60
OCCUPYING_RECOVERY_STATUSES = ("DISPATCHED", "ON_SITE", "COMPLETED")


def occupation_end_at(recovery):
    anchor = (
        recovery["preservation_at"]
        if recovery["status"] == "COMPLETED" and recovery["preservation_at"] is not None
        else recovery["planned_release_at"]
    )
    return store.add_minutes(anchor, TURNAROUND_MINUTES)


def refresh_occupation(recovery):
    recovery["occupation_end_at"] = occupation_end_at(recovery)


def has_dispatch_overlap(technician_id, dispatched_at, occupation_end, ignore_id=None):
    """Half-open [dispatched_at, occupation_end_at) intervals; adjacency is legal."""
    for row in store.DB["recoveries"].values():
        if row["technician_id"] != technician_id:
            continue
        if ignore_id is not None and row["id"] == ignore_id:
            continue
        if row["status"] not in OCCUPYING_RECOVERY_STATUSES:
            continue
        other_end = row["occupation_end_at"]
        if dispatched_at < other_end and row["dispatched_at"] < occupation_end:
            return True
    return False


# ------------------------------------------------------------ 6. shelf life

MEDIUM_BASE_HOURS = {"OPTISOL_GS": 336, "LIFE4C": 264}
BAND_PENALTY_HOURS = 48
COOLING_PENALTY_HOURS = 72
LOW_ENDOTHELIUM_PENALTY_HOURS = 24
SHELF_LIFE_FLOOR_HOURS = 24
LOW_ENDOTHELIUM_THRESHOLD = 2200


def recorded_evaluation(tissue_id, method):
    rows = [
        e
        for e in store.DB["evaluations"].values()
        if e["tissue_id"] == tissue_id and e["method"] == method and e["status"] == "RECORDED"
    ]
    rows = store.by_created(rows)
    return rows[-1] if rows else None


def provisional_shelf_life(medium, band):
    hours = MEDIUM_BASE_HOURS[medium]
    if band == "WITHIN_EXTENDED":
        hours -= BAND_PENALTY_HOURS
    return max(SHELF_LIFE_FLOOR_HOURS, hours)


def final_shelf_life(medium, band, donor, specular_ecd):
    hours = MEDIUM_BASE_HOURS[medium]
    if band == "WITHIN_EXTENDED":
        hours -= BAND_PENALTY_HOURS
    delay = cooling_delay_minutes(donor)
    if delay is None or delay > 480:
        hours -= COOLING_PENALTY_HOURS
    if specular_ecd is not None and specular_ecd < LOW_ENDOTHELIUM_THRESHOLD:
        hours -= LOW_ENDOTHELIUM_PENALTY_HOURS
    return max(SHELF_LIFE_FLOOR_HOURS, hours)


def apply_shelf_life(tissue, hours, variant):
    tissue["shelf_life_hours"] = hours
    tissue["shelf_life_variant"] = variant
    tissue["expires_at"] = store.add_hours(tissue["preserved_at"], hours)


# --------------------------------------------------------- 7. quality score


def tissue_quality_score(slit_lamp, specular, donor):
    ecd_points = min(40, max(0, (specular["endothelial_cell_count"] - 1800) // 50))
    clarity_points = 25 - 5 * slit_lamp["stromal_clarity_grade"]
    epithelium_points = 15 - 4 * slit_lamp["epithelium_defect_grade"]
    folds_points = 10 - 3 * slit_lamp["dm_folds_grade"]
    guttata_points = 10 - 5 * specular["guttata_grade"]
    age = donor["age_years"]
    if age >= 71:
        age_adjust = -8
    elif age >= 46:
        age_adjust = 0
    else:
        age_adjust = 5
    total = (
        ecd_points
        + clarity_points
        + epithelium_points
        + folds_points
        + guttata_points
        + age_adjust
    )
    return max(0, min(100, total))


# --------------------------------------------------------- 8. classification

CLASSIFICATION_DISPOSITION = {
    "TRANSPLANT_OPTICAL": "ELIGIBLE",
    "TRANSPLANT_THERAPEUTIC": "ELIGIBLE",
    "RESEARCH": "RELEASED_FOR_RESEARCH",
    "TRAINING": "RELEASED_FOR_TRAINING",
    "UNSUITABLE": "DISCARDED",
}


def tissue_classification(donor, band, quality_score, specular_ecd):
    """Ordered decision table; the first matching row wins."""
    if donor["serology_status"] == "REACTIVE":
        return "UNSUITABLE"
    if donor["consent_scope"] == "RESEARCH_ONLY":
        return "RESEARCH"
    if donor["consent_scope"] == "TRAINING_ONLY":
        return "TRAINING"
    if donor["screening_risk_score"] >= 50:
        return "RESEARCH"
    if donor["serology_status"] == "INDETERMINATE":
        return "RESEARCH"
    if band == "EXCEEDED":
        return "UNSUITABLE"
    if quality_score >= 70 and specular_ecd >= 2000 and band == "WITHIN_STANDARD":
        return "TRANSPLANT_OPTICAL"
    if quality_score >= 45 and specular_ecd >= 1800:
        return "TRANSPLANT_THERAPEUTIC"
    if donor["consent_scope"] == "TRANSPLANT_AND_RESEARCH":
        return "RESEARCH"
    return "UNSUITABLE"


# ------------------------------------------------------- 9. request priority

URGENCY_WEIGHT = {"URGENT": 30, "ROUTINE": 10}
TIER_BONUS = {"PLATINUM": 15, "GOLD": 8, "STANDARD": 0}


def days_to_surgery(surgery_date):
    return store.floor_days(store.now(), surgery_date)


def request_priority(urgency, surgery_date):
    """Returns (base_score, priority_tier, priority_score) in the pinned order."""
    weight = URGENCY_WEIGHT[urgency]
    days = days_to_surgery(surgery_date)
    if days <= 2:
        proximity = 40
    elif days <= 7:
        proximity = 25
    elif days <= 21:
        proximity = 10
    else:
        proximity = 0
    base = weight + proximity
    # The tier is read from base_score only; never re-derived from priority_score.
    if base >= 60:
        tier = "PLATINUM"
    elif base >= 40:
        tier = "GOLD"
    else:
        tier = "STANDARD"
    return base, tier, base + TIER_BONUS[tier]


def apply_priority(req):
    base, tier, score = request_priority(req["urgency"], req["surgery_date"])
    req["base_score"] = base
    req["priority_tier"] = tier
    req["priority_score"] = score
    return score


# ----------------------------------------------------------- 11. processing fee

CLASSIFICATION_BASE_CENTS = {
    "TRANSPLANT_OPTICAL": 245000,
    "TRANSPLANT_THERAPEUTIC": 189000,
}
URGENCY_SURCHARGE_RATE = Decimal("0.0725")
PROCEDURE_SURCHARGE_RATE = Decimal("0.0425")
SHORT_NOTICE_SURCHARGE_RATE = Decimal("0.0175")
SURCHARGED_PROCEDURES = ("DMEK", "DSAEK")


def allocation_processing_fee(classification_snapshot, req):
    """Each surcharge is rounded half up independently, then added to the base."""
    base = CLASSIFICATION_BASE_CENTS[classification_snapshot]
    base_dec = Decimal(base)
    total = base
    if req["urgency"] == "URGENT":
        total += store.round_half_up(base_dec * URGENCY_SURCHARGE_RATE)
    if req["procedure_type"] in SURCHARGED_PROCEDURES:
        total += store.round_half_up(base_dec * PROCEDURE_SURCHARGE_RATE)
    if days_to_surgery(req["surgery_date"]) <= 2:
        total += store.round_half_up(base_dec * SHORT_NOTICE_SURCHARGE_RATE)
    return total


# ------------------------------------------------------- 12. integrity verdict

TEMP_MIN_IN_RANGE = Decimal("2.0")
TEMP_MAX_IN_RANGE = Decimal("8.0")
MINOR_MAX_TEMP = Decimal("12.0")
MINOR_MIN_TEMP = Decimal("-5.0")


def shipment_readings(shipment_id):
    rows = [r for r in store.DB["temperature_readings"].values() if r["shipment_id"] == shipment_id]
    return sorted(rows, key=lambda r: (r["recorded_at"], r["created_at"], r["_seq"]))


def shipment_integrity_verdict(shipment, shipped_at, delivered_at):
    """Returns (min_temp_c, max_temp_c, excursion_minutes, verdict)."""
    included = [
        r
        for r in shipment_readings(shipment["id"])
        if shipped_at <= r["recorded_at"] <= delivered_at
    ]
    if not included:
        return None, None, 0, "PASS"

    temps = [r["temperature_c"] for r in included]
    min_temp = min(temps)
    max_temp = max(temps)

    total_minutes = 0
    index = 0
    count = len(included)
    while index < count:
        temp = included[index]["temperature_c"]
        if temp < TEMP_MIN_IN_RANGE or temp > TEMP_MAX_IN_RANGE:
            start_index = index
            end_index = index
            while end_index + 1 < count:
                nxt = included[end_index + 1]["temperature_c"]
                if nxt < TEMP_MIN_IN_RANGE or nxt > TEMP_MAX_IN_RANGE:
                    end_index += 1
                else:
                    break
            if start_index == 0:
                segment_start = shipped_at
            else:
                segment_start = included[start_index - 1]["recorded_at"]
            segment_end = included[end_index]["recorded_at"]
            total_minutes += store.floor_minutes(segment_start, segment_end)
            index = end_index + 1
        else:
            index += 1

    if total_minutes == 0:
        verdict = "PASS"
    elif 1 <= total_minutes <= 45 and max_temp <= MINOR_MAX_TEMP and min_temp >= MINOR_MIN_TEMP:
        verdict = "EXCURSION_MINOR"
    else:
        verdict = "EXCURSION_MAJOR"
    return min_temp, max_temp, total_minutes, verdict


def refresh_temperature_envelope(shipment):
    """Running provisional min/max across every reading recorded so far."""
    rows = shipment_readings(shipment["id"])
    if not rows:
        shipment["min_temp_c"] = None
        shipment["max_temp_c"] = None
        return
    temps = [r["temperature_c"] for r in rows]
    shipment["min_temp_c"] = min(temps)
    shipment["max_temp_c"] = max(temps)


# ---------------------------------------------------------- 13. fee ledger

GROSS_STATUSES = ("CONFIRMED", "CONSUMED", "RELEASED")
CREDITED_STATUSES = ("RELEASED",)


def surgeon_allocations(surgeon_id):
    request_ids = {
        r["id"] for r in store.DB["requests"].values() if r["surgeon_id"] == surgeon_id
    }
    return [a for a in store.DB["allocations"].values() if a["request_id"] in request_ids]


def recompute_fee_ledger(surgeon):
    allocations = surgeon_allocations(surgeon["id"])
    gross = sum(a["processing_fee_cents"] for a in allocations if a["status"] in GROSS_STATUSES)
    credited = sum(
        a["processing_fee_cents"] for a in allocations if a["status"] in CREDITED_STATUSES
    )
    surgeon["gross_billed_cents"] = gross
    surgeon["credited_fee_cents"] = credited
    surgeon["outstanding_fee_cents"] = gross - credited


# ------------------------------------------------------ 14. availability ledger

AVAILABLE_CUSTODY = ("IN_HOUSE", "RETURNED_TO_BANK")
COMMITTED_DISPOSITIONS = ("RESERVED", "ISSUED")
RETIRED_DISPOSITIONS = (
    "IMPLANTED",
    "DISCARDED",
    "RELEASED_FOR_RESEARCH",
    "RELEASED_FOR_TRAINING",
)


def tissue_availability_ledger(rows):
    available = [
        t
        for t in rows
        if t["disposition_status"] == "ELIGIBLE" and t["custody_status"] in AVAILABLE_CUSTODY
    ]
    committed = [t for t in rows if t["disposition_status"] in COMMITTED_DISPOSITIONS]
    held = [t for t in rows if t["disposition_status"] == "QUARANTINED"]
    retired = [t for t in rows if t["disposition_status"] in RETIRED_DISPOSITIONS]
    graded = [t for t in rows if t["disposition_status"] != "UNGRADED"]
    return {
        "available": len(available),
        "committed": len(committed),
        "held": len(held),
        "retired": len(retired),
        "graded": len(graded),
    }


# ------------------------------------------------------- 15. lookback impact

LOOKBACK_QUARANTINABLE = ("ELIGIBLE", "RESERVED")
NOTIFIABLE_ALLOCATION_STATUSES = ("RESERVED", "CONFIRMED", "CONSUMED", "RELEASED")


def donor_tissues(donor_id):
    rows = [t for t in store.DB["tissues"].values() if t["donor_id"] == donor_id]
    return store.by_created(rows)


def lookback_notified_recipient_count(donor_id):
    tissue_ids = {t["id"] for t in donor_tissues(donor_id)}
    surgeons = set()
    for allocation in store.DB["allocations"].values():
        if allocation["tissue_id"] not in tissue_ids:
            continue
        if allocation["status"] not in NOTIFIABLE_ALLOCATION_STATUSES:
            continue
        req = store.DB["requests"].get(allocation["request_id"])
        if req is not None:
            surgeons.add(req["surgeon_id"])
    return len(surgeons)
