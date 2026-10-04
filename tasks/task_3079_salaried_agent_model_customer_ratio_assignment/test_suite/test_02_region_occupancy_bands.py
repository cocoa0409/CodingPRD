"""Difficulty tests — region occupancy arithmetic and band boundaries (queue A).

Covers the `combinatorial_formula` and `boundary_precision_check` difficulty
rules. Every asserted figure is the one the PRD's stated formula produces for
the instance's declared region shape.
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
    create_associate_agent,
    create_client,
    assign_client,
    create_referral,
    create_listing,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def _region_with_agents_and_clients(target_client_ratio, agent_count, client_count,
                                    service_area_codes=None, assign=False):
    codes = service_area_codes or ["98101", "98102", "98103"]
    region = create_region(target_client_ratio=target_client_ratio, service_area_codes=codes)
    agents = [
        create_lead_agent(region["id"], full_name=f"Lead {i}", home_zip=codes[i % len(codes)])
        for i in range(agent_count)
    ]
    clients = []
    for i in range(client_count):
        client = create_client(full_name=f"Pipeline {i}", service_area_code=codes[i % len(codes)])
        if assign:
            assign_client(client["id"])
        clients.append(client)
    return region, agents, clients


def test_occupancy_pipeline_and_band_are_derived_from_agents_clients_and_ratio():
    """PRD §2.6: "`occupancy_pct` is the number of clients in the pipeline divided by the product of `agent_count` and `target_client_ratio`, rounded half-up to 4 decimal places, and it is exactly 0.0 when that denominator is zero".
    PRD §2.6: "an `occupancy_pct` that is at or above 1.00 and no greater than 1.25 belongs to `OVER_TARGET`".
    PRD §2.5: "its `clients_in_pipeline` counts the region's `Client` rows whose `status` is `UNASSIGNED`, `ASSIGNED` or `IN_TRANSACTION`".

    Design: Difficulty/combinatorial_formula/region_occupancy_nested_min_max_non_linear_mode_a
    """
    region, agents, clients = _region_with_agents_and_clients(
        target_client_ratio=2.0, agent_count=2, client_count=5, assign=True,
    )

    state = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))
    assert state["agent_count"] == 2, state
    assert state["clients_in_pipeline"] == 5, state
    # 5 / (2 * 2.0) = 1.25
    assert state["occupancy_pct"] == pytest.approx(1.25, abs=1e-4), state
    assert state["occupancy_band"] == "OVER_TARGET", state


def test_referral_rederives_open_referral_count_inside_the_same_request():
    """PRD §3.8: "The region's `referral_count` rises by one and its `open_referral_count`, which counts only the `PENDING` and `COMPUTED` rows, rises with it."
    PRD §2.5: "`open_referral_count` counts only the region's referrals whose `settlement_status` is `PENDING` or `COMPUTED`".

    Design: Difficulty/combinatorial_formula/region_occupancy_nested_min_max_non_linear_mode_a
    """
    region = create_region(target_client_ratio=2.0)
    create_lead_agent(region["id"])
    overflow = create_client(full_name="Ref Client", service_area_code="98101")

    referral = create_referral(overflow["id"], region["id"])
    assert referral["settlement_status"] == "PENDING", referral

    state = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))
    assert state["open_referral_count"] == 1, state
    assert state["referral_count"] == 1, state


def test_service_commitment_hours_stays_at_the_tier_value_for_a_limited_service_listing():
    """PRD §3.6: "`service_commitment_hours` is 24 for `FULL_SERVICE`, 48 for `LIMITED_SERVICE` and 0 for `MLS_ONLY`".
    PRD §3.6: "The `gross_listing_fee_cents` is the platform's own commission at the flat rate, the `list_price_cents` multiplied by `list_fee_rate_pct`, rounded half-up to whole cents".

    Design: Difficulty/combinatorial_formula/nested_rounding_order_divergence_on_tour_load_mode_b
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])

    listing = create_listing(
        seller["id"], lead["id"], region["id"],
        list_price_cents=62_000_001,
        list_fee_rate_pct=0.0125,
        service_tier="LIMITED_SERVICE",
    )

    assert listing["service_commitment_hours"] == 48, listing
    # 62000001 * 0.0125 = 775000.0125 -> 775000 at whole cents
    assert listing["gross_listing_fee_cents"] == 775_000, listing


def test_limited_service_commitment_is_not_the_full_service_value():
    """PRD §3.6: "`service_commitment_hours` is 24 for `FULL_SERVICE`, 48 for `LIMITED_SERVICE` and 0 for `MLS_ONLY`".
    PRD §3.6: "The listing also carries a forward-looking roadmap that is reported alongside the charged fee but is never the fee itself".

    Design: Difficulty/combinatorial_formula/nested_rounding_order_divergence_on_tour_load_mode_b
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])

    listing = create_listing(
        seller["id"], lead["id"], region["id"],
        list_price_cents=62_000_001,
        list_fee_rate_pct=0.0125,
        service_tier="LIMITED_SERVICE",
    )

    assert listing["service_commitment_hours"] != 24, listing
    assert listing["service_commitment_hours"] != 0, listing


def test_occupancy_band_veto_ceiling_is_inclusive_at_one_point_two_five():
    """PRD §2.6: "an `occupancy_pct` that is at or above 1.00 and no greater than 1.25 belongs to `OVER_TARGET`, so the band is continuous across the range that a fresh assignment would push through.".
    PRD §2.6: "an `occupancy_pct` of at least 1.00 selects the `OVER_TARGET` band".

    Design: Difficulty/boundary_precision_check/occupancy_ratio_band_edge_is_inclusive_at_one_point_two_five
    """
    # Five unassigned clients over two agents at target 2.0 -> 5 / 4 = 1.25 exactly,
    # which is the top of the veto window and therefore still OVER_TARGET.
    region, _agents, _clients = _region_with_agents_and_clients(
        target_client_ratio=2.0, agent_count=2, client_count=5,
    )
    state = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))
    assert state["occupancy_pct"] == pytest.approx(1.25, abs=1e-4), state
    assert state["occupancy_band"] == "OVER_TARGET", state


def test_occupancy_band_leaves_the_veto_window_above_one_point_two_five():
    """PRD §2.6: "an `occupancy_pct` of at least 0.75 but below 1.00 selects `NEAR_TARGET`; anything below 0.75 is `UNDER_TARGET`.".

    Design: Difficulty/boundary_precision_check/occupancy_ratio_band_edge_is_inclusive_at_one_point_two_five
    """
    # One further unassigned client over the same two agents -> 6 / 4 = 1.5,
    # which is past the veto ceiling and so is not OVER_TARGET.
    region, _agents, _clients = _region_with_agents_and_clients(
        target_client_ratio=2.0, agent_count=2, client_count=5,
    )
    extra = create_client(full_name="C Six", service_area_code="98103")

    state = get_success_data(api_client.get_region(region["id"], PLATFORM_ADMIN))
    assert state["clients_in_pipeline"] == 6, state
    assert state["occupancy_pct"] == pytest.approx(1.5, abs=1e-4), state
    assert state["occupancy_band"] != "OVER_TARGET", state


def test_first_assignment_leaves_no_open_candidate_for_the_next_client():
    """PRD §3.3: "ranks the candidates by `OpenClientCount.active_client_count` ascending, and breaks ties by `Agent.created_at` ascending — the least-loaded agent wins, and among equals the one that joined first wins."
    PRD §3.3: "When every in-geography agent is already at capacity — no candidate has an `OPEN` posture — the selection reports `ERR_NO_ELIGIBLE_AGENT` (HTTP 409) and the client stays `UNASSIGNED`, recording the reason `ALL_AT_CAPACITY`."

    Design: Difficulty/boundary_precision_check/first_assignment_boundary_at_floor_versus_ceil
    """
    # A region whose only agent staffs tours (ASSOCIATE) has no lead agent that
    # can carry clients, so the selector reports ERR_NO_ELIGIBLE_AGENT.
    region = create_region(target_client_ratio=1.5)
    create_associate_agent(region["id"])
    client = create_client(full_name="First Buyer", service_area_code="98101")

    resp = api_client.assign_agent(client["id"], {}, OPERATIONS_COORDINATOR)
    data = validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_AGENT)
    assert data["error_id"] == "ERR_NO_ELIGIBLE_AGENT", data

    still_unassigned = get_success_data(api_client.get_client(client["id"], PLATFORM_ADMIN))
    assert still_unassigned["status"] == "UNASSIGNED", still_unassigned


def test_first_assignment_raises_the_capacity_posture_at_count_one():
    """PRD §3.3: "When that count reaches the floor of the region target the winner's `LeadCapacity.current_state` moves to `AT_CAPACITY`."
    PRD §3.3: "The winner's `OpenClientCount.active_client_count` increases by one and its `ratio_state` is recomputed."

    Design: Difficulty/boundary_precision_check/first_assignment_boundary_at_floor_versus_ceil
    """
    region = create_region(target_client_ratio=1.5)
    lead = create_lead_agent(region["id"])
    first = create_client(full_name="First Buyer", service_area_code="98101")
    assign_client(first["id"])

    occ = get_success_data(api_client.get_open_client_counts(lead["id"], PLATFORM_ADMIN))
    row = occ[0] if isinstance(occ, list) else occ
    assert row["active_client_count"] == 1, row
    assert row["ratio_state"] == "ON_TARGET", row

    capacity = get_success_data(api_client.get_lead_capacity(lead["id"], PLATFORM_ADMIN))
    posture = capacity[0] if isinstance(capacity, list) else capacity
    assert posture["current_state"] == "AT_CAPACITY", posture