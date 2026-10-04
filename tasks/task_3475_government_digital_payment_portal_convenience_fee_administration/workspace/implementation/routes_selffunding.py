"""Self-funding period close (PRD section 3.8): pool reckoned from capture
dates, tiered absorbed billing, waterfall allocation, dual ACCRUAL/CASH
portal-cost recognition, zero-remainder conservation."""
from collections import defaultdict

from flask import Blueprint, request

import clock
import envelope
import fees
import serialize
import store
from auth import caller
from errors import raise_err
from validate import as_month, body, req_field

bp = Blueprint("selffunding", __name__)


def _period_of(dt):
    return dt.strftime("%Y-%m")


@bp.route("/portal/self-funding/close-period", methods=["POST"])
def close_period():
    caller({"TreasuryOfficer"})
    data = body()
    period = as_month(req_field(data, "period"), "period")
    # priority 5: a period may be closed only once
    for e in store.ledger:
        if e["period"] == period:
            raise_err(
                "ERR_PERIOD_ALREADY_CLOSED",
                409,
                "Period %s has already been closed" % period,
            )
    # pool inputs are reckoned from capture dates
    captured = [
        t
        for t in store.transactions.values()
        if t["captured_at"] is not None and _period_of(t["captured_at"]) == period
    ]
    fees_collected = sum(t["charged_fee_cents"] for t in captured)
    processing_costs = sum(t["final_fee_cents"] for t in captured)
    # tiered absorbed billing per agency (MARGINAL_CHRONOLOGICAL governs,
    # FLAT_RETROACTIVE is audit-only)
    by_agency = defaultdict(list)
    for t in captured:
        if t["fee_model"] == "ABSORBED":
            by_agency[t["agency_id"]].append(t)
    absorbed = 0
    absorbed_flat = 0
    for agency_id, txns in by_agency.items():
        txns.sort(key=lambda t: (t["captured_at"], t["created_seq"]))
        bands = [
            b
            for b in store.tiers.values()
            if b["agency_id"] == agency_id and b["effective_month"] == period
        ]
        # raises ERR_TIER_COVERAGE_GAP, aborting the whole close
        absorbed += fees.absorbed_invoice_marginal(txns, bands)
        absorbed_flat += fees.absorbed_invoice_flat(txns, bands)
    pool_available = fees_collected + absorbed - processing_costs
    # portal cost recognition: ACCRUAL recognizes the straight-line
    # amortization regardless of pool sufficiency; CASH takes only what the
    # pool can pay — shortfalls defer, they never vanish
    prior_accrual = sum(e["accrual_portal_recovery_cents"] for e in store.ledger)
    accrual_recovery = min(
        fees.MONTHLY_AMORTIZATION_CENTS,
        fees.TOTAL_PORTAL_COST_CENTS - prior_accrual,
    )
    cash_recovery = min(accrual_recovery, max(0, pool_available))
    # waterfall bucket 3: surplus swept to the state treasury
    surplus = max(0, pool_available - cash_recovery)
    prior_balance = store.ledger[-1]["pool_balance_after_cents"] if store.ledger else 0
    pool_balance_after = prior_balance + pool_available - cash_recovery - surplus
    prior_cash = sum(e["cash_portal_recovery_cents"] for e in store.ledger)
    rec = {
        "id": store.new_id(),
        "period": period,
        "fees_collected_cents": fees_collected,
        "absorbed_billed_cents": absorbed,
        "absorbed_billed_flat_cents": absorbed_flat,
        "processing_costs_cents": processing_costs,
        "accrual_portal_recovery_cents": accrual_recovery,
        "cash_portal_recovery_cents": cash_recovery,
        "surplus_remitted_cents": surplus,
        "pool_balance_after_cents": pool_balance_after,
        "portal_cost_remaining_accrual_cents": fees.TOTAL_PORTAL_COST_CENTS
        - (prior_accrual + accrual_recovery),
        "portal_cost_remaining_cash_cents": fees.TOTAL_PORTAL_COST_CENTS
        - (prior_cash + cash_recovery),
        "created_at": clock.now(),
        "created_seq": store.next_seq(),
    }
    store.ledger.append(rec)
    return envelope.obj(serialize.ledger_entry(rec), 201)


@bp.route("/portal/self-funding-ledger", methods=["GET"])
def list_ledger():
    caller({"PlatformAdmin", "TreasuryOfficer", "ComplianceAuditor"})
    period = request.args.get("period")
    items = list(store.ledger)
    if period is not None:
        items = [e for e in items if e["period"] == period]
    items.sort(key=lambda e: (e["created_at"], e["created_seq"]))
    return envelope.page([serialize.ledger_entry(e) for e in items], request.args)
