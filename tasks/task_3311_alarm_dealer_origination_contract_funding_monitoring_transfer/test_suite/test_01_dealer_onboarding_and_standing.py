"""Dealer onboarding, standing derivation and the chargeback-rate recompute."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    set_logical_clock,
    setup_package_with_contract,
    submit_and_approve_package,
    fund_package,
    cancel_contract,
    find_monitoring_account,
    verify_alarm,
    validate_success,
    validate_error,
    create_dealer_payload,
    create_alarm_event_payload,
    ApiErrorId,
)
from test_helpers import TEST_USERS

_CHANNEL = TEST_USERS["channel_manager_headers"]
_ANALYST = TEST_USERS["funding_analyst_headers"]
_MONITORING = TEST_USERS["monitoring_operator_headers"]

_D2_ACTIVATION = "2026-07-10T00:00:00Z"
_D2_WINDOW_NOW = "2026-09-01T00:00:00Z"


def _dealer_with_cancelled_package_contract(*, with_verified_alarm: bool):
    """Build dealer D2 with one funded PREMIUM child sold, cancelled from ACTIVE.

    When ``with_verified_alarm`` is true a VERIFIED alarm is recorded inside the
    contract's ACTIVE interval, so the cancellation counts toward the trailing
    rate denominator D; otherwise it does not.
    """
    set_logical_clock(_D2_ACTIVATION)
    dealer, package, contract = setup_package_with_contract(
        dealer_code="D2",
        legal_name="Bugle Alarm Partners",
        holdback_rate=0.10,
        quality_tier="TIER_2",
        package_reference="PKG-P2",
        equipment_config_code="PREMIUM",
        credit_score=700,
        contract_term_months=60,
        install_scheduled_at=_D2_ACTIVATION,
        engineer_id="ENG-2",
    )
    package = submit_and_approve_package(dealer, package["id"])
    fund_package(package["id"])

    account = find_monitoring_account(contract["id"])
    if with_verified_alarm:
        alarm = get_success_data(api_client.create_alarm_event(
            create_alarm_event_payload(
                account["id"],
                signal_source="ZONE-3",
                occurred_at="2026-07-15T00:00:00Z",
                entered_at_utc="2026-07-15T00:00:30Z",
            ),
            _MONITORING,
        ), 201)
        verify_alarm(alarm["id"], "VERIFIED")

    set_logical_clock(_D2_WINDOW_NOW)
    contract = get_success_data(api_client.get_contract(contract["id"], _ANALYST))
    contract = cancel_contract(contract["id"], customer_id=contract["customer_id"])
    return dealer, contract


def _recompute_chargeback_rate(dealer_id):
    dealer = get_success_data(api_client.get_dealer(dealer_id, _ANALYST))
    res = api_client.recompute_dealer_chargeback_rate(
        dealer_id,
        {"expected_dealer_version": dealer["version"]},
        _ANALYST,
    )
    return validate_success(res, 200)


# ─── Difficulty: dealer_chargeback_rate_inadvertent_alarm_dependent ───

def test_chargeback_denominator_counts_cancellation_carrying_a_verified_alarm(api):
    """PRD §3.1: "The denominator `D` counts the dealer's contracts, across all packages, that are in contract state `CANCELLED` with a recorded `cancelled_from_status` of `ACTIVE` and a non-null `activated_at`, whose `cancelled_at` falls inside the same window, and whose active lifetime carried at least one valid inadvertent alarm — a contract is counted toward the denominator only if it has at least one alarm event with a non-null `verified_at`, an outcome of `VERIFIED` or `FALSE_ALARM`, and an `occurred_at` falling between its `activated_at` and its `cancelled_at` inclusive."
    PRD §3.1: "The recompute then writes `chargeback_rate_12mo_sum` to `L` and `funding_package_count_12mo` to `D`, and the standing derivation of §2.9 runs on those fresh counters."

    Design: Difficulty/dual_variant_calc/dealer_chargeback_rate_inadvertent_alarm_dependent
    """
    dealer, contract = _dealer_with_cancelled_package_contract(with_verified_alarm=True)
    assert contract["contract_status"] == "CANCELLED"
    assert contract["cancelled_from_status"] == "ACTIVE"

    updated = _recompute_chargeback_rate(dealer["id"])

    assert updated["funding_package_count_12mo"] == 1, (
        "the cancelled contract's ACTIVE interval carried a verified alarm, so it "
        f"must be counted in D; got {updated['funding_package_count_12mo']}"
    )
    assert updated["chargeback_rate_12mo_sum"] == 1


def test_chargeback_denominator_excludes_cancellation_without_a_verified_alarm(api):
    """PRD §3.1: "The denominator `D` counts the dealer's contracts, across all packages, that are in contract state `CANCELLED` with a recorded `cancelled_from_status` of `ACTIVE` and a non-null `activated_at`, whose `cancelled_at` falls inside the same window, and whose active lifetime carried at least one valid inadvertent alarm — a contract is counted toward the denominator only if it has at least one alarm event with a non-null `verified_at`, an outcome of `VERIFIED` or `FALSE_ALARM`, and an `occurred_at` falling between its `activated_at` and its `cancelled_at` inclusive."

    Design: Difficulty/dual_variant_calc/dealer_chargeback_rate_inadvertent_alarm_dependent
    """
    dealer, contract = _dealer_with_cancelled_package_contract(with_verified_alarm=False)
    assert contract["contract_status"] == "CANCELLED"
    assert contract["cancelled_from_status"] == "ACTIVE"

    updated = _recompute_chargeback_rate(dealer["id"])

    # Identical cancellation, no counted inadvertent alarm: D drops by exactly one.
    assert updated["funding_package_count_12mo"] == 0, (
        "without a verified alarm inside the ACTIVE interval the cancellation must "
        f"not count toward D; got {updated['funding_package_count_12mo']}"
    )
    assert updated["chargeback_rate_12mo_sum"] == 1


# ─── Corner: entities / dealer_create_returns_defaults_and_version_one ───

def test_dealer_create_initializes_standing_and_zero_balances(api, channel_manager_headers):
    """PRD §3.1: "On registration the dealer's `standing` is initialised to `ACTIVE`, its `chargeback_balance_due_cents` and `holdback_reserve_cents` balances both begin at zero, and its `funded_package_count` begins at zero."
    PRD §2.5: "The `id` is a server-minted UUID with no type prefix — a dealer's `id` and an alarm event's `id` are indistinguishable in shape."

    Design: Corner/entities/dealer_create_returns_defaults_and_version_one
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    res = api_client.create_dealer(
        create_dealer_payload(
            dealer_code="D7", legal_name="Cobalt Security Corp",
            holdback_rate=0.08, quality_tier="TIER_2",
        ),
        channel_manager_headers,
    )
    dealer = validate_success(res, 201)

    assert dealer["dealer_code"] == "D7"
    assert dealer["legal_name"] == "Cobalt Security Corp"
    assert dealer["standing"] == "ACTIVE"
    assert dealer["chargeback_balance_due_cents"] == 0
    assert dealer["holdback_reserve_cents"] == 0
    assert dealer["funded_package_count"] == 0
    assert is_valid_uuid(dealer["id"])
    assert is_iso8601_timestamp(dealer["created_at"])


# ─── Corner: entities / dealer_get_unknown_identifier_returns_404 ───

def test_dealer_get_unknown_identifier_returns_entity_not_found(api, channel_manager_headers):
    """PRD §2.5: "a parent identifier that does not resolve to a row fails before any child collection is consulted, and the failure is reported as `ERR_ENTITY_NOT_FOUND` with HTTP 404."

    Design: Corner/entities/dealer_get_unknown_identifier_returns_404
    """
    res = api_client.get_dealer(NON_EXISTENT_UUID, channel_manager_headers)
    validate_error(res, ApiErrorId.ERR_ENTITY_NOT_FOUND, expected_status=404)


# ─── Corner: entities / create_dealer_missing_required_field_returns_400 ───

def test_dealer_create_missing_required_field_returns_invalid_request(api, channel_manager_headers):
    """PRD §2.10: "a missing required body field or a value outside its declared type or range reports `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_dealer_missing_required_field_returns_400
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    payload = create_dealer_payload(
        dealer_code="D8", holdback_rate=0.05, quality_tier="TIER_1")
    del payload["legal_name"]

    res = api_client.create_dealer(payload, channel_manager_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


# ─── Corner: entities / create_dealer_invalid_quality_tier_returns_400 ───

def test_dealer_create_invalid_quality_tier_returns_invalid_request(api, channel_manager_headers):
    """PRD §2.6: "`quality_tier` is exactly one of `TIER_1`, `TIER_2` or `TIER_3`, and it drives the dealer's funding points"
    PRD §2.10: "a missing required body field or a value outside its declared type or range reports `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_dealer_invalid_quality_tier_returns_400
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    res = api_client.create_dealer(
        create_dealer_payload(
            dealer_code="D9", legal_name="Bad Tier LLC",
            holdback_rate=0.05, quality_tier="TIER_9",
        ),
        channel_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


# ─── Corner: endpoints / success_envelope_carries_meta_and_object_shape ───

def test_success_envelope_carries_request_meta_and_object_shape(api, channel_manager_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."

    Design: Corner/endpoints/success_envelope_carries_meta_and_object_shape
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    res = api_client.create_dealer(
        create_dealer_payload(
            dealer_code="D12", legal_name="Foxtrot Alarms",
            holdback_rate=0.10, quality_tier="TIER_1",
        ),
        channel_manager_headers,
    )
    body = res.json()
    dealer = validate_success(res, 201)

    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert is_valid_uuid(dealer["id"])