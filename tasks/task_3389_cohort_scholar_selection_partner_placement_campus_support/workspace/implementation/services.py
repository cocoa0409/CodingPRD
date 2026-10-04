"""Cross-entity cascades: offer expiry sweep, waitlist promotion, pre-collegiate
withdrawal cascade, cohort completion, outcome rates, and standing derivation.
"""

from datetime import timedelta

from constants import (
    BPS_DENOMINATOR,
    OFFER_TTL_DAYS,
    PROBATION_RETENTION_FLOOR_BPS,
    RECOVERY_RETENTION_BPS,
    TERMINAL_ENROLLMENT,
)
from core import add, now, rhu, store, touch
from ledger import accepted_offer_of, has_live_offer, seat_counts


def create_offer(nominee, cohort):
    """OFFERED offer with expires_at = logical now + 14 days (PRD 2.4/3.5)."""
    offer = add(
        store.offers,
        {
            "nominee_id": nominee["id"],
            "cohort_id": cohort["id"],
            "status": "OFFERED",
            "expires_at": now() + timedelta(days=OFFER_TTL_DAYS),
        },
    )
    touch(cohort)  # offers_outstanding rose by one
    return offer


def run_promotion_sweep(cohort):
    """Waitlist promotion (PRD 3.5): fires only while the cohort is FORMING
    with seats_remaining > 0. Ranking: round_3_score DESC, nominee created_at
    ASC (insertion order breaks created_at ties; id is never used)."""
    if cohort["status"] != "FORMING":
        return
    while True:
        committed, outstanding = seat_counts(cohort["id"])
        if cohort["cohort_size"] - committed - outstanding <= 0:
            return
        eligible = [
            n
            for n in store.nominees.values()
            if n["status"] == "WAITLISTED"
            and n["city_program_id"] == cohort["city_program_id"]
            and not has_live_offer(n["id"])
        ]
        if not eligible:
            return
        eligible.sort(key=lambda n: (-n["round_3_score"], n["_seq"]))
        pick = eligible[0]
        pick["status"] = "SELECTED"
        touch(pick)
        create_offer(pick, cohort)


def run_offer_expiry_sweep():
    """Offer expiry (PRD 2.4): OFFERED offers with expires_at strictly before
    the new logical now -> EXPIRED, created_at ASC; promotion sweep per cohort."""
    expired = [
        o
        for o in store.offers.values()
        if o["status"] == "OFFERED" and o["expires_at"] < now()
    ]
    expired.sort(key=lambda o: o["_seq"])
    for offer in expired:
        offer["status"] = "EXPIRED"
        touch(offer)
        cohort = store.cohorts.get(offer["cohort_id"])
        if cohort is not None:
            touch(cohort)  # offers_outstanding fell by one
            run_promotion_sweep(cohort)


def revoke_pending_offers_of_nominee(nominee):
    """DROP side effect (PRD 3.2): pending OFFERED offer -> REVOKED, ledger
    recompute, promotion sweep for that cohort."""
    for offer in list(store.offers.values()):
        if offer["nominee_id"] == nominee["id"] and offer["status"] == "OFFERED":
            offer["status"] = "REVOKED"
            touch(offer)
            cohort = store.cohorts.get(offer["cohort_id"])
            if cohort is not None:
                touch(cohort)
                run_promotion_sweep(cohort)


def withdraw_scholar_pre_collegiate(scholar):
    """PRE_COLLEGIATE -> WITHDRAWN cascade (PRD 3.5/3.7): accepted offer ->
    REVOKED, seat released; LOCKED cohort with seats now free reverts to
    FORMING and the promotion sweep runs. Suppressed once the cohort is
    MATRICULATED or COMPLETED (the LOCKED guard covers that)."""
    cohort = store.cohorts.get(scholar["cohort_id"])
    offer = accepted_offer_of(scholar["cohort_id"], scholar["nominee_id"])
    if offer is not None:
        offer["status"] = "REVOKED"
        touch(offer)
    if cohort is None:
        return
    touch(cohort)  # seats_committed fell by one
    if cohort["status"] == "LOCKED":
        committed, _ = seat_counts(cohort["id"])
        if committed < cohort["cohort_size"]:
            cohort["status"] = "FORMING"
            touch(cohort)
    # PRD 3.5: the sweep triggers on any event that raises seats_remaining
    # while the cohort is FORMING — a revocation qualifies even when the cohort
    # was already FORMING (no revert needed). Self-guards: no-op unless FORMING,
    # so the cascade stays suppressed once MATRICULATED or COMPLETED.
    run_promotion_sweep(cohort)


def outcome_rates(college_id, variant):
    """partner_outcome_rates (PRD 3.9). variant is "census" (COMPLETED cohorts
    only) or "rolling" (cohorts in any status). Only ever_matriculated scholars
    enter any set. Returns (retention_bps, graduation_bps), each None when its
    denominator is empty."""
    scholars = []
    for s in store.scholars.values():
        if not s["ever_matriculated"]:
            continue
        cohort = store.cohorts.get(s["cohort_id"])
        if cohort is None or cohort["partner_college_id"] != college_id:
            continue
        if variant == "census" and cohort["status"] != "COMPLETED":
            continue
        scholars.append(s)
    if scholars:
        retained = sum(
            1 for s in scholars if s["enrollment_status"] in ("RETAINED", "GRADUATED")
        )
        retention = rhu(BPS_DENOMINATOR * retained, len(scholars))
    else:
        retention = None
    grad_set = [s for s in scholars if s["enrollment_status"] in TERMINAL_ENROLLMENT]
    if grad_set:
        graduated = sum(1 for s in grad_set if s["enrollment_status"] == "GRADUATED")
        graduation = rhu(BPS_DENOMINATOR * graduated, len(grad_set))
    else:
        graduation = None
    return retention, graduation


def derive_college_standing(college_id):
    """partner_standing_derivation (PRD 3.9): runs right after a cohort of this
    college completes. null census retention never changes standing."""
    college = store.colleges.get(college_id)
    if college is None:
        return
    retention, _grad = outcome_rates(college_id, "census")
    if retention is None:
        return
    if college["status"] == "ACTIVE" and retention < PROBATION_RETENTION_FLOOR_BPS:
        college["status"] = "PROBATION"
        touch(college)
    elif college["status"] == "PROBATION" and retention >= RECOVERY_RETENTION_BPS:
        college["status"] = "ACTIVE"
        touch(college)


def check_cohort_completion(cohort):
    """Cohort completion check (PRD 3.7): when every scholar of a MATRICULATED
    cohort is in a terminal enrollment state, the cohort completes, its
    agreement is fulfilled, and college standing is re-derived."""
    if cohort["status"] != "MATRICULATED":
        return
    scholars = [s for s in store.scholars.values() if s["cohort_id"] == cohort["id"]]
    if not scholars:
        return
    if not all(s["enrollment_status"] in TERMINAL_ENROLLMENT for s in scholars):
        return
    cohort["status"] = "COMPLETED"
    touch(cohort)
    agreement = store.agreements.get(cohort["agreement_id"])
    if agreement is not None and agreement["status"] == "ACTIVE":
        agreement["status"] = "FULFILLED"
        touch(agreement)
    derive_college_standing(cohort["partner_college_id"])
