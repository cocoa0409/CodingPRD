"""Team charge waterfall split and lead terminal lockdown (PRD §3.6, §3.9)."""
from test_helpers import (
    ApiErrorId,
    create_routed_lead,
    get_agent,
    get_share_order,
    make_agent_headers,
    set_clock,
    setup_assigned_lead,
    setup_team_with_order,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTeamChargeSplit:
    def test_waterfall_split_floors_then_reconciles_remainder_to_largest_weight(self, api, marketplace_ops_headers):
        """PRD §3.6: "For team orders the charge is distributed across the team's
        `ACTIVE` memberships in proportion to their `allocation_weight` using a waterfall
        allocation: the platform computes the total of the active members'
        `allocation_weight` values, then computes each member's raw share as the floor of
        the charge multiplied by their `allocation_weight` divided by the total weight,
        then reconciles the remainder one cent at a time to members in order of
        `allocation_weight` descending, breaking ties by `created_at` ascending. Each
        member's `allocated_charge_cents` accumulates their awarded share. The split sums
        exactly to the charge."

        Design: Difficulty/combinatorial_formula/team_charge_split_remainder_allocation
        """
        set_clock()
        # PRD §3.3: order created against an empty market is demand tier 1; at
        # 4000 bps the 5% volume band gives unit_price_cents == 9500, and
        # floor(9500*2/3)=6333 / floor(9500*1/3)=3166 leaves a 1-cent remainder
        # that PRD §3.6 reconciles to the largest weight.
        (market, brokerage, lead_agent, members, team, memberships, order, listing) = setup_team_with_order(
            zip_code="97201", state_code="OR", share_bps=4000, member_weights=(2, 1),
            include_lead_membership=False,
        )
        lead, assignment = create_routed_lead(market["id"], "c-t1@x.com", listing)
        # Any covered member may accept; the finalized charge then splits across the team.
        from test_helpers import accept_lead_offer
        accept_lead_offer(lead, assignment, members[0]["id"])
        fresh_memberships, _ = validate_paginated(
            api.list_team_memberships(marketplace_ops_headers, params={"team_id": team["id"]})
        )
        by_weight = {m["allocation_weight"]: m for m in fresh_memberships}
        assert by_weight[2]["allocated_charge_cents"] == 6334, (
            "floor(9500*2/3)=6333 plus the 1-cent remainder to the largest weight"
        )
        assert by_weight[1]["allocated_charge_cents"] == 3166, "floor(9500*1/3)"
        total = sum(m["allocated_charge_cents"] for m in fresh_memberships)
        assert total == 9500, "the split sums exactly to the charge"
        fresh_order = get_share_order(order["id"])
        assert fresh_order["unit_price_cents"] == 9500
        assert fresh_order["charged_cents"] == 9500
        assert fresh_order["leads_charged"] == 1

    def test_equal_weights_split_evenly_with_remainder_to_earliest(self, api, marketplace_ops_headers):
        """PRD §3.6: "then reconciles the remainder one cent at a time to members in order
        of `allocation_weight` descending, breaking ties by `created_at` ascending. Each
        member's `allocated_charge_cents` accumulates their awarded share. The split sums
        exactly to the charge."

        Design: Difficulty/combinatorial_formula/team_charge_split_remainder_allocation
        """
        set_clock()
        # base 10001 with share_bps=600 (< 2500, no volume discount) at tier 1
        # (empty market) -> charge 10001; the odd charge leaves a 1-cent
        # remainder that PRD §3.6 gives to the earlier-created equal-weight
        # membership.
        (market, brokerage, lead_agent, members, team, memberships, order, listing) = setup_team_with_order(
            zip_code="97202", state_code="OR", share_bps=600, member_weights=(1, 1),
            include_lead_membership=False, base_lead_price_cents=10001,
        )
        lead, assignment = create_routed_lead(market["id"], "c-t2@x.com", listing)
        from test_helpers import accept_lead_offer
        accept_lead_offer(lead, assignment, members[0]["id"])
        fresh_memberships, _ = validate_paginated(
            api.list_team_memberships(marketplace_ops_headers, params={"team_id": team["id"]})
        )
        total = sum(m["allocated_charge_cents"] for m in fresh_memberships)
        assert total == 10001, "the split sums exactly to the charge"
        by_agent = {m["agent_id"]: m["allocated_charge_cents"] for m in fresh_memberships}
        assert by_agent[members[0]["id"]] == 5001, (
            "floor(10001/2)=5000 plus the 1-cent remainder to the earlier membership"
        )
        assert by_agent[members[1]["id"]] == 5000, "the later membership gets floor only"


class TestLeadTerminalLockdown:
    def test_closed_lost_lead_cannot_be_closed_again(self, api, marketplace_ops_headers):
        """PRD §3.9: "Closing is permitted from either `ASSIGNED` or `LIVE_CONNECTED`
        status, and only by the lead's `accepted_agent_id`."
        PRD §5: "`ERR_ALREADY_TERMINAL` | 409".

        Design: Corner/state_machines/lead_starts_new_and_terminal_lockdown
        """
        set_clock()
        market, _, agent, _, lead, _, _ = setup_assigned_lead(
            zip_code="97205", state_code="OR", consumer_key="c-t1@x.com"
        )
        closed = validate_success(
            api.close_lead(lead["id"], {"outcome": "LOST"}, make_agent_headers(agent["id"]))
        )
        assert closed["lead_status"] == "CLOSED_LOST"
        again = api.close_lead(lead["id"], {"outcome": "CONVERTED"}, make_agent_headers(agent["id"]))
        validate_error(again, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        fresh_agent = get_agent(agent["id"])
        assert fresh_agent["leads_closed_lost"] == 1
        assert fresh_agent["leads_converted"] == 0, "rejected second close must not double count"

    def test_closed_converted_lead_is_terminal_too(self, api, marketplace_ops_headers):
        """PRD §3.9: "A `CONVERTED` outcome moves the lead to `CLOSED_CONVERTED` and
        increments the agent's `leads_converted`".
        PRD §5: "`ERR_ALREADY_TERMINAL` | 409".

        Design: Corner/state_machines/lead_starts_new_and_terminal_lockdown
        """
        set_clock()
        market, _, agent, _, lead, _, _ = setup_assigned_lead(
            zip_code="97206", state_code="OR", consumer_key="c-t2@x.com"
        )
        closed = validate_success(
            api.close_lead(lead["id"], {"outcome": "CONVERTED"}, make_agent_headers(agent["id"]))
        )
        assert closed["lead_status"] == "CLOSED_CONVERTED"
        again = api.close_lead(lead["id"], {"outcome": "LOST"}, make_agent_headers(agent["id"]))
        validate_error(again, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        fresh_agent = get_agent(agent["id"])
        assert fresh_agent["leads_converted"] == 1
        assert fresh_agent["leads_closed_lost"] == 0
