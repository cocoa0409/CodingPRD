"""Litigation matter reads and the OCC-guarded docket PATCH (PRD 3.2)."""

from flask import Blueprint

from db import store, strip_internal, parse_iso
from errors import (
    raise_err, ERR_VALIDATION, ERR_STALE_MATTER_VERSION, ERR_INVALID_STATE,
)
from helpers import (
    require_roles, get_body, req_int, success_object, list_response,
    request_arg, ALL_ROLES,
)
from lookups import get_matter
from calculations import refresh_pending_petitions_for_patent

bp = Blueprint("matters", __name__)

MATTER_STATUSES = ("ACTIVE", "STAYED", "SETTLED", "TRIAL_COMPLETED", "DISMISSED")
TERMINAL_STATUSES = ("SETTLED", "TRIAL_COMPLETED", "DISMISSED")

# LitigationMatter state machine (SCAFFOLD Table 2).
ALLOWED_TRANSITIONS = {
    "ACTIVE": {"STAYED", "SETTLED", "TRIAL_COMPLETED", "DISMISSED"},
    "STAYED": {"ACTIVE", "SETTLED"},
}


@bp.get("/ptab/litigation-matters")
def list_matters():
    require_roles(*ALL_ROLES)
    patent_id = request_arg("patent_id")
    defendant_party_id = request_arg("defendant_party_id")
    status = request_arg("status")
    items = store.matters.values()
    if patent_id is not None:
        items = [m for m in items if m["patent_id"] == patent_id]
    if defendant_party_id is not None:
        items = [m for m in items if m["defendant_party_id"] == defendant_party_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return list_response(list(items))


@bp.get("/ptab/litigation-matters/<matterId>")
def get_matter_route(matterId):
    require_roles(*ALL_ROLES)
    return success_object(strip_internal(get_matter(matterId)))


@bp.patch("/ptab/litigation-matters/<matterId>")
def patch_matter(matterId):
    require_roles("PlatformAdmin")
    matter = get_matter(matterId)
    body = get_body()

    # Schema (priority 5).
    expected = req_int(body, "expected_litigation_matter_version")
    new_status = body.get("status")
    if new_status is not None and new_status not in MATTER_STATUSES:
        raise_err(ERR_VALIDATION, f"status must be one of {list(MATTER_STATUSES)}")
    has_trial_date = "trial_date" in body
    new_trial_date = body.get("trial_date")
    new_trial_dt = None
    if has_trial_date and new_trial_date is not None:
        if not isinstance(new_trial_date, str):
            raise_err(ERR_VALIDATION, "trial_date must be an ISO 8601 datetime")
        try:
            new_trial_dt = parse_iso(new_trial_date)
        except (ValueError, TypeError):
            raise_err(ERR_VALIDATION,
                      "trial_date must be a valid ISO 8601 datetime")

    # OCC (priority 6).
    if expected != matter["version"]:
        raise_err(ERR_STALE_MATTER_VERSION,
                  "expected_litigation_matter_version does not match the "
                  "matter's current version")

    # State (priority 7): terminal matters admit no patch; transitions must
    # follow the LitigationMatter machine.
    if matter["status"] in TERMINAL_STATUSES:
        raise_err(ERR_INVALID_STATE,
                  f"matter in terminal status {matter['status']} admits no patch")
    if new_status is not None and new_status != matter["status"]:
        if new_status not in ALLOWED_TRANSITIONS[matter["status"]]:
            raise_err(ERR_INVALID_STATE,
                      f"status transition {matter['status']} -> {new_status} "
                      "is not permitted")
    elif new_status == matter["status"]:
        raise_err(ERR_INVALID_STATE,
                  f"status transition {matter['status']} -> {new_status} "
                  "is not permitted")

    # Apply.
    if has_trial_date:
        matter["trial_date"] = new_trial_date
        matter["_trial_dt"] = new_trial_dt
    if new_status is not None:
        matter["status"] = new_status
        if new_status == "STAYED":
            matter["stay_reason"] = "MANUAL_STAY"
        else:
            # stay_reason is null in every non-STAYED status.
            matter["stay_reason"] = None
    store.touch(matter)
    refresh_pending_petitions_for_patent(matter["patent_id"])
    return success_object(strip_internal(matter), status=200)
