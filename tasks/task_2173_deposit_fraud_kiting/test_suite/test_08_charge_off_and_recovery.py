"""Charging off a deposit loss, referring it to recovery, and unwinding it."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    account_version,
    approve_charge_off,
    assert_charge_off,
    assert_net_bank_position,
    book_charge_off,
    create_active_account,
    post_recovery,
    propose_charge_off,
    read_account,
    read_charge_off,
    setup_approved_charge_off,
    setup_booked_charge_off,
    validate_error,
    validate_paginated,
    validate_success,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]
OPS = TEST_USERS["ops_admin_headers"]


# ===========================================================================
# Booking and reversing conserve the bank's recognised loss position
# ===========================================================================
def test_booking_a_write_off_leaves_the_net_bank_position_unchanged(api, analyst_headers):
    """PRD §3.8: "Second, the recovery-agency fee rate is selected **from
    `base_net_cents`, never from the final figure**, against two inclusive upper
    bounds: a `base_net_cents` of 100,000 cents or less takes 500 basis points, a
    `base_net_cents` above that but no more than 500,000 cents takes 350 basis
    points, and anything above 500,000 cents takes 200 basis points."
    PRD §3.8: "Booking snapshots the account's current `ledger_balance_cents` into
    `ledger_balance_before_book_cents` so that a later reversal can restore it
    exactly, then adds `net_charge_off_cents` to both `ledger_balance_cents` and
    `available_balance_cents`, sets the account's `charged_off_amount_cents` to
    `net_charge_off_cents`, and drives the account `CLOSED → CHARGED_OFF`."
    PRD §3.8: "Within the very same request, a charge-off whose
    `net_charge_off_cents` is 25,000 cents or more — $250.00, the floor below which
    agency referral costs more than it recovers — transitions
    `BOOKED → REFERRED_TO_RECOVERY`."
    PRD §2.9: "The second is the bank's recognised loss position, defined as
    `ledger_balance_cents` minus `charged_off_amount_cents`. Booking a write-off
    adds the net loss to the ledger balance and simultaneously records the same
    figure as charged off, so the net position is unchanged; reversing that booking
    restores both terms to their pre-booking values, so the net position is again
    unchanged."

    Design: Difficulty/compensating_invariant/charge_off_book_then_reverse_restores_net_bank_position_exactly
    """
    scenario = setup_approved_charge_off(
        gross_loss_cents=120000, collateral_offset_cents=20000,
        legal_name="Anouk Delacroix", tin_last4="5757",
    )
    charge_off = scenario["charge_off"]
    assert_charge_off(charge_off)
    assert charge_off["base_net_cents"] == 100000
    assert charge_off["recovery_fee_cents"] == 5000, "100000 at tier-1 500 bps"
    assert charge_off["net_charge_off_cents"] == 105000

    before = read_account(scenario["account_id"], analyst_headers)
    assert before["ledger_balance_cents"] == 0
    assert_net_bank_position(before, 0)

    booked = validate_success(api.book_charge_off(scenario["charge_off_id"], OPS))
    assert booked["status"] == "REFERRED_TO_RECOVERY", (
        "105000 is at or above the 25,000-cent referral floor, so booking refers in one request"
    )
    assert booked["ledger_balance_before_book_cents"] == 0

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["ledger_balance_cents"] == 105000
    assert account["charged_off_amount_cents"] == 105000
    assert account["lifecycle_status"] == "CHARGED_OFF"
    assert_net_bank_position(account, 0)


def test_reversing_the_booking_restores_both_terms_exactly(api, analyst_headers):
    """PRD §3.8: "A permitted reversal — from `BOOKED` or from
    `REFERRED_TO_RECOVERY` — sets `status` to `REVERSED`, stamps `reversed_at`,
    restores the account's `ledger_balance_cents` to
    `ledger_balance_before_book_cents` exactly, subtracts `net_charge_off_cents`
    from its `available_balance_cents`, zeroes its `charged_off_amount_cents`, and
    drives the account `CHARGED_OFF → CLOSED`."
    PRD §2.9: "The second is the bank's recognised loss position, defined as
    `ledger_balance_cents` minus `charged_off_amount_cents`. Booking a write-off
    adds the net loss to the ledger balance and simultaneously records the same
    figure as charged off, so the net position is unchanged; reversing that booking
    restores both terms to their pre-booking values, so the net position is again
    unchanged."

    Design: Difficulty/compensating_invariant/charge_off_book_then_reverse_restores_net_bank_position_exactly
    """
    scenario = setup_booked_charge_off(
        gross_loss_cents=120000, collateral_offset_cents=20000,
        legal_name="Anouk Delacroix", tin_last4="5757",
    )
    assert scenario["account"]["lifecycle_status"] == "CHARGED_OFF"

    reversed_charge_off = validate_success(
        api.reverse_charge_off(
            scenario["charge_off_id"],
            {"reversal_reason": "Drawer paid in full; write-off rescinded"},
            SUPERVISOR,
        )
    )
    assert reversed_charge_off["status"] == "REVERSED"

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["ledger_balance_cents"] == 0, "Restored to the pre-booking snapshot"
    assert account["charged_off_amount_cents"] == 0
    assert account["available_balance_cents"] == 0
    assert account["held_amount_cents"] == 0
    assert account["lifecycle_status"] == "CLOSED"
    assert_net_bank_position(account, 0)


# ===========================================================================
# Tiered pricing off base_net_cents
# ===========================================================================
def test_recovery_fee_tier_is_selected_from_base_net_not_the_grossed_up_total(
    api, analyst_headers
):
    """PRD §3.8: "First, `base_net_cents` is `gross_loss_cents` less
    `collateral_offset_cents`; if that is zero or negative there is nothing to
    write off and the proposal is refused with `ERR_NO_NET_LOSS` (HTTP 422)."
    PRD §3.8: "Second, the recovery-agency fee rate is selected **from
    `base_net_cents`, never from the final figure**, against two inclusive upper
    bounds: a `base_net_cents` of 100,000 cents or less takes 500 basis points, a
    `base_net_cents` above that but no more than 500,000 cents takes 350 basis
    points, and anything above 500,000 cents takes 200 basis points. Because the
    boundary comparison is inclusive, a `base_net_cents` of exactly 100,000 cents
    stays in the first tier even though the resulting total then exceeds that
    boundary."
    PRD §3.8: "Creating a proposal moves any existing charge-off on the same
    account whose `status` is `PROPOSED` to `SUPERSEDED`, and advances the
    account's `version` by 1."

    Design: Corner/calculations/charge_off_fee_tier_is_selected_from_base_net_not_from_the_grossed_up_total
    """
    scenario = create_active_account(legal_name="Tier Boundary Depositor", tin_last4="0024")

    at_boundary = propose_charge_off(
        scenario["account_id"], gross_loss_cents=100000, collateral_offset_cents=0
    )
    assert at_boundary["base_net_cents"] == 100000
    assert at_boundary["recovery_fee_cents"] == 5000, "Exactly 100000 stays in the 500 bps tier"
    assert at_boundary["net_charge_off_cents"] == 105000

    above_boundary = propose_charge_off(
        scenario["account_id"], gross_loss_cents=100001, collateral_offset_cents=0
    )
    assert above_boundary["base_net_cents"] == 100001
    assert above_boundary["recovery_fee_cents"] == 3500, (
        "100001 falls to the 350 bps tier; 100001 * 350 / 10000 = 3500.035 -> 3500"
    )
    assert above_boundary["net_charge_off_cents"] == 103501

    validate_error(
        api.create_charge_off(
            scenario["account_id"],
            {
                "gross_loss_cents": 20000,
                "collateral_offset_cents": 20000,
                "expected_account_version": account_version(scenario["account_id"]),
            },
            analyst_headers,
        ),
        ApiErrorId.ERR_NO_NET_LOSS.value,
    )

    assert read_charge_off(at_boundary["id"], analyst_headers)["status"] == "SUPERSEDED"
    later = read_charge_off(above_boundary["id"], analyst_headers)
    assert later["status"] == "PROPOSED"
    assert later["outstanding_loss_cents"] == 103501

    _rows, meta = validate_paginated(
        api.list_account_charge_offs(scenario["account_id"], analyst_headers)
    )
    assert meta["total_count"] == 2, "The refused proposal created nothing"


def test_stale_account_version_on_a_charge_off_proposal_is_refused(api, analyst_headers):
    """PRD §2.7: "Proposing a charge-off against a deposit account requires a
    non-optional `expected_account_version` field carrying the client's last
    observed `version` of that `DepositAccount`. If it does not equal the account's
    current `version`, the request is rejected with `ERR_STALE_ACCOUNT_VERSION`
    (HTTP 412) and nothing is created."
    PRD §2.7: "A new proposal supersedes any existing proposed charge-off on the
    same account, and the loss figure is priced against balances the stale reader
    has not seen. On success the account's `version` advances by 1."
    PRD §3.8: "Third, `recovery_fee_cents` is `base_net_cents` multiplied by the
    selected rate, divided by 10,000, and rounded half up to whole cents — the
    single rounding event in this rule."

    Design: Corner/cross_cutting_complexity_layers/stale_account_version_on_charge_off_creation_is_refused
    """
    scenario = create_active_account(legal_name="Occ Account Depositor", tin_last4="0044")
    observed_version = account_version(scenario["account_id"])

    first = propose_charge_off(
        scenario["account_id"], expected_version=observed_version,
        gross_loss_cents=80000, collateral_offset_cents=0,
    )

    validate_error(
        api.create_charge_off(
            scenario["account_id"],
            {
                "gross_loss_cents": 90000,
                "collateral_offset_cents": 0,
                "expected_account_version": observed_version,
            },
            analyst_headers,
        ),
        ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value,
    )

    refreshed_version = account_version(scenario["account_id"])
    assert refreshed_version > observed_version, "The first proposal advanced the account's version"

    second = propose_charge_off(
        scenario["account_id"], expected_version=refreshed_version,
        gross_loss_cents=90000, collateral_offset_cents=0,
    )
    assert second["net_charge_off_cents"] == 94500, (
        "90000 at tier-1 500 bps gives a 4500-cent fee"
    )

    assert read_charge_off(first["id"], analyst_headers)["status"] == "SUPERSEDED"

    _rows, meta = validate_paginated(
        api.list_account_charge_offs(scenario["account_id"], analyst_headers)
    )
    assert meta["total_count"] == 2


def test_booking_against_an_account_that_is_not_closed_is_refused(api, analyst_headers):
    """PRD §3.8: "**Booking** is an `OperationsAdmin` action and is the transition
    `APPROVED → BOOKED`, stamping `booked_by_user_id` and `booked_at`. The account
    must have `lifecycle_status` `CLOSED` before a write-off may be booked against
    it; otherwise the request is refused with `ERR_ACCOUNT_NOT_CLOSED` (HTTP 409)."
    PRD §3.8: "A fresh proposal has `principal_recovered_cents` and
    `fee_recovered_cents` at 0, `approved_by_user_id`, `booked_by_user_id`,
    `ledger_balance_before_book_cents`, `booked_at`, and `reversed_at` all null,
    and `status` `PROPOSED`."
    PRD §3.8: "**Approval** is a `FraudSupervisor` action and is the transition
    `PROPOSED → APPROVED`, stamping `approved_by_user_id` from `X-User-ID`."

    Design: Corner/validations/booking_a_charge_off_while_the_account_is_still_active_is_rejected
    """
    scenario = create_active_account(legal_name="Premature Booking Depositor", tin_last4="0034")
    charge_off = propose_charge_off(
        scenario["account_id"], gross_loss_cents=60000, collateral_offset_cents=0
    )
    assert charge_off["net_charge_off_cents"] == 63000, (
        "base_net 60000 at tier-1 500 bps gives a 3000-cent fee"
    )
    approve_charge_off(charge_off["id"])

    validate_error(
        api.book_charge_off(charge_off["id"], OPS),
        ApiErrorId.ERR_ACCOUNT_NOT_CLOSED.value,
    )

    unchanged = read_charge_off(charge_off["id"], analyst_headers)
    assert unchanged["status"] == "APPROVED"
    assert unchanged["booked_at"] is None
    assert unchanged["ledger_balance_before_book_cents"] is None

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["lifecycle_status"] == "ACTIVE"
    assert account["ledger_balance_cents"] == 0
    assert account["charged_off_amount_cents"] == 0


# ===========================================================================
# The recovery waterfall
# ===========================================================================
def test_recovery_waterfall_fills_the_fee_bucket_first_and_guards_every_edge(
    api, analyst_headers
):
    """PRD §3.8: "**Recovery postings** are made by an `OperationsAdmin` and carry
    an `amount_cents` receipt, which is allocated through a two-bucket waterfall in
    fixed order: the recovery agency's fee is made whole before the bank recovers
    any principal. The fee bucket has room equal to `recovery_fee_cents` less
    `fee_recovered_cents`, and the posting fills it with the smaller of the receipt
    and that room. Whatever remains then goes to the principal bucket, whose room is
    `base_net_cents` less `principal_recovered_cents`, again taking the smaller of
    what remains and that room. If anything is still left over after both buckets
    are full, the posting does not fit and is rejected in its entirety with
    `ERR_RECOVERY_EXCEEDS_LOSS` (HTTP 422) — a posting is all-or-nothing and, when
    rejected, mutates no field anywhere. Otherwise `fee_recovered_cents` and
    `principal_recovered_cents` are increased by the amounts actually applied, the
    account's `charged_off_amount_cents` is reduced by the total applied, and the
    charge-off's status becomes `RECOVERED_FULL` when `outstanding_loss_cents` has
    reached exactly 0 and `RECOVERED_PARTIAL` while it is still greater than 0."
    PRD §3.8: "**Reversal** is a `FraudSupervisor` action carrying a
    `reversal_reason`. It is permitted only where nothing has been recovered: both
    `principal_recovered_cents` and `fee_recovered_cents` must be exactly 0, and a
    reversal attempted after any recovery posting is refused with
    `ERR_RECOVERY_ALREADY_POSTED` (HTTP 409)."
    PRD §3.8: "Every charge-off operation checks the state it expects, reporting
    `ERR_CHARGE_OFF_INVALID_STATE` (HTTP 409) on a mismatch: approval requires
    `PROPOSED`; booking requires `APPROVED`; a recovery posting requires
    `REFERRED_TO_RECOVERY` or `RECOVERED_PARTIAL`; and a reversal requires
    `BOOKED`, `REFERRED_TO_RECOVERY`, `RECOVERED_PARTIAL`, or `RECOVERED_FULL`."

    Design: Corner/calculations/recovery_waterfall_fills_the_fee_bucket_before_principal_and_guards_overflow
    """
    scenario = setup_booked_charge_off(
        gross_loss_cents=120000, collateral_offset_cents=20000,
        legal_name="Recovery Waterfall Depositor", tin_last4="0025",
    )
    assert scenario["charge_off"]["status"] == "REFERRED_TO_RECOVERY"

    validate_error(
        api.create_recovery_posting(
            scenario["charge_off_id"], {"amount_cents": 105001}, OPS
        ),
        ApiErrorId.ERR_RECOVERY_EXCEEDS_LOSS.value,
    )

    fee_only = validate_success(
        api.create_recovery_posting(scenario["charge_off_id"], {"amount_cents": 5000}, OPS)
    )
    assert fee_only["fee_recovered_cents"] == 5000, "The fee bucket is filled first"
    assert fee_only["principal_recovered_cents"] == 0
    assert fee_only["outstanding_loss_cents"] == 100000
    assert fee_only["status"] == "RECOVERED_PARTIAL"

    validate_error(
        api.reverse_charge_off(
            scenario["charge_off_id"],
            {"reversal_reason": "Attempted reversal after a recovery"},
            SUPERVISOR,
        ),
        ApiErrorId.ERR_RECOVERY_ALREADY_POSTED.value,
    )

    full = post_recovery(scenario["charge_off_id"], 100000)
    assert full["fee_recovered_cents"] == 5000
    assert full["principal_recovered_cents"] == 100000
    assert full["outstanding_loss_cents"] == 0
    assert full["status"] == "RECOVERED_FULL"

    validate_error(
        api.create_recovery_posting(scenario["charge_off_id"], {"amount_cents": 1}, OPS),
        ApiErrorId.ERR_CHARGE_OFF_INVALID_STATE.value,
    )

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["charged_off_amount_cents"] == 0
    assert account["lifecycle_status"] == "CHARGED_OFF"
