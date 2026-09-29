"""Reads that derive rather than store, and listings that stay inside their slice.

A computed summary must recompute its figures on every call and leave the resource
alone; a listing must count the filtered set rather than the page it returns; a
nested route must never show a sibling's rows; and a PATCH must leave every field
it did not name exactly as it found it.
"""

from test_helpers import (
    ApiErrorId,
    ROSTER_LOCK_AT,
    TRANSFER_WINDOW_CLOSE_AT,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    make_coaching_staff_headers,
    make_finance_officer_headers,
    make_general_manager_headers,
    make_league_admin_headers,
    make_ops_manager_headers,
    make_performance_support_headers,
    make_player_agent_headers,
    make_sponsorship_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_both_computed_summaries_derive_their_figures_and_write_nothing():
    """The prorated and full-season variants sit side by side and the contract's version holds.

    PRD: "A dedicated computed read gives the league office, the general manager and finance a
    single view of an organization's cap position: it returns `annual_salary_budget_cents`,
    `committed_salary_cents`, `uncommitted_salary_cents`, `active_roster_count`,
    `prize_payable_cents` and `wellness_flag_count` as stored, plus the two cap-charge variants side
    by side."
    PRD: "`provisional_committed_cents` is the sum of `provisional_cap_charge_cents` over the
    organization's `ACTIVE` and `SUSPENDED` contracts — the same quantity the committed figure
    tracks — while `final_committed_cents` is the sum of `final_cap_charge_cents` over that same set
    of contracts."
    PRD: "A computed obligation summary gathers the whole picture for one contract without
    persisting anything."
    PRD: "It returns the contract's current `obligation_status`, its rolling `burnout_score` and the
    freshly-derived `season_burnout_score`, the `scheduled_minutes_this_week` and
    `streaming_minutes_this_week` that the weekly arithmetic charges for that player together with
    the resulting `cap_minutes`, the frozen `provisional_cap_charge_cents` next to the recomputed
    `final_cap_charge_cents`, and the current `wellness_hold_until`."
    PRD: "Note that the streaming figure reported here is the one the cap arithmetic actually
    charged, which is zero for a player who is not a minor."
    PRD: "Players may be listed with any combination of the filters `player_status`, `region_code`,
    `current_organization_id` and `last_release_organization_id`, and an organization's roster read
    returns the players whose `current_organization_id` or `last_release_organization_id` names that
    organization, optionally narrowed by `player_status`."

    Design: Corner/endpoints/computed_read_endpoints_report_derived_cap_and_obligation_values
    """
    ctx = fixtures.setup_signed_player()
    finance_headers = make_finance_officer_headers()

    cap = validate_success(
        api_client.get_organization_cap_summary(ctx["org"]["id"], finance_headers)
    )
    assert cap["annual_salary_budget_cents"] == 50000000
    assert cap["committed_salary_cents"] == 12328767
    assert cap["uncommitted_salary_cents"] == 37671233
    assert cap["provisional_committed_cents"] == 12328767
    assert cap["final_committed_cents"] == 12500000
    assert cap["active_roster_count"] == 1
    assert cap["prize_payable_cents"] == 0
    assert cap["wellness_flag_count"] == 0

    summary = validate_success(
        api_client.get_contract_obligation_summary(
            ctx["contract"]["id"], make_performance_support_headers()
        )
    )
    assert summary["obligation_status"] == "COMPLIANT"
    assert summary["burnout_score"] == 0
    assert summary["season_burnout_score"] == 0
    assert summary["scheduled_minutes_this_week"] == 0
    assert summary["streaming_minutes_this_week"] == 0
    assert summary["cap_minutes"] == 2700
    assert summary["provisional_cap_charge_cents"] == 12328767
    assert summary["final_cap_charge_cents"] == 12500000
    assert summary["wellness_hold_until"] is None

    contract = validate_success(
        api_client.get_contract(ctx["contract"]["id"], finance_headers)
    )
    assert contract["contract_status"] == "ACTIVE"
    assert contract["base_salary_cents"] == 12500000
    assert contract["prize_split_player_pct_bp"] == 4000
    assert contract["provisional_cap_charge_cents"] == 12328767
    assert contract["version"] == ctx["contract"]["version"]

    rows, meta = validate_paginated(
        api_client.get_organization_roster(
            ctx["org"]["id"],
            ctx["gm_headers"],
            params={"player_status": "SIGNED", "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] == ctx["player"]["id"]
    assert rows[0]["current_organization_id"] == ctx["org"]["id"]


def test_the_top_level_listings_count_the_filtered_set_and_refuse_bad_bounds():
    """total_count survives the page window, has_more flips on the last page, and 0/101/-1 are refused.

    PRD: "Every list endpoint accepts two optional query parameters, `limit` and `offset`."
    PRD: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100; `offset` defaults to 0
    and has a minimum of 0."
    PRD: "A `limit` below 1 or above 100, or a negative `offset`, is a malformed request and is
    refused with `ERR_INVALID_REQUEST` (HTTP 400) rather than being silently clamped."
    PRD: "The `meta` block of a list response carries `limit` and `offset` as they were applied,
    `total_count` as the number of records matching the filters before the page window is applied,
    and `has_more` as true exactly when records remain beyond the current window."
    PRD: "Leagues may be listed page by page, and the organizations competing in one league are
    reachable as a nested read."
    PRD: "Organizations may be listed with an optional `league_id` filter, and the league office may
    later adjust an organization's `annual_salary_budget_cents` or `org_prize_share_bp`, after which
    the uncommitted figure is recomputed and the organization's `version` advances."

    Design: Corner/endpoints/top_level_collection_listings_paginate_with_total_count_and_has_more
    """
    admin_headers = make_league_admin_headers()
    finance_headers = make_finance_officer_headers()

    league_a = fixtures.create_league(name="Apex Masters League")
    league_b = fixtures.create_league(name="Boreal Circuit")
    org_a1 = fixtures.create_organization(league_a["id"], name="Vertex Vanguard")
    org_a2 = fixtures.create_organization(league_a["id"], name="Ember Collective")
    org_a3 = fixtures.create_organization(league_a["id"], name="Northwind Syndicate")
    org_b1 = fixtures.create_organization(league_b["id"], name="Solstice Union")

    first_page, first_meta = validate_paginated(
        api_client.list_leagues(admin_headers, params={"limit": 1, "offset": 0})
    )
    assert len(first_page) == 1
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api_client.list_leagues(finance_headers, params={"limit": 1, "offset": 1})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert {first_page[0]["id"], second_page[0]["id"]} == {league_a["id"], league_b["id"]}

    every_org, every_meta = validate_paginated(
        api_client.list_organizations(admin_headers, params={"limit": 10, "offset": 0})
    )
    assert every_meta["total_count"] == 4
    assert every_meta["has_more"] is False
    assert {row["id"] for row in every_org} == {
        org_a1["id"],
        org_a2["id"],
        org_a3["id"],
        org_b1["id"],
    }

    league_a_page_one, page_one_meta = validate_paginated(
        api_client.list_organizations(
            finance_headers,
            params={"league_id": league_a["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(league_a_page_one) == 2
    assert page_one_meta["total_count"] == 3
    assert page_one_meta["has_more"] is True

    league_a_page_two, page_two_meta = validate_paginated(
        api_client.list_organizations(
            finance_headers,
            params={"league_id": league_a["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(league_a_page_two) == 1
    assert page_two_meta["total_count"] == 3
    assert page_two_meta["has_more"] is False
    assert {row["id"] for row in league_a_page_one + league_a_page_two} == {
        org_a1["id"],
        org_a2["id"],
        org_a3["id"],
    }

    beyond, beyond_meta = validate_paginated(
        api_client.list_organizations(
            finance_headers,
            params={"league_id": league_a["id"], "limit": 2, "offset": 3},
        )
    )
    assert beyond == []
    assert beyond_meta["total_count"] == 3
    assert beyond_meta["has_more"] is False

    validate_error(
        api_client.list_organizations(admin_headers, params={"limit": 0, "offset": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.list_organizations(admin_headers, params={"limit": 101, "offset": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.list_leagues(admin_headers, params={"limit": 10, "offset": -1}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )


def test_every_child_and_filtered_listing_returns_only_its_own_slice():
    """Two organizations, three deals and two deliverables, each reachable from exactly its own route.

    PRD: "Leagues may be listed page by page, and the organizations competing in one league are
    reachable as a nested read."
    PRD: "Deals may be listed with any combination of `organization_id`, `deal_status` and
    `exclusivity_category`, and an organization's deals are also reachable as a nested read
    filterable by `deal_status`."
    PRD: "Assignments may be listed with any combination of `sponsorship_deal_id`, `contract_id` and
    `assignment_status`, and one deal's deliverables are reachable as a nested read filterable by
    `assignment_status`."
    PRD: "Filter query parameters, where an endpoint offers them, combine conjunctively: a request
    that supplies both an organization filter and a status filter returns only records matching
    both."
    PRD: "Its `fee_share_cents` is frozen at creation as the deal's `total_fee_cents` divided by its
    `deliverable_count_required` with the fractional remainder discarded."

    Design: Corner/endpoints/child_and_filtered_listings_scope_to_their_parent
    """
    ctx = fixtures.setup_signed_player()
    org_a = ctx["org"]["id"]
    admin_headers = make_league_admin_headers()
    finance_headers = make_finance_officer_headers()
    org_b = fixtures.create_organization(ctx["league"]["id"], name="Solstice Union")

    deal_a1 = fixtures.setup_active_deal(
        org_a,
        sponsor_name="Voltcharge Energy",
        exclusivity_category="ENERGY_DRINK",
        total_fee_cents=1000000,
        deliverable_count_required=2,
    )
    deal_a2 = fixtures.create_deal(
        org_a, sponsor_name="Kestrel Peripherals", exclusivity_category="PERIPHERALS"
    )
    deal_b1 = fixtures.create_deal(
        org_b["id"], sponsor_name="Loomwear Apparel", exclusivity_category="APPAREL"
    )
    assert deal_a1["deal_status"] == "ACTIVE"
    assert deal_a2["deal_status"] == "DRAFT"
    assert deal_b1["deal_status"] == "DRAFT"

    first_deliverable = fixtures.add_deliverable(
        deal_a1["id"], org_a, ctx["contract"]["id"]
    )
    second_deliverable = fixtures.add_deliverable(
        deal_a1["id"],
        org_a,
        ctx["contract"]["id"],
        deliverable_type="STREAM_SEGMENT",
        due_at="2026-09-15T00:00:00Z",
    )

    nested_orgs, nested_orgs_meta = validate_paginated(
        api_client.list_league_organizations(
            ctx["league"]["id"], finance_headers, params={"limit": 10, "offset": 0}
        )
    )
    assert nested_orgs_meta["total_count"] == 2
    assert {row["id"] for row in nested_orgs} == {org_a, org_b["id"]}

    own_deals, own_deals_meta = validate_paginated(
        api_client.list_organization_sponsorship_deals(
            org_a, ctx["gm_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert own_deals_meta["total_count"] == 2
    assert {row["id"] for row in own_deals} == {deal_a1["id"], deal_a2["id"]}

    active_deals, active_deals_meta = validate_paginated(
        api_client.list_organization_sponsorship_deals(
            org_a,
            ctx["gm_headers"],
            params={"deal_status": "ACTIVE", "limit": 10, "offset": 0},
        )
    )
    assert active_deals_meta["total_count"] == 1
    assert [row["id"] for row in active_deals] == [deal_a1["id"]]

    by_org, by_org_meta = validate_paginated(
        api_client.list_sponsorship_deals(
            admin_headers, params={"organization_id": org_b["id"], "limit": 10, "offset": 0}
        )
    )
    assert by_org_meta["total_count"] == 1
    assert [row["id"] for row in by_org] == [deal_b1["id"]]

    by_category, by_category_meta = validate_paginated(
        api_client.list_sponsorship_deals(
            admin_headers,
            params={"exclusivity_category": "PERIPHERALS", "limit": 10, "offset": 0},
        )
    )
    assert by_category_meta["total_count"] == 1
    assert [row["id"] for row in by_category] == [deal_a2["id"]]

    drafts, drafts_meta = validate_paginated(
        api_client.list_sponsorship_deals(
            admin_headers, params={"deal_status": "DRAFT", "limit": 10, "offset": 0}
        )
    )
    assert drafts_meta["total_count"] == 2
    assert {row["id"] for row in drafts} == {deal_a2["id"], deal_b1["id"]}

    expected_pair = {first_deliverable["id"], second_deliverable["id"]}
    from_the_deal_side, deal_side_meta = validate_paginated(
        api_client.list_deliverable_assignments(
            make_sponsorship_manager_headers(org_a),
            params={"sponsorship_deal_id": deal_a1["id"], "limit": 10, "offset": 0},
        )
    )
    assert deal_side_meta["total_count"] == 2
    assert {row["id"] for row in from_the_deal_side} == expected_pair

    from_the_contract_side, contract_side_meta = validate_paginated(
        api_client.list_deliverable_assignments(
            make_player_agent_headers(ctx["player"]["id"]),
            params={
                "contract_id": ctx["contract"]["id"],
                "assignment_status": "ASSIGNED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert contract_side_meta["total_count"] == 2
    assert {row["id"] for row in from_the_contract_side} == expected_pair
    for row in from_the_contract_side:
        assert row["fee_share_cents"] == 500000
        assert row["sponsorship_deal_id"] == deal_a1["id"]

    nested_deliverables, nested_deliverables_meta = validate_paginated(
        api_client.list_deal_deliverables(
            deal_a1["id"], ctx["gm_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert nested_deliverables_meta["total_count"] == 2
    assert {row["id"] for row in nested_deliverables} == expected_pair

    refreshed_deal = fixtures.read_deal(deal_a1["id"], org_a)
    assert refreshed_deal["assigned_count"] == 2
    assert refreshed_deal["approved_count"] == 0
    assert refreshed_deal["deal_status"] == "ACTIVE"


def test_the_lifecycle_reads_show_the_actor_ids_and_follow_the_status_filter():
    """The waterfall figures and both actor ids are readable, and PENDING stops matching after approval.

    PRD: "Step one takes the association's cut: `association_levy_cents` is `gross_prize_cents`
    multiplied by the league's `player_association_levy_bp`, divided by 10000 and rounded half up;
    what remains after subtracting it is the distributable amount."
    PRD: "The calculation moves `distribution_status` `DRAFT` → `CALCULATED`, stamps
    `calculated_by_user_id` with the calling finance officer's identifier, writes one allocation row
    per eligible contract with `allocation_status` of `CALCULATED` and a `prize_distribution_id` and
    `contract_id` naming its parents, and increases the organization's `prize_payable_cents` by
    `org_share_cents`."
    PRD: "Approval moves the distribution `CALCULATED` → `APPROVED`, moves every child allocation
    `CALCULATED` → `APPROVED`, and stamps `approved_by_user_id`."
    PRD: "Distributions may be listed with any combination of `organization_id`, `league_id` and
    `distribution_status`."
    PRD: "The move is created with `move_status` of `PENDING`, its `requested_by_user_id` stamped
    from the filing manager, its `approved_by_user_id`, `decision_note` and `reversal_reason` null,
    and its five money fields — `buyout_credit_cents`, `commission_tier_bp`,
    `agent_commission_cents`, `net_to_org_cents` and `released_cap_cents` — all at 0."
    PRD: "Moves may be listed with any combination of `organization_id`, `player_id`, `contract_id`,
    `transfer_to_organization_id` and `move_status`, and a single move read exposes its settlement
    figures."

    Design: Corner/endpoints/roster_move_and_distribution_reads_track_their_lifecycle
    """
    ctx = fixtures.setup_signed_player()
    org_id = ctx["org"]["id"]
    admin_headers = make_league_admin_headers()
    finance_headers = make_finance_officer_headers()
    fixtures.set_clock("2026-08-25T00:00:00Z")

    distribution = fixtures.create_distribution(org_id, ctx["league"]["id"])
    fixtures.calculate_distribution(distribution["id"])
    fixtures.approve_distribution(distribution["id"])
    move = fixtures.file_roster_move(
        org_id, ctx["player"]["id"], "RELEASE", ctx["contract"]["id"]
    )

    read_distribution = validate_success(
        api_client.get_prize_distribution(distribution["id"], finance_headers)
    )
    assert read_distribution["distribution_status"] == "APPROVED"
    assert read_distribution["association_levy_cents"] == 250000
    assert read_distribution["org_share_cents"] == 3412500
    assert read_distribution["allocated_cents"] == 6337500
    assert read_distribution["unallocated_cents"] == 0
    assert read_distribution["withholding_total_cents"] == 950625
    assert read_distribution["escrow_total_cents"] == 0
    assert (
        read_distribution["association_levy_cents"]
        + read_distribution["org_share_cents"]
        + read_distribution["allocated_cents"]
        + read_distribution["unallocated_cents"]
        == read_distribution["gross_prize_cents"]
    )
    assert read_distribution["calculated_by_user_id"] == "finance-1"
    assert read_distribution["approved_by_user_id"] == "admin-1"

    approved_rows, approved_meta = validate_paginated(
        api_client.list_prize_distributions(
            finance_headers,
            params={"distribution_status": "APPROVED", "limit": 10, "offset": 0},
        )
    )
    assert approved_meta["total_count"] == 1
    assert [row["id"] for row in approved_rows] == [distribution["id"]]

    _draft_rows, draft_meta = validate_paginated(
        api_client.list_prize_distributions(
            finance_headers,
            params={"distribution_status": "DRAFT", "limit": 10, "offset": 0},
        )
    )
    assert draft_meta["total_count"] == 0

    both_parents, both_parents_meta = validate_paginated(
        api_client.list_prize_distributions(
            ctx["gm_headers"],
            params={
                "organization_id": org_id,
                "league_id": ctx["league"]["id"],
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert both_parents_meta["total_count"] == 1
    assert [row["id"] for row in both_parents] == [distribution["id"]]

    pending_read = validate_success(
        api_client.get_roster_move(move["id"], make_player_agent_headers(ctx["player"]["id"]))
    )
    assert pending_read["move_status"] == "PENDING"
    assert pending_read["requested_by_user_id"] == org_id
    assert pending_read["approved_by_user_id"] is None
    assert pending_read["gross_transfer_fee_cents"] == 0

    _pending_rows, pending_meta = validate_paginated(
        api_client.list_roster_moves(
            admin_headers, params={"move_status": "PENDING", "limit": 10, "offset": 0}
        )
    )
    assert pending_meta["total_count"] == 1

    fixtures.decide_roster_move(
        move["id"], "APPROVE", "admin-9", decision_note="Release cleared"
    )

    approved_read = validate_success(
        api_client.get_roster_move(move["id"], make_general_manager_headers(org_id))
    )
    assert approved_read["move_status"] == "APPROVED"
    assert approved_read["approved_by_user_id"] == "admin-9"

    _still_pending, still_pending_meta = validate_paginated(
        api_client.list_roster_moves(
            admin_headers, params={"move_status": "PENDING", "limit": 10, "offset": 0}
        )
    )
    assert still_pending_meta["total_count"] == 0

    by_parents, by_parents_meta = validate_paginated(
        api_client.list_roster_moves(
            admin_headers,
            params={
                "player_id": ctx["player"]["id"],
                "contract_id": ctx["contract"]["id"],
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert by_parents_meta["total_count"] == 1
    assert by_parents[0]["id"] == move["id"]
    assert by_parents[0]["move_type"] == "RELEASE"


def test_a_patch_touches_only_its_named_fields_and_still_advances_the_version():
    """Two fields change, every untouched default survives, and both versions go 1 to 2.

    PRD: "The remaining charter terms are optional at registration and fall back to league-standard
    defaults: a `minimum_salary_cents` floor of 3,600,000 cents (thirty-six thousand dollars a year)
    which may be any value of zero or more; a `min_roster_size` of 1 and a `max_roster_size` of 7,
    both of which must be zero or more and where the maximum must be greater than or equal to the
    minimum; an `offer_response_window_hours` of 72 (three days), which must be at least 1; and a
    `max_negotiation_rounds` of 3, which must also be at least 1."
    PRD: "A league administrator may later adjust the calendar and the terms, supplying any subset of
    `roster_lock_at`, `transfer_window_open_at`, `transfer_window_close_at`, `minimum_salary_cents`,
    `min_roster_size`, `max_roster_size`, `offer_response_window_hours`, `max_negotiation_rounds`,
    `minor_max_weekly_minutes`, `adult_max_weekly_minutes`, `education_reserved_minutes`,
    `association_min_prize_split_bp`, `association_max_streaming_hours_per_week` and
    `tryout_required_before_offer`."
    PRD: "The derived lock flag is recomputed on the next evaluation and the league's `version`
    advances."
    PRD: "An operations manager may later adjust the facility's `name`, `turnaround_buffer_minutes`
    or `concurrent_seat_capacity`; later bookings are judged against the new values while bookings
    already on the calendar are never re-validated, and the facility's `version` advances."
    PRD: "An organization's facilities are reachable as a nested read, and a single facility read
    returns its buffer and capacity."
    PRD: "`version` is an integer that starts at 1 and increases by exactly 1 on every mutation of
    that resource, whether the mutation was requested directly by a client or produced as a side
    effect of an operation on a different resource."

    Design: Corner/endpoints/patch_endpoints_update_only_the_supplied_fields
    """
    admin_headers = make_league_admin_headers()
    league = validate_success(
        api_client.create_league(
            factories.create_minimal_league_payload(max_negotiation_rounds=3),
            admin_headers,
        ),
        201,
    )
    assert league["version"] == 1
    assert league["adult_max_weekly_minutes"] == 2700
    assert league["max_roster_size"] == 7

    patched_league = validate_success(
        api_client.update_league(
            league["id"],
            {"minimum_salary_cents": 4200000, "min_roster_size": 2},
            admin_headers,
        )
    )
    assert patched_league["minimum_salary_cents"] == 4200000
    assert patched_league["min_roster_size"] == 2
    assert_instant_equals(
        patched_league["roster_lock_at"], ROSTER_LOCK_AT, "League.roster_lock_at"
    )
    assert_instant_equals(
        patched_league["transfer_window_close_at"],
        TRANSFER_WINDOW_CLOSE_AT,
        "League.transfer_window_close_at",
    )
    assert patched_league["max_negotiation_rounds"] == 3
    assert patched_league["max_roster_size"] == 7
    assert patched_league["adult_max_weekly_minutes"] == 2700
    assert patched_league["version"] == 2

    org = fixtures.create_organization(league["id"])
    ops_headers = make_ops_manager_headers(org["id"])
    house = fixtures.create_team_house(
        org["id"], timezone="America/Los_Angeles", concurrent_seat_capacity=5
    )
    assert house["version"] == 1
    assert house["turnaround_buffer_minutes"] == 60

    patched_house = validate_success(
        api_client.update_team_house(
            house["id"], {"turnaround_buffer_minutes": 30}, ops_headers
        )
    )
    assert patched_house["turnaround_buffer_minutes"] == 30
    assert patched_house["name"] == "Vanguard House"
    assert patched_house["timezone"] == "America/Los_Angeles"
    assert patched_house["concurrent_seat_capacity"] == 5
    assert patched_house["version"] == 2

    independent_read = validate_success(
        api_client.get_team_house(house["id"], make_coaching_staff_headers())
    )
    assert independent_read["turnaround_buffer_minutes"] == 30
    assert independent_read["name"] == "Vanguard House"
    assert independent_read["timezone"] == "America/Los_Angeles"
    assert independent_read["concurrent_seat_capacity"] == 5

    houses, houses_meta = validate_paginated(
        api_client.list_organization_team_houses(
            org["id"], ops_headers, params={"limit": 10, "offset": 0}
        )
    )
    assert houses_meta["total_count"] == 1
    assert houses[0]["id"] == house["id"]
    assert houses[0]["organization_id"] == org["id"]
