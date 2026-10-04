"""POST /_batch/run-monthly-cycle — the five pinned phases (PRD §2.10, §3.7):

  1. January COLA for ENTITLED claims entitled strictly before this January;
  2. auto-resume of SUSPENDED claims whose age_months at run_month >= 840;
  3. payment generation (family-maximum re-evaluation per covered record,
     then one payment per ENTITLED claim with entitlement_month <= run_month,
     withholding waterfall, underpayment-credit drain);
  4. correction sweep: PENDING_REVIEW / EVIDENCE_REQUESTED / DENIED past the
     statute deadline (vs the logical clock date) -> EXPIRED;
  5. auto begin-recovery (FULL) for NOTIFIED cases whose 30-day waiver
     window lapsed before run_month — they withhold from the NEXT cycle.

Idempotent: a re-run of an already-run month creates nothing and reports
already_run=true with every count at zero.
"""

from fractions import Fraction

import calc
import timeutil as tu
from benefits import reevaluate_family_maximum, resume_claim
from db import store, stamp_common_new, touch, created_key


def _withhold_proportional(claim, active, capacity):
    """PROPORTIONAL: split capacity pro-rata to remaining balances, dime_floor
    per case first, then residual dimes one at a time in created_at ASC order
    respecting each case's remaining balance."""
    total_remaining = sum(o["amount_cents"] - o["recovered_cents"] for o in active)
    withhold = {}
    for o in active:
        remaining = o["amount_cents"] - o["recovered_cents"]
        share = calc.dime_floor(Fraction(capacity * remaining, total_remaining))
        withhold[o["id"]] = min(remaining, share)
    residual = capacity - sum(withhold.values())
    while residual >= 10:
        progressed = False
        for o in active:
            if residual < 10:
                break
            gap = (o["amount_cents"] - o["recovered_cents"]) - withhold[o["id"]]
            if gap >= 10:
                withhold[o["id"]] += 10
                residual -= 10
                progressed = True
        if not progressed:
            break
    return withhold


def _withhold_chronological(claim, active, capacity):
    """FULL / PARTIAL: oldest debt first; FULL takes min(remaining, capacity
    left), PARTIAL additionally caps at the case's elected monthly rate."""
    withhold = {}
    capacity_left = capacity
    for o in active:
        remaining = o["amount_cents"] - o["recovered_cents"]
        if claim["recovery_mode"] == "PARTIAL":
            rate = o.get("monthly_rate_cents") or claim.get("partial_rate_cents") or 0
            w = min(rate, remaining, capacity_left)
        else:  # FULL
            w = min(remaining, capacity_left)
        w = max(0, w)
        withhold[o["id"]] = w
        capacity_left -= w
    return withhold


def _generate_payment(claim, run_month_str):
    gross = claim["monthly_benefit_cents"]
    active = [
        o
        for o in store.overpayments.values()
        if o["claim_id"] == claim["id"] and o["status"] == "RECOVERY_ACTIVE"
    ]
    active.sort(key=created_key)
    if active and claim["recovery_mode"] == "PROPORTIONAL":
        withhold = _withhold_proportional(claim, active, gross)
    else:
        withhold = _withhold_chronological(claim, active, gross)
    withheld_total = sum(withhold.values())
    recovered_now = 0
    for o in active:
        w = withhold[o["id"]]
        if w <= 0:
            continue
        o["recovered_cents"] += w
        if o["recovered_cents"] >= o["amount_cents"]:
            o["recovered_cents"] = o["amount_cents"]
            o["status"] = "RECOVERED"
            recovered_now += 1
        touch(o)
    credit = claim["underpayment_credit_cents"]
    if credit:
        claim["underpayment_credit_cents"] = 0
        touch(claim)
    net = gross - withheld_total + credit
    status = "WITHHELD_FULL" if (net == 0 and withheld_total > 0) else "PAID"
    payment = stamp_common_new(
        {
            "claim_id": claim["id"],
            "month": run_month_str,
            "gross_cents": gross,
            "withheld_cents": withheld_total,
            "underpayment_credit_cents": credit,
            "net_paid_cents": net,
            "paid_to": "REPRESENTATIVE_PAYEE" if claim["has_active_payee"] else "BENEFICIARY",
            "status": status,
        }
    )
    store.payments[payment["id"]] = payment
    return recovered_now


def run_monthly_cycle(run_month):
    """run_month is a (year, month) tuple. Returns the run-report dict."""
    run_month_str = tu.ym_str(run_month)
    if run_month_str in store.ran_months:
        return {
            "run_month": run_month_str,
            "payments_created": 0,
            "corrections_expired": 0,
            "claims_auto_resumed": 0,
            "overpayments_recovered": 0,
            "cola_applied": 0,
            "already_run": True,
        }

    cola_applied = 0
    claims_auto_resumed = 0
    payments_created = 0
    corrections_expired = 0
    overpayments_recovered = 0

    # Phase 1 — January COLA.
    if run_month[1] == 1:
        entitled = [c for c in store.claims.values() if c["status"] == "ENTITLED"]
        entitled.sort(key=created_key)
        for c in entitled:
            if tu.parse_month_str(c["entitlement_month"]) < run_month:
                c["monthly_benefit_cents"] = calc.cola_adjusted_cents(c["monthly_benefit_cents"])
                touch(c)
                cola_applied += 1

    # Phase 2 — auto-resume at age 70 (840 months).
    suspended = [c for c in store.claims.values() if c["status"] == "SUSPENDED"]
    suspended.sort(key=created_key)
    for c in suspended:
        w = store.workers[c["worker_id"]]
        if tu.age_months_at(w["birth_year"], w["birth_month"], run_month) >= calc.MAX_DRC_AGE_MONTHS:
            resume_claim(c, run_month)
            claims_auto_resumed += 1

    # Phase 3 — payment generation. Family maximum is re-evaluated per
    # covered record first, then payments are cut in claim created_at order.
    covered_ids = set()
    for c in store.claims.values():
        if c["status"] == "ENTITLED" and c["claim_type"] in ("SPOUSAL", "DIVORCED_SPOUSAL"):
            rel = store.relationships.get(c["relationship_id"]) if c["relationship_id"] else None
            if rel:
                covered_ids.add(rel["worker_id"])
    for cid in sorted(covered_ids):
        reevaluate_family_maximum(cid, bump_versions=True)

    entitled = [
        c
        for c in store.claims.values()
        if c["status"] == "ENTITLED" and tu.parse_month_str(c["entitlement_month"]) <= run_month
    ]
    entitled.sort(key=created_key)
    for c in entitled:
        overpayments_recovered += _generate_payment(c, run_month_str)
        payments_created += 1

    # Phase 4 — correction sweep against the logical clock date.
    clock_date = store.clock_date()
    pending = [
        r
        for r in store.corrections.values()
        if r["status"] in ("PENDING_REVIEW", "EVIDENCE_REQUESTED", "DENIED")
    ]
    pending.sort(key=created_key)
    for r in pending:
        if tu.parse_date_str(r["statute_deadline"]) < clock_date:
            r["status"] = "EXPIRED"
            touch(r)
            corrections_expired += 1

    # Phase 5 — auto begin-recovery in FULL mode once the 30-day waiver
    # window lapsed before this run month; withholding starts NEXT cycle.
    run_first = tu.month_first_day(run_month)
    notified = [o for o in store.overpayments.values() if o["status"] == "NOTIFIED"]
    notified.sort(key=created_key)
    for o in notified:
        created_date = tu.parse_iso_to_date(o["created_at"])
        if tu.plus_days(created_date, 30) < run_first:
            o["status"] = "RECOVERY_ACTIVE"
            touch(o)
            claim = store.claims.get(o["claim_id"])
            if claim and claim["recovery_mode"] != "FULL":
                claim["recovery_mode"] = "FULL"
                touch(claim)

    store.ran_months.add(run_month_str)
    return {
        "run_month": run_month_str,
        "payments_created": payments_created,
        "corrections_expired": corrections_expired,
        "claims_auto_resumed": claims_auto_resumed,
        "overpayments_recovered": overpayments_recovered,
        "cola_applied": cola_applied,
        "already_run": False,
    }
