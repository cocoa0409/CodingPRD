"""Amendment motions: filing (one motion of right per cycle) and resolution
with its per-outcome role split (PRD 3.6)."""

from flask import Blueprint

from db import store, strip_internal
from errors import (
    raise_err, ERR_VALIDATION, ERR_FORBIDDEN_ROLE, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_PHASE, ERR_INVALID_STATE, ERR_AMENDMENT_QUOTA_EXCEEDED,
    ERR_AMENDMENT_VOLUME_EXCEEDED, ERR_SUBSTITUTE_CLAIM_MISMATCH,
)
from helpers import (
    require_roles, get_body, req_enum, req_array, opt_string, is_int,
    success_object, list_response, ALL_ROLES,
)
from lookups import (
    get_proceeding, get_motion, proceeding_context,
)

bp = Blueprint("amendments", __name__)

MOTION_PHASES = ("INSTITUTED", "REPLY_WINDOW", "REMANDED")
MOTION_OUTCOMES = ("GRANTED", "DENIED", "WITHDRAWN")
PANEL_OUTCOMES = ("GRANTED", "DENIED")


@bp.post("/ptab/proceedings/<proceedingId>/amendment-motions")
def create_motion(proceedingId):
    user_id, _ = require_roles("PatentOwner")
    proceeding = get_proceeding(proceedingId)
    petition, patent = proceeding_context(proceeding)
    if user_id != patent["owner_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "amendment motions may be filed only by the patent owner")
    body = get_body()
    substitute_claims = req_array(body, "substitute_claims")
    for sub in substitute_claims:
        if not isinstance(sub, dict):
            raise_err(ERR_VALIDATION, "substitute_claims entries must be objects")
        if not is_int(sub.get("original_claim_number")):
            raise_err(ERR_VALIDATION,
                      "original_claim_number must be an integer")
        if not isinstance(sub.get("substitute_text"), str) \
                or sub.get("substitute_text") == "":
            raise_err(ERR_VALIDATION, "substitute_text must be a string")

    # State (priority 7): phase gate.
    if proceeding["phase"] not in MOTION_PHASES:
        raise_err(ERR_INVALID_PHASE,
                  f"amendment motions are not accepted in phase "
                  f"{proceeding['phase']}")

    # Domain (priority 9): slot, then claim membership, then volume.
    if proceeding["amendment_slots_available"] <= 0:
        raise_err(ERR_AMENDMENT_QUOTA_EXCEEDED,
                  "no amendment slot available in the current briefing cycle")
    for sub in substitute_claims:
        if sub["original_claim_number"] not in proceeding["instituted_claims"]:
            raise_err(ERR_SUBSTITUTE_CLAIM_MISMATCH,
                      "every substitute must respond to an instituted claim")
    if len(substitute_claims) > len(proceeding["instituted_claims"]):
        raise_err(ERR_AMENDMENT_VOLUME_EXCEEDED,
                  "substitute count exceeds the number of instituted claims")

    motion = store.new_common()
    motion.update({
        "proceeding_id": proceeding["id"],
        "cycle": proceeding["briefing_cycle"],
        "substitute_claims": substitute_claims,
        "status": "FILED",
        "construction_standard": "PHILLIPS",
    })
    store.motions[motion["id"]] = motion
    proceeding["amendment_slots_available"] -= 1
    store.touch(proceeding)
    return success_object(strip_internal(motion), status=201)


@bp.get("/ptab/proceedings/<proceedingId>/amendment-motions")
def list_motions(proceedingId):
    require_roles(*ALL_ROLES)
    proceeding = get_proceeding(proceedingId)
    items = [m for m in store.motions.values()
             if m["proceeding_id"] == proceeding["id"]]
    return list_response(items)


@bp.post("/ptab/amendment-motions/<motionId>/resolve")
def resolve_motion(motionId):
    user_id, role = require_roles("BoardPanel", "PatentOwner")
    body = get_body()
    outcome = body.get("outcome")
    # Per-outcome role split (priority 2): only the panel may grant or deny;
    # only the patent owner may withdraw.
    if outcome in PANEL_OUTCOMES and role != "BoardPanel":
        raise_err(ERR_FORBIDDEN_ROLE,
                  "only BoardPanel may grant or deny an amendment motion")
    if outcome == "WITHDRAWN" and role != "PatentOwner":
        raise_err(ERR_FORBIDDEN_ROLE,
                  "only the patent owner may withdraw an amendment motion")

    motion = get_motion(motionId)
    proceeding = store.proceedings.get(motion["proceeding_id"])
    petition, patent = proceeding_context(proceeding)
    if outcome == "WITHDRAWN" and user_id != patent["owner_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "withdrawal requires the patent owner")

    outcome = req_enum(body, "outcome", MOTION_OUTCOMES)
    opt_string(body, "rationale")

    if motion["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, "the motion is no longer FILED")
    if outcome == "GRANTED" and proceeding["phase"] in ("DECIDED", "CLOSED"):
        raise_err(ERR_INVALID_PHASE,
                  "a motion may not be granted on a DECIDED or CLOSED "
                  "proceeding")

    motion["status"] = outcome
    store.touch(motion)
    if outcome == "GRANTED":
        # Claim ledger swap (PRD 2.9): per substitute, total +1,
        # cancelled +1, amended +1; claims_alive is unchanged.
        for _sub in motion["substitute_claims"]:
            patent["total_claims"] += 1
            patent["claims_cancelled_count"] += 1
            patent["claims_amended_count"] += 1
        patent["claims_alive"] = (
            patent["total_claims"] - patent["claims_cancelled_count"])
        store.touch(patent)
    elif outcome == "WITHDRAWN":
        proceeding["amendment_slots_available"] += 1
        store.touch(proceeding)
    # DENIED: the amendment slot stays consumed.
    return success_object(strip_internal(motion), status=200)
