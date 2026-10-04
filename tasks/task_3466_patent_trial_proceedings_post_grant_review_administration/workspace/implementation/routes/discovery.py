"""Discovery requests and the deterministic panel ruling (PRD 3.6)."""

from flask import Blueprint

from db import store, strip_internal
from calculations import garmin_score, GARMIN_GRANT_THRESHOLD
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE,
)
from helpers import (
    require_roles, get_body, req_enum, is_int, success_object, list_response,
    ALL_ROLES,
)
from lookups import get_proceeding, get_request, is_party_to_proceeding

bp = Blueprint("discovery", __name__)

DISCOVERY_TYPES = ("ROUTINE", "ADDITIONAL")


@bp.post("/ptab/proceedings/<proceedingId>/discovery-requests")
def create_discovery_request(proceedingId):
    user_id, _ = require_roles("Petitioner", "PatentOwner")
    proceeding = get_proceeding(proceedingId)
    if not is_party_to_proceeding(user_id, proceeding):
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "only a party to the proceeding may request discovery")
    body = get_body()
    discovery_type = req_enum(body, "discovery_type", DISCOVERY_TYPES)

    if discovery_type == "ADDITIONAL":
        factors = body.get("factor_scores")
        if (not isinstance(factors, list) or len(factors) != 5
                or any(not is_int(f) or f < 0 or f > 2 for f in factors)):
            raise_err(ERR_VALIDATION,
                      "factor_scores must be exactly 5 integers each 0..2")
        status = "PENDING"
        score = garmin_score(factors, proceeding["phase"])
        stored_factors = list(factors)
    else:
        # ROUTINE is auto-granted at creation; any supplied factor_scores
        # are simply ignored.
        status = "GRANTED"
        score = None
        stored_factors = None

    request_obj = store.new_common()
    request_obj.update({
        "proceeding_id": proceeding["id"],
        "requester_user_id": user_id,
        "discovery_type": discovery_type,
        "factor_scores": stored_factors,
        "garmin_score": score,
        "status": status,
    })
    store.discovery_requests[request_obj["id"]] = request_obj
    return success_object(strip_internal(request_obj), status=201)


@bp.get("/ptab/proceedings/<proceedingId>/discovery-requests")
def list_discovery_requests(proceedingId):
    require_roles(*ALL_ROLES)
    proceeding = get_proceeding(proceedingId)
    items = [r for r in store.discovery_requests.values()
             if r["proceeding_id"] == proceeding["id"]]
    return list_response(items)


@bp.post("/ptab/discovery-requests/<requestId>/rule")
def rule_discovery_request(requestId):
    require_roles("BoardPanel")
    request_obj = get_request(requestId)
    if request_obj["status"] != "PENDING" or \
            request_obj["discovery_type"] != "ADDITIONAL":
        raise_err(ERR_INVALID_STATE,
                  "only a PENDING ADDITIONAL request may be ruled on")
    request_obj["status"] = (
        "GRANTED" if request_obj["garmin_score"] >= GARMIN_GRANT_THRESHOLD
        else "DENIED")
    store.touch(request_obj)
    return success_object(strip_internal(request_obj), status=200)
