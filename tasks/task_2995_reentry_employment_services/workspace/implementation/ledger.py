"""Grant ledger, deferral waterfall, support pricing and funder reporting.

PRD sections 2.9, 3.8 and 3.9.
"""

from decimal import Decimal

from domain import (
    ADMIN_FEE_RATE_T1, ADMIN_FEE_RATE_T2, ADMIN_FEE_RATE_T3,
    ADMIN_FEE_T1_MAX_CENTS, ADMIN_FEE_T2_MAX_CENTS, COVERAGE_RATES,
    RESTRICTED_FLOOR_RATE, apply, cents, dec, pct1, placements_of_grant,
    support_requests_of_grant,
)
from store import db, now_str, touch


# --------------------------------------------------------------------------
# the ledger — calculations.grant_ledger
# --------------------------------------------------------------------------

def restricted_floor_cents(grant):
    return cents(Decimal(int(grant["authorized_cents"])) * RESTRICTED_FLOOR_RATE)


def posture_for(available, floor):
    if available <= 0:
        return "EXHAUSTED"
    if available < floor:
        return "RESTRICTED"
    return "OPEN"


def apply_ledger(grant):
    """Recompute the four money columns, the posture and open_request_count."""
    requests = support_requests_of_grant(grant["id"])
    placements = placements_of_grant(grant["id"])
    committed = sum(r["total_charge_cents"] for r in requests
                    if r["status"] == "APPROVED")
    committed += sum(p["projected_subsidy_cents"] for p in placements
                     if p["employment_status"] == "ACTIVE")
    disbursed = sum(r["total_charge_cents"] for r in requests
                    if r["status"] == "DISBURSED")
    disbursed += sum(p["disbursed_subsidy_cents"] for p in placements
                     if p["employment_status"] == "SEPARATED")
    available = int(grant["authorized_cents"]) - committed - disbursed
    open_count = len([r for r in requests if r["status"] in
                      ("SUBMITTED", "INFO_REQUESTED", "DEFERRED")])
    changed = apply(grant, "committed_cents", committed)
    changed = apply(grant, "disbursed_cents", disbursed) or changed
    changed = apply(grant, "available_cents", available) or changed
    changed = apply(grant, "open_request_count", open_count) or changed
    changed = apply(grant, "funding_posture",
                    posture_for(available, restricted_floor_cents(grant))) or changed
    if changed:
        touch(grant)
    return changed


def deferred_queue(grant):
    """DEFERRED requests in waterfall order: deferred_at ASC, created_at ASC."""
    queue = [r for r in support_requests_of_grant(grant["id"])
             if r["status"] == "DEFERRED"]
    queue.sort(key=lambda r: (r["deferred_at"] or "", r["created_at"], r["_seq"]))
    return queue


def promote_head(grant):
    """Promote at most the head of the deferral queue, never skipping it."""
    queue = deferred_queue(grant)
    if not queue:
        return False
    head = queue[0]
    if head["total_charge_cents"] > grant["available_cents"]:
        return False
    head["status"] = "APPROVED"
    head["promoted_at"] = now_str()
    touch(head)
    return True


def recompute_grant(grant, allow_waterfall=True):
    """Reconcile the ledger; run the waterfall when available_cents rose."""
    if grant is None:
        return
    before = grant["available_cents"]
    apply_ledger(grant)
    if allow_waterfall and grant["available_cents"] > before:
        if promote_head(grant):
            apply_ledger(grant)


def recompute_grant_by_id(grant_id, allow_waterfall=True):
    if not grant_id:
        return
    recompute_grant(db.grants.get(grant_id), allow_waterfall=allow_waterfall)


# --------------------------------------------------------------------------
# support request pricing — calculations.support_request_award / _settlement
# --------------------------------------------------------------------------

def price_request(category, line_items):
    """Return (priced_lines, requested_cents, admin_fee_cents, total_charge)."""
    rate = COVERAGE_RATES[category]
    priced = []
    requested = 0
    for item in line_items:
        award = cents(Decimal(int(item["unit_cost_cents"]))
                      * Decimal(int(item["quantity"])) * rate)
        priced.append({
            "description": item["description"],
            "unit_cost_cents": int(item["unit_cost_cents"]),
            "quantity": int(item["quantity"]),
            "line_award_cents": award,
        })
        requested += award
    if requested <= ADMIN_FEE_T1_MAX_CENTS:
        fee_rate = ADMIN_FEE_RATE_T1
    elif requested <= ADMIN_FEE_T2_MAX_CENTS:
        fee_rate = ADMIN_FEE_RATE_T2
    else:
        fee_rate = ADMIN_FEE_RATE_T3
    admin_fee = cents(Decimal(requested) * fee_rate)
    return priced, requested, admin_fee, requested + admin_fee


def participant_charged_cents(grant_id, participant_id, exclude_request_id=None):
    """Running per-participant total against one grant, per PRD section 3.8."""
    counted = ("APPROVED", "DISBURSED", "DEFERRED", "SUBMITTED", "INFO_REQUESTED")
    total = 0
    for request in support_requests_of_grant(grant_id):
        if request["participant_id"] != participant_id:
            continue
        if request["status"] not in counted:
            continue
        if exclude_request_id is not None and request["id"] == exclude_request_id:
            continue
        total += request["total_charge_cents"]
    return total


# --------------------------------------------------------------------------
# funder outcome report — calculations.grant_outcome_report
# --------------------------------------------------------------------------

def outcome_report(grant, variant):
    started = [p for p in placements_of_grant(grant["id"])
               if p["employment_status"] in ("ACTIVE", "SEPARATED")]
    if variant == "EXIT_BASED":
        selected = []
        for placement in started:
            participant = db.participants.get(placement["participant_id"])
            if participant is not None and participant["stage"] == "EXITED":
                selected.append(placement)
    else:
        selected = started

    denominator = len(selected)
    retained = len([p for p in selected if p["retention_90_outcome"] == "RETAINED"])
    participant_ids = []
    for placement in selected:
        if placement["participant_id"] not in participant_ids:
            participant_ids.append(placement["participant_id"])
    participants_served = len(participant_ids)
    recidivism_ids = {p["participant_id"] for p in selected
                      if p["recidivism_event"] not in (None, "NONE")}

    if denominator == 0:
        retention_rate = None
    else:
        retention_rate = pct1(Decimal(100) * Decimal(retained) / Decimal(denominator))
    if participants_served == 0:
        recidivism_rate = None
    else:
        recidivism_rate = pct1(Decimal(100) * Decimal(len(recidivism_ids))
                               / Decimal(participants_served))
    if retention_rate is None:
        benchmark_met = False
    else:
        benchmark_met = dec(retention_rate) >= dec(grant["retention_benchmark_pct"])

    subsidy_disbursed = sum(p["disbursed_subsidy_cents"] for p in selected)
    support_disbursed = sum(r["total_charge_cents"]
                            for r in support_requests_of_grant(grant["id"])
                            if r["status"] == "DISBURSED")

    return {
        "grant_id": grant["id"],
        "variant": variant,
        "participants_served": participants_served,
        "denominator_placements": denominator,
        "retained_placements": retained,
        "retention_rate_pct": retention_rate,
        "recidivism_rate_pct": recidivism_rate,
        "benchmark_met": bool(benchmark_met),
        "subsidy_disbursed_cents": subsidy_disbursed,
        "support_disbursed_cents": support_disbursed,
    }


def ledger_view(grant):
    return {
        "grant_id": grant["id"],
        "authorized_cents": grant["authorized_cents"],
        "committed_cents": grant["committed_cents"],
        "disbursed_cents": grant["disbursed_cents"],
        "available_cents": grant["available_cents"],
        "restricted_floor_cents": restricted_floor_cents(grant),
        "funding_posture": grant["funding_posture"],
        "open_request_count": grant["open_request_count"],
        "deferred_request_count": len(deferred_queue(grant)),
    }
