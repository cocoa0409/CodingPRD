"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the server is restarted against an empty database before
each test. Setup steps use ``get_success_data`` so a broken precondition
surfaces as a clear "Setup ... failed" assertion rather than a downstream
field error.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import ApiClient, api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_agreement_payload,
    create_application_payload,
    create_balance_payload,
    create_credit_program_payload,
    create_partner_payload,
    create_promo_transaction_payload,
    create_settlement_batch_payload,
    create_transaction_payload,
)
from .test_users import TEST_USERS, make_cardholder_headers

ADMIN = TEST_USERS["program_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
SERVICE = TEST_USERS["cardholder_service_headers"]
APPLICANT = TEST_USERS["applicant_headers"]
COBRAND = TEST_USERS["co_brand_issuer_headers"]

_SEQUENCE = {"n": 0}


def _client(api):
    return api if api is not None else api_client


def reset_clock(api=None, to_iso8601="2026-09-01T00:00:00Z"):
    return get_success_data(_client(api).set_clock(to_iso8601, ADMIN))


def advance_clock(api=None, days=1):
    return get_success_data(_client(api).advance_clock(days, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------

def onboard_partner(api=None, name=None, code=None, loyalty_link_enabled=None):
    """Create a RetailPartner and return it."""
    _SEQUENCE["n"] += 1
    payload = create_partner_payload(
        retailer_name=name or f"Ridge Retailer {_SEQUENCE['n']}",
        loyalty_program_code=code or f"RIDGE_{_SEQUENCE['n']}",
    )
    if loyalty_link_enabled is not None:
        payload["loyalty_link_enabled"] = loyalty_link_enabled
    return get_success_data(_client(api).create_partner(payload, ADMIN), 201)


def ensure_clock(api=None):
    return reset_clock(api)


# ---------------------------------------------------------------------------
# Tier 1 — agreement state progression
# ---------------------------------------------------------------------------

def draft_agreement(api=None, partner_id=None, **overrides):
    _SEQUENCE["n"] += 1
    payload = create_agreement_payload(partner_id, **overrides)
    return get_success_data(_client(api).create_agreement(payload, ADMIN), 201)


def open_negotiation(api=None, agreement_id=None):
    return get_success_data(_client(api).open_negotiation(agreement_id, ADMIN))


def setup_negotiation_agreement(api=None, partner_id=None, **overrides):
    """DRAFT agreement moved to NEGOTIATION. Returns (agreement, version)."""
    agreement = draft_agreement(api, partner_id, **overrides)
    neg = open_negotiation(api, agreement["id"])
    return agreement, neg["version"]


def setup_active_agreement(api=None, partner_id=None, **overrides):
    """DRAFT -> NEGOTIATION -> ACTIVE agreement. Returns the ACTIVE agreement."""
    agreement, neg_version = setup_negotiation_agreement(api, partner_id, **overrides)
    return get_success_data(
        _client(api).execute_agreement(agreement["id"], neg_version, ADMIN)
    )


def setup_partner_with_active_agreement(api=None, **overrides):
    """Partner + ACTIVE agreement. Returns (partner, agreement)."""
    partner = onboard_partner(api)
    agreement = setup_active_agreement(api, partner["id"], **overrides)
    return partner, agreement


# ---------------------------------------------------------------------------
# Tier 2 — program issuance and account acquisition
# ---------------------------------------------------------------------------

def issue_program(api=None, partner_id=None, agreement_id=None, **overrides):
    payload = create_credit_program_payload(partner_id, agreement_id, **overrides)
    return get_success_data(_client(api).create_credit_program(payload, ADMIN), 201)


def setup_program(api=None, partner_name=None, partner_code=None,
                  loyalty_link_enabled=None, **agreement_overrides):
    """Partner + ACTIVE agreement + ACTIVE program.

    Returns (partner, agreement, program).
    """
    partner = onboard_partner(api, partner_name, partner_code, loyalty_link_enabled)
    agreement = setup_active_agreement(api, partner["id"], **agreement_overrides)
    program = issue_program(api, partner["id"], agreement["id"])
    return partner, agreement, program


def _only(items, what):
    assert len(items) == 1, f"Setup: expected exactly one {what}, got {len(items)}"
    return items[0]


def issue_account(api=None, program_id=None, credit_limit_cents=None, source_channel="DIGITAL"):
    """Submit + decide an application; return the synthesized Account.

    The account is discoverable only by listing accounts on the program.
    """
    payload = create_application_payload(
        program_id,
        source_channel=source_channel,
        requested_credit_limit_cents=credit_limit_cents or TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    )
    application = get_success_data(_client(api).create_application(payload, APPLICANT), 201)
    get_success_data(_client(api).decide_application(application["id"], UNDERWRITER))
    resp = _client(api).list_accounts(ADMIN, {"program_id": program_id})
    accounts, _ = validate_paginated(resp)
    return _only(accounts, "account on program")


def setup_program_with_account(api=None, credit_limit_cents=None, **agreement_overrides):
    """Partner + agreement + program + one ACTIVE account.

    Returns (partner, agreement, program, account).
    """
    partner, agreement, program = setup_program(api, **agreement_overrides)
    account = issue_account(api, program["id"], credit_limit_cents)
    return partner, agreement, program, account


def account_headers(account_id):
    """Ownership-gated headers for the Cardholder acting on their own account."""
    return make_cardholder_headers(account_id)


# ---------------------------------------------------------------------------
# Purchases and promotional plans
# ---------------------------------------------------------------------------

def post_purchase(api=None, account_id=None, **overrides):
    payload = create_transaction_payload(account_id, **overrides)
    hdrs = make_cardholder_headers(account_id)
    return get_success_data(_client(api).create_transaction(payload, hdrs), 201)


def post_promo_purchase(api=None, account_id=None, amount_cents=120_000,
                        promo_term_months=12, **overrides):
    payload = create_promo_transaction_payload(
        account_id, amount_cents, promo_term_months, **overrides
    )
    hdrs = make_cardholder_headers(account_id)
    return get_success_data(_client(api).create_transaction(payload, hdrs), 201)


def get_plan_for_transaction(api=None, transaction_id=None):
    resp = _client(api).list_promo_plans(ADMIN, {"transaction_id": transaction_id})
    plans, _ = validate_paginated(resp)
    return _only(plans, "promo plan for transaction")


def apply_principal(api=None, account_id=None, principal_balance_cents=0,
                    balance_bucket="PRINCIPAL"):
    return get_success_data(
        _client(api).create_balance(account_id, principal_balance_cents, balance_bucket, ADMIN),
        201,
    )


def pay_account(api=None, account_id=None, payment_amount_cents=100):
    hdrs = make_cardholder_headers(account_id)
    return get_success_data(
        _client(api).post_payment(account_id, payment_amount_cents, hdrs)
    )


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_program_with_two_promo_plans(api=None, principal_balance_cents=0,
                                       credit_limit_cents=None, **agreement_overrides):
    """Program + account + a 120000/12mo plan and a 240000/6mo plan.

    Returns (partner, agreement, program, account, plan_12, plan_6).
    """
    limit = credit_limit_cents or 500_000
    partner, agreement, program, account = setup_program_with_account(
        api, credit_limit_cents=limit, **agreement_overrides
    )
    # The purchases are posted first, then the statement principal slice is
    # recorded — the credit check sees the balance slice either way, and this
    # order keeps both promotional purchases comfortably inside the line.
    tx_12 = post_promo_purchase(api, account["id"], 120_000, 12)
    tx_6 = post_promo_purchase(api, account["id"], 240_000, 6)
    if principal_balance_cents:
        apply_principal(api, account["id"], principal_balance_cents)
    return (partner, agreement, program, account,
            get_plan_for_transaction(api, tx_12["id"]),
            get_plan_for_transaction(api, tx_6["id"]))


def open_settlement_batch(api=None, agreement_id=None, period_start="2026-09-01T00:00:00Z",
                          period_end="2026-10-01T00:00:00Z", **overrides):
    payload = create_settlement_batch_payload(
        agreement_id, period_start, period_end, **overrides
    )
    return get_success_data(_client(api).create_settlement_batch(payload, ADMIN), 201)


def settle_window(api=None, agreement_id=None, period_start="2026-09-01T00:00:00Z",
                  period_end="2026-10-01T00:00:00Z", **overrides):
    """Open and finalize a settlement batch. Returns the SETTLED batch."""
    batch = open_settlement_batch(api, agreement_id, period_start, period_end, **overrides)
    return get_success_data(
        _client(api).finalize_settlement_batch(batch["id"], ADMIN)
    )


def setup_settled_month(api=None, principal_balance_cents=360_000):
    """Program with one account, two promo plans and one SETTLED September batch.

    Returns (partner, agreement, program, account, settled_batch).
    """
    partner, agreement, program, account, _p12, _p6 = setup_program_with_two_promo_plans(
        api, principal_balance_cents=principal_balance_cents
    )
    batch = settle_window(api, agreement["id"])
    return partner, agreement, program, account, batch


def program_summary(api=None, program_id=None):
    return get_success_data(_client(api).get_program_summary(program_id, ADMIN))


def bring_account_to_delinquent(api=None, account_id=None, principal_balance_cents=0,
                                due_date="2026-09-10T00:00:00Z", days=200):
    """Record principal, schedule a due date, then advance past it."""
    if principal_balance_cents:
        apply_principal(api, account_id, principal_balance_cents)
    get_success_data(_client(api).schedule_payment(account_id, due_date, ADMIN))
    advance_clock(api, days)
    return get_success_data(_client(api).get_account(account_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 3 / Tier 5 — program lifecycle, wind-down and closure
# ---------------------------------------------------------------------------

def promote_to_renewal(api=None, program_id=None, expected_version=None):
    return get_success_data(
        _client(api).open_renewal(program_id, expected_version, "RENEWAL_NEGOTIATION", ADMIN)
    )


def roll_into_winding_down(api=None, program_id=None, expected_version=None):
    """Second arm of the renewal operation: a failed round rolls into wind-down."""
    return get_success_data(
        _client(api).open_renewal(program_id, expected_version, "WINDING_DOWN", ADMIN)
    )


def propose_transfer(api=None, program_id=None, buyer_role="RETAILER", **overrides):
    payload = {"program_id": program_id, "buyer_role": buyer_role}
    payload.update(overrides)
    return get_success_data(_client(api).create_transfer(payload, ADMIN), 201)


def accept_transfer(api=None, transfer_id=None, accepted_by_role="RETAILER", headers=None):
    return get_success_data(
        _client(api).accept_transfer(transfer_id, accepted_by_role, headers or ADMIN)
    )


def execute_transfer(api=None, transfer_id=None):
    return get_success_data(_client(api).execute_transfer(transfer_id, ADMIN))


def close_program(api=None, program_id=None, expected_version=None, headers=None):
    return get_success_data(
        _client(api).close_credit_program(program_id, expected_version, headers or ADMIN)
    )


def setup_closed_program(api=None, buyer_role="RETAILER", settle_account=True):
    """Wind a program all the way to CLOSED via a completed portfolio transfer.

    Returns (partner, agreement, program, account, transfer).
    """
    partner, agreement, program, account = setup_program_with_account(api)
    if settle_account:
        pay_account(api, account["id"], 100)
    roll_into_winding_down(api, program["id"], program["version"])
    transfer = propose_transfer(api, program["id"], buyer_role)
    accept_transfer(api, transfer["id"], buyer_role)
    transfer = execute_transfer(api, transfer["id"])
    # Executing the transfer bumps the program's version, so the closure
    # expected-version must be read back after that mutation.
    after_transfer = get_success_data(_client(api).get_credit_program(program["id"], ADMIN))
    program = close_program(api, program["id"], after_transfer["version"])
    return partner, agreement, program, account, transfer


def setup_wound_down_program_with_transfer(api=None, buyer_role="RETAILER",
                                           account_balance_cents=0, accepted=False):
    """Program in WINDING_DOWN with a PROPOSED (or accepted) transfer.

    Returns (partner, agreement, program, account, transfer).
    """
    partner, agreement, program, account = setup_program_with_account(api)
    if account_balance_cents:
        apply_principal(api, account["id"], account_balance_cents)
    winding = roll_into_winding_down(api, program["id"], program["version"])
    program["version"] = winding["version"]
    transfer = propose_transfer(api, program["id"], buyer_role)
    if accepted:
        transfer = accept_transfer(api, transfer["id"], buyer_role)
    return partner, agreement, program, account, transfer


def account_exposure_after_purchase(api=None, program_id=None,
                                    amount_cents=120_000, promo_term_months=12):
    """Helper: post one promo purchase and return (account, transaction, plan)."""
    account = issue_account(api, program_id)
    tx = post_promo_purchase(api, account["id"], amount_cents, promo_term_months)
    return account, tx, get_plan_for_transaction(api, tx["id"])