"""Business services: cohort recompute, bind, claim payment, giveback."""
from datetime import timedelta
from decimal import Decimal

from store import db, now, new_id, rhu, dec
from errors import (
    err_cohort_not_open, err_fee_config_not_found, err_invalid_request,
)


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 0) + 1


def policies_in_cohort(cohort_id):
    return [p for p in db.policies.values() if p["cohort_id"] == cohort_id]


def claims_in_cohort(cohort_id):
    pol_ids = {p["id"] for p in policies_in_cohort(cohort_id)}
    return [c for c in db.claims.values() if c["policy_id"] in pol_ids]


def cohort_treaty(cohort_id):
    tid = db.cohort_treaty.get(cohort_id)
    if not tid:
        return None
    t = db.treaties.get(tid)
    if t and t["status"] == "ACTIVE":
        return t
    return None


def recompute_cohort(cohort):
    """Recompute cohort aggregates from policy ledgers and claims."""
    policies = policies_in_cohort(cohort["id"])
    pol_ids = {p["id"] for p in policies}
    pool = 0
    fee = 0
    ceded = 0
    for e in db.ledger.values():
        if e["policy_id"] in pol_ids:
            if e["kind"] == "PREMIUM_CHARGE":
                pool += e["amount_cents"]
            elif e["kind"] == "FEE_RETAINED":
                fee += e["amount_cents"]
            elif e["kind"] == "REINSURANCE_CEDED":
                ceded += e["amount_cents"]
    cohort["premium_pool_cents"] = pool
    cohort["fee_retained_cents"] = fee
    cohort["reinsurance_ceded_cents"] = ceded
    cohort["claims_pot_cents"] = pool - fee - ceded

    retained_actual = 0
    reserved_extra = 0
    for c in claims_in_cohort(cohort["id"]):
        if c["status"] == "PAID":
            retained_actual += max(0, (c["payout_cents"] or 0) - c["reinsurance_share_cents"])
        elif c["status"] == "ESCALATED":
            reserved_extra += max(0, (c["reserve_cents"] or 0) - c["reinsurance_share_cents"])
    cohort["retained_claims_actual_cents"] = retained_actual
    cohort["retained_claims_reserved_cents"] = retained_actual + reserved_extra
    cohort["giveback_actual_cents"] = max(0, cohort["claims_pot_cents"] - retained_actual)
    cohort["giveback_projected_cents"] = max(
        0, cohort["claims_pot_cents"] - cohort["retained_claims_reserved_cents"]
    )


def find_open_cohort_for_year(year):
    for c in db.cohorts.values():
        if c["cohort_year"] == year and c["status"] == "OPEN":
            return c
    return None


def find_active_fee_config(state_code):
    for fc in db.fee_configs.values():
        if fc["state_code"] == state_code and fc["status"] == "ACTIVE":
            return fc
    return None


def append_ledger(policy_id, kind, amount_cents, claim_id=None):
    eid = new_id()
    entry = {
        "id": eid,
        "policy_id": policy_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "claim_id": claim_id,
        "created_at": now(),
    }
    db.ledger[eid] = entry
    return entry


def bind_policy(quote, application_signal_count):
    """Create a Policy from a quote. Raises cohort/fee errors if not resolvable."""
    policyholder = db.policyholders[quote["policyholder_id"]]
    bind_year = now().year
    cohort = find_open_cohort_for_year(bind_year)
    if not cohort:
        raise err_cohort_not_open()
    fee_config = find_active_fee_config(quote["state_code"])
    if not fee_config:
        raise err_fee_config_not_found()
    pid = new_id()
    ts = now()
    policy = {
        "id": pid,
        "policyholder_id": policyholder["id"],
        "quote_id": quote["id"],
        "cohort_id": cohort["id"],
        "fee_config_id": fee_config["id"],
        "annual_premium_cents": quote["premium_cents"],
        "premium_paid_cents": 0,
        "premium_outstanding_cents": quote["premium_cents"],
        "fraud_flag": application_signal_count >= 1,
        "cause_id": None,
        "cause_election_version": 0,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.policies[pid] = policy
    quote["status"] = "BOUND"
    touch(quote)
    return policy


def pay_claim(claim, payout_cents):
    """Execute payment for a claim: payment row, ledger entry, cohort recompute."""
    policy = db.policies[claim["policy_id"]]
    cohort = db.cohorts[policy["cohort_id"]]
    treaty = cohort_treaty(cohort["id"])
    share = 0
    if treaty:
        share = rhu(dec(payout_cents) * dec(treaty["quota_share_pct"]))
    claim["payout_cents"] = payout_cents
    claim["reserve_cents"] = None
    claim["reinsurance_share_cents"] = share
    claim["status"] = "PAID"
    pmid = new_id()
    payment = {
        "id": pmid,
        "claim_id": claim["id"],
        "amount_cents": payout_cents,
        "reinsurance_share_cents": share,
        "fee_cents": 0,
        "status": "SETTLED",
        "created_at": now(),
    }
    db.payments[pmid] = payment
    append_ledger(policy["id"], "CLAIM_PAYOUT", payout_cents, claim_id=claim["id"])
    touch(claim)
    recompute_cohort(cohort)
    touch(cohort)
    return payment


def giveback_allocations(cohort):
    """Largest-remainder apportionment. Returns (allocations {policy_id: cents}, cause_allocations list, total)."""
    eligible = [
        p for p in policies_in_cohort(cohort["id"]) if p["status"] != "LAPSED"
    ]
    pot = cohort["giveback_actual_cents"]
    total_weight = sum(p["premium_paid_cents"] for p in eligible)
    if total_weight == 0 or pot == 0:
        return {}, [], 0
    raws = []
    floor_sum = 0
    for p in eligible:
        raw = Decimal(pot) * Decimal(p["premium_paid_cents"]) / Decimal(total_weight)
        fl = int(raw)  # floor for non-negative
        frac = raw - Decimal(fl)
        floor_sum += fl
        raws.append((p, raw, fl, frac))
    remainder = pot - floor_sum
    # sort by frac DESC, created_at ASC (stable: insertion order breaks further ties)
    order = sorted(raws, key=lambda t: (-t[3], t[0]["created_at"]))
    alloc = {p["id"]: fl for (p, raw, fl, frac) in raws}
    i = 0
    while remainder > 0 and order:
        p = order[i % len(order)][0]
        alloc[p["id"]] += 1
        remainder -= 1
        i += 1
    by_cause = {}
    for p in eligible:
        cents = alloc.get(p["id"], 0)
        eff = p["cause_id"] if p["cause_id"] else cohort["cause_id"]
        by_cause[eff] = by_cause.get(eff, 0) + cents
    cause_allocations = [
        {"cause_id": cid, "amount_cents": amt}
        for cid, amt in sorted(by_cause.items(), key=lambda kv: kv[0])
    ]
    return alloc, cause_allocations, pot
