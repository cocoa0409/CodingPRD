"""Cascades finish inside the request that triggers them.

Two multi-resource writes are watched twice each: once in the body they return, and
once in the very next read of every resource they touched. Nothing here retries, polls
or sleeps — if a secondary mutation were deferred, the first assertion after the write
would already see the unfinished state.
"""

from test_helpers import (
    ACCEPT_CLOCK,
    OFFER_CLOCK,
    api_client,
    factories,
    fixtures,
    make_finance_officer_headers,
    make_general_manager_headers,
    make_league_admin_headers,
    make_player_agent_headers,
    make_scout_headers,
    make_sponsorship_manager_headers,
    validate_paginated,
    validate_success,
)


def test_the_acceptance_and_the_final_approval_are_complete_when_they_answer():
    """Both cascades report their finished state in the response body and in the next read.

    PRD: "Every entity touched by a cascade has its `updated_at` refreshed and its `version`
    incremented."
    PRD: "Cascades run to completion inside the request that triggered them, so the response body and
    any immediately following read both reflect the finished state — consistency is immediate, never
    eventual."
    PRD: "The response to a successful acceptance is the created contract, with HTTP 201."
    PRD: "Second, because that contract now exists, the player's `player_status` becomes `SIGNED`,
    their `current_organization_id` becomes the offering organization, and both
    `free_agency_window_ends_at` and `last_release_organization_id` are cleared to null."
    PRD: "Third, because the player is now signed under this contract, the organization's
    `committed_salary_cents` increases by the contract's `provisional_cap_charge_cents`, its
    `uncommitted_salary_cents` is recomputed as budget less commitment, and its `active_roster_count`
    increases by 1."
    PRD: "An approval moves it `SUBMITTED` → `APPROVED` and increases the deal's `approved_count` by
    1."
    PRD: "Once `approved_count` equals `deliverable_count_required`, the deal moves `ACTIVE` →
    `FULFILLED` in the same request as the final approval."
    PRD: "Its `fee_share_cents` is frozen at creation as the deal's `total_fee_cents` divided by its
    `deliverable_count_required` with the fractional remainder discarded."

    Design: Corner/consistency model/every_cascade_is_visible_in_the_same_response_and_the_next_read
    """
    ctx = fixtures.setup_league_and_org(org_overrides={"annual_salary_budget_cents": 50000000})
    org_id = ctx["org"]["id"]
    league_id = ctx["league"]["id"]
    gm_headers = make_general_manager_headers(org_id)
    sponsor_headers = make_sponsorship_manager_headers(org_id)
    admin_headers = make_league_admin_headers()

    player = fixtures.create_player()
    player_id = player["id"]
    agent_headers = make_player_agent_headers(player_id)
    assert player["player_status"] == "PROSPECT"

    fixtures.set_clock(OFFER_CLOCK)
    offer = fixtures.create_offer(org_id, player_id, base_salary_cents=12500000)
    fixtures.set_clock(ACCEPT_CLOCK)

    contract = validate_success(
        api_client.accept_contract_offer(
            offer["id"], factories.accept_offer_payload("2026-08-05T00:00:00Z"), agent_headers
        ),
        201,
    )
    assert contract["contract_status"] == "ACTIVE"
    assert contract["obligation_status"] == "COMPLIANT"
    assert contract["provisional_cap_charge_cents"] == 12328767
    assert contract["player_id"] == player_id
    assert contract["organization_id"] == org_id

    organization = validate_success(api_client.get_organization(org_id, admin_headers))
    assert organization["committed_salary_cents"] == 12328767
    assert organization["uncommitted_salary_cents"] == 37671233
    assert organization["active_roster_count"] == 1

    signed_player = validate_success(api_client.get_player(player_id, make_scout_headers()))
    assert signed_player["player_status"] == "SIGNED"
    assert signed_player["current_organization_id"] == org_id
    assert signed_player["free_agency_window_ends_at"] is None
    assert signed_player["last_release_organization_id"] is None

    accepted_offer = validate_success(api_client.get_contract_offer(offer["id"], gm_headers))
    assert accepted_offer["offer_status"] == "ACCEPTED"

    cap = validate_success(
        api_client.get_organization_cap_summary(org_id, make_finance_officer_headers())
    )
    assert cap["committed_salary_cents"] == 12328767
    assert cap["provisional_committed_cents"] == 12328767
    assert cap["active_roster_count"] == 1

    deal = fixtures.create_deal(
        org_id,
        sponsor_name="Voltcharge Energy",
        exclusivity_category="ENERGY_DRINK",
        total_fee_cents=1000000,
        deliverable_count_required=1,
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-12-31T00:00:00Z",
    )
    assert deal["deal_status"] == "DRAFT"
    assert deal["assigned_count"] == 0
    assert deal["approved_count"] == 0

    activated = fixtures.activate_deal(deal["id"], org_id)
    assert activated["deal_status"] == "ACTIVE"
    assert activated["version"] > deal["version"]

    assignment = validate_success(
        api_client.create_deliverable_assignment(
            deal["id"],
            factories.create_deliverable_payload(
                contract["id"],
                activated["version"],
                deliverable_type="STREAM_SEGMENT",
                due_at="2026-08-20T00:00:00Z",
            ),
            sponsor_headers,
        ),
        201,
    )
    assert assignment["assignment_status"] == "ASSIGNED"
    assert assignment["fee_share_cents"] == 1000000
    assert assignment["rejection_count"] == 0

    submitted = validate_success(
        api_client.submit_deliverable_assignment(
            assignment["id"], factories.submit_deliverable_payload(), agent_headers
        )
    )
    assert submitted["assignment_status"] == "SUBMITTED"

    reviewed = validate_success(
        api_client.review_deliverable_assignment(
            assignment["id"],
            factories.review_deliverable_payload("APPROVE"),
            sponsor_headers,
        )
    )
    assert reviewed["assignment_status"] == "APPROVED"
    assert reviewed["rejection_count"] == 0

    fulfilled = validate_success(api_client.get_sponsorship_deal(deal["id"], sponsor_headers))
    assert fulfilled["approved_count"] == 1
    assert fulfilled["assigned_count"] == 1
    assert fulfilled["deal_status"] == "FULFILLED"
    assert fulfilled["version"] > activated["version"]

    reread_assignment = validate_success(
        api_client.get_deliverable_assignment(assignment["id"], sponsor_headers)
    )
    assert reread_assignment["assignment_status"] == "APPROVED"
    assert reread_assignment["rejection_count"] == 0
    assert reread_assignment["fee_share_cents"] == 1000000

    rows, meta = validate_paginated(
        api_client.list_deal_deliverables(
            deal["id"],
            sponsor_headers,
            params={"assignment_status": "APPROVED", "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [assignment["id"]]

    still_committed = validate_success(api_client.get_organization(org_id, admin_headers))
    assert still_committed["committed_salary_cents"] == 12328767
    assert still_committed["active_roster_count"] == 1
    assert still_committed["league_id"] == league_id
