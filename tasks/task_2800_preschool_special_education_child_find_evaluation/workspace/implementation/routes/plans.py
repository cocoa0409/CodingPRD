"""Service plans, service lines, staffing, service consent and the
kindergarten transition (PRD sections 3.8 and 3.9)."""
from flask import Blueprint

from db import base_row, clock_date, db, now_utc, touch
from errors import ApiError
from middleware import endpoint
from response import object_response
from routes.common import matches, paged
from services import calc, derive, rules
from validation import (
    DELIVERY_MODEL,
    ELIGIBILITY_DECISION,
    INTERPRETER_MODALITY,
    KT_ACTION,
    KT_STATUS,
    LINE_DISCIPLINE,
    LINE_STATUS,
    NOTICE_DELIVERY_METHOD,
    PLAN_STATUS,
    SETTING,
    bad,
    body,
    opt_date,
    opt_enum,
    opt_id,
    opt_str,
    q_enum,
    q_str,
    req_enum,
    req_id,
    req_int,
    req_lang,
)

bp = Blueprint("plans", __name__)

PLAN_READ_ROLES = (
    "ChildFindCoordinator",
    "EvaluationChair",
    "PlacementAdministrator",
    "Parent",
    "DistrictAdmin",
)
LINE_READ_ROLES = (
    "ChildFindCoordinator",
    "EvaluationChair",
    "PlacementAdministrator",
    "DistrictAdmin",
)
ITINERANT_MAX_LINE_MINUTES = 300


@bp.post("/service-plans/<plan_id>/service-lines")
@endpoint("PlacementAdministrator", "EvaluationChair", "DistrictAdmin")
def add_service_line(plan_id):
    data = body()
    discipline = req_enum(data, "discipline", LINE_DISCIPLINE)
    weekly_minutes = req_int(data, "weekly_minutes", minimum=5, maximum=600, multiple_of=5)
    delivery_model = req_enum(data, "delivery_model", DELIVERY_MODEL)

    plan = rules.fetch("service_plans", plan_id)              # rung 4
    if plan["status"] != "DRAFT":                              # rung 12
        raise ApiError(
            "ERR_INVALID_PLAN_STATE",
            "Plan status is %s; lines may only be added to a DRAFT plan" % plan["status"],
        )
    site = db.community_sites.get(plan.get("community_site_id"))
    if site is not None:                                       # rung 20
        rules.require_site_placement_eligible(site, db.children[plan["child_id"]])
    if plan.get("setting") == "ITINERANT_ONLY":                # rung 30
        if delivery_model not in ("DIRECT", "CONSULT"):
            raise ApiError(
                "ERR_PLAN_SETTING_REQUIREMENTS_UNMET",
                "An ITINERANT_ONLY plan admits only DIRECT or CONSULT lines",
            )
        if weekly_minutes > ITINERANT_MAX_LINE_MINUTES:
            raise ApiError(
                "ERR_PLAN_SETTING_REQUIREMENTS_UNMET",
                "An ITINERANT_ONLY line may not exceed %d weekly minutes"
                % ITINERANT_MAX_LINE_MINUTES,
            )

    row = base_row()
    row.update(
        {
            "service_plan_id": plan_id,
            "provider_id": None,
            "delivery_site_id": None,
            "discipline": discipline,
            "weekly_minutes": weekly_minutes,
            "delivery_model": delivery_model,
            "status": "PROPOSED",
        }
    )
    db.service_lines[row["id"]] = row
    return object_response(derive.line_out(row), 201)


@bp.post("/service-lines/<line_id>/staff")
@endpoint("PlacementAdministrator", "DistrictAdmin")
def staff_line(line_id):
    data = body()
    provider_id = req_id(data, "provider_id")
    expected_version = req_int(data, "expected_provider_version")
    site_id = opt_id(data, "delivery_site_id")

    line = rules.fetch("service_lines", line_id)                 # rung 4
    provider = rules.fetch("providers", provider_id)             # rung 5
    rules.fetch_optional_fk("community_sites", site_id)
    plan = db.service_plans[line["service_plan_id"]]

    if expected_version != provider["version"]:                  # rung 10
        raise ApiError(
            "ERR_STALE_PROVIDER_VERSION",
            "Provider version has advanced since it was read",
        )
    if line["status"] not in ("PROPOSED", "UNSTAFFED"):           # rung 11
        raise ApiError(
            "ERR_INVALID_LINE_STATE",
            "Line status is %s; only a PROPOSED or UNSTAFFED line may be staffed"
            % line["status"],
        )
    if plan["status"] not in ("DRAFT", "ACTIVE"):                 # rung 12
        raise ApiError(
            "ERR_INVALID_PLAN_STATE", "Plan status is %s" % plan["status"]
        )
    rules.require_provider_active(provider)                       # rung 18
    if provider["discipline"] == "INTERPRETER" or provider["discipline"] != line["discipline"]:
        raise ApiError(                                           # rung 19
            "ERR_DISCIPLINE_MISMATCH",
            "Provider discipline %s does not match the line's %s"
            % (provider["discipline"], line["discipline"]),
        )

    # An omitted delivery_site_id falls back to the plan's own community site.
    effective_site = site_id if site_id is not None else plan.get("community_site_id")
    projected = rules.projected_provider_minutes(provider, line, effective_site)
    if projected["assigned_weekly_service_minutes"] > provider["max_weekly_service_minutes"]:
        raise ApiError(                                           # rung 37
            "ERR_PROVIDER_CASELOAD_EXCEEDED",
            "Staffing would take the provider to %d of %d assigned weekly minutes"
            % (
                projected["assigned_weekly_service_minutes"],
                provider["max_weekly_service_minutes"],
            ),
        )

    line["provider_id"] = provider_id
    line["delivery_site_id"] = effective_site
    line["status"] = "STAFFED"
    touch(line)
    touch(provider)
    return object_response(derive.line_out(line))


@bp.post("/service-lines/<line_id>/unstaff")
@endpoint("PlacementAdministrator", "DistrictAdmin")
def unstaff_line(line_id):
    data = body()
    opt_str(data, "unstaff_reason", max_len=500)

    line = rules.fetch("service_lines", line_id)                 # rung 4
    plan = db.service_plans[line["service_plan_id"]]
    if line["status"] != "STAFFED":                               # rung 11
        raise ApiError(
            "ERR_INVALID_LINE_STATE",
            "Line status is %s; only a STAFFED line may be released" % line["status"],
        )
    if plan["status"] not in ("DRAFT", "ACTIVE"):                 # rung 12
        raise ApiError(
            "ERR_INVALID_PLAN_STATE", "Plan status is %s" % plan["status"]
        )

    provider = db.providers.get(line["provider_id"])
    line["provider_id"] = None
    line["delivery_site_id"] = None
    line["status"] = "UNSTAFFED"
    touch(line)
    if provider is not None:
        touch(provider)
    return object_response(derive.line_out(line))


def _staffed_lines(plan_id):
    return [l for l in derive.lines_of_plan(plan_id) if l["status"] == "STAFFED"]


@bp.post("/service-plans/<plan_id>/consent-submission")
@endpoint("PlacementAdministrator", "ChildFindCoordinator", "DistrictAdmin")
def submit_for_consent(plan_id):
    data = body()
    notice_language_code = req_lang(data, "notice_language_code")
    notice_delivery_method = req_enum(data, "notice_delivery_method", NOTICE_DELIVERY_METHOD)
    interpreter_id = opt_id(data, "interpreter_provider_id")
    interpreter_modality = opt_enum(data, "interpreter_modality", INTERPRETER_MODALITY)
    if interpreter_id is not None and interpreter_modality is None:
        bad("Field 'interpreter_modality' is required when an interpreter_provider_id is named")

    plan = rules.fetch("service_plans", plan_id)                      # rung 4
    interpreter = rules.fetch_optional_fk("providers", interpreter_id)  # rung 5

    if plan["status"] != "DRAFT":                                     # rung 11
        raise ApiError(
            "ERR_INVALID_PLAN_STATE",
            "Plan status is %s; only a DRAFT plan may be submitted" % plan["status"],
        )
    if plan["eligibility_decision"] != "ELIGIBLE" or plan.get("setting") is None:
        raise ApiError(
            "ERR_INVALID_PLAN_STATE",
            "Only an ELIGIBLE plan with a setting may be submitted for consent",
        )

    child = db.children[plan["child_id"]]
    rules.require_language_access(child, notice_language_code, interpreter)   # rung 14

    setting = plan["setting"]
    site_id = plan.get("community_site_id")
    site = db.community_sites.get(site_id)
    if site is not None:                                              # rung 20
        rules.require_site_placement_eligible(site, child)

    staffed = _staffed_lines(plan_id)                                 # rung 30
    if not staffed:
        raise ApiError(
            "ERR_PLAN_SETTING_REQUIREMENTS_UNMET",
            "A plan submitted for consent must hold at least one STAFFED line",
        )
    if setting == "COMMUNITY_PRESCHOOL":
        if site_id is None:
            raise ApiError(
                "ERR_PLAN_SETTING_REQUIREMENTS_UNMET",
                "A COMMUNITY_PRESCHOOL plan must name a community_site_id",
            )
    elif site_id is not None:
        raise ApiError(
            "ERR_PLAN_SETTING_REQUIREMENTS_UNMET",
            "A %s plan must not name a community_site_id" % setting,
        )
    if setting == "DISTRICT_ECSE_CLASSROOM" and not any(
        l["discipline"] == "ECSE_TEACHER" for l in staffed
    ):
        raise ApiError(
            "ERR_PLAN_SETTING_REQUIREMENTS_UNMET",
            "A DISTRICT_ECSE_CLASSROOM plan needs a STAFFED ECSE_TEACHER line",
        )
    if setting == "HOME_BASED" and not any(l["delivery_model"] == "DIRECT" for l in staffed):
        raise ApiError(
            "ERR_PLAN_SETTING_REQUIREMENTS_UNMET",
            "A HOME_BASED plan needs a STAFFED DIRECT line",
        )

    if setting == "COMMUNITY_PRESCHOOL":                               # rung 35
        reserved = derive.site_reserved_seats(site_id)
        if reserved >= site["iep_seat_capacity"]:
            raise ApiError(
                "ERR_IEP_SEAT_CAPACITY_EXCEEDED",
                "Site holds %d of %d IEP seats" % (reserved, site["iep_seat_capacity"]),
            )

    if interpreter is not None:                                       # rung 38
        rules.require_interpreter_available(interpreter)

    case = db.evaluation_cases[plan["evaluation_case_id"]]
    row = base_row()
    row.update(
        {
            "referral_id": case["referral_id"],
            "kind": "SERVICE_CONSENT",
            "requested_at": now_utc(),
            "decision": "PENDING",
            "decided_at": None,
            "notice_language_code": notice_language_code,
            "notice_delivery_method": notice_delivery_method,
            "interpreter_provider_id": interpreter_id,
            "interpreter_modality": interpreter_modality,
            "service_plan_id": plan_id,
        }
    )
    db.consent_records[row["id"]] = row
    plan["status"] = "PENDING_PARENT_CONSENT"
    touch(plan)
    return object_response(derive.consent_out(row), 201)


KT_PRECONDITION = {
    "SCHEDULE_CONFERENCE": "NOT_STARTED",
    "SEND_PACKET": "CONFERENCE_SCHEDULED",
    "EXIT": "PACKET_SENT",
}


@bp.post("/service-plans/<plan_id>/kindergarten-transition")
@endpoint("PlacementAdministrator", "ChildFindCoordinator", "DistrictAdmin")
def kindergarten_transition(plan_id):
    data = body()
    action = req_enum(data, "action", KT_ACTION)
    conference_date = opt_date(data, "transition_conference_date")
    school_code = opt_str(data, "receiving_school_code", max_len=40)
    if action == "SCHEDULE_CONFERENCE" and conference_date is None:
        bad("Field 'transition_conference_date' is required for SCHEDULE_CONFERENCE")
    if action == "SEND_PACKET" and school_code is None:
        bad("Field 'receiving_school_code' is required for SEND_PACKET")

    plan = rules.fetch("service_plans", plan_id)                   # rung 4
    if plan["status"] != "ACTIVE":                                 # rung 11
        raise ApiError(
            "ERR_INVALID_PLAN_STATE",
            "Plan status is %s; kindergarten transition runs on an ACTIVE plan"
            % plan["status"],
        )

    if action == "SCHEDULE_CONFERENCE":                            # rung 24
        child = db.children[plan["child_id"]]
        eligibility_date = calc.kindergarten_eligibility_date(child["date_of_birth"])
        lead_days = (eligibility_date - conference_date).days
        if lead_days < calc.KINDERGARTEN_CONFERENCE_LEAD_DAYS:
            raise ApiError(
                "ERR_TRANSITION_CONFERENCE_TOO_LATE",
                "Conference gives %d days of notice; %d are required"
                % (lead_days, calc.KINDERGARTEN_CONFERENCE_LEAD_DAYS),
            )
        if conference_date <= clock_date():
            raise ApiError(
                "ERR_TRANSITION_CONFERENCE_TOO_LATE",
                "The conference date must fall strictly after today",
            )

    if plan["kindergarten_transition_status"] != KT_PRECONDITION[action]:   # rung 32
        raise ApiError(
            "ERR_TRANSITION_SEQUENCE_VIOLATION",
            "Action %s requires kindergarten_transition_status %s, not %s"
            % (action, KT_PRECONDITION[action], plan["kindergarten_transition_status"]),
        )

    if action == "SCHEDULE_CONFERENCE":
        plan["transition_conference_date"] = conference_date
        plan["kindergarten_transition_status"] = "CONFERENCE_SCHEDULED"
        touch(plan)
    elif action == "SEND_PACKET":
        plan["receiving_school_code"] = school_code
        plan["kindergarten_transition_status"] = "PACKET_SENT"
        touch(plan)
    else:
        plan["kindergarten_transition_status"] = "COMPLETE"
        plan["exit_date"] = clock_date()
        plan["status"] = "EXITED_TO_KINDERGARTEN"
        touch(plan)
        rules.discontinue_plan_lines(plan)
    return object_response(derive.plan_out(plan))


@bp.get("/service-plans/<plan_id>")
@endpoint(*PLAN_READ_ROLES)
def get_plan(plan_id):
    plan = rules.fetch("service_plans", plan_id)
    rules.require_guardian(plan["child_id"])
    return object_response(derive.plan_out(plan))


@bp.get("/service-plans")
@endpoint(*PLAN_READ_ROLES)
def list_plans():
    case_id = q_str("evaluation_case_id")
    child_id = q_str("child_id")
    site_id = q_str("community_site_id")
    setting = q_enum("setting", SETTING)
    decision = q_enum("eligibility_decision", ELIGIBILITY_DECISION)
    kt_status = q_enum("kindergarten_transition_status", KT_STATUS)
    status = q_enum("status", PLAN_STATUS)
    rows = [
        p
        for p in db.service_plans.values()
        if matches(p, "evaluation_case_id", case_id)
        and matches(p, "child_id", child_id)
        and matches(p, "community_site_id", site_id)
        and matches(p, "setting", setting)
        and matches(p, "eligibility_decision", decision)
        and matches(p, "kindergarten_transition_status", kt_status)
        and matches(p, "status", status)
    ]
    return paged(rows, derive.plan_out)


@bp.get("/service-lines/<line_id>")
@endpoint(*LINE_READ_ROLES)
def get_line(line_id):
    return object_response(derive.line_out(rules.fetch("service_lines", line_id)))


@bp.get("/service-lines")
@endpoint(*LINE_READ_ROLES)
def list_lines():
    plan_id = q_str("service_plan_id")
    provider_id = q_str("provider_id")
    site_id = q_str("delivery_site_id")
    discipline = q_enum("discipline", LINE_DISCIPLINE)
    delivery_model = q_enum("delivery_model", DELIVERY_MODEL)
    status = q_enum("status", LINE_STATUS)
    rows = [
        l
        for l in db.service_lines.values()
        if matches(l, "service_plan_id", plan_id)
        and matches(l, "provider_id", provider_id)
        and matches(l, "delivery_site_id", site_id)
        and matches(l, "discipline", discipline)
        and matches(l, "delivery_model", delivery_model)
        and matches(l, "status", status)
    ]
    return paged(rows, derive.line_out)
