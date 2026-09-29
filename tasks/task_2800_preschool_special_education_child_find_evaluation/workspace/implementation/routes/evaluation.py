"""The multidisciplinary evaluation, its report loop and the determination
(PRD sections 3.5, 3.6 and 3.7)."""
from flask import Blueprint

from db import base_row, db, now_utc, touch
from errors import ApiError
from middleware import current_user_id, endpoint
from response import object_response
from routes.common import matches, paged
from services import calc, derive, rules
from validation import (
    ASSESSMENT_PROTOCOL,
    ASSESSMENT_STATUS,
    CASE_STATUS,
    DISABILITY_CATEGORY,
    DOMAIN,
    ELIGIBILITY_DECISION,
    METHOD,
    SETTING,
    TIMELINE_COMPLIANCE,
    bad,
    body,
    opt_enum,
    opt_id,
    opt_number,
    opt_str,
    q_enum,
    q_str,
    req_datetime,
    req_enum,
    req_id,
    req_int,
    req_str,
)

bp = Blueprint("evaluation", __name__)

CASE_READ_ROLES = (
    "ChildFindCoordinator",
    "EvaluationChair",
    "Evaluator",
    "PlacementAdministrator",
    "DistrictAdmin",
)


@bp.post("/referrals/<referral_id>/evaluation-cases")
@endpoint("ChildFindCoordinator", "DistrictAdmin")
def open_case(referral_id):
    data = body()
    chair_id = req_id(data, "chair_provider_id")
    protocol = opt_enum(data, "assessment_protocol", ASSESSMENT_PROTOCOL, "STANDARDIZED")

    referral = rules.fetch("referrals", referral_id)        # rung 4
    chair = rules.fetch("providers", chair_id)              # rung 5

    if chair["discipline"] not in calc.CHAIR_ELIGIBLE_DISCIPLINES:      # rung 9
        raise ApiError(
            "ERR_CHAIR_NOT_ELIGIBLE",
            "Discipline %s may not chair an evaluation" % chair["discipline"],
        )

    # rung 11, carve-out B: the intake dimension is inspected only when consent
    # actually reads GRANTED; otherwise rung 13 answers instead.
    if referral["consent_status"] == "GRANTED":
        if referral["intake_status"] != "EVALUATION_AUTHORIZED":
            raise ApiError(
                "ERR_INVALID_REFERRAL_STATE",
                "Referral intake_status is %s" % referral["intake_status"],
            )
    else:
        raise ApiError(                                                  # rung 13
            "ERR_CONSENT_NOT_GRANTED",
            "Referral consent_status is %s; evaluation may not begin"
            % referral["consent_status"],
        )

    rules.require_provider_active(chair)                                 # rung 18

    count = derive.provider_active_evaluation_count(chair["id"])         # rung 36
    if count >= chair["max_evaluation_caseload"]:
        raise ApiError(
            "ERR_EVALUATION_CASELOAD_EXCEEDED",
            "Chair already holds %d of %d active evaluations"
            % (count, chair["max_evaluation_caseload"]),
        )

    row = base_row()
    row.update(
        {
            "referral_id": referral_id,
            "child_id": referral["child_id"],
            "chair_provider_id": chair_id,
            "assessment_protocol": protocol,
            "required_domain_count": calc.REQUIRED_DOMAIN_COUNT,
            "revision_round": 0,
            "report_narrative_summary": None,
            "report_drafted_at": None,
            "last_revision_note": None,
            "_determined_at": None,
            "status": "PLANNED",
        }
    )
    db.evaluation_cases[row["id"]] = row
    return object_response(derive.case_out(row), 201)


def _discipline_can_assess(discipline, domain):
    if domain == "ADAPTIVE":
        return discipline != "INTERPRETER"
    return discipline in calc.DOMAIN_DISCIPLINE_MAP[domain]


@bp.post("/evaluation-cases/<case_id>/domain-assessments")
@endpoint("ChildFindCoordinator", "EvaluationChair", "DistrictAdmin")
def schedule_assessment(case_id):
    data = body()
    evaluator_id = req_id(data, "evaluator_provider_id")
    domain = req_enum(data, "domain", DOMAIN)
    method = req_enum(data, "method", METHOD)
    window_start = req_datetime(data, "window_start_utc")
    window_end = req_datetime(data, "window_end_utc")
    site_id = opt_id(data, "assessment_site_id")
    if window_end <= window_start:
        bad("Field 'window_end_utc' must fall strictly after 'window_start_utc'")

    case = rules.fetch("evaluation_cases", case_id)              # rung 4
    evaluator = rules.fetch("providers", evaluator_id)           # rung 5
    site = rules.fetch_optional_fk("community_sites", site_id)
    rules.require_case_chair(case)                               # rung 8

    if case["status"] in ("CANCELLED", "ELIGIBILITY_DETERMINED"):    # rung 11
        raise ApiError(
            "ERR_INVALID_CASE_STATE",
            "Case status is %s; no assessment may be scheduled" % case["status"],
        )
    if evaluator_id == case["chair_provider_id"]:                     # rung 16
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The case chair may not evaluate a domain on the same case",
        )
    rules.require_provider_active(evaluator)                          # rung 18
    if not _discipline_can_assess(evaluator["discipline"], domain):   # rung 19
        raise ApiError(
            "ERR_DISCIPLINE_MISMATCH",
            "Discipline %s may not assess %s" % (evaluator["discipline"], domain),
        )
    if rules.evaluator_window_conflict(evaluator_id, site_id, window_start, window_end):
        raise ApiError(                                               # rung 22
            "ERR_EVALUATOR_WINDOW_CONFLICT",
            "Evaluator already occupied in an overlapping window",
        )
    for other in derive.assessments_of_case(case_id):                 # rung 26
        if other["domain"] == domain and other["status"] in ("SCHEDULED", "COMPLETED"):
            raise ApiError(
                "ERR_DUPLICATE_DOMAIN_ASSESSMENT",
                "Case already holds a live %s assessment" % domain,
            )

    child = db.children[case["child_id"]]
    row = base_row()
    row.update(
        {
            "evaluation_case_id": case_id,
            "evaluator_provider_id": evaluator_id,
            "assessment_site_id": site["id"] if site else None,
            "domain": domain,
            "method": method,
            "window_start_utc": window_start,
            "window_end_utc": window_end,
            "chronological_age_months": calc.whole_months(
                child["date_of_birth"], window_start.date()
            ),
            "age_equivalent_months": None,
            "standard_score": None,
            "percent_delay": None,
            "weighted_percent_delay": None,
            "qualifies_delay": False,
            "invalidation_reason": None,
            "completed_at": None,
            "status": "SCHEDULED",
        }
    )
    db.domain_assessments[row["id"]] = row
    if case["status"] == "PLANNED":
        case["status"] = "IN_PROGRESS"
        touch(case)
    return object_response(derive.assessment_out(row), 201)


@bp.post("/domain-assessments/<assessment_id>/completion")
@endpoint("EvaluationChair", "Evaluator", "DistrictAdmin")
def complete_assessment(assessment_id):
    data = body()
    age_equivalent = req_int(data, "age_equivalent_months", minimum=0)
    standard_score = opt_number(data, "standard_score", minimum=0)

    row = rules.fetch("domain_assessments", assessment_id)        # rung 4
    if age_equivalent > row["chronological_age_months"]:          # rung 3, cross-field
        bad(
            "Field 'age_equivalent_months' must not exceed chronological_age_months (%d)"
            % row["chronological_age_months"]
        )
    case = db.evaluation_cases[row["evaluation_case_id"]]
    rules.require_assigned_evaluator(row)                         # rung 7
    rules.require_case_chair(case)                                # rung 8

    if row["status"] != "SCHEDULED":                              # rung 11
        raise ApiError(
            "ERR_INVALID_ASSESSMENT_STATE",
            "Assessment status is %s; only a SCHEDULED assessment may be completed"
            % row["status"],
        )
    if case["status"] not in ("IN_PROGRESS", "DOMAINS_COMPLETE"):  # rung 12
        raise ApiError(
            "ERR_INVALID_CASE_STATE",
            "Case status is %s; a completion is not accepted" % case["status"],
        )

    variant = calc.pinned_variant(case["assessment_protocol"])
    pct = calc.percent_delay(row["chronological_age_months"], age_equivalent)
    weighted = calc.weighted_delay(variant, row["method"], pct)
    row["age_equivalent_months"] = age_equivalent
    row["standard_score"] = standard_score
    row["percent_delay"] = pct
    row["weighted_percent_delay"] = weighted
    row["qualifies_delay"] = weighted is not None and weighted >= calc.DELAY_QUALIFY_PCT
    row["completed_at"] = now_utc()
    row["status"] = "COMPLETED"
    touch(row)
    rules.refresh_case_status_after_assessment_change(case)
    return object_response(derive.assessment_out(row))


@bp.post("/domain-assessments/<assessment_id>/invalidation")
@endpoint("EvaluationChair", "Evaluator", "DistrictAdmin")
def invalidate_assessment(assessment_id):
    data = body()
    reason = req_str(data, "invalidation_reason", max_len=500)

    row = rules.fetch("domain_assessments", assessment_id)        # rung 4
    case = db.evaluation_cases[row["evaluation_case_id"]]
    rules.require_assigned_evaluator(row)                         # rung 7
    rules.require_case_chair(case)                                # rung 8

    if row["status"] not in ("SCHEDULED", "COMPLETED"):            # rung 11
        raise ApiError(
            "ERR_INVALID_ASSESSMENT_STATE",
            "Assessment status is %s; INVALIDATED is terminal" % row["status"],
        )
    if row["status"] == "COMPLETED" and case["status"] == "ELIGIBILITY_DETERMINED":
        raise ApiError(                                            # rung 12
            "ERR_INVALID_CASE_STATE",
            "A determined case's evidentiary record is closed",
        )

    # The delay figures are retained on the row as historical values; the row
    # simply leaves every case aggregate.
    row["status"] = "INVALIDATED"
    row["invalidation_reason"] = reason
    touch(row)
    rules.refresh_case_status_after_assessment_change(case)
    return object_response(derive.assessment_out(row))


@bp.post("/evaluation-cases/<case_id>/report")
@endpoint("EvaluationChair", "DistrictAdmin")
def draft_report(case_id):
    data = body()
    narrative = req_str(data, "report_narrative_summary", max_len=4000)

    case = rules.fetch("evaluation_cases", case_id)          # rung 4
    rules.require_case_chair(case)                           # rung 8
    if case["status"] not in ("DOMAINS_COMPLETE", "REVISIONS_REQUESTED"):   # rung 11
        raise ApiError(
            "ERR_INVALID_CASE_STATE",
            "Case status is %s; a report may not be drafted" % case["status"],
        )
    profile = derive.case_profile(case)
    if profile["completed_domain_count"] < case["required_domain_count"]:   # rung 25
        raise ApiError(
            "ERR_DOMAINS_INCOMPLETE",
            "Only %d of %d domains stand COMPLETED"
            % (profile["completed_domain_count"], case["required_domain_count"]),
        )

    case["report_narrative_summary"] = narrative
    case["report_drafted_at"] = now_utc()
    case["status"] = "REPORT_DRAFTED"
    touch(case)
    return object_response(derive.case_out(case))


@bp.post("/evaluation-cases/<case_id>/revision-requests")
@endpoint("ChildFindCoordinator", "PlacementAdministrator", "DistrictAdmin")
def request_revision(case_id):
    data = body()
    note = req_str(data, "revision_note", max_len=2000)

    case = rules.fetch("evaluation_cases", case_id)          # rung 4
    if case["status"] != "REPORT_DRAFTED":                   # rung 11
        raise ApiError(
            "ERR_INVALID_CASE_STATE",
            "Case status is %s; only a drafted report may be sent back" % case["status"],
        )
    if case["revision_round"] >= calc.MAX_REVISION_ROUNDS:   # rung 27
        raise ApiError(
            "ERR_REVISION_LIMIT_REACHED",
            "A case may absorb at most %d revision rounds" % calc.MAX_REVISION_ROUNDS,
        )

    case["revision_round"] += 1
    case["last_revision_note"] = note
    case["status"] = "REVISIONS_REQUESTED"
    touch(case)
    return object_response(derive.case_out(case))


@bp.post("/evaluation-cases/<case_id>/service-plans")
@endpoint("PlacementAdministrator", "EvaluationChair", "DistrictAdmin")
def determine_eligibility(case_id):
    data = body()
    decision = req_enum(data, "eligibility_decision", ELIGIBILITY_DECISION)
    expected_version = req_int(data, "expected_evaluation_case_version")
    disability_category = opt_enum(data, "disability_category", DISABILITY_CATEGORY)
    setting = opt_enum(data, "setting", SETTING)
    site_id = opt_id(data, "community_site_id")
    override = opt_str(data, "override_justification", max_len=2000)
    if decision == "ELIGIBLE":
        if disability_category is None:
            bad("Field 'disability_category' is required when eligibility_decision is ELIGIBLE")
        if setting is None:
            bad("Field 'setting' is required when eligibility_decision is ELIGIBLE")
    else:
        if disability_category is not None:
            bad("Field 'disability_category' must be absent when the decision is NOT_ELIGIBLE")
        if setting is not None:
            bad("Field 'setting' must be absent when the decision is NOT_ELIGIBLE")

    case = rules.fetch("evaluation_cases", case_id)                 # rung 4
    site = rules.fetch_optional_fk("community_sites", site_id)      # rung 5
    rules.require_case_chair(case)                                  # rung 8

    if expected_version != case["version"]:                         # rung 10
        raise ApiError(
            "ERR_STALE_EVALUATION_CASE_VERSION",
            "Evaluation case version has advanced since it was read",
        )
    if case["status"] not in ("REPORT_DRAFTED", "ELIGIBILITY_DETERMINED"):   # rung 11
        raise ApiError(
            "ERR_INVALID_CASE_STATE",
            "Case status is %s; a determination may not be recorded" % case["status"],
        )

    prior_plans = [p for p in derive.plans_of_child(case["child_id"])
                   if p["evaluation_case_id"] == case_id]
    prior = prior_plans[-1] if prior_plans else None
    if case["status"] == "ELIGIBILITY_DETERMINED":                   # rung 12
        if prior is None or prior["status"] != "DRAFT":
            raise ApiError(
                "ERR_INVALID_PLAN_STATE",
                "The plan already on this case has moved beyond DRAFT",
            )

    child = db.children[case["child_id"]]
    if site is not None:                                            # rung 20
        rules.require_site_placement_eligible(site, child)

    profile = derive.case_profile(case)
    if profile["completed_domain_count"] < case["required_domain_count"]:    # rung 25
        raise ApiError(
            "ERR_DOMAINS_INCOMPLETE",
            "Only %d of %d domains stand COMPLETED"
            % (profile["completed_domain_count"], case["required_domain_count"]),
        )

    if setting == "COMMUNITY_PRESCHOOL":                             # rung 30
        if site_id is None:
            raise ApiError(
                "ERR_PLAN_SETTING_REQUIREMENTS_UNMET",
                "A COMMUNITY_PRESCHOOL plan must name a community_site_id",
            )
    elif site_id is not None:
        raise ApiError(
            "ERR_PLAN_SETTING_REQUIREMENTS_UNMET",
            "community_site_id may only be supplied for the COMMUNITY_PRESCHOOL setting",
        )

    recommendation = profile["composite_eligibility_recommendation"]  # rung 31
    contradicts = (decision == "ELIGIBLE" and recommendation == "NOT_ELIGIBLE_RECOMMENDED") or (
        decision == "NOT_ELIGIBLE" and recommendation == "ELIGIBLE_RECOMMENDED"
    )
    if contradicts and not (override or "").strip():
        raise ApiError(
            "ERR_ELIGIBILITY_OVERRIDE_JUSTIFICATION_REQUIRED",
            "A determination contradicting the team recommendation needs a justification",
        )

    case["status"] = "ELIGIBILITY_DETERMINED"
    case["_determined_at"] = now_utc()
    touch(case)

    if prior is not None and prior["status"] == "DRAFT":
        prior["status"] = "SUPERSEDED"
        touch(prior)
        rules.discontinue_plan_lines(prior)

    plan = base_row()
    plan.update(
        {
            "evaluation_case_id": case_id,
            "child_id": case["child_id"],
            "community_site_id": site_id,
            "eligibility_decision": decision,
            "disability_category": disability_category,
            "setting": setting,
            "override_justification": override,
            "recommended_weekly_minutes": profile["per_line_rounded_minutes"],
            "determined_by_user_id": current_user_id(),
            "start_date": None,
            "exit_date": None,
            "kindergarten_transition_status": "NOT_STARTED",
            "transition_conference_date": None,
            "receiving_school_code": None,
            "status": "DRAFT",
        }
    )
    db.service_plans[plan["id"]] = plan
    if decision == "NOT_ELIGIBLE":
        plan["status"] = "CLOSED_NOT_ELIGIBLE"
        touch(plan)
    return object_response(derive.plan_out(plan), 201)


@bp.get("/evaluation-cases/<case_id>")
@endpoint(*CASE_READ_ROLES)
def get_case(case_id):
    return object_response(derive.case_out(rules.fetch("evaluation_cases", case_id)))


@bp.get("/evaluation-cases")
@endpoint(*CASE_READ_ROLES)
def list_cases():
    referral_id = q_str("referral_id")
    child_id = q_str("child_id")
    chair_id = q_str("chair_provider_id")
    protocol = q_enum("assessment_protocol", ASSESSMENT_PROTOCOL)
    compliance = q_enum("timeline_compliance", TIMELINE_COMPLIANCE)
    status = q_enum("status", CASE_STATUS)
    rows = [
        c
        for c in db.evaluation_cases.values()
        if matches(c, "referral_id", referral_id)
        and matches(c, "child_id", child_id)
        and matches(c, "chair_provider_id", chair_id)
        and matches(c, "assessment_protocol", protocol)
        and matches(c, "status", status)
        and (compliance is None or derive.case_out(c)["timeline_compliance"] == compliance)
    ]
    return paged(rows, derive.case_out)


@bp.get("/domain-assessments/<assessment_id>")
@endpoint(*CASE_READ_ROLES)
def get_assessment(assessment_id):
    return object_response(derive.assessment_out(rules.fetch("domain_assessments", assessment_id)))


@bp.get("/domain-assessments")
@endpoint(*CASE_READ_ROLES)
def list_assessments():
    case_id = q_str("evaluation_case_id")
    evaluator_id = q_str("evaluator_provider_id")
    site_id = q_str("assessment_site_id")
    domain = q_enum("domain", DOMAIN)
    method = q_enum("method", METHOD)
    status = q_enum("status", ASSESSMENT_STATUS)
    rows = [
        a
        for a in db.domain_assessments.values()
        if matches(a, "evaluation_case_id", case_id)
        and matches(a, "evaluator_provider_id", evaluator_id)
        and matches(a, "assessment_site_id", site_id)
        and matches(a, "domain", domain)
        and matches(a, "method", method)
        and matches(a, "status", status)
    ]
    return paged(rows, derive.assessment_out)


@bp.get("/evaluation-cases/<case_id>/eligibility-profile")
@endpoint(*CASE_READ_ROLES)
def eligibility_profile(case_id):
    case = rules.fetch("evaluation_cases", case_id)
    pinned = calc.pinned_variant(case["assessment_protocol"])
    strict = derive.case_profile(case, calc.VARIANT_STRICT)
    inclusive = derive.case_profile(case, calc.VARIANT_INCLUSIVE)
    live = strict if pinned == calc.VARIANT_STRICT else inclusive
    return object_response(
        {
            "evaluation_case_id": case["id"],
            "pinned_variant": pinned,
            "completed_domain_count": live["completed_domain_count"],
            "standardized_strict_qualifying_domain_count": strict["qualifying_domain_count"],
            "standardized_strict_max_weighted_percent_delay": calc.as_number(
                strict["max_weighted_percent_delay"]
            ),
            "standardized_strict_recommendation": strict["composite_eligibility_recommendation"],
            "play_based_inclusive_qualifying_domain_count": inclusive["qualifying_domain_count"],
            "play_based_inclusive_max_weighted_percent_delay": calc.as_number(
                inclusive["max_weighted_percent_delay"]
            ),
            "play_based_inclusive_recommendation": inclusive[
                "composite_eligibility_recommendation"
            ],
            "composite_eligibility_recommendation": live[
                "composite_eligibility_recommendation"
            ],
            "recommended_weekly_minutes": live["per_line_rounded_minutes"],
            "per_line_rounded_minutes": live["per_line_rounded_minutes"],
            "sum_then_rounded_minutes": live["sum_then_rounded_minutes"],
        }
    )
