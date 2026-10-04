"""Households and custody accounts: lifecycle, listing and relinking."""

from core import constants as C
from core.context import body, check_if_match, check_occ, need
from core.errors import fail
from core.response import ok, paginate
from core.store import STORE, parse_dt
from domain import calc
from domain.cascade import refresh_household, revoke_standing_instructions
from domain.guards import current_agreement, firm_active_guard
from domain.guards import require_any_entitlement
from domain.model import create, serialize, touch
from domain.resolve import sorted_rows
from routes._base import identity, load, load_firm


def register(api):

    # ------------------------------------------------------------ households

    @api.route("/ria/households", methods=["POST"], roles=["AdvisorOperationsLead"])
    def create_household():
        data = body()
        firm = load_firm(need(data, "firm_id"))
        firm_active_guard(firm)
        row = create("Household",
                     firm_id=firm.get("id"),
                     household_name=need(data, "household_name"),
                     household_status="ACTIVE",
                     household_fee_basis_cents=0,
                     household_annual_fee_cents=0,
                     billing_period_number=0)
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(row), 201)

    @api.route("/ria/households", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_households():
        from routes._base import params
        p = params()
        rows = sorted_rows("Household", {"firm_id": p.get("firm_id"),
                                         "household_status": p.get("household_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/households/<household_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def read_household(household_id):
        household = load("Household", household_id)
        calc.recompute_household_basis(household)
        calc.recompute_household_annual_fee(household)
        return ok(serialize(household), 200)

    # -------------------------------------------------------------- accounts

    @api.route("/ria/accounts", methods=["POST"], roles=["AdvisorOperationsLead"])
    def create_account():
        data = body()
        household = load("Household", need(data, "household_id"))
        firm = load_firm(need(data, "firm_id"))
        if household.get("firm_id") != firm.get("id"):
            fail("ERR_REFERENCE_MISMATCH")
        firm_active_guard(firm)
        account_type = need(data, "account_type")
        if account_type not in C.ACCOUNT_TYPES:
            fail("ERR_INVALID_STATE", "Unsupported account_type.")
        number = need(data, "account_number")
        for existing in STORE.find("HouseholdAccount", firm_id=firm.get("id")):
            if existing.get("account_number") == number and existing.get("account_status") != "CLOSED":
                fail("ERR_REFERENCE_MISMATCH", "account_number must be unique among non-CLOSED accounts.")
        row = create("HouseholdAccount",
                     household_id=household.get("id"),
                     firm_id=firm.get("id"),
                     account_number=number,
                     account_type=account_type,
                     account_status="PENDING",
                     market_value_cents=0,
                     account_fee_basis_cents=0,
                     billable=account_type in C.BILLABLE_ACCOUNT_TYPES,
                     householding_consent=data.get("householding_consent", "NONE"),
                     last_listed_cents=None,
                     last_listed_at=None,
                     model_portfolio_id=None,
                     billed_period_count=0)
        return ok(serialize(row), 201)

    @api.route("/ria/accounts", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_accounts():
        from routes._base import params
        p = params()
        rows = sorted_rows("HouseholdAccount", {"household_id": p.get("household_id"),
                                                "firm_id": p.get("firm_id"),
                                                "account_status": p.get("account_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/accounts/<account_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "AdvisorSupportAnalyst", "CustodyOperationsOfficer",
                      "ComplianceReviewer", "Client", "PlatformAdmin"])
    def read_account(account_id):
        ident = identity()
        account = load("HouseholdAccount", account_id)
        if ident.is_client and account.get("household_id") != ident.user_id:
            fail("ERR_RESOURCE_NOT_FOUND")
        account["market_value_cents"] = calc.compute_account_market_value(account)
        return ok(serialize(account), 200)

    @api.route("/ria/accounts/<account_id>", methods=["PATCH"], roles=["AdvisorOperationsLead"],
               if_match=True)
    def patch_account(account_id):
        account = load("HouseholdAccount", account_id)
        data = body()
        check_if_match(account, data)
        firm_active_guard(load_firm(account.get("firm_id")))
        if "householding_consent" in data:
            account["householding_consent"] = data["householding_consent"]
        touch(account)
        household = STORE.get("Household", account.get("household_id"))
        refresh_household(household)
        return ok(serialize(account), 200)

    @api.route("/ria/accounts/<account_id>/activate", methods=["POST"],
               roles=["CustodyOperationsOfficer"], if_match=True)
    def activate_account(account_id):
        account = load("HouseholdAccount", account_id)
        data = body()
        check_if_match(account, data)
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(account, ("PENDING",), ("CLOSED",))
        if firm.get("firm_posture") not in ("OPEN", "LIMITED"):
            fail("ERR_FIRM_NOT_OPEN_FOR_TRADING") if firm.get("firm_posture") != "FROZEN" \
                else fail("ERR_FIRM_FROZEN")
        agreement = current_agreement(firm)
        if agreement is None:
            fail("ERR_CUSTODY_AGREEMENT_REQUIRED")
        require_any_entitlement(firm, ("TRADING_AUTHORIZATION", "BILLING"))
        account["account_status"] = "OPEN"
        touch(account)
        refresh_household(STORE.get("Household", account.get("household_id")))
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(account), 200)

    @api.route("/ria/accounts/<account_id>/freeze", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def freeze_account(account_id):
        account = load("HouseholdAccount", account_id)
        data = body()
        check_if_match(account, data)
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(account, ("OPEN",), ("CLOSED",))
        account["account_status"] = "FROZEN"
        touch(account)
        _recompute_unallocated_blocks(firm)
        refresh_household(STORE.get("Household", account.get("household_id")))
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(account), 200)

    @api.route("/ria/accounts/<account_id>/unfreeze", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def unfreeze_account(account_id):
        account = load("HouseholdAccount", account_id)
        data = body()
        check_if_match(account, data)
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(account, ("FROZEN",), ("CLOSED",))
        if firm.get("firm_posture") not in ("OPEN", "LIMITED"):
            fail("ERR_FIRM_NOT_OPEN_FOR_TRADING")
        account["account_status"] = "OPEN"
        touch(account)
        refresh_household(STORE.get("Household", account.get("household_id")))
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(account), 200)

    @api.route("/ria/accounts/<account_id>/close", methods=["POST"],
               roles=["CustodyOperationsOfficer"], if_match=True)
    def close_account(account_id):
        account = load("HouseholdAccount", account_id)
        data = body()
        check_if_match(account, data)
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        status = account.get("account_status")
        if status == "CLOSED":
            fail("ERR_ALREADY_TERMINAL")
        if status not in ("OPEN", "FROZEN"):
            fail("ERR_INVALID_STATE")
        if status == "OPEN" and firm.get("firm_posture") not in ("OPEN", "LIMITED"):
            fail("ERR_FIRM_NOT_OPEN_FOR_TRADING")
        if status == "FROZEN" and firm.get("firm_posture") not in ("OPEN", "LIMITED", "SUSPENDED"):
            fail("ERR_FIRM_NOT_OPEN_FOR_TRADING")
        for transfer in STORE.find("AssetTransfer", receiving_account_id=account_id):
            if transfer.get("transfer_status") in C.TRANSFER_OPEN_STATES:
                fail("ERR_ACCOUNT_NOT_ELIGIBLE", "The account has in-flight asset transfers.")
        if status == "OPEN":
            for mov in STORE.find("MoneyMovementInstruction", account_id=account_id):
                if mov.get("movement_status") in C.MOVEMENT_OPEN_STATES:
                    fail("ERR_ACCOUNT_NOT_ELIGIBLE", "The account has in-flight money movements.")
        account["account_status"] = "CLOSED"
        touch(account)
        revoke_standing_instructions(account)
        refresh_household(STORE.get("Household", account.get("household_id")))
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(account), 200)

    @api.route("/ria/accounts/<account_id>/list", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def list_account(account_id):
        account = load("HouseholdAccount", account_id)
        data = body()
        check_if_match(account, data)
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        if account.get("account_status") not in ("PENDING", "OPEN", "FROZEN"):
            fail("ERR_INVALID_STATE")
        previous = account.get("last_listed_at")
        if previous is not None:
            from datetime import timedelta
            window_end = parse_dt(previous) + timedelta(hours=C.LISTING_COOLDOWN_HOURS)
            if parse_dt(previous) <= STORE.clock.now_dt() < window_end:
                fail("ERR_LISTING_COOLDOWN")
        traditional, _total = calc.listing_snapshot(account)
        account["last_listed_cents"] = traditional
        account["last_listed_at"] = STORE.clock.now()
        touch(account)
        refresh_household(STORE.get("Household", account.get("household_id")))
        calc.recompute_firm_basis_total(firm)
        _reconcile(firm)
        return ok(serialize(account), 200)

    @api.route("/ria/accounts/<account_id>/relink", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def relink_account(account_id):
        account = load("HouseholdAccount", account_id)
        data = body()
        check_if_match(account, data)
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        target = load("Household", need(data, "target_household_id"))
        if target.get("firm_id") != firm.get("id"):
            fail("ERR_REFERENCE_MISMATCH")
        check_occ(target, data, "expected_household_version", "ERR_STALE_HOUSEHOLD_VERSION")
        source = STORE.get("Household", account.get("household_id"))
        account["household_id"] = target.get("id")
        touch(account)
        touch(target)
        refresh_household(source)
        refresh_household(target)
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(account), 200)

    @api.route("/ria/accounts/<account_id>/model", methods=["PUT"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def assign_model(account_id):
        account = load("HouseholdAccount", account_id)
        data = body()
        check_if_match(account, data)
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        model_id = data.get("model_portfolio_id")
        if model_id:
            model = load("ModelPortfolio", model_id)
            if model.get("firm_id") != firm.get("id"):
                fail("ERR_REFERENCE_MISMATCH")
        account["model_portfolio_id"] = model_id
        touch(account)
        return ok(serialize(account), 200)

    # --------------------------------------------------- model-scoped reads

    @api.route("/ria/models/<model_id>/accounts", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "InvestmentCommitteeChair",
                      "ComplianceReviewer", "PlatformAdmin"])
    def list_model_accounts(model_id):
        from routes._base import params
        load("ModelPortfolio", model_id)
        p = params()
        rows = sorted_rows("HouseholdAccount", {"model_portfolio_id": model_id,
                                                "account_status": p.get("account_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)


def _state_or_terminal(row, from_states, terminal_states):
    from core.context import STATE_FIELDS
    state = row.get(STATE_FIELDS.get(row.get("_entity")))
    if terminal_states and state in terminal_states:
        fail("ERR_ALREADY_TERMINAL")
    allowed = from_states if isinstance(from_states, (tuple, list, set)) else (from_states,)
    if state not in allowed:
        fail("ERR_INVALID_STATE")


def _recompute_unallocated_blocks(firm):
    for block in STORE.find("BlockOrder", firm_id=firm.get("id")):
        if block.get("block_status") not in ("EXECUTED", "ALLOCATED", "UNALLOCATED"):
            continue
        allocations = STORE.find("BlockAllocation", block_order_id=block.get("id"))
        assigned = sum(int(a.get("share_micros") or 0) for a in allocations
                       if a.get("allocation_status") != "PENDING" and a.get("share_micros") is not None)
        residual = int(block.get("executed_share_micros") or 0) - assigned
        block["unallocated_share_micros"] = residual
        if block.get("block_status") in ("ALLOCATED", "UNALLOCATED"):
            block["block_status"] = "ALLOCATED" if residual == 0 else "UNALLOCATED"
        touch(block)


def _reconcile(firm):
    """Refresh the firm's already-provisioned reconciliation invariant rows."""
    from routes.ops import _evaluate_one
    now = STORE.clock.now()
    for inv in STORE.find("DatabaseInvariant", firm_id=firm.get("id")):
        status, expected, observed, detail = _evaluate_one(firm, inv.get("invariant_code"))
        inv["invariant_status"] = status
        inv["expected_total_cents"] = expected
        inv["observed_total_cents"] = observed
        inv["breach_detail_code"] = detail
        inv["last_evaluated_at"] = now
        touch(inv)