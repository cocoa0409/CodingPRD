"""Shared helpers: record construction, validation, counters, aggregation."""

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import fail

# --------------------------------------------------------------------------
# Enumerations declared by the PRD
# --------------------------------------------------------------------------

ENUMS = {
    "facility_type": {"HOSPITAL", "IMAGING_CENTER", "MOBILE_UNIT"},
    "facility_status": {"PENDING", "ENROLLED", "DEFERRED", "SUSPENDED"},
    "accreditation_currency": {"PROVISIONAL", "CURRENT", "LAPSED", "SUSPENDED"},
    "payer_participation_status": {"ACTIVE", "AT_RISK", "REVOKED"},
    "roster_disposition": {"CLEAR", "HOLD", "HALT"},
    "modality_code": {"MRI", "CT", "MAMM", "PET", "US"},
    "unit_status": {"ENROLLED", "DEFERRED", "WITHDRAWN"},
    "equipment_status": {"ACTIVE", "OUT_OF_SERVICE", "RETIRED"},
    "performance_verdict": {"PASS", "FAIL", "PENDING"},
    "image_type": {"CLINICAL", "PHANTOM_REFERENCE"},
    "review_status": {"PENDING_REVIEW", "ACCEPTED", "DEFICIENCY", "FAILED", "RESUBMITTED"},
    "deficiency_code": {"NONE", "IMAGE_QUALITY", "POSITIONING", "ARTIFACT", "DOSE"},
    "plan_deficiency_code": {"IMAGE_QUALITY", "POSITIONING", "ARTIFACT", "DOSE"},
    "result_status": {"ACQUIRED", "SCORED", "PASS", "FAIL", "VOIDED"},
    "survey_type": {"ANNUAL", "INITIAL", "POST_REPAIR"},
    "survey_status": {
        "SCHEDULED", "SUBMITTED", "ACCEPTED", "REJECTED",
        "CORRECTIVE_REQUIRED", "RESUBMITTED",
    },
    "rejection_code": {
        "NONE", "CREDENTIAL_LAPSED", "DOSE_OUT_OF_RANGE",
        "SHIELDING_FAILED", "DOCUMENTATION_INCOMPLETE",
    },
    "shielding_verdict": {"PASS", "FAIL"},
    "personnel_role": {"INTERPRETING_PHYSICIAN", "TECHNOLOGIST", "MEDICAL_PHYSICIST"},
    "credential_status": {"PENDING", "VERIFIED", "LAPSED", "REVOKED"},
    "plan_status": {"OPEN", "SUBMITTED", "ACCEPTED", "REJECTED", "EXPIRED"},
    "deadline_status": {"ON_TRACK", "DUE_SOON", "OVERDUE"},
    "cycle_status": {"PENDING", "ACTIVE", "RENEWAL_DUE", "RENEWED", "LAPSED"},
    "benchmark_submission_status": {"NOT_STARTED", "PARTIAL", "COMPLETE", "OVERDUE"},
    "audit_selection_status": {"NOT_APPLICABLE", "SELECTED", "WAIVED"},
    "audit_outcome": {"PENDING", "PASS", "FAIL"},
    "exam_category_code": {"CT_HEAD", "CT_ABDOMEN", "MAMM_SCREEN", "PET_TORSO"},
    "benchmark_status": {"NOT_EVALUATED", "WITHIN_BENCHMARK", "ABOVE_BENCHMARK", "CRITICAL"},
    "submission_status": {"STAGED", "SUBMITTED", "REJECTED"},
}

# --------------------------------------------------------------------------
# Serialisation field classification
# --------------------------------------------------------------------------

DATE_FIELDS = {
    "created_at", "updated_at", "clinical_deadline_at", "testing_deadline_at",
    "last_survey_at", "installed_on", "submitted_at", "deficiency_issued_at",
    "deficiency_deadline_at", "acquired_at", "scored_at", "scheduled_at",
    "performed_at", "credential_expires_on", "qualification_verified_at",
    "due_at", "resubmission_deadline_at", "cycle_started_at", "cycle_expires_at",
    "exam_month",
}

NUMERIC_FIELDS = {
    "last_phantom_score", "review_outcome_score", "spatial_resolution_score",
    "contrast_score", "artifact_score", "phantom_total_score",
    "reference_entrance_dose_mgy", "measured_entrance_dose_mgy",
    "dose_deviation_pct", "ce_credit_hours", "required_ce_hours",
    "dose_index_value", "benchmark_comparison_value", "dose_benchmark_average",
}


# Fields whose reported form is shrunk to a stated number of significant digits.
SIG_DIGIT_FIELDS = {"dose_benchmark_average": 6}


def serialize(record):
    if record is None:
        return None
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        if value is None:
            out[key] = None
        elif key in DATE_FIELDS:
            if isinstance(value, str) and "." not in value:
                out[key] = value
            else:
                out[key] = db.fmt_ts(value)
        elif key in SIG_DIGIT_FIELDS:
            out[key] = six_sig(value)
        elif key in NUMERIC_FIELDS:
            out[key] = float(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def serialize_many(records):
    return [serialize(r) for r in records]


# --------------------------------------------------------------------------
# Record construction
# --------------------------------------------------------------------------

def make_record(**fields):
    stamp = db.now()
    record = dict(fields)
    record.setdefault("created_at", stamp)
    record.setdefault("updated_at", stamp)
    record.setdefault("version", 1)
    return record


def touch(record, stamp=None):
    """Refresh updated_at and advance version by exactly one."""
    record["updated_at"] = stamp or db.now()
    record["version"] = record.get("version", 1) + 1


def set_field(record, name, value, stamp=None):
    record[name] = value
    touch(record, stamp)


def body():
    from flask import request
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def require_fields(payload, names):
    for name in names:
        if name not in payload or payload[name] is None:
            fail("ERR_INVALID_REQUEST", f"missing required field: {name}")


def check_enum(payload, name, enum_key, required=False):
    if name not in payload or payload[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", f"missing required field: {name}")
        return
    if payload[name] not in ENUMS[enum_key]:
        fail("ERR_INVALID_REQUEST", f"invalid value for {name}")


def check_required_enum(payload, name, enum_key):
    check_enum(payload, name, enum_key, required=True)


def as_int(payload, name):
    try:
        return int(payload[name])
    except (TypeError, ValueError, KeyError):
        fail("ERR_INVALID_REQUEST", f"{name} must be an integer")


def occ_version(payload, field_name, required):
    if field_name not in payload or payload[field_name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", f"missing required field: {field_name}")
        return None
    try:
        return int(payload[field_name])
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", f"{field_name} must be an integer")


def enforce_version(parent, payload, field_name, required=True):
    supplied = occ_version(payload, field_name, required)
    if supplied is None:
        return
    if supplied != parent["version"]:
        fail("ERR_STALE_VERSION", "the supplied version does not match the stored version")


def rounded2(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def six_sig(value):
    if value is None:
        return None
    return float(f"{float(value):.6g}")


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def get_facility(facility_id):
    facility = db.FACILITIES.get(facility_id)
    if facility is None:
        fail("ERR_FACILITY_NOT_FOUND", "facility not found")
    return facility


def get_unit(unit_id, facility_id=None):
    unit = db.MODALITY_UNITS.get(unit_id)
    if unit is None:
        fail("ERR_UNIT_NOT_FOUND", "modality unit not found")
    if facility_id is not None and unit["facility_id"] != facility_id:
        fail("ERR_UNIT_NOT_FOUND", "modality unit not found")
    return unit


def get_equipment(equipment_id):
    item = db.EQUIPMENT.get(equipment_id)
    if item is None:
        fail("ERR_EQUIPMENT_NOT_FOUND", "equipment item not found")
    return item


def get_submission(submission_id):
    record = db.SUBMISSIONS.get(submission_id)
    if record is None:
        fail("ERR_SUBMISSION_NOT_FOUND", "clinical image submission not found")
    return record


def get_phantom_test(phantom_test_id):
    record = db.PHANTOM_TESTS.get(phantom_test_id)
    if record is None:
        fail("ERR_PHANTOM_TEST_NOT_FOUND", "phantom test not found")
    return record


def get_survey(survey_id):
    record = db.SURVEYS.get(survey_id)
    if record is None:
        fail("ERR_SURVEY_NOT_FOUND", "physicist survey not found")
    return record


def get_qualification(qualification_id):
    record = db.QUALIFICATIONS.get(qualification_id)
    if record is None:
        fail("ERR_QUALIFICATION_NOT_FOUND", "personnel qualification not found")
    return record


def get_plan(plan_id):
    record = db.PLANS.get(plan_id)
    if record is None:
        fail("ERR_PLAN_NOT_FOUND", "corrective action plan not found")
    return record


def get_cycle(cycle_id):
    record = db.CYCLES.get(cycle_id)
    if record is None:
        fail("ERR_CYCLE_NOT_FOUND", "accreditation cycle not found")
    return record


def get_record(record_id):
    record = db.DOSE_RECORDS.get(record_id)
    if record is None:
        fail("ERR_RECORD_NOT_FOUND", "dose registry record not found")
    return record


def facility_units(facility_id):
    return [u for u in db.MODALITY_UNITS.values() if u["facility_id"] == facility_id]


def facility_equipment(facility_id):
    unit_ids = {u["id"] for u in facility_units(facility_id)}
    return [e for e in db.EQUIPMENT.values() if e["unit_id"] in unit_ids]


def unit_equipment(unit_id):
    return [e for e in db.EQUIPMENT.values() if e["unit_id"] == unit_id]


def facility_plans(facility_id):
    return [p for p in db.PLANS.values() if p["facility_id"] == facility_id]


def facility_surveys(facility_id):
    return [s for s in db.SURVEYS.values() if s["facility_id"] == facility_id]


def facility_qualifications(facility_id):
    return [q for q in db.QUALIFICATIONS.values() if q["facility_id"] == facility_id]


def facility_cycles(facility_id):
    return [c for c in db.CYCLES.values() if c["facility_id"] == facility_id]


def unit_phantom_tests(unit_id):
    return [t for t in db.PHANTOM_TESTS.values() if t["unit_id"] == unit_id]


def unit_submissions(unit_id):
    return [s for s in db.SUBMISSIONS.values() if s["unit_id"] == unit_id]


def facility_of_unit(unit):
    return db.FACILITIES.get(unit["facility_id"])


# --------------------------------------------------------------------------
# Counters — always recomputed from their definition, never incremented blindly
# --------------------------------------------------------------------------

def recompute_enrolled_unit_count(facility):
    units = facility_units(facility["id"])
    facility["enrolled_unit_count"] = sum(
        1 for u in units if u["unit_status"] == "ENROLLED"
    )
    facility["deferred_unit_count"] = sum(
        1 for u in units if u["unit_status"] == "DEFERRED"
    )


def recompute_rejected_survey_count(facility):
    facility["rejected_survey_count"] = sum(
        1 for s in facility_surveys(facility["id"]) if s["survey_status"] == "REJECTED"
    )


def recompute_phantom_counts(unit):
    tests = unit_phantom_tests(unit["id"])
    unit["phantom_attempt_count"] = sum(
        1 for t in tests if t["result_status"] in ("SCORED", "PASS", "FAIL")
    )
    unit["phantom_failure_count"] = sum(
        1 for t in tests if t["result_status"] == "FAIL"
    )


def recompute_deficiency_open_count(unit):
    """Recompute the unit's open-plan count without touching the aggregate."""
    count = 0
    for plan in db.PLANS.values():
        if plan["plan_status"] not in ("OPEN", "SUBMITTED"):
            continue
        source = db.SUBMISSIONS.get(plan["source_submission_id"])
        if source is not None and source["unit_id"] == unit["id"]:
            count += 1
    unit["deficiency_open_count"] = count
    return count


def recompute_survey_count(qualification):
    qualification["survey_count"] = sum(
        1 for s in db.SURVEYS.values()
        if s["physicist_qualification_id"] == qualification["id"]
        and s["survey_status"] != "REJECTED"
    )


def recompute_roster_disposition(facility):
    facility["roster_disposition"] = roster_disposition(facility["id"])
    return facility["roster_disposition"]


def roster_disposition(facility_id):
    included = []
    for q in facility_qualifications(facility_id):
        status = q["credential_status"]
        if status in ("PENDING", "VERIFIED", "LAPSED", "REVOKED"):
            included.append(q)
        elif q["personnel_role"] == "MEDICAL_PHYSICIST" and status == "LAPSED":
            included.append(q)
    if any(q["credential_status"] == "REVOKED" for q in included):
        return "HALT"
    lapsed = sum(1 for q in included if q["credential_status"] == "LAPSED")
    if lapsed >= 2:
        return "HALT"
    if lapsed == 1:
        return "HOLD"
    if sum(1 for q in included if q["credential_status"] == "PENDING") >= 3:
        return "HOLD"
    return "CLEAR"


def clinical_role_qualifications_unverified(facility_id):
    for q in facility_qualifications(facility_id):
        if q["personnel_role"] in ("INTERPRETING_PHYSICIAN", "TECHNOLOGIST"):
            if q["credential_status"] != "VERIFIED":
                return True
    return False


def has_revoked_qualification(facility_id):
    return any(
        q["credential_status"] == "REVOKED"
        for q in facility_qualifications(facility_id)
    )


def has_overdue_plan(facility_id):
    for plan in facility_plans(facility_id):
        if recompute_deadline_status(plan) == "OVERDUE":
            return True
    return False


def has_pending_plan(facility_id):
    return any(
        p["plan_status"] in ("OPEN", "SUBMITTED")
        for p in facility_plans(facility_id)
    )


def days_remaining_until(target):
    """Whole days between an instant and the current logical clock.

    Elapsed seconds are divided by 86400 and truncated toward zero, so a
    deadline that has passed by less than a whole day still counts as zero
    days remaining — the whole-day variant of the deadline rule.
    """
    if target is None:
        return None
    remaining = (db.parse_ts(target) - db.now()).total_seconds()
    # Truncation toward zero, not floor: a deadline that has passed by less
    # than a whole day still leaves a whole-day count of zero.
    return int(remaining / 86400)


def recompute_deadline_status(plan):
    """corrective_action_deadline — whole days, truncated toward zero.

    A plan that has already expired keeps whatever value it last computed.
    """
    if plan["plan_status"] == "EXPIRED" and plan.get("deadline_status") is not None:
        return plan["deadline_status"]
    due_at = db.parse_ts(plan["due_at"])
    if due_at is None:
        return plan.get("deadline_status")
    days_remaining = days_remaining_until(plan["due_at"])
    derived = "OVERDUE" if days_remaining < 0 else ("DUE_SOON" if days_remaining <= 10 else "ON_TRACK")
    plan["deadline_status"] = derived
    return derived


def recompute_all_deadline_statuses(facility_id):
    for plan in facility_plans(facility_id):
        recompute_deadline_status(plan)


def current_cycle(facility):
    index = facility.get("current_cycle_index") or 0
    for cycle in facility_cycles(facility["id"]):
        if cycle["cycle_index"] == index:
            return cycle
    return None


def plan_resubmission_round_has_status(plan, statuses):
    """The clinical image submissions answering this plan's source submission."""
    source_id = plan["source_submission_id"]
    current = db.SUBMISSIONS.get(source_id)
    while current is not None:
        if current["review_status"] in statuses:
            return True
        parent_id = current.get("resubmission_of_submission_id")
        current = db.SUBMISSIONS.get(parent_id) if parent_id else None
    return False


def settle_facility_time(facility):
    """Bring a facility's date-governed posture up to date against the clock.

    Re-derived on every re-read: a corrective action plan that has fallen due,
    and a credential that has reached its expiry, are both movements the
    workflow performs on its own.
    """
    for plan in db.PLANS.values():
        if plan["facility_id"] != facility["id"]:
            continue
        if plan["plan_status"] not in ("OPEN", "SUBMITTED"):
            continue
        due_days = days_remaining_until(plan.get("due_at"))
        deadline_days = days_remaining_until(plan.get("resubmission_deadline_at"))
        if plan["plan_status"] == "OPEN" and due_days is not None and due_days < 0:
            expire_plan(plan)
        elif plan["plan_status"] == "SUBMITTED" and deadline_days is not None and deadline_days < 0:
            expire_plan(plan)
    for qualification in db.QUALIFICATIONS.values():
        if qualification["facility_id"] != facility["id"]:
            continue
        if qualification["credential_status"] != "VERIFIED":
            continue
        expires_on = db.parse_ts(qualification["credential_expires_on"])
        if expires_on is None or expires_on > db.now():
            continue
        qualification["credential_status"] = "LAPSED"
        touch(qualification)
        reject_surveys_by(facility, qualification, ("SUBMITTED",), "CREDENTIAL_LAPSED")
        recompute_rejected_survey_count(facility)
        recompute_roster_disposition(facility)
        for unit in facility_units(facility["id"]):
            recompute_deficiency_open_count(unit)
    recompute_roster_disposition(facility)


def expire_plan(plan):
    """System transition: an unanswered plan expires against the clock."""
    plan["plan_status"] = "EXPIRED"
    plan["deadline_status"] = "OVERDUE"
    touch(plan)
    facility = db.FACILITIES.get(plan["facility_id"])
    if facility is None:
        return
    facility["payer_participation_status"] = "AT_RISK"
    source = db.SUBMISSIONS.get(plan["source_submission_id"])
    if source is not None:
        unit = db.MODALITY_UNITS.get(source["unit_id"])
        if unit is not None:
            recompute_deficiency_open_count(unit)


def reject_surveys_by(facility, qualification, statuses, rejection_code):
    for survey in facility_surveys(facility["id"]):
        if survey["physicist_qualification_id"] != qualification["id"]:
            continue
        if survey["survey_status"] in statuses:
            survey["survey_status"] = "REJECTED"
            survey["rejection_code"] = rejection_code
            touch(survey)


def unit_active_or_oos_equipment_exists(unit_id):
    return any(
        e["equipment_status"] in ("ACTIVE", "OUT_OF_SERVICE")
        for e in unit_equipment(unit_id)
    )