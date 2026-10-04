"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server before each test and every
test therefore begins against an empty database.

Internal setup calls use the lenient ``get_success_data`` validator so a broken
precondition surfaces as a clear "Setup step failed" error rather than as a
confusing assertion failure inside the test.

State-changing calls carry the acting row's current ``version`` as the
conditional-request token PRD §2.10 requires; the token is taken from the row
the previous call in the same fixture already returned.
"""
from prd_bench_local_runner.testing import get_success_data

import uuid

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_UTC, Q4_PERIOD_END, Q4_PERIOD_START, MICROS_TO_CENTS_DIVISOR,
)
from .factories import (
    DEFAULTS, create_account_payload, create_admin_action_payload,
    create_alternative_payload, create_asset_transfer_payload,
    create_billing_run_payload, create_block_allocation_payload,
    create_block_order_payload, create_custody_agreement_payload,
    create_custody_evidence_payload, create_data_feed_payload,
    create_entitlement_payload, create_fee_credit_payload, create_firm_payload,
    create_household_payload, create_model_payload, create_model_target_payload,
    create_money_movement_payload, create_second_firm_payload,
    create_standing_instruction_payload, create_system_config_payload,
    create_transfer_lot_payload,
)
from .test_users import TEST_USERS, make_client_headers

EMPTY = {}


def _ok(response):
    return get_success_data(response)


# ══════════════════════════════════════════════════════════════════════════════
# Tier 1 — State progression primitives
# ══════════════════════════════════════════════════════════════════════════════

def setup_clock(current_utc: str = DEFAULT_CLOCK_UTC):
    """Move the platform's logical clock to a deterministic instant."""
    return _ok(api_client.set_clock({"current_utc": current_utc}, TEST_USERS["admin_headers"]))


def _firm_payload(**overrides) -> dict:
    """A firm registration payload.

    PRD §3.1: "Both `legal_name` and `crd_number` are required and must be
    unique among the firm's non-`ARCHIVED` peers."  A fixture that builds a firm
    without an explicit identity therefore mints its own, so that independent
    fixtures never collide on the uniqueness rule they are not exercising; a
    caller that pins the identity keeps it verbatim.
    """
    if "legal_name" in overrides or "crd_number" in overrides:
        return create_firm_payload(**overrides)
    suffix = uuid.uuid4().hex[:10].upper()
    return create_firm_payload(
        legal_name="%s %s" % (DEFAULTS["LEGAL_NAME"], suffix),
        crd_number="CRD-%s" % suffix,
        **overrides,
    )


def setup_firm(**overrides) -> dict:
    """Register a firm. It begins PENDING/SUSPENDED — the intended cold-start state."""
    return _ok(api_client.create_firm(_firm_payload(**overrides), TEST_USERS["admin_headers"]))


def setup_second_firm(**overrides) -> dict:
    """Register a second, independent firm for multi-tenancy scenarios."""
    return _ok(api_client.create_firm(create_second_firm_payload(**overrides), TEST_USERS["admin_headers"]))


def draft_and_execute_agreement(firm_id: str, adviser_crd_number: str = None, draft=None) -> dict:
    """Draft, submit and countersign a custody agreement for a firm.

    The drafter and the countersigner are always different identities, as the
    two-party control requires.  ``draft`` may be supplied when the caller
    already holds the drafted row (and therefore its conditional token).
    """
    if draft is None:
        draft = _ok(api_client.create_custody_agreement(
            firm_id,
            create_custody_agreement_payload(
                adviser_crd_number=adviser_crd_number or DEFAULTS["CRD_NUMBER"]
            ),
            TEST_USERS["advisor_ops_headers"],
        ))
    submitted = _ok(api_client.submit_custody_agreement(
        draft["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=draft
    ))
    executed = _ok(
        api_client.execute_custody_agreement(
            firm_id, EMPTY, TEST_USERS["custody_officer_headers"], row=submitted
        )
    )
    return executed


def grant_entitlement(firm_id: str, agreement_id: str, entitlement_code: str, requested=None) -> dict:
    """Request and grant one entitlement against the firm's current agreement."""
    if requested is None:
        requested = _ok(api_client.create_entitlement(
            create_entitlement_payload(firm_id, agreement_id, entitlement_code=entitlement_code),
            TEST_USERS["advisor_ops_headers"],
        ))
    return _ok(api_client.grant_entitlement(
        requested["id"], EMPTY, TEST_USERS["custody_officer_headers"], row=requested
    ))


def setup_firm_with_agreement(entitlement_codes=(), **firm_overrides):
    """Firm with an EXECUTED agreement and an optional set of GRANTED entitlements.

    Returns (firm, agreement). The firm's posture is OPEN once the agreement
    executes; granting entitlements does not disturb it.
    """
    setup_clock()
    firm = setup_firm(**firm_overrides)
    # PRD §3.1: submitting an agreement requires the firm's `crd_number` to equal
    # the agreement's `adviser_crd_number`, so the drafted agreement attests the
    # firm that actually owns it.
    agreement = draft_and_execute_agreement(firm["id"], adviser_crd_number=firm["crd_number"])
    for code in entitlement_codes:
        grant_entitlement(firm["id"], agreement["id"], code)
    return firm, agreement


def refetch_firm(firm_id: str) -> dict:
    return _ok(api_client.get_firm(firm_id, TEST_USERS["compliance_headers"]))


def refetch_account(account_id: str) -> dict:
    return _ok(api_client.get_account(account_id, TEST_USERS["advisor_ops_headers"]))


def refetch_household(household_id: str) -> dict:
    return _ok(api_client.get_household(household_id, TEST_USERS["advisor_ops_headers"]))


def refetch_model(model_id: str) -> dict:
    return _ok(api_client.get_model(model_id, TEST_USERS["advisor_ops_headers"]))


def refetch_block(block_id: str) -> dict:
    return _ok(api_client.get_block_order(block_id, TEST_USERS["advisor_ops_headers"]))


def refetch_transfer(transfer_id: str) -> dict:
    return _ok(api_client.get_asset_transfer(transfer_id, TEST_USERS["advisor_ops_headers"]))


def refetch_agreement(agreement_id: str) -> dict:
    return _ok(api_client.get_custody_agreement(agreement_id, TEST_USERS["advisor_ops_headers"]))


def refetch_entitlement(entitlement_id: str) -> dict:
    return _ok(api_client.get_entitlement(entitlement_id, TEST_USERS["advisor_ops_headers"]))


def refetch_instruction(instruction_id: str) -> dict:
    return _ok(api_client.get_standing_instruction(instruction_id, TEST_USERS["advisor_ops_headers"]))


def refetch_movement(movement_id: str) -> dict:
    return _ok(api_client.get_money_movement(movement_id, TEST_USERS["advisor_ops_headers"]))


def refetch_alternative(holding_id: str) -> dict:
    return _ok(api_client.get_alternative(holding_id, TEST_USERS["advisor_ops_headers"]))


def refetch_run(run_id: str) -> dict:
    return _ok(api_client.get_billing_run(run_id, TEST_USERS["advisor_ops_headers"]))


def refetch_feed(firm_id: str, feed_id: str = None) -> dict:
    feeds = _ok(api_client.list_firm_data_feeds(firm_id, TEST_USERS["compliance_headers"]))
    if feed_id:
        return next(f for f in feeds if f["id"] == feed_id)
    return feeds[0]


# ══════════════════════════════════════════════════════════════════════════════
# Tier 2 — Entity hierarchy primitives
# ══════════════════════════════════════════════════════════════════════════════

def setup_household(firm_id: str, household_name: str = None, **overrides) -> dict:
    name = household_name or DEFAULTS["HOUSEHOLD_NAME"]
    return _ok(api_client.create_household(
        create_household_payload(firm_id, household_name=name, **overrides),
        TEST_USERS["advisor_ops_headers"],
    ))


def create_pending_account(household_id: str, firm_id: str, account_number: str, **overrides) -> dict:
    return _ok(api_client.create_account(
        create_account_payload(household_id, firm_id, account_number=account_number, **overrides),
        TEST_USERS["advisor_ops_headers"],
    ))


def open_account(household_id: str, firm_id: str, account_number: str, **overrides) -> dict:
    """Create an account and activate it (requires a GRANTED trading or billing entitlement)."""
    account = create_pending_account(household_id, firm_id, account_number, **overrides)
    return _ok(api_client.activate_account(
        account["id"], EMPTY, TEST_USERS["custody_officer_headers"], row=account
    ))


def credit_lot_position(
    account_id: str,
    firm_id: str,
    symbol: str = "VTI",
    quantity_micros: int = 4_000_000_000,
    valuation_price_micros: int = 250_000_000,
    sent_cost_basis_cents: int = 90_000_000,
    lot_inventory_date: str = "2019-01-02T00:00:00Z",
    method: str = "ACAT",
    extra_lots=(),
):
    """Open a transfer, add its lots, submit it and record receipt.

    With every lot carrying a reported basis the transfer credits immediately,
    so the receiving account's positions (and its fee basis) are live.

    Returns (transfer, [lots]).
    """
    transfer = _ok(api_client.create_asset_transfer(
        create_asset_transfer_payload(account_id, firm_id, method=method),
        TEST_USERS["advisor_ops_headers"],
    ))
    lot_specs = [dict(
        symbol=symbol, quantity_micros=quantity_micros,
        valuation_price_micros=valuation_price_micros,
        sent_cost_basis_cents=sent_cost_basis_cents,
        lot_inventory_date=lot_inventory_date,
    )]
    lot_specs.extend(extra_lots)
    lots = []
    for spec in lot_specs:
        lots.append(_ok(api_client.create_transfer_lot(
            transfer["id"], create_transfer_lot_payload(**spec), TEST_USERS["advisor_ops_headers"]
        )))
    transfer = _ok(api_client.transfer_out(
        transfer["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=transfer
    ))
    transfer = _ok(api_client.mark_received(
        transfer["id"], EMPTY, TEST_USERS["custody_officer_headers"], row=transfer
    ))
    return transfer, lots


def setup_funded_household(
    entitlement_codes=("TRADING_AUTHORIZATION",),
    account_specs=(),
    household_name: str = None,
    start_number: int = 1,
    **firm_overrides,
):
    """Firm + executed agreement + entitlements + one household + N funded accounts.

    ``account_specs`` is a sequence of dicts with ``basis_cents`` (the desired
    ``account_fee_basis_cents``) and optional ``account_type``,
    ``householding_consent`` and ``account_number``. The basis is realised by a
    single credited lot whose market value and reported cost basis are both set
    to the requested figure, so MAX(market, cost) lands exactly on it.

    Returns (firm, agreement, household, [accounts]).
    """
    firm, agreement = setup_firm_with_agreement(entitlement_codes=entitlement_codes, **firm_overrides)
    household = setup_household(firm["id"], household_name=household_name)
    accounts = []
    for index, spec in enumerate(account_specs):
        spec = dict(spec)
        basis = spec.pop("basis_cents")
        number = spec.pop("account_number", f"RIA-{100000 + start_number + index}")
        account = open_account(household["id"], firm["id"], number, **spec)
        if basis:
            quantity, price = lot_for_basis(basis)
            credit_lot_position(
                account["id"], firm["id"],
                quantity_micros=quantity, valuation_price_micros=price,
                sent_cost_basis_cents=basis,
            )
        accounts.append(refetch_account(account["id"]))
    return firm, agreement, household, accounts


def lot_for_basis(basis_cents: int, valuation_price_micros: int = 250_000_000):
    """Return (quantity_micros, price_micros) whose market value equals ``basis_cents``."""
    quantity = basis_cents * MICROS_TO_CENTS_DIVISOR // valuation_price_micros
    return quantity, valuation_price_micros


# ══════════════════════════════════════════════════════════════════════════════
# Tier 3 — Full lifecycle shortcuts
# ══════════════════════════════════════════════════════════════════════════════

def setup_approved_model(firm_id: str, targets=(("VTI", 10000),), activate: bool = False,
                         account_ids=(), model_name: str = "Core Balanced", model=None) -> dict:
    """Create a model, add its target lines, approve it, optionally activate it."""
    if model is None:
        model = _ok(api_client.create_model(
            create_model_payload(firm_id, model_name=model_name), TEST_USERS["advisor_ops_headers"]
        ))
    for symbol, bps in targets:
        _ok(api_client.create_model_target(
            model["id"], create_model_target_payload(symbol=symbol, target_weight_bps=bps),
            TEST_USERS["advisor_ops_headers"],
        ))
    model = _ok(api_client.approve_model(
        model["id"], EMPTY, TEST_USERS["committee_chair_headers"], row=refetch_model(model["id"])
    ))
    if activate:
        for account_id in account_ids:
            row = refetch_account(account_id)
            _ok(api_client.set_account_model(
                account_id, {"model_portfolio_id": model["id"]},
                TEST_USERS["advisor_ops_headers"], row=row,
            ))
        model = _ok(api_client.activate_model(
            model["id"], EMPTY, TEST_USERS["committee_chair_headers"], row=refetch_model(model["id"])
        ))
    return refetch_model(model["id"])


def assign_model(account_id: str, model_id: str, account=None) -> dict:
    row = account if account is not None else refetch_account(account_id)
    return _ok(api_client.set_account_model(
        account_id, {"model_portfolio_id": model_id}, TEST_USERS["advisor_ops_headers"], row=row
    ))


def setup_executed_block(
    firm_id: str,
    model_id: str,
    allocations=(),
    executed_share_micros: int = 1_000_000_000,
    execution_price_micros: int = 52_375_001,
    side: str = "BUY",
    symbol: str = "VTI",
    allocate: bool = False,
) -> dict:
    """Draft a block, add its allocations, submit and execute it (optionally allocate).

    Each allocation spec is ``(account_id, requested_share_micros, allocation_rank)``.
    Returns the block order in its final state.
    """
    block = _ok(api_client.create_block_order(
        create_block_order_payload(
            firm_id, model_id, symbol=symbol, side=side,
            executed_share_micros=executed_share_micros,
            execution_price_micros=execution_price_micros,
        ),
        TEST_USERS["advisor_ops_headers"],
    ))
    for account_id, requested, rank in allocations:
        _ok(api_client.create_block_allocation(
            block["id"],
            create_block_allocation_payload(account_id, requested_share_micros=requested, allocation_rank=rank),
            TEST_USERS["advisor_ops_headers"],
        ))
    block = refetch_block(block["id"])
    block = _ok(api_client.submit_block_order(
        block["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=block
    ))
    block = _ok(api_client.execute_block_order(
        block["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=block
    ))
    if allocate:
        block = refetch_block(block["id"])
        block = _ok(api_client.allocate_block_order(
            block["id"], {"expected_block_order_version": block["version"]},
            TEST_USERS["advisor_ops_headers"], row=block,
        ))
    return refetch_block(block["id"])


def setup_block_model_scenario(
    account_numbers=("RIA-300001", "RIA-300002", "RIA-300003"),
    entitlement_codes=("TRADING_AUTHORIZATION", "MODEL_MANAGEMENT", "BILLING"),
):
    """Firm + household + three OPEN accounts + an APPROVED model assigned to all three."""
    firm, agreement = setup_firm_with_agreement(entitlement_codes=entitlement_codes)
    household = setup_household(firm["id"])
    accounts = [
        open_account(household["id"], firm["id"], number) for number in account_numbers
    ]
    model = setup_approved_model(firm["id"], targets=(("VTI", 6000), ("BND", 4000)))
    for account in accounts:
        assign_model(account["id"], model["id"], account=refetch_account(account["id"]))
    return firm, agreement, household, accounts, model


def create_three_way_block(firm_id: str, model_id: str, accounts, executed_share_micros: int = 1_000_000_000,
                           requests=(333_000_000, 333_000_000, 334_000_001), allocate: bool = False):
    """The canonical three-way split used by the allocation and rounding scenarios."""
    specs = [(accounts[i]["id"], requests[i], i + 1) for i in range(3)]
    return setup_executed_block(
        firm_id, model_id, allocations=specs,
        executed_share_micros=executed_share_micros, allocate=allocate,
    )


def setup_verified_standing_instruction(
    account_id: str, household_id: str, periodic_limit_cents: int = 500_000,
    instruction_type: str = "THIRD_PARTY_DISBURSEMENT", payee_name: str = None, verify: bool = True,
):
    """Create a standing instruction and, unless suppressed, verify it as the Client.

    Returns the instruction (VERIFIED and carrying its consumed total when verified).
    """
    instruction = _ok(api_client.create_standing_instruction(
        account_id,
        create_standing_instruction_payload(
            periodic_limit_cents=periodic_limit_cents,
            instruction_type=instruction_type,
            **({"payee_name": payee_name} if payee_name else {}),
        ),
        TEST_USERS["advisor_ops_headers"],
    ))
    if verify:
        instruction = _ok(api_client.verify_standing_instruction(
            instruction["id"], {"verification_token": instruction["verification_token"]},
            make_client_headers(household_id), row=instruction,
        ))
    return instruction


def setup_submitted_movement(account_id: str, instruction_id: str, amount_cents: int = 100_000,
                             authorization_note: str = "Client confirmed on 2026-09-01 by signed form",
                             movement_type: str = "ACH_DISBURSEMENT") -> dict:
    """Draft a movement and submit it for authorization."""
    movement = _ok(api_client.create_money_movement(
        create_money_movement_payload(
            account_id, instruction_id, amount_cents=amount_cents,
            authorization_note=authorization_note, movement_type=movement_type,
        ),
        TEST_USERS["advisor_ops_headers"],
    ))
    return _ok(api_client.submit_money_movement(
        movement["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=movement
    ))


def authorize_movement_as_client(movement_id: str, household_id: str, movement=None):
    """Authorize a pending movement as the household that owns the account."""
    row = movement if movement is not None else refetch_movement(movement_id)
    return api_client.authorize_money_movement(
        movement_id, EMPTY, make_client_headers(household_id), row=row
    )


def setup_money_movement_scenario(account_type: str = "INDIVIDUAL", account_number: str = "RIA-400001",
                                  periodic_limit_cents: int = 500_000, verify_instruction: bool = True,
                                  movement_amount_cents: int = 100_000,
                                  authorization_note: str = "Client confirmed on 2026-09-01 by signed form",
                                  fund_account: bool = False):
    """Firm + household + one OPEN account + instruction + a submitted movement.

    Returns a dict with firm, agreement, household, account, instruction, movement.
    """
    firm, agreement = setup_firm_with_agreement(entitlement_codes=("MONEY_MOVEMENT", "TRADING_AUTHORIZATION"))
    household = setup_household(firm["id"])
    account = open_account(
        household["id"], firm["id"], account_number, account_type=account_type
    )
    if fund_account:
        credit_lot_position(account["id"], firm["id"])
    instruction = setup_verified_standing_instruction(
        account["id"], household["id"], periodic_limit_cents=periodic_limit_cents,
        verify=verify_instruction,
    )
    movement = setup_submitted_movement(
        account["id"], instruction["id"], amount_cents=movement_amount_cents,
        authorization_note=authorization_note,
    )
    return {
        "firm": firm, "agreement": agreement, "household": household,
        "account": account, "instruction": instruction, "movement": movement,
    }


def setup_alternative_holding(account_id: str, **overrides) -> dict:
    return _ok(api_client.create_alternative(
        create_alternative_payload(account_id, **overrides), TEST_USERS["advisor_ops_headers"]
    ))


def setup_accepted_alternative(account_id: str, **overrides) -> dict:
    """Create a holding, submit its valuation and accept it."""
    holding = setup_alternative_holding(account_id, **overrides)
    holding = _ok(api_client.submit_valuation(
        holding["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=holding
    ))
    return _ok(api_client.accept_valuation(
        holding["id"], EMPTY, TEST_USERS["compliance_headers"], row=holding
    ))


def setup_custody_evidence(firm_id: str, requirement_code: str = "SURPRISE_EXAMINATION",
                           critical: bool = True, submit_as: str = None) -> dict:
    """Raise an evidence requirement and, if requested, submit it."""
    evidence = _ok(api_client.create_custody_evidence(
        firm_id, create_custody_evidence_payload(requirement_code=requirement_code, critical=critical),
        TEST_USERS["advisor_ops_headers"],
    ))
    if submit_as:
        headers = TEST_USERS["advisor_ops_headers"] if submit_as == "default" else None
        _ok(api_client.submit_custody_evidence(
            evidence["id"], EMPTY, headers or {"X-User-ID": submit_as, "X-User-Role": "AdvisorOperationsLead",
                                               "Content-Type": "application/json"},
            row=evidence,
        ))
    return refetch_evidence(evidence["id"])


def refetch_evidence(evidence_id: str) -> dict:
    return _ok(api_client.get_custody_evidence(evidence_id, TEST_USERS["compliance_headers"]))


def setup_configured_system(enforcement: str = "ENFORCED") -> dict:
    return _ok(api_client.create_system_config(
        create_system_config_payload(database_invariant_enforcement=enforcement),
        TEST_USERS["admin_headers"],
    ))


def issue_regulatory_freeze(firm_id: str, detail: str = "Emergency suspension pending examination") -> dict:
    return _ok(api_client.issue_admin_action(
        create_admin_action_payload(firm_id, admin_action_kind="REGULATORY_FREEZE",
                                    admin_action_detail=detail),
        TEST_USERS["admin_headers"],
    ))


# ══════════════════════════════════════════════════════════════════════════════
# Tier 4 — Accumulation / threshold targeting
# ══════════════════════════════════════════════════════════════════════════════

def setup_household_at_basis(target_basis_cents: int, entitlement_codes=("BILLING",),
                             household_name: str = None, account_number: str = "RIA-103001",
                             householding_consent: str = "OP_IN", account_type: str = "INDIVIDUAL",
                             start_number: int = 0):
    """One household whose single account's fee basis is exactly ``target_basis_cents``.

    Used for boundary work: build the household at THRESHOLD - 1 next to one built
    at the threshold so both are compared under identical conditions.
    Returns (firm, agreement, household, account).
    """
    firm, agreement, household, accounts = setup_funded_household(
        entitlement_codes=entitlement_codes,
        account_specs=[{
            "basis_cents": target_basis_cents,
            "account_number": account_number,
            "account_type": account_type,
            "householding_consent": householding_consent,
        }],
        household_name=household_name,
        start_number=start_number,
    )
    return firm, agreement, household, accounts[0]


def setup_two_households_fee_tier_boundary(high_cents: int = 250_000_000,
                                           low_cents: int = 249_999_999):
    """Firm with two households: one exactly at ``high_cents``, one one cent below.

    Returns a dict with firm, agreement, high household/account and low household/account.
    """
    firm, agreement, high_household, high_account = setup_household_at_basis(
        high_cents, account_number="RIA-103001",
    )
    low_household = setup_household(firm["id"], household_name=DEFAULTS["SECOND_HOUSEHOLD_NAME"])
    low_account = open_account(low_household["id"], firm["id"], "RIA-103002")
    quantity, price = lot_for_basis(low_cents)
    credit_lot_position(
        low_account["id"], firm["id"], quantity_micros=quantity,
        valuation_price_micros=price, sent_cost_basis_cents=low_cents,
    )
    return {
        "firm": firm, "agreement": agreement,
        "high_household": refetch_household(high_household["id"]), "high_account": refetch_account(high_account["id"]),
        "low_household": refetch_household(low_household["id"]), "low_account": refetch_account(low_account["id"]),
    }


def setup_account_at_periodic_limit_consumption(limit_cents: int = 500_000,
                                               accepted_amounts=(200_000, 200_000),
                                               pending_amount_cents: int = None):
    """Account with a VERIFIED instruction already carrying a consumed total.

    Each accepted amount is authorized end to end so ``consumed_period_cents``
    reflects the sum of the accepted tranches.
    Returns a dict with firm, household, account, instruction.
    """
    firm, agreement = setup_firm_with_agreement(entitlement_codes=("MONEY_MOVEMENT", "TRADING_AUTHORIZATION"))
    household = setup_household(firm["id"])
    account = open_account(household["id"], firm["id"], "RIA-107001")
    instruction = setup_verified_standing_instruction(
        account["id"], household["id"], periodic_limit_cents=limit_cents,
    )
    # A movement that will breach the headroom once the tranches consume it must
    # be drafted while the room is still available (PRD §3.8 constrains the limit
    # at authorization, not at drafting), so it is created first and authorized last.
    pending = None
    if pending_amount_cents is not None:
        pending = setup_submitted_movement(
            account["id"], instruction["id"], amount_cents=pending_amount_cents,
            authorization_note="Client confirmed 2026-09-01 later tranche",
        )
    for index, amount in enumerate(accepted_amounts):
        movement = setup_submitted_movement(
            account["id"], instruction["id"], amount_cents=amount,
            authorization_note=f"Client confirmed 2026-09-01 tranche {index + 1}",
        )
        _ok(authorize_movement_as_client(movement["id"], household["id"], movement=movement))
    instruction = refetch_instruction(instruction["id"])
    return {"firm": firm, "agreement": agreement, "household": household,
            "account": account, "instruction": instruction,
            "pending_movement": pending}


def setup_billing_ready_household(basis_cents: int = 200_000_000,
                                  entitlement_codes=("BILLING",),
                                  account_number: str = "RIA-101001",
                                  household_name: str = None):
    """Firm + household + one OPEN account funded to ``basis_cents``, ready for billing."""
    return setup_funded_household(
        entitlement_codes=entitlement_codes,
        account_specs=[{"basis_cents": basis_cents, "account_number": account_number}],
        household_name=household_name,
    )


def settle_billing_run(firm_id: str, household_id: str, stated_invoice_cents: int,
                       period_start: str = Q4_PERIOD_START, period_end: str = Q4_PERIOD_END,
                       fee_variant: str = "HOUSEHOLD_AGGREGATED", raw: bool = False):
    response = api_client.create_billing_run(
        create_billing_run_payload(
            firm_id, household_id, period_start_date=period_start, period_end_date=period_end,
            fee_variant_used=fee_variant, stated_invoice_cents=stated_invoice_cents,
        ),
        TEST_USERS["advisor_ops_headers"],
    )
    return response if raw else _ok(response)


def setup_household_with_two_accounts(entitlement_codes=("BILLING",),
                                      basis_by_account=(200_000_000, 120_000_000),
                                      account_numbers=("RIA-100001", "RIA-100002")):
    """Household hosting two OPEN billable accounts with the given fee bases."""
    specs = [
        {"basis_cents": basis, "account_number": number}
        for basis, number in zip(basis_by_account, account_numbers)
    ]
    return setup_funded_household(entitlement_codes=entitlement_codes, account_specs=specs)


def setup_firm_with_relinkable_households(entitlement_codes=("BILLING",)):
    """HH-1 hosting two funded accounts plus an empty HH-2, with enforcement turned on.

    Returns a dict with firm, agreement, source household, destination household,
    and the two funded accounts.
    """
    firm, agreement, household, accounts = setup_funded_household(
        entitlement_codes=entitlement_codes,
        account_specs=[
            {"basis_cents": 200_000_000, "account_number": "RIA-100001"},
            {"basis_cents": 120_000_000, "account_number": "RIA-100002"},
        ],
    )
    destination = setup_household(firm["id"], household_name=DEFAULTS["SECOND_HOUSEHOLD_NAME"])
    setup_configured_system("ENFORCED")
    _ok(api_client.evaluate_invariants({"firm_id": firm["id"]}, TEST_USERS["custody_officer_headers"]))
    return {"firm": firm, "agreement": agreement, "household": household,
            "destination": destination, "accounts": accounts}


def setup_model_cycle_scenario(entitlement_codes=("MODEL_MANAGEMENT", "BILLING"),
                               account_number: str = "RIA-700001"):
    """Firm + one OPEN account + a DRAFT model whose target lines already sum to 10000."""
    firm, agreement = setup_firm_with_agreement(entitlement_codes=entitlement_codes)
    household = setup_household(firm["id"])
    account = open_account(household["id"], firm["id"], account_number)
    model = _ok(api_client.create_model(
        create_model_payload(firm["id"], model_name="Core Balanced"), TEST_USERS["advisor_ops_headers"]
    ))
    _ok(api_client.create_model_target(
        model["id"], create_model_target_payload(symbol="VTI", target_weight_bps=6000),
        TEST_USERS["advisor_ops_headers"],
    ))
    _ok(api_client.create_model_target(
        model["id"], create_model_target_payload(symbol="BND", target_weight_bps=4000),
        TEST_USERS["advisor_ops_headers"],
    ))
    return firm, agreement, household, account, refetch_model(model["id"])


def setup_deficient_firm(requirement_code: str = "SURPRISE_EXAMINATION",
                         entitlement_codes=("MODEL_MANAGEMENT", "DATA_FEED")):
    """Firm whose posture is LIMITED because one critical evidence row is DEFICIENT.

    Returns (firm, agreement, evidence).
    """
    firm, agreement = setup_firm_with_agreement(entitlement_codes=entitlement_codes)
    evidence = setup_custody_evidence(firm["id"], requirement_code=requirement_code,
                                      critical=True, submit_as="default")
    _ok(api_client.reject_custody_evidence(
        evidence["id"], {"deficiency_reason_code": "MISSING_SAMPLE_SELECTION_METHODOLOGY"},
        TEST_USERS["compliance_headers"], row=evidence,
    ))
    return firm, agreement, refetch_evidence(evidence["id"])


def setup_multi_hop_cascade_scenario():
    """Model ACTIVE, a live POSITIONS feed and a critical SUBMITTED evidence row.

    Rejecting the evidence is what drives the posture cascade under test.
    Returns a dict with the firm, model, feed and evidence.
    """
    firm, agreement = setup_firm_with_agreement(
        entitlement_codes=("MODEL_MANAGEMENT", "DATA_FEED", "BILLING")
    )
    household = setup_household(firm["id"])
    account = open_account(household["id"], firm["id"], "RIA-800001")
    model = setup_approved_model(firm["id"], targets=(("VTI", 10000),))
    assign_model(account["id"], model["id"], account=refetch_account(account["id"]))
    _ok(api_client.activate_model(
        model["id"], EMPTY, TEST_USERS["committee_chair_headers"], row=refetch_model(model["id"])
    ))
    feed = _ok(api_client.create_data_feed(
        create_data_feed_payload(firm["id"]), TEST_USERS["advisor_ops_headers"]
    ))
    _ok(api_client.provision_data_feed(
        feed["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=feed
    ))
    # Raised last: submission drops the posture to LIMITED, which retires the
    # MODEL_MANAGEMENT entitlement — so it must not precede the model activation.
    evidence = setup_custody_evidence(
        firm["id"], requirement_code="QUALIFIED_CUSTODIAN", critical=True, submit_as="default"
    )
    return {
        "firm": firm, "agreement": agreement, "household": household, "account": account,
        "model": refetch_model(model["id"]),
        "feed": refetch_feed(firm["id"], feed["id"]),
        "evidence": evidence,
    }


def setup_supersession_scenario():
    """Firm with agreement A executed, a MODEL_MANAGEMENT entitlement on A, and
    a second agreement B submitted and awaiting countersignature.

    The entitlement on A is what the supersession cascade revokes, so no further
    authority is claimed on B — PRD §3.2 refuses a sibling GRANTED duplicate, and
    a claim against B is refused until B becomes the current agreement.
    Returns a dict with the firm, agreement A, agreement B (PENDING_SIGNATURE)
    and a DRAFT model.
    """
    firm, agreement_a = setup_firm_with_agreement(entitlement_codes=("MODEL_MANAGEMENT",))
    agreement_b_draft = _ok(api_client.create_custody_agreement(
        firm["id"], create_custody_agreement_payload(adviser_crd_number=firm["crd_number"]),
        TEST_USERS["advisor_ops_headers"],
    ))
    agreement_b = _ok(api_client.submit_custody_agreement(
        agreement_b_draft["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=agreement_b_draft
    ))
    model = _ok(api_client.create_model(
        create_model_payload(firm["id"], model_name="Core Balanced"), TEST_USERS["advisor_ops_headers"]
    ))
    _ok(api_client.create_model_target(
        model["id"], create_model_target_payload(symbol="VTI", target_weight_bps=10000),
        TEST_USERS["advisor_ops_headers"],
    ))
    return {"firm": firm, "agreement_a": agreement_a, "agreement_b_draft": agreement_b,
            "model": refetch_model(model["id"])}


def setup_account_in_basis_review(account_number: str = "RIA-110001"):
    """An OPEN account whose transfer sits in BASIS_REVIEW because one lot has no basis.

    Returns a dict with firm, household, account, transfer and lots.
    """
    firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
    household = setup_household(firm["id"])
    account = open_account(household["id"], firm["id"], account_number)
    transfer = _ok(api_client.create_asset_transfer(
        create_asset_transfer_payload(account["id"], firm["id"], method="ACAT"),
        TEST_USERS["advisor_ops_headers"],
    ))
    lots = [
        _ok(api_client.create_transfer_lot(transfer["id"], create_transfer_lot_payload(
            symbol="VTI", quantity_micros=4_000_000_000, sent_cost_basis_cents=90_000_000,
            lot_inventory_date="2019-01-02T00:00:00Z", valuation_price_micros=250_000_000,
        ), TEST_USERS["advisor_ops_headers"])),
        _ok(api_client.create_transfer_lot(transfer["id"], create_transfer_lot_payload(
            symbol="BND", quantity_micros=2_000_000_000, sent_cost_basis_cents=None,
            lot_inventory_date="2021-07-07T00:00:00Z", valuation_price_micros=90_000_000,
        ), TEST_USERS["advisor_ops_headers"])),
    ]
    transfer = _ok(api_client.transfer_out(
        transfer["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=transfer
    ))
    transfer = _ok(api_client.mark_received(
        transfer["id"], EMPTY, TEST_USERS["custody_officer_headers"], row=transfer
    ))
    return {"firm": firm, "agreement": agreement, "household": household,
            "account": account, "transfer": transfer, "lots": lots}


# ══════════════════════════════════════════════════════════════════════════════
# Tier 5 — Finalization / terminal-state targeting
# ══════════════════════════════════════════════════════════════════════════════

def setup_frozen_firm(firm_id: str = None, household_name: str = "Blocked Household"):
    """Firm driven FROZEN by an ACTIVE regulatory-freeze admin action.

    The household (if any) is opened while the firm is still writable, because a
    frozen firm refuses every write outside the two exempt capabilities.
    """
    if firm_id is None:
        firm, agreement = setup_firm_with_agreement()
    else:
        firm, agreement = refetch_firm(firm_id), None
    household = None
    if household_name:
        household = setup_household(firm["id"], household_name=household_name)
    action = issue_regulatory_freeze(firm["id"])
    return {"firm": refetch_firm(firm["id"]), "agreement": agreement,
            "admin_action": action, "household": household}


def setup_account_at_evidence_ceiling(requirement_code: str = "SURPRISE_EXAMINATION"):
    """A critical evidence row driven to the four-round correction ceiling.

    Three SUBMITTED -> DEFICIENT -> SUBMITTED cycles leave evidence_round_number 3;
    the fourth rejection takes it to the ceiling of 4.
    Returns a dict with firm and evidence.
    """
    firm, agreement = setup_firm_with_agreement()
    evidence = setup_custody_evidence(firm["id"], requirement_code=requirement_code, critical=True)
    evidence = _ok(api_client.submit_custody_evidence(
        evidence["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=evidence
    ))
    # One initial submission, then three SUBMITTED -> DEFICIENT -> SUBMITTED rounds
    # leave evidence_round_number at 3; the fourth rejection reaches the ceiling.
    for _ in range(3):
        evidence = _ok(api_client.reject_custody_evidence(
            evidence["id"], {"deficiency_reason_code": "MISSING_SAMPLE_SELECTION_METHODOLOGY"},
            TEST_USERS["compliance_headers"], row=evidence,
        ))
        evidence = _ok(api_client.resubmit_custody_evidence(
            evidence["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=evidence
        ))
    evidence = _ok(api_client.reject_custody_evidence(
        evidence["id"], {"deficiency_reason_code": "MISSING_SAMPLE_SELECTION_METHODOLOGY"},
        TEST_USERS["compliance_headers"], row=evidence,
    ))
    return {"firm": refetch_firm(firm["id"]), "agreement": agreement,
            "evidence": refetch_evidence(evidence["id"])}


def setup_terminated_agreement_scenario():
    """A TERMINATED agreement on a firm with no OPEN accounts.

    Returns a dict with the firm and the terminated agreement.
    """
    firm, agreement = setup_firm_with_agreement()
    terminated = _ok(api_client.terminate_custody_agreement(
        firm["id"], agreement["id"], EMPTY, TEST_USERS["custody_officer_headers"],
        row=refetch_agreement(agreement["id"]),
    ))
    return {"firm": refetch_firm(firm["id"]), "agreement": terminated}


def setup_revoked_entitlement_scenario(entitlement_code: str = "MODEL_MANAGEMENT"):
    """A firm whose single entitlement has been revoked through the sanctioned path.

    The explicit revoke path runs from SUSPENDED, so the entitlement is first
    driven SUSPENDED by a posture drop and then revoked by the compliance function.
    Returns a dict with the firm, agreement and entitlement.
    """
    firm, agreement = setup_firm_with_agreement(entitlement_codes=(entitlement_code,))
    evidence = setup_custody_evidence(firm["id"], requirement_code="SURPRISE_EXAMINATION", critical=True,
                                      submit_as="default")
    _ok(api_client.reject_custody_evidence(
        evidence["id"], {"deficiency_reason_code": "REVIEW_SCOPE_MISMATCH"},
        TEST_USERS["compliance_headers"], row=evidence,
    ))
    entitlements = _ok(api_client.list_firm_entitlements(
        firm["id"], TEST_USERS["compliance_headers"]
    ))
    entitlement = entitlements[0]
    revoked = _ok(api_client.revoke_entitlement(
        entitlement["id"], EMPTY, TEST_USERS["compliance_headers"], row=entitlement
    ))
    return {"firm": refetch_firm(firm["id"]), "agreement": agreement, "entitlement": revoked}


def setup_household_with_credits(basis_cents: int = 200_000_000,
                                credit_amounts=(300_000, 700_000),
                                account_number: str = "RIA-101001"):
    """Household funded to ``basis_cents`` with the given available fee credits issued.

    Returns a dict with firm, household, account and the issued credits.
    """
    firm, agreement, household, accounts = setup_billing_ready_household(
        basis_cents=basis_cents, account_number=account_number,
    )
    credits = []
    for amount in credit_amounts:
        credits.append(_ok(api_client.create_fee_credit(
            household["id"], create_fee_credit_payload(credit_cents=amount),
            TEST_USERS["custody_officer_headers"],
        )))
    return {"firm": firm, "agreement": agreement, "household": household,
            "account": accounts[0], "credits": credits}


def setup_listed_account(account_number: str = "RIA-108001",
                         quantity_micros: int = 4_000_000_000,
                         valuation_price_micros: int = 250_000_000,
                         sent_cost_basis_cents: int = 90_000_000):
    """An OPEN account holding one credited lot, ready for the listing dimension."""
    firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
    household = setup_household(firm["id"])
    account = open_account(household["id"], firm["id"], account_number)
    credit_lot_position(
        account["id"], firm["id"], quantity_micros=quantity_micros,
        valuation_price_micros=valuation_price_micros,
        sent_cost_basis_cents=sent_cost_basis_cents,
    )
    return {"firm": firm, "agreement": agreement, "household": household,
            "account": refetch_account(account["id"])}


def setup_account_with_frozen_block(account_numbers=("RIA-104001", "RIA-104002")):
    """An EXECUTED block whose two targeted accounts are then frozen.

    Returns a dict with the firm, model, accounts and the executed block.
    """
    firm, agreement = setup_firm_with_agreement(
        entitlement_codes=("TRADING_AUTHORIZATION", "MODEL_MANAGEMENT")
    )
    household = setup_household(firm["id"])
    accounts = [open_account(household["id"], firm["id"], number) for number in account_numbers]
    model = setup_approved_model(firm["id"], targets=(("VTI", 10000),))
    block = setup_executed_block(
        firm["id"], model["id"],
        allocations=[(accounts[0]["id"], 250_000_000, 1), (accounts[1]["id"], 250_000_000, 2)],
        executed_share_micros=500_000_000,
    )
    for account in accounts:
        _ok(api_client.freeze_account(
            account["id"], EMPTY, TEST_USERS["compliance_headers"], row=refetch_account(account["id"])
        ))
    return {"firm": firm, "agreement": agreement, "household": household,
            "accounts": [refetch_account(a["id"]) for a in accounts], "model": model,
            "block": refetch_block(block["id"])}

# ══════════════════════════════════════════════════════════════════════════════
# Scenario helpers shared across the transfer, block and money-movement families
# ══════════════════════════════════════════════════════════════════════════════

def setup_transfer_variant_pair():
    """Two accounts receive the identical two-lot payload by different methods.

    The graded path is an ACAT delivery and the ungraded path a DIRECT_ROLLOVER,
    so the transfer method is the only difference between the two carryovers.
    Returns a dict with the firm, household, both accounts and both transfers.
    """
    firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
    household = setup_household(firm["id"])
    graded_account = open_account(household["id"], firm["id"], "RIA-200001")
    rollover_account = open_account(household["id"], firm["id"], "RIA-200002")

    lot_payloads = [
        dict(symbol="VTI", quantity_micros=4_000_000_000, sent_cost_basis_cents=1_200_000,
             lot_inventory_date="2020-01-02T00:00:00Z", valuation_price_micros=250_000_000),
        dict(symbol="BND", quantity_micros=2_000_000_000, sent_cost_basis_cents=2_400_000,
             lot_inventory_date="2027-01-02T00:00:00Z", valuation_price_micros=90_000_000),
    ]
    graded_transfer, graded_lots = _receive_transfer(
        graded_account["id"], firm["id"], "ACAT", lot_payloads,
        delivering_firm_name="Prior Custodian LLC",
    )
    rollover_transfer, rollover_lots = _receive_transfer(
        rollover_account["id"], firm["id"], "DIRECT_ROLLOVER", lot_payloads,
        delivering_firm_name="Legacy Rollover Services",
    )
    return {
        "firm": firm, "agreement": agreement, "household": household,
        "graded_account": graded_account, "rollover_account": rollover_account,
        "graded_transfer": graded_transfer, "rollover_transfer": rollover_transfer,
        "graded_lots": graded_lots, "rollover_lots": rollover_lots,
    }


def _receive_transfer(account_id: str, firm_id: str, method: str, lot_payloads,
                      delivering_firm_name: str = None):
    """Open a transfer, add its lots, submit it and record receipt."""
    payload = create_asset_transfer_payload(account_id, firm_id, method=method)
    if delivering_firm_name is not None:
        payload["delivering_firm_name"] = delivering_firm_name
    transfer = _ok(api_client.create_asset_transfer(payload, TEST_USERS["advisor_ops_headers"]))
    for payload in lot_payloads:
        _ok(api_client.create_transfer_lot(
            transfer["id"], create_transfer_lot_payload(**payload),
            TEST_USERS["advisor_ops_headers"],
        ))
    transfer = _ok(api_client.transfer_out(
        transfer["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=transfer
    ))
    transfer = _ok(api_client.mark_received(
        transfer["id"], EMPTY, TEST_USERS["custody_officer_headers"], row=transfer
    ))
    lots = _ok(api_client.list_transfer_lots(
        transfer["id"], TEST_USERS["advisor_ops_headers"]
    ))
    return transfer, lots


def setup_three_way_allocation_scenario(executed_share_micros=1_000_000_000,
                                        requests=(333_000_000, 333_000_000, 334_000_001),
                                        allocation_ranks=(1, 2, 3),
                                        execution_price_micros=52_375_001,
                                        allocate=False, targets=(("VTI", 6000), ("BND", 4000))):
    """Firm + household + three OPEN accounts + approved model assigned to all three
    + an EXECUTED block carrying the requested three-way split.

    Returns a dict with the firm, household, the three accounts, the model and the block.
    """
    firm, agreement, household, accounts, model = setup_block_model_scenario()
    block = setup_executed_block(
        firm["id"], model["id"],
        allocations=[(accounts[i]["id"], requests[i], allocation_ranks[i]) for i in range(len(requests))],
        executed_share_micros=executed_share_micros,
        execution_price_micros=execution_price_micros,
        allocate=allocate,
    )
    return {"firm": firm, "agreement": agreement, "household": household,
            "accounts": accounts, "model": model, "block": block}


def allocation_rows(block_id: str):
    return _ok(api_client.list_block_allocations(block_id, TEST_USERS["advisor_ops_headers"]))


def setup_withholding_dominant_rule_scenario():
    """An IRA account on an unverified instruction with a drafted movement that
    carries a blank authorization note.

    Returns a dict with the firm, household, IRA account, instruction and movement.
    """
    firm, agreement = setup_firm_with_agreement(
        entitlement_codes=("TRADING_AUTHORIZATION", "MONEY_MOVEMENT")
    )
    household = setup_household(firm["id"])
    account = open_account(household["id"], firm["id"], "RIA-400001", account_type="IRA")
    credit_lot_position(account["id"], firm["id"], method="DIRECT_ROLLOVER",
                        sent_cost_basis_cents=90_000_000, lot_inventory_date="2019-06-01T00:00:00Z")
    instruction = setup_verified_standing_instruction(
        account["id"], household["id"], periodic_limit_cents=500_000, verify=False,
    )
    movement = setup_submitted_movement(
        account["id"], instruction["id"], amount_cents=100_000, authorization_note="",
    )
    return {"firm": firm, "agreement": agreement, "household": household,
            "account": account, "instruction": instruction, "movement": movement}


def setup_chronological_ordering_scenario():
    """A transfer whose newer-dated lot is posted before its older-dated lot.

    Grading must follow lot_inventory_date, not posting order, so the older
    VTI lot grades HIGH and the newer BND lot MEDIUM.
    Returns a dict with the firm, household, account, transfer and its lots.
    """
    firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
    household = setup_household(firm["id"])
    account = open_account(household["id"], firm["id"], "RIA-500001")
    transfer, lots = _receive_transfer(account["id"], firm["id"], "ACAT", [
        dict(symbol="BND", quantity_micros=2_000_000_000, sent_cost_basis_cents=2_400_000,
             lot_inventory_date="2027-01-02T00:00:00Z", valuation_price_micros=90_000_000),
        dict(symbol="VTI", quantity_micros=4_000_000_000, sent_cost_basis_cents=1_200_000,
             lot_inventory_date="2020-01-02T00:00:00Z", valuation_price_micros=250_000_000),
    ])
    return {"firm": firm, "agreement": agreement, "household": household,
            "account": account, "transfer": transfer, "lots": lots}


def setup_zero_execution_block():
    """A submitted, executed block whose executed quantity and only requested
    allocation are both zero, plus a second executed block targeting two
    accounts that are then frozen.

    Returns a dict with the firm, model, the zero block and the frozen-target block.
    """
    firm, agreement = setup_firm_with_agreement(
        entitlement_codes=("TRADING_AUTHORIZATION", "MODEL_MANAGEMENT")
    )
    household = setup_household(firm["id"])
    accounts = [open_account(household["id"], firm["id"], number)
                for number in ("RIA-104001", "RIA-104002")]
    model = setup_approved_model(firm["id"], targets=(("VTI", 10000),))

    zero_block = setup_executed_block(
        firm["id"], model["id"], symbol="BND",
        allocations=[(accounts[0]["id"], 0, 1)],
        executed_share_micros=0, allocate=False,
    )
    frozen_block = setup_executed_block(
        firm["id"], model["id"],
        allocations=[(accounts[0]["id"], 250_000_000, 1), (accounts[1]["id"], 250_000_000, 2)],
        executed_share_micros=500_000_000, allocate=False,
    )
    for account in accounts:
        _ok(api_client.freeze_account(
            account["id"], EMPTY, TEST_USERS["compliance_headers"], row=refetch_account(account["id"])
        ))
    return {"firm": firm, "agreement": agreement, "household": household,
            "accounts": [refetch_account(a["id"]) for a in accounts],
            "model": model, "zero_block": refetch_block(zero_block["id"]),
            "frozen_block": refetch_block(frozen_block["id"])}


def setup_stale_model_rebalance_scenario():
    """An APPROVED model that has already been rebalanced once, plus the stale
    version a client would still be holding.

    Returns a dict with the firm, the model and the stale version.
    """
    firm, agreement, household, account, model = setup_model_cycle_scenario()
    approved = _ok(api_client.approve_model(
        model["id"], EMPTY, TEST_USERS["committee_chair_headers"], row=refetch_model(model["id"])
    ))
    stale_version = approved["version"]
    _ok(api_client.rebalance_model(
        model["id"], {"expected_model_portfolio_version": stale_version},
        TEST_USERS["advisor_ops_headers"], row=approved,
    ))
    return {"firm": firm, "agreement": agreement, "model": refetch_model(model["id"]),
            "stale_version": stale_version}


def setup_idempotent_batch_scenario(batch_size: int = 2):
    """A firm with a household and a dispatchable ACCOUNTS batch of the given size."""
    firm, agreement = setup_firm_with_agreement()
    household = setup_household(firm["id"])
    items = [
        {"household_id": household["id"], "account_number": f"RIA-11800{index + 1}",
         "account_type": "INDIVIDUAL", "householding_consent": "OP_IN"}
        for index in range(batch_size)
    ]
    batch = _ok(api_client.create_onboarding_batch(
        {"firm_id": firm["id"], "batch_kind": "ACCOUNTS", "items": items},
        TEST_USERS["advisor_ops_headers"],
    ))
    return {"firm": firm, "agreement": agreement, "household": household, "batch": batch}


def setup_throttled_feed_scenario():
    """A firm with a live POSITIONS feed and a critical evidence row awaiting review.

    Returns a dict with the firm, the account, the feed and the evidence row.
    """
    firm, agreement = setup_firm_with_agreement(
        entitlement_codes=("DATA_FEED", "TRADING_AUTHORIZATION")
    )
    household = setup_household(firm["id"])
    account = open_account(household["id"], firm["id"], "RIA-110001")
    feed = _ok(api_client.create_data_feed(
        create_data_feed_payload(firm["id"]), TEST_USERS["advisor_ops_headers"]
    ))
    _ok(api_client.provision_data_feed(
        feed["id"], EMPTY, TEST_USERS["advisor_ops_headers"], row=feed
    ))
    evidence = setup_custody_evidence(
        firm["id"], requirement_code="SURPRISE_EXAMINATION", critical=True, submit_as="default"
    )
    return {"firm": firm, "agreement": agreement, "household": household, "account": account,
            "feed": refetch_feed(firm["id"], feed["id"]), "evidence": evidence}