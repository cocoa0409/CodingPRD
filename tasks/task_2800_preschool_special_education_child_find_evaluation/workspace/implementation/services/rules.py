"""Shared ladder rungs (existence, ownership, language access) and cascades."""
from db import clock_date, db, now_utc, touch
from errors import ApiError
from middleware import current_role, current_user_id
from services import calc, derive

NOT_FOUND = {
    "children": "ERR_CHILD_NOT_FOUND",
    "community_sites": "ERR_COMMUNITY_SITE_NOT_FOUND",
    "providers": "ERR_PROVIDER_NOT_FOUND",
    "screening_events": "ERR_SCREENING_EVENT_NOT_FOUND",
    "screening_slots": "ERR_SCREENING_SLOT_NOT_FOUND",
    "referrals": "ERR_REFERRAL_NOT_FOUND",
    "consent_records": "ERR_CONSENT_RECORD_NOT_FOUND",
    "evaluation_cases": "ERR_EVALUATION_CASE_NOT_FOUND",
    "domain_assessments": "ERR_DOMAIN_ASSESSMENT_NOT_FOUND",
    "service_plans": "ERR_SERVICE_PLAN_NOT_FOUND",
    "service_lines": "ERR_SERVICE_LINE_NOT_FOUND",
}


# --- rungs 4 and 5: existence ---------------------------------------------
def fetch(collection, row_id):
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection], "%s '%s' does not exist" % (collection, row_id))
    return row


def fetch_optional_fk(collection, row_id):
    if row_id is None:
        return None
    return fetch(collection, row_id)


# --- rung 6: guardian ownership -------------------------------------------
def require_guardian(child_id):
    if current_role() != "Parent":
        return
    if current_user_id() != child_id:
        raise ApiError(
            "ERR_NOT_CHILD_GUARDIAN", "Caller does not hold educational rights for this child"
        )


# --- rungs 7 and 8: assignment ownership ----------------------------------
def require_assigned_evaluator(assessment):
    if current_role() != "Evaluator":
        return
    if current_user_id() != assessment["evaluator_provider_id"]:
        raise ApiError(
            "ERR_NOT_ASSIGNED_EVALUATOR", "Caller is not the assigned evaluator of this assessment"
        )


def require_case_chair(case):
    if current_role() != "EvaluationChair":
        return
    if current_user_id() != case["chair_provider_id"]:
        raise ApiError("ERR_NOT_CASE_CHAIR", "Caller is not the chair of this evaluation case")


# --- rung 14: language access on parent notices ---------------------------
def require_language_access(child, notice_language_code, interpreter):
    if child["primary_language_code"] == "en":
        return
    home_language = child["primary_language_code"]
    if notice_language_code == home_language:
        return
    if (
        interpreter is not None
        and interpreter["discipline"] == "INTERPRETER"
        and home_language in interpreter["languages"]
    ):
        return
    raise ApiError(
        "ERR_INTERPRETER_NOT_PROVIDED",
        "Notice must be written in '%s' or name an interpreter covering it" % home_language,
    )


# --- rung 38: interpreter availability ------------------------------------
def require_interpreter_available(interpreter):
    if interpreter is None:
        return
    count = derive.provider_interpreter_count(interpreter["id"])
    if count >= interpreter["max_weekly_interpreter_assignments"]:
        raise ApiError(
            "ERR_INTERPRETER_UNAVAILABLE",
            "Interpreter has no remaining assignment capacity this week",
        )


# --- rung 18 --------------------------------------------------------------
def require_provider_active(provider):
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE", "Provider status is not ACTIVE")


# --- rung 20 --------------------------------------------------------------
def require_site_placement_eligible(site, child):
    if site["status"] != "ACTIVE":
        raise ApiError("ERR_SITE_NOT_ELIGIBLE", "Community site status is not ACTIVE")
    if child["primary_language_code"] not in site["languages_supported"]:
        raise ApiError(
            "ERR_SITE_NOT_ELIGIBLE",
            "Community site does not support the child's primary language",
        )


# --- cascades -------------------------------------------------------------
def discontinue_plan_lines(plan):
    """ServicePlan terminal cascade: hops 2-4."""
    for line in derive.lines_of_plan(plan["id"]):
        if line["status"] not in ("PROPOSED", "STAFFED", "UNSTAFFED"):
            continue
        was_staffed = line["status"] == "STAFFED"
        provider_id = line.get("provider_id")
        line["status"] = "DISCONTINUED"
        touch(line)
        if was_staffed and provider_id and provider_id in db.providers:
            touch(db.providers[provider_id])


def cancel_case(case):
    """EvaluationCase -> CANCELLED cascade (hops 3 and 4)."""
    if case["status"] in ("ELIGIBILITY_DETERMINED", "CANCELLED"):
        return
    case["status"] = "CANCELLED"
    touch(case)
    for assessment in derive.assessments_of_case(case["id"]):
        if assessment["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        assessment["status"] = "INVALIDATED"
        assessment["invalidation_reason"] = "CASE_CANCELLED"
        touch(assessment)


def cancel_cases_of_referral(referral):
    for case in derive.cases_of_referral(referral["id"]):
        cancel_case(case)


def supersede_prior_referrals(child_id, new_referral_id):
    for referral in derive.referrals_of_child(child_id):
        if referral["id"] == new_referral_id:
            continue
        if referral["intake_status"] not in (
            "RECEIVED",
            "CONSENT_PENDING",
            "EVALUATION_AUTHORIZED",
        ):
            continue
        previous = referral["intake_status"]
        referral["intake_status"] = "SUPERSEDED"
        referral["superseded_by_referral_id"] = new_referral_id
        touch(referral)
        if previous == "CONSENT_PENDING":
            for record in derive.consents_of_referral(referral["id"]):
                if record["decision"] == "PENDING":
                    record["decision"] = "REFUSED"
                    record["decided_at"] = now_utc()
                    touch(record)
        if previous == "EVALUATION_AUTHORIZED":
            cancel_cases_of_referral(referral)


def refresh_case_status_after_assessment_change(case):
    """Keep the case status consistent with the live completed-domain count."""
    profile = derive.case_profile(case)
    completed = profile["completed_domain_count"]
    if case["status"] == "IN_PROGRESS" and completed >= case["required_domain_count"]:
        case["status"] = "DOMAINS_COMPLETE"
        touch(case)
    elif case["status"] == "DOMAINS_COMPLETE" and completed < case["required_domain_count"]:
        case["status"] = "IN_PROGRESS"
        touch(case)


def create_referral(child, source, npi, originating_slot_id):
    """Shared by manual intake and the system referral behind a REFER outcome."""
    from db import base_row

    received_at = now_utc()
    age_months, pathway = calc.referral_age_and_pathway(
        child["date_of_birth"], received_at, child["part_c_enrolled"]
    )
    row = base_row()
    row.update(
        {
            "child_id": child["id"],
            "source": source,
            "referring_provider_npi": npi,
            "originating_screening_slot_id": originating_slot_id,
            "received_at": received_at,
            "age_months_at_referral": age_months,
            "eligibility_pathway": pathway,
            "intake_status": "RECEIVED",
            "consent_status": "NOT_REQUESTED",
            "consent_granted_at": None,
            "evaluation_due_date": None,
            "superseded_by_referral_id": None,
        }
    )
    db.referrals[row["id"]] = row
    supersede_prior_referrals(child["id"], row["id"])
    return row


def evaluator_window_conflict(evaluator_provider_id, site_id, start, end, exclude_case=None):
    from datetime import timedelta

    for other in db.domain_assessments.values():
        if other["evaluator_provider_id"] != evaluator_provider_id:
            continue
        if other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        other_site = other.get("assessment_site_id") or calc.DISTRICT_CENTER
        this_site = site_id or calc.DISTRICT_CENTER
        buffer = timedelta(
            minutes=0 if other_site == this_site else calc.EVALUATOR_BUFFER_MINUTES
        )
        if start < other["window_end_utc"] + buffer and other["window_start_utc"] < end + buffer:
            return True
    return False


def site_event_overlap(site_id, start, end):
    for event in db.screening_events.values():
        if event["site_id"] != site_id or event["status"] == "CANCELLED":
            continue
        if start < event["window_end_utc"] and event["window_start_utc"] < end:
            return True
    return False


def projected_provider_minutes(provider, line, delivery_site_id):
    """Minutes the provider would carry if `line` were staffed to them."""
    lines = [
        l
        for l in derive.in_scope_staffed_lines(provider["id"], calc.COUNTED_PLAN_STATES_PROJECTED)
        if l["id"] != line["id"]
    ]
    lines.append(
        {
            "weekly_minutes": line["weekly_minutes"],
            "delivery_model": line["delivery_model"],
            "delivery_site_id": delivery_site_id,
        }
    )
    return calc.provider_minutes(lines)


def grant_evaluation_consent(referral):
    referral["consent_status"] = "GRANTED"
    referral["consent_granted_at"] = now_utc()
    referral["intake_status"] = "EVALUATION_AUTHORIZED"
    child = db.children.get(referral["child_id"])
    referral["evaluation_due_date"] = calc.evaluation_due_date(
        "GRANTED",
        referral["consent_granted_at"],
        referral["eligibility_pathway"],
        calc.third_birthday(child["date_of_birth"]) if child else None,
    )
    touch(referral)


def resolve_child_of_referral(referral_id):
    referral = db.referrals.get(referral_id)
    return referral["child_id"] if referral else None
