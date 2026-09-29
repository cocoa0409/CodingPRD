"""Shared domain services: vial conservation, treat-and-extend, authorization
usage, cascades, the patient-responsibility waterfall, lot exposure and
adverse-event reportability.

Traces to PRD 2.9 - 2.11 and 3.3 - 3.9 and SCAFFOLD calculations.
"""
from datetime import timedelta
from decimal import Decimal

from core import (
    DB,
    add_days,
    cents,
    dec,
    fail,
    ordered,
    round_half_up,
    touch,
    whole_days,
)

# ------------------------------------------------------------------ constants
CST_ACTIVE_THRESHOLD_UM = 300
LOADING_INTERVAL_DAYS = 28
EXTENSION_STEP_DAYS = 14
REDUCTION_STEP_DAYS = 14
QUIESCENT_RUN_FOR_DOUBLE_STEP = 3
IMAGING_VALIDITY_DAYS = 14
CAPACITY_WINDOW_HOURS = 24
FOUNDATION_HIGH_TIER_CENTS = 50000
LOW_TIER_CAP_FACTOR = Decimal("0.5")
WRITEOFF_THRESHOLD_CENTS = 1000
CARRYING_RATE_BASIS_POINTS = 2000
DAYS_PER_YEAR = 365
BURN_WINDOW_DAYS = 30
ENDOPHTHALMITIS_WINDOW_DAYS = 30
SEVERE_REPORT_DAYS = 15
ROUTINE_REPORT_DAYS = 30
LOT_CLUSTER_THRESHOLD = 2
RECALL_CLASS_DAYS = {"CLASS_I": 3, "CLASS_II": 10, "CLASS_III": 30}
ADMINISTRATION_CPT_CODE = "67028"

FEDERAL_PAYER_TYPES = ("MEDICARE_PART_B", "MEDICARE_ADVANTAGE", "MEDICAID")

PLAN_OPEN_STATUSES = ("DRAFT", "LOADING", "MAINTENANCE", "INTENSIFIED", "SUSPENDED")
PLAN_TREATABLE = ("LOADING", "MAINTENANCE", "INTENSIFIED")
ENCOUNTER_COUNTED = ("DOCUMENTED", "ATTESTED", "BILLED", "CLOSED")

POLICY_DEFAULT_PA_VALIDITY_DAYS = 180
POLICY_DEFAULT_PA_MAX_INJECTIONS = 3


# ---------------------------------------------------------------- collections
def policy_for(payer_id, drug_id):
    for row in ordered(DB.policies.values()):
        if row["payer_id"] == payer_id and row["drug_id"] == drug_id:
            return row
    return None


def lot_vials(lot_id):
    return ordered([v for v in DB.vials.values() if v["drug_lot_id"] == lot_id])


def plan_encounters(plan_id, statuses=None, exclude_voided=False):
    rows = [e for e in DB.encounters.values() if e["treatment_plan_id"] == plan_id]
    if statuses is not None:
        rows = [e for e in rows if e["status"] in statuses]
    if exclude_voided:
        rows = [e for e in rows if e["status"] != "VOIDED"]
    return ordered(rows)


def encounter_order_key(enc):
    return (enc["encounter_datetime"], enc["created_at"], enc["_seq"])


def latest_non_voided_encounter(plan_id):
    rows = plan_encounters(plan_id, exclude_voided=True)
    if not rows:
        return None
    return sorted(rows, key=encounter_order_key)[-1]


def refresh_last_encounter(plan):
    """PRD 3.3: last_encounter_id is always the plan's non-VOIDED encounter with
    the greatest encounter_datetime. Returns True when the pointer moved."""
    newest = latest_non_voided_encounter(plan["id"])
    value = newest["id"] if newest else None
    if plan.get("last_encounter_id") == value:
        return False
    plan["last_encounter_id"] = value
    return True


# ------------------------------------------------- vial conservation (PRD 2.9)
VIAL_COUNTERS = (
    ("vials_on_hand", "IN_STOCK"),
    ("vials_reserved", "RESERVED"),
    ("vials_administered", "ADMINISTERED"),
    ("vials_quarantined", "QUARANTINED"),
    ("vials_returned", "RETURNED"),
    ("vials_expired", "EXPIRED"),
)


def recompute_lot_counters(lot):
    """Counters are always recomputed from vial statuses, never incremented."""
    vials = lot_vials(lot["id"])
    changed = False
    for field, status in VIAL_COUNTERS:
        count = sum(1 for v in vials if v["status"] == status)
        if lot.get(field) != count:
            lot[field] = count
            changed = True
    if changed:
        touch(lot)
    return lot


def recompute_endophthalmitis_count(lot):
    count = sum(
        1
        for ev in DB.adverse_events.values()
        if ev["source_drug_lot_id"] == lot["id"]
        and ev["event_type"] == "ENDOPHTHALMITIS"
        and ev["status"] == "ADJUDICATED_RELATED"
    )
    if lot.get("related_endophthalmitis_count") != count:
        lot["related_endophthalmitis_count"] = count
        touch(lot)
    return count


def reserve_vial(vial, encounter_id):
    vial["status"] = "RESERVED"
    vial["reserved_for_encounter_id"] = encounter_id
    vial["reserved_at"] = DB.clock
    touch(vial)
    recompute_lot_counters(DB.lots[vial["drug_lot_id"]])


def release_reserved_vial(encounter):
    """RESERVED -> IN_STOCK, clearing both reservation fields (PRD 3.5)."""
    vial = DB.vials.get(encounter.get("vial_id"))
    if vial is None or vial["status"] != "RESERVED":
        return
    vial["status"] = "IN_STOCK"
    vial["reserved_for_encounter_id"] = None
    vial["reserved_at"] = None
    touch(vial)
    recompute_lot_counters(DB.lots[vial["drug_lot_id"]])


# ----------------------------------------------- authorization usage (PRD 3.4)
def recompute_authorization_usage(pa):
    if pa is None:
        return
    used = sum(
        1
        for e in DB.encounters.values()
        if e.get("prior_authorization_id") == pa["id"] and e["status"] != "VOIDED"
    )
    changed = pa.get("injections_used") != used
    pa["injections_used"] = used
    approved = pa.get("approved_injections")
    if (
        pa["status"] == "EXHAUSTED"
        and approved is not None
        and used < approved
        and pa.get("expiration_date") is not None
        and DB.clock <= pa["expiration_date"]
    ):
        pa["status"] = "APPROVED"
        changed = True
    if changed:
        touch(pa)


def bump_authorization_usage(pa):
    """Encounter creation consumes one injection of the covering authorization."""
    pa["injections_used"] = int(pa.get("injections_used") or 0) + 1
    approved = pa.get("approved_injections")
    if approved is not None and pa["injections_used"] >= approved and pa["status"] == "APPROVED":
        pa["status"] = "EXHAUSTED"
    touch(pa)


# ------------------------------------------------ treat and extend (PRD 3.3)
def _extend_step(run_in):
    return EXTENSION_STEP_DAYS * 2 if run_in >= QUIESCENT_RUN_FOR_DOUBLE_STEP else EXTENSION_STEP_DAYS


def _interval_branch(plan, encounter, injections_after, run_in, interval_in):
    study = DB.imaging_studies[encounter["imaging_study_id"]]
    drug = DB.drugs[encounter["effective_drug_id"]]
    activity = study["disease_activity"]
    if injections_after < plan["loading_doses_required"]:
        new_interval = LOADING_INTERVAL_DAYS
        new_run = run_in + 1 if activity == "QUIESCENT" else 0
    elif activity == "QUIESCENT":
        step = _extend_step(run_in)
        base = interval_in if interval_in is not None else LOADING_INTERVAL_DAYS
        new_interval = min(base + step, drug["max_interval_days"])
        new_run = run_in + 1
    else:
        base = interval_in if interval_in is not None else LOADING_INTERVAL_DAYS
        new_interval = max(base - REDUCTION_STEP_DAYS, drug["min_interval_days"])
        new_run = 0
    return activity, new_interval, new_run


def advance_plan_on_documentation(plan, encounter):
    injections_after = int(plan["injections_administered"]) + 1
    run_in = int(plan["consecutive_quiescent_visits"])
    activity, new_interval, new_run = _interval_branch(
        plan, encounter, injections_after, run_in, plan.get("current_interval_days")
    )
    plan["current_interval_days"] = new_interval
    plan["consecutive_quiescent_visits"] = new_run
    plan["next_due_date"] = add_days(encounter["encounter_datetime"], new_interval)
    plan["injections_administered"] = injections_after
    plan["last_encounter_id"] = encounter["id"]

    status = plan["status"]
    if status == "LOADING":
        if injections_after >= plan["loading_doses_required"]:
            plan["status"] = "MAINTENANCE"
    elif status == "MAINTENANCE":
        if activity == "ACTIVE":
            plan["status"] = "INTENSIFIED"
    elif status == "INTENSIFIED":
        if activity == "QUIESCENT":
            plan["status"] = "MAINTENANCE"
    touch(plan)


def replay_plan_schedule(plan):
    """Re-derive the schedule from surviving encounters after a void (PRD 3.7)."""
    encounters = sorted(
        plan_encounters(plan["id"], statuses=ENCOUNTER_COUNTED), key=encounter_order_key
    )
    interval = plan.get("_activation_interval")
    next_due = plan.get("_activation_next_due")
    run = 0
    count = 0
    for enc in encounters:
        count += 1
        _activity, interval, run = _interval_branch(plan, enc, count, run, interval)
        next_due = add_days(enc["encounter_datetime"], interval)
    plan["injections_administered"] = count
    plan["consecutive_quiescent_visits"] = run
    plan["current_interval_days"] = interval
    if plan["status"] in ("SUSPENDED", "DISCONTINUED", "DRAFT"):
        plan["next_due_date"] = None
    else:
        plan["next_due_date"] = next_due
    last = latest_non_voided_encounter(plan["id"])
    plan["last_encounter_id"] = last["id"] if last else None
    touch(plan)


# ------------------------------------------------------- cascades (PRD 2.11)
def void_draft_encounters(plan, reason):
    """Release reservations held by the plan's DRAFT encounters and void them."""
    authorizations = []
    for enc in plan_encounters(plan["id"], statuses=("DRAFT",)):
        release_reserved_vial(enc)
        enc["status"] = "VOIDED"
        enc["void_reason"] = reason
        touch(enc)
        pa = DB.authorizations.get(enc.get("prior_authorization_id"))
        if pa is not None and pa not in authorizations:
            authorizations.append(pa)
    refresh_last_encounter(plan)
    for pa in authorizations:
        recompute_authorization_usage(pa)


def suspend_plan(plan, reason):
    plan["status"] = "SUSPENDED"
    plan["suspension_reason"] = reason
    plan["next_due_date"] = None
    touch(plan)
    void_draft_encounters(plan, "PLAN_SUSPENDED")


# --------------------------------------------- waterfall + margin (PRD 3.8)
def _enrollment_pool(claim, payer):
    pool = []
    for row in DB.enrollments.values():
        if row["patient_id"] != claim["patient_id"]:
            continue
        if row["status"] != "ACTIVE":
            continue
        if not (row["effective_date"] <= DB.clock <= row["expiration_date"]):
            continue
        if payer["federal_program"] and row["program_type"] == "MANUFACTURER_COPAY_CARD":
            continue
        pool.append(row)
    pool.sort(
        key=lambda a: (
            -(int(a["annual_benefit_cents"]) - int(a["benefit_used_cents"])),
            -int(a["per_encounter_cap_cents"]),
            a["created_at"],
            a["_seq"],
        )
    )
    return pool


def run_waterfall(claim, provisional):
    payer = DB.payers[claim["payer_id"]]

    if not provisional:
        previous = DB.enrollments.get(claim.get("assistance_enrollment_id"))
        prior_amount = int(claim.get("foundation_applied_cents") or 0)
        if previous is not None and prior_amount:
            previous["benefit_used_cents"] = int(previous["benefit_used_cents"]) - prior_amount
            if (
                previous["status"] == "EXHAUSTED"
                and previous["benefit_used_cents"] < previous["annual_benefit_cents"]
            ):
                previous["status"] = "ACTIVE"
            touch(previous)

    total_allowed = (
        int(claim["drug_allowed_cents"])
        + int(claim["wastage_allowed_cents"])
        + int(claim["admin_allowed_cents"])
    )
    coinsurance = cents(dec(total_allowed) * dec(payer["coinsurance_rate"]))

    pool = _enrollment_pool(claim, payer)
    enrollment = pool[0] if pool else None

    if enrollment is None:
        per_encounter_cap = 0
        remaining = 0
    else:
        if coinsurance >= FOUNDATION_HIGH_TIER_CENTS:
            per_encounter_cap = int(enrollment["per_encounter_cap_cents"])
        else:
            per_encounter_cap = cents(dec(enrollment["per_encounter_cap_cents"]) * LOW_TIER_CAP_FACTOR)
        remaining = int(enrollment["annual_benefit_cents"]) - int(enrollment["benefit_used_cents"])
        if remaining < 0:
            remaining = 0

    foundation = min(coinsurance, per_encounter_cap, remaining) if enrollment is not None else 0
    if foundation < 0:
        foundation = 0

    responsibility_pre = coinsurance - foundation
    small_balance = responsibility_pre if responsibility_pre <= WRITEOFF_THRESHOLD_CENTS else 0
    patient_responsibility = responsibility_pre - small_balance

    if provisional:
        payer_paid_total = total_allowed - coinsurance
    else:
        payer_paid_total = (
            int(claim["drug_paid_cents"])
            + int(claim["wastage_paid_cents"])
            + int(claim["admin_paid_cents"])
        )
    payer_shortfall = max(0, total_allowed - payer_paid_total - coinsurance)

    claim["total_allowed_cents"] = total_allowed
    claim["coinsurance_cents"] = coinsurance
    claim["assistance_enrollment_id"] = enrollment["id"] if enrollment is not None else None
    claim["foundation_applied_cents"] = foundation
    claim["patient_responsibility_cents"] = patient_responsibility
    claim["practice_writeoff_cents"] = small_balance + payer_shortfall

    if enrollment is not None:
        enrollment["benefit_used_cents"] = int(enrollment["benefit_used_cents"]) + foundation
        if enrollment["benefit_used_cents"] >= int(enrollment["annual_benefit_cents"]):
            if enrollment["status"] == "ACTIVE":
                enrollment["status"] = "EXHAUSTED"
        if foundation:
            touch(enrollment)


def claim_lines_terminal(claim):
    return claim["drug_line_status"] in ("PAID", "WRITTEN_OFF") and claim["admin_line_status"] in (
        "PAID",
        "DENIED",
    )


def finalize_claim_margin(claim):
    encounter = DB.encounters[claim["injection_encounter_id"]]
    vial = DB.vials.get(encounter.get("vial_id"))
    acquisition = 0
    if vial is not None:
        lot = DB.lots.get(vial["drug_lot_id"])
        if lot is not None:
            acquisition = int(lot["unit_acquisition_cost_cents"])
    claim["actual_acquisition_cost_cents"] = acquisition
    claim["realized_margin_cents"] = (
        int(claim["drug_paid_cents"])
        + int(claim["wastage_paid_cents"])
        + int(claim["admin_paid_cents"])
        + int(claim["patient_responsibility_cents"])
        + int(claim["foundation_applied_cents"])
        - acquisition
    )
    if encounter["status"] == "BILLED":
        encounter["status"] = "CLOSED"
        touch(encounter)


def expire_stale_enrollments(patient_id):
    """Lazy PENDING/ACTIVE -> EXPIRED edge, fired at claim creation (PRD 3.8)."""
    for row in ordered(DB.enrollments.values()):
        if row["patient_id"] != patient_id:
            continue
        if row["status"] in ("PENDING", "ACTIVE") and row["expiration_date"] < DB.clock:
            row["status"] = "EXPIRED"
            touch(row)


# ------------------------------------------------------- lot exposure (3.5)
def carrying_exposure_cents(lot, days_held):
    value = int(lot["vials_on_hand"]) * int(lot["unit_acquisition_cost_cents"])
    raw = (
        dec(value)
        * (dec(CARRYING_RATE_BASIS_POINTS) / dec(10000))
        * dec(days_held)
        / dec(DAYS_PER_YEAR)
    )
    return cents(raw)


def lot_exposure(lot, basis):
    unit_cost = int(lot["unit_acquisition_cost_cents"])
    days_held = whole_days(lot["received_date"], DB.clock)
    if basis == "CARRYING":
        unconsumed = int(lot["vials_on_hand"])
        return {
            "drug_lot_id": lot["id"],
            "basis": basis,
            "days_held": days_held,
            "unconsumed_vials": unconsumed,
            "unconsumed_value_cents": unconsumed * unit_cost,
            "exposure_cents": carrying_exposure_cents(lot, days_held),
            "projected_burn_vials": 0,
            "at_risk_vials": 0,
        }

    lower = DB.clock - timedelta(days=BURN_WINDOW_DAYS)
    burned = 0
    for vial in DB.vials.values():
        if vial["status"] != "ADMINISTERED" or vial.get("administered_at") is None:
            continue
        vial_lot = DB.lots.get(vial["drug_lot_id"])
        if vial_lot is None or vial_lot["drug_id"] != lot["drug_id"]:
            continue
        if lower <= vial["administered_at"] < DB.clock:
            burned += 1
    days_to_expiry = max(0, whole_days(DB.clock, lot["expiration_date"]))
    projected = (burned * days_to_expiry) // BURN_WINDOW_DAYS
    unconsumed = int(lot["vials_on_hand"]) + int(lot["vials_reserved"])
    at_risk = max(0, unconsumed - projected)
    return {
        "drug_lot_id": lot["id"],
        "basis": basis,
        "days_held": days_held,
        "unconsumed_vials": unconsumed,
        "unconsumed_value_cents": unconsumed * unit_cost,
        "exposure_cents": at_risk * unit_cost,
        "projected_burn_vials": projected,
        "at_risk_vials": at_risk,
    }


# ---------------------------------------------- adverse event reportability
def apply_reportability(event, encounter):
    days = whole_days(encounter["encounter_datetime"], event["onset_datetime"])
    reportable = (
        (event["event_type"] == "ENDOPHTHALMITIS" and days <= ENDOPHTHALMITIS_WINDOW_DAYS)
        or event["severity"] == "SEVERE"
        or event["culture_result"] == "POSITIVE"
    )
    event["days_post_injection"] = days
    event["reportable"] = reportable
    if reportable:
        window = SEVERE_REPORT_DAYS if event["severity"] == "SEVERE" else ROUTINE_REPORT_DAYS
        event["fda_report_due_date"] = add_days(event["onset_datetime"], window)
    else:
        event["fda_report_due_date"] = None


# ------------------------------------------------------ billing units split
def billing_units_split(drug, dose_ml):
    if drug["vial_type"] == "SINGLE_DOSE":
        wasted_ml = round_half_up(dec(drug["vial_fill_ml"]) - dec(dose_ml), 3)
    else:
        wasted_ml = round_half_up(0, 3)
    administered_mg = dec(dose_ml) * dec(drug["mg_per_ml"])
    wasted_mg = dec(wasted_ml) * dec(drug["mg_per_ml"])
    unit_mg = dec(drug["billing_unit_mg"])
    administered_units = int(round_half_up(administered_mg / unit_mg, 0))
    wasted_units = int(round_half_up(wasted_mg / unit_mg, 0))
    return wasted_ml, administered_units, wasted_units, administered_units + wasted_units


def assemble_modifiers(encounter, drug, wasted_units):
    modifiers = ["RT" if encounter["eye"] == "OD" else "LT"]
    if drug["vial_type"] == "SINGLE_DOSE":
        modifiers.append("JW" if wasted_units > 0 else "JZ")
    return modifiers


# --------------------------------------------- recall notification planning
def generate_recall_notifications(recall, lot):
    from core import base_row

    exposed = []
    for enc in DB.encounters.values():
        if enc["status"] not in ENCOUNTER_COUNTED:
            continue
        vial = DB.vials.get(enc.get("vial_id"))
        if vial is None or vial["drug_lot_id"] != lot["id"]:
            continue
        exposed.append(enc)
    exposed.sort(key=encounter_order_key)
    for enc in exposed:
        patient = DB.patients[enc["patient_id"]]
        row = base_row()
        row.update(
            {
                "lot_recall_id": recall["id"],
                "patient_id": enc["patient_id"],
                "injection_encounter_id": enc["id"],
                "channel": patient["notification_channel"],
                "status": "PENDING",
                "sent_at": None,
                "acknowledged_at": None,
                "attempt_note": None,
            }
        )
        DB.notifications[row["id"]] = row
    recall["notifications_required"] = len(exposed)


def recount_notifications(recall):
    rows = [n for n in DB.notifications.values() if n["lot_recall_id"] == recall["id"]]
    recall["notifications_acknowledged"] = sum(1 for n in rows if n["status"] == "ACKNOWLEDGED")
    recall["notifications_unreachable"] = sum(1 for n in rows if n["status"] == "UNREACHABLE")


def open_recall_for_lot(lot_id):
    for row in ordered(DB.recalls.values()):
        if row["drug_lot_id"] == lot_id and row["status"] != "CLOSED":
            return row
    return None


def quarantine_lot_vials(lot, statuses):
    for vial in lot_vials(lot["id"]):
        if vial["status"] in statuses:
            vial["status"] = "QUARANTINED"
            touch(vial)
    recompute_lot_counters(lot)
