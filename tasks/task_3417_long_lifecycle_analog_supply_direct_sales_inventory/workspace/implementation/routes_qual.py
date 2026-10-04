# Site qualification routes (PRD 3.5): open and drive the review workflow.
from flask import Blueprint

import constants as C
from auth import require_roles
from envelope import success
from errors import ApiError, ERR_INVALID_STATE, ERR_QUALIFICATION_OVERLAP
from lookups import get_site_qualification
from serialize import site_qualification_public
from store import store
from validate import (
    as_enum,
    as_int_at_least,
    as_str,
    check_unknown_fields,
    get_body,
    require_fields,
)

bp = Blueprint("site_qualifications", __name__)

_CREATE_ALLOWED = {"site_name", "segment", "validity_months"}
_TRANSITION_ALLOWED = {"to_state"}

# The legal transition graph (PRD 3.5).
_LEGAL_TRANSITIONS = {
    "REQUESTED": {"IN_REVIEW"},
    "IN_REVIEW": {"QUALIFIED", "REJECTED"},
    "QUALIFIED": {"SUSPENDED"},
    "SUSPENDED": {"QUALIFIED"},
    "REJECTED": set(),
}


@bp.post("/site-qualifications")
def create_site_qualification():
    require_roles("QualityEngineer")
    body = get_body(required=True)
    require_fields(body, ["site_name", "segment"])
    check_unknown_fields(body, _CREATE_ALLOWED)
    site_name = as_str(body["site_name"], "site_name")
    segment = as_enum(body["segment"], "segment", C.QUAL_SEGMENTS)
    validity_months = C.QUALIFICATION_VALIDITY_DEFAULT_MONTHS
    if "validity_months" in body:
        validity_months = as_int_at_least(body["validity_months"], "validity_months", 1)
    qualification = {
        "site_name": site_name,
        "segment": segment,
        "status": "REQUESTED",
        "qualified_at": None,
        "validity_months": validity_months,
    }
    qualification.update(store.stamp())
    store.site_qualifications[qualification["id"]] = qualification
    return success(site_qualification_public(qualification), 201)


@bp.post("/site-qualifications/<qual_id>/transition")
def transition_site_qualification(qual_id):
    require_roles("QualityEngineer")
    qualification = get_site_qualification(qual_id)
    body = get_body(required=True)
    require_fields(body, ["to_state"])
    check_unknown_fields(body, _TRANSITION_ALLOWED)
    to_state = as_enum(body["to_state"], "to_state", C.QUAL_STATUSES)

    # Row 5: the transition must exist in the qualification graph.
    if to_state not in _LEGAL_TRANSITIONS.get(qualification["status"], set()):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Qualification transition %s -> %s is not permitted" % (qualification["status"], to_state),
        )
    # Row 7: entering QUALIFIED requires no other QUALIFIED/SUSPENDED
    # qualification for the same site + segment.
    if to_state == "QUALIFIED":
        for other in store.site_qualifications.values():
            if (
                other["id"] != qualification["id"]
                and other["site_name"] == qualification["site_name"]
                and other["segment"] == qualification["segment"]
                and other["status"] in ("QUALIFIED", "SUSPENDED")
            ):
                raise ApiError(ERR_QUALIFICATION_OVERLAP, 409, "Another qualification for this site and segment is QUALIFIED or SUSPENDED")
    qualification["status"] = to_state
    if to_state == "QUALIFIED":
        # Stamped on every entry into QUALIFIED, including re-qualification.
        qualification["qualified_at"] = store.now()
    store.touch(qualification)
    return success(site_qualification_public(qualification))
