"""The logical clock and its six pinned scheduled checkpoints (PRD 2.6)."""
from datetime import timedelta

import constants as C
from store import db, sorted_records, touch
from val import d, r2

from services import rating


def _term_sweep_order(terms, key):
    return sorted(terms, key=lambda t: (d(t[key]), t["created_at"], t["_seq"]))


def set_clock(raw_instant, parsed_instant):
    """Set the clock, then run the checkpoint sweep in its pinned order."""
    # Step 1 - the clock itself.
    db.clock_str = raw_instant
    db.clock_dt = parsed_instant
    today = parsed_instant.date()

    promoted_term_ids = []
    expired_term_ids = []
    expired_enrollment_ids = []
    lapsed_insured_ids = []
    closed_claim_ids = []

    # Step 2 - ISSUED terms effective on or before today become IN_FORCE.
    pending = [
        t
        for t in db.policy_terms.values()
        if t["status"] == "ISSUED" and d(t["effective_date"]) <= today
    ]
    for term in _term_sweep_order(pending, "effective_date"):
        term["status"] = "IN_FORCE"
        touch(term)
        promoted_term_ids.append(term["id"])
        policy = db.policies.get(term["policy_id"])
        if policy is not None:
            rating.derive_current_term(policy)
            touch(policy)

    # Step 3 - IN_FORCE terms expiring on or before today become EXPIRED.
    live = [
        t
        for t in db.policy_terms.values()
        if t["status"] == "IN_FORCE" and d(t["expiration_date"]) <= today
    ]
    affected_policies = []
    for term in _term_sweep_order(live, "expiration_date"):
        term["status"] = "EXPIRED"
        touch(term)
        expired_term_ids.append(term["id"])
        policy = db.policies.get(term["policy_id"])
        if policy is not None and policy not in affected_policies:
            affected_policies.append(policy)
    for policy in affected_policies:
        rating.derive_current_term(policy)
        rating.derive_policy_status(policy)
        touch(policy)

    # Step 4 - completed enrollments reaching their expiry become EXPIRED.
    expiring = [
        e
        for e in sorted_records(list(db.enrollments.values()))
        if e["status"] == "COMPLETED" and e["expires_on"] and d(e["expires_on"]) <= today
    ]
    touched_insureds = []
    for enrollment in expiring:
        enrollment["status"] = "EXPIRED"
        touch(enrollment)
        expired_enrollment_ids.append(enrollment["id"])
        if enrollment["insured_id"] not in touched_insureds:
            touched_insureds.append(enrollment["insured_id"])
    for insured_id in touched_insureds:
        rating.rerate_drafts(insured_id)

    # Step 5 - credentialing verdicts whose expiry fell behind the clock lapse.
    for insured in sorted_records(list(db.insureds.values())):
        if insured["credentialing_status"] not in ("CREDENTIALED", "PROVISIONAL"):
            continue
        expires = insured.get("credentialing_expires_on")
        if not expires or not (d(expires) < today):
            continue
        insured["credentialing_status"] = "LAPSED"
        if insured["status"] == "ACTIVE":
            insured["status"] = "SUSPENDED"
        touch(insured)
        lapsed_insured_ids.append(insured["id"])

    # Step 6 - resolved claims past their thirty day run-off close.
    for claim in sorted_records(list(db.claims.values())):
        if claim["claim_status"] != "RESOLVED" or not claim["resolved_on"]:
            continue
        if d(claim["resolved_on"]) + timedelta(days=C.CLAIM_CLOSE_LAG_DAYS) > today:
            continue
        claim["claim_status"] = "CLOSED"
        claim["closed_on"] = today.isoformat()
        touch(claim)
        closed_claim_ids.append(claim["id"])

    return {
        "current_utc": db.clock_str,
        "promoted_term_ids": promoted_term_ids,
        "expired_term_ids": expired_term_ids,
        "expired_enrollment_ids": expired_enrollment_ids,
        "lapsed_insured_ids": lapsed_insured_ids,
        "closed_claim_ids": closed_claim_ids,
    }
