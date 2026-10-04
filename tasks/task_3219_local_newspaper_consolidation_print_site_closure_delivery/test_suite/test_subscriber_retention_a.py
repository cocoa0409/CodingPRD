"""Difficulty queue A — non_linear_state_machine, the subscriber retention fork.

The subscriber machine is a second fork-join on a different entity: active forks
into a retention branch that loops back to active and an exit branch that
terminates at churned. The retention branch is entered only through a system event
seeded by a market withdrawal or a stop termination.
"""
import pytest

from test_helpers import (
    api,
    setup_market_with_single_stop,
    terminate_stop,
    terminate_stop_response,
    resume_stop_response,
    get_subscriber,
    cancel_subscriber,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

CS = TEST_USERS["customer_service_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]


@pytest.fixture
def subscriber_on_terminated_stop():
    """One subscriber SUB-LOOP with 40 remaining issues on a now-terminated stop."""
    s = setup_market_with_single_stop(
        clock=CLOCK_2026_09_30,
        subscriber_overrides={
            "subscriber_ref": "SUB-LOOP",
            "remaining_print_issues": 40,
            "paid_through_utc": "2027-06-01T00:00:00Z",
            "print_issue_value_cents": 1200,
        },
    )
    s["stop_status_before"] = s["stop"]["status"]
    terminate_stop(s["stop"]["id"])
    return s


def test_stop_termination_forks_the_contract_into_retention(subscriber_on_terminated_stop):
    """PRD §3.4: "Terminating a stop — permitted from `active` or from `paused` —
    is terminal, and moves every subscriber contract on it into retention with
    `delivery_status` `terminated`."
    PRD §3.6: "A contract enters `churned_pending_retention` only through a system
    event seeded by a market withdrawal or a stop termination".

    Design: Difficulty/non_linear_state_machine/subscriber_retention_fork_loops_back_to_active
    """
    s = subscriber_on_terminated_stop

    refreshed = get_subscriber(s["subscriber"]["id"])

    assert refreshed["status"] == "churned_pending_retention", (
        f"expected churned_pending_retention, got {refreshed['status']}"
    )
    assert refreshed["delivery_status"] == "terminated"
    assert refreshed["offer_status"] == "offered"


def test_the_exit_branch_is_reachable_from_the_same_fork_point(
        subscriber_on_terminated_stop):
    """PRD §3.6: "Cancellation moves an `active` or `churned_pending_retention`
    contract to `churned` with `offer_status` set to `declined`, computing the
    churn credit under the refund-responsibility variant".

    Design: Difficulty/non_linear_state_machine/subscriber_retention_fork_loops_back_to_active
    """
    s = subscriber_on_terminated_stop

    entry = get_subscriber(s["subscriber"]["id"])
    assert entry["status"] == "churned_pending_retention"

    exited = cancel_subscriber(s["subscriber"]["id"])

    assert exited["status"] == "churned", (
        f"the exit edge must reach churned, got {exited['status']}"
    )
    assert exited["offer_status"] == "declined"
    assert exited["churn_retention_credit_cents"] == 5000


def test_the_retention_branch_is_terminal_for_its_sibling_stop(
        subscriber_on_terminated_stop):
    """PRD §3.4: "Resuming is admitted only once the current logical date is
    strictly later than the stop's `pause_end_date`".
    PRD §3.4: "Terminating a stop — permitted from `active` or from `paused` — is
    terminal".

    Design: Difficulty/non_linear_state_machine/subscriber_retention_fork_loops_back_to_active
    """
    s = subscriber_on_terminated_stop

    stop_after = validate_success(
        api.get_delivery_stop(s["stop"]["id"], DELIVERY), 200)
    assert stop_after["status"] == "terminated"

    # A terminated stop is terminal: resuming it cannot re-enter active.
    resumed = resume_stop_response(s["stop"]["id"])
    assert resumed.status_code >= 400, (
        f"resuming a terminated stop must be refused, got {resumed.status_code}"
    )
    assert resumed.json()["data"]["error_id"] in (
        "ERR_STOP_NOT_ACTIVE", "ERR_INVALID_STATE", "ERR_BACKED_OUT_REFERENCE",
    )
    final = validate_success(api.get_delivery_stop(s["stop"]["id"], DELIVERY), 200)
    assert final["status"] == "terminated", (
        "the stop must not re-enter active after the refused resume"
    )
    assert final["status"] == "terminated", (
        "the stop must never re-enter active"
    )