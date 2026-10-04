"""Relocation, contract-assumption negotiation and its rejection cycle."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    set_logical_clock,
    setup_assumption_ready,
    setup_funded_direct_contract,
    find_monitoring_account,
    raise_service_required_action,
    register_customer,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)

_ANALYST = TEST_USERS["funding_analyst_headers"]


# ─── Difficulty: non_linear_state_machine / assumption_request_failed_negotiation_round_cycle ───

def _open_rejectable_assumption():
    """An ACTIVE contract plus an assumption request the funding desk may reject.

    PRD §3.9 gives the reject two declared reasons: an incoming credit score strictly
    below the floor of 620, or a residence outside the service radius — the latter is
    refused with ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS. This fixture takes the first
    reason so the counter-offer actually lands as a rejection and the cyclic
    negotiation round is exercised.
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    outgoing, incoming, contract, request = setup_assumption_ready(
        residence_state_code="TX", incoming_credit_score=580)
    assert request["request_status"] == "PENDING_NEGOTIATION"
    assert request["rejection_count"] == 0
    return request


def test_first_rejection_loops_back_to_pending_negotiation(api):
    """PRD §3.9: "A rejection increments `rejection_count` and advances the request's `version`. Critically, the first two rejections loop the request back to `PENDING_NEGOTIATION` rather than terminating it — each is a cyclic negotiation round that leaves the request open for a new incoming subscriber"
    PRD §3.9: "The request begins in the request state `PENDING_NEGOTIATION` — the value its `request_status` field takes — with a `rejection_count` of zero and no accepted or completed instants."

    Design: Difficulty/non_linear_state_machine/assumption_request_failed_negotiation_round_cycle
    """
    request = _open_rejectable_assumption()

    rejected = validate_success(
        api_client.reject_assumption_request(request["id"], _ANALYST), 200)

    assert rejected["rejection_count"] == 1
    assert rejected["request_status"] == "PENDING_NEGOTIATION"


def test_second_rejection_still_loops_back_to_pending_negotiation(api):
    """PRD §3.9: "Critically, the first two rejections loop the request back to `PENDING_NEGOTIATION` rather than terminating it — each is a cyclic negotiation round that leaves the request open for a new incoming subscriber"

    Design: Difficulty/non_linear_state_machine/assumption_request_failed_negotiation_round_cycle
    """
    request = _open_rejectable_assumption()

    api_client.reject_assumption_request(request["id"], _ANALYST)
    second = validate_success(
        api_client.reject_assumption_request(request["id"], _ANALYST), 200)

    assert second["rejection_count"] == 2
    assert second["request_status"] == "PENDING_NEGOTIATION"


# ─── Difficulty: priority_pair_validation_conflict / temporal_precedes_safety_on_assumption_complete ───

def _accepted_request_with_radius_and_watch_faults():
    """An accepted assumption whose residence is out of radius AND whose account is watched."""
    set_logical_clock("2026-09-01T00:00:00Z")
    outgoing, incoming, contract, request = setup_assumption_ready(
        residence_state_code="AZ", incoming_credit_score=700)
    account = find_monitoring_account(contract["id"])
    raise_service_required_action(account["id"])
    accepted = validate_success(
        api_client.accept_assumption_request(request["id"], _ANALYST), 200)
    assert accepted["request_status"] == "ACCEPTED"
    return outgoing, contract, request


def test_assumption_complete_reports_the_radius_error(api):
    """PRD §3.9: "completion is gated on four conditions: the incoming `incoming_credit_score` is at least 620; the `residence_state_code` lies inside the relocation service radius of `TX`, `OK`, `NM`, `AR` and `LA`; the outgoing subscriber retains at least one other contract in status `ACTIVE` or `DELINQUENT`, refused otherwise with `ERR_ASSUMED_CONTRACT_MUST_HAVE_SURVIVING_CONTRACT`; and the contract carries no open `SERVICE_REQUIRED` reduction action, refused otherwise with `ERR_FALSE_ALARM_WATCH_ACTIVE`."
    PRD §2.10: "Temporal and scheduling checks come fourth, covering the funding window (`ERR_FUNDING_WINDOW_EXPIRED`), the alarm verification and abort windows (`ERR_ALARM_OUTSIDE_VERIFIED_WINDOW`), resource window collisions (`ERR_SERVICE_WINDOW_OVERLAP`) and the relocation radius (`ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS`)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_precedes_safety_on_assumption_complete
    """
    outgoing, contract, request = _accepted_request_with_radius_and_watch_faults()

    res = api_client.complete_assumption_request(
        request["id"], TEST_USERS["customer_headers"])
    validate_error(res, ApiErrorId.ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS, expected_status=422)


def test_assumption_complete_reports_temporal_error_over_safety_watch(api):
    """PRD §2.10: "Safety checks come fifth: the suspended-dealer package refusal (`ERR_DEALER_PACKAGE_SUSPENDED`), segregation of duties on rescission (`ERR_SEGREGATION_OF_DUTIES_REQUIRED`), the dispatch mass-cancel guard (`ERR_MASS_CANCEL_BLOCKED`) and the false-alarm watch blocking an assumption (`ERR_FALSE_ALARM_WATCH_ACTIVE`)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_precedes_safety_on_assumption_complete
    """
    outgoing, contract, request = _accepted_request_with_radius_and_watch_faults()

    res = api_client.complete_assumption_request(
        request["id"], TEST_USERS["customer_headers"])
    body = res.json()
    assert body["data"]["error_id"] == "ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS"
    assert body["data"]["error_id"] != "ERR_FALSE_ALARM_WATCH_ACTIVE"