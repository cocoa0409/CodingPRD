"""Settlement batches and the dual-variant promotional subsidy / partner
chargeback reconciliation (PRD §3.7)."""
from flask import request

from core import auth, clock, computations, domain
from core.auth import enum_field, require_field
from core.errors import ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND, fail
from core.store import add, store, touch
from .common import listing, single

_VALID_SETTLEMENT_METHODS = ("FORWARD_LOOKING", "AS_CHARGED")
_VALID_RECONCILIATION_METHODS = ("PROJECTED", "AS_CHARGED")


def _not_found(what):
    return fail(ERR_RESOURCE_NOT_FOUND, f"{what} does not exist.")


def _inputs(agreement_id, period_start, period_end):
    """The shared input set: plans whose promo_start_at falls in
    [period_start, period_end) and whose transaction is POSTED (PRD §3.7)."""
    start = clock.parse(period_start)
    end = clock.parse(period_end)
    rows = []
    for plan in store.promo_plans.values():
        if plan.get("program_id") not in _programs_of(agreement_id):
            continue
        try:
            started = clock.parse(plan["promo_start_at"])
        except (KeyError, ValueError):
            continue
        if not (start <= started < end):
            continue
        transaction = store.transactions.get(plan.get("transaction_id"))
        if not transaction or transaction.get("transaction_status") != "POSTED":
            continue
        rows.append(plan)
    rows.sort(key=lambda p: (p.get("promo_start_at", ""), p.get("transaction_id", "")))
    return rows, start, end


def _programs_of(agreement_id):
    return {p["id"] for p in store.programs.values() if p.get("agreement_id") == agreement_id}


def _projected_pass(plans):
    return sum(computations.projected_interest(p["promo_principal_cents"], p["promo_term_months"])
               for p in plans)


def _days_accrued(plan, period_end):
    started = clock.parse(plan["promo_start_at"])
    elapsed = int((period_end - started).total_seconds() // 86400)
    return min(elapsed, plan["promo_term_months"] * 30)


def _accrued_pass(plans, period_end):
    total = 0
    per_plan = {}
    for plan in plans:
        days = _days_accrued(plan, period_end)
        gross = computations.accrued_interest(
            plan["promo_principal_cents"], plan["promo_term_months"], days)
        per_plan[plan["id"]] = (gross, days)
        total += gross
    return total, per_plan


def _reconcile(plans, agreement, method, gross_total, accrued_total, per_plan):
    rate = computations.dec(agreement.get("promo_subsidy_rate", 0.0))
    complement = computations.dec(1) - rate
    if method == "PROJECTED":
        retailer = 0
        issuer = 0
        for plan in plans:
            projected = computations.projected_interest(
                plan["promo_principal_cents"], plan["promo_term_months"])
            retailer += computations.money(computations.dec(projected) * rate)
            issuer += computations.money(computations.dec(projected) * complement)
        return retailer, issuer
    # AS_CHARGED: per-plan rounding on each party's share of accrued interest.
    retailer = 0
    issuer = 0
    for plan in plans:
        accrued, _days = per_plan[plan["id"]]
        retailer += computations.money(computations.dec(accrued) * rate)
        issuer += computations.money(computations.dec(accrued) * complement)
    return retailer, issuer


def register(app):

    @app.post("/servicing/settlement-batches")
    def create_settlement_batch():
        auth.require_role("ProgramAdmin")
        payload = auth.body()
        agreement_id = require_field(payload, "agreement_id", "string")
        period_start = require_field(payload, "period_start", "string")
        period_end = require_field(payload, "period_end", "string")
        agreement = store.agreements.get(agreement_id)
        if not agreement:
            raise _not_found("ProgramAgreement")
        method = enum_field(payload, "settlement_method", _VALID_SETTLEMENT_METHODS,
                            required=False, default="AS_CHARGED")
        reconciliation = enum_field(payload, "reconciliation_method",
                                    _VALID_RECONCILIATION_METHODS,
                                    required=False, default="PROJECTED")
        try:
            start = clock.parse(period_start)
            end = clock.parse(period_end)
        except ValueError:
            raise fail("ERR_INVALID_REQUEST", "period_start and period_end must be ISO 8601 instants.")

        plans, _start, end = _inputs(agreement_id, period_start, period_end)
        active_plans = [p for p in plans if p.get("plan_status") == "ACTIVE"]
        gross = _projected_pass(active_plans)
        net, per_plan = _accrued_pass(plans, end)
        batch = add("settlement_batches", {
            "agreement_id": agreement_id,
            "period_start": clock.fmt(start),
            "period_end": clock.fmt(end),
            "settlement_method": method,
            "reconciliation_method": reconciliation,
            "transaction_count": len(plans),
            "gross_subsidy_cents": gross,
            "net_subsidy_cents": net,
            "retailer_liability_cents": 0,
            "issuer_subsidy_cents": 0,
            "variance_cents": gross - net,
            "batch_status": "OPEN",
        })
        batch["_accrued"] = per_plan
        return single(batch, 201)

    @app.get("/servicing/settlement-batches")
    def list_settlement_batches():
        auth.require_role("ProgramAdmin", "Underwriter", "RetailPartnerAnalyst")
        return listing(list(store.settlement_batches.values()),
                       {"agreement_id": request.args.get("agreement_id")})

    @app.get("/servicing/settlement-batches/<batch_id>")
    def read_settlement_batch(batch_id):
        auth.require_role("ProgramAdmin", "Underwriter", "RetailPartnerAnalyst")
        batch = store.settlement_batches.get(batch_id)
        if not batch:
            raise _not_found("SettlementBatch")
        return single(batch)

    @app.post("/servicing/settlement-batches/<batch_id>/finalize")
    def finalize_settlement_batch(batch_id):
        auth.require_role("ProgramAdmin")
        batch = store.settlement_batches.get(batch_id)
        if not batch:
            raise _not_found("SettlementBatch")
        agreement = store.agreements.get(batch["agreement_id"])
        if not agreement:
            raise _not_found("ProgramAgreement")

        plans, _start, end = _inputs(batch["agreement_id"], batch["period_start"], batch["period_end"])

        # The batch's own state is evaluated first; the in-scope dispute hold
        # follows (PRD §2.11).
        if batch["batch_status"] != "OPEN":
            raise fail(ERR_INVALID_STATE, "Only an OPEN batch can finalize.")
        if _has_open_dispute(plans):
            raise fail("ERR_SETTLEMENT_DISPUTE_HOLD",
                       "An in-scope purchase still carries an OPEN or UNDER_REVIEW dispute.")

        active_plans = [p for p in plans if p.get("plan_status") == "ACTIVE"]
        gross = _projected_pass(active_plans)
        net, per_plan = _accrued_pass(plans, end)
        retailer, issuer = _reconcile(
            plans, agreement, batch["reconciliation_method"], gross, net, per_plan)

        batch["gross_subsidy_cents"] = gross
        batch["net_subsidy_cents"] = net
        batch["variance_cents"] = gross - net
        batch["retailer_liability_cents"] = retailer
        batch["issuer_subsidy_cents"] = issuer
        batch["transaction_count"] = len(plans)
        batch["batch_status"] = "SETTLED"
        batch.pop("_accrued", None)

        # Every in-scope plan moves to SETTLED with its as-charged figure
        # stamped; the plan leaves the ACTIVE exposure set, but its
        # subsidy_at_risk_cents is left untouched (PRD §3.7).
        for plan in plans:
            if plan.get("plan_status") == "ACTIVE":
                plan["net_subsidy_cents"] = per_plan[plan["id"]][0]
                plan["plan_status"] = "SETTLED"
                plan["updated_at"] = clock.now_iso()
        touch(batch)

        for program in domain.programs_of_agreement(batch["agreement_id"]):
            domain.refresh_program(program)
        # The settlement day bumps the agreement version once.
        agreement["version"] = agreement.get("version", 1) + 1
        agreement["updated_at"] = clock.now_iso()
        return single(batch)


def _has_open_dispute(plans):
    for plan in plans:
        for dispute in store.disputes.values():
            if (dispute.get("transaction_id") == plan.get("transaction_id")
                    and dispute.get("case_status") in ("OPEN", "UNDER_REVIEW")):
                return True
    return False