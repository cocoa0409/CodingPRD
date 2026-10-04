"""Difficulty tests — transitive cascade chains (queue A, rule `transitive_cascade`).

Both chains are asserted hop by hop, in the order the PRD narrates them, because
a later hop only fires when the earlier one moved its input.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    PLATFORM_ADMIN,
    OPERATIONS_COORDINATOR,
    TRANSACTION_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    open_transaction,
    advance_to_review,
    close_transaction,
    setup_lead_with_confirmed_tour,
    complete_tour,
    set_clock,
    TOUR_CONFIRM_CLOCK,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_closing_a_transaction_releases_the_agents_client_capacity():
    """PRD §3.5: "When it succeeds the transaction records `closed_at`, the client becomes `CLOSED`, the client's originating `OpenClientCount.active_client_count` drops by one and `ratio_state` is recomputed".
    PRD §3.4: "the moment `active_client_count` reaches the floor of the region target the posture becomes `AT_CAPACITY`, and the moment it reaches the ceiling the posture becomes `OVER_TARGET`".

    Design: Difficulty/transitive_cascade/client_closure_cascade_unwinds_agent_capacity_three_hops
    """
    # target 2.0 -> floor = ceil = 2; two clients put the agent at the ceiling.
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    close_me = create_client(full_name="Close Me", service_area_code="98101")
    stay_open = create_client(full_name="Stay Open", service_area_code="98102")
    assign_client(close_me["id"])
    assign_client(stay_open["id"])

    tx = open_transaction(close_me["id"])
    advance_to_review(tx["id"], 80_000_000)

    before = get_success_data(api_client.get_open_client_counts(lead["id"], PLATFORM_ADMIN))
    row_before = before[0] if isinstance(before, list) else before
    assert row_before["active_client_count"] == 2, row_before

    close_transaction(tx["id"])

    after = get_success_data(api_client.get_open_client_counts(lead["id"], PLATFORM_ADMIN))
    row_after = after[0] if isinstance(after, list) else after
    assert row_after["active_client_count"] == 1, row_after
    assert row_after["ratio_state"] == "UNDER_TARGET", row_after


def test_closing_a_transaction_restores_the_posture_and_employment_status():
    """PRD §3.5: "when that recomputation lands on `UNDER_TARGET` the agent's `LeadCapacity.current_state` returns to `OPEN`, which in turn restores the agent to `ACTIVE` and refreshes the region's `agent_count`".

    Design: Difficulty/transitive_cascade/client_closure_cascade_unwinds_agent_capacity_three_hops
    """
    # target 2.0 -> floor = ceil = 2; the second assignment leaves the agent
    # AT_CAPACITY, and closing one transaction returns it to OPEN/ACTIVE.
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    close_me = create_client(full_name="Close Me", service_area_code="98101")
    stay_open = create_client(full_name="Stay Open", service_area_code="98102")
    assign_client(close_me["id"])
    assign_client(stay_open["id"])

    tx = open_transaction(close_me["id"])
    advance_to_review(tx["id"], 80_000_000)

    agent_before = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent_before["status"] == "AT_CAPACITY", agent_before

    close_transaction(tx["id"])

    capacity = get_success_data(api_client.get_lead_capacity(lead["id"], PLATFORM_ADMIN))
    posture = capacity[0] if isinstance(capacity, list) else capacity
    assert posture["current_state"] == "OPEN", posture

    agent_after = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent_after["status"] == "ACTIVE", agent_after


def test_closing_a_transaction_records_a_capacity_release_audit_entry():
    """PRD §3.10: "`CLIENT_CAPACITY_RELEASED` when a close or cancel releases an agent's tally".
    PRD §3.10: "Every one of these consequences that touches a count appends an audit entry."

    Design: Difficulty/transitive_cascade/client_closure_cascade_unwinds_agent_capacity_three_hops
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    close_me = create_client(full_name="Close Me", service_area_code="98101")
    assign_client(close_me["id"])
    tx = open_transaction(close_me["id"])
    advance_to_review(tx["id"], 80_000_000)
    close_transaction(tx["id"])

    audits = get_success_data(api_client.list_region_activity_audits(
        region["id"], PLATFORM_ADMIN, params={"limit": 100},
    ))
    rows = audits if isinstance(audits, list) else audits.get("data", [])
    releases = [a for a in rows if a["kind"] == "CLIENT_CAPACITY_RELEASED"]
    assert releases, rows
    assert any(a["entity_type"] == "OpenClientCount" for a in releases), releases


def test_completing_a_tour_creates_a_bonus_eligible_responded_survey():
    """PRD §3.7: "A `Survey` row is created for the client's transaction with `response_status` `RESPONDED` and `bonus_eligible` true — an agent-initiated close earns bonus credit, as against a survey dispatched by the desk and answered later, which never does."

    Design: Difficulty/transitive_cascade/tour_completion_cascade_reaches_capacity_posture_five_hops
    """
    region, lead, associate, client, tour = setup_lead_with_confirmed_tour(target_client_ratio=2.0)
    # The completion survey is attached to the client's transaction, so one must
    # exist before the tour completes.
    open_transaction(client["id"])
    complete_tour(tour["id"], associate["id"], feedback_rating=5, feedback_notes="Bright and quiet")

    surveys = get_success_data(api_client.list_surveys(
        PLATFORM_ADMIN, params={"agent_id": lead["id"]},
    ))
    rows = surveys if isinstance(surveys, list) else surveys.get("data", [])
    assert len(rows) == 1, rows
    assert rows[0]["response_status"] == "RESPONDED", rows[0]
    assert rows[0]["bonus_eligible"] is True, rows[0]


def test_completing_a_tour_moves_satisfaction_then_bonus_then_posture():
    """PRD §3.7: "That score movement recomputes the agent's `bonus_pct` and `bonus_cents`."
    PRD §3.7: "The bonus band movement recomputes the agent's `LeadCapacity.current_state`, and the recomputed `salary_commitment_cents` is persisted."
    PRD §3.2: "The blend is capped at 0.30 before it is stored."

    Design: Difficulty/transitive_cascade/tour_completion_cascade_reaches_capacity_posture_five_hops
    """
    region, lead, associate, client, tour = setup_lead_with_confirmed_tour(target_client_ratio=2.0)
    open_transaction(client["id"])
    complete_tour(tour["id"], associate["id"], feedback_rating=5)

    agent = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent["satisfaction_score"] == pytest.approx(5.0, abs=1e-2), agent
    # The client is still in the pipeline (occupancy 0.5) and the agent has a
    # single closed transaction, so the <3-close eligibility gate forces the
    # blend to zero while the score itself is recorded.
    assert agent["bonus_pct"] == pytest.approx(0.0, abs=1e-4), agent
    assert agent["bonus_cents"] == 0, agent

    capacity = get_success_data(api_client.get_lead_capacity(lead["id"], PLATFORM_ADMIN))
    posture = capacity[0] if isinstance(capacity, list) else capacity
    assert posture["current_state"] == "OPEN", posture