"""Cascading side effects (PRD §2.5, §3.1, §3.6, §3.7, §3.8).

Every affected resource gets its own `updated_at` refresh and its own `version`
bump, one per mutation.
"""

import db
from services import common


def void_unit_acquisitions(unit, stamp=None):
    """Every PhantomTest of the unit still ACQUIRED becomes VOIDED."""
    for test in common.unit_phantom_tests(unit["id"]):
        if test["result_status"] == "ACQUIRED":
            common.set_field(test, "result_status", "VOIDED", stamp)


def out_of_service_unit_equipment(unit, stamp=None):
    for item in common.unit_equipment(unit["id"]):
        if item["equipment_status"] == "ACTIVE":
            common.set_field(item, "equipment_status", "OUT_OF_SERVICE", stamp)


def expire_plans(facility, only_open=False, stamp=None):
    for plan in common.facility_plans(facility["id"]):
        if only_open:
            if plan["plan_status"] != "OPEN":
                continue
        if plan["plan_status"] in ("ACCEPTED", "EXPIRED"):
            continue
        plan["plan_status"] = "EXPIRED"
        plan["deadline_status"] = "OVERDUE"
        common.touch(plan, stamp)


def defer_unit(unit, stamp=None):
    """System transition ENROLLED -> DEFERRED plus the whole cascade."""
    if unit["unit_status"] == "ENROLLED":
        common.set_field(unit, "unit_status", "DEFERRED", stamp)
    facility = common.facility_of_unit(unit)
    out_of_service_unit_equipment(unit, stamp)
    if facility is not None:
        expire_plans(facility, stamp=stamp)
        common.recompute_enrolled_unit_count(facility)
        for _unit in common.facility_units(facility["id"]):
            common.recompute_deficiency_open_count(_unit)
    void_unit_acquisitions(unit, stamp)
    common.recompute_phantom_counts(unit)


def suspend_facility(facility, stamp=None):
    facility["facility_status"] = "SUSPENDED"
    facility["accreditation_currency"] = "SUSPENDED"
    facility["payer_participation_status"] = "REVOKED"
    for unit in common.facility_units(facility["id"]):
        if unit["unit_status"] == "ENROLLED":
            defer_unit(unit, stamp)
    common.recompute_enrolled_unit_count(facility)


def reject_scheduled_surveys(facility, rejection_code, stamp=None, statuses=("SCHEDULED",)):
    for survey in common.facility_surveys(facility["id"]):
        if survey["survey_status"] in statuses:
            survey["survey_status"] = "REJECTED"
            survey["rejection_code"] = rejection_code
            common.touch(survey, stamp)


def lapse_facility(facility, stamp=None):
    """The widest cascade: a rejected renewal."""
    facility["accreditation_currency"] = "LAPSED"
    facility["facility_status"] = "DEFERRED"
    for unit in common.facility_units(facility["id"]):
        defer_unit(unit, stamp)
    for item in common.facility_equipment(facility["id"]):
        if item["equipment_status"] == "ACTIVE":
            common.set_field(item, "equipment_status", "OUT_OF_SERVICE", stamp)
    for unit in common.facility_units(facility["id"]):
        void_unit_acquisitions(unit, stamp)
        common.recompute_phantom_counts(unit)
    expire_plans(facility, stamp=stamp)
    reject_scheduled_surveys(facility, "DOCUMENTATION_INCOMPLETE", stamp)
    common.recompute_enrolled_unit_count(facility)
    common.recompute_rejected_survey_count(facility)


def extend_all_deadlines(facility, days, stamp=None):
    """Renewal-window opening pushes every deadline of the facility forward."""
    # A deadline that has never been established is not an extension target: it
    # has to stay unset rather than materialize as a moved null.
    for unit in common.facility_units(facility["id"]):
        for field in ("clinical_deadline_at", "testing_deadline_at"):
            if unit.get(field) is not None:
                unit[field] = db.extend_deadline(unit[field], days)
        common.touch(unit, stamp)
    for plan in common.facility_plans(facility["id"]):
        for field in ("due_at", "resubmission_deadline_at"):
            if plan.get(field) is not None:
                plan[field] = db.extend_deadline(plan[field], days)
        common.touch(plan, stamp)


def reject_qualification_surveys(qualification, statuses, stamp=None):
    facility = db.FACILITIES.get(qualification["facility_id"])
    for survey in db.SURVEYS.values():
        if survey["physicist_qualification_id"] != qualification["id"]:
            continue
        if survey["survey_status"] in statuses:
            survey["survey_status"] = "REJECTED"
            survey["rejection_code"] = "CREDENTIAL_LAPSED"
            common.touch(survey, stamp)
    if facility is not None:
        common.recompute_rejected_survey_count(facility)


def expire_lapsed_credentials(stamp=None):
    """System transition: VERIFIED -> LAPSED once the clock reaches the expiry."""
    for qualification in list(db.QUALIFICATIONS.values()):
        if qualification["credential_status"] != "VERIFIED":
            continue
        expires_on = db.parse_ts(qualification["credential_expires_on"])
        if expires_on is not None and expires_on <= db.now():
            qualification["credential_status"] = "LAPSED"
            common.touch(qualification, stamp)
            facility = db.FACILITIES.get(qualification["facility_id"])
            if facility is not None:
                reject_surveys_named_by(facility, qualification, ("SUBMITTED",), "CREDENTIAL_LAPSED", stamp)
                common.recompute_rejected_survey_count(facility)
                common.recompute_roster_disposition(facility)
                for unit in common.facility_units(facility["id"]):
                    common.recompute_deficiency_open_count(unit)


def reject_surveys_named_by(facility, qualification, statuses, rejection_code, stamp=None):
    for survey in common.facility_surveys(facility["id"]):
        if survey["physicist_qualification_id"] != qualification["id"]:
            continue
        if survey["survey_status"] in statuses:
            survey["survey_status"] = "REJECTED"
            survey["rejection_code"] = rejection_code
            common.touch(survey, stamp)


def expire_plans_by_clock(stamp=None):
    """OPEN plans past due_at and SUBMITTED plans past resubmission_deadline_at."""
    for plan in list(db.PLANS.values()):
        if plan["plan_status"] not in ("OPEN", "SUBMITTED"):
            continue
        due_days = common.days_remaining_until(plan.get("due_at"))
        deadline_days = common.days_remaining_until(plan.get("resubmission_deadline_at"))
        if plan["plan_status"] == "OPEN" and due_days is not None and due_days < 0:
            _expire_plan(plan, stamp)
            continue
        if plan["plan_status"] == "SUBMITTED" and deadline_days is not None and deadline_days < 0:
            _expire_plan(plan, stamp)


def _expire_plan(plan, stamp=None):
    plan["plan_status"] = "EXPIRED"
    plan["deadline_status"] = "OVERDUE"
    common.touch(plan, stamp)
    facility = db.FACILITIES.get(plan["facility_id"])
    if facility is None:
        return
    facility["payer_participation_status"] = "AT_RISK"
    source = db.SUBMISSIONS.get(plan["source_submission_id"])
    if source is not None:
        unit = db.MODALITY_UNITS.get(source["unit_id"])
        if unit is not None:
            common.recompute_deficiency_open_count(unit)


def run_clock_cascades(stamp=None):
    """Re-evaluate every credential expiry, plan deadline and plan expiry."""
    expire_lapsed_credentials(stamp)
    expire_plans_by_clock(stamp)
    for facility in db.FACILITIES.values():
        common.recompute_all_deadline_statuses(facility["id"])
    for plan in db.PLANS.values():
        if plan["plan_status"] != "EXPIRED":
            common.recompute_deadline_status(plan)