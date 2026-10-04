"""Service contracts: the cyclic ACTIVE/RENEWAL_DUE renewal machine, the
renewal window gate, optimistic concurrency on renew, the one-live-contract
rule, and the early-termination credit cascade.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    CLOCK_START_UTC,
    DEFAULT_WINDOW_END,
    ApiErrorId,
    api_client,
    contract_renew_payload,
    create_account,
    create_catalog_item,
    create_order,
    create_service_contract,
    get_account,
    get_order,
    get_service_contract,
    plus_days,
    plus_months,
    renew_service_contract,
    same_instant,
    set_clock,
    setup_instrument_with_contract,
    cancel_service_contract,
    validate_error,
    validate_success,
)

_RENEWAL_DUE_INSTANT = plus_days(plus_months(CLOCK_START_UTC, 11), 14)  # 2027-08-15
_CANCEL_INSTANT = plus_months(CLOCK_START_UTC, 6)  # 2027-03-01T00:00:00Z


def _gold_contract_on_installed_instrument():
    return setup_instrument_with_contract(tier="GOLD")


def test_contract_derives_renewal_due_without_version_bump(api):
    """PRD section 3.4: "A contract's `status` derives at read from the
    logical clock, in this order: `CANCELLED` once `cancelled_at` is set;
    otherwise `EXPIRED` once the clock has reached `end_date`; otherwise
    `RENEWAL_DUE` once the clock has reached the instant 30 days before
    `end_date`; otherwise `ACTIVE`. Derivation never increments the
    contract's `version`."

    Design: Difficulty/non_linear_state_machine/service_contract_renewal_cycle
    """
    account, instrument, contract = _gold_contract_on_installed_instrument()
    created_version = contract["version"]

    at_start = get_service_contract(contract)
    assert at_start["status"] == "ACTIVE"
    assert at_start["version"] == created_version

    set_clock(_RENEWAL_DUE_INSTANT)  # 2027-08-15, past end_date - 30 days
    due = get_service_contract(contract)
    assert due["status"] == "RENEWAL_DUE", (
        "clock at 2027-08-15 is past the 30-day renewal window of a "
        "2027-09-01 end_date"
    )
    assert due["version"] == created_version, (
        "the derived RENEWAL_DUE transition never bumps version"
    )


def test_contract_renew_closes_cycle_and_extends_term(api):
    """PRD section 3.4: "While a contract reads `RENEWAL_DUE`, an
    `AccountManager` may renew it: `end_date` extends by 12 months,
    `renewal_count` increments by 1, the contract's `version` increments by 1,
    and the derived status returns to `ACTIVE` on the next read."

    Design: Difficulty/non_linear_state_machine/service_contract_renewal_cycle
    """
    account, instrument, contract = _gold_contract_on_installed_instrument()
    created_version = contract["version"]
    set_clock(_RENEWAL_DUE_INSTANT)

    renewed = renew_service_contract(contract, created_version)
    assert renewed["status"] == "ACTIVE", "the cycle closes back to ACTIVE"
    assert same_instant(renewed["end_date"], plus_months(DEFAULT_WINDOW_END, 12)), (
        "renew extends end_date by 12 months: 2027-09-01 -> 2028-09-01"
    )
    assert renewed["renewal_count"] == 1
    assert renewed["version"] == created_version + 1

    reread = get_service_contract(contract)
    assert reread["status"] == "ACTIVE"


def test_contract_renew_before_window_rejected(api):
    """PRD section 3.4: "Renewing in any other state fails with
    `ERR_RENEWAL_WINDOW_CLOSED`" and PRD section 2.9: "a renewal attempted
    outside its renewal window reports `ERR_RENEWAL_WINDOW_CLOSED` even when
    the supplied version is also stale."

    Design: Corner/state_machines/contract_renew_before_window_rejected
    """
    account, instrument, contract = _gold_contract_on_installed_instrument()
    response = api_client.renew_service_contract(
        contract["id"],
        contract_renew_payload(contract["version"]),
        headers=ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)
    fresh = get_service_contract(contract)
    assert same_instant(fresh["end_date"], DEFAULT_WINDOW_END)
    assert fresh["renewal_count"] == 0


def test_contract_renew_stale_version_rejected(api):
    """PRD section 2.7: "If the supplied value does not equal the resource's
    current `version`, the request is rejected with `ERR_STALE_VERSION` and
    HTTP status 412: a prior renewal has already extended the coverage window
    and advanced the version, so applying a second renewal against the stale
    view would double-extend the term, and the stale request is refused
    instead."

    Design: Corner/cross_cutting_layers/contract_renew_stale_version_rejected
    """
    account, instrument, contract = _gold_contract_on_installed_instrument()
    set_clock(_RENEWAL_DUE_INSTANT)  # contract now reads RENEWAL_DUE
    stale = contract["version"] - 1
    response = api_client.renew_service_contract(
        contract["id"], contract_renew_payload(stale), headers=ACCOUNT_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    fresh = get_service_contract(contract)
    assert same_instant(fresh["end_date"], DEFAULT_WINDOW_END), "end_date must not move"
    assert fresh["renewal_count"] == 0


def test_second_contract_same_instrument_rejected(api):
    """PRD section 3.4: "An instrument supports at most one live contract:
    when it already carries a contract reading `ACTIVE` or `RENEWAL_DUE`,
    creation fails with `ERR_CONTRACT_ALREADY_ACTIVE`."

    Design: Corner/validations/second_contract_same_instrument_rejected
    """
    account, instrument, first = setup_instrument_with_contract(tier="BRONZE")
    response = api_client.create_service_contract(
        {"instrument_id": instrument["id"], "tier": "GOLD",
         "start_date": CLOCK_START_UTC, "end_date": DEFAULT_WINDOW_END},
        headers=ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_ALREADY_ACTIVE)

    cancel_service_contract(first)
    replacement = api_client.create_service_contract(
        {"instrument_id": instrument["id"], "tier": "GOLD",
         "start_date": CLOCK_START_UTC, "end_date": DEFAULT_WINDOW_END},
        headers=ACCOUNT_MANAGER,
    )
    validate_success(replacement, 201)


def _platinum_cancel_scene():
    """PLATINUM contract on an installed instrument, one DRAFT order, clock at
    2027-03-01 - six full months before the 2027-09-01 end_date."""
    account, instrument, contract = setup_instrument_with_contract(
        tier="PLATINUM"
    )
    item = create_catalog_item(base_price_cents=100, stock_on_hand=10)
    draft = create_order(account, [ {"sku": item["sku"], "quantity": 1} ])
    set_clock(_CANCEL_INSTANT)
    return account, contract, draft


def test_contract_cancel_posts_fee_and_flips_credit(api):
    """PRD section 3.4: "Cancelling a `PLATINUM` contract, at 800000 cents per
    month, on 2027-03-01 with an `end_date` of 2027-09-01 therefore leaves six
    full months — March, April, May, June, July, and August — and posts a fee
    of 800000 times 6 times 0.5, which is 2400000 cents." and "Posting the
    fee triggers the credit evaluation of §2.8: when the resulting balance is
    strictly greater than 2000000 cents the account flips to `HOLD`".

    Design: Difficulty/transitive_cascade/contract_cancel_credit_hold_cancels_drafts
    """
    account, contract, draft = _platinum_cancel_scene()
    cancelled = cancel_service_contract(contract)
    assert cancelled["status"] == "CANCELLED"

    fresh = get_account(account)
    assert fresh["outstanding_balance_cents"] == 2400000, (
        "link 1: the termination fee is 800000 x 6 months x 0.5"
    )
    assert fresh["credit_status"] == "HOLD", (
        "link 2: 2400000 is strictly greater than the 2000000 credit line"
    )


def test_contract_cancel_hold_cancels_draft_orders(api):
    """PRD section 2.8: "At the moment an account flips to `HOLD`, every order
    of that account still in `DRAFT` status is cancelled to `CANCELLED`, and
    each such cancellation increments that order's `version` by 1."

    Design: Difficulty/transitive_cascade/contract_cancel_credit_hold_cancels_drafts
    """
    account, contract, draft = _platinum_cancel_scene()
    draft_version = draft["version"]
    cancel_service_contract(contract)

    after = get_order(draft)
    assert after["status"] == "CANCELLED", (
        "link 3: the HOLD transition cancels every DRAFT order of the account"
    )
    assert after["version"] == draft_version + 1
