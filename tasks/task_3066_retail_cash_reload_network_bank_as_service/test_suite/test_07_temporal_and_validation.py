"""Temporal window semantics and validation-path claims (PRD §2.4, §3.4, §3.6, §3.8)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId, validate_error, get_success_data, set_clock,
    setup_network, get_account, get_location, get_agreement, get_load,
    create_and_fund_load, create_load, create_load_raw, raise_alert, raise_alert_raw,
    review_alert, confirm_alert, create_float_window, create_settlement_batch,
    open_settlement_batch, settle_settlement_batch, set_brand_state,
    set_location_state, setup_structuring_account,
    make_retailer_clerk_headers, ANALYST, ADMIN, SETTLEMENT,
)


# ---------------------------------------------------------------------------
# Trailing 24h half-open window
# ---------------------------------------------------------------------------

def test_trailing_window_lower_bound_is_strictly_exclusive():
    """PRD §3.6: "The trailing variant looks back 24 hours from the current clock
    instant, counting loads whose `funded_at` is strictly later than the instant
    24 hours ago and no later than the current instant".

    Design: Difficulty/resource_temporal_overlap/account_trailing_24h_half_open_window
    """
    net = setup_network(clock="2026-08-31T00:00:00Z")
    first = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                 principal_cents=1000)
    set_clock("2026-08-31T00:00:01Z")
    second = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                  principal_cents=1000)
    set_clock("2026-09-01T00:00:00Z")
    account = get_account(net["account"]["id"])
    # The load funded exactly 24h ago is excluded; the one funded one second later is in.
    assert account["window_load_count"] == 1
    assert account["window_load_cents"] == 1000
    assert get_load(first["id"])["funded_at"] == "2026-08-31T00:00:00Z"
    assert get_load(second["id"])["funded_at"] == "2026-08-31T00:00:01Z"


def test_trailing_window_upper_bound_is_closed_at_the_present_instant():
    """PRD §3.6: "counting loads whose `funded_at` is strictly later than the
    instant 24 hours ago and no later than the current instant".

    Design: Difficulty/resource_temporal_overlap/account_trailing_24h_half_open_window
    """
    net = setup_network(clock="2026-09-01T00:00:00Z")
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=1000)
    account = get_account(net["account"]["id"])
    # A load funded at exactly the current instant is counted (<= now).
    assert account["window_load_count"] == 1


# ---------------------------------------------------------------------------
# Float-window buffer overlap
# ---------------------------------------------------------------------------

def test_float_window_buffer_overlap_is_closed_interval_with_buffer():
    """PRD §3.8: "a candidate window's interval, extended by its `buffer_minutes`
    on both sides, may not overlap any non-cancelled window of the same location,
    else `ERR_FLOAT_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/float_window_buffer_overlap_asymmetry
    """
    net = setup_network(clock="2026-09-01T12:00:00Z")
    create_float_window(net["location"],
                        window_start_at="2026-09-01T14:00:00Z",
                        window_end_at="2026-09-01T15:00:00Z",
                        buffer_minutes=120)
    # Starting exactly two hours after the first window ends collides with the buffer.
    resp = api_client.create_float_window(
        {"reload_location_id": net["location"]["id"],
         "window_start_at": "2026-09-01T17:00:00Z",
         "window_end_at": "2026-09-01T18:00:00Z",
         "armored_carrier": "Brinks",
         "float_amount_cents": 400000,
         "buffer_minutes": 120},
        SETTLEMENT)
    validate_error(resp, ApiErrorId.ERR_FLOAT_WINDOW_OVERLAP, 409)


def test_float_window_one_minute_past_the_buffer_is_accepted():
    """PRD §3.8: "a candidate window's interval, extended by its `buffer_minutes`
    on both sides, may not overlap any non-cancelled window of the same location".

    Design: Difficulty/resource_temporal_overlap/float_window_buffer_overlap_asymmetry
    """
    net = setup_network(clock="2026-09-01T12:00:00Z")
    first = create_float_window(net["location"],
                                window_start_at="2026-09-01T14:00:00Z",
                                window_end_at="2026-09-01T15:00:00Z",
                                buffer_minutes=120)
    accepted = get_success_data(api_client.create_float_window(
        {"reload_location_id": net["location"]["id"],
         "window_start_at": "2026-09-01T17:01:00Z",
         "window_end_at": "2026-09-01T18:01:00Z",
         "armored_carrier": "Brinks",
         "float_amount_cents": 400000,
         "buffer_minutes": 120},
        SETTLEMENT))
    assert accepted["window_status"] == "REQUESTED"
    assert get_success_data(api_client.get_float_window(first["id"], ADMIN))[
        "window_status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# Empty settlement period
# ---------------------------------------------------------------------------

def test_settlement_refuses_a_period_containing_no_qualifying_loads():
    """PRD §3.8: "The batch must be `OPEN`, and at least one load in its period
    must be `FUNDED` — a period with nothing to settle is refused with
    `ERR_SETTLEMENT_EMPTY_PERIOD` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/settlement_zero_qualifying_loads_boundary
    """
    net = setup_network(clock="2026-09-01T00:00:00Z")
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=3500)
    batch = create_settlement_batch(net["agreement"],
                                    period_start_at="2026-09-05T00:00:00Z",
                                    period_end_at="2026-09-06T00:00:00Z")
    open_settlement_batch(batch["id"])
    resp = settle_settlement_batch(batch["id"])
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EMPTY_PERIOD, 422)


def test_failed_empty_period_settlement_leaves_the_batch_and_load_untouched():
    """PRD §3.8: "a period with nothing to settle is refused with
    `ERR_SETTLEMENT_EMPTY_PERIOD` (HTTP 422)".
    PRD §3.8: "the period boundaries are half-open: the start is inclusive and
    the end is exclusive."

    Design: Difficulty/boundary_precision_check/settlement_zero_qualifying_loads_boundary
    """
    net = setup_network(clock="2026-09-01T00:00:00Z")
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=3500)
    batch = create_settlement_batch(net["agreement"],
                                    period_start_at="2026-09-05T00:00:00Z",
                                    period_end_at="2026-09-06T00:00:00Z")
    open_settlement_batch(batch["id"])
    settle_settlement_batch(batch["id"])
    batch_now = get_success_data(api_client.get_settlement_batch(batch["id"], ADMIN))
    assert batch_now["batch_status"] == "OPEN"
    assert batch_now["gross_principal_cents"] == 0
    load_now = get_load(load["id"])
    assert load_now["load_status"] == "FUNDED"
    assert load_now["settlement_batch_id"] is None


# ---------------------------------------------------------------------------
# Structuring band closure
# ---------------------------------------------------------------------------

def test_structuring_band_is_closed_once_flagged():
    """PRD §3.4: "Fourth, a load whose principal falls inside the sub-threshold
    structuring band while the account's `structuring_txn_count` already stands at
    or above the structuring transaction count is refused with
    `ERR_STRUCTURING_BAND` (HTTP 422), because the band is closed once the account
    has been flagged."

    Design: Corner/validations/structuring_band_closed_after_third_subthreshold_load
    """
    net, loads = setup_structuring_account(principals=(9000, 9500, 9999))
    assert get_account(net["account"]["id"])["structuring_txn_count"] == 3
    resp = create_load_raw(net["location"], net["account"], net["agreement"],
                           principal_cents=9500)
    validate_error(resp, ApiErrorId.ERR_STRUCTURING_BAND, 422)
    assert get_account(net["account"]["id"])["structuring_txn_count"] == 3


def test_principal_outside_the_band_is_permitted_while_flagged():
    """PRD §3.4: "the band is closed once the account has been flagged."
    PRD §3.6: "a load outside the band never contributes to either figure."

    Design: Corner/validations/structuring_band_closed_after_third_subthreshold_load
    """
    net, loads = setup_structuring_account(principals=(9000, 9500, 9999))
    load = create_load(net["location"], net["account"], net["agreement"],
                       principal_cents=10000)
    assert load["load_status"] == "INITIATED"


# ---------------------------------------------------------------------------
# Account holds and alerts
# ---------------------------------------------------------------------------

def test_aml_alert_pending_blocks_returning_an_account_to_clear():
    """PRD §3.6: "Returning from `REVIEW` to `CLEAR` requires that no non-terminal
    alert reference the account (`ERR_AML_ALERT_PENDING`, HTTP 409)".

    Design: Corner/validations/aml_alert_pending_blocks_account_clear
    """
    net = setup_network(activate_brand_flag=True)
    # Suspend the brand to move the account CLEAR -> REVIEW, then raise a live alert.
    get_success_data(set_brand_state(net["brand"]["id"], "SUSPENDED"))
    assert get_account(net["account"]["id"])["compliance_hold_status"] == "REVIEW"
    raise_alert(net["program"], net["account"], "VELOCITY")
    resp = api_client.set_card_account_hold(
        net["account"]["id"], {"to_hold_status": "CLEAR"}, ANALYST)
    validate_error(resp, ApiErrorId.ERR_AML_ALERT_PENDING, 409)
    assert get_account(net["account"]["id"])["compliance_hold_status"] == "REVIEW"


def test_frozen_account_beats_the_per_transaction_limit_on_load_creation():
    """PRD §2.8: "A hold dimension of `FROZEN` blocks money-affecting work on the
    account with `ERR_ACCOUNT_FROZEN` (HTTP 409)".
    PRD §3.4: "Second, the principal must not exceed the store's
    `effective_per_transaction_limit_cents`; a breach is
    `ERR_PER_TRANSACTION_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/account_frozen_beats_per_transaction_limit
    """
    net = setup_network(agreement_overrides={"per_transaction_limit_cents": 5000})
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=4000)
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    review_alert(alert["id"])
    confirm_alert(alert["id"])
    assert get_account(net["account"]["id"])["compliance_hold_status"] == "FROZEN"
    # 6000 violates the 5000 per-transaction limit AND the account is frozen.
    resp = api_client.create_load(
        {"reload_location_id": net["location"]["id"],
         "card_account_id": net["account"]["id"],
         "principal_cents": 6000,
         "expected_card_account_version": get_account(net["account"]["id"])["version"]},
        make_retailer_clerk_headers(net["agreement"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_FROZEN, 409)


def test_per_transaction_limit_is_reported_when_the_account_is_clear():
    """PRD §3.4: "Second, the principal must not exceed the store's
    `effective_per_transaction_limit_cents`; a breach is
    `ERR_PER_TRANSACTION_LIMIT_EXCEEDED` (HTTP 422)."
    PRD §2.8: "A hold dimension of `FROZEN` blocks money-affecting work on the
    account with `ERR_ACCOUNT_FROZEN` (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/account_frozen_beats_per_transaction_limit
    """
    net = setup_network(agreement_overrides={"per_transaction_limit_cents": 5000})
    resp = api_client.create_load(
        {"reload_location_id": net["location"]["id"],
         "card_account_id": net["account"]["id"],
         "principal_cents": 6000,
         "expected_card_account_version": get_account(net["account"]["id"])["version"]},
        make_retailer_clerk_headers(net["agreement"]["id"]))
    # Same violating principal as the frozen case, but the CLEAR account means the
    # constraint tier answers instead of the state tier.
    validate_error(resp, ApiErrorId.ERR_PER_TRANSACTION_LIMIT_EXCEEDED, 422)
    assert get_account(net["account"]["id"])["compliance_hold_status"] == "CLEAR"


def test_open_location_with_an_oversized_float_gets_the_cap_error():
    """PRD §3.8: "a window may not be requested, nor completed, if doing so would
    push the agreement's `float_position_cents` past the float cap of 3,000,000
    cents, else `ERR_FLOAT_CAP_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/location_closed_beats_float_cap_exceeded
    """
    net = setup_network(clock="2026-09-01T00:00:00Z")
    resp = api_client.create_float_window(
        {"reload_location_id": net["location"]["id"],
         "window_start_at": "2026-09-01T14:00:00Z",
         "window_end_at": "2026-09-01T15:00:00Z",
         "armored_carrier": "Loomis",
         "float_amount_cents": 4_000_000,
         "buffer_minutes": 120},
        net["pm_headers"])
    # The location is OPEN here, so the fiscal ceiling is the rule that answers.
    validate_error(resp, ApiErrorId.ERR_FLOAT_CAP_EXCEEDED, 422)


def test_closed_location_beats_the_float_cap_on_a_float_window_request():
    """PRD §3.3: "Cash may only be accepted at a store whose `location_status` is
    `OPEN` (`ERR_LOCATION_NOT_OPEN`, HTTP 409)".
    PRD §3.8: "a window may not be requested, nor completed, if doing so would push
    the agreement's `float_position_cents` past the float cap of 3,000,000 cents,
    else `ERR_FLOAT_CAP_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/location_closed_beats_float_cap_exceeded
    """
    net = setup_network(clock="2026-09-01T00:00:00Z")
    get_success_data(set_location_state(net["program"]["id"], net["location"]["id"],
                                        "CLOSED"))
    resp = api_client.create_float_window(
        {"reload_location_id": net["location"]["id"],
         "window_start_at": "2026-09-01T14:00:00Z",
         "window_end_at": "2026-09-01T15:00:00Z",
         "armored_carrier": "Loomis",
         "float_amount_cents": 4_000_000,
         "buffer_minutes": 120},
        SETTLEMENT)
    validate_error(resp, ApiErrorId.ERR_LOCATION_NOT_OPEN, 409)
    assert get_location(net["location"]["id"])["location_status"] == "CLOSED"