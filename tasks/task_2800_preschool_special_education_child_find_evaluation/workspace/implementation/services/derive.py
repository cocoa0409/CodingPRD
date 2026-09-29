"""Derived (computed) field resolution and entity serialisers.

Every `source: computed` field is re-derived from the live store on read, so a
clock move or a cascade is always reflected on the next read.
"""
from db import clock_date, common_fields, db, fmt_date, fmt_dt, ordered
from services import calc


# --- collection helpers ----------------------------------------------------
def slots_of_event(event_id):
    return [s for s in db.screening_slots.values() if s["screening_event_id"] == event_id]


def assessments_of_case(case_id):
    return ordered(
        [a for a in db.domain_assessments.values() if a["evaluation_case_id"] == case_id]
    )


def completed_assessments_of_case(case_id):
    return [a for a in assessments_of_case(case_id) if a["status"] == "COMPLETED"]


def lines_of_plan(plan_id):
    return ordered([l for l in db.service_lines.values() if l["service_plan_id"] == plan_id])


def plans_of_child(child_id):
    return ordered([p for p in db.service_plans.values() if p["child_id"] == child_id])


def cases_of_child(child_id):
    return ordered([c for c in db.evaluation_cases.values() if c["child_id"] == child_id])


def referrals_of_child(child_id):
    return ordered([r for r in db.referrals.values() if r["child_id"] == child_id])


def cases_of_referral(referral_id):
    return ordered([c for c in db.evaluation_cases.values() if c["referral_id"] == referral_id])


def consents_of_referral(referral_id):
    return ordered([c for c in db.consent_records.values() if c["referral_id"] == referral_id])


def in_scope_staffed_lines(provider_id, counted_plan_states):
    result = []
    for line in db.service_lines.values():
        if line["provider_id"] != provider_id or line["status"] != "STAFFED":
            continue
        plan = db.service_plans.get(line["service_plan_id"])
        if plan is None or plan["status"] not in counted_plan_states:
            continue
        result.append(line)
    return result


# --- computed scalars ------------------------------------------------------
def site_reserved_seats(site_id):
    return sum(
        1
        for p in db.service_plans.values()
        if p.get("community_site_id") == site_id
        and p["status"] in calc.SEAT_HOLDING_PLAN_STATES
    )


def event_booked_count(event_id):
    return sum(1 for s in slots_of_event(event_id) if s["status"] in calc.BOOKED_SLOT_STATES)


def provider_active_evaluation_count(provider_id):
    return sum(
        1
        for c in db.evaluation_cases.values()
        if c["chair_provider_id"] == provider_id
        and c["status"] in calc.CASE_NON_TERMINAL_STATUSES
    )


def provider_interpreter_count(provider_id):
    return sum(
        1
        for r in db.consent_records.values()
        if r.get("interpreter_provider_id") == provider_id
        and r["decision"] in ("PENDING", "GRANTED")
    )


def provider_capacity(provider, counted_plan_states=None):
    states = counted_plan_states or calc.COUNTED_PLAN_STATES_PROJECTED
    return calc.provider_minutes(in_scope_staffed_lines(provider["id"], states))


def plan_assigned_minutes(plan_id):
    return sum(
        l["weekly_minutes"]
        for l in lines_of_plan(plan_id)
        if l["status"] in ("PROPOSED", "STAFFED", "UNSTAFFED")
    )


def child_status(child_id):
    plans = plans_of_child(child_id)
    if any(p["status"] == "EXITED_TO_KINDERGARTEN" for p in plans):
        return "EXITED_TO_KINDERGARTEN"
    if any(p["status"] == "ACTIVE" for p in plans):
        return "SERVED"
    if any(p["status"] == "DECLINED" for p in plans):
        return "SERVICES_DECLINED"
    if any(p["status"] == "CLOSED_NOT_ELIGIBLE" for p in plans):
        return "NOT_ELIGIBLE"
    if any(c["status"] in calc.CASE_NON_TERMINAL_STATUSES for c in cases_of_child(child_id)):
        return "IN_EVALUATION"
    if any(p["status"] in ("DRAFT", "PENDING_PARENT_CONSENT") for p in plans):
        return "IN_EVALUATION"
    if any(
        r["intake_status"] in ("RECEIVED", "CONSENT_PENDING", "EVALUATION_AUTHORIZED")
        for r in referrals_of_child(child_id)
    ):
        return "REFERRED"
    return "NO_ACTIVE_REFERRAL"


def referral_due_date(referral):
    """The pinned CONSENT_ANCHORED due date, retained across a revocation."""
    return referral.get("evaluation_due_date")


def case_due_date(case):
    referral = db.referrals.get(case["referral_id"])
    if referral is None:
        return None
    return referral_due_date(referral)


def case_profile(case, variant=None):
    variant = variant or calc.pinned_variant(case["assessment_protocol"])
    return calc.composite_profile(completed_assessments_of_case(case["id"]), variant)


# --- serialisers -----------------------------------------------------------
def child_out(row):
    data = common_fields(row)
    data.update(
        {
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "date_of_birth": fmt_date(row["date_of_birth"]),
            "guardian_full_name": row["guardian_full_name"],
            "district_of_residence": row["district_of_residence"],
            "primary_language_code": row["primary_language_code"],
            "interpreter_required": row["primary_language_code"] != "en",
            "part_c_enrolled": row["part_c_enrolled"],
            "part_c_exit_date": fmt_date(row.get("part_c_exit_date")),
            "third_birthday": fmt_date(calc.third_birthday(row["date_of_birth"])),
            "kindergarten_eligibility_date": fmt_date(
                calc.kindergarten_eligibility_date(row["date_of_birth"])
            ),
            "status": child_status(row["id"]),
        }
    )
    return data


def site_out(row):
    data = common_fields(row)
    data.update(
        {
            "name": row["name"],
            "region_code": row["region_code"],
            "licensed_capacity": row["licensed_capacity"],
            "iep_seat_capacity": row["iep_seat_capacity"],
            "reserved_iep_seat_count": site_reserved_seats(row["id"]),
            "languages_supported": list(row["languages_supported"]),
            "screening_host_approved": row["screening_host_approved"],
            "status": row["status"],
        }
    )
    return data


def provider_out(row):
    minutes = provider_capacity(row)
    active = provider_active_evaluation_count(row["id"])
    data = common_fields(row)
    data.update(
        {
            "full_name": row["full_name"],
            "discipline": row["discipline"],
            "languages": list(row["languages"]),
            "home_region_code": row["home_region_code"],
            "status": row["status"],
            "max_weekly_service_minutes": row["max_weekly_service_minutes"],
            "direct_weekly_service_minutes": minutes["direct_weekly_service_minutes"],
            "travel_overhead_minutes": minutes["travel_overhead_minutes"],
            "assigned_weekly_service_minutes": minutes["assigned_weekly_service_minutes"],
            "service_capacity_posture": calc.service_capacity_posture(
                minutes["assigned_weekly_service_minutes"], row["max_weekly_service_minutes"]
            ),
            "max_evaluation_caseload": row["max_evaluation_caseload"],
            "active_evaluation_count": active,
            "evaluation_intake_posture": calc.evaluation_intake_posture(
                active, row["max_evaluation_caseload"]
            ),
            "max_weekly_interpreter_assignments": row["max_weekly_interpreter_assignments"],
            "assigned_interpreter_assignment_count": provider_interpreter_count(row["id"]),
            "is_evaluation_chair_eligible": row["discipline"]
            in calc.CHAIR_ELIGIBLE_DISCIPLINES,
        }
    )
    return data


def event_out(row):
    data = common_fields(row)
    data.update(
        {
            "site_id": row["site_id"],
            "event_label": row["event_label"],
            "window_start_utc": fmt_dt(row["window_start_utc"]),
            "window_end_utc": fmt_dt(row["window_end_utc"]),
            "slot_length_minutes": row["slot_length_minutes"],
            "slot_capacity": row["slot_capacity"],
            "effective_slot_capacity": calc.effective_slot_capacity(
                row["slot_capacity"],
                row["slot_length_minutes"],
                row["window_start_utc"],
                row["window_end_utc"],
            ),
            "booked_slot_count": event_booked_count(row["id"]),
            "interpreter_languages": list(row["interpreter_languages"]),
            "status": row["status"],
        }
    )
    return data


def slot_out(row):
    data = common_fields(row)
    data.update(
        {
            "screening_event_id": row["screening_event_id"],
            "child_id": row["child_id"],
            "slot_start_utc": fmt_dt(row["slot_start_utc"]),
            "slot_end_utc": fmt_dt(row["slot_end_utc"]),
            "requested_language_code": row["requested_language_code"],
            "status": row["status"],
            "screening_result": row.get("screening_result"),
        }
    )
    return data


def referral_out(row):
    data = common_fields(row)
    data.update(
        {
            "child_id": row["child_id"],
            "source": row["source"],
            "referring_provider_npi": row.get("referring_provider_npi"),
            "originating_screening_slot_id": row.get("originating_screening_slot_id"),
            "received_at": fmt_dt(row["received_at"]),
            "age_months_at_referral": row["age_months_at_referral"],
            "eligibility_pathway": row["eligibility_pathway"],
            "intake_status": row["intake_status"],
            "consent_status": row["consent_status"],
            "consent_granted_at": fmt_dt(row.get("consent_granted_at")),
            "evaluation_due_date": fmt_date(referral_due_date(row)),
            "superseded_by_referral_id": row.get("superseded_by_referral_id"),
        }
    )
    return data


def consent_out(row):
    data = common_fields(row)
    data.update(
        {
            "referral_id": row["referral_id"],
            "kind": row["kind"],
            "requested_at": fmt_dt(row["requested_at"]),
            "decision": row["decision"],
            "decided_at": fmt_dt(row.get("decided_at")),
            "notice_language_code": row["notice_language_code"],
            "notice_delivery_method": row["notice_delivery_method"],
            "interpreter_provider_id": row.get("interpreter_provider_id"),
            "interpreter_modality": row.get("interpreter_modality"),
            "service_plan_id": row.get("service_plan_id"),
        }
    )
    return data


def case_out(row):
    profile = case_profile(row)
    due = case_due_date(row)
    data = common_fields(row)
    data.update(
        {
            "referral_id": row["referral_id"],
            "child_id": row["child_id"],
            "chair_provider_id": row["chair_provider_id"],
            "assessment_protocol": row["assessment_protocol"],
            "required_domain_count": row["required_domain_count"],
            "completed_domain_count": profile["completed_domain_count"],
            "qualifying_domain_count": profile["qualifying_domain_count"],
            "max_weighted_percent_delay": calc.as_number(
                profile["max_weighted_percent_delay"]
            ),
            "composite_eligibility_recommendation": profile[
                "composite_eligibility_recommendation"
            ],
            "recommended_weekly_minutes": profile["per_line_rounded_minutes"],
            "revision_round": row["revision_round"],
            "report_narrative_summary": row.get("report_narrative_summary"),
            "report_drafted_at": fmt_dt(row.get("report_drafted_at")),
            "last_revision_note": row.get("last_revision_note"),
            "due_date": fmt_date(due),
            "timeline_compliance": calc.timeline_compliance(
                row["status"],
                due,
                clock_date(),
                row["_determined_at"].date() if row.get("_determined_at") else None,
            ),
            "status": row["status"],
        }
    )
    return data


def assessment_out(row):
    data = common_fields(row)
    data.update(
        {
            "evaluation_case_id": row["evaluation_case_id"],
            "evaluator_provider_id": row["evaluator_provider_id"],
            "assessment_site_id": row.get("assessment_site_id"),
            "domain": row["domain"],
            "method": row["method"],
            "window_start_utc": fmt_dt(row["window_start_utc"]),
            "window_end_utc": fmt_dt(row["window_end_utc"]),
            "chronological_age_months": row["chronological_age_months"],
            "age_equivalent_months": row.get("age_equivalent_months"),
            "standard_score": row.get("standard_score"),
            "percent_delay": calc.as_number(row.get("percent_delay")),
            "weighted_percent_delay": calc.as_number(row.get("weighted_percent_delay")),
            "qualifies_delay": row["qualifies_delay"],
            "invalidation_reason": row.get("invalidation_reason"),
            "completed_at": fmt_dt(row.get("completed_at")),
            "status": row["status"],
        }
    )
    return data


def plan_out(row):
    data = common_fields(row)
    data.update(
        {
            "evaluation_case_id": row["evaluation_case_id"],
            "child_id": row["child_id"],
            "community_site_id": row.get("community_site_id"),
            "eligibility_decision": row["eligibility_decision"],
            "disability_category": row.get("disability_category"),
            "setting": row.get("setting"),
            "override_justification": row.get("override_justification"),
            "recommended_weekly_minutes": row["recommended_weekly_minutes"],
            "assigned_weekly_minutes": plan_assigned_minutes(row["id"]),
            "determined_by_user_id": row["determined_by_user_id"],
            "start_date": fmt_date(row.get("start_date")),
            "exit_date": fmt_date(row.get("exit_date")),
            "kindergarten_transition_status": row["kindergarten_transition_status"],
            "transition_conference_date": fmt_date(row.get("transition_conference_date")),
            "receiving_school_code": row.get("receiving_school_code"),
            "status": row["status"],
        }
    )
    return data


def line_out(row):
    data = common_fields(row)
    data.update(
        {
            "service_plan_id": row["service_plan_id"],
            "provider_id": row.get("provider_id"),
            "delivery_site_id": row.get("delivery_site_id"),
            "discipline": row["discipline"],
            "weekly_minutes": row["weekly_minutes"],
            "delivery_model": row["delivery_model"],
            "status": row["status"],
        }
    )
    return data
