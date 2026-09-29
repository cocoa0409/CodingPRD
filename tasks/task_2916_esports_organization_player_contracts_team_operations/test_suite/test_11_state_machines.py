"""Initial states, single-shot transitions and absorbing terminal states.

Every lifecycle in this contract is entered at exactly one declared state and left
through exactly one door per action. These tests walk the doors twice: once when
they are meant to open, and once again when the same call must be refused.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    make_coaching_staff_headers,
    make_finance_officer_headers,
    make_general_manager_headers,
    make_league_admin_headers,
    make_player_agent_headers,
    make_scout_headers,
    make_sponsorship_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_every_write_surface_creates_its_record_in_the_declared_initial_state():
    """Seven creations, seven declared starting states, and a round counter that starts at one.

    PRD: "A freshly created offer has `offer_status` of `SENT`, `round_number` of 1, `sent_at` stamped
    from the logical clock, and `expires_at` set to `sent_at` plus the league's
    `offer_response_window_hours` hours."
    PRD: "A player contract carries **two independent status dimensions** on the same record."
    PRD: "On insertion the server derives `duration_minutes` as the number of whole minutes between
    `starts_at` and `ends_at`, stamps the booking coach's identifier into `coach_user_id`, sets
    `block_status` to `SCHEDULED` and leaves `cancel_reason` null."
    PRD: "A drafted deal has `deal_status` of `DRAFT`, `assigned_count` and `approved_count` both 0, and
    one derived flag: `minor_permitted` is false when the `exclusivity_category` is `ENERGY_DRINK`,
    `BETTING` or `CRYPTO`, and true for `PERIPHERALS` and `APPAREL`."
    PRD: "A new distribution has `distribution_status` of `DRAFT`, `unallocated_cents` equal to the
    whole `gross_prize_cents`, and `association_levy_cents`, `org_share_cents`, `allocated_cents`,
    `withholding_total_cents` and `escrow_total_cents` all at 0, with `calculated_by_user_id`,
    `approved_by_user_id` and `void_reason` all null."
    PRD: "The move is created with `move_status` of `PENDING`, its `requested_by_user_id` stamped from
    the filing manager, its `approved_by_user_id`, `decision_note` and `reversal_reason` null, and its
    five money fields — `buyout_credit_cents`, `commission_tier_bp`, `agent_commission_cents`,
    `net_to_org_cents` and `released_cap_cents` — all at 0."

    Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
    """
    ctx = fixtures.setup_league_and_org()
    house = fixtures.create_team_house(ctx["org"]["id"])
    player = fixtures.create_player()
    gm_headers = make_general_manager_headers(ctx["org"]["id"])
    sponsor_headers = make_sponsorship_manager_headers(ctx["org"]["id"])
    finance_headers = make_finance_officer_headers()
    assert player["player_status"] == "PROSPECT"

    offer = validate_success(
        api_client.create_contract_offer(
            factories.create_contract_offer_payload(ctx["org"]["id"], player["id"]),
            gm_headers,
        ),
        201,
    )
    assert offer["offer_status"] == "SENT"
    assert offer["round_number"] == 1

    contract = validate_success(
        api_client.accept_contract_offer(
            offer["id"],
            {"effective_at": "2026-08-05T00:00:00Z"},
            make_player_agent_headers(player["id"]),
        ),
        201,
    )
    assert contract["contract_status"] == "ACTIVE"
    assert contract["obligation_status"] == "COMPLIANT"
    assert contract["burnout_score"] == 0
    assert contract["season_practice_minutes"] == 0
    assert contract["wellness_hold_until"] is None

    assert (
        validate_success(api_client.get_player(player["id"], make_scout_headers()))[
            "player_status"
        ]
        == "SIGNED"
    )
    settled_offer = validate_success(api_client.get_contract_offer(offer["id"], gm_headers))
    assert settled_offer["offer_status"] == "ACCEPTED"
    assert settled_offer["round_number"] == 1

    block = validate_success(
        api_client.create_practice_block(
            {
                "organization_id": ctx["org"]["id"],
                "team_house_id": house["id"],
                "block_type": "SCRIM",
                "starts_at": "2026-08-10T10:00:00Z",
                "ends_at": "2026-08-10T14:00:00Z",
                "participant_player_ids": [player["id"]],
            },
            make_coaching_staff_headers(),
        ),
        201,
    )
    assert block["block_status"] == "SCHEDULED"
    assert block["duration_minutes"] == 240
    assert block["cancel_reason"] is None

    deal = validate_success(
        api_client.create_sponsorship_deal(
            factories.create_sponsorship_deal_payload(
                ctx["org"]["id"],
                sponsor_name="Voltade",
                exclusivity_category="ENERGY_DRINK",
                starts_at="2026-08-01T00:00:00Z",
                ends_at="2026-09-01T00:00:00Z",
            ),
            sponsor_headers,
        ),
        201,
    )
    assert deal["deal_status"] == "DRAFT"
    assert deal["assigned_count"] == 0
    assert deal["approved_count"] == 0

    distribution = validate_success(
        api_client.create_prize_distribution(
            factories.create_prize_distribution_payload(
                ctx["org"]["id"],
                ctx["league"]["id"],
                tournament_name="Summer Split Finals",
                placement=1,
                tournament_end_at="2026-08-31T00:00:00Z",
            ),
            finance_headers,
        ),
        201,
    )
    assert distribution["distribution_status"] == "DRAFT"
    assert distribution["allocated_cents"] == 0
    assert distribution["unallocated_cents"] == 10000000

    organization = validate_success(api_client.get_organization(ctx["org"]["id"], gm_headers))
    move = validate_success(
        api_client.create_roster_move(
            {
                "organization_id": ctx["org"]["id"],
                "player_id": player["id"],
                "move_type": "RELEASE",
                "contract_id": contract["id"],
                "expected_organization_version": organization["version"],
            },
            gm_headers,
        ),
        201,
    )
    assert move["move_status"] == "PENDING"
    assert move["buyout_credit_cents"] == 0
    assert move["agent_commission_cents"] == 0
    assert move["net_to_org_cents"] == 0
    assert move["released_cap_cents"] == 0


def test_completing_and_cancelling_a_block_each_work_exactly_once():
    """Too early, then on time, then never again — and the sibling block proves cancellation is terminal too.

    PRD: "Completing a block is a separate coaching action, permitted only while `block_status` is
    `SCHEDULED` — otherwise `ERR_BLOCK_NOT_SCHEDULED` (HTTP 409) — and only once the current instant has
    reached the block's `ends_at`, the boundary instant being sufficient; an early attempt is refused
    with `ERR_BLOCK_NOT_FINISHED` (HTTP 409)."
    PRD: "On a `TRYOUT` block, completion additionally advances every attendee sitting in
    `TRYOUT_INVITED` to `TRYOUT_COMPLETED`."
    PRD: "It moves `block_status` `SCHEDULED` → `CANCELLED`, and both `HELD` and `CANCELLED` are
    terminal for a block — an attempt to cancel a block that is already `HELD` or `CANCELLED` is refused
    with `ERR_BLOCK_NOT_SCHEDULED`, exactly as an attempt to complete one is."
    PRD: "A manual cancellation must supply `cancel_reason` equal to `COACH_CANCELLED`, and any other
    value is a malformed request; an optional `coach_note` may accompany it."
    PRD: "Booking a `TRYOUT` block does double duty as a scouting action: every attendee whose
    `player_status` is `PROSPECT` or `FREE_AGENT` moves to `TRYOUT_INVITED` as the block is created."

    Design: Corner/state_machines/practice_block_completion_and_cancellation_are_single_shot_returns_409
    """
    ctx = fixtures.setup_league_and_org()
    house = fixtures.create_team_house(ctx["org"]["id"])
    player = fixtures.create_player()
    coach_headers = make_coaching_staff_headers()

    block_a = fixtures.create_practice_block(
        ctx["org"]["id"],
        house["id"],
        "2026-08-02T10:00:00Z",
        "2026-08-02T14:00:00Z",
        [player["id"]],
        block_type="TRYOUT",
    )
    block_b = fixtures.create_practice_block(
        ctx["org"]["id"],
        house["id"],
        "2026-08-04T10:00:00Z",
        "2026-08-04T14:00:00Z",
        [player["id"]],
        block_type="TRYOUT",
    )
    assert (
        validate_success(api_client.get_player(player["id"], make_scout_headers()))[
            "player_status"
        ]
        == "TRYOUT_INVITED"
    )

    validate_error(
        api_client.complete_practice_block(block_a["id"], coach_headers),
        ApiErrorId.ERR_BLOCK_NOT_FINISHED.value,
        409,
    )
    assert (
        validate_success(api_client.get_practice_block(block_a["id"], coach_headers))[
            "block_status"
        ]
        == "SCHEDULED"
    )

    fixtures.set_clock("2026-08-02T14:00:00Z")
    held = validate_success(api_client.complete_practice_block(block_a["id"], coach_headers))
    assert held["block_status"] == "HELD"
    assert (
        validate_success(api_client.get_player(player["id"], make_scout_headers()))[
            "player_status"
        ]
        == "TRYOUT_COMPLETED"
    )

    validate_error(
        api_client.complete_practice_block(block_a["id"], coach_headers),
        ApiErrorId.ERR_BLOCK_NOT_SCHEDULED.value,
        409,
    )
    validate_error(
        api_client.cancel_practice_block(
            block_a["id"],
            {"cancel_reason": "COACH_CANCELLED", "coach_note": "double booked room"},
            coach_headers,
        ),
        ApiErrorId.ERR_BLOCK_NOT_SCHEDULED.value,
        409,
    )
    still_held = validate_success(
        api_client.get_practice_block(block_a["id"], coach_headers)
    )
    assert still_held["block_status"] == "HELD"
    assert still_held["cancel_reason"] is None

    cancelled = validate_success(
        api_client.cancel_practice_block(
            block_b["id"], {"cancel_reason": "COACH_CANCELLED"}, coach_headers
        )
    )
    assert cancelled["block_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "COACH_CANCELLED"

    fixtures.set_clock("2026-08-04T14:00:00Z")
    validate_error(
        api_client.complete_practice_block(block_b["id"], coach_headers),
        ApiErrorId.ERR_BLOCK_NOT_SCHEDULED.value,
        409,
    )


def test_a_voided_distribution_absorbs_every_further_action():
    """Void is reachable only from the middle of the walk, and once reached nothing leaves it.

    PRD: "Running the waterfall is finance's exclusive action and is permitted only from `DRAFT`;
    anything else yields `ERR_DISTRIBUTION_NOT_DRAFT` (HTTP 409)."
    PRD: "A distribution must be in `CALCULATED`, or `ERR_DISTRIBUTION_NOT_CALCULATED` (HTTP 409) is
    returned, and the approving `X-User-ID` must differ from the recorded `calculated_by_user_id`, or
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) is returned."
    PRD: "Voiding is finance's compensating action and is permitted from `CALCULATED` and from
    `APPROVED`, with any other status — including `DRAFT` and an already-voided distribution — refused
    with `ERR_DISTRIBUTION_NOT_CALCULATED`."
    PRD: "The `org_share_cents` the calculation had added to the organization's `prize_payable_cents` is
    withdrawn again, exactly."

    Design: Corner/state_machines/prize_distribution_void_is_terminal_and_admits_no_further_action_returns_409
    """
    ctx = fixtures.setup_signed_player()
    finance_headers = make_finance_officer_headers()
    distribution = fixtures.create_distribution(
        ctx["org"]["id"],
        ctx["league"]["id"],
        tournament_name="Summer Split Finals",
        placement=1,
        tournament_end_at="2026-08-31T00:00:00Z",
    )

    validate_error(
        api_client.approve_prize_distribution(
            distribution["id"], make_league_admin_headers("admin-9")
        ),
        ApiErrorId.ERR_DISTRIBUTION_NOT_CALCULATED.value,
        409,
    )
    validate_error(
        api_client.void_prize_distribution(
            distribution["id"], {"void_reason": "premature"}, finance_headers
        ),
        ApiErrorId.ERR_DISTRIBUTION_NOT_CALCULATED.value,
        409,
    )

    calculated = validate_success(
        api_client.calculate_prize_distribution(distribution["id"], finance_headers)
    )
    assert calculated["distribution_status"] == "CALCULATED"
    assert calculated["association_levy_cents"] == 250000
    assert calculated["org_share_cents"] == 3412500
    assert calculated["allocated_cents"] == 6337500
    assert calculated["unallocated_cents"] == 0

    validate_error(
        api_client.calculate_prize_distribution(distribution["id"], finance_headers),
        ApiErrorId.ERR_DISTRIBUTION_NOT_DRAFT.value,
        409,
    )
    unchanged = validate_success(
        api_client.get_prize_distribution(distribution["id"], finance_headers)
    )
    assert unchanged["distribution_status"] == "CALCULATED"
    assert unchanged["org_share_cents"] == 3412500
    assert unchanged["allocated_cents"] == 6337500

    voided = validate_success(
        api_client.void_prize_distribution(
            distribution["id"],
            {"void_reason": "wrong placement recorded"},
            finance_headers,
        )
    )
    assert voided["distribution_status"] == "VOIDED"
    assert voided["association_levy_cents"] == 0
    assert voided["org_share_cents"] == 0
    assert voided["allocated_cents"] == 0
    assert voided["withholding_total_cents"] == 0
    assert voided["escrow_total_cents"] == 0
    assert voided["unallocated_cents"] == 10000000

    validate_error(
        api_client.calculate_prize_distribution(distribution["id"], finance_headers),
        ApiErrorId.ERR_DISTRIBUTION_NOT_DRAFT.value,
        409,
    )
    validate_error(
        api_client.approve_prize_distribution(
            distribution["id"], make_league_admin_headers("admin-9")
        ),
        ApiErrorId.ERR_DISTRIBUTION_NOT_CALCULATED.value,
        409,
    )
    validate_error(
        api_client.void_prize_distribution(
            distribution["id"], {"void_reason": "second void"}, finance_headers
        ),
        ApiErrorId.ERR_DISTRIBUTION_NOT_CALCULATED.value,
        409,
    )

    cap_summary = validate_success(
        api_client.get_organization_cap_summary(ctx["org"]["id"], finance_headers)
    )
    assert cap_summary["prize_payable_cents"] == 0
    final = validate_success(
        api_client.get_prize_distribution(distribution["id"], finance_headers)
    )
    assert final["void_reason"] == "wrong placement recorded"


def test_each_roster_move_endpoint_guards_its_own_from_state():
    """Four endpoints over one lifecycle produce four distinct refusals, and nothing moves.

    PRD: "Execution belongs back to the filing organization's general manager, who may act only on their
    own organization's moves and only while `move_status` is `APPROVED`; anything else yields
    `ERR_MOVE_NOT_APPROVED` (HTTP 409)."
    PRD: "Reversal is the league office's compensating action and requires `move_status` to be
    `EXECUTED`, with anything else refused as `ERR_MOVE_NOT_EXECUTED` (HTTP 409)."
    PRD: "An executed `SIGN` has nothing to unwind and is refused with `ERR_MOVE_NOT_REVERSIBLE` (HTTP
    422); only a `RELEASE` or a `TRANSFER_OUT` may be reversed."
    PRD: "Both require `move_status` to be `PENDING`, or `ERR_MOVE_NOT_PENDING` (HTTP 409) is returned;
    both require the deciding `X-User-ID` to differ from the recorded `requested_by_user_id`, or
    `ERR_SEGREGATION_OF_DUTIES` is returned; both require the league's roster lock to be inactive, or
    `ERR_ROSTER_LOCK_ACTIVE` is returned; both take a mandatory `decision` of `APPROVE` or `REJECT` and
    an optional `decision_note`; and both stamp `approved_by_user_id` with the deciding administrator and
    record the note."
    PRD: "A `SIGN` execution is deliberately empty of all that."

    Design: Corner/state_machines/roster_move_action_endpoints_each_enforce_their_own_from_state_returns_409
    """
    ctx = fixtures.setup_two_signed_players(
        second_offer_overrides={"base_salary_cents": 12500000}
    )
    gm_headers = make_general_manager_headers(ctx["org"]["id"])
    admin_headers = make_league_admin_headers("admin-9")

    before = validate_success(api_client.get_organization(ctx["org"]["id"], gm_headers))
    assert before["committed_salary_cents"] == 24657534
    assert before["active_roster_count"] == 2

    release = fixtures.file_roster_move(
        ctx["org"]["id"],
        ctx["player_two"]["id"],
        "RELEASE",
        ctx["contract_two"]["id"],
    )
    assert release["move_status"] == "PENDING"

    validate_error(
        api_client.execute_roster_move(release["id"], gm_headers),
        ApiErrorId.ERR_MOVE_NOT_APPROVED.value,
        409,
    )
    validate_error(
        api_client.reverse_roster_move(
            release["id"], {"reversal_reason": "too early"}, admin_headers
        ),
        ApiErrorId.ERR_MOVE_NOT_EXECUTED.value,
        409,
    )

    approved = validate_success(
        api_client.decide_roster_move(
            release["id"],
            {"decision": "APPROVE", "decision_note": "release cleared"},
            admin_headers,
        )
    )
    assert approved["move_status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "admin-9"

    validate_error(
        api_client.decide_roster_move(
            release["id"],
            {"decision": "REJECT", "decision_note": "changed my mind"},
            admin_headers,
        ),
        ApiErrorId.ERR_MOVE_NOT_PENDING.value,
        409,
    )
    unchanged = validate_success(api_client.get_roster_move(release["id"], gm_headers))
    assert unchanged["move_status"] == "APPROVED"
    assert unchanged["decision_note"] == "release cleared"

    organization = validate_success(api_client.get_organization(ctx["org"]["id"], gm_headers))
    sign = validate_success(
        api_client.create_roster_move(
            {
                "organization_id": ctx["org"]["id"],
                "player_id": ctx["player_one"]["id"],
                "move_type": "SIGN",
                "contract_id": ctx["contract_one"]["id"],
                "expected_organization_version": organization["version"],
            },
            gm_headers,
        ),
        201,
    )
    validate_success(
        api_client.decide_roster_move(
            sign["id"],
            {"decision": "APPROVE", "decision_note": "signing ratified"},
            admin_headers,
        )
    )
    executed = validate_success(api_client.execute_roster_move(sign["id"], gm_headers))
    assert executed["move_status"] == "EXECUTED"
    assert executed["released_cap_cents"] == 0
    assert executed["net_to_org_cents"] == 0

    validate_error(
        api_client.reverse_roster_move(
            sign["id"], {"reversal_reason": "league changed its mind"}, admin_headers
        ),
        ApiErrorId.ERR_MOVE_NOT_REVERSIBLE.value,
        422,
    )
    assert (
        validate_success(api_client.get_roster_move(sign["id"], gm_headers))["move_status"]
        == "EXECUTED"
    )

    for contract_id in (ctx["contract_one"]["id"], ctx["contract_two"]["id"]):
        assert (
            validate_success(api_client.get_contract(contract_id, gm_headers))[
                "contract_status"
            ]
            == "ACTIVE"
        )
    after = validate_success(api_client.get_organization(ctx["org"]["id"], gm_headers))
    assert after["committed_salary_cents"] == 24657534
    assert after["active_roster_count"] == 2


def test_the_review_loop_keeps_its_tally_and_the_deal_fulfils_on_the_second_approval():
    """Reject, resubmit, approve, approve — and the parent flips exactly when the quota is met.

    PRD: "An attempt to submit something already `SUBMITTED`, `APPROVED` or `VOIDED` is refused with
    `ERR_ASSIGNMENT_NOT_SUBMITTED` (HTTP 409), as is any review of an assignment that is not
    `SUBMITTED`."
    PRD: "A rejection moves the assignment `SUBMITTED` → `REJECTED` and increases its `rejection_count`
    by 1; the agent may then resubmit, and the rejection tally is preserved across as many loops as the
    pair needs."
    PRD: "An approval moves it `SUBMITTED` → `APPROVED` and increases the deal's `approved_count` by 1."
    PRD: "Once `approved_count` equals `deliverable_count_required`, the deal moves `ACTIVE` →
    `FULFILLED` in the same request as the final approval."
    PRD: "Its `fee_share_cents` is frozen at creation as the deal's `total_fee_cents` divided by its
    `deliverable_count_required` with the fractional remainder discarded."

    Design: Corner/state_machines/deliverable_review_cycle_resubmission_bubbles_the_deal_to_fulfilled
    """
    ctx = fixtures.setup_signed_player()
    sponsor_headers = make_sponsorship_manager_headers(ctx["org"]["id"])
    agent_headers = make_player_agent_headers(ctx["player"]["id"])
    deal = fixtures.setup_active_deal(
        ctx["org"]["id"],
        sponsor_name="Voltade",
        exclusivity_category="ENERGY_DRINK",
        total_fee_cents=1000001,
        deliverable_count_required=2,
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-09-01T00:00:00Z",
    )
    first = fixtures.add_deliverable(
        deal["id"], ctx["org"]["id"], ctx["contract"]["id"], due_at="2026-08-20T00:00:00Z"
    )
    second = fixtures.add_deliverable(
        deal["id"], ctx["org"]["id"], ctx["contract"]["id"], due_at="2026-08-25T00:00:00Z"
    )
    assert first["fee_share_cents"] == 500000
    assert second["fee_share_cents"] == 500000

    validate_error(
        api_client.review_deliverable_assignment(
            first["id"], {"decision": "APPROVE", "review_note": "too early"}, sponsor_headers
        ),
        ApiErrorId.ERR_ASSIGNMENT_NOT_SUBMITTED.value,
        409,
    )
    assert (
        validate_success(
            api_client.get_deliverable_assignment(first["id"], sponsor_headers)
        )["assignment_status"]
        == "ASSIGNED"
    )

    submitted = validate_success(
        api_client.submit_deliverable_assignment(
            first["id"], {"submission_note": "first cut"}, agent_headers
        )
    )
    assert submitted["assignment_status"] == "SUBMITTED"
    assert submitted["submission_note"] == "first cut"

    rejected = validate_success(
        api_client.review_deliverable_assignment(
            first["id"],
            {"decision": "REJECT", "review_note": "logo not visible"},
            sponsor_headers,
        )
    )
    assert rejected["assignment_status"] == "REJECTED"
    assert rejected["rejection_count"] == 1
    assert rejected["review_note"] == "logo not visible"
    assert (
        validate_success(api_client.get_sponsorship_deal(deal["id"], sponsor_headers))[
            "approved_count"
        ]
        == 0
    )

    resubmitted = validate_success(
        api_client.submit_deliverable_assignment(
            first["id"], {"submission_note": "logo fixed"}, agent_headers
        )
    )
    assert resubmitted["assignment_status"] == "SUBMITTED"
    assert resubmitted["rejection_count"] == 1

    approved = validate_success(
        api_client.review_deliverable_assignment(
            first["id"], {"decision": "APPROVE", "review_note": "cleared"}, sponsor_headers
        )
    )
    assert approved["assignment_status"] == "APPROVED"
    assert approved["fee_share_cents"] == 500000
    midway = validate_success(api_client.get_sponsorship_deal(deal["id"], sponsor_headers))
    assert midway["approved_count"] == 1
    assert midway["deal_status"] == "ACTIVE"

    validate_error(
        api_client.submit_deliverable_assignment(
            first["id"], {"submission_note": "one more take"}, agent_headers
        ),
        ApiErrorId.ERR_ASSIGNMENT_NOT_SUBMITTED.value,
        409,
    )

    validate_success(
        api_client.submit_deliverable_assignment(
            second["id"], {"submission_note": "post scheduled"}, agent_headers
        )
    )
    validate_success(
        api_client.review_deliverable_assignment(
            second["id"], {"decision": "APPROVE", "review_note": "cleared"}, sponsor_headers
        )
    )
    fulfilled = validate_success(api_client.get_sponsorship_deal(deal["id"], sponsor_headers))
    assert fulfilled["approved_count"] == 2
    assert fulfilled["deal_status"] == "FULFILLED"
    assert fulfilled["assigned_count"] == 2

    rows, meta = validate_paginated(
        api_client.list_deal_deliverables(
            deal["id"], sponsor_headers, params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert {row["fee_share_cents"] for row in rows} == {500000}


def test_a_signed_player_supersedes_one_rival_offer_and_refuses_a_fresh_one():
    """Two paths to a refused acceptance, and they are deliberately different errors.

    PRD: "Fourth, because the player is now signed, every *other* offer to the same `player_id` sitting
    in `SENT` or `COUNTERED` is moved to `SUPERSEDED`."
    PRD: "An offer's six states are `SENT`, `COUNTERED`, `ACCEPTED`, `DECLINED`, `EXPIRED` and
    `SUPERSEDED`, of which the last four are terminal — an offer in any of them accepts no further
    action, and an attempt to act on one is refused with `ERR_OFFER_NOT_OPEN` (HTTP 409)."
    PRD: "The player must have no other `PlayerContract` whose `contract_status` is `ACTIVE` or
    `SUSPENDED`, or the request is refused with `ERR_PLAYER_ALREADY_SIGNED` (HTTP 409)."
    PRD: "Second, because that contract now exists, the player's `player_status` becomes `SIGNED`, their
    `current_organization_id` becomes the offering organization, and both `free_agency_window_ends_at`
    and `last_release_organization_id` are cleared to null."

    Design: Corner/state_machines/second_acceptance_for_an_already_signed_player_is_rejected
    """
    ctx = fixtures.setup_league_and_org()
    rival = fixtures.create_organization(ctx["league"]["id"], name="Meridian Esports")
    player = fixtures.create_player()
    agent_headers = make_player_agent_headers(player["id"])
    rival_gm_headers = make_general_manager_headers(rival["id"])

    first_offer = fixtures.create_offer(ctx["org"]["id"], player["id"])
    second_offer = fixtures.create_offer(rival["id"], player["id"])

    contract = validate_success(
        api_client.accept_contract_offer(
            first_offer["id"], {"effective_at": "2026-08-05T00:00:00Z"}, agent_headers
        ),
        201,
    )
    assert contract["contract_status"] == "ACTIVE"
    assert contract["organization_id"] == ctx["org"]["id"]
    assert contract["provisional_cap_charge_cents"] == 12328767

    signed_player = validate_success(api_client.get_player(player["id"], make_scout_headers()))
    assert signed_player["player_status"] == "SIGNED"
    assert signed_player["current_organization_id"] == ctx["org"]["id"]

    superseded = validate_success(
        api_client.get_contract_offer(second_offer["id"], agent_headers)
    )
    assert superseded["offer_status"] == "SUPERSEDED"
    validate_error(
        api_client.accept_contract_offer(
            second_offer["id"], {"effective_at": "2026-08-05T00:00:00Z"}, agent_headers
        ),
        ApiErrorId.ERR_OFFER_NOT_OPEN.value,
        409,
    )

    third_offer = validate_success(
        api_client.create_contract_offer(
            {
                "organization_id": rival["id"],
                "player_id": player["id"],
                "base_salary_cents": 14000000,
                "term_months": 12,
                "prize_split_player_pct_bp": 4300,
                "streaming_hours_per_week": 12,
                "tax_residency_code": "US-CA",
                "signing_bonus_cents": 0,
                "buyout_multiplier_bp": 5000,
            },
            rival_gm_headers,
        ),
        201,
    )
    assert third_offer["offer_status"] == "SENT"
    validate_error(
        api_client.accept_contract_offer(
            third_offer["id"], {"effective_at": "2026-08-05T00:00:00Z"}, agent_headers
        ),
        ApiErrorId.ERR_PLAYER_ALREADY_SIGNED.value,
        409,
    )

    _rows, meta = validate_paginated(
        api_client.list_contracts(
            make_league_admin_headers(), params={"player_id": player["id"]}
        )
    )
    assert meta["total_count"] == 1
    rival_org = validate_success(api_client.get_organization(rival["id"], rival_gm_headers))
    assert rival_org["committed_salary_cents"] == 0
    assert rival_org["active_roster_count"] == 0
