"""Final written decisions: issuance, claim-ledger reconciliation, estoppel
attachment, and the full-cancellation stay cascade (PRD 3.8, 2.9, 2.10)."""

from flask import Blueprint

from db import store, strip_internal
from calculations import refresh_pending_petitions_for_patent
from errors import (
    raise_err, ERR_VALIDATION, ERR_DECISION_ALREADY_ISSUED,
    ERR_INVALID_PHASE, ERR_FWD_DEADLINE_PASSED, ERR_OUTCOME_SET_INVALID,
)
from helpers import (
    require_roles, get_body, req_array, is_int, success_object,
    list_response, ALL_ROLES,
)
from lookups import get_proceeding, proceeding_context

bp = Blueprint("decisions", __name__)

FWD_OUTCOMES = ("UNPATENTABLE", "NOT_UNPATENTABLE", "AMENDED_SUBSTITUTED")


@bp.post("/ptab/proceedings/<proceedingId>/final-decisions")
def issue_final_decision(proceedingId):
    require_roles("BoardPanel")
    proceeding = get_proceeding(proceedingId)
    body = get_body()

    # Schema (priority 5).
    outcomes = req_array(body, "outcomes")
    for entry in outcomes:
        if not isinstance(entry, dict):
            raise_err(ERR_VALIDATION, "outcomes entries must be objects")
        if not is_int(entry.get("claim_number")):
            raise_err(ERR_VALIDATION, "claim_number must be an integer")
        if entry.get("outcome") not in FWD_OUTCOMES:
            raise_err(ERR_VALIDATION,
                      f"outcome must be one of {list(FWD_OUTCOMES)}")

    # State guards in the fixed order pinned by PRD 3.8: already-issued first,
    # then phase, then the statutory deadline.
    for existing in store.fwds.values():
        if (existing["proceeding_id"] == proceeding["id"]
                and existing["cycle"] == proceeding["briefing_cycle"]):
            raise_err(ERR_DECISION_ALREADY_ISSUED,
                      "a final written decision already exists for the "
                      "current briefing cycle")
    if proceeding["phase"] != "DECISION_PHASE":
        raise_err(ERR_INVALID_PHASE,
                  "the proceeding must be in DECISION_PHASE")
    now = store.clock.now()
    if now > proceeding["_fwd_dt"]:
        raise_err(ERR_FWD_DEADLINE_PASSED,
                  "the final-written-decision deadline has passed")

    # Domain (priority 9): outcome-set coverage.
    instituted = proceeding["instituted_claims"]
    seen = [entry["claim_number"] for entry in outcomes]
    if len(set(seen)) != len(seen) or set(seen) != set(instituted) \
            or len(seen) != len(instituted):
        raise_err(ERR_OUTCOME_SET_INVALID,
                  "outcomes must cover every instituted claim exactly once")
    granted_substitutes = set()
    for motion in store.motions.values():
        if motion["proceeding_id"] == proceeding["id"] \
                and motion["status"] == "GRANTED":
            for sub in motion["substitute_claims"]:
                granted_substitutes.add(sub["original_claim_number"])
    for entry in outcomes:
        if entry["claim_number"] in granted_substitutes \
                and entry["outcome"] != "AMENDED_SUBSTITUTED":
            raise_err(ERR_OUTCOME_SET_INVALID,
                      "every claim with a granted substitute must be marked "
                      "AMENDED_SUBSTITUTED")

    # Persist the immutable event record.
    now_iso = store.clock.now_iso()
    cancelled_here = sum(1 for e in outcomes if e["outcome"] == "UNPATENTABLE")
    fwd = {
        "id": store.new_id(),
        "created_at": now_iso,
        "_seq": store.next_seq(),
        "proceeding_id": proceeding["id"],
        "cycle": proceeding["briefing_cycle"],
        "outcomes": outcomes,
        "issued_at": now_iso,
        "claims_cancelled_count": cancelled_here,
    }
    store.fwds[fwd["id"]] = fwd

    proceeding["phase"] = "DECIDED"
    proceeding["estoppel_applied"] = True
    store.touch(proceeding)

    # Claim ledger reconciliation and status precedence (PRD 2.9).
    petition, patent = proceeding_context(proceeding)
    patent["claims_cancelled_count"] += cancelled_here
    patent["claims_alive"] = (
        patent["total_claims"] - patent["claims_cancelled_count"])
    if patent["claims_alive"] == 0:
        patent["status"] = "FULLY_CANCELLED"
    elif patent["claims_amended_count"] > 0:
        patent["status"] = "AMENDED"
    elif patent["claims_cancelled_count"] > 0:
        patent["status"] = "PARTIALLY_CANCELLED"
    else:
        patent["status"] = "CONFIRMED"
    store.touch(patent)

    # Estoppel: matters naming the petitioner as defendant receive the full
    # challenged-claim set, whatever their current status.
    for matter in store.matters.values():
        if matter["patent_id"] != patent["id"]:
            continue
        if matter["defendant_party_id"] != petition["petitioner_id"]:
            continue
        new_claims = list(petition["challenged_claims"])
        if matter["estoppel_claims"] != new_claims:
            matter["estoppel_claims"] = new_claims
            store.touch(matter)

    # Full cancellation auto-stays every still-ACTIVE matter for the patent.
    if patent["status"] == "FULLY_CANCELLED":
        for matter in store.matters.values():
            if matter["patent_id"] == patent["id"] \
                    and matter["status"] == "ACTIVE":
                matter["status"] = "STAYED"
                matter["stay_reason"] = "PATENT_CANCELLED"
                store.touch(matter)
        refresh_pending_petitions_for_patent(patent["id"])

    return success_object(strip_internal(fwd), status=201)


@bp.get("/ptab/proceedings/<proceedingId>/final-decisions")
def list_final_decisions(proceedingId):
    require_roles(*ALL_ROLES)
    proceeding = get_proceeding(proceedingId)
    items = [f for f in store.fwds.values()
             if f["proceeding_id"] == proceeding["id"]]
    return list_response(items)
