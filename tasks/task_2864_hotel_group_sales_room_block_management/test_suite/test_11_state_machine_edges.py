"""Declared transitions, and the ones that were never declared.

Every entity in PRD section 3 starts in one named state and leaves it only
through a transition the PRD writes down; PRD 2.8 refuses anything else at
priority 10 with the entity's own invalid-state error. These tests walk the
initial states, the terminal states and the edges that are easy to invent by
accident.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    REVENUE_MANAGER,
    REVENUE_MANAGER_ALT_ID,
    RESERVATIONS_AGENT,
    SALES_MANAGER,
    AnalysisStatus,
    AnalysisVariant,
    ApiErrorId,
    ContractStatus,
    HoldStatus,
    LeadStatus,
    MarketSegment,
    QuoteStatus,
    ReservationStatus,
    SpaceCode,
    assert_displacement_analysis,
    assert_function_space_hold,
    assert_group_contract,
    assert_lead,
    assert_pickup_summary,
    assert_rate_quote,
    assert_reservation,
    committed_rooms,
    constants as C,
    decide_displacement_analysis,
    factories as F,
    held_rooms,
    pickup_summary,
    read_lead,
    read_quote,
    reset_clock,
    seed_account,
    seed_displacement_analysis,
    seed_draft_contract,
    seed_draft_quote,
    seed_function_space_hold,
    seed_inventory_days,
    seed_lead,
    seed_open_master_block,
    seed_proposed_quote,
    seed_qualified_lead,
    seed_reservation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

_BALLROOM_DAY = {
    "space_code": SpaceCode.GRAND_BALLROOM,
    "start_at": "2026-11-09T09:00:00Z",
    "end_at": "2026-11-09T17:00:00Z",
    "attendee_count": 80,
}


def test_a_captured_lead_waits_in_new_with_no_score_of_any_kind(api):
    """Capture records the enquiry; it does not judge it.

    PRD 3.2 starts a lead in NEW with qualification_score and
    estimated_room_night_value_cents null, and it is the separate qualify
    operation that "requires an InventoryDay for every date of the half-open
    stay range" - so capture succeeds against a house with no calendar at all.
    An implementation that scores on create would report QUALIFIED here and
    would also have skipped that calendar check.

    Design: Corner/state_machines/lead_starts_in_new_and_carries_no_score
    """
    reset_clock(api)
    account = seed_account(api)

    created = validate_success(
        api.create_lead(
            F.lead_payload(account["id"], program_name="Un-scored On Purpose"),
            SALES_MANAGER,
        ),
        201,
    )

    assert_lead(
        created,
        status=LeadStatus.NEW,
        qualification_score=None,
        estimated_room_night_value_cents=None,
        peak_rooms=4,
        total_requested_room_nights=12,
        version=1,
    )


def test_a_second_qualification_conflicts_and_rewrites_nothing(api):
    """Qualification happens once; the replay is refused, not repeated.

    PRD 3.2 declares qualify only from NEW and refuses "a second qualification
    attempt against any lead that is no longer NEW" with ERR_LEAD_INVALID_STATE.
    PRD 2.5 advances version only on a successful mutation, so a refused replay
    must leave the score, the status and the version exactly where the first
    qualification left them - a recompute-and-rewrite would show version 3.

    Design: Corner/state_machines/qualify_is_one_shot_and_the_second_call_conflicts
    """
    world = seed_qualified_lead(api)

    validate_error(
        api.qualify_lead(world["lead_id"], SALES_MANAGER),
        ApiErrorId.LEAD_INVALID_STATE,
        409,
    )

    assert_lead(
        read_lead(api, world["lead_id"]),
        status=LeadStatus.QUALIFIED,
        qualification_score=35,
        version=2,
    )


def test_a_turned_down_lead_releases_its_space_and_accepts_nothing_further(api):
    """The low-scoring branch is terminal and takes the meeting space with it.

    PRD 3.2 scales the same raw 29 points by the SMERF multiplier of 0.75 to 22,
    below the inclusive floor of 30, so the identical enquiry that qualifies for
    a CORPORATE organization is turned down here. The branches "are not
    symmetric in their consequences": the turn-down "releases the lead's meeting
    space, moving every function-space hold of that lead whose status is HELD to
    RELEASED", while still writing the room-night value. TURNED_DOWN is then
    terminal from both directions - PRD 3.2 refuses a re-qualification and PRD
    3.3 refuses a displacement study against it, both with
    ERR_LEAD_INVALID_STATE.

    Design: Corner/state_machines/turned_down_lead_is_terminal_and_releases_its_space_hold
    """
    reset_clock(api)
    account = seed_account(api, market_segment=MarketSegment.SMERF)
    seed_inventory_days(api)
    lead = seed_lead(api, account["id"])
    seed_function_space_hold(api, lead["id"], **_BALLROOM_DAY)

    turned_down = validate_success(api.qualify_lead(lead["id"], SALES_MANAGER))

    assert_lead(
        turned_down,
        status=LeadStatus.TURNED_DOWN,
        qualification_score=22,
        estimated_room_night_value_cents=206640,
        version=2,
    )
    holds, _ = validate_paginated(
        api.list_lead_function_space_holds(lead["id"], SALES_MANAGER)
    )
    assert_function_space_hold(holds[0], status=HoldStatus.RELEASED)

    validate_error(
        api.qualify_lead(lead["id"], SALES_MANAGER),
        ApiErrorId.LEAD_INVALID_STATE,
        409,
    )
    validate_error(
        api.create_displacement_analysis(
            F.displacement_analysis_payload(lead["id"]), REVENUE_MANAGER
        ),
        ApiErrorId.LEAD_INVALID_STATE,
        409,
    )
    assert_lead(
        read_lead(api, lead["id"]), status=LeadStatus.TURNED_DOWN, version=2
    )


_QUOTE_EXPIRES_AT = "2026-10-01T00:00:00Z"


def test_countering_a_draft_and_signing_a_draft_are_both_refused(api):
    """Skipping a step is refused, and the skipped step still works afterwards.

    PRD 3.4 declares a counter only from PROPOSED and refuses "countering a
    DRAFT quote" with ERR_QUOTE_INVALID_STATE; PRD 3.5 countersigns only a SENT
    contract, so "signing a contract that is not SENT - a DRAFT one" is
    ERR_CONTRACT_INVALID_STATE, and cancellation, declared from SENT or SIGNED,
    refuses "any attempt against a contract that is DRAFT". Each refusal is
    scoped to its own entity, and neither may poison the row: the same quote
    proposes and is accepted, and the same contract issues as its second
    version.

    Design: Corner/state_machines/counter_before_propose_and_sign_before_send_both_conflict
    """
    world = seed_draft_quote(api)

    validate_error(
        api.counter_rate_quote(
            world["quote_id"], F.counter_payload(), world["group_contact"]
        ),
        ApiErrorId.QUOTE_INVALID_STATE,
        409,
    )

    assert_rate_quote(
        validate_success(api.propose_rate_quote(world["quote_id"], SALES_MANAGER)),
        status=QuoteStatus.PROPOSED,
    )
    assert_rate_quote(
        validate_success(
            api.accept_rate_quote(world["quote_id"], world["group_contact"])
        ),
        status=QuoteStatus.ACCEPTED,
    )
    seed_draft_contract(api, world)

    validate_error(
        api.sign_contract(world["contract_id"], F.sign_payload(), CONTRACT_ADMIN),
        ApiErrorId.CONTRACT_INVALID_STATE,
        409,
    )
    validate_error(
        api.cancel_contract(
            world["contract_id"], F.cancel_contract_payload(), CONTRACT_ADMIN
        ),
        ApiErrorId.CONTRACT_INVALID_STATE,
        409,
    )

    assert_group_contract(
        validate_success(api.send_contract(world["contract_id"], CONTRACT_ADMIN)),
        status=ContractStatus.SENT,
        version=2,
    )


def test_an_acceptance_at_the_expiry_instant_expires_the_quote_and_fails(api):
    """One request expires the quote, releases the rooms and still rejects.

    PRD 3.4 evaluates expiry lazily, "when the quote is next read for writing":
    if an acceptance "is attempted at or after the quote's expires_at, the quote
    moves from PROPOSED or COUNTERED to EXPIRED, hold_placed becomes false,
    held_group_rooms decreases by quoted_peak_rooms on every occupied date, and
    the triggering request is itself rejected with ERR_QUOTE_EXPIRED". The
    boundary is inclusive, so a clock standing exactly on expires_at is already
    expired, and the lead's negotiation stage is not part of the cascade.

    Design: Corner/state_machines/lazy_quote_expiry_releases_the_hold_and_rejects_the_accept
    """
    world = seed_proposed_quote(api)
    assert held_rooms(api, C.STAY_DATES) == [4, 4, 4]
    set_clock(api, _QUOTE_EXPIRES_AT)

    validate_error(
        api.accept_rate_quote(world["quote_id"], world["group_contact"]),
        ApiErrorId.QUOTE_EXPIRED,
        422,
    )

    assert_rate_quote(
        read_quote(api, world["quote_id"]),
        status=QuoteStatus.EXPIRED,
        hold_placed=False,
    )
    assert held_rooms(api, C.STAY_DATES) == [0, 0, 0], (
        "the failed request must still have released the soft hold"
    )
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.QUOTED)
    assert committed_rooms(api, C.STAY_DATES) == [0, 0, 0], (
        "no contract was ever countersigned, so nothing is committed"
    )


def test_a_counter_then_a_flat_revise_returns_the_quote_to_the_client(api):
    """The non-increasing revise is the leg that keeps both the hold and the lead.

    PRD 3.4 keeps the hold across a counter - "hold_placed stays true and the
    rooms stay in held_group_rooms on every occupied date" - and does not
    advance negotiation_round, "that counter moves only when the hotel
    re-prices". The revise then does move it, and because quoted_peak_rooms is
    unchanged "the quote returns COUNTERED to PROPOSED and stays in the client's
    court", with held_group_rooms moved by a difference of zero. The re-price
    runs on the new base of 22000 as "a subtraction of four already-rounded
    integers" - 22000 less 1595 less 537 less 750 - and multiplies by the 12
    quoted room nights. The lead is untouched, so it does not fall back to
    DISPLACEMENT_REVIEW as the upward leg would make it.

    Design: Corner/state_machines/counter_then_downward_revise_returns_to_proposed_and_keeps_the_hold
    """
    world = seed_proposed_quote(api)

    countered = validate_success(
        api.counter_rate_quote(
            world["quote_id"],
            F.counter_payload(
                countered_base_rate_cents=22000,
                counter_note="Budget is 220 per night",
            ),
            world["group_contact"],
        )
    )
    assert_rate_quote(
        countered,
        status=QuoteStatus.COUNTERED,
        negotiation_round=1,
        hold_placed=True,
        countered_base_rate_cents=22000,
    )

    revised = validate_success(
        api.revise_rate_quote(
            world["quote_id"],
            F.revise_payload(
                base_rate_cents=22000, quoted_peak_rooms=4, quoted_room_nights=12
            ),
            SALES_MANAGER,
        )
    )

    assert_rate_quote(
        revised,
        status=QuoteStatus.PROPOSED,
        negotiation_round=2,
        hold_placed=True,
        effective_net_rate_cents=19118,
        total_quote_value_cents=229416,
    )
    assert held_rooms(api, C.STAY_DATES) == [4, 4, 4], (
        "an unchanged peak count adjusts the hold by zero"
    )
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.QUOTED)


def test_a_rejection_from_quoted_kills_the_deal_and_unwinds_both_holds(api):
    """The deal can die from QUOTED, and the death has a two-part cascade.

    PRD 3.3 lets a study be requested against a lead that is already QUOTED and,
    on REJECT, moves "the lead to LOST from whichever of DISPLACEMENT_REVIEW,
    CLEARED, or QUOTED it occupied". The cascade then runs both compensations:
    "every rate quote of the lead whose status is DRAFT, PROPOSED, or COUNTERED
    moves to WITHDRAWN", each proposed quote's hold is released so held_group_rooms
    "decreases by that quote's quoted_peak_rooms", and "every function-space hold
    of the lead still in HELD moves to RELEASED". The lead's version counts
    exactly the seven writes it has taken: capture, qualification, the first
    study, the first approval, the proposal, the re-study and this rejection.

    Design: Corner/state_machines/reject_decision_withdraws_the_quote_and_unwinds_both_holds
    """
    world = seed_proposed_quote(api)
    hold = seed_function_space_hold(api, world["lead_id"], **_BALLROOM_DAY)
    restudy = seed_displacement_analysis(
        api, world, analysis_variant=AnalysisVariant.FORECAST_BASED
    )
    assert_displacement_analysis(restudy, status=AnalysisStatus.PENDING)
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.QUOTED)

    rejected = decide_displacement_analysis(
        api, world, restudy["id"], decision="REJECT"
    )

    assert_displacement_analysis(
        rejected,
        status=AnalysisStatus.REJECTED,
        decided_by_user_id=REVENUE_MANAGER_ALT_ID,
    )
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.LOST, version=7)
    assert_rate_quote(
        read_quote(api, world["quote_id"]),
        status=QuoteStatus.WITHDRAWN,
        hold_placed=False,
    )
    assert_function_space_hold(
        validate_success(api.get_function_space_hold(hold["id"], SALES_MANAGER)),
        status=HoldStatus.RELEASED,
    )
    assert held_rooms(api, C.STAY_DATES) == [0, 0, 0]


def test_every_hop_of_a_stay_checks_its_own_precondition(api):
    """Three preconditions on one guest: the skip, the late cancel, the no-show.

    PRD 3.6 declares four advances and refuses "any to_status for which no
    transition is declared from the reservation's current status" with
    ERR_RESERVATION_INVALID_STATE, so CHECKED_IN is unreachable from PENDING.
    Cancellation is admissible "only while the logical clock's current date is
    strictly before the reservation's arrival_date - after arrival the
    cancellation channel is closed with ERR_CANCEL_AFTER_ARRIVAL and the guest
    can only be advanced or marked a no-show"; the cutoff-date bar of PRD 3.6
    applies to writing a rooming-list entry, not to cancelling one, so it must
    not pre-empt that answer. The no-show is then the asymmetry PRD 3.7 turns on:
    it "leaves the pickup set" but "the no-show's room nights stay inside the
    actualized set that attrition is measured against", so one actualized room
    night stands against a ROOM_NIGHTS commitment of ceil(12 * 0.75) = 9 while
    pickup reads 0.

    Design: Corner/state_machines/reservation_advance_preconditions_are_enforced_at_every_hop
    """
    world = seed_open_master_block(api)
    reservation = seed_reservation(
        api,
        world["master_block_id"],
        arrival_date="2026-11-09",
        departure_date="2026-11-10",
    )
    assert_reservation(reservation, status=ReservationStatus.PENDING)

    validate_error(
        api.advance_reservation(
            reservation["id"], F.advance_payload("CHECKED_IN"), RESERVATIONS_AGENT
        ),
        ApiErrorId.RESERVATION_INVALID_STATE,
        409,
    )
    assert_reservation(
        validate_success(
            api.advance_reservation(
                reservation["id"], F.advance_payload("CONFIRMED"), RESERVATIONS_AGENT
            )
        ),
        status=ReservationStatus.CONFIRMED,
    )

    set_clock(api, "2026-11-09T00:00:00Z")

    validate_error(
        api.cancel_reservation(
            reservation["id"],
            F.cancel_reservation_payload(disposition_reason="Traveller withdrew"),
            RESERVATIONS_AGENT,
        ),
        ApiErrorId.CANCEL_AFTER_ARRIVAL,
        422,
    )
    assert_reservation(
        validate_success(
            api.advance_reservation(
                reservation["id"], F.advance_payload("NO_SHOW"), RESERVATIONS_AGENT
            )
        ),
        status=ReservationStatus.NO_SHOW,
    )

    assert_pickup_summary(
        pickup_summary(api, world["master_block_id"]),
        picked_up_room_nights=0,
        peak_night_rooms=0,
        commitment_base_room_nights=12,
        room_nights_basis_shortfall=8,
        room_nights_basis_damages_cents=141984,
        peak_night_basis_shortfall=6,
        peak_night_basis_damages_cents=106488,
    )


def test_releasing_meeting_space_is_terminal_and_frees_the_interval(api):
    """A second release conflicts, and the vacated slot is genuinely bookable.

    PRD 3.2 makes RELEASED the end of the line: "releasing a hold that is already
    RELEASED is refused with ERR_HOLD_INVALID_STATE". It also promises the
    release is real - "releasing frees the buffered interval immediately, so a
    later hold may take the slot" - so the identical GRAND_BALLROOM window,
    which the 45-minute turnover comparison would have refused a moment earlier,
    is now accepted. PRD 2.3 orders the lead's holds by created_at ascending, so
    the released one is still first.

    Design: Corner/state_machines/function_space_release_is_terminal_and_frees_the_slot
    """
    reset_clock(api)
    account = seed_account(api)
    seed_inventory_days(api)
    lead = seed_lead(api, account["id"])
    hold = seed_function_space_hold(api, lead["id"], **_BALLROOM_DAY)

    released = validate_success(
        api.release_function_space_hold(hold["id"], SALES_MANAGER)
    )
    assert_function_space_hold(released, status=HoldStatus.RELEASED)

    validate_error(
        api.release_function_space_hold(hold["id"], SALES_MANAGER),
        ApiErrorId.HOLD_INVALID_STATE,
        409,
    )

    rebooked = seed_function_space_hold(api, lead["id"], **_BALLROOM_DAY)
    assert_function_space_hold(
        rebooked, status=HoldStatus.HELD, space_code=SpaceCode.GRAND_BALLROOM
    )

    rows, meta = validate_paginated(
        api.list_lead_function_space_holds(lead["id"], SALES_MANAGER)
    )
    assert meta["total_count"] == 2, f"the lead owns two bookings: {rows}"
    assert rows[0]["status"] == HoldStatus.RELEASED, (
        f"created_at ascending puts the released booking first: {rows}"
    )
