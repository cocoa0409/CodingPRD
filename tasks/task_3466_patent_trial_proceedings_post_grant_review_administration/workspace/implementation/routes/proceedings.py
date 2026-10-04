"""Proceeding reads and the good-cause extension request (PRD 3.8)."""

from flask import Blueprint

from db import store, strip_internal, format_iso, parse_iso
from calculations import FWD_EXTENSION_DAYS, add_months
from datetime import timedelta
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_PHASE,
    ERR_EXTENSION_ALREADY_USED,
)
from helpers import (
    require_roles, get_body, req_string, success_object, list_response,
    request_arg, ALL_ROLES,
)
from lookups import get_proceeding, is_party_to_proceeding

bp = Blueprint("proceedings", __name__)


@bp.get("/ptab/proceedings")
def list_proceedings():
    require_roles(*ALL_ROLES)
    patent_id = request_arg("patent_id")
    petition_id = request_arg("petition_id")
    lead = request_arg("lead_judge_user_id")
    phase = request_arg("phase")
    items = store.proceedings.values()
    if patent_id is not None:
        items = [p for p in items if p["patent_id"] == patent_id]
    if petition_id is not None:
        items = [p for p in items if p["petition_id"] == petition_id]
    if lead is not None:
        items = [p for p in items if p["lead_judge_user_id"] == lead]
    if phase is not None:
        items = [p for p in items if p["phase"] == phase]
    return list_response(list(items))


@bp.get("/ptab/proceedings/<proceedingId>")
def get_proceeding_route(proceedingId):
    require_roles(*ALL_ROLES)
    return success_object(strip_internal(get_proceeding(proceedingId)))


@bp.post("/ptab/proceedings/<proceedingId>/extension-requests")
def request_extension(proceedingId):
    user_id, _ = require_roles("Petitioner", "PatentOwner")
    proceeding = get_proceeding(proceedingId)
    # Ownership (priority 4): parties to the proceeding only.
    if not is_party_to_proceeding(user_id, proceeding):
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "only a party to the proceeding may request an extension")
    body = get_body()
    justification = req_string(body, "justification")
    if len(justification) < 20:
        raise_err(ERR_VALIDATION,
                  "justification must be at least 20 characters")
    # State (priority 7): the single extension first, then the phase gate
    # (PRD 3.8 prose order).
    if proceeding["extension_used"]:
        raise_err(ERR_EXTENSION_ALREADY_USED,
                  "the single good-cause extension has already been granted")
    if proceeding["phase"] in ("DECIDED", "CLOSED"):
        raise_err(ERR_INVALID_PHASE,
                  "no extension after the proceeding is DECIDED or CLOSED")
    proceeding["_fwd_dt"] = proceeding["_fwd_dt"] + timedelta(
        days=FWD_EXTENSION_DAYS)
    proceeding["fwd_due_date"] = format_iso(proceeding["_fwd_dt"])
    proceeding["advisory_anniversary_date"] = format_iso(
        add_months(parse_iso(proceeding["advisory_anniversary_date"]), 6))
    proceeding["extension_used"] = True
    store.touch(proceeding)
    return success_object(strip_internal(proceeding), status=200)
