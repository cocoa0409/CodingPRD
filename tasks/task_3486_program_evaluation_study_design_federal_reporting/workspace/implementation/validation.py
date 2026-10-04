"""Ordered request-validation pipeline, stages 1-4.

Stage 1: user context headers. Stage 2: role authorization. Stage 3 is path
existence (handled per endpoint against the stores). Stage 4: body schema.
Later stages (OCC, state, compliance, windows, gates, fiscal) are enforced
inline by the endpoint handlers in pipeline order.
"""
from flask import request

from clock import parse_iso
from errors import raise_err

ROLE_AGENCY_OFFICER = "AgencyOfficer"
ROLE_PRINCIPAL_INVESTIGATOR = "PrincipalInvestigator"
ROLE_STUDY_DIRECTOR = "StudyDirector"
ROLE_DATA_MANAGER = "DataManager"
ROLE_IRB_REVIEWER = "IRBReviewer"
ROLE_PEER_REVIEWER = "PeerReviewer"
ROLE_PARTICIPANT = "Participant"
ROLE_EXTERNAL_RESEARCHER = "ExternalResearcher"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = (
    ROLE_AGENCY_OFFICER,
    ROLE_PRINCIPAL_INVESTIGATOR,
    ROLE_STUDY_DIRECTOR,
    ROLE_DATA_MANAGER,
    ROLE_IRB_REVIEWER,
    ROLE_PEER_REVIEWER,
    ROLE_PARTICIPANT,
    ROLE_EXTERNAL_RESEARCHER,
    ROLE_PLATFORM_ADMIN,
)

STAFF_ROLES = (
    ROLE_AGENCY_OFFICER,
    ROLE_PRINCIPAL_INVESTIGATOR,
    ROLE_STUDY_DIRECTOR,
    ROLE_DATA_MANAGER,
    ROLE_IRB_REVIEWER,
    ROLE_PEER_REVIEWER,
)


def authenticate():
    """Stage 1: X-User-ID and X-User-Role must be present; role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise_err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and the role must "
            "be one of the declared role names",
        )
    return uid, role


def authorize(role, allowed):
    """Stage 2: role must be in the endpoint's role list."""
    if role not in allowed:
        raise_err("ERR_UNAUTHORIZED_ROLE",
                  "Role %s may not perform this operation" % role)


def get_json_body():
    """Body must be a JSON object when present; empty body reads as {}."""
    if not request.data:
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None or not isinstance(data, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_kind(name, value, kind):
    if kind == "str":
        ok = isinstance(value, str)
    elif kind == "int":
        ok = _is_int(value)
    elif kind == "num":
        ok = _is_num(value)
    elif kind == "dt":
        ok = parse_iso(value) is not None
    elif kind == "arr_str":
        ok = isinstance(value, list) and all(isinstance(x, str) for x in value)
    elif kind == "arr_int":
        ok = isinstance(value, list) and all(_is_int(x) for x in value)
    elif kind == "arr_num":
        ok = isinstance(value, list) and all(_is_num(x) for x in value)
    elif kind.startswith("enum:"):
        ok = value in kind[len("enum:"):].split("|")
    else:
        ok = False
    if not ok:
        raise_err("ERR_INVALID_REQUEST",
                  "Field '%s' failed type or enum validation" % name)


def check_schema(body, spec):
    """Stage 4: reject undeclared fields, require required fields, type-check.

    spec maps field name -> (kind, required). An explicit JSON null for an
    optional field is treated as omitted.
    """
    for key in body:
        if key not in spec:
            raise_err("ERR_INVALID_REQUEST", "Undeclared field: %s" % key)
    for name, (kind, required) in spec.items():
        if name not in body or body[name] is None:
            if required:
                raise_err("ERR_INVALID_REQUEST",
                          "Missing required field: %s" % name)
            continue
        _check_kind(name, body[name], kind)
