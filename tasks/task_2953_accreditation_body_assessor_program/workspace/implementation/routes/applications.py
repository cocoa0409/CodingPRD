"""Applicant organizations, assessment cycles and team assembly (PRD 3.4)."""

from flask import Blueprint

import calc
import domain
import store
from auth import (APPLICANT_CONTACT, ASSESSMENT_MANAGER, endpoint,
                  owns_body_organization)
from envelope import created, single
from errors import ApiError
from validators import body, enum_field, int_field, string_field, string_list_field

bp = Blueprint("applications", __name__)

CYCLE_TYPES = ("INITIAL", "SURVEILLANCE", "REASSESSMENT", "UNANNOUNCED")
ROLE_TYPES = ("LEAD_ASSESSOR", "TECHNICAL_ASSESSOR", "TECHNICAL_EXPERT")


def scope_lines_field(payload, required=True, default=None):
    return string_list_field(payload, "requested_scope_lines", 1, 20, 1, 80,
                             required=required, default=default)


def check_notice_period(cycle_type, notice_days):
    if cycle_type == "UNANNOUNCED":
        if notice_days != 0:
            raise ApiError("ERR_INVALID_NOTICE_PERIOD",
                           "an UNANNOUNCED cycle must carry exactly 0 notice days")
    elif notice_days < calc.MIN_NOTICE_DAYS:
        raise ApiError("ERR_INVALID_NOTICE_PERIOD",
                       "a %s cycle requires at least %d notice days"
                       % (cycle_type, calc.MIN_NOTICE_DAYS))


def check_duplicate_active(organization_id, scheme_id):
    for existing in store.rows("applications"):
        if existing["organization_id"] != organization_id:
            continue
        if existing["scheme_id"] != scheme_id:
            continue
        if existing["status"] in domain.APPLICATION_TERMINAL:
            continue
        raise ApiError("ERR_DUPLICATE_ACTIVE_APPLICATION")


def check_unannounced_authority(cycle_type, pinned):
    if cycle_type == "UNANNOUNCED" and not pinned["unannounced_authority"]:
        raise ApiError("ERR_UNANNOUNCED_NOT_AUTHORIZED")


def new_cycle(organization, scheme, cycle_type, scope_lines, notice_days, origin_scope_id):
    snapshot = domain.scheme_snapshot(scheme)
    application = store.insert("applications", {
        "organization_id": organization["id"],
        "scheme_id": scheme["id"],
        "origin_scope_id": origin_scope_id,
        "cycle_type": cycle_type,
        "requested_scope_lines": list(scope_lines),
        "notice_days": notice_days,
        "pinned_scheme_rule_revision": scheme["rule_revision"],
        "status": "SUBMITTED",
        "decision_round": 1,
        "nc_total_count": 0,
        "nc_blocking_open_count": 0,
        "nc_closed_count": 0,
        "nc_observation_count": 0,
        "completed_witness_session_count": 0,
        "planned_effort_days": None,
        "suspension_blocked": False,
        "_pinned": snapshot,
    })
    return application


@bp.post("/accreditation/organizations")
@endpoint([ASSESSMENT_MANAGER])
def create_organization(user_id, role):
    payload = body()
    legal_name = string_field(payload, "legal_name", 1, 160)
    country_code = string_field(payload, "country_code", 2, 2)
    contact_email = string_field(payload, "contact_email", 1, 320)

    if not country_code.isalpha() or country_code != country_code.upper():
        raise ApiError("ERR_INVALID_REQUEST",
                       "country_code must be exactly two upper-case letters")
    if contact_email.count("@") != 1:
        raise ApiError("ERR_INVALID_REQUEST",
                       "contact_email must contain exactly one @ character")
    for existing in store.rows("organizations"):
        if existing["legal_name"] == legal_name:
            raise ApiError("ERR_INVALID_REQUEST", "legal_name must be unique")

    organization = store.insert("organizations", {
        "legal_name": legal_name,
        "country_code": country_code,
        "contact_email": contact_email,
        "status": "APPLIED",
        "risk_score": 0,
        "active_scope_count": 0,
        "upheld_complaint_count": 0,
        "mra_escalation_count": 0,
        "suspension_reason": None,
    })
    return created(store.public(organization))


@bp.post("/accreditation/applications")
@endpoint([ASSESSMENT_MANAGER, APPLICANT_CONTACT], owner=owns_body_organization)
def open_cycle(user_id, role):
    payload = body()
    organization_id = string_field(payload, "organization_id", 1)
    scheme_id = string_field(payload, "scheme_id", 1)
    cycle_type = enum_field(payload, "cycle_type", CYCLE_TYPES)
    scope_lines = scope_lines_field(payload)
    notice_days = int_field(payload, "notice_days", 0, 120, required=False, default=30)

    organization = domain.find("organizations", organization_id)
    scheme = domain.find("schemes", scheme_id)

    if scheme["status"] != "PUBLISHED":
        raise ApiError("ERR_SCHEME_NOT_PUBLISHED")
    check_notice_period(cycle_type, notice_days)
    check_duplicate_active(organization_id, scheme_id)
    check_unannounced_authority(cycle_type, domain.scheme_snapshot(scheme))

    application = new_cycle(organization, scheme, cycle_type, scope_lines, notice_days, None)
    return created(store.public(application))


@bp.post("/accreditation/applications/<application_id>/team-assignments")
@endpoint([ASSESSMENT_MANAGER])
def propose_team_member(user_id, role, application_id):
    payload = body()
    assessor_id = string_field(payload, "assessor_id", 1)
    role_type = enum_field(payload, "role_type", ROLE_TYPES)

    application = domain.find("applications", application_id)
    assessor = domain.find("assessors", assessor_id)

    if application["suspension_blocked"] or application["status"] not in domain.TEAM_BUILD_STATUSES:
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "this cycle does not permit team building")

    verdict = calc.conflict_verdict(assessor_id, application["organization_id"],
                                    store.clock_date())
    if verdict == "BLOCKED":
        raise ApiError("ERR_IMPARTIALITY_CONFLICT")
    if assessor["impartiality_status"] == "RESTRICTED":
        raise ApiError("ERR_ASSESSOR_IMPARTIALITY_RESTRICTED")
    if domain.live_granted_qualification(assessor_id, application["scheme_id"], role_type) is None:
        raise ApiError("ERR_QUALIFICATION_NOT_GRANTED")

    assignment = store.insert("assignments", {
        "application_id": application_id,
        "assessor_id": assessor_id,
        "role_type": role_type,
        "status": "PROPOSED",
        "conflict_verdict": None,
        "conflict_checked_at": None,
        "recusal_reason": None,
    })
    return created(store.public(assignment))


@bp.post("/accreditation/team-assignments/<assignment_id>/confirm")
@endpoint([ASSESSMENT_MANAGER])
def confirm_team_member(user_id, role, assignment_id):
    assignment = domain.find("assignments", assignment_id)
    if assignment["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a PROPOSED assignment may be confirmed")

    application = store.get("applications", assignment["application_id"])
    if application["suspension_blocked"] or application["status"] not in domain.TEAM_BUILD_STATUSES:
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "this cycle does not permit team confirmation")

    assessor = store.get("assessors", assignment["assessor_id"])
    if assessor is None:
        raise ApiError("ERR_ASSESSOR_NOT_FOUND")
    if assessor["qualification_status"] != "QUALIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the assessor is not in QUALIFIED standing")

    verdict = calc.conflict_verdict(assignment["assessor_id"], application["organization_id"],
                                    store.clock_date())
    if verdict == "BLOCKED":
        raise ApiError("ERR_IMPARTIALITY_CONFLICT")
    if assessor["impartiality_status"] == "RESTRICTED":
        raise ApiError("ERR_ASSESSOR_IMPARTIALITY_RESTRICTED")
    qualification = domain.live_granted_qualification(
        assignment["assessor_id"], application["scheme_id"], assignment["role_type"],
        expire_lazily=True)
    if qualification is None:
        raise ApiError("ERR_QUALIFICATION_NOT_GRANTED")

    assignment["status"] = "CONFIRMED"
    assignment["conflict_verdict"] = verdict
    assignment["conflict_checked_at"] = store.now_iso()
    store.touch(assignment)

    if assignment["role_type"] == "LEAD_ASSESSOR" and application["status"] == "SUBMITTED":
        application["status"] = "TEAM_ASSIGNED"
        store.touch(application)
        organization = store.get("organizations", application["organization_id"])
        if organization is not None and organization["status"] == "APPLIED":
            organization["status"] = "UNDER_ASSESSMENT"
            store.touch(organization)

    return single(store.public(assignment))


@bp.post("/accreditation/team-assignments/<assignment_id>/recuse")
@endpoint([ASSESSMENT_MANAGER])
def recuse_team_member(user_id, role, assignment_id):
    payload = body()
    reason = string_field(payload, "reason", 1, 300)

    assignment = domain.find("assignments", assignment_id)
    if assignment["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a CONFIRMED assignment may be recused")
    application = store.get("applications", assignment["application_id"])
    if application["status"] not in domain.RECUSAL_STATUSES:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "this cycle does not permit recusal")

    assignment["status"] = "RECUSED"
    assignment["recusal_reason"] = reason
    store.touch(assignment)

    if assignment["role_type"] == "LEAD_ASSESSOR" \
            and application["status"] == "TEAM_ASSIGNED" \
            and not domain.has_confirmed_lead(application["id"]):
        application["status"] = "SUBMITTED"
        store.touch(application)

    return single(store.public(assignment))
