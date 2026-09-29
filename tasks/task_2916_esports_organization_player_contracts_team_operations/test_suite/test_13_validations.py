"""Conditional, temporal and cross-entity gates, each checked at its own boundary.

Several of these tests deliberately build one request that violates two rules at
once, so the reported error identifies which precedence band ran first.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    make_coaching_staff_headers,
    make_general_manager_headers,
    make_guardian_representative_headers,
    make_league_admin_headers,
    make_performance_support_headers,
    make_player_agent_headers,
    make_scout_headers,
    make_sponsorship_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_two_association_terms_bind_members_only_and_the_salary_floor_binds_everyone():
    """The same body is legal for a non-member and illegal for a member; boundary values pass.

    PRD: "The salary floor is universal: on the initial offer, on a counter, on a revision and at
    acceptance, the base salary in question — the countered value when an agent is countering, the
    revised value when a manager is revising, otherwise the offer's own `base_salary_cents` — must be
    greater than or equal to the league's `minimum_salary_cents`, failing which the request is refused
    with `ERR_BELOW_MINIMUM_SALARY` (HTTP 422)."
    PRD: "For such a player, `prize_split_player_pct_bp` must be greater than or equal to the league's
    `association_min_prize_split_bp` or the request is refused with
    `ERR_PRIZE_SPLIT_BELOW_ASSOCIATION_MIN` (HTTP 422), and `streaming_hours_per_week` must be less than
    or equal to the league's `association_max_streaming_hours_per_week` or the request is refused with
    `ERR_STREAMING_HOURS_EXCEED_ASSOCIATION_MAX` (HTTP 422)."
    PRD: "For a player who is not an association member neither of the two applies at all."
    PRD: "Offers may be listed with any combination of the filters `organization_id`, `player_id`,
    `supersedes_offer_id` and `offer_status`, which together make the whole negotiation chain —
    including its superseded links — reconstructible."

    Design: Corner/validations/association_terms_bind_members_only_while_the_salary_floor_is_universal
    """
    ctx = fixtures.setup_league_and_org()
    org_id = ctx["org"]["id"]
    gm_headers = make_general_manager_headers(org_id)
    member = fixtures.create_player(full_name="Rin Adachi", association_member=True)
    outsider = fixtures.create_player(
        full_name="Marek Rus", birth_date="2000-03-02", association_member=False
    )

    def offer(player_id, **terms):
        return api_client.create_contract_offer(
            factories.create_contract_offer_payload(org_id, player_id, **terms), gm_headers
        )

    validate_error(
        offer(
            member["id"],
            base_salary_cents=3599999,
            prize_split_player_pct_bp=4000,
            streaming_hours_per_week=20,
        ),
        ApiErrorId.ERR_BELOW_MINIMUM_SALARY.value,
        422,
    )
    validate_error(
        offer(
            member["id"],
            base_salary_cents=4000000,
            prize_split_player_pct_bp=3999,
            streaming_hours_per_week=20,
        ),
        ApiErrorId.ERR_PRIZE_SPLIT_BELOW_ASSOCIATION_MIN.value,
        422,
    )
    validate_error(
        offer(
            member["id"],
            base_salary_cents=4000000,
            prize_split_player_pct_bp=4000,
            streaming_hours_per_week=21,
        ),
        ApiErrorId.ERR_STREAMING_HOURS_EXCEED_ASSOCIATION_MAX.value,
        422,
    )

    member_offer = validate_success(
        offer(
            member["id"],
            base_salary_cents=3600000,
            prize_split_player_pct_bp=4000,
            streaming_hours_per_week=20,
        ),
        201,
    )
    assert member_offer["offer_status"] == "SENT"
    assert member_offer["base_salary_cents"] == 3600000

    outsider_offer = validate_success(
        offer(
            outsider["id"],
            base_salary_cents=3600000,
            prize_split_player_pct_bp=3999,
            streaming_hours_per_week=40,
        ),
        201,
    )
    assert outsider_offer["prize_split_player_pct_bp"] == 3999
    assert outsider_offer["streaming_hours_per_week"] == 40

    validate_error(
        offer(
            outsider["id"],
            base_salary_cents=3599999,
            prize_split_player_pct_bp=3999,
            streaming_hours_per_week=40,
        ),
        ApiErrorId.ERR_BELOW_MINIMUM_SALARY.value,
        422,
    )

    rows, meta = validate_paginated(
        api_client.list_contract_offers(
            gm_headers, params={"organization_id": org_id, "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {member_offer["id"], outsider_offer["id"]}


def test_a_roster_pinned_at_one_seat_can_neither_grow_nor_shrink():
    """The ceiling refuses a second acceptance and the floor refuses the approved release.

    PRD: "The organization's `active_roster_count` must be strictly less than the league's
    `max_roster_size`, or `ERR_ROSTER_SIZE_EXCEEDED` (HTTP 422) is returned."
    PRD: "For both `RELEASE` and `TRANSFER_OUT` the departure must leave a legal squad: the
    organization's `active_roster_count` less one must remain greater than or equal to the league's
    `min_roster_size`, and a departure that would take the roster below that floor is refused with
    `ERR_ROSTER_SIZE_BELOW_MINIMUM` (HTTP 422)."
    PRD: "`active_roster_count` is the count of the organization's contracts whose `contract_status` is
    exactly `ACTIVE`, so a suspended contract still consumes budget while no longer counting as a roster
    seat."
    PRD: "`uncommitted_salary_cents` is `annual_salary_budget_cents` less `committed_salary_cents`."

    Design: Corner/validations/roster_size_upper_and_lower_bounds_are_both_enforced
    """
    ctx = fixtures.setup_signed_player(
        league_overrides={"min_roster_size": 1, "max_roster_size": 1}
    )
    org_id = ctx["org"]["id"]
    gm_headers = make_general_manager_headers(org_id)

    second_player = fixtures.create_player(**fixtures.SECOND_PLAYER)
    second_offer = fixtures.create_offer(org_id, second_player["id"])
    refused_acceptance = api_client.accept_contract_offer(
        second_offer["id"],
        {"effective_at": "2026-08-05T00:00:00Z"},
        make_player_agent_headers(second_player["id"]),
    )
    validate_error(refused_acceptance, ApiErrorId.ERR_ROSTER_SIZE_EXCEEDED.value, 422)

    still_open = validate_success(
        api_client.get_contract_offer(second_offer["id"], gm_headers)
    )
    assert still_open["offer_status"] == "SENT"
    assert (
        validate_success(
            api_client.get_player(second_player["id"], make_scout_headers())
        )["player_status"]
        == "PROSPECT"
    )

    move = fixtures.file_roster_move(
        org_id, ctx["player"]["id"], "RELEASE", ctx["contract"]["id"]
    )
    fixtures.decide_roster_move(move["id"], "APPROVE", "admin-9")
    validate_error(
        api_client.execute_roster_move(move["id"], gm_headers),
        ApiErrorId.ERR_ROSTER_SIZE_BELOW_MINIMUM.value,
        422,
    )

    unchanged = validate_success(api_client.get_roster_move(move["id"], gm_headers))
    assert unchanged["move_status"] == "APPROVED"
    assert unchanged["released_cap_cents"] == 0
    assert (
        validate_success(api_client.get_contract(ctx["contract"]["id"], gm_headers))[
            "contract_status"
        ]
        == "ACTIVE"
    )
    assert (
        validate_success(
            api_client.get_player(ctx["player"]["id"], make_scout_headers())
        )["player_status"]
        == "SIGNED"
    )

    cap_summary = validate_success(
        api_client.get_organization_cap_summary(org_id, gm_headers)
    )
    assert cap_summary["active_roster_count"] == 1
    assert cap_summary["committed_salary_cents"] == 12328767
    assert cap_summary["uncommitted_salary_cents"] == 37671233

    _rows, meta = validate_paginated(
        api_client.list_contracts(
            gm_headers,
            params={
                "organization_id": org_id,
                "contract_status": "ACTIVE",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1


def test_the_season_the_transfer_window_and_the_roster_lock_each_bite_at_their_boundary():
    """Three priority-10 window rules on three endpoints, each tested one second either side.

    PRD: "The supplied or defaulted `effective_at` must fall at or after the league's `season_start_at`
    and strictly before its `season_end_at`, or `ERR_EFFECTIVE_AT_OUTSIDE_SEASON` (HTTP 422) is
    returned."
    PRD: "A `SIGN` filing is refused with `ERR_ROSTER_LOCK_ACTIVE` once the current instant has reached
    the league's `roster_lock_at`, and a `TRANSFER_OUT` filing is refused with
    `ERR_TRANSFER_WINDOW_CLOSED` (HTTP 422) unless the current instant falls at or after
    `transfer_window_open_at` and strictly before `transfer_window_close_at`."
    PRD: "The league's roster lock must not be active — once the current instant has reached
    `roster_lock_at`, no offer may be accepted at all and the refusal is `ERR_ROSTER_LOCK_ACTIVE` (HTTP
    422)."
    PRD: "`roster_lock_active` is true exactly when the current instant has reached `roster_lock_at`,
    and false while the current instant is still earlier than that."

    Design: Corner/validations/season_transfer_and_roster_lock_windows_each_gate_their_own_operation
    """
    ctx = fixtures.setup_league_and_org()
    org_one = ctx["org"]["id"]
    org_two = fixtures.create_organization(ctx["league"]["id"], name="Northwind Nine")["id"]
    gm_headers = make_general_manager_headers(org_one)
    player_one = fixtures.create_player(full_name="Rin Adachi")
    player_two = fixtures.create_player(**fixtures.SECOND_PLAYER)

    fixtures.set_clock("2026-08-04T00:00:00Z")
    offer_one = fixtures.create_offer(org_one, player_one["id"])
    fixtures.set_clock("2026-08-05T00:00:00Z")
    agent_one = make_player_agent_headers(player_one["id"])

    validate_error(
        api_client.accept_contract_offer(
            offer_one["id"], {"effective_at": "2027-07-31T00:00:00Z"}, agent_one
        ),
        ApiErrorId.ERR_EFFECTIVE_AT_OUTSIDE_SEASON.value,
        422,
    )
    validate_error(
        api_client.accept_contract_offer(
            offer_one["id"], {"effective_at": "2026-07-31T23:59:59Z"}, agent_one
        ),
        ApiErrorId.ERR_EFFECTIVE_AT_OUTSIDE_SEASON.value,
        422,
    )
    contract_one = validate_success(
        api_client.accept_contract_offer(
            offer_one["id"], {"effective_at": "2026-08-05T00:00:00Z"}, agent_one
        ),
        201,
    )
    assert contract_one["provisional_cap_charge_cents"] == 12328767

    fixtures.set_clock("2026-08-30T23:59:59Z")
    inside_window = fixtures.file_roster_move(
        org_one,
        player_one["id"],
        "TRANSFER_OUT",
        contract_one["id"],
        transfer_to_organization_id=org_two,
        gross_transfer_fee_cents=8000000,
    )
    assert inside_window["move_status"] == "PENDING"

    fixtures.set_clock("2026-08-31T00:00:00Z")
    validate_error(
        api_client.create_roster_move(
            factories.create_roster_move_payload(
                org_one,
                player_one["id"],
                "TRANSFER_OUT",
                contract_one["id"],
                fixtures.current_organization_version(org_one),
                transfer_to_organization_id=org_two,
                gross_transfer_fee_cents=8000000,
            ),
            gm_headers,
        ),
        ApiErrorId.ERR_TRANSFER_WINDOW_CLOSED.value,
        422,
    )

    fixtures.set_clock("2026-09-15T00:00:00Z")
    late_offer = fixtures.create_offer(org_one, player_two["id"])
    assert late_offer["offer_status"] == "SENT"
    validate_error(
        api_client.accept_contract_offer(
            late_offer["id"],
            {"effective_at": "2026-09-20T00:00:00Z"},
            make_player_agent_headers(player_two["id"]),
        ),
        ApiErrorId.ERR_ROSTER_LOCK_ACTIVE.value,
        422,
    )
    validate_error(
        api_client.create_roster_move(
            factories.create_roster_move_payload(
                org_one,
                player_one["id"],
                "SIGN",
                contract_one["id"],
                fixtures.current_organization_version(org_one),
            ),
            gm_headers,
        ),
        ApiErrorId.ERR_ROSTER_LOCK_ACTIVE.value,
        422,
    )

    league = validate_success(
        api_client.get_league(ctx["league"]["id"], make_league_admin_headers())
    )
    assert league["roster_lock_active"] is True
    organization = validate_success(api_client.get_organization(org_one, gm_headers))
    assert organization["active_roster_count"] == 1
    assert organization["committed_salary_cents"] == 12328767


def test_the_cooldown_outranks_the_tryout_gate_and_only_binds_the_releasing_club():
    """The same released player, two clubs, two different refusals from the same payload.

    PRD: "When the league's `tryout_required_before_offer` is true the player's `player_status` must be
    `TRYOUT_COMPLETED` at acceptance time, or `ERR_TRYOUT_REQUIRED` (HTTP 422) is returned; when it is
    false a `PROSPECT` or `FREE_AGENT` player is equally acceptable."
    PRD: "Where the player was released by this very organization and is still inside the cooldown, the
    refusal is `ERR_FREE_AGENCY_COOLDOWN` (HTTP 422); an offer from any *other* organization is
    unaffected."
    PRD: "On a `TRYOUT` block, completion additionally advances every attendee sitting in
    `TRYOUT_INVITED` to `TRYOUT_COMPLETED`."
    PRD: "Second, because the contract terminated, the player's `player_status` becomes `FREE_AGENT`,
    their `current_organization_id` is cleared to null, their `free_agency_window_ends_at` is stamped at
    the current instant plus the league's `free_agency_cooldown_days` days, and their
    `last_release_organization_id` is set to the releasing organization — the pair that will later block
    a re-signing by that same organization while allowing any other organization to sign the player
    immediately."

    Design: Corner/validations/tryout_requirement_and_free_agency_cooldown_gate_acceptance_in_priority_order
    """
    ctx = fixtures.setup_league_and_org(
        league_overrides={
            "tryout_required_before_offer": True,
            "free_agency_cooldown_days": 14,
            "min_roster_size": 1,
        }
    )
    org_one = ctx["org"]["id"]
    org_two = fixtures.create_organization(ctx["league"]["id"], name="Northwind Nine")["id"]
    house = fixtures.create_team_house(org_one)
    player_a = fixtures.create_player(full_name="Rin Adachi")
    player_b = fixtures.create_player(**fixtures.SECOND_PLAYER)
    agent_a = make_player_agent_headers(player_a["id"])

    fixtures.set_clock("2026-08-01T00:00:00Z")
    offer_a = fixtures.create_offer(org_one, player_a["id"])
    validate_error(
        api_client.accept_contract_offer(
            offer_a["id"], {"effective_at": "2026-08-05T00:00:00Z"}, agent_a
        ),
        ApiErrorId.ERR_TRYOUT_REQUIRED.value,
        422,
    )

    tryout = fixtures.create_practice_block(
        org_one,
        house["id"],
        "2026-08-02T10:00:00Z",
        "2026-08-02T14:00:00Z",
        [player_a["id"], player_b["id"]],
        block_type="TRYOUT",
    )
    fixtures.set_clock("2026-08-02T14:00:00Z")
    held = fixtures.complete_practice_block(tryout["id"])
    assert held["block_status"] == "HELD"
    assert (
        validate_success(api_client.get_player(player_a["id"], make_scout_headers()))[
            "player_status"
        ]
        == "TRYOUT_COMPLETED"
    )

    contract_a = validate_success(
        api_client.accept_contract_offer(
            offer_a["id"], {"effective_at": "2026-08-05T00:00:00Z"}, agent_a
        ),
        201,
    )
    offer_b = fixtures.create_offer(org_one, player_b["id"])
    fixtures.accept_offer(offer_b["id"], player_b["id"])

    fixtures.set_clock("2026-08-10T00:00:00Z")
    move = fixtures.file_roster_move(org_one, player_a["id"], "RELEASE", contract_a["id"])
    fixtures.decide_roster_move(move["id"], "APPROVE", "admin-9")
    executed = fixtures.execute_roster_move(move["id"], org_one)
    assert executed["move_status"] == "EXECUTED"

    released = validate_success(
        api_client.get_player(player_a["id"], make_scout_headers())
    )
    assert released["player_status"] == "FREE_AGENT"
    assert_instant_equals(
        released["free_agency_window_ends_at"],
        "2026-08-24T00:00:00Z",
        "Player.free_agency_window_ends_at",
    )
    assert released["last_release_organization_id"] == org_one
    assert released["current_organization_id"] is None
    assert (
        validate_success(
            api_client.get_contract(contract_a["id"], make_general_manager_headers(org_one))
        )["contract_status"]
        == "TERMINATED"
    )
    organization = validate_success(
        api_client.get_organization(org_one, make_general_manager_headers(org_one))
    )
    assert organization["committed_salary_cents"] == 12328767
    assert organization["active_roster_count"] == 1

    re_offer = fixtures.create_offer(org_one, player_a["id"])
    validate_error(
        api_client.accept_contract_offer(
            re_offer["id"], {"effective_at": "2026-08-15T00:00:00Z"}, agent_a
        ),
        ApiErrorId.ERR_FREE_AGENCY_COOLDOWN.value,
        422,
    )

    rival_offer = fixtures.create_offer(org_two, player_a["id"])
    validate_error(
        api_client.accept_contract_offer(
            rival_offer["id"], {"effective_at": "2026-08-15T00:00:00Z"}, agent_a
        ),
        ApiErrorId.ERR_TRYOUT_REQUIRED.value,
        422,
    )

    _rows, meta = validate_paginated(
        api_client.list_contracts(
            make_general_manager_headers(org_one),
            params={"player_id": player_a["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1


def test_one_consent_gate_guards_three_endpoints_and_betting_stays_forbidden():
    """Acceptance and booking unlock together, the guardian cap overrides the league ceiling, and BETTING never opens.

    PRD: "Consent is exactly what unlocks three otherwise-forbidden things for a minor: accepting a
    contract offer on that player's behalf, listing that player as a participant on a practice block, and
    placing a sponsorship deliverable on that player's contract. In all three, a minor whose
    `guardian_consent_status` is not `GRANTED` is refused with `ERR_GUARDIAN_CONSENT_REQUIRED` (HTTP
    422)."
    PRD: "Independently of consent, a deal whose `exclusivity_category` is `BETTING` or `CRYPTO` may
    never carry a deliverable for a minor player's contract at all, and such a placement is refused with
    `ERR_MINOR_CATEGORY_FORBIDDEN` (HTTP 422) — no guardian can waive that one."
    PRD: "A drafted deal has `deal_status` of `DRAFT`, `assigned_count` and `approved_count` both 0, and
    one derived flag: `minor_permitted` is false when the `exclusivity_category` is `ENERGY_DRINK`,
    `BETTING` or `CRYPTO`, and true for `PERIPHERALS` and `APPAREL`."
    PRD: "For a minor it is the smaller of the league's `minor_max_weekly_minutes` and the player's
    `guardian_weekly_cap_minutes`, treating a null guardian cap as if it equalled the league ceiling, and
    then, only when the minor's `education_enrollment_status` is exactly `ENROLLED_FULL_TIME`, reduced by
    the league's `education_reserved_minutes`."
    PRD: "Their **streaming minutes** are added on top: for a minor who owns a contract in `ACTIVE` or
    `SUSPENDED`, the contract's `streaming_hours_per_week` multiplied by 60; for a player who is not a
    minor, or for one who owns no such contract, zero."
    PRD: "Its `fee_share_cents` is frozen at creation as the deal's `total_fee_cents` divided by its
    `deliverable_count_required` with the fractional remainder discarded."

    Design: Corner/validations/minor_protections_require_consent_and_forbid_restricted_categories
    """
    ctx = fixtures.setup_league_and_org()
    org_id = ctx["org"]["id"]
    house = fixtures.create_team_house(org_id)
    coach_headers = make_coaching_staff_headers()
    sponsor_headers = make_sponsorship_manager_headers(org_id)

    minor = fixtures.create_minor_player(birth_date="2010-02-20")
    assert minor["age_years"] == 16
    assert minor["is_minor"] is True
    assert minor["guardian_consent_status"] == "REQUIRED"

    betting_deal = fixtures.setup_active_deal(
        org_id,
        sponsor_name="Luckystrike Bets",
        exclusivity_category="BETTING",
        total_fee_cents=1000000,
        deliverable_count_required=1,
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-09-01T00:00:00Z",
    )
    apparel_deal = fixtures.setup_active_deal(
        org_id,
        sponsor_name="Northline Apparel",
        exclusivity_category="APPAREL",
        total_fee_cents=1000000,
        deliverable_count_required=1,
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-09-01T00:00:00Z",
    )
    assert betting_deal["minor_permitted"] is False
    assert apparel_deal["minor_permitted"] is True

    fixtures.set_clock("2026-08-04T00:00:00Z")
    offer = fixtures.create_offer(org_id, minor["id"])
    fixtures.set_clock("2026-08-05T00:00:00Z")
    agent_headers = make_player_agent_headers(minor["id"])
    block_payload = {
        "organization_id": org_id,
        "team_house_id": house["id"],
        "block_type": "TRYOUT",
        "starts_at": "2026-08-10T10:00:00Z",
        "ends_at": "2026-08-10T14:00:00Z",
        "participant_player_ids": [minor["id"]],
    }

    validate_error(
        api_client.accept_contract_offer(
            offer["id"], {"effective_at": "2026-08-05T00:00:00Z"}, agent_headers
        ),
        ApiErrorId.ERR_GUARDIAN_CONSENT_REQUIRED.value,
        422,
    )
    validate_error(
        api_client.create_practice_block(block_payload, coach_headers),
        ApiErrorId.ERR_GUARDIAN_CONSENT_REQUIRED.value,
        422,
    )

    consented = validate_success(
        api_client.grant_guardian_consent(
            minor["id"],
            {
                "guardian_name": "Alma Mendoza",
                "guardian_email": "alma@example.com",
                "guardian_weekly_cap_minutes": 900,
            },
            make_guardian_representative_headers(minor["id"]),
        )
    )
    assert consented["guardian_consent_status"] == "GRANTED"
    assert consented["guardian_weekly_cap_minutes"] == 900

    contract = validate_success(
        api_client.accept_contract_offer(
            offer["id"], {"effective_at": "2026-08-05T00:00:00Z"}, agent_headers
        ),
        201,
    )
    assert contract["provisional_cap_charge_cents"] == 12328767
    scrim_payload = dict(block_payload, block_type="SCRIM")
    booked = validate_success(
        api_client.create_practice_block(scrim_payload, coach_headers), 201
    )
    assert booked["duration_minutes"] == 240

    validate_error(
        api_client.create_deliverable_assignment(
            betting_deal["id"],
            factories.create_deliverable_payload(
                contract["id"],
                fixtures.current_deal_version(betting_deal["id"], org_id),
                due_at="2026-08-25T00:00:00Z",
            ),
            sponsor_headers,
        ),
        ApiErrorId.ERR_MINOR_CATEGORY_FORBIDDEN.value,
        422,
    )
    assert (
        validate_success(
            api_client.get_sponsorship_deal(betting_deal["id"], sponsor_headers)
        )["assigned_count"]
        == 0
    )

    assignment = fixtures.add_deliverable(
        apparel_deal["id"], org_id, contract["id"], due_at="2026-08-25T00:00:00Z"
    )
    assert assignment["fee_share_cents"] == 1000000
    assert assignment["assignment_status"] == "ASSIGNED"

    fixtures.set_clock("2026-08-10T00:00:00Z")
    summary = validate_success(
        api_client.get_contract_obligation_summary(
            contract["id"], make_performance_support_headers()
        )
    )
    assert summary["cap_minutes"] == 900
    assert summary["streaming_minutes_this_week"] == 600
    assert summary["scheduled_minutes_this_week"] == 240


def test_the_hold_expires_on_its_boundary_while_the_breach_never_lifts():
    """One report drives the score to 100; a week later practice reopens and commercial work does not.

    PRD: "Only entry into `BREACH` additionally stamps `wellness_hold_until` at the current instant plus
    seven days and increases the organization's `wellness_flag_count` by 1; a `WARNED` escalation stamps
    neither."
    PRD: "An attendee with an `ACTIVE` contract whose `wellness_hold_until` the current instant has not
    yet reached causes `ERR_WELLNESS_HOLD_ACTIVE` (HTTP 409) — the hold lifts on the boundary instant
    itself."
    PRD: "The wellness dimension is escalation-only — `COMPLIANT` may move to `WARNED` or straight to
    `BREACH`, and `WARNED` may move to `BREACH`, but nothing ever moves back down, so `BREACH` is terminal
    for that dimension."
    PRD: "The target contract's `contract_status` must be `ACTIVE`, or the placement is refused with
    `ERR_CONTRACT_NOT_ACTIVE`; its `obligation_status` must not be `BREACH`, since a breached contract
    accepts no new commercial work, and a breached one is refused with
    `ERR_OBLIGATION_BREACH_BLOCKS_ASSIGNMENT` (HTTP 422)."
    PRD: "The three weighted components are summed at full precision, multiplied by 100, and only then
    rounded half up exactly once to a whole integer."

    Design: Corner/validations/wellness_breach_stamps_a_hold_that_expires_while_the_breach_does_not
    """
    ctx = fixtures.setup_signed_player(with_team_house=True)
    org_id = ctx["org"]["id"]
    contract_id = ctx["contract"]["id"]
    coach_headers = make_coaching_staff_headers()
    sponsor_headers = make_sponsorship_manager_headers(org_id)
    deal = fixtures.setup_active_deal(
        org_id,
        sponsor_name="Northline Apparel",
        exclusivity_category="APPAREL",
        total_fee_cents=1000000,
        deliverable_count_required=2,
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-09-01T00:00:00Z",
    )

    fixtures.setup_held_blocks(
        org_id,
        ctx["house"]["id"],
        [ctx["player"]["id"]],
        [("2026-08-10T00:00:00Z", "2026-08-11T21:00:00Z")],
        "2026-08-11T21:00:00Z",
    )
    after_completion = validate_success(
        api_client.get_contract(contract_id, make_general_manager_headers(org_id))
    )
    assert after_completion["burnout_score"] == 50
    assert after_completion["obligation_status"] == "COMPLIANT"

    breached = validate_success(
        api_client.file_wellness_report(
            contract_id,
            {"last_self_reported_load": 10, "reported_streaming_minutes_7d": 600},
            make_performance_support_headers(),
        )
    )
    assert breached["burnout_score"] == 100
    assert breached["obligation_status"] == "BREACH"
    assert_instant_equals(
        breached["wellness_hold_until"],
        "2026-08-18T21:00:00Z",
        "PlayerContract.wellness_hold_until",
    )
    assert breached["contract_status"] == "ACTIVE"
    organization = validate_success(
        api_client.get_organization(org_id, make_general_manager_headers(org_id))
    )
    assert organization["wellness_flag_count"] == 1

    late_block = {
        "organization_id": org_id,
        "team_house_id": ctx["house"]["id"],
        "block_type": "SCRIM",
        "starts_at": "2026-08-20T10:00:00Z",
        "ends_at": "2026-08-20T14:00:00Z",
        "participant_player_ids": [ctx["player"]["id"]],
    }
    validate_error(
        api_client.create_practice_block(late_block, coach_headers),
        ApiErrorId.ERR_WELLNESS_HOLD_ACTIVE.value,
        409,
    )

    def place_deliverable():
        return api_client.create_deliverable_assignment(
            deal["id"],
            factories.create_deliverable_payload(
                contract_id,
                fixtures.current_deal_version(deal["id"], org_id),
                deliverable_type="STREAM_SEGMENT",
                due_at="2026-08-25T00:00:00Z",
            ),
            sponsor_headers,
        )

    validate_error(
        place_deliverable(),
        ApiErrorId.ERR_OBLIGATION_BREACH_BLOCKS_ASSIGNMENT.value,
        422,
    )
    assert (
        validate_success(api_client.get_sponsorship_deal(deal["id"], sponsor_headers))[
            "assigned_count"
        ]
        == 0
    )

    fixtures.set_clock("2026-08-18T21:00:00Z")
    admitted = validate_success(
        api_client.create_practice_block(late_block, coach_headers), 201
    )
    assert admitted["block_status"] == "SCHEDULED"
    validate_error(
        place_deliverable(),
        ApiErrorId.ERR_OBLIGATION_BREACH_BLOCKS_ASSIGNMENT.value,
        422,
    )

    summary = validate_success(
        api_client.get_contract_obligation_summary(
            contract_id, make_performance_support_headers()
        )
    )
    assert summary["obligation_status"] == "BREACH"
    assert_instant_equals(
        summary["wellness_hold_until"],
        "2026-08-18T21:00:00Z",
        "obligation_summary.wellness_hold_until",
    )


def test_the_deliverable_window_the_quota_and_exclusivity_fire_in_that_order():
    """One endpoint, three escalating gates, and a category-scoped conflict that spares PERIPHERALS.

    PRD: "The `due_at` must fall at or after the deal's `starts_at` and strictly before its `ends_at`, or
    `ERR_DELIVERABLE_DUE_OUTSIDE_DEAL` (HTTP 422) is returned."
    PRD: "The deal's `assigned_count` must be strictly less than its `deliverable_count_required`,
    otherwise the quota is full and `ERR_DELIVERABLE_QUOTA_EXCEEDED` (HTTP 422) is returned."
    PRD: "A conflict exists when some *other* sponsorship deal of the same organization is in `ACTIVE` or
    `FULFILLED`, carries exactly the same `exclusivity_category` compared case-sensitively, has a coverage
    window that overlaps this deal's window on the half-open comparison — that other deal starts strictly
    before this deal ends and this deal starts strictly before that other deal ends — and already carries
    a non-`VOIDED` deliverable on the very same player contract that is at issue."
    PRD: "Two energy-drink sponsors may coexist in an organization's portfolio; what they may not do is
    both hold live content obligations on one player."
    PRD: "Assignments may be listed with any combination of `sponsorship_deal_id`, `contract_id` and
    `assignment_status`, and one deal's deliverables are reachable as a nested read filterable by
    `assignment_status`."

    Design: Corner/validations/deliverable_window_quota_and_exclusivity_fire_in_their_priority_order
    """
    ctx = fixtures.setup_signed_player()
    org_id = ctx["org"]["id"]
    contract_id = ctx["contract"]["id"]
    sponsor_headers = make_sponsorship_manager_headers(org_id)
    first_deal = fixtures.setup_active_deal(
        org_id,
        sponsor_name="Voltaic",
        exclusivity_category="ENERGY_DRINK",
        total_fee_cents=1000000,
        deliverable_count_required=2,
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-09-01T00:00:00Z",
    )

    def place(deal_id, **overrides):
        return api_client.create_deliverable_assignment(
            deal_id,
            factories.create_deliverable_payload(
                contract_id, fixtures.current_deal_version(deal_id, org_id), **overrides
            ),
            sponsor_headers,
        )

    validate_error(
        place(first_deal["id"], due_at="2026-09-01T00:00:00Z"),
        ApiErrorId.ERR_DELIVERABLE_DUE_OUTSIDE_DEAL.value,
        422,
    )
    validate_error(
        place(first_deal["id"], due_at="2026-07-31T23:59:59Z"),
        ApiErrorId.ERR_DELIVERABLE_DUE_OUTSIDE_DEAL.value,
        422,
    )

    first_assignment = validate_success(
        place(first_deal["id"], due_at="2026-08-20T00:00:00Z"), 201
    )
    second_assignment = validate_success(
        place(
            first_deal["id"],
            deliverable_type="STREAM_SEGMENT",
            due_at="2026-08-21T00:00:00Z",
        ),
        201,
    )
    assert first_assignment["fee_share_cents"] == 500000
    assert second_assignment["fee_share_cents"] == 500000
    assert (
        validate_success(
            api_client.get_sponsorship_deal(first_deal["id"], sponsor_headers)
        )["assigned_count"]
        == 2
    )

    validate_error(
        place(
            first_deal["id"],
            deliverable_type="APPEARANCE",
            due_at="2026-08-22T00:00:00Z",
        ),
        ApiErrorId.ERR_DELIVERABLE_QUOTA_EXCEEDED.value,
        422,
    )

    rival_energy_deal = fixtures.setup_active_deal(
        org_id,
        sponsor_name="Zapfizz",
        exclusivity_category="ENERGY_DRINK",
        total_fee_cents=400000,
        deliverable_count_required=1,
        starts_at="2026-08-15T00:00:00Z",
        ends_at="2026-09-15T00:00:00Z",
    )
    assert rival_energy_deal["deal_status"] == "ACTIVE"
    validate_error(
        place(rival_energy_deal["id"], due_at="2026-08-25T00:00:00Z"),
        ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
        409,
    )

    peripherals_deal = fixtures.setup_active_deal(
        org_id,
        sponsor_name="Clickmaster",
        exclusivity_category="PERIPHERALS",
        total_fee_cents=400000,
        deliverable_count_required=1,
        starts_at="2026-08-15T00:00:00Z",
        ends_at="2026-09-15T00:00:00Z",
    )
    third_assignment = validate_success(
        place(peripherals_deal["id"], due_at="2026-08-25T00:00:00Z"), 201
    )
    assert third_assignment["fee_share_cents"] == 400000
    assert (
        validate_success(
            api_client.get_sponsorship_deal(peripherals_deal["id"], sponsor_headers)
        )["assigned_count"]
        == 1
    )
    assert (
        validate_success(
            api_client.get_sponsorship_deal(rival_energy_deal["id"], sponsor_headers)
        )["assigned_count"]
        == 0
    )

    rows, meta = validate_paginated(
        api_client.list_deliverable_assignments(
            sponsor_headers,
            params={"contract_id": contract_id, "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 3
    assert {row["id"] for row in rows} == {
        first_assignment["id"],
        second_assignment["id"],
        third_assignment["id"],
    }


def test_a_transfer_fee_below_the_buyout_credit_is_refused_before_anything_is_written():
    """250,002 cents against a 6,250,002-cent credit writes nothing; 7,000,000 clears with the thin tier.

    PRD: "Step six sets `net_to_org_cents` to the gross settlement less the agent's commission, and if
    that figure is negative the whole execution is refused with `ERR_NEGATIVE_SETTLEMENT` (HTTP 422) and
    nothing is written."
    PRD: "Step three computes the `buyout_credit_cents` owed to the departing player as that monthly rate
    multiplied by the remaining whole months, multiplied by the contract's `buyout_multiplier_bp`, divided
    by 10000 and rounded half up."
    PRD: "Step five selects the agent's `commission_tier_bp` **from that gross settlement, before any
    commission is deducted**: 500 basis points when the gross settlement is strictly below 5,000,000
    cents, and 300 basis points at or above that breakpoint — the larger the deal, the thinner the agent's
    percentage."
    PRD: "Step seven takes the cap relief from the contract's frozen charge: `released_cap_cents` is set
    to the contract's `provisional_cap_charge_cents`, which is what makes a later reversal exact."
    PRD: "Step two derives the monthly rate from the base salary alone and never from any cap charge:
    `base_salary_cents` divided by 12 and rounded half up."

    Design: Corner/validations/negative_transfer_settlement_is_refused_at_execution
    """
    ctx = fixtures.setup_two_signed_players(
        league_overrides={"min_roster_size": 1},
        second_offer_overrides={"base_salary_cents": 12500000},
    )
    org_one = ctx["org"]["id"]
    org_two = fixtures.create_organization(ctx["league"]["id"], name="Northwind Nine")["id"]
    gm_headers = make_general_manager_headers(org_one)
    contract_a = ctx["contract_one"]["id"]
    player_a = ctx["player_one"]["id"]

    fixtures.set_clock("2026-08-10T00:00:00Z")
    underwater = fixtures.file_roster_move(
        org_one,
        player_a,
        "TRANSFER_OUT",
        contract_a,
        transfer_to_organization_id=org_two,
        gross_transfer_fee_cents=250002,
    )
    fixtures.decide_roster_move(underwater["id"], "APPROVE", "admin-9")
    validate_error(
        api_client.execute_roster_move(underwater["id"], gm_headers),
        ApiErrorId.ERR_NEGATIVE_SETTLEMENT.value,
        422,
    )

    untouched = validate_success(
        api_client.get_roster_move(underwater["id"], gm_headers)
    )
    assert untouched["move_status"] == "APPROVED"
    assert untouched["buyout_credit_cents"] == 0
    assert untouched["agent_commission_cents"] == 0
    assert untouched["net_to_org_cents"] == 0
    assert untouched["released_cap_cents"] == 0
    assert (
        validate_success(api_client.get_contract(contract_a, gm_headers))[
            "contract_status"
        ]
        == "ACTIVE"
    )
    assert (
        validate_success(api_client.get_organization(org_one, gm_headers))[
            "committed_salary_cents"
        ]
        == 24657534
    )

    revised = fixtures.file_roster_move(
        org_one,
        player_a,
        "TRANSFER_OUT",
        contract_a,
        transfer_to_organization_id=org_two,
        gross_transfer_fee_cents=7000000,
    )
    fixtures.decide_roster_move(revised["id"], "APPROVE", "admin-9")
    settled = fixtures.execute_roster_move(revised["id"], org_one)
    assert settled["move_status"] == "EXECUTED"
    assert settled["buyout_credit_cents"] == 6250002
    assert settled["commission_tier_bp"] == 500
    assert settled["agent_commission_cents"] == 37500
    assert settled["net_to_org_cents"] == 712498
    assert settled["released_cap_cents"] == 12328767

    assert (
        validate_success(api_client.get_contract(contract_a, gm_headers))[
            "contract_status"
        ]
        == "TERMINATED"
    )
    departed = validate_success(api_client.get_player(player_a, make_scout_headers()))
    assert departed["player_status"] == "FREE_AGENT"
    assert_instant_equals(
        departed["free_agency_window_ends_at"],
        "2026-08-24T00:00:00Z",
        "Player.free_agency_window_ends_at",
    )

    cap_summary = validate_success(
        api_client.get_organization_cap_summary(org_one, gm_headers)
    )
    assert cap_summary["committed_salary_cents"] == 12328767
    assert cap_summary["uncommitted_salary_cents"] == 37671233
    assert cap_summary["active_roster_count"] == 1
