"""Model portfolios, target lines and the block-trading path."""

from core.context import body, check_if_match, check_occ, need
from core.errors import fail
from core.response import ok, paginate
from core.store import STORE
from domain import calc
from domain.cascade import refresh_household
from domain.guards import (firm_active_guard, require_all_entitlements,
                           require_model_management, trading_guard)
from domain.model import create, serialize, touch
from domain.resolve import sorted_rows
from routes._base import load, load_firm


def register(api):

    # ---------------------------------------------------------------- models

    @api.route("/ria/models", methods=["POST"], roles=["AdvisorOperationsLead"])
    def create_model():
        data = body()
        firm = load_firm(need(data, "firm_id"))
        firm_active_guard(firm)
        row = create("ModelPortfolio",
                     firm_id=firm.get("id"),
                     model_name=need(data, "model_name"),
                     model_status="DRAFT",
                     approval_round_number=0,
                     drift_approved_at=None,
                     target_weight_total_bps=0,
                     _model_entitlement_blocked=False)
        return ok(serialize(row), 201)

    @api.route("/ria/firms/<firm_id>/models", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "InvestmentCommitteeChair",
                      "ComplianceReviewer", "PlatformAdmin"])
    def list_models(firm_id):
        from routes._base import params
        load_firm(firm_id)
        p = params()
        rows = sorted_rows("ModelPortfolio", {"firm_id": firm_id, "model_status": p.get("model_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/models/<model_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "InvestmentCommitteeChair",
                      "PlatformAdmin"])
    def read_model(model_id):
        model = load("ModelPortfolio", model_id)
        _recompute_weights(model)
        return ok(serialize(model), 200)

    @api.route("/ria/models/<model_id>/targets", methods=["POST"],
               roles=["AdvisorOperationsLead"])
    def add_target(model_id):
        model = load("ModelPortfolio", model_id)
        firm = load_firm(model.get("firm_id"))
        firm_active_guard(firm)
        data = body()
        symbol = need(data, "symbol")
        for existing in STORE.find("ModelTarget", model_id=model_id):
            if existing.get("symbol") == symbol:
                fail("ERR_REFERENCE_MISMATCH", "symbol must be unique within the model.")
        create("ModelTarget", model_id=model_id, symbol=symbol,
               target_weight_bps=int(data.get("target_weight_bps") or 0))
        _recompute_weights(model)
        target = STORE.find_one("ModelTarget", model_id=model_id, symbol=symbol)
        if model.get("target_weight_total_bps") != 10000 and model.get("model_status") == "APPROVED":
            _validate_weights(model)
        return ok(serialize(target), 201)

    @api.route("/ria/model-targets/<target_id>", methods=["PUT"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def replace_target(target_id):
        target = load("ModelTarget", target_id)
        data = body()
        check_if_match(target, data)
        model = load("ModelPortfolio", target.get("model_id"))
        firm_active_guard(load_firm(model.get("firm_id")))
        target["target_weight_bps"] = int(need(data, "target_weight_bps"))
        touch(target)
        _recompute_weights(model)
        return ok(serialize(target), 200)

    @api.route("/ria/models/<model_id>/targets", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "InvestmentCommitteeChair",
                      "PlatformAdmin"])
    def list_targets(model_id):
        load("ModelPortfolio", model_id)
        rows = sorted_rows("ModelTarget", {"model_id": model_id})
        return ok([serialize(r) for r in rows], 200)

    @api.route("/ria/models/<model_id>/approve", methods=["POST"],
               roles=["InvestmentCommitteeChair"], if_match=True)
    def approve_model(model_id):
        model = load("ModelPortfolio", model_id)
        data = body()
        check_if_match(model, data)
        firm = load_firm(model.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(model, ("DRAFT", "REBALANCING"), ("ARCHIVED",))
        require_model_management(firm)
        if firm.get("firm_posture") not in ("OPEN", "LIMITED"):
            fail("ERR_FIRM_NOT_OPEN_FOR_TRADING")
        _validate_weights(model)
        model["model_status"] = "APPROVED"
        model["drift_approved_at"] = STORE.clock.now()
        model["approval_round_number"] = int(model.get("approval_round_number") or 0) + 1
        model["_model_entitlement_blocked"] = False
        touch(model)
        return ok(serialize(model), 200)

    @api.route("/ria/models/<model_id>/rebalance", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def rebalance_model(model_id):
        model = load("ModelPortfolio", model_id)
        data = body()
        check_if_match(model, data)
        firm = load_firm(model.get("firm_id"))
        firm_active_guard(firm)
        check_occ(model, data, "expected_model_portfolio_version", "ERR_STALE_MODEL_VERSION")
        _state_or_terminal(model, ("APPROVED", "ACTIVE"), ("ARCHIVED",))
        if model.get("model_status") == "APPROVED":
            require_model_management(firm)
        model["model_status"] = "REBALANCING"
        touch(model)
        for block in STORE.find("BlockOrder", firm_id=firm.get("id"), model_id=model_id):
            if block.get("block_status") == "DRAFT":
                block["block_status"] = "SUBMITTED"
                touch(block)
        return ok(serialize(model), 200)

    @api.route("/ria/models/<model_id>/activate", methods=["POST"],
               roles=["InvestmentCommitteeChair"], if_match=True)
    def activate_model(model_id):
        model = load("ModelPortfolio", model_id)
        data = body()
        check_if_match(model, data)
        firm = load_firm(model.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(model, ("APPROVED",), ("ARCHIVED",))
        require_model_management(firm)
        trading_guard(firm)
        accounts = STORE.find("HouseholdAccount", firm_id=firm.get("id"), model_portfolio_id=model_id)
        if not accounts:
            fail("ERR_INVALID_STATE", "At least one account must be assigned to the model.")
        model["model_status"] = "ACTIVE"
        touch(model)
        for account in accounts:
            if account.get("account_status") == "PENDING":
                account["account_status"] = "OPEN"
                touch(account)
                refresh_household(STORE.get("Household", account.get("household_id")))
            else:
                refresh_household(STORE.get("Household", account.get("household_id")))
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(model), 200)

    @api.route("/ria/models/<model_id>/archive", methods=["POST"],
               roles=["InvestmentCommitteeChair"], if_match=True)
    def archive_model(model_id):
        model = load("ModelPortfolio", model_id)
        data = body()
        check_if_match(model, data)
        firm = load_firm(model.get("firm_id"))
        firm_active_guard(firm)
        status = model.get("model_status")
        if status == "ARCHIVED":
            fail("ERR_ALREADY_TERMINAL")
        if status == "DRAFT":
            pass
        elif status == "APPROVED":
            if STORE.find("HouseholdAccount", firm_id=firm.get("id"), model_portfolio_id=model_id):
                fail("ERR_INVALID_STATE", "An account is still assigned to this model.")
        else:
            fail("ERR_INVALID_STATE")
        model["model_status"] = "ARCHIVED"
        touch(model)
        return ok(serialize(model), 200)

    # ---------------------------------------------------------- block orders

    @api.route("/ria/block-orders", methods=["POST"], roles=["AdvisorOperationsLead"])
    def create_block():
        data = body()
        firm = load_firm(need(data, "firm_id"))
        firm_active_guard(firm)
        model = load("ModelPortfolio", need(data, "model_id"))
        if model.get("firm_id") != firm.get("id"):
            fail("ERR_REFERENCE_MISMATCH")
        row = create("BlockOrder",
                     firm_id=firm.get("id"),
                     model_id=model.get("id"),
                     symbol=need(data, "symbol"),
                     side=need(data, "side"),
                     total_requested_share_micros=0,
                     executed_share_micros=int(data.get("executed_share_micros") or 0),
                     execution_price_micros=int(data.get("execution_price_micros") or 0),
                     block_status="DRAFT",
                     unallocated_share_micros=None,
                     preview_notional_cents=None)
        return ok(serialize(row), 201)

    @api.route("/ria/block-orders/<block_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def read_block(block_id):
        block = load("BlockOrder", block_id)
        _recompute_requested(block)
        return ok(serialize(block), 200)

    @api.route("/ria/firms/<firm_id>/block-orders", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_blocks(firm_id):
        from routes._base import params
        load_firm(firm_id)
        p = params()
        rows = sorted_rows("BlockOrder", {"firm_id": firm_id, "block_status": p.get("block_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/models/<model_id>/block-orders", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "InvestmentCommitteeChair",
                      "ComplianceReviewer", "PlatformAdmin"])
    def list_model_blocks(model_id):
        from routes._base import params
        load("ModelPortfolio", model_id)
        p = params()
        rows = sorted_rows("BlockOrder", {"model_id": model_id, "block_status": p.get("block_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/block-orders/<block_id>/allocations", methods=["POST"],
               roles=["AdvisorOperationsLead"])
    def add_allocation(block_id):
        block = load("BlockOrder", block_id)
        firm = load_firm(block.get("firm_id"))
        firm_active_guard(firm)
        data = body()
        account = load("HouseholdAccount", need(data, "account_id"))
        if account.get("firm_id") != firm.get("id"):
            fail("ERR_REFERENCE_MISMATCH")
        rank = int(need(data, "allocation_rank"))
        for existing in STORE.find("BlockAllocation", block_order_id=block_id):
            if int(existing.get("allocation_rank") or 0) == rank:
                fail("ERR_ALLOCATION_NOT_CONSISTENT", "allocation_rank must be unique within the block.")
        row = create("BlockAllocation",
                     block_order_id=block_id,
                     account_id=account.get("id"),
                     requested_share_micros=int(data.get("requested_share_micros") or 0),
                     share_micros=None,
                     allocation_rank=rank,
                     allocated_cost_cents=None,
                     average_price_micros=None,
                     fee_rebate_cents=0,
                     allocation_status="PENDING")
        _recompute_requested(block)
        return ok(serialize(row), 201)

    @api.route("/ria/block-orders/<block_id>/allocations", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_allocations(block_id):
        from routes._base import params
        load("BlockOrder", block_id)
        p = params()
        rows = sorted_rows("BlockAllocation", {"block_order_id": block_id,
                                               "allocation_status": p.get("allocation_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/accounts/<account_id>/block-allocations", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_account_allocations(account_id):
        from routes._base import params
        load("HouseholdAccount", account_id)
        p = params()
        rows = sorted_rows("BlockAllocation", {"account_id": account_id,
                                               "allocation_status": p.get("allocation_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/block-orders/<block_id>/submit", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def submit_block(block_id):
        block = load("BlockOrder", block_id)
        data = body()
        check_if_match(block, data)
        firm = load_firm(block.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(block, ("DRAFT",), ("SETTLED",))
        model = STORE.get("ModelPortfolio", block.get("model_id"))
        request_list = STORE.find("BlockAllocation", block_order_id=block_id)
        for alloc in request_list:
            account = STORE.get("HouseholdAccount", alloc.get("account_id"))
            if account is None or account.get("account_status") != "OPEN":
                fail("ERR_ACCOUNT_NOT_ELIGIBLE")
        if model is None or model.get("model_status") not in ("APPROVED", "ACTIVE"):
            fail("ERR_MODEL_NOT_APPROVED")
        require_all_entitlements(firm, ("TRADING_AUTHORIZATION", "MODEL_MANAGEMENT"))
        trading_guard(firm)
        _recompute_requested(block)
        ranks = [int(a.get("allocation_rank") or 0) for a in request_list]
        if len(ranks) != len(set(ranks)):
            fail("ERR_ALLOCATION_NOT_CONSISTENT")
        if int(block.get("total_requested_share_micros") or 0) < int(block.get("executed_share_micros") or 0):
            fail("ERR_ALLOCATION_NOT_CONSISTENT")
        block["block_status"] = "SUBMITTED"
        touch(block)
        return ok(serialize(block), 200)

    @api.route("/ria/block-orders/<block_id>/execute", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def execute_block(block_id):
        block = load("BlockOrder", block_id)
        data = body()
        check_if_match(block, data)
        firm = load_firm(block.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(block, ("SUBMITTED",), ("SETTLED",))
        trading_guard(firm)
        block["block_status"] = "EXECUTED"
        touch(block)
        return ok(serialize(block), 200)

    @api.route("/ria/block-orders/<block_id>/allocate", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def allocate(block_id):
        block = load("BlockOrder", block_id)
        data = body()
        check_if_match(block, data)
        firm = load_firm(block.get("firm_id"))
        firm_active_guard(firm)
        check_occ(block, data, "expected_block_order_version", "ERR_STALE_BLOCK_VERSION")
        # PRD §3.3: unfreezing an account "makes an `UNALLOCATED` block recoverable",
        # so the allocation run is re-enterable from `UNALLOCATED`.
        _state_or_terminal(block, ("EXECUTED", "UNALLOCATED"), ("SETTLED",))
        executed = int(block.get("executed_share_micros") or 0)
        allocations = STORE.find("BlockAllocation", block_order_id=block_id)
        eligible = [a for a in allocations
                    if (STORE.get("HouseholdAccount", a.get("account_id")) or {}).get("account_status") == "OPEN"]
        # PRD §3.4: a zero executed quantity "never reaches allocation at all",
        # and the run must find at least one allocation to target.  Allocations
        # that target a non-OPEN account are excluded from the requested sum and
        # left PENDING with no shares, so the block keeps the full residual.
        if executed <= 0 or not allocations:
            fail("ERR_NO_ELIGIBLE_ALLOCATION_TARGET")
        if eligible:
            filled, residual = calc.allocate_block(block, allocations, executed,
                                                   int(block.get("execution_price_micros") or 0))
            for alloc in filled:
                touch(alloc)
        else:
            residual = executed
        block["unallocated_share_micros"] = residual
        block["block_status"] = "ALLOCATED" if residual == 0 else "UNALLOCATED"
        touch(block)
        for alloc in STORE.find("BlockAllocation", block_order_id=block_id):
            touch(alloc)
        return ok(serialize(block), 200)

    @api.route("/ria/block-orders/<block_id>/allocation-preview", methods=["POST"],
               roles=["AdvisorOperationsLead"])
    def allocation_preview(block_id):
        block = load("BlockOrder", block_id)
        data = body()
        firm = load_firm(block.get("firm_id"))
        firm_active_guard(firm)
        executed = int(data.get("executed_share_micros", block.get("executed_share_micros")) or 0)
        price = int(data.get("execution_price_micros", block.get("execution_price_micros")) or 0)
        notional = calc.block_notional_cents(executed, price)
        # Declared as a pure read ("writes no rows", side_effects: none); the
        # indicative figure is surfaced on the row, but the block's version and
        # updated_at are deliberately left untouched so a subsequent allocation
        # is not invalidated by this diagnostic call.
        block["preview_notional_cents"] = notional
        return ok(serialize(block), 200)

    @api.route("/ria/block-orders/<block_id>/settle", methods=["POST"],
               roles=["CustodyOperationsOfficer"], if_match=True)
    def settle_block(block_id):
        block = load("BlockOrder", block_id)
        data = body()
        check_if_match(block, data)
        firm = load_firm(block.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(block, ("ALLOCATED",), ("SETTLED",))
        if int(block.get("unallocated_share_micros") or 0) != 0:
            fail("ERR_ALLOCATION_INCOMPLETE")
        allocations = STORE.find("BlockAllocation", block_order_id=block_id)
        # PRD §3.4: the drift is credited back onto the allocations at the moment
        # the block is still `ALLOCATED` and its allocations are not yet `SETTLED`;
        # the household-level `FeeCredit` path applies only to a block already
        # settled before its allocation basis was finalized.
        settled = block.get("block_status") == "SETTLED"
        drift = calc.distribute_over_allocation(block)
        if drift > 0 and settled:
            calc.reset_block_rebates(block)
            _credit_households(block, drift)
        for alloc in allocations:
            alloc["allocation_status"] = "SETTLED"
            touch(alloc)
        block["block_status"] = "SETTLED"
        touch(block)
        for alloc in allocations:
            account = STORE.get("HouseholdAccount", alloc.get("account_id"))
            if account is not None:
                calc.recompute_account(account)
                refresh_household(STORE.get("Household", account.get("household_id")))
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(block), 200)


def _credit_households(block, drift):
    """C4 CREDIT_TO_HOUSEHOLD: the drift is credited to the owning household."""
    accounts = STORE.find("BlockAllocation", block_order_id=block.get("id"))
    seen = set()
    remaining = drift
    for alloc in sorted(accounts, key=lambda a: (-int(a.get("allocated_cost_cents") or 0),
                                                 int(a.get("allocation_rank") or 0))):
        account = STORE.get("HouseholdAccount", alloc.get("account_id"))
        if account is None:
            continue
        household_id = account.get("household_id")
        if household_id in seen or remaining <= 0:
            continue
        seen.add(household_id)
        create("FeeCredit",
               household_id=household_id,
               credit_cents=remaining,
               earned_on_date=STORE.clock.now(),
               credit_status="AVAILABLE",
               applied_to_billing_run_id=None)
        remaining = 0


def _recompute_weights(model):
    total = sum(int(t.get("target_weight_bps") or 0) for t in STORE.find("ModelTarget", model_id=model.get("id")))
    model["target_weight_total_bps"] = total
    return total


def _validate_weights(model):
    if _recompute_weights(model) != 10000:
        fail("ERR_MODEL_WEIGHTS_INVALID")


def _recompute_requested(block):
    total = sum(int(a.get("requested_share_micros") or 0)
                for a in STORE.find("BlockAllocation", block_order_id=block.get("id")))
    block["total_requested_share_micros"] = total
    return total


def _state_or_terminal(row, from_states, terminal_states):
    from core.context import STATE_FIELDS
    state = row.get(STATE_FIELDS.get(row.get("_entity")))
    if terminal_states and state in terminal_states:
        fail("ERR_ALREADY_TERMINAL")
    allowed = from_states if isinstance(from_states, (tuple, list, set)) else (from_states,)
    if state not in allowed:
        fail("ERR_INVALID_STATE")