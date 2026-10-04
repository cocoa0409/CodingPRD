"""Difficulty tests — non-linear state-machine shapes (queue A, rule `non_linear_state_machine`).

The derived capacity posture walks with its child tally, and the referral
machine loops through a late-price supersession instead of terminating.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    OPERATIONS_COORDINATOR,
    PLATFORM_ADMIN,
    TRANSACTION_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    create_referral,
    reconcile_referral,
    assert_referral_split_conserves,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_capacity_posture_is_rederived_from_the_child_count_at_the_floor():
    """PRD §3.4: "the moment `active_client_count` reaches the floor of the region target the posture becomes `AT_CAPACITY`, and the moment it reaches the ceiling the posture becomes `OVER_TARGET`".
    PRD §3.3: "When that count reaches the floor of the region target the winner's `LeadCapacity.current_state` moves to `AT_CAPACITY`."

    Design: Difficulty/non_linear_state_machine/lead_capacity_compound_posture_derived_from_open_client_count_children
    """
    # target 1.5 -> floor 1, ceil 2
    region = create_region(target_client_ratio=1.5)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="C One", service_area_code="98101")
    assign_client(client["id"])

    occ = get_success_data(api_client.get_open_client_counts(lead["id"], PLATFORM_ADMIN))
    row = occ[0] if isinstance(occ, list) else occ
    assert row["active_client_count"] == 1, row
    # count-normalised reading: 1 >= floor(1.5) = 1
    assert row["ratio_state"] == "ON_TARGET", row
    # an absolute-deficit reading would call one client UNDER_TARGET against 1.5
    assert row["ratio_state"] != "UNDER_TARGET", row


def test_capacity_posture_never_moves_to_the_ceiling_band_at_the_floor_count():
    """PRD §3.4: "It is `OPEN` only while the agent is neither at capacity nor past its target and is not on leave; the moment `active_client_count` reaches the floor of the region target the posture becomes `AT_CAPACITY`, and the moment it reaches the ceiling the posture becomes `OVER_TARGET`."

    Design: Difficulty/non_linear_state_machine/lead_capacity_compound_posture_derived_from_open_client_count_children
    """
    region = create_region(target_client_ratio=1.5)
    lead = create_lead_agent(region["id"])
    client = create_client(full_name="C One", service_area_code="98101")
    assign_client(client["id"])

    capacity = get_success_data(api_client.get_lead_capacity(lead["id"], PLATFORM_ADMIN))
    posture = capacity[0] if isinstance(capacity, list) else capacity
    assert posture["current_state"] == "AT_CAPACITY", posture
    assert posture["current_state"] != "OVER_TARGET", posture


def test_referral_reexamination_keeps_the_status_computed_and_reduces_the_fee():
    """PRD §3.8: "A referral already `COMPUTED` is re-derived in place when a superseding price is recorded — the status stays `COMPUTED` and only the fee moves — which keeps the conservation invariant intact because there is no settlement to unwind."

    Design: Difficulty/non_linear_state_machine/agent_referral_cyclic_late_price_supersession_round
    """
    region = create_region(target_client_ratio=2.0)
    create_lead_agent(region["id"])
    overflow = create_client(full_name="Omar Overflow", service_area_code="98101")
    referral = create_referral(overflow["id"], region["id"], referral_fee_bps=1500,
                               split_policy="SPLIT_50_PARTNER")

    first = reconcile_referral(referral["id"], 100_000_000)
    assert first["settlement_status"] == "COMPUTED", first
    # 100000000 * 1500 / 10000 = 15000000
    assert first["referral_fee_cents"] == 15_000_000, first

    superseded = reconcile_referral(referral["id"], 90_000_000)
    assert superseded["settlement_status"] == "COMPUTED", superseded
    assert superseded["referral_fee_cents"] == 13_500_000, superseded


def test_referral_supersession_preserves_the_partner_house_conservation():
    """PRD §2.10: "the partner's side plus the retained side equals the computed fee to the cent, with the retained side defined as the fee minus the partner's side so the equality holds by construction."

    Design: Difficulty/non_linear_state_machine/agent_referral_cyclic_late_price_supersession_round
    """
    region = create_region(target_client_ratio=2.0)
    create_lead_agent(region["id"])
    overflow = create_client(full_name="Omar Overflow", service_area_code="98101")
    referral = create_referral(overflow["id"], region["id"], referral_fee_bps=1500,
                               split_policy="SPLIT_50_PARTNER")

    reconcile_referral(referral["id"], 100_000_000)
    after_first = get_success_data(api_client.get_referral(referral["id"], PLATFORM_ADMIN))
    assert_referral_split_conserves(after_first)
    assert after_first["partner_cents"] == 7_500_000, after_first

    reconcile_referral(referral["id"], 90_000_000)
    after_second = get_success_data(api_client.get_referral(referral["id"], PLATFORM_ADMIN))
    assert_referral_split_conserves(after_second)
    assert after_second["partner_cents"] == 6_750_000, after_second
    assert after_second["house_cents"] == 6_750_000, after_second