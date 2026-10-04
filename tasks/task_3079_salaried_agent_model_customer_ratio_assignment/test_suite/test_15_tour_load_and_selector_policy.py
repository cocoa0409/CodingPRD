"""Corner tests — tour load window and the assignment selector policy (queue B)."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    ApiErrorId,
    PLATFORM_ADMIN,
    OPERATIONS_COORDINATOR,
    TRANSACTION_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    schedule_tour,
    open_transaction,
    advance_to_review,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_tours_in_week_counts_only_tours_inside_the_inclusive_seven_day_window():
    """PRD §3.4: "`tours_in_week` counts the agent's tours whose `scheduled_at` falls inside the inclusive window from now through seven days from now, so both ends are inside the window."

    Design: Corner/calculations/tour_load_bands_span_the_seven_day_window_inclusively
    """
    codes = ["98101", "98102", "98103", "98104", "98105", "98106", "98107", "98108"]
    region = create_region(target_client_ratio=8.0, service_area_codes=codes)
    lead = create_lead_agent(region["id"], home_zip="98101")

    # Six tours inside the window (2026-09-01T00:00Z .. 2026-09-08T00:00Z) and one
    # scheduled at 2026-09-08T10:00:00Z, which is outside it.
    inside_times = [
        "2026-09-02T10:00:00Z", "2026-09-02T12:00:00Z", "2026-09-03T10:00:00Z",
        "2026-09-03T14:00:00Z", "2026-09-04T10:00:00Z", "2026-09-05T10:00:00Z",
    ]
    for i, scheduled_at in enumerate(inside_times):
        client = create_client(full_name=f"Tour Client {i}", service_area_code=codes[i])
        assign_client(client["id"])
        schedule_tour(client["id"], scheduled_at)

    outside_client = create_client(full_name="Tour Client 7", service_area_code=codes[6])
    assign_client(outside_client["id"])
    schedule_tour(outside_client["id"], "2026-09-08T10:00:00Z")

    capacity = get_success_data(api_client.get_lead_capacity(lead["id"], PLATFORM_ADMIN))
    row = capacity[0] if isinstance(capacity, list) else capacity
    assert row["tours_in_week"] == 6, row


def test_tours_list_keeps_the_outside_window_tour_as_a_row():
    """PRD §3.4: "so both ends are inside the window".

    Design: Corner/calculations/tour_load_bands_span_the_seven_day_window_inclusively
    """
    codes = ["98101", "98102", "98103", "98104", "98105", "98106", "98107", "98108"]
    region = create_region(target_client_ratio=8.0, service_area_codes=codes)
    lead = create_lead_agent(region["id"], home_zip="98101")
    for i, scheduled_at in enumerate([
        "2026-09-02T10:00:00Z", "2026-09-02T12:00:00Z", "2026-09-03T10:00:00Z",
        "2026-09-03T14:00:00Z", "2026-09-04T10:00:00Z", "2026-09-05T10:00:00Z",
    ]):
        client = create_client(full_name=f"Tour Client {i}", service_area_code=codes[i])
        assign_client(client["id"])
        schedule_tour(client["id"], scheduled_at)
    outside_client = create_client(full_name="Tour Client 7", service_area_code=codes[6])
    assign_client(outside_client["id"])
    schedule_tour(outside_client["id"], "2026-09-08T10:00:00Z")

    tours = get_success_data(api_client.list_tours(
        PLATFORM_ADMIN, params={"lead_agent_id": lead["id"]},
    ))
    rows = tours if isinstance(tours, list) else tours.get("data", [])
    assert len(rows) == 7, rows

    pending = get_success_data(api_client.list_tours(
        PLATFORM_ADMIN, params={"lead_agent_id": lead["id"], "status": "ACCESS_PENDING"},
    ))
    pending_rows = pending if isinstance(pending, list) else pending.get("data", [])
    assert len(pending_rows) == 7, pending_rows


def test_selector_prefers_the_earliest_created_agent_when_loads_are_tied():
    """PRD §3.3: "In its ordinary mode the platform builds a candidate set of every agent in the client's region whose `LeadCapacity.current_state` is `OPEN`, ranks the candidates by `OpenClientCount.active_client_count` ascending, and breaks ties by `Agent.created_at` ascending — the least-loaded agent wins, and among equals the one that joined first wins."
    PRD §3.3: "Row identifiers never participate in the ranking or the tie-break."

    Design: Corner/cross_cutting_layers/assignment_selector_ranks_by_load_then_creation_order_within_geography
    """
    region = create_region(target_client_ratio=5.0)
    first_agent = create_lead_agent(region["id"], full_name="Ada Lead", home_zip="98101")
    second_agent = create_lead_agent(region["id"], full_name="Ben Lead", home_zip="98102")

    client_1 = create_client(full_name="First Buyer", service_area_code="98101")
    client_2 = create_client(full_name="Second Buyer", service_area_code="98102")
    client_3 = create_client(full_name="Third Buyer", service_area_code="98101")

    assigned_1 = assign_client(client_1["id"])
    assert assigned_1["assigned_agent_id"] == first_agent["id"], assigned_1

    assigned_2 = assign_client(client_2["id"])
    assert assigned_2["assigned_agent_id"] == second_agent["id"], assigned_2

    assigned_3 = assign_client(client_3["id"])
    assert assigned_3["assigned_agent_id"] == first_agent["id"], assigned_3


def test_selector_load_counts_land_on_the_winning_agents_tally():
    """PRD §3.3: "The winner's `OpenClientCount.active_client_count` increases by one and its `ratio_state` is recomputed."

    Design: Corner/cross_cutting_layers/assignment_selector_ranks_by_load_then_creation_order_within_geography
    """
    region = create_region(target_client_ratio=5.0)
    first_agent = create_lead_agent(region["id"], full_name="Ada Lead", home_zip="98101")
    second_agent = create_lead_agent(region["id"], full_name="Ben Lead", home_zip="98102")

    for i, code in enumerate(["98101", "98102", "98101"]):
        client = create_client(full_name=f"Buyer {i}", service_area_code=code)
        assign_client(client["id"])

    first_occ = get_success_data(api_client.get_open_client_counts(first_agent["id"], PLATFORM_ADMIN))
    second_occ = get_success_data(api_client.get_open_client_counts(second_agent["id"], PLATFORM_ADMIN))
    first_row = first_occ[0] if isinstance(first_occ, list) else first_occ
    second_row = second_occ[0] if isinstance(second_occ, list) else second_occ

    assert first_row["active_client_count"] == 2, first_row
    assert second_row["active_client_count"] == 1, second_row
    assert first_row["ratio_state"] == "UNDER_TARGET", first_row
    assert second_row["ratio_state"] == "UNDER_TARGET", second_row