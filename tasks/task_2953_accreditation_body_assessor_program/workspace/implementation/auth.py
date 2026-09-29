"""Authentication, role authorisation and ApplicantContact ownership.

Precedence ranks 1 and 2 of PRD section 2.9 live here: header presence is checked
before anything else, then role validity/authorisation and (same rank) ownership.
"""

import functools

from flask import request

import store
from errors import ApiError
from validators import lenient_body

SCHEME_MANAGER = "SchemeManager"
ASSESSMENT_MANAGER = "AssessmentManager"
LEAD_ASSESSOR = "LeadAssessor"
TECHNICAL_EXPERT = "TechnicalExpert"
DECISION_PANEL_MEMBER = "DecisionPanelMember"
APPLICANT_CONTACT = "ApplicantContact"
COMPLAINT_OFFICER = "ComplaintOfficer"

ALL_ROLES = (
    SCHEME_MANAGER,
    ASSESSMENT_MANAGER,
    LEAD_ASSESSOR,
    TECHNICAL_EXPERT,
    DECISION_PANEL_MEMBER,
    APPLICANT_CONTACT,
    COMPLAINT_OFFICER,
)


def identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def endpoint(roles, owner=None):
    """Wrap a handler with rank-1 and rank-2 checks."""

    allowed = tuple(roles)

    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(**kwargs):
            user_id, role = identity()
            if role not in ALL_ROLES or role not in allowed:
                raise ApiError("ERR_ROLE_NOT_PERMITTED")
            if owner is not None:
                owner(user_id, role, kwargs)
            with store.LOCK:
                return handler(user_id, role, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------- ownership hooks
def owns_body_organization(user_id, role, kwargs):
    if role != APPLICANT_CONTACT:
        return
    supplied = lenient_body().get("organization_id")
    if isinstance(supplied, str) and supplied != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def owns_finding(user_id, role, kwargs):
    if role != APPLICANT_CONTACT:
        return
    finding = store.get("nonconformities", kwargs.get("nonconformity_id"))
    if finding is None:
        return
    application = store.get("applications", finding["application_id"])
    if application is None:
        return
    if application["organization_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
