"""Benefit pipeline: spousal/survivor computation, family-maximum waterfall,
recomputation with retro-delta settlement, and suspension resume.

The pinned spousal evaluation order (PRD §3.5): (1) reduced spousal amount
from the covered worker's PIA and the spouse's age; (2) dual-entitlement
offset of the claimant's own RETIREMENT PIA; (3) family-maximum allocation;
(4) GPO subtraction floored at zero. The family maximum rounds each
auxiliary share FIRST (dime_floor per claim), then distributes the stranded
residual one dime at a time in created_at ASC order, one dime per claim per
pass. A sum-then-round order is non-conformant.
"""

from fractions import Fraction

import calc
import timeutil as tu
from db import store, stamp_new, stamp_common_new, touch, created_key

AUX_TYPES = ("SPOUSAL", "DIVORCED_SPOUSAL")


def covered_retirement_claim(store_, worker_id):
    """The worker's RETIREMENT claim in ENTITLED or SUSPENDED, if any."""
    cands = [
        c
        for c in store_.claims.values()
        if c["worker_id"] == worker_id
        and c["claim_type"] == "RETIREMENT"
        and c["status"] in ("ENTITLED", "SUSPENDED")
    ]
    cands.sort(key=created_key)
    return cands[0] if cands else None


def covered_worker_id_of(claim):
    rel = store.relationships.get(claim["relationship_id"]) if claim["relationship_id"] else None
    return rel["worker_id"] if rel else None


def worker_pia_context(store_, worker):
    """(aime, pia) computed from the worker's earnings record right now."""
    aime = calc.compute_aime_cents(store_, worker)
    return aime, calc.compute_pia_cents(store_, worker, aime)


def covered_pia_for_aux(store_, covered_worker_id):
    """Covered worker's current PIA: from their ENTITLED/SUSPENDED RETIREMENT
    claim, else the hypothetical PIA computed from their earnings record
    (DIVORCED_SPOUSAL independent-entitlement path)."""
    rc = covered_retirement_claim(store_, covered_worker_id)
    if rc:
        return rc["pia_cents"], rc["aime_cents"]
    aime, pia = worker_pia_context(store_, store.workers[covered_worker_id])
    return pia, aime


def spousal_excess_cents(claim, worker_pia_cents):
    """Steps (1) and (2): reduced spousal amount minus the claimant's own
    RETIREMENT PIA, floored at zero."""
    claimant = store.workers[claim["worker_id"]]
    base = calc.spousal_base_cents(worker_pia_cents)
    reduced = calc.spousal_reduced_cents(base, claimant["fra_months"], claim["claiming_age_months"])
    own = covered_retirement_claim(store, claimant["id"])
    own_pia = own["pia_cents"] if own else 0
    return max(0, reduced - own_pia)


def reevaluate_family_maximum(covered_worker_id, bump_versions, skip_touch_id=None):
    """Step (3)+(4) for every ENTITLED SPOUSAL/DIVORCED_SPOUSAL claim riding
    on one covered record. Recomputes each auxiliary's pre-reduction excess,
    allocates the family-maximum pool (per-claim dime_floor first, residual
    dimes in created_at ASC order), then subtracts GPO floored at zero. The
    covered worker's own benefit is NEVER reduced. skip_touch_id excludes one
    claim from the version bump (its caller owns that increment)."""
    aux = [
        c
        for c in store.claims.values()
        if c["claim_type"] in AUX_TYPES
        and c["status"] == "ENTITLED"
        and covered_worker_id_of(c) == covered_worker_id
    ]
    if not aux:
        return
    aux.sort(key=created_key)
    covered_worker = store.workers[covered_worker_id]
    rc = covered_retirement_claim(store, covered_worker_id)
    if rc:
        worker_pia = rc["pia_cents"]
        own_benefit = rc["monthly_benefit_cents"]
    else:
        _, worker_pia = worker_pia_context(store, covered_worker)
        own_benefit = 0
    pre = {c["id"]: spousal_excess_cents(c, worker_pia) for c in aux}
    fmax = calc.family_maximum_cents(worker_pia, covered_worker["eligibility_year"])
    sum_aux = sum(pre.values())
    if own_benefit + sum_aux <= fmax:
        alloc = dict(pre)
    else:
        pool = max(0, fmax - own_benefit)
        alloc = {}
        if sum_aux > 0:
            for c in aux:
                alloc[c["id"]] = calc.dime_floor(Fraction(pool * pre[c["id"]], sum_aux))
            residual = pool - sum(alloc.values())
            # one dime at a time, created_at ASC, one dime per claim per pass
            while residual >= 10:
                progressed = False
                for c in aux:
                    if residual < 10:
                        break
                    alloc[c["id"]] += 10
                    residual -= 10
                    progressed = True
                if not progressed:
                    break
        else:
            for c in aux:
                alloc[c["id"]] = 0
    for c in aux:
        claimant = store.workers[c["worker_id"]]
        new_mb = max(0, alloc[c["id"]] - calc.gpo_offset_cents(claimant))
        if c["monthly_benefit_cents"] != new_mb:
            c["monthly_benefit_cents"] = new_mb
            if bump_versions and c["id"] != skip_touch_id:
                touch(c)


def _settle_retro_delta(claim, old_mb, new_mb, trigger, old_pia, new_pia):
    """recomputation_delta (PRD §3.5): signed delta = (new - old) monthly x
    count of PAID/WITHHELD_FULL payments; positive credits the claim,
    negative auto-opens a system OverpaymentCase."""
    paid = [
        p
        for p in store.payments.values()
        if p["claim_id"] == claim["id"] and p["status"] in ("PAID", "WITHHELD_FULL")
    ]
    delta = (new_mb - old_mb) * len(paid)
    if delta > 0:
        claim["underpayment_credit_cents"] += delta
        resolution = "UNDERPAYMENT_CREDIT"
    elif delta < 0:
        months = sorted(p["month"] for p in paid)
        case = stamp_common_new(
            {
                "claim_id": claim["id"],
                "amount_cents": -delta,
                "period_start_month": months[0],
                "period_end_month": months[-1],
                "reason": "RECOMPUTATION",
                "status": "NOTIFIED",
                "created_by": "system",
                "recovered_cents": 0,
                "waiver_grounds": None,
                "waiver_decided_by": None,
                "monthly_rate_cents": None,
            }
        )
        store.overpayments[case["id"]] = case
        resolution = "OVERPAYMENT_CREATED"
    else:
        resolution = "NONE"
    event = stamp_new(
        {
            "claim_id": claim["id"],
            "trigger": trigger,
            "old_pia_cents": old_pia,
            "new_pia_cents": new_pia,
            "old_monthly_benefit_cents": old_mb,
            "new_monthly_benefit_cents": new_mb,
            "retro_delta_cents": delta,
            "resolution": resolution,
        }
    )
    store.recomputations[event["id"]] = event


def recompute_claim(claim, trigger):
    """Recompute pia_cents / monthly_benefit_cents of an ENTITLED or
    SUSPENDED claim and append a RecomputationEvent. The caller owns the
    claim's version increment (exactly one per logical mutation)."""
    old_pia = claim["pia_cents"] or 0
    old_mb = claim["monthly_benefit_cents"] or 0
    worker = store.workers[claim["worker_id"]]
    ctype = claim["claim_type"]
    if ctype == "RETIREMENT":
        aime = calc.compute_aime_cents(store, worker)
        pia = calc.compute_pia_cents(store, worker, aime)
        claim["aime_cents"] = aime
        claim["pia_cents"] = pia
        claim["monthly_benefit_cents"] = calc.age_adjusted_monthly_cents(
            pia, worker["fra_months"], claim["claiming_age_months"], claim["drc_months"]
        )
    elif ctype in AUX_TYPES:
        covered_id = covered_worker_id_of(claim)
        worker_pia, aime = covered_pia_for_aux(store, covered_id)
        claim["aime_cents"] = aime
        claim["pia_cents"] = worker_pia
        if claim["status"] == "ENTITLED":
            reevaluate_family_maximum(covered_id, bump_versions=True, skip_touch_id=claim["id"])
        else:
            # SUSPENDED auxiliaries sit outside the ENTITLED family pool;
            # their stored benefit is excess-after-GPO on its own.
            claimant = store.workers[claim["worker_id"]]
            excess = spousal_excess_cents(claim, worker_pia)
            claim["monthly_benefit_cents"] = max(0, excess - calc.gpo_offset_cents(claimant))
    else:  # SURVIVOR
        covered_id = covered_worker_id_of(claim)
        covered = store.workers[covered_id]
        aime, worker_pia = worker_pia_context(store, covered)
        claim["aime_cents"] = aime
        claim["pia_cents"] = worker_pia
        amount = calc.survivor_benefit_cents(worker_pia, claim["claiming_age_months"])
        claim["monthly_benefit_cents"] = max(0, amount - calc.gpo_offset_cents(worker))
    _settle_retro_delta(claim, old_mb, claim["monthly_benefit_cents"], trigger, old_pia, claim["pia_cents"])


def resume_claim(claim, current_month):
    """SUSPENDED -> ENTITLED with delayed-retirement-credit accrual:
    drc_months := min(months suspended, max(0, 840 - age at suspension)).
    current_month is the logical clock month for a manual resume and the
    run_month for the batch auto-resume."""
    worker = store.workers[claim["worker_id"]]
    since = tu.parse_month_str(claim["suspended_since"])
    age_at_suspension = tu.age_months_at(worker["birth_year"], worker["birth_month"], since)
    months_suspended = max(0, tu.months_between_ym(since, current_month))
    claim["drc_months"] = min(months_suspended, max(0, calc.MAX_DRC_AGE_MONTHS - age_at_suspension))
    claim["status"] = "ENTITLED"
    claim["suspended_since"] = None
    recompute_claim(claim, "SUSPENSION_RESUME")
    touch(claim)
