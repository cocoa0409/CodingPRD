"""The fifteen declared calculations (PRD 3.x, scaffold 1.3).

Every calculation reads the logical clock and recomputes from scratch; no
derived quantity is ever incrementally patched.
"""

import math
from datetime import datetime, timedelta

from money import half_of, pct_of, self_pay_total
from store import db, ordered

# --- queue_priority_score
ACUITY_POINT_WEIGHT = 100
ON_TIME_APPOINTMENT_BONUS = 250
LATE_GRACE_MINUTES = 10
WAIT_CREDIT_CAP_MINUTES = 180
AGE_BUMP_POINTS = 60
PEDIATRIC_AGE_MONTHS = 24
GERIATRIC_AGE_MONTHS = 780
PRIORITY_SCORE_CAP = 1000

# --- wait_time_estimate
AVG_VISIT_MINUTES = 20
APPOINTMENT_BLEND_MINUTES = 10
WAIT_CAP_MINUTES = 120

# --- queue lifecycle
ABANDON_AFTER_MINUTES = 120
ARRIVAL_EARLY_MINUTES = 15
ARRIVAL_LATE_MINUTES = 10
APPOINTMENT_SPACING_MINUTES = 30

# --- pricing
SERVICE_PRICE_CENTS = {
    "RAPID_STREP_TEST": 3500,
    "URINALYSIS": 2800,
    "INJECTION_ADMIN": 4200,
    "EKG": 6500,
}
SERVICE_CODES = ("RAPID_STREP_TEST", "URINALYSIS", "INJECTION_ADMIN", "EKG")
SELF_PAY_BALANCE_CEILING_CENTS = 50000

# --- oversight
MAX_CHANGE_CYCLES = 2
MAX_TRANSMIT_ATTEMPTS = 3

# --- vocabularies
COMPLAINT_CODES = (
    "SORE_THROAT",
    "EAR_PAIN",
    "UTI",
    "RASH",
    "FLU_LIKE",
    "SPORTS_PHYSICAL",
)
THERAPY_CLASSES = (
    "ANTIBIOTIC_BETA_LACTAM",
    "ANTIBIOTIC_MACROLIDE",
    "ANALGESIC_NSAID",
    "ANTIHISTAMINE",
    "CONTROLLED_OPIOID",
)
CONTROLLED_CLASS = "CONTROLLED_OPIOID"


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def state_rule_for(state_code):
    for row in ordered(db.state_rules.values()):
        if row["state_code"] == state_code:
            return row
    return None


def protocol_for(complaint_code, state_code):
    """The single Protocol offering this complaint in this state."""
    for row in ordered(db.protocols.values()):
        if row["complaint_code"] == complaint_code and state_code in row[
            "allowed_state_codes"
        ]:
            return row
    return None


def assessment_for_visit(visit_id):
    for row in ordered(db.assessments.values()):
        if row["visit_id"] == visit_id:
            return row
    return None


def visits_for_queue_entry(queue_entry_id):
    return [
        v for v in ordered(db.visits.values())
        if v["queue_entry_id"] == queue_entry_id
    ]


def active_assignment_at(clinic_id, clinician_id):
    for row in ordered(db.assignments.values()):
        if (
            row["clinic_id"] == clinic_id
            and row["clinician_id"] == clinician_id
            and row["status"] == "ACTIVE"
        ):
            return row
    return None


def active_assignment_of(clinician_id):
    for row in ordered(db.assignments.values()):
        if row["clinician_id"] == clinician_id and row["status"] == "ACTIVE":
            return row
    return None


# ---------------------------------------------------------------------------
# patient_age_months_at_visit
# ---------------------------------------------------------------------------

def age_months(date_of_birth, at_instant=None):
    """Whole months from a calendar date of birth to the logical clock."""
    moment = at_instant if at_instant is not None else db.clock
    dob = datetime.strptime(date_of_birth, "%Y-%m-%d")
    months = (moment.year - dob.year) * 12 + (moment.month - dob.month)
    if moment.day < dob.day:
        months = months - 1
    return months


# ---------------------------------------------------------------------------
# visit_eligibility_screening
# ---------------------------------------------------------------------------

def effective_min_age_months(protocol, state_rule):
    return max(
        protocol["min_age_months"],
        state_rule["min_independent_practice_age_months"],
    )


def age_in_scope(age, protocol, state_rule):
    floor = effective_min_age_months(protocol, state_rule)
    return age >= floor and age <= protocol["max_age_months"]


# ---------------------------------------------------------------------------
# queue_priority_score
# ---------------------------------------------------------------------------

def queue_priority_score(entry):
    clinic = db.clinics.get(entry["clinic_id"])
    patient = db.patients.get(entry["patient_id"])

    tier = entry.get("acuity_tier")
    if tier is None and clinic is not None:
        protocol = protocol_for(entry["complaint_code"], clinic["state_code"])
        tier = protocol["acuity_tier"] if protocol is not None else 0
    acuity_points = ACUITY_POINT_WEIGHT * (tier or 0)

    appointment_points = 0
    if (
        entry["kind"] == "APPOINTMENT"
        and entry.get("arrived_at") is not None
        and entry.get("scheduled_at") is not None
    ):
        grace = entry["scheduled_at"] + timedelta(minutes=LATE_GRACE_MINUTES)
        if entry["arrived_at"] <= grace:
            appointment_points = ON_TIME_APPOINTMENT_BONUS

    wait_points = 0
    if entry.get("arrived_at") is not None:
        elapsed = (db.clock - entry["arrived_at"]).total_seconds()
        if elapsed < 0:
            elapsed = 0
        whole_minutes = int(elapsed // 60)
        wait_points = min(WAIT_CREDIT_CAP_MINUTES, whole_minutes)

    age_points = 0
    if patient is not None:
        months = age_months(patient["date_of_birth"])
        if months < PEDIATRIC_AGE_MONTHS or months >= GERIATRIC_AGE_MONTHS:
            age_points = AGE_BUMP_POINTS

    total = acuity_points + appointment_points + wait_points + age_points
    return min(PRIORITY_SCORE_CAP, total)


# ---------------------------------------------------------------------------
# call_next_selection
# ---------------------------------------------------------------------------

def call_next_selection(clinic_id):
    candidates = [
        e for e in ordered(db.queue_entries.values())
        if e["clinic_id"] == clinic_id and e["status"] == "WAITING"
    ]
    if not candidates:
        return None
    live = dict(
        (entry["id"], queue_priority_score(entry)) for entry in candidates
    )

    def key(entry):
        return (
            -live[entry["id"]],
            entry["arrived_at"],
            entry["created_at"],
            entry["_seq"],
        )

    return sorted(candidates, key=key)[0]


# ---------------------------------------------------------------------------
# wait_time_estimate
# ---------------------------------------------------------------------------

def posted_wait_minutes(clinic):
    waiting = clinic["waiting_count"]
    on_duty = max(1, clinic["on_duty_clinician_count"])
    horizon = db.clock + timedelta(minutes=60)
    appts_next_hour = 0
    for entry in db.queue_entries.values():
        if (
            entry["clinic_id"] == clinic["id"]
            and entry["kind"] == "APPOINTMENT"
            and entry["status"] == "SCHEDULED"
            and entry.get("scheduled_at") is not None
            and db.clock <= entry["scheduled_at"] < horizon
        ):
            appts_next_hour += 1
    projected = (
        int(math.ceil(waiting / float(on_duty))) * AVG_VISIT_MINUTES
        + APPOINTMENT_BLEND_MINUTES * appts_next_hour
    )
    return min(WAIT_CAP_MINUTES, projected)


def realized_wait_minutes(entry):
    if entry.get("arrived_at") is None or entry.get("called_at") is None:
        return None
    elapsed = (entry["called_at"] - entry["arrived_at"]).total_seconds()
    if elapsed < 0:
        elapsed = 0
    return int(elapsed // 60)


# ---------------------------------------------------------------------------
# referral_trigger_evaluation
# ---------------------------------------------------------------------------

def referral_trigger_evaluation(assessment, protocol):
    """Returns (destination, reason) or (None, None).  Positional precedence."""
    observed = set(assessment.get("red_flag_codes") or [])
    declared = set(protocol.get("red_flag_codes") or [])
    if observed & declared:
        return ("EMERGENCY_DEPARTMENT", "RED_FLAG")
    if assessment["spo2_pct"] < protocol["min_spo2_pct"]:
        return ("EMERGENCY_DEPARTMENT", "HYPOXIA")
    if float(assessment["temp_c"]) >= float(protocol["max_temp_c"]):
        return ("URGENT_CARE", "FEVER_THRESHOLD")
    if assessment["heart_rate_bpm"] > protocol["max_heart_rate_bpm"]:
        return ("URGENT_CARE", "TACHYCARDIA")
    return (None, None)


# ---------------------------------------------------------------------------
# visit_price_quote
# ---------------------------------------------------------------------------

def insured_quote(base_price_cents, copay_cents, coinsurance_pct):
    remainder = base_price_cents - copay_cents
    return copay_cents + pct_of(remainder, coinsurance_pct)


def self_pay_quote(base_price_cents):
    return self_pay_total(base_price_cents)


# ---------------------------------------------------------------------------
# visit_price_final
# ---------------------------------------------------------------------------

def billed_lines(protocol, services_rendered, referred):
    if referred:
        return [half_of(protocol["base_price_cents"])]
    lines = [protocol["base_price_cents"]]
    for service in services_rendered or []:
        lines.append(SERVICE_PRICE_CENTS[service])
    return lines


def visit_price_final(visit, protocol, services_rendered, referred):
    lines = billed_lines(protocol, services_rendered, referred)
    total_allowed = sum(lines)
    if visit["self_pay"]:
        final_price = self_pay_total(total_allowed)
        return (final_price, final_price, 0)
    coinsurance = visit["coinsurance_pct"] or 0
    copay = visit["copay_cents"] or 0
    per_line = [pct_of(price, coinsurance) for price in lines]
    patient = min(total_allowed, copay + sum(per_line))
    return (total_allowed, patient, total_allowed - patient)


# ---------------------------------------------------------------------------
# chart_review_sampling
# ---------------------------------------------------------------------------

def sampling_plan(clinic, state_rule, window_start, window_end):
    """Returns (ordered list of (visit, reason)) for the run."""
    eligible = []
    for visit in ordered(db.visits.values()):
        if visit["clinic_id"] != clinic["id"]:
            continue
        if visit["clinical_status"] != "CLOSED":
            continue
        if not (window_start <= visit["created_at"] < window_end):
            continue
        if assessment_for_visit(visit["id"]) is None:
            continue
        if any(
            review["visit_id"] == visit["id"]
            for review in db.chart_reviews.values()
        ):
            continue
        eligible.append(visit)

    mandatory = []
    for visit in eligible:
        if visit["referral_required"]:
            mandatory.append((visit, "MANDATORY_REFERRAL"))
            continue
        controlled = any(
            rx["visit_id"] == visit["id"]
            and rx["status"] == "ROUTED"
            and rx["therapy_class"] == CONTROLLED_CLASS
            for rx in db.prescriptions.values()
        )
        if controlled:
            mandatory.append((visit, "CONTROLLED_RX"))

    mandatory_ids = set(visit["id"] for visit, _ in mandatory)
    target_total = int(
        math.ceil(len(eligible) * state_rule["chart_review_sample_pct"] / 100.0)
    )
    random_count = max(0, target_total - len(mandatory))

    pool = [v for v in eligible if v["id"] not in mandatory_ids]

    def rank(visit):
        protocol = db.protocols.get(visit["protocol_id"])
        tier = protocol["acuity_tier"] if protocol is not None else 0
        return (-tier, visit["created_at"], visit["_seq"])

    picked = sorted(pool, key=rank)[:random_count]
    selected = list(mandatory) + [(v, "RANDOM_SAMPLE") for v in picked]
    return (eligible, mandatory, picked, selected)


# ---------------------------------------------------------------------------
# float_coverage_selection
# ---------------------------------------------------------------------------

def overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap: adjacency does not overlap."""
    return a_start < b_end and b_start < a_end


def float_coverage_selection(clinic, covered):
    candidates = []
    for clinician in ordered(db.clinicians.values()):
        if not clinician["float_eligible"]:
            continue
        if clinician["scope_hold"]:
            continue
        if clinician["license_state_code"] != clinic["state_code"]:
            continue
        if clinician["id"] == covered["clinician_id"]:
            continue
        blocked = False
        for assignment in db.assignments.values():
            if assignment["clinician_id"] != clinician["id"]:
                continue
            if assignment["status"] not in ("SCHEDULED", "ACTIVE"):
                continue
            if overlaps(
                assignment["starts_at"],
                assignment["ends_at"],
                covered["starts_at"],
                covered["ends_at"],
            ):
                blocked = True
                break
        if blocked:
            continue
        candidates.append(clinician)

    if not candidates:
        return None

    def rank(clinician):
        home_flag = 0 if clinician["home_clinic_id"] == clinic["id"] else 1
        return (
            home_flag,
            clinician["active_assignment_count"],
            clinician["created_at"],
            clinician["_seq"],
        )

    return sorted(candidates, key=rank)[0]


# ---------------------------------------------------------------------------
# reviewer_reassignment_selection
# ---------------------------------------------------------------------------

def effective_supervision_cap(physician, state_rule):
    return min(
        physician["max_supervised_clinicians"],
        state_rule["max_supervised_clinicians_per_physician"],
    )


def reviewer_reassignment_selection(review, clinic, state_rule, assessment):
    cosigner = assessment.get("cosigned_by_physician_id") if assessment else None
    candidates = []
    for physician in ordered(db.physicians.values()):
        if physician["status"] != "ACTIVE":
            continue
        if clinic["state_code"] not in physician["licensed_state_codes"]:
            continue
        if physician["id"] == review["reviewer_physician_id"]:
            continue
        if cosigner is not None and physician["id"] == cosigner:
            continue
        if physician["current_supervised_count"] >= effective_supervision_cap(
            physician, state_rule
        ):
            continue
        candidates.append(physician)

    if not candidates:
        return None

    def rank(physician):
        return (
            physician["current_supervised_count"],
            physician["created_at"],
            physician["_seq"],
        )

    return sorted(candidates, key=rank)[0]


# ---------------------------------------------------------------------------
# summary_destination_selection
# ---------------------------------------------------------------------------

def summary_destination_selection(patient):
    address = patient.get("pcp_direct_address")
    if address is not None and patient.get("pcp_accepts_electronic_summary"):
        return ("DIRECT_MESSAGE", address)
    if address is not None:
        return ("FAX", address)
    return ("PATIENT_PORTAL", None)


# ---------------------------------------------------------------------------
# physician_supervision_load
# ---------------------------------------------------------------------------

def physician_supervision_load(physician_id):
    clinician_ids = set()
    for assignment in db.assignments.values():
        if assignment["pinned_supervising_physician_id"] != physician_id:
            continue
        if assignment["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        clinician_ids.add(assignment["clinician_id"])
    return len(clinician_ids)


def clinician_active_assignment_count(clinician_id):
    total = 0
    for assignment in db.assignments.values():
        if assignment["clinician_id"] != clinician_id:
            continue
        if assignment["status"] in ("SCHEDULED", "ACTIVE"):
            total += 1
    return total


# ---------------------------------------------------------------------------
# patient_outstanding_balance
# ---------------------------------------------------------------------------

def patient_outstanding_balance(patient_id):
    total = 0
    for visit in db.visits.values():
        if visit["patient_id"] != patient_id:
            continue
        if visit["billing_status"] != "INVOICED":
            continue
        total += visit["patient_responsibility_cents"] or 0
    return total


def patient_active_therapy_classes(patient_id):
    classes = set()
    for rx in db.prescriptions.values():
        if rx["patient_id"] != patient_id:
            continue
        if rx["status"] == "ROUTED":
            classes.add(rx["therapy_class"])
    return sorted(classes)
