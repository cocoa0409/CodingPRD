"""Strike application and cascade helpers shared by impound/run failure paths."""

from db import store
from services_common import new_id, now_iso, touch
from services_calc import recompute_risk_posture


def apply_funding_strike(client, impound, kind):
    """Create FundingFailureEvent, recompute posture, append CreditAssessment,
    auto-suspend on 3rd strike, increment Client.version."""
    # Recompute count including the new event: create event first, then recompute.
    event = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
        "impound_id": impound["id"],
        "client_id": client["id"],
        "kind": kind,
        "occurred_at": now_iso(),
        "resolved_at": None,
        "strike_count_after": None,  # set below
    }
    store.funding_failures[event["id"]] = event

    prior_posture = client["risk_posture"]
    new_posture, count = recompute_risk_posture(client)
    event["strike_count_after"] = count

    # CreditAssessment appended for every posture recomputation
    assessment = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
        "updated_at": now_iso(),
        "version": 1,
        "client_id": client["id"],
        "assessed_at": now_iso(),
        "prior_posture": prior_posture,
        "new_posture": new_posture,
        "trigger": "FUNDING_FAILURE",
        "note": None,
    }
    store.credit_assessments[assessment["id"]] = assessment

    # 3rd unresolved strike suspends the client
    if count >= 3 and client["status"] == "ACTIVE":
        client["status"] = "SUSPENDED"

    touch(client)
    return event


def resolve_funding_failure(client, event):
    """Cure a funding failure: set resolved_at, recompute posture, append assessment."""
    event["resolved_at"] = now_iso()
    prior_posture = client["risk_posture"]
    new_posture, count = recompute_risk_posture(client)
    assessment = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
        "updated_at": now_iso(),
        "version": 1,
        "client_id": client["id"],
        "assessed_at": now_iso(),
        "prior_posture": prior_posture,
        "new_posture": new_posture,
        "trigger": "FAILURE_CURED",
        "note": None,
    }
    store.credit_assessments[assessment["id"]] = assessment
    touch(client)


def cancel_scheduled_deposits_for_run(run_id):
    """Cascade: run's SCHEDULED TaxDeposit rows -> CANCELLED, each touched."""
    for dep in store.deposits.values():
        if dep["payroll_run_id"] == run_id and dep["status"] == "SCHEDULED":
            dep["status"] = "CANCELLED"
            touch(dep)
