"""Gates that live on a different record than the one being created.

A practice block carries no state that could explain its own refusal — the
attendee's contract does. A deliverable carries none either — its parent deal
does. In both pairs the identical payload is admitted before the parent moves and
refused afterwards.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    make_coaching_staff_headers,
    make_general_manager_headers,
    make_league_admin_headers,
    make_sponsorship_manager_headers,
    validate_error,
    validate_success,
)


def _two_contracts_and_a_house():
    """One organization holding two ACTIVE contracts, clock at 2026-08-09."""
    ctx = fixtures.setup_two_signed_players(with_team_house=True)
    fixtures.set_clock("2026-08-09T00:00:00Z")
    return ctx


def _book_for(ctx, player_id, starts_at, ends_at):
    return api_client.create_practice_block(
        {
            "organization_id": ctx["org"]["id"],
            "team_house_id": ctx["house"]["id"],
            "block_type": "INDIVIDUAL",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "participant_player_ids": [player_id],
        },
        make_coaching_staff_headers(),
    )


def test_suspending_the_attendees_contract_cancels_the_block_it_already_had():
    """The block never changed; the contract under it did, and the sweep reached the block.

    PRD: "A participant who owns at least one contract in `ACTIVE`, `SUSPENDED` or `TERMINATED` must
    own an `ACTIVE` one; if their only employment is suspended or terminated, the booking is refused
    with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409)."
    PRD: "And every block that is still `SCHEDULED` and whose `starts_at` is strictly later than the
    current instant and which lists the suspended contract's player is cancelled with `cancel_reason`
    of `CONTRACT_SUSPENDED`."
    PRD: "The organization's `active_roster_count` decreases by 1, but its `committed_salary_cents`
    is **not** released — a suspended contract still consumes cap space, which is what stops
    suspension from being used as a budget trick."

    Design: Difficulty/cross_entity_state_dependency/practice_block_creation_depends_on_player_contract_contract_status
    """
    ctx = _two_contracts_and_a_house()
    gm_headers = make_general_manager_headers(ctx["org"]["id"])

    before = validate_success(api_client.get_organization(ctx["org"]["id"], gm_headers))
    assert before["committed_salary_cents"] == 22191781
    assert before["active_roster_count"] == 2

    booked = validate_success(
        _book_for(
            ctx, ctx["player_one"]["id"], "2026-08-12T10:00:00Z", "2026-08-12T13:00:00Z"
        ),
        201,
    )
    assert booked["block_status"] == "SCHEDULED"

    suspended = validate_success(
        api_client.suspend_contract(
            ctx["contract_one"]["id"],
            {"suspension_reason": "disciplinary review"},
            make_league_admin_headers(),
        )
    )
    assert suspended["contract_status"] == "SUSPENDED"

    swept = validate_success(
        api_client.get_practice_block(booked["id"], make_coaching_staff_headers())
    )
    assert swept["block_status"] == "CANCELLED"
    assert swept["cancel_reason"] == "CONTRACT_SUSPENDED"

    after = validate_success(api_client.get_organization(ctx["org"]["id"], gm_headers))
    assert after["committed_salary_cents"] == 22191781
    assert after["active_roster_count"] == 1


def test_the_booking_gate_reads_each_attendees_own_contract():
    """After the suspension the same request fails for that player and still passes for the other.

    PRD: "Before a booking is admitted, each attendee is examined against their employment."
    PRD: "A participant who owns at least one contract in `ACTIVE`, `SUSPENDED` or `TERMINATED` must
    own an `ACTIVE` one; if their only employment is suspended or terminated, the booking is refused
    with `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409)."
    PRD: "On insertion the server derives `duration_minutes` as the number of whole minutes between
    `starts_at` and `ends_at`, stamps the booking coach's identifier into `coach_user_id`, sets
    `block_status` to `SCHEDULED` and leaves `cancel_reason` null."

    Design: Difficulty/cross_entity_state_dependency/practice_block_creation_depends_on_player_contract_contract_status
    """
    ctx = _two_contracts_and_a_house()
    validate_success(
        api_client.suspend_contract(
            ctx["contract_one"]["id"],
            {"suspension_reason": "disciplinary review"},
            make_league_admin_headers(),
        )
    )

    refused = _book_for(
        ctx, ctx["player_one"]["id"], "2026-08-13T10:00:00Z", "2026-08-13T13:00:00Z"
    )
    validate_error(refused, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)

    admitted = validate_success(
        _book_for(
            ctx, ctx["player_two"]["id"], "2026-08-14T10:00:00Z", "2026-08-14T13:00:00Z"
        ),
        201,
    )
    assert admitted["block_status"] == "SCHEDULED"
    assert admitted["cancel_reason"] is None
    assert admitted["participant_player_ids"] == [ctx["player_two"]["id"]]


def _draft_deal_over_one_contract():
    """One ACTIVE contract and a DRAFT two-deliverable deal worth 1,000,000 cents."""
    ctx = fixtures.setup_signed_player()
    fixtures.set_clock("2026-08-09T00:00:00Z")
    ctx["deal"] = fixtures.create_deal(ctx["org"]["id"])
    ctx["sponsor_headers"] = make_sponsorship_manager_headers(ctx["org"]["id"])
    return ctx


def _place(ctx, expected_deal_version):
    return api_client.create_deliverable_assignment(
        ctx["deal"]["id"],
        {
            "contract_id": ctx["contract"]["id"],
            "deliverable_type": "SOCIAL_POST",
            "due_at": "2026-09-01T00:00:00Z",
            "expected_deal_version": expected_deal_version,
        },
        ctx["sponsor_headers"],
    )


def test_a_deliverable_cannot_be_placed_while_its_parent_deal_is_still_a_draft():
    """The concurrency token matches, so the refusal can only come from the parent's status.

    PRD: "`DRAFT` deals are inert: they carry no obligations and they never conflict with anything."
    PRD: "Placing a deliverable is a nested creation against an `ACTIVE` deal, and it is the one
    operation in this area that carries a concurrency token."
    PRD: "A drafted deal has `deal_status` of `DRAFT`, `assigned_count` and `approved_count` both 0,
    and one derived flag: `minor_permitted` is false when the `exclusivity_category` is
    `ENERGY_DRINK`, `BETTING` or `CRYPTO`, and true for `PERIPHERALS` and `APPAREL`."

    Design: Difficulty/cross_entity_state_dependency/deliverable_placement_depends_on_sponsorship_deal_deal_status
    """
    ctx = _draft_deal_over_one_contract()
    assert ctx["deal"]["deal_status"] == "DRAFT"
    assert ctx["deal"]["assigned_count"] == 0

    refused = _place(ctx, ctx["deal"]["version"])
    validate_error(refused, ApiErrorId.ERR_DEAL_NOT_ACTIVE.value, 409)

    stored = validate_success(
        api_client.get_sponsorship_deal(ctx["deal"]["id"], ctx["sponsor_headers"])
    )
    assert stored["deal_status"] == "DRAFT"
    assert stored["assigned_count"] == 0
    assert stored["version"] == ctx["deal"]["version"]


def test_activation_admits_the_identical_placement_and_freezes_the_fee_share():
    """Only the parent moved DRAFT to ACTIVE, and the same payload is now a 201.

    PRD: "Activation, performed by the sponsorship manager of the owning organization, moves
    `deal_status` `DRAFT` → `ACTIVE` and advances the deal's `version`; a deal that is not `DRAFT`
    yields `ERR_DEAL_NOT_ACTIVE` (HTTP 409)."
    PRD: "A successful placement creates an assignment whose `sponsorship_deal_id` comes from the
    path, whose `assignment_status` is `ASSIGNED`, whose `rejection_count` is 0 and whose
    `submission_note` and `review_note` are null."
    PRD: "Its `fee_share_cents` is frozen at creation as the deal's `total_fee_cents` divided by its
    `deliverable_count_required` with the fractional remainder discarded."
    PRD: "Once `approved_count` equals `deliverable_count_required`, the deal moves `ACTIVE` →
    `FULFILLED` in the same request as the final approval."

    Design: Difficulty/cross_entity_state_dependency/deliverable_placement_depends_on_sponsorship_deal_deal_status
    """
    ctx = _draft_deal_over_one_contract()
    validate_error(_place(ctx, ctx["deal"]["version"]), ApiErrorId.ERR_DEAL_NOT_ACTIVE.value, 409)

    activated = validate_success(
        api_client.activate_sponsorship_deal(ctx["deal"]["id"], ctx["sponsor_headers"])
    )
    assert activated["deal_status"] == "ACTIVE"
    assert activated["version"] > ctx["deal"]["version"]

    placed = validate_success(_place(ctx, activated["version"]), 201)
    assert placed["assignment_status"] == "ASSIGNED"
    assert placed["fee_share_cents"] == 500000
    assert placed["rejection_count"] == 0
    assert placed["submission_note"] is None
    assert placed["review_note"] is None

    deal = validate_success(
        api_client.get_sponsorship_deal(ctx["deal"]["id"], ctx["sponsor_headers"])
    )
    assert deal["deal_status"] == "ACTIVE"
    assert deal["assigned_count"] == 1
    assert deal["approved_count"] == 0
