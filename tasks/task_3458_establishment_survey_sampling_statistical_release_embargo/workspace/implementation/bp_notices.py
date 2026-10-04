"""/survey/methodology-notices: create and advance (PRD 3.8)."""
from flask import Blueprint

from authz import get_auth, require_role
from bp_programs import find_program_by_code
from calc_apply import activate_notice
from envelope import ok
from errors import (
    raise_err, ERR_VALIDATION, ERR_PROGRAM_NOT_FOUND, ERR_NOTICE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_NOTICE_NOT_EFFECTIVE,
)
from store import DB, new_entity, touch, now, INDUSTRIES, SIZE_CLASSES
from validate import get_body, req_str, req_enum, req_int, req_instant

bp = Blueprint("notices", __name__)

ACTIONS = {"ANNOUNCE", "ACTIVATE", "WITHDRAW"}


@bp.post("/methodology-notices")
def create_notice():
    _user, role = get_auth()
    require_role(role, {"SurveyMethodologist"})
    data = get_body()

    program = None
    if data.get("program_code") is not None:
        program = find_program_by_code(data["program_code"])
        if program is None:
            raise_err(ERR_PROGRAM_NOT_FOUND, "program_code does not resolve")

    req_str(data, "program_code")
    title = req_str(data, "title")
    effective_from = req_instant(data, "effective_from")
    scope = req_enum(data, "scope", ["ALL_SERIES", "LISTED_SERIES"])
    series = data.get("series")
    if scope == "LISTED_SERIES":
        if not isinstance(series, list) or not series:
            raise_err(ERR_VALIDATION,
                      "series must be a non-empty array when scope is LISTED_SERIES")
        for entry in series:
            if not isinstance(entry, dict):
                raise_err(ERR_VALIDATION, "each series entry must be an object")
            if entry.get("industry_code") not in INDUSTRIES:
                raise_err(ERR_VALIDATION, "series industry_code is invalid")
            if entry.get("size_class") not in SIZE_CLASSES:
                raise_err(ERR_VALIDATION, "series size_class is invalid")
    ppm = req_int(data, "reconstruction_factor_ppm", minimum=1)

    notice = new_entity("notices", {
        "program_code": program["code"],
        "title": title,
        "effective_from": effective_from,
        "scope": scope,
        "series": series if isinstance(series, list) else [],
        "reconstruction_factor_ppm": ppm,
        "notice_status": "DRAFT",
        "announced_at": None,
        "activated_at": None,
    })
    return ok(notice, status=201)


@bp.post("/methodology-notices/<nid>/advance")
def advance_notice(nid):
    _user, role = get_auth()
    require_role(role, {"SurveyMethodologist"})
    notice = DB["notices"].get(nid)
    if notice is None:
        raise_err(ERR_NOTICE_NOT_FOUND, "methodology notice not found")
    data = get_body()
    action = req_str(data, "action")
    if action not in ACTIONS:
        raise_err(ERR_VALIDATION, f"unknown notice action '{action}'")

    status = notice["notice_status"]
    if action == "ANNOUNCE":
        if status != "DRAFT":
            raise_err(ERR_INVALID_STATE, f"cannot announce a notice in {status}")
        if notice["effective_from"] <= now():
            raise_err(ERR_VALIDATION,
                      "effective_from must be strictly after the current clock")
        notice["notice_status"] = "ANNOUNCED"
        notice["announced_at"] = now()
        touch(notice)
    elif action == "ACTIVATE":
        if status != "ANNOUNCED":
            raise_err(ERR_INVALID_STATE, f"cannot activate a notice in {status}")
        if now() < notice["effective_from"]:
            raise_err(ERR_NOTICE_NOT_EFFECTIVE,
                      "notice is not yet effective")
        activate_notice(notice)
    elif action == "WITHDRAW":
        if status not in ("DRAFT", "ANNOUNCED"):
            raise_err(ERR_INVALID_STATE, f"cannot withdraw a notice in {status}")
        notice["notice_status"] = "WITHDRAWN"
        touch(notice)
    return ok(notice)
