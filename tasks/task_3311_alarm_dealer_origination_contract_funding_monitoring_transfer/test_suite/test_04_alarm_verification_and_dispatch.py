"""Alarm verification, the false-alarm ratio reads, legal holds and dispatch branching."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    set_logical_clock,
    setup_funded_direct_contract,
    setup_alarm_account,
    setup_verified_alarm_account,
    verify_alarm,
    find_monitoring_account,
    validate_success,
    validate_error,
    create_alarm_event_payload,
    create_dispatch_payload,
    ApiErrorId,
    TEST_USERS,
)

_ANALYST = TEST_USERS["funding_analyst_headers"]
_MONITORING = TEST_USERS["monitoring_operator_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Corner: state_machines / dispatch_cannot_transition_from_aborted_returns_409 ───

def _aborted_dispatch():
    """A dispatch that has been released and then aborted."""
    set_logical_clock("2026-09-01T00:00:00Z")
    account, alarms = setup_alarm_account(
        1, occurred_at="2026-09-03T00:00:00Z", entered_offset_seconds=30)
    dispatch = get_success_data(api_client.create_dispatch_request(
        create_dispatch_payload(alarms[0]["id"]), _MONITORING), 201)
    released = validate_success(api_client.dispatch_request(dispatch["id"], _MONITORING), 200)
    assert released["dispatch_status"] == "DISPATCHED"
    aborted = validate_success(api_client.abort_dispatch(
        dispatch["id"], {"abort_reason": "false alarm"}, _MONITORING), 200)
    assert aborted["dispatch_status"] == "ABORTED"
    return dispatch


def test_completing_an_aborted_dispatch_returns_dispatch_not_requested(api):
    """PRD §3.7: "Completion is reachable only from `DISPATCHED`, and an action attempted from the wrong state is refused with `ERR_DISPATCH_NOT_REQUESTED`."

    Design: Corner/state_machines/dispatch_cannot_transition_from_aborted_returns_409
    """
    dispatch = _aborted_dispatch()

    res = api_client.complete_dispatch(dispatch["id"], _MONITORING)
    validate_error(res, ApiErrorId.ERR_DISPATCH_NOT_REQUESTED, expected_status=409)

    after = validate_success(api_client.get_dispatch_request(dispatch["id"], _MONITORING), 200)
    assert after["dispatch_status"] == "ABORTED"


# ─── Difficulty: non_linear_state_machine / dispatch_request_branch_divergent_guards ───

def test_dispatch_released_branch_reaches_dispatched(api):
    """PRD §3.7: "a `MonitoringOperator` releases a `REQUESTED` dispatch to the central station, which is permitted only while the monitoring account is `PROVISIONED`, stamps `dispatched_at` and advances the `version`"

    Design: Difficulty/non_linear_state_machine/dispatch_request_branch_divergent_guards
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    account, alarms = setup_alarm_account(
        2, occurred_at="2026-09-03T00:00:00Z", entered_offset_seconds=30)

    dispatch = get_success_data(api_client.create_dispatch_request(
        create_dispatch_payload(alarms[0]["id"]), _MONITORING), 201)
    released = validate_success(api_client.dispatch_request(dispatch["id"], _MONITORING), 200)

    assert released["dispatch_status"] == "DISPATCHED"
    assert released["dispatched_at"] is not None


def test_never_dispatched_branch_closes_rather_than_aborting(api):
    """PRD §3.7: "either a `REQUESTED` or a `DISPATCHED` dispatch may be aborted or closed, recording the `abort_reason` and advancing the `version`."
    PRD §3.7: "Closing a `REQUESTED` dispatch has no such timing precondition — it requires nothing beyond authorization."

    Design: Difficulty/non_linear_state_machine/dispatch_request_branch_divergent_guards
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    account, alarms = setup_alarm_account(
        2, occurred_at="2026-09-03T00:00:00Z", entered_offset_seconds=30)

    dispatch = get_success_data(api_client.create_dispatch_request(
        create_dispatch_payload(alarms[1]["id"]), _MONITORING), 201)
    assert dispatch["dispatch_status"] == "REQUESTED"

    closed = validate_success(api_client.abort_dispatch(
        dispatch["id"], {"abort_reason": "customer cancelled"}, _MONITORING), 200)
    assert closed["dispatch_status"] == "CLOSED"

    # CLOSED is terminal: no declared transition leaves it.
    res = api_client.dispatch_request(dispatch["id"], _MONITORING)
    validate_error(res, ApiErrorId.ERR_DISPATCH_NOT_REQUESTED, expected_status=409)


# ─── Difficulty: boundary_precision_check / false_alarm_ratio_cap_strict_inequality_on_verify ───

def test_verified_alarm_raises_the_ratio_to_one_hundred_percent(api):
    """PRD §3.7: "The ratio is the verified signal count as a percent of the known alarm count, and it is defined to be 0.00 percent when the known count is zero; like the dealer rate, it is carried in percent with two decimal places under round-half-up."
    PRD §3.7: "a `VERIFIED` outcome sets `counted_for_false_alarm` true only if the account was `PROVISIONED` at the alarm's `occurred_at`, because the flag is what feeds the numerator of the false-alarm ratio"

    Design: Difficulty/boundary_precision_check/false_alarm_ratio_cap_strict_inequality_on_verify
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    account, alarms = setup_alarm_account(
        1, occurred_at="2026-08-15T00:00:00Z", entered_offset_seconds=30)
    assert account["provision_state"] == "PROVISIONED"

    before = validate_success(
        api_client.get_account_false_alarm_ratio(account["id"], _MONITORING), 200)
    assert before["known_alarm_count"] == 1
    assert before["verified_signal_count"] == 0

    verify_alarm(alarms[0]["id"], "VERIFIED")

    after = validate_success(
        api_client.get_account_false_alarm_ratio(account["id"], _MONITORING), 200)
    assert after["known_alarm_count"] == 1
    assert after["verified_signal_count"] == 1
    assert float(after["ratio_percent"]) == pytest.approx(100.00, abs=0.001)


def test_false_alarm_outcome_is_not_counted_as_a_verified_signal(api):
    """PRD §3.7: "a `FALSE_ALARM` outcome leaves `counted_for_false_alarm` false, because a confirmed false alarm is not a verified signal."
    PRD §3.7: "its verified signals are counted as those alarms in the window that have a non-null `verified_at`, an outcome of `VERIFIED` or `FALSE_ALARM`, and `counted_for_false_alarm` true"

    Design: Difficulty/boundary_precision_check/false_alarm_ratio_cap_strict_inequality_on_verify
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    account, alarms = setup_alarm_account(
        1, occurred_at="2026-08-15T00:00:00Z", entered_offset_seconds=30)
    verify_alarm(alarms[0]["id"], "FALSE_ALARM")

    read = validate_success(
        api_client.get_account_false_alarm_ratio(account["id"], _MONITORING), 200)
    assert read["known_alarm_count"] == 1
    assert read["verified_signal_count"] == 0
    assert float(read["ratio_percent"]) == pytest.approx(0.00, abs=0.001)


# ─── Difficulty: boundary_precision_check / empty_ratio_denominator_zero_not_error_on_contract_read ───

def test_contract_ratio_read_with_no_alarms_returns_zero_not_an_error(api):
    """PRD §3.7: "The ratio is the verified signal count as a percent of the known alarm count, and it is defined to be 0.00 percent when the known count is zero"
    PRD §3.7: "the read reports it as `ratio_percent` alongside `known_alarm_count` and `verified_signal_count`"

    Design: Difficulty/boundary_precision_check/empty_ratio_denominator_zero_not_error_on_contract_read
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    customer, contract = setup_funded_direct_contract(
        equipment_config_code="PREMIUM", credit_score=700, contract_term_months=60,
        customer_email="wren.quiet@example.com")

    read = validate_success(
        api_client.get_contract_false_alarm_ratio(contract["id"], _MONITORING), 200)

    assert float(read["ratio_percent"]) == pytest.approx(0.00, abs=0.001)
    assert read["known_alarm_count"] == 0
    assert read["verified_signal_count"] == 0


def test_account_ratio_read_with_no_alarms_returns_zero_with_http_200(api):
    """PRD §3.7: "its verified signals are counted as those alarms in the window that have a non-null `verified_at`, an outcome of `VERIFIED` or `FALSE_ALARM`, and `counted_for_false_alarm` true. The ratio is the verified signal count as a percent of the known alarm count, and it is defined to be 0.00 percent when the known count is zero"
    PRD §3.7: "The ratio is computed on verification and recomputed on each read, and the read reports it as `ratio_percent` alongside `known_alarm_count` and `verified_signal_count`."

    Design: Difficulty/boundary_precision_check/empty_ratio_denominator_zero_not_error_on_contract_read
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    customer, contract = setup_funded_direct_contract(
        equipment_config_code="PREMIUM", credit_score=700, contract_term_months=60,
        customer_email="wren.quiet.account@example.com")
    account = find_monitoring_account(contract["id"])

    res = api_client.get_account_false_alarm_ratio(account["id"], _MONITORING)
    read = validate_success(res, 200)

    assert res.status_code == 200
    assert float(read["ratio_percent"]) == pytest.approx(0.00, abs=0.001)
    assert read["known_alarm_count"] == 0
    assert read["verified_signal_count"] == 0


# ─── Difficulty: compensating_invariant / false_alarm_legal_hold_release_conserves_verified_signal_count ───

def _account_with_two_verified_alarms():
    set_logical_clock("2026-09-01T00:00:00Z")
    account, alarms = setup_verified_alarm_account(
        2, outcome="VERIFIED", occurred_at="2026-08-20T00:00:00Z",
        provision=True)
    return account, alarms


def test_legal_hold_removes_one_alarm_from_the_verified_signal_count(api):
    """PRD §3.7: "A `ComplianceOfficer` may place a legal hold on a verified alarm, which sets `counted_for_false_alarm` false and advances the alarm's `version`, removing it from the verified signal count"

    Design: Difficulty/compensating_invariant/false_alarm_legal_hold_release_conserves_verified_signal_count
    """
    account, alarms = _account_with_two_verified_alarms()

    before = validate_success(
        api_client.get_account_false_alarm_ratio(account["id"], _MONITORING), 200)
    assert before["verified_signal_count"] == 2
    assert before["known_alarm_count"] == 2
    assert float(before["ratio_percent"]) == pytest.approx(100.00, abs=0.001)

    held = validate_success(
        api_client.place_alarm_legal_hold(alarms[0]["id"], _COMPLIANCE), 200)
    assert held["counted_for_false_alarm"] is False

    during = validate_success(
        api_client.get_account_false_alarm_ratio(account["id"], _MONITORING), 200)
    assert during["verified_signal_count"] == 1


def test_legal_hold_release_restores_the_verified_signal_count(api):
    """PRD §3.7: "releasing the hold restores the flag to true when the alarm had been counted for its window, and advances the `version` again"

    Design: Difficulty/compensating_invariant/false_alarm_legal_hold_release_conserves_verified_signal_count
    """
    account, alarms = _account_with_two_verified_alarms()

    api_client.place_alarm_legal_hold(alarms[0]["id"], _COMPLIANCE)
    released = validate_success(
        api_client.release_alarm_legal_hold(alarms[0]["id"], _COMPLIANCE), 200)
    assert released["counted_for_false_alarm"] is True

    after = validate_success(
        api_client.get_account_false_alarm_ratio(account["id"], _MONITORING), 200)
    # The conserved count returns to its pre-hold value with zero drift.
    assert after["verified_signal_count"] == 2
    assert after["known_alarm_count"] == 2