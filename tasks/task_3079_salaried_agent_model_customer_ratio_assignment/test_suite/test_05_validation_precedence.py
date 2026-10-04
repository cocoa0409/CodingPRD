"""Difficulty tests — validation priority conflicts (queue A).

The platform reports the earliest failure when a request breaks more than one
rule, so these tests build a request that genuinely violates two rules at once
and pin which one is reported.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    ApiErrorId,
    OPERATIONS_COORDINATOR,
    PLATFORM_ADMIN,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    schedule_tour,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_tour_schedule_reports_the_temporal_conflict_over_the_associate_requirement():
    """PRD §2.1: "Where a single request could fail more than one rule, the platform evaluates the rules in a fixed precedence and reports the earliest failure rather than a later one."
    PRD §2.1: "The temporal and clock-window rules come after that, then the workload-protection rules that force an associate onto a tour or bound the partner pool".
    PRD §3.7: "if the agent already has a tour in `ACCESS_PENDING`, `CONFIRMED` or `COMPLETED` whose block window — the half-hour starting at that tour's `scheduled_at` — overlaps the requested window, the schedule is refused with `ERR_TOUR_SCHEDULE_CONFLICT` (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/tour_priority_5_temporal_out_ranks_6_safety
    """
    # target 2.0 -> floor = ceil = 2, so a single lead agent can hold both clients.
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    client_t = create_client(full_name="Tina Tour", service_area_code="98101")
    client_u = create_client(full_name="Uma View", service_area_code="98102")
    assign_client(client_t["id"])
    assign_client(client_u["id"])

    first = schedule_tour(client_t["id"], "2026-09-02T10:00:00Z")
    assert first["status"] == "ACCESS_PENDING", first

    # This request collides with the 10:00 block window AND omits the associate that
    # the workload-protection rule now demands.
    resp = api_client.create_tour(
        {"client_id": client_u["id"], "scheduled_at": "2026-09-02T10:30:00Z",
         "access_instructions": "Front desk will release the key"},
        OPERATIONS_COORDINATOR,
    )
    data = validate_error(resp, ApiErrorId.ERR_TOUR_SCHEDULE_CONFLICT)
    assert data["error_id"] == "ERR_TOUR_SCHEDULE_CONFLICT", data
    assert data["error_id"] != "ERR_ASSOCIATE_AGENT_REQUIRED", data


def test_tour_schedule_conflict_leaves_the_earlier_tour_as_the_only_row():
    """PRD §3.7: "Two safety rules guard scheduling. The lead agent may not be double-booked: if the agent already has a tour in `ACCESS_PENDING`, `CONFIRMED` or `COMPLETED` whose block window — the half-hour starting at that tour's `scheduled_at` — overlaps the requested window, the schedule is refused with `ERR_TOUR_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/tour_priority_5_temporal_out_ranks_6_safety
    """
    region = create_region(target_client_ratio=1.0)
    lead = create_lead_agent(region["id"])
    client_t = create_client(full_name="Tina Tour", service_area_code="98101")
    client_u = create_client(full_name="Uma View", service_area_code="98102")
    assign_client(client_t["id"])
    assign_client(client_u["id"])

    schedule_tour(client_t["id"], "2026-09-02T10:00:00Z")
    api_client.create_tour(
        {"client_id": client_u["id"], "scheduled_at": "2026-09-02T10:30:00Z",
         "access_instructions": "Front desk will release the key"},
        OPERATIONS_COORDINATOR,
    )

    tours = get_success_data(api_client.list_tours(
        PLATFORM_ADMIN, params={"lead_agent_id": lead["id"]},
    ))
    rows = tours if isinstance(tours, list) else tours.get("data", [])
    assert len(rows) == 1, rows