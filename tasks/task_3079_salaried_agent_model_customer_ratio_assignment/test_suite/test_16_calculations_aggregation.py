"""Corner tests — close rate, satisfaction aggregation and capacity reopening (queue B)."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    PLATFORM_ADMIN,
    TRANSACTION_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    open_transaction,
    advance_to_review,
    close_transaction,
    setup_lead_with_open_transaction_at_review,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_close_rate_excludes_cancelled_transactions_from_the_denominator():
    """PRD §3.5: "A cancel releases the client's capacity in exactly the same way, dropping the agent's tally by one and recomputing the band, but it leaves the agent's `close_rate` untouched: cancelled transactions are excluded from the denominator entirely, so a cancelled deal neither helps nor harms the agent's ratio."
    PRD §3.10: "the count of the agent's `CLOSED` transactions over the count of all its transactions that are not `CANCELLED`, rounded half-up to four decimal places, and zero when the denominator is zero".

    Design: Corner/calculations/close_rate_excludes_cancelled_transactions_from_the_denominator
    """
    region = create_region(target_client_ratio=5.0)
    lead = create_lead_agent(region["id"], base_salary_cents=8_000_000)

    closes = create_client(full_name="Closes", service_area_code="98101")
    cancels = create_client(full_name="Cancels", service_area_code="98102")
    assign_client(closes["id"])
    assign_client(cancels["id"])

    tx_close = open_transaction(closes["id"])
    advance_to_review(tx_close["id"], 75_000_000)
    close_transaction(tx_close["id"])

    tx_cancel = open_transaction(cancels["id"])
    get_success_data(api_client.cancel_transaction(tx_cancel["id"], TRANSACTION_COORDINATOR))

    agent = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent["close_rate"] == pytest.approx(1.0, abs=1e-4), agent
    # a naive "closed over everything" reading would report 0.5
    assert agent["close_rate"] != pytest.approx(0.5, abs=1e-4), agent


def test_cancelled_transaction_is_still_a_transaction_row_for_the_lead_agent():
    """PRD §3.5: "cancelled transactions are excluded from the denominator entirely, so a cancelled deal neither helps nor harms the agent's ratio".

    Design: Corner/calculations/close_rate_excludes_cancelled_transactions_from_the_denominator
    """
    region = create_region(target_client_ratio=5.0)
    lead = create_lead_agent(region["id"])
    closes = create_client(full_name="Closes", service_area_code="98101")
    cancels = create_client(full_name="Cancels", service_area_code="98102")
    assign_client(closes["id"])
    assign_client(cancels["id"])

    tx_close = open_transaction(closes["id"])
    advance_to_review(tx_close["id"], 75_000_000)
    close_transaction(tx_close["id"])
    tx_cancel = open_transaction(cancels["id"])
    get_success_data(api_client.cancel_transaction(tx_cancel["id"], TRANSACTION_COORDINATOR))

    all_rows = get_success_data(api_client.list_transactions(
        PLATFORM_ADMIN, params={"lead_agent_id": lead["id"]},
    ))
    rows = all_rows if isinstance(all_rows, list) else all_rows.get("data", [])
    assert len(rows) == 2, rows

    cancelled = get_success_data(api_client.list_transactions(
        PLATFORM_ADMIN, params={"lead_agent_id": lead["id"], "coordination_status": "CANCELLED"},
    ))
    cancelled_rows = cancelled if isinstance(cancelled, list) else cancelled.get("data", [])
    assert len(cancelled_rows) == 1, cancelled_rows


def test_satisfaction_score_is_the_mean_of_the_responded_surveys():
    """PRD §3.9: "The score that drives compensation is a single aggregation over answered surveys: `satisfaction_score` is the rounded half-up mean, to two decimal places, of the `score` values from the agent's surveys whose `response_status` is `RESPONDED`, and it is null when the agent has no such survey".

    Design: Corner/calculations/satisfaction_score_shifts_when_a_new_responded_survey_lands
    """
    region = create_region(target_client_ratio=5.0)
    lead = create_lead_agent(region["id"])

    first = create_client(full_name="First Buyer", service_area_code="98101")
    assign_client(first["id"])
    tx_1 = open_transaction(first["id"])
    advance_to_review(tx_1["id"], 70_000_000)
    close_transaction(tx_1["id"])
    get_success_data(api_client.create_survey(
        tx_1["id"], {"agent_id": lead["id"], "score": 5}, TRANSACTION_COORDINATOR,
    ))
    single = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert single["satisfaction_score"] == pytest.approx(5.0, abs=1e-2), single

    second = create_client(full_name="Second Buyer", service_area_code="98102")
    assign_client(second["id"])
    tx_2 = open_transaction(second["id"])
    advance_to_review(tx_2["id"], 80_000_000)
    close_transaction(tx_2["id"])
    get_success_data(api_client.create_survey(
        tx_2["id"], {"agent_id": lead["id"], "score": 4}, TRANSACTION_COORDINATOR,
    ))

    both = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert both["satisfaction_score"] == pytest.approx(4.5, abs=1e-2), both


def test_a_flawless_agent_bonus_is_capped_at_the_stored_ceiling():
    """PRD §3.2: "The blend is capped at 0.30 before it is stored."
    PRD §3.2: "plus 0.1 times the smaller of the region's `occupancy_pct` and 1.0".

    Design: Corner/calculations/satisfaction_score_shifts_when_a_new_responded_survey_lands
    """
    region = create_region(target_client_ratio=5.0)
    lead = create_lead_agent(region["id"], base_salary_cents=8_000_000)

    for i, (code, price) in enumerate([("98101", 70_000_000), ("98102", 80_000_000),
                                       ("98103", 75_000_000)]):
        client = create_client(full_name=f"Buyer {i}", service_area_code=code)
        assign_client(client["id"])
        tx = open_transaction(client["id"])
        advance_to_review(tx["id"], price)
        close_transaction(tx["id"])
        get_success_data(api_client.create_survey(
            tx["id"], {"agent_id": lead["id"], "score": 5 if i == 0 else 4},
            TRANSACTION_COORDINATOR,
        ))

    agent = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    # close_rate 1.0, csat 4.5/5 = 0.9, occupancy 0.0 (every client closed out)
    # => 0.2 + 0.135 + 0.0 = 0.335, capped to 0.30
    assert agent["close_rate"] == pytest.approx(1.0, abs=1e-4), agent
    assert agent["bonus_pct"] == pytest.approx(0.30, abs=1e-4), agent
    assert agent["bonus_cents"] == 2_400_000, agent


def test_a_close_returns_the_capacity_posture_to_open():
    """PRD §3.5: "when that recomputation lands on `UNDER_TARGET` the agent's `LeadCapacity.current_state` returns to `OPEN`".
    PRD §3.4: "`OPEN` is the only posture that admits a new client".

    Design: Corner/state_machines/lead_capacity_returns_to_open_when_the_recomputation_band_clears
    """
    region, lead, _client, tx = setup_lead_with_open_transaction_at_review(target_client_ratio=1.5)

    before = get_success_data(api_client.get_lead_capacity(lead["id"], PLATFORM_ADMIN))
    posture_before = before[0] if isinstance(before, list) else before
    assert posture_before["current_state"] == "AT_CAPACITY", posture_before

    close_transaction(tx["id"])

    after = get_success_data(api_client.get_lead_capacity(lead["id"], PLATFORM_ADMIN))
    posture_after = after[0] if isinstance(after, list) else after
    assert posture_after["current_state"] == "OPEN", posture_after


def test_capacity_reopening_also_restores_the_agent_to_active():
    """PRD §3.5: "which in turn restores the agent to `ACTIVE` and refreshes the region's `agent_count`".
    PRD §3.2: "`AT_CAPACITY` in the same request that pushes its `active_client_count` to the floor of the region target".

    Design: Corner/state_machines/lead_capacity_returns_to_open_when_the_recomputation_band_clears
    """
    region, lead, _client, tx = setup_lead_with_open_transaction_at_review(target_client_ratio=1.5)
    close_transaction(tx["id"])

    agent = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent["status"] == "ACTIVE", agent

    occ = get_success_data(api_client.get_open_client_counts(lead["id"], PLATFORM_ADMIN))
    row = occ[0] if isinstance(occ, list) else occ
    assert row["active_client_count"] == 0, row
    assert row["ratio_state"] == "UNDER_TARGET", row