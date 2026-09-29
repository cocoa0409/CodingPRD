"""The twenty-six read endpoints (PRD section 4). Every role may read the registry."""

from flask import Blueprint, request

import domain
import store
from auth import ALL_ROLES, endpoint
from envelope import paginate, single

bp = Blueprint("read", __name__)

ALL = ALL_ROLES


def _filtered(kind, fields):
    rows = []
    supplied = [(field, request.args.get(field)) for field in fields]
    for record in store.rows(kind):
        keep = True
        for field, wanted in supplied:
            if wanted is None:
                continue
            value = record.get(field)
            if value is None or str(value) != wanted:
                keep = False
                break
        if keep:
            rows.append(record)
    return rows


def _list(kind, fields):
    return paginate(_filtered(kind, fields), store.public)


def _detail(kind, row_id):
    return single(store.public(domain.find(kind, row_id)))


# ------------------------------------------------------------------- collections
@bp.get("/accreditation/schemes")
@endpoint(ALL)
def list_schemes(user_id, role):
    return _list("schemes", ("status", "standard_ref"))


@bp.get("/accreditation/schemes/<scheme_id>")
@endpoint(ALL)
def get_scheme(user_id, role, scheme_id):
    return _detail("schemes", scheme_id)


@bp.get("/accreditation/assessors")
@endpoint(ALL)
def list_assessors(user_id, role):
    return _list("assessors", ("qualification_status", "impartiality_status", "employment_type"))


@bp.get("/accreditation/assessors/<assessor_id>")
@endpoint(ALL)
def get_assessor(user_id, role, assessor_id):
    return _detail("assessors", assessor_id)


@bp.get("/accreditation/qualifications")
@endpoint(ALL)
def list_qualifications(user_id, role):
    return _list("qualifications", ("assessor_id", "scheme_id", "role_type", "status"))


@bp.get("/accreditation/qualifications/<qualification_id>")
@endpoint(ALL)
def get_qualification(user_id, role, qualification_id):
    return _detail("qualifications", qualification_id)


@bp.get("/accreditation/impartiality-declarations")
@endpoint(ALL)
def list_declarations(user_id, role):
    return _list("declarations", ("assessor_id", "organization_id", "relationship_type"))


@bp.get("/accreditation/impartiality-declarations/<declaration_id>")
@endpoint(ALL)
def get_declaration(user_id, role, declaration_id):
    return _detail("declarations", declaration_id)


@bp.get("/accreditation/organizations")
@endpoint(ALL)
def list_organizations(user_id, role):
    return _list("organizations", ("status", "country_code"))


@bp.get("/accreditation/organizations/<organization_id>")
@endpoint(ALL)
def get_organization(user_id, role, organization_id):
    return _detail("organizations", organization_id)


@bp.get("/accreditation/applications")
@endpoint(ALL)
def list_applications(user_id, role):
    return _list("applications",
                 ("organization_id", "scheme_id", "origin_scope_id", "cycle_type", "status"))


@bp.get("/accreditation/applications/<application_id>")
@endpoint(ALL)
def get_application(user_id, role, application_id):
    return _detail("applications", application_id)


@bp.get("/accreditation/team-assignments")
@endpoint(ALL)
def list_assignments(user_id, role):
    return _list("assignments", ("application_id", "assessor_id", "role_type", "status"))


@bp.get("/accreditation/team-assignments/<assignment_id>")
@endpoint(ALL)
def get_assignment(user_id, role, assignment_id):
    return _detail("assignments", assignment_id)


@bp.get("/accreditation/assessment-plans")
@endpoint(ALL)
def list_plans(user_id, role):
    return _list("plans", ("application_id", "superseded_by_plan_id", "mode", "status"))


@bp.get("/accreditation/assessment-plans/<plan_id>")
@endpoint(ALL)
def get_plan(user_id, role, plan_id):
    return _detail("plans", plan_id)


@bp.get("/accreditation/witness-sessions")
@endpoint(ALL)
def list_sessions(user_id, role):
    return _list("sessions", ("plan_id", "assessor_id", "site_ref", "delivery_mode", "status"))


@bp.get("/accreditation/witness-sessions/<session_id>")
@endpoint(ALL)
def get_session(user_id, role, session_id):
    return _detail("sessions", session_id)


@bp.get("/accreditation/nonconformities")
@endpoint(ALL)
def list_nonconformities(user_id, role):
    return _list("nonconformities",
                 ("application_id", "raised_by_assessor_id", "reviewed_by_assessor_id",
                  "verified_by_assessor_id", "classification", "status"))


@bp.get("/accreditation/nonconformities/<nonconformity_id>")
@endpoint(ALL)
def get_nonconformity(user_id, role, nonconformity_id):
    return _detail("nonconformities", nonconformity_id)


@bp.get("/accreditation/decisions")
@endpoint(ALL)
def list_decisions(user_id, role):
    return _list("decisions", ("application_id", "status", "outcome"))


@bp.get("/accreditation/decisions/<decision_id>")
@endpoint(ALL)
def get_decision(user_id, role, decision_id):
    return _detail("decisions", decision_id)


@bp.get("/accreditation/scopes")
@endpoint(ALL)
def list_scopes(user_id, role):
    return _list("scopes", ("application_id", "organization_id", "scheme_id", "status"))


@bp.get("/accreditation/scopes/<scope_id>")
@endpoint(ALL)
def get_scope(user_id, role, scope_id):
    return _detail("scopes", scope_id)


@bp.get("/accreditation/complaints")
@endpoint(ALL)
def list_complaints(user_id, role):
    return _list("complaints",
                 ("organization_id", "application_id", "reviewer_assessor_id", "kind", "status"))


@bp.get("/accreditation/complaints/<complaint_id>")
@endpoint(ALL)
def get_complaint(user_id, role, complaint_id):
    return _detail("complaints", complaint_id)
