"""Cancellation cascades, the decline cascade, settlement and the three status axes."""

from test_helpers import (
    ARTISTIC_ADMIN,
    ApiErrorId,
    add_engagement,
    build_world,
    create_contract,
    create_musician,
    create_service,
    decline_engagement,
    open_public_onsale,
    open_renewal_window,
    publish_service,
    read_concert,
    read_contract,
    read_engagement,
    read_musician,
    read_season,
    read_service,
    setup_locked_concert,
    setup_published_service,
    sign_contract_as_artist,
    start_season,
    validate_error,
    validate_success,
)

UNION_TERMS = {
    "scale_service_fee_cents": 20000,
    "max_service_minutes": 150,
    "overtime_rate_cents_per_minute": 400,
    "mandatory_break_minutes": 20,
    "principal_premium_bp": 2000,
    "doubling_premium_bp": 1250,
}


def _locked_concert_on_public_sale():
    world = setup_locked_concert(
        world_kwargs={"union_overrides": {"scale_service_fee_cents": 20000}},
        contract_overrides={"artist_name": "Mira Halvorsen", "role_type": "CONDUCTOR",
                            "offered_fee_cents": 800000},
    )
    open_renewal_window(world.season["id"])
    open_public_onsale(world.season)
    world.concert = read_concert(world.concert["id"])
    return world


def _published_service_with_one_rank_and_file_player():
    return setup_published_service(
        world_kwargs={"union_overrides": UNION_TERMS},
        service_overrides={
            "scheduled_start_utc": "2026-11-04T14:00:00Z",
            "scheduled_end_utc": "2026-11-04T17:00:00Z",
            "minimum_complement": 1,
            "break_minutes": 30,
        },
        musician_specs=({"full_name": "Pia Solberg", "instrument": "VIOLIN"},),
    )


def _locked_concert_with_two_player_service():
    world = build_world(union_overrides={"scale_service_fee_cents": 20000,
                                         "mandatory_break_minutes": 20})
    contract = create_contract(world.concert["id"], artist_name="Mira Halvorsen",
                               role_type="CONDUCTOR", offered_fee_cents=800000)
    sign_contract_as_artist(contract["id"])

    first_player = create_musician(full_name="Pia Solberg", instrument="VIOLIN")
    second_player = create_musician(full_name="Tomas Reiner", instrument="CELLO")
    service = create_service(
        world.concert["id"], world.venue["id"], service_type="DRESS_REHEARSAL",
        scheduled_start_utc="2026-11-04T14:00:00Z",
        scheduled_end_utc="2026-11-04T16:00:00Z",
        minimum_complement=2, break_minutes=20,
    )
    first_engagement = add_engagement(service["id"], first_player["id"])
    second_engagement = add_engagement(service["id"], second_player["id"])
    publish_service(service["id"])

    world.contract = contract
    world.service = service
    world.musicians = [first_player, second_player]
    world.engagements = [first_engagement, second_engagement]
    return world


# --------------------------------------------------------------------------
# The three parallel status dimensions
# --------------------------------------------------------------------------
def test_cancellation_closes_sales_but_leaves_the_programming_axis_locked(api):
    """PRD 2.7: "Cancelling a concert drives `performance_status` to `CANCELLED` and
    `sale_status` to `SALES_CLOSED`, but it explicitly leaves `programming_status`
    untouched — a cancelled concert that had been `LOCKED` stays `LOCKED`."
    PRD 3.9: "The concert's `performance_status` becomes `CANCELLED`, its
    `sale_status` becomes `SALES_CLOSED`, and the season's
    `concerts_cancelled_count` increments by one."

    Design: Difficulty/non_linear_state_machine/concert_parallel_status_dimensions_independent
    """
    world = _locked_concert_on_public_sale()
    assert world.concert["programming_status"] == "LOCKED"
    assert world.concert["sale_status"] == "PUBLIC_ONSALE"
    assert world.concert["performance_status"] == "SCHEDULED"

    cancelled = validate_success(
        api.cancel_concert(world.concert["id"], "conductor illness", ARTISTIC_ADMIN)
    )

    assert cancelled["performance_status"] == "CANCELLED"
    assert cancelled["sale_status"] == "SALES_CLOSED"
    assert cancelled["programming_status"] == "LOCKED", (
        "the programming axis moves independently and is not touched by cancellation"
    )


def test_cancellation_cancels_services_but_leaves_a_signed_contract_alone(api):
    """PRD 3.9: "Hop one: every rehearsal service of this concert whose status is
    `DRAFT` or `PUBLISHED` moves to `CANCELLED`, processed in ascending
    `scheduled_start_utc` order with ties broken by ascending `created_at`."
    PRD 3.9: "Every guest artist contract of this concert still in `OFFERED` or
    `COUNTERED` moves to `WITHDRAWN`; contracts already `SIGNED` are left alone."

    Design: Difficulty/non_linear_state_machine/concert_parallel_status_dimensions_independent
    """
    world = _locked_concert_on_public_sale()

    validate_success(
        api.cancel_concert(world.concert["id"], "conductor illness", ARTISTIC_ADMIN)
    )

    assert read_service(world.service["id"])["status"] == "CANCELLED"
    assert read_contract(world.contract["id"])["status"] == "SIGNED"
    assert read_season(world.season["id"])["concerts_cancelled_count"] == 1


def test_cancelling_an_already_cancelled_concert_is_refused(api):
    """PRD 3.9: "An `ArtisticAdmin` performs it with a `reason`, on a concert whose
    `performance_status` is `SCHEDULED` — anything else is
    `ERR_CONCERT_ALREADY_CANCELLED` — and whose season has not yet reached
    `CLOSED`, else `ERR_INVALID_SEASON_TRANSITION`."

    Design: Corner/state_machines/cancel_concert_twice_returns_already_cancelled
    """
    world = build_world(with_union=False)
    validate_success(api.cancel_concert(world.concert["id"], "hall flood",
                                        ARTISTIC_ADMIN))

    response = api.cancel_concert(world.concert["id"], "hall flood again",
                                  ARTISTIC_ADMIN)
    validate_error(response, ApiErrorId.ERR_CONCERT_ALREADY_CANCELLED.value, 409)

    assert read_concert(world.concert["id"])["performance_status"] == "CANCELLED"
    assert read_season(world.season["id"])["concerts_cancelled_count"] == 1, (
        "the refused second cancellation must not double-count"
    )


# --------------------------------------------------------------------------
# The personnel cascade
# --------------------------------------------------------------------------
def test_cancellation_voids_the_engagements_of_its_published_services(api):
    """PRD 3.9: "Hop one: every rehearsal service of this concert whose status is
    `DRAFT` or `PUBLISHED` moves to `CANCELLED`, processed in ascending
    `scheduled_start_utc` order with ties broken by ascending `created_at`. Hop
    two, caused by hop one: every engagement of each service that just became
    `CANCELLED` whose status is `CONFIRMED` moves to `VOIDED`."

    Design: Difficulty/transitive_cascade/concert_cancel_service_engagement_musician_chain
    """
    world = _published_service_with_one_rank_and_file_player()
    assert read_engagement(world.engagement["id"])["provisional_pay_cents"] == 20000

    validate_success(api.cancel_concert(world.concert["id"], "hall flood",
                                        ARTISTIC_ADMIN))

    assert read_concert(world.concert["id"])["performance_status"] == "CANCELLED"
    assert read_service(world.service["id"])["status"] == "CANCELLED"

    voided = read_engagement(world.engagement["id"])
    assert voided["status"] == "VOIDED"
    assert voided["provisional_pay_cents"] == 20000, (
        "the priced figure stays on the row as history"
    )


def test_voided_engagement_refunds_the_musician_service_credit_and_earnings(api):
    """PRD 3.9: "Hop three, caused by hop two: each engagement entering `VOIDED`
    whose `provisional_pay_cents` is not null decrements its musician's
    `services_charged_ytd` by one and subtracts that same provisional figure from
    the musician's `ytd_earnings_cents`."
    PRD 3.9: "What the cancellation explicitly does **not** change is the concert's
    `programming_status` or its `readiness_posture`: both are left exactly as they
    stood before the cancellation, so a cancelled concert that was `LOCKED` remains
    `LOCKED` and a posture of `BLOCKED` or `AT_RISK` survives the cancellation
    unchanged."

    Design: Difficulty/transitive_cascade/concert_cancel_service_engagement_musician_chain
    """
    world = _published_service_with_one_rank_and_file_player()
    before = read_musician(world.musician["id"])
    assert before["services_charged_ytd"] == 1
    assert before["ytd_earnings_cents"] == 20000

    validate_success(api.cancel_concert(world.concert["id"], "hall flood",
                                        ARTISTIC_ADMIN))

    after = read_musician(world.musician["id"])
    assert after["services_charged_ytd"] == 0
    assert after["ytd_earnings_cents"] == 0

    assert read_concert(world.concert["id"])["programming_status"] == "PROGRAMMED", (
        "cancellation never touches the programming axis"
    )


def test_cancelling_a_draft_service_voids_without_touching_the_ledger(api):
    """PRD 2.11: "Declining or voiding an engagement is the compensating action and
    refunds exactly one credit, but only when that engagement was actually charged:
    an engagement on a service that never reached publication has a null
    `provisional_pay_cents`, was never charged, and is therefore never refunded."
    PRD 3.9: "An engagement whose service never reached publication carries a null
    `provisional_pay_cents`, was never charged, and so is voided without any ledger
    movement."

    Design: Corner/state_machines/draft_service_cancellation_does_not_refund_service_credit
    """
    world = build_world(union_overrides={"scale_service_fee_cents": 20000})
    player = create_musician(full_name="Pia Solberg", instrument="VIOLIN")
    service = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T14:00:00Z",
        scheduled_end_utc="2026-11-04T16:00:00Z",
        minimum_complement=1, break_minutes=20,
    )
    engagement = add_engagement(service["id"], player["id"])

    validate_success(api.cancel_concert(world.concert["id"], "programme change",
                                        ARTISTIC_ADMIN))

    assert read_service(service["id"])["status"] == "CANCELLED"
    voided = read_engagement(engagement["id"])
    assert voided["status"] == "VOIDED"
    assert voided["provisional_pay_cents"] is None

    player_after = read_musician(player["id"])
    assert player_after["services_charged_ytd"] == 0
    assert player_after["ytd_earnings_cents"] == 0


# --------------------------------------------------------------------------
# The decline cascade
# --------------------------------------------------------------------------
def test_decline_marks_the_service_understaffed_and_reprices_it(api):
    """PRD 3.3: "Hop one decrements the parent service's
    `confirmed_engagement_count` by one. Hop two, caused by hop one: if the service
    is `PUBLISHED` and its `confirmed_engagement_count` has now fallen below its
    `minimum_complement`, the service's `compliance_status` becomes `UNDERSTAFFED`
    and its `provisional_service_cost_cents` is recomputed over the engagements
    that remain."
    PRD 3.3: "Before it begins, if the engagement had already been priced — that is,
    its `provisional_pay_cents` is not null — the player's `services_charged_ytd`
    is decremented by one and their `ytd_earnings_cents` is reduced by that
    provisional figure, per the ledger discipline of §2.11."

    Design: Difficulty/transitive_cascade/engagement_decline_service_concert_unlock_chain
    """
    world = _locked_concert_with_two_player_service()
    leaving, staying = world.musicians
    leaving_engagement = world.engagements[0]

    declined = decline_engagement(leaving_engagement["id"], leaving["id"])
    assert declined["status"] == "DECLINED"

    service = read_service(world.service["id"])
    assert service["confirmed_engagement_count"] == 1
    assert service["compliance_status"] == "UNDERSTAFFED"
    assert service["provisional_service_cost_cents"] == 20000, (
        "recomputed over the one engagement that remains"
    )

    assert read_musician(leaving["id"])["services_charged_ytd"] == 0
    assert read_musician(staying["id"])["services_charged_ytd"] == 1


def test_understaffed_service_puts_the_concert_at_risk_and_unlocks_it(api):
    """PRD 3.3: "Hop three, caused by hop two: the parent concert's
    `readiness_posture` becomes `AT_RISK`. Hop four, caused by hop three: if that
    concert's `programming_status` is `LOCKED` it reverts to `PROGRAMMED`, because
    the orchestra can no longer claim the concert is fully staffed."
    PRD 2.7: "Conversely, the programming unlock edge — the revert from `LOCKED`
    back to `PROGRAMMED` — never touches `sale_status` or `performance_status`; a
    concert that reverts to `PROGRAMMED` while already `PUBLIC_ONSALE` remains on
    sale."

    Design: Difficulty/transitive_cascade/engagement_decline_service_concert_unlock_chain
    """
    world = _locked_concert_with_two_player_service()
    assert read_concert(world.concert["id"])["programming_status"] == "LOCKED"
    leaving = world.musicians[0]

    decline_engagement(world.engagements[0]["id"], leaving["id"])

    concert = read_concert(world.concert["id"])
    assert concert["readiness_posture"] == "AT_RISK"
    assert concert["programming_status"] == "PROGRAMMED", "reverted from LOCKED"
    assert concert["sale_status"] == "UNANNOUNCED", (
        "the unlock edge never touches the sale axis"
    )
    assert concert["performance_status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# Settlement
# --------------------------------------------------------------------------
def test_settling_with_an_unclocked_published_service_is_refused(api):
    """PRD 3.9: "An `ArtisticAdmin` settles a concert whose `performance_status` is
    `SCHEDULED`, whose season has reached `IN_PROGRESS`, and every one of whose
    `PUBLISHED` services has already been clocked out to `COMPLETED`; a failure of
    any of those three conditions is reported as `ERR_CONCERT_NOT_SETTLEABLE`."

    Design: Corner/state_machines/settle_concert_with_unclocked_published_service_returns_not_settleable
    """
    world = build_world(union_overrides={"scale_service_fee_cents": 20000})
    service = create_service(
        world.concert["id"], world.venue["id"], service_type="PERFORMANCE",
        scheduled_start_utc="2026-11-05T19:30:00Z",
        scheduled_end_utc="2026-11-05T20:30:00Z",
        minimum_complement=0, break_minutes=0,
    )
    publish_service(service["id"])

    open_renewal_window(world.season["id"])
    open_public_onsale(world.season)
    start_season(world.season["id"])

    response = api.settle_concert(world.concert["id"], ARTISTIC_ADMIN)
    validate_error(response, ApiErrorId.ERR_CONCERT_NOT_SETTLEABLE.value, 409)

    concert = read_concert(world.concert["id"])
    assert concert["performance_status"] == "SCHEDULED"
    assert concert["sale_status"] == "PUBLIC_ONSALE"
    assert read_service(service["id"])["status"] == "PUBLISHED"
