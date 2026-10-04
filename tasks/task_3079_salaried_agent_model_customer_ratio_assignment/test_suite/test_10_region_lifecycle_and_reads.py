"""Corner tests — region lifecycle, derived reads and immediate consistency (queue B)."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
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
    set_clock,
    DEFAULT_LOGICAL_CLOCK,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_region_create_returns_the_declared_derived_defaults():
    """PRD §3.1: "A freshly created region reports `agent_count` 0, `clients_in_pipeline` 0, `occupancy_pct` 0.0, `referral_count` 0 and `open_referral_count` 0, and its band opens at `UNDER_TARGET`."
    PRD §2.4: "Every entity in the platform carries `id` and `created_at`."

    Design: Corner/entities/region_create_returns_derived_defaults_and_generated_identity
    """
    resp = api_client.create_region(
        {"name": "Puget Sound", "service_area_codes": ["98101", "98102", "98103"],
         "traditional_commission_pct": 0.025, "target_client_ratio": 2.0},
        PLATFORM_ADMIN,
    )
    region = validate_success(resp, expected_status=201)

    assert region["agent_count"] == 0, region
    assert region["clients_in_pipeline"] == 0, region
    assert region["occupancy_pct"] == 0.0, region
    assert region["referral_count"] == 0, region
    assert region["occupancy_band"] == "UNDER_TARGET", region
    assert region["version"] == 1, region
    assert region["id"] and region["created_at"] and region["updated_at"], region


def test_region_create_applies_the_declared_optional_defaults():
    """PRD §3.1: "`capacity`, the size of the region's partner pool for the referral programme, which defaults to 10, and `enrolment_is_required`, which defaults to false".
    PRD §2.4: "`version`, an integer that starts at 1 and increments by exactly 1 on every mutation of the row".

    Design: Corner/entities/region_create_returns_derived_defaults_and_generated_identity
    """
    region = create_region()
    assert region["capacity"] == 10, region
    assert region["enrolment_is_required"] is False, region


def test_region_read_counts_only_clients_still_in_the_pipeline():
    """PRD §2.5: "its `clients_in_pipeline` counts the region's `Client` rows whose `status` is `UNASSIGNED`, `ASSIGNED` or `IN_TRANSACTION`".
    PRD §2.6: "`occupancy_pct` is the number of clients in the pipeline divided by the product of `agent_count` and `target_client_ratio`, rounded half-up to 4 decimal places".

    Design: Corner/endpoints/region_computed_read_matches_an_independent_client_count
    """
    region = create_region(target_client_ratio=4.0)
    lead_a = create_lead_agent(region["id"], full_name="Ada Lead", home_zip="98101")
    create_lead_agent(region["id"], full_name="Ben Lead", home_zip="98102")

    closing = create_client(full_name="First Buyer", service_area_code="98101")
    assign_client(closing["id"])
    tx = open_transaction(closing["id"])
    advance_to_review(tx["id"], 70_000_000)
    close_transaction(tx["id"])

    second = create_client(full_name="Second Buyer", service_area_code="98102")
    assign_client(second["id"])
    create_client(full_name="Third Buyer", service_area_code="98103")

    state = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))
    assert state["clients_in_pipeline"] == 2, state
    assert state["agent_count"] == 2, state
    assert state["occupancy_pct"] == pytest.approx(0.25, abs=1e-4), state

    listed = get_success_data(api_client.list_clients(
        PLATFORM_ADMIN, params={"region_id": region["id"]},
    ))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    assert len(rows) == 3, rows

    closed_client = get_success_data(api_client.get_client(closing["id"], PLATFORM_ADMIN))
    assert closed_client["status"] == "CLOSED", closed_client
    third = get_success_data(api_client.list_clients(
        PLATFORM_ADMIN, params={"region_id": region["id"], "status": "UNASSIGNED"},
    ))
    third_rows = third if isinstance(third, list) else third.get("data", [])
    assert len(third_rows) == 1, third_rows


def test_transaction_close_releases_capacity_within_the_same_request():
    """PRD §2.5: "A transaction reaching `CLOSED` or `CANCELLED` releases capacity in the same request that records the termination, so an agent's coverage never lags behind the event that ended it."
    PRD §2.5: "the caller receives a response in which all of these already agree".

    Design: Corner/consistency_model/close_releases_capacity_immediately_in_the_same_request
    """
    region = create_region(target_client_ratio=5.0)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="Close Me", service_area_code="98101")
    assign_client(client["id"])
    tx = open_transaction(client["id"])
    advance_to_review(tx["id"], 75_000_000)

    before = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))
    assert before["clients_in_pipeline"] == 1, before

    close_transaction(tx["id"])

    after = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))
    assert after["clients_in_pipeline"] == 0, after

    occ = get_success_data(api_client.get_open_client_counts(lead["id"], PLATFORM_ADMIN))
    row = occ[0] if isinstance(occ, list) else occ
    assert row["active_client_count"] == 0, row

    agent = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))
    assert agent["close_rate"] == pytest.approx(1.0, abs=1e-4), agent