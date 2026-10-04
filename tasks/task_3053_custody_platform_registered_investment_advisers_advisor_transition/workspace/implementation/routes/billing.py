"""Advisory fee billing runs and household fee credits."""

from core import constants as C
from core.context import body, check_if_match, need
from core.errors import fail
from core.response import ok, paginate
from core.store import STORE, days_between, new_token, parse_dt
from domain import calc
from domain.cascade import hold_household, release_household
from domain.guards import firm_active_guard, invariant_guard, require_any_entitlement
from domain.model import create, serialize, touch
from domain.resolve import sorted_rows
from routes._base import load, load_firm


def register(api):

    @api.route("/ria/billing-runs", methods=["POST"], roles=["AdvisorOperationsLead"])
    def seed_billing_run():
        data = body()
        firm = load_firm(need(data, "firm_id"))
        firm_active_guard(firm)
        household = load("Household", need(data, "household_id"))
        if household.get("firm_id") != firm.get("id"):
            fail("ERR_REFERENCE_MISMATCH")

        accounts = STORE.find("HouseholdAccount", household_id=household.get("id"))
        require_any_entitlement(firm, ("BILLING",))
        if household.get("household_status") != "ACTIVE":
            fail("ERR_HOUSEHOLD_BILLING_HELD")
        # Priority 8 tests a target HouseholdAccount's lifecycle state.  A
        # household holding no account at all has no such row, so it falls
        # through to the fiscal floors and reports ERR_FEE_BASIS_ZERO, which
        # PRD §3.6 states explicitly for a zero-included-account household.
        if accounts and not any(a.get("account_status") in ("OPEN", "FROZEN") for a in accounts):
            fail("ERR_ACCOUNT_NOT_ELIGIBLE")

        start = parse_dt(need(data, "period_start_date"))
        end = parse_dt(need(data, "period_end_date"))
        period_days = days_between(end, start)
        if period_days <= 0 or period_days > C.MAX_BILLING_PERIOD_DAYS:
            fail("ERR_BILLING_PERIOD_INVALID")
        invariant_guard(firm)
        calc.recompute_household_basis(household)
        basis = int(household.get("household_fee_basis_cents") or 0)
        if basis <= 0:
            fail("ERR_FEE_BASIS_ZERO")
        if basis < C.FEE_BASIS_MINIMUM_CENTS:
            fail("ERR_FEE_BASIS_BELOW_MINIMUM")

        variant, annual = calc.household_fee_variant(household)
        household["household_annual_fee_cents"] = annual
        gross = calc.prorate_gross_fee(annual, period_days)

        run = create("FeeBillingRun",
                     firm_id=firm.get("id"),
                     household_id=household.get("id"),
                     period_start_date=data.get("period_start_date"),
                     period_end_date=data.get("period_end_date"),
                     period_days=period_days,
                     billing_run_status="SETTLED",
                     fee_basis_snapshot_cents=basis,
                     fee_variant_used=data.get("fee_variant_used") or variant,
                     gross_fee_cents=gross,
                     credit_applied_cents=0,
                     net_fee_cents=gross,
                     stated_invoice_cents=data.get("stated_invoice_cents"),
                     settlement_evidence_hash=new_token("st_"))
        applied, consumption = calc.select_credits(household, gross)
        calc.apply_credit_consumption(consumption, run)
        run["credit_applied_cents"] = applied
        run["net_fee_cents"] = gross - applied
        touch(run)
        household["billing_period_number"] = int(household.get("billing_period_number") or 0) + 1
        touch(household)
        for account in accounts:
            if account.get("account_status") in ("OPEN", "FROZEN") and account.get("billable"):
                account["billed_period_count"] = int(account.get("billed_period_count") or 0) + 1
                touch(account)
        return ok(serialize(run), 201)

    @api.route("/ria/billing-runs/<run_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "ComplianceReviewer", "PlatformAdmin"])
    def read_billing_run(run_id):
        return ok(serialize(load("FeeBillingRun", run_id)), 200)

    @api.route("/ria/households/<household_id>/billing-runs", methods=["GET"],
               roles=["AdvisorOperationsLead", "ComplianceReviewer", "PlatformAdmin"])
    def list_household_runs(household_id):
        from routes._base import params
        load("Household", household_id)
        p = params()
        rows = sorted_rows("FeeBillingRun", {"household_id": household_id,
                                             "billing_run_status": p.get("billing_run_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/firms/<firm_id>/billing-runs", methods=["GET"],
               roles=["AdvisorOperationsLead", "ComplianceReviewer", "PlatformAdmin"])
    def list_firm_runs(firm_id):
        from routes._base import params
        load_firm(firm_id)
        p = params()
        rows = sorted_rows("FeeBillingRun", {"firm_id": firm_id,
                                             "billing_run_status": p.get("billing_run_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/billing-runs/<run_id>/remit-invoice", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def remit_invoice(run_id):
        run = load("FeeBillingRun", run_id)
        data = body()
        check_if_match(run, data)
        firm = load_firm(run.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(run, ("SETTLED",), ("VOIDED",))
        stated = int(need(data, "stated_invoice_cents"))
        reinvest = _recompute(run)
        run["stated_invoice_cents"] = stated
        if stated != reinvest["net_fee_cents"]:
            run["billing_run_status"] = "INVOICE_MISMATCH"
            run["net_fee_cents"] = reinvest["net_fee_cents"]
            run["credit_applied_cents"] = reinvest["credit_applied_cents"]
            run["gross_fee_cents"] = reinvest["gross_fee_cents"]
            touch(run)
            hold_household(STORE.get("Household", run.get("household_id")))
            return ok(serialize(run), 200)
        run["net_fee_cents"] = reinvest["net_fee_cents"]
        run["credit_applied_cents"] = reinvest["credit_applied_cents"]
        run["gross_fee_cents"] = reinvest["gross_fee_cents"]
        touch(run)
        return ok(serialize(run), 200)

    @api.route("/ria/billing-runs/<run_id>/reopen", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def reopen_run(run_id):
        run = load("FeeBillingRun", run_id)
        data = body()
        check_if_match(run, data)
        firm = load_firm(run.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(run, ("INVOICE_MISMATCH",), ("VOIDED",))
        calc.release_credits_for_run(run)
        run["billing_run_status"] = "REOPENED"
        run["credit_applied_cents"] = 0
        run["net_fee_cents"] = run.get("gross_fee_cents")
        touch(run)
        release_household(STORE.get("Household", run.get("household_id")))
        return ok(serialize(run), 200)

    @api.route("/ria/billing-runs/<run_id>/settle", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def settle_run(run_id):
        run = load("FeeBillingRun", run_id)
        data = body()
        check_if_match(run, data)
        firm = load_firm(run.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(run, ("REOPENED",), ("VOIDED",))
        household = STORE.get("Household", run.get("household_id"))
        calc.recompute_household_basis(household)
        variant, annual = calc.household_fee_variant(household)
        household["household_annual_fee_cents"] = annual
        gross = calc.prorate_gross_fee(annual, int(run.get("period_days") or 0))
        applied, consumption = calc.select_credits(household, gross)
        net = gross - applied
        if run.get("stated_invoice_cents") is not None and int(run["stated_invoice_cents"]) != net:
            fail("ERR_FEE_INVOICE_MISMATCH")
        calc.apply_credit_consumption(consumption, run)
        run["gross_fee_cents"] = gross
        run["credit_applied_cents"] = applied
        run["net_fee_cents"] = net
        run["fee_basis_snapshot_cents"] = int(household.get("household_fee_basis_cents") or 0)
        run["billing_run_status"] = "SETTLED"
        run["settlement_evidence_hash"] = new_token("st_")
        touch(run)
        return ok(serialize(run), 200)

    @api.route("/ria/billing-runs/<run_id>/void", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def void_run(run_id):
        run = load("FeeBillingRun", run_id)
        data = body()
        check_if_match(run, data)
        firm = load_firm(run.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(run, ("SETTLED",), ("VOIDED",))
        calc.release_credits_for_run(run)
        run["billing_run_status"] = "VOIDED"
        run["credit_applied_cents"] = 0
        run["net_fee_cents"] = run.get("gross_fee_cents")
        touch(run)
        return ok(serialize(run), 200)

    @api.route("/ria/billing-runs/<run_id>/fee-credits", methods=["GET"],
               roles=["ComplianceReviewer", "AdvisorOperationsLead", "PlatformAdmin"])
    def list_run_credits(run_id):
        load("FeeBillingRun", run_id)
        rows = sorted_rows("FeeCredit", {"applied_to_billing_run_id": run_id})
        return ok([serialize(r) for r in rows], 200)

    # --------------------------------------------------------- fee credits

    @api.route("/ria/households/<household_id>/fee-credits", methods=["POST"],
               roles=["CustodyOperationsOfficer"])
    def issue_credit(household_id):
        household = load("Household", household_id)
        firm_active_guard(load_firm(household.get("firm_id")))
        data = body()
        amount = int(need(data, "credit_cents"))
        outstanding = sum(int(c.get("credit_cents") or 0)
                          for c in STORE.find("FeeCredit", household_id=household_id)
                          if c.get("credit_status") in ("AVAILABLE", "PARTIALLY_APPLIED"))
        if outstanding + amount > int(household.get("household_annual_fee_cents") or 0):
            fail("ERR_CREDIT_EXCEEDS_FEE")
        row = create("FeeCredit",
                     household_id=household_id,
                     credit_cents=amount,
                     earned_on_date=STORE.clock.now(),
                     credit_status="AVAILABLE",
                     applied_to_billing_run_id=None)
        return ok(serialize(row), 201)

    @api.route("/ria/households/<household_id>/fee-credits", methods=["GET"],
               roles=["AdvisorOperationsLead", "ComplianceReviewer", "PlatformAdmin"])
    def list_credits(household_id):
        from routes._base import params
        load("Household", household_id)
        p = params()
        rows = sorted_rows("FeeCredit", {"household_id": household_id,
                                         "credit_status": p.get("credit_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)


def _recompute(run):
    household = STORE.get("Household", run.get("household_id"))
    calc.recompute_household_basis(household)
    variant, annual = calc.household_fee_variant(household)
    household["household_annual_fee_cents"] = annual
    gross = calc.prorate_gross_fee(annual, int(run.get("period_days") or 0))
    applied, _consumption = calc.select_credits(household, gross)
    return {"gross_fee_cents": gross, "credit_applied_cents": applied, "net_fee_cents": gross - applied}


def _state_or_terminal(row, from_states, terminal_states):
    from core.context import STATE_FIELDS
    state = row.get(STATE_FIELDS.get(row.get("_entity")))
    if terminal_states and state in terminal_states:
        fail("ERR_ALREADY_TERMINAL")
    allowed = from_states if isinstance(from_states, (tuple, list, set)) else (from_states,)
    if state not in allowed:
        fail("ERR_INVALID_STATE")