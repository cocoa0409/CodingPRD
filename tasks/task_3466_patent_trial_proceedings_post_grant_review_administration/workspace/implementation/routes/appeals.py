"""Appeals and appellate dispositions, including the remand cascade
(PRD 3.9)."""

from flask import Blueprint

from db import store, strip_internal
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE,
    ERR_PROCEEDING_NOT_DECIDED, ERR_APPEAL_ALREADY_PENDING,
)
from helpers import (
    require_roles, get_body, req_enum, success_object, list_response,
    ALL_ROLES,
)
from lookups import get_proceeding, get_appeal, is_party_to_proceeding

bp = Blueprint("appeals", __name__)

APPEAL_OUTCOMES = ("AFFIRMED", "DISMISSED", "VACATED_AND_REMANDED")
REMAND_INSTRUCTIONS = ("REOPEN_RECORD", "RECONSIDER")


@bp.post("/ptab/proceedings/<proceedingId>/appeals")
def create_appeal(proceedingId):
    user_id, _ = require_roles("Petitioner", "PatentOwner")
    proceeding = get_proceeding(proceedingId)
    if not is_party_to_proceeding(user_id, proceeding):
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "only a party to the proceeding may appeal")
    if proceeding["phase"] != "DECIDED":
        raise_err(ERR_PROCEEDING_NOT_DECIDED,
                  "appeal creation requires the proceeding to be DECIDED")
    for other in store.appeals.values():
        if other["proceeding_id"] == proceeding["id"] \
                and other["status"] == "FILED":
            raise_err(ERR_APPEAL_ALREADY_PENDING,
                      "an appeal in FILED status already exists for this "
                      "proceeding")

    appeal = store.new_common()
    appeal.update({
        "proceeding_id": proceeding["id"],
        "appellant_user_id": user_id,
        "status": "FILED",
        "remand_instructions": None,
    })
    store.appeals[appeal["id"]] = appeal
    return success_object(strip_internal(appeal), status=201)


@bp.get("/ptab/proceedings/<proceedingId>/appeals")
def list_appeals(proceedingId):
    require_roles(*ALL_ROLES)
    proceeding = get_proceeding(proceedingId)
    items = [a for a in store.appeals.values()
             if a["proceeding_id"] == proceeding["id"]]
    return list_response(items)


@bp.post("/ptab/appeals/<appealId>/decide")
def decide_appeal(appealId):
    require_roles("AppealsCourt")
    appeal = get_appeal(appealId)
    body = get_body()

    # Schema (priority 5): remand_instructions present iff vacating.
    outcome = req_enum(body, "outcome", APPEAL_OUTCOMES)
    remand = body.get("remand_instructions")
    if outcome == "VACATED_AND_REMANDED":
        if remand not in REMAND_INSTRUCTIONS:
            raise_err(ERR_VALIDATION,
                      "remand_instructions must be REOPEN_RECORD or "
                      "RECONSIDER when the outcome is VACATED_AND_REMANDED")
    else:
        if remand is not None:
            raise_err(ERR_VALIDATION,
                      "remand_instructions must be absent unless the outcome "
                      "is VACATED_AND_REMANDED")

    # State (priority 7).
    if appeal["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, "the appeal is no longer FILED")

    proceeding = store.proceedings.get(appeal["proceeding_id"])
    appeal["status"] = outcome
    if outcome == "VACATED_AND_REMANDED":
        appeal["remand_instructions"] = remand
    store.touch(appeal)

    if outcome in ("AFFIRMED", "DISMISSED"):
        proceeding["phase"] = "CLOSED"
        store.touch(proceeding)
        return success_object(strip_internal(appeal), status=200)

    # VACATED_AND_REMANDED: one atomic unwind cascade (PRD 3.9).
    now = store.clock.now()
    proceeding["phase"] = "REMANDED"
    proceeding["briefing_cycle"] += 1
    proceeding["cycle_anchor_date"] = store.clock.now_iso()
    proceeding["_anchor_dt"] = now
    proceeding["amendment_slots_available"] += 1
    proceeding["estoppel_applied"] = False
    store.touch(proceeding)

    patent = store.patents.get(proceeding["patent_id"])
    if patent is not None and patent["status"] in (
            "PARTIALLY_CANCELLED", "AMENDED", "CONFIRMED"):
        patent["status"] = "IN_REVIEW"
        store.touch(patent)

    for matter in store.matters.values():
        if matter["patent_id"] == proceeding["patent_id"] \
                and matter["estoppel_claims"] != []:
            matter["estoppel_claims"] = []
            store.touch(matter)
    return success_object(strip_internal(appeal), status=200)
