"""Conserved aggregates across confirm and cancel compensation (PRD §2.10, §3.7, §3.9)."""
from test_helpers import *  # noqa: F401,F403

# ─── Pinned figures (design index: Difficulty/compensating_invariant) ────────
BUDGET_TOTAL_CENTS = 5000000
AWARD_SIDE_CENTS = 1443174          # 921765 (PLATINUM winner) + 521409 (GOLD winner)
PRE_HEADROOM_CENTS = 3556826        # 5000000 - 1443174
SEAT_B_COST_CENTS = 105500          # 77000 upgrade + 28500 deviation
MID_COMMITTED_CENTS = 1548674       # 1443174 + 105500
MID_HEADROOM_CENTS = 3451326        # 5000000 - 1548674
QUALIFIER_A_COMMITTED_CENTS = 921765
QUALIFIER_B_COMMITTED_CENTS = 521409

ROOM_NIGHTS_BLOCKED = 60            # room_block_count 12 * contracted_nights 5
ATTRITION_FLOOR_ROOM_NIGHTS = 48    # ceil(60 * (10000 - 2000) / 10000)
NIGHTLY_RATE_CENTS = 38500
SEAT_A_ROOM_NIGHTS = 10             # 2 rooms * 5 nights
SEAT_B_ROOM_NIGHTS = 5              # 1 room * 5 nights

STAY_START_AT = "2026-11-08T00:00:00Z"
ARRIVAL_DATE = "2026-11-08T00:00:00Z"
DEPARTURE_DATE = "2026-11-13T00:00:00Z"

AIR_B = {
    "cabin_class": "BUSINESS",
    "deviation_pre_days": 3,
    "deviation_post_days": 2,
    "base_fare_cents": 214000,
}


def _build_registration_open_base():
    """The design index's shared setup chain, built from Tier 0 primitives.

    Program on a 5000000-cent budget, PLATINUM/GOLD ladder, Lisbon inspected and
    shortlisted at a 431757-cent per-person basis, two adjudicated winners, the
    12x5 Estoril Palace HOTEL contract EXECUTED with its three deposit
    milestones, both winners NOTIFIED and the program at REGISTRATION_OPEN.
    """
    reset_logical_clock()
    program = create_program(
        name="FY26 Presidents Circle",
        fiscal_year=2026,
        qualification_metric="NET_REVENUE_CENTS",
        sales_period_start="2026-01-01T00:00:00Z",
        sales_period_end="2026-06-30T00:00:00Z",
        budget_total_cents=BUDGET_TOTAL_CENTS,
    )
    program_id = program["id"]

    tier_platinum = create_award_tier(
        program_id,
        tier_code="PLATINUM",
        tier_rank=1,
        qualification_threshold=250000000,
        budget_per_qualifier_cents=2500000,
        guest_allowance=1,
        air_cabin_class="BUSINESS",
        upgrade_allowance_cents=150000,
        service_load_bp=1275,
    )
    tier_gold = create_award_tier(
        program_id,
        tier_code="GOLD",
        tier_rank=2,
        qualification_threshold=150000000,
        budget_per_qualifier_cents=1600000,
        guest_allowance=1,
        air_cabin_class="PREMIUM_ECONOMY",
        upgrade_allowance_cents=40000,
        service_load_bp=800,
    )

    lisbon = create_destination(
        program_id,
        city="Lisbon",
        country_code="PT",
        per_person_cost_cents=431757,
        risk_score=35,
        air_gateway_code="LIS",
    )
    create_destination(
        program_id,
        city="Seville",
        country_code="ES",
        per_person_cost_cents=388000,
        risk_score=28,
        air_gateway_code="SVQ",
    )
    inspect_destination(lisbon["id"], 82)
    shortlist_destination(lisbon["id"])

    qualifier_a = create_qualifier(
        program_id,
        employee_code="S-1001",
        full_name="Ana Reyes",
        baseline_metric=180000000,
        actual_metric=260000000,
        guest_count=1,
    )
    review_qualifier(qualifier_a["id"])
    qualifier_b = create_qualifier(
        program_id,
        employee_code="S-2001",
        full_name="Ben Ortiz",
        baseline_metric=120000000,
        actual_metric=155000000,
        guest_count=0,
    )
    review_qualifier(qualifier_b["id"])

    advance_program(program_id, "SOURCING")

    contract = create_contract(
        program_id,
        lisbon["id"],
        supplier_name="Estoril Palace",
        supplier_kind="HOTEL",
        room_block_count=12,
        contracted_nights=5,
        stay_start_at=STAY_START_AT,
        nightly_rate_cents=NIGHTLY_RATE_CENTS,
        attrition_allowance_bp=2000,
        force_majeure_clause="STANDARD",
        exposure_basis="ATTRITION_BASIS",
    )
    contract_id = contract["id"]
    create_milestone(
        contract_id, sequence=1, due_at="2026-08-15T00:00:00Z",
        amount_cents=577500, refundable_bp=10000,
    )
    create_milestone(
        contract_id, sequence=2, due_at="2026-09-15T00:00:00Z",
        amount_cents=577500, refundable_bp=5000,
    )
    create_milestone(
        contract_id, sequence=3, due_at="2026-10-15T00:00:00Z",
        amount_cents=1155000, refundable_bp=0,
    )
    propose_contract(contract_id, note="opening room block and rate")
    execute_contract(contract_id)

    notify_qualifiers(program_id)
    lock_gross_up_policy(program_id, "FULL_GROSS_UP")
    advance_program(program_id, "REGISTRATION_OPEN")

    return {
        "program_id": program_id,
        "contract_id": contract_id,
        "destination_id": lisbon["id"],
        "qualifier_a_id": qualifier_a["id"],
        "qualifier_b_id": qualifier_b["id"],
        "tier_platinum": tier_platinum,
        "tier_gold": tier_gold,
    }


def _enrol_accepted_seat(program_id, qualifier_id, rooms=1, air=None):
    """Enrol a WINNER seat over the 08-13 November window and accept it."""
    registration = create_registration(
        qualifier_id,
        program_id=program_id,
        registration_kind="WINNER",
        arrival_date=ARRIVAL_DATE,
        departure_date=DEPARTURE_DATE,
        rooms=rooms,
    )
    if air:
        air_action(registration["id"], "REQUEST", **air)
    respond_registration(registration["id"], qualifier_id, "ACCEPT")
    return read_registration(registration["id"])


def test_budget_pair_is_conserved_at_rest_before_any_confirmation():
    """The award-side rollup alone already satisfies the budget identity.

    PRD §2.10: "The program's `committed_budget_cents` plus its
    `budget_headroom_cents` always equals its `budget_total_cents`, even when the
    headroom is negative."

    Design: Difficulty/compensating_invariant/budget_committed_plus_headroom_is_conserved_across_confirm_and_cancel
    """
    base = _build_registration_open_base()

    program = read_program(base["program_id"])
    assert_program(program)
    assert program["budget_total_cents"] == BUDGET_TOTAL_CENTS
    assert program["committed_budget_cents"] == AWARD_SIDE_CENTS
    assert program["budget_headroom_cents"] == PRE_HEADROOM_CENTS
    assert program["committed_budget_cents"] + program["budget_headroom_cents"] == BUDGET_TOTAL_CENTS
    assert_budget_conserved(program)
    assert program["budget_posture"] == "OK"

    # The award side is exactly the two winners' committed costs, nothing else.
    qualifier_a = read_qualifier(base["qualifier_a_id"])
    qualifier_b = read_qualifier(base["qualifier_b_id"])
    assert qualifier_a["committed_cost_cents"] == QUALIFIER_A_COMMITTED_CENTS
    assert qualifier_b["committed_cost_cents"] == QUALIFIER_B_COMMITTED_CENTS
    assert (
        qualifier_a["committed_cost_cents"] + qualifier_b["committed_cost_cents"]
        == AWARD_SIDE_CENTS
    )


def test_budget_pair_returns_to_its_pre_state_after_confirm_then_cancel():
    """Confirming folds the seat's cost in; cancelling removes exactly it again.

    PRD §2.10: "Every compensating path in §3 — cancelling a registration,
    voiding a filed tax report, reversing a confirmation — is specified so that
    these two identities hold again once the compensation has run."

    Design: Difficulty/compensating_invariant/budget_committed_plus_headroom_is_conserved_across_confirm_and_cancel
    """
    base = _build_registration_open_base()
    seat_b = _enrol_accepted_seat(base["program_id"], base["qualifier_b_id"], rooms=1, air=AIR_B)
    assert seat_b["cost_cents"] == SEAT_B_COST_CENTS
    assert seat_b["attendance_status"] == "ACCEPTED"
    assert seat_b["air_status"] == "REQUESTED"

    # pre-state: the accepted seat's cost is not yet in the rollup.
    pre = read_program(base["program_id"])
    assert pre["committed_budget_cents"] == AWARD_SIDE_CENTS
    assert pre["budget_headroom_cents"] == PRE_HEADROOM_CENTS
    assert pre["committed_budget_cents"] + pre["budget_headroom_cents"] == BUDGET_TOTAL_CENTS
    assert pre["budget_posture"] == "OK"
    assert_budget_conserved(pre)

    confirm_registration(seat_b["id"])

    # mid-state: read back from a fresh GET of the parent row, not the response.
    mid = read_program(base["program_id"])
    assert mid["committed_budget_cents"] == MID_COMMITTED_CENTS
    assert mid["budget_headroom_cents"] == MID_HEADROOM_CENTS
    assert mid["committed_budget_cents"] + mid["budget_headroom_cents"] == BUDGET_TOTAL_CENTS
    assert mid["budget_posture"] == "OK"
    assert_budget_conserved(mid)

    cancel_registration(seat_b["id"], reason="declined after ticketing")

    # post-state: byte-for-byte the pre-state pair.
    post = read_program(base["program_id"])
    assert post["committed_budget_cents"] == AWARD_SIDE_CENTS
    assert post["budget_headroom_cents"] == PRE_HEADROOM_CENTS
    assert post["committed_budget_cents"] + post["budget_headroom_cents"] == BUDGET_TOTAL_CENTS
    assert post["budget_posture"] == "OK"
    assert_budget_conserved(post)

    cancelled = read_registration(seat_b["id"])
    assert cancelled["attendance_status"] == "CANCELLED"
    assert cancelled["air_status"] == "VOIDED"
    # The air ledger is preserved; only its participation in the rollup reversed.
    assert cancelled["cost_cents"] == SEAT_B_COST_CENTS

    qualifier_b = read_qualifier(base["qualifier_b_id"])
    assert qualifier_b["award_status"] == "NOTIFIED"
    assert qualifier_b["committed_cost_cents"] == QUALIFIER_B_COMMITTED_CENTS


def test_budget_pair_is_conserved_component_by_component_not_merely_in_sum():
    """The cancel releases the air side exactly and never touches the award side.

    PRD §3.9: "That last reversal is a **compensating** transition rather than a
    punitive one: because both `NOTIFIED` and `REGISTERED` sit inside the budget
    rollup's award-side input set, moving the qualifier back from `REGISTERED` to
    `NOTIFIED` leaves the award commitment exactly where it was and produces no
    budget drift."

    Design: Difficulty/compensating_invariant/budget_committed_plus_headroom_is_conserved_across_confirm_and_cancel
    """
    base = _build_registration_open_base()
    seat_b = _enrol_accepted_seat(base["program_id"], base["qualifier_b_id"], rooms=1, air=AIR_B)

    confirm_registration(seat_b["id"])
    mid = read_program(base["program_id"])
    # The delta is exactly the seat's cost_cents, in both components.
    assert mid["committed_budget_cents"] - AWARD_SIDE_CENTS == SEAT_B_COST_CENTS
    assert PRE_HEADROOM_CENTS - mid["budget_headroom_cents"] == SEAT_B_COST_CENTS
    # The winner is inside the award-side input set on both sides of the move.
    assert read_qualifier(base["qualifier_b_id"])["award_status"] == "REGISTERED"
    assert read_qualifier(base["qualifier_b_id"])["committed_cost_cents"] == QUALIFIER_B_COMMITTED_CENTS

    cancel_registration(seat_b["id"], reason="medical")

    post = read_program(base["program_id"])
    # An implementation that patches one component and recomputes the other can
    # still satisfy the sum, so both figures are pinned independently.
    assert post["committed_budget_cents"] == AWARD_SIDE_CENTS
    assert post["budget_headroom_cents"] == PRE_HEADROOM_CENTS
    assert MID_COMMITTED_CENTS - post["committed_budget_cents"] == SEAT_B_COST_CENTS
    assert post["budget_headroom_cents"] - MID_HEADROOM_CENTS == SEAT_B_COST_CENTS
    assert_budget_conserved(post)

    # The award side is still the untouched sum of the two winners' commitments.
    qualifier_a = read_qualifier(base["qualifier_a_id"])
    qualifier_b = read_qualifier(base["qualifier_b_id"])
    assert qualifier_a["committed_cost_cents"] == QUALIFIER_A_COMMITTED_CENTS
    assert qualifier_b["committed_cost_cents"] == QUALIFIER_B_COMMITTED_CENTS
    assert qualifier_b["award_status"] == "NOTIFIED"
    assert (
        post["committed_budget_cents"]
        == qualifier_a["committed_cost_cents"] + qualifier_b["committed_cost_cents"]
    )


def test_budget_pair_is_conserved_across_a_sequence_of_confirms_and_cancels():
    """Five reads across two confirms and two cancels; the identity holds at each.

    PRD §3.7: "`committed_budget_cents` is the award side plus the air side, and
    `budget_headroom_cents` is `budget_total_cents` less `committed_budget_cents`
    — a figure that may legitimately be negative."

    Design: Difficulty/compensating_invariant/budget_committed_plus_headroom_is_conserved_across_confirm_and_cancel
    """
    base = _build_registration_open_base()
    seat_b = _enrol_accepted_seat(base["program_id"], base["qualifier_b_id"], rooms=1, air=AIR_B)
    seat_a = _enrol_accepted_seat(base["program_id"], base["qualifier_a_id"], rooms=1)
    assert seat_a["cost_cents"] == 0
    assert seat_a["air_status"] == "NOT_REQUESTED"

    read_1 = read_program(base["program_id"])
    assert read_1["committed_budget_cents"] == AWARD_SIDE_CENTS
    assert read_1["budget_headroom_cents"] == PRE_HEADROOM_CENTS
    assert_budget_conserved(read_1)

    confirm_registration(seat_b["id"])
    read_2 = read_program(base["program_id"])
    assert read_2["committed_budget_cents"] == MID_COMMITTED_CENTS
    assert read_2["budget_headroom_cents"] == MID_HEADROOM_CENTS
    assert_budget_conserved(read_2)

    # A's seat carries no air cost, and A was already inside the award side as
    # NOTIFIED, so its confirmation moves neither component.
    confirm_registration(seat_a["id"])
    read_3 = read_program(base["program_id"])
    assert read_3["committed_budget_cents"] == MID_COMMITTED_CENTS
    assert read_3["budget_headroom_cents"] == MID_HEADROOM_CENTS
    assert_budget_conserved(read_3)
    assert read_qualifier(base["qualifier_a_id"])["award_status"] == "REGISTERED"

    # Cancelling A compensates back to NOTIFIED, which is also inside the award
    # side, so again neither component moves.
    cancel_registration(seat_a["id"], reason="medical")
    read_4 = read_program(base["program_id"])
    assert read_4["committed_budget_cents"] == MID_COMMITTED_CENTS
    assert read_4["budget_headroom_cents"] == MID_HEADROOM_CENTS
    assert_budget_conserved(read_4)
    assert read_qualifier(base["qualifier_a_id"])["award_status"] == "NOTIFIED"
    assert read_qualifier(base["qualifier_a_id"])["committed_cost_cents"] == QUALIFIER_A_COMMITTED_CENTS

    cancel_registration(seat_b["id"], reason="declined after ticketing")
    read_5 = read_program(base["program_id"])
    assert read_5["committed_budget_cents"] == AWARD_SIDE_CENTS
    assert read_5["budget_headroom_cents"] == PRE_HEADROOM_CENTS
    assert_budget_conserved(read_5)
    assert read_5["budget_posture"] == "OK"


def test_budget_pair_round_trips_on_cancel_then_reconfirm_of_a_fresh_seat():
    """Re-enrolling and reconfirming restores the aggregate to its earlier value.

    PRD §2.10: "Aggregates are **recomputed, never patched**."

    Design: Difficulty/compensating_invariant/budget_committed_plus_headroom_is_conserved_across_confirm_and_cancel
    """
    base = _build_registration_open_base()
    first_seat = _enrol_accepted_seat(base["program_id"], base["qualifier_b_id"], rooms=1, air=AIR_B)

    confirm_registration(first_seat["id"])
    assert read_program(base["program_id"])["committed_budget_cents"] == MID_COMMITTED_CENTS

    cancel_registration(first_seat["id"], reason="declined after ticketing")
    released = read_program(base["program_id"])
    assert released["committed_budget_cents"] == AWARD_SIDE_CENTS
    assert released["budget_headroom_cents"] == PRE_HEADROOM_CENTS
    assert_budget_conserved(released)

    # The cancelled WINNER seat freed the slot, so the winner is re-enrollable.
    second_seat = _enrol_accepted_seat(base["program_id"], base["qualifier_b_id"], rooms=1, air=AIR_B)
    assert second_seat["id"] != first_seat["id"]
    assert second_seat["cost_cents"] == SEAT_B_COST_CENTS

    confirm_registration(second_seat["id"])
    reconfirmed = read_program(base["program_id"])
    assert reconfirmed["committed_budget_cents"] == MID_COMMITTED_CENTS
    assert reconfirmed["budget_headroom_cents"] == MID_HEADROOM_CENTS
    assert reconfirmed["committed_budget_cents"] + reconfirmed["budget_headroom_cents"] == BUDGET_TOTAL_CENTS
    assert_budget_conserved(reconfirmed)
    assert reconfirmed["budget_posture"] == "OK"

    # The first seat's own ledger is untouched by the second seat's confirmation.
    stale = read_registration(first_seat["id"])
    assert stale["attendance_status"] == "CANCELLED"
    assert stale["cost_cents"] == SEAT_B_COST_CENTS


def test_room_night_ledger_is_conserved_on_the_empty_executed_block():
    """A freshly executed hotel contract holds its whole block as available.

    PRD §2.10: "An executed hotel contract's `room_nights_blocked` always equals
    its `room_nights_confirmed` plus its `room_nights_available`."

    Design: Difficulty/compensating_invariant/room_nights_blocked_is_conserved_as_confirmed_plus_available
    """
    base = _build_registration_open_base()
    _enrol_accepted_seat(base["program_id"], base["qualifier_a_id"], rooms=2)
    _enrol_accepted_seat(base["program_id"], base["qualifier_b_id"], rooms=1)

    contract = read_contract(base["contract_id"])
    assert_supplier_contract(contract)
    assert contract["status"] == "EXECUTED"
    assert contract["room_nights_blocked"] == ROOM_NIGHTS_BLOCKED
    assert contract["room_nights_confirmed"] == 0
    assert contract["room_nights_available"] == ROOM_NIGHTS_BLOCKED
    assert (
        contract["room_nights_confirmed"] + contract["room_nights_available"]
        == ROOM_NIGHTS_BLOCKED
    )
    assert_room_nights_conserved(contract)
    # Accepted seats contribute nothing to the ledger.
    assert contract["attrition_posture"] == "AT_RISK"


def test_room_nights_move_in_exact_opposition_across_two_confirmations():
    """Each confirmation shifts the seat's room-nights from available to confirmed.

    PRD §3.7: "Its `room_nights_available` is `room_nights_blocked` less
    `room_nights_confirmed`, and the identity of §2.10 — blocked equals confirmed
    plus available — holds after every confirmation and every cancellation."

    Design: Difficulty/compensating_invariant/room_nights_blocked_is_conserved_as_confirmed_plus_available
    """
    base = _build_registration_open_base()
    seat_a = _enrol_accepted_seat(base["program_id"], base["qualifier_a_id"], rooms=2)
    seat_b = _enrol_accepted_seat(base["program_id"], base["qualifier_b_id"], rooms=1)

    confirm_registration(seat_a["id"])
    after_a = read_contract(base["contract_id"])
    assert after_a["room_nights_blocked"] == ROOM_NIGHTS_BLOCKED
    assert after_a["room_nights_confirmed"] == SEAT_A_ROOM_NIGHTS
    assert after_a["room_nights_available"] == ROOM_NIGHTS_BLOCKED - SEAT_A_ROOM_NIGHTS
    assert after_a["room_nights_confirmed"] + after_a["room_nights_available"] == ROOM_NIGHTS_BLOCKED
    assert_room_nights_conserved(after_a)

    confirmed_a = read_registration(seat_a["id"])
    assert confirmed_a["attendance_status"] == "CONFIRMED"
    assert confirmed_a["rooms"] == 2
    assert confirmed_a["room_nights"] == SEAT_A_ROOM_NIGHTS

    confirm_registration(seat_b["id"])
    after_b = read_contract(base["contract_id"])
    assert after_b["room_nights_blocked"] == ROOM_NIGHTS_BLOCKED
    assert after_b["room_nights_confirmed"] == SEAT_A_ROOM_NIGHTS + SEAT_B_ROOM_NIGHTS
    assert after_b["room_nights_available"] == (
        ROOM_NIGHTS_BLOCKED - SEAT_A_ROOM_NIGHTS - SEAT_B_ROOM_NIGHTS
    )
    assert after_b["room_nights_confirmed"] + after_b["room_nights_available"] == ROOM_NIGHTS_BLOCKED
    assert_room_nights_conserved(after_b)
    assert read_registration(seat_b["id"])["room_nights"] == SEAT_B_ROOM_NIGHTS

    # The blocked total is never rewritten by a registration event.
    assert after_a["room_nights_blocked"] == after_b["room_nights_blocked"] == ROOM_NIGHTS_BLOCKED


def test_cancelling_a_confirmed_seat_returns_exactly_its_room_nights():
    """The released room-nights equal the seat's own stamped figure, exactly.

    PRD §3.9: "The room-night ledger is re-derived, releasing this seat's
    `room_nights` back into `room_nights_available` and refreshing
    `attrition_posture`; the budget rollup is re-derived, removing the seat's
    `cost_cents` from `committed_budget_cents`."

    Design: Difficulty/compensating_invariant/room_nights_blocked_is_conserved_as_confirmed_plus_available
    """
    base = _build_registration_open_base()
    seat_a = _enrol_accepted_seat(base["program_id"], base["qualifier_a_id"], rooms=2)
    seat_b = _enrol_accepted_seat(base["program_id"], base["qualifier_b_id"], rooms=1)
    confirm_registration(seat_a["id"])
    confirm_registration(seat_b["id"])

    before = read_contract(base["contract_id"])
    assert before["room_nights_confirmed"] == 15
    assert before["room_nights_available"] == 45

    cancel_registration(seat_a["id"], reason="medical")

    after = read_contract(base["contract_id"])
    # Both components are pinned, not just their sum: an implementation that
    # patches one and recomputes the other can satisfy the identity while drifting.
    assert after["room_nights_blocked"] == ROOM_NIGHTS_BLOCKED
    assert after["room_nights_confirmed"] == SEAT_B_ROOM_NIGHTS
    assert after["room_nights_available"] == ROOM_NIGHTS_BLOCKED - SEAT_B_ROOM_NIGHTS
    assert after["room_nights_confirmed"] + after["room_nights_available"] == ROOM_NIGHTS_BLOCKED
    assert_room_nights_conserved(after)

    # The released amount equals exactly what the confirmation consumed.
    assert before["room_nights_confirmed"] - after["room_nights_confirmed"] == SEAT_A_ROOM_NIGHTS
    assert after["room_nights_available"] - before["room_nights_available"] == SEAT_A_ROOM_NIGHTS

    cancelled = read_registration(seat_a["id"])
    assert cancelled["attendance_status"] == "CANCELLED"
    assert read_qualifier(base["qualifier_a_id"])["award_status"] == "NOTIFIED"


def test_attrition_shortfall_tracks_the_conserved_ledger_at_every_step():
    """The derived shortfall follows confirmed room-nights without drifting the sum.

    PRD §3.7: "The `shortfall_room_nights` is the floor less
    `room_nights_confirmed`, or 0 when the floor has already been met, and never
    negative."

    Design: Difficulty/compensating_invariant/room_nights_blocked_is_conserved_as_confirmed_plus_available
    """
    base = _build_registration_open_base()
    seat_a = _enrol_accepted_seat(base["program_id"], base["qualifier_a_id"], rooms=2)
    seat_b = _enrol_accepted_seat(base["program_id"], base["qualifier_b_id"], rooms=1)

    def _projection():
        projection = read_exposure_projection(base["contract_id"])
        assert projection["contract_id"] == base["contract_id"]
        assert projection["contract_value_cents"] == 2310000
        assert projection["room_nights_blocked"] == ROOM_NIGHTS_BLOCKED
        assert projection["attrition_floor_room_nights"] == ATTRITION_FLOOR_ROOM_NIGHTS
        assert projection["binding_basis"] == "ATTRITION_BASIS"
        assert projection["binding_exposure_cents"] == projection["attrition_basis_cents"]
        return projection

    at_rest = _projection()
    assert at_rest["room_nights_confirmed"] == 0
    assert at_rest["shortfall_room_nights"] == 48
    assert read_contract(base["contract_id"])["attrition_posture"] == "AT_RISK"

    confirm_registration(seat_a["id"])
    after_a = _projection()
    assert after_a["room_nights_confirmed"] == 10
    assert after_a["shortfall_room_nights"] == 38
    contract_a = read_contract(base["contract_id"])
    assert contract_a["attrition_posture"] == "AT_RISK"
    assert_room_nights_conserved(contract_a)

    confirm_registration(seat_b["id"])
    after_b = _projection()
    assert after_b["room_nights_confirmed"] == 15
    assert after_b["shortfall_room_nights"] == 33
    contract_b = read_contract(base["contract_id"])
    assert contract_b["attrition_posture"] == "AT_RISK"
    assert_room_nights_conserved(contract_b)

    cancel_registration(seat_a["id"], reason="medical")
    after_cancel = _projection()
    assert after_cancel["room_nights_confirmed"] == 5
    assert after_cancel["shortfall_room_nights"] == 43
    assert after_cancel["attrition_basis_cents"] == 43 * NIGHTLY_RATE_CENTS
    assert after_cancel["attrition_basis_cents"] == 1655500
    contract_cancel = read_contract(base["contract_id"])
    assert contract_cancel["attrition_posture"] == "AT_RISK"
    assert contract_cancel["room_nights_confirmed"] == 5
    assert contract_cancel["room_nights_available"] == 55
    assert_room_nights_conserved(contract_cancel)


def test_room_night_ledger_round_trips_on_cancel_then_reconfirm():
    """Re-enrolling the cancelled winner returns the ledger to its earlier split.

    PRD §2.10: "Every compensating path in §3 — cancelling a registration,
    voiding a filed tax report, reversing a confirmation — is specified so that
    these two identities hold again once the compensation has run."

    Design: Difficulty/compensating_invariant/room_nights_blocked_is_conserved_as_confirmed_plus_available
    """
    base = _build_registration_open_base()
    first_seat = _enrol_accepted_seat(base["program_id"], base["qualifier_a_id"], rooms=2)
    seat_b = _enrol_accepted_seat(base["program_id"], base["qualifier_b_id"], rooms=1)
    confirm_registration(first_seat["id"])
    confirm_registration(seat_b["id"])

    filled = read_contract(base["contract_id"])
    assert filled["room_nights_confirmed"] == 15
    assert filled["room_nights_available"] == 45
    assert_room_nights_conserved(filled)

    cancel_registration(first_seat["id"], reason="medical")
    released = read_contract(base["contract_id"])
    assert released["room_nights_blocked"] == ROOM_NIGHTS_BLOCKED
    assert released["room_nights_confirmed"] == 5
    assert released["room_nights_available"] == 55
    assert_room_nights_conserved(released)

    second_seat = _enrol_accepted_seat(base["program_id"], base["qualifier_a_id"], rooms=2)
    assert second_seat["id"] != first_seat["id"]
    confirm_registration(second_seat["id"])

    refilled = read_contract(base["contract_id"])
    assert refilled["room_nights_blocked"] == ROOM_NIGHTS_BLOCKED
    assert refilled["room_nights_confirmed"] == 15
    assert refilled["room_nights_available"] == 45
    assert refilled["room_nights_confirmed"] + refilled["room_nights_available"] == ROOM_NIGHTS_BLOCKED
    assert_room_nights_conserved(refilled)
    assert read_registration(second_seat["id"])["room_nights"] == SEAT_A_ROOM_NIGHTS
    # The cancelled seat stays out of the ledger's input set.
    assert read_registration(first_seat["id"])["attendance_status"] == "CANCELLED"
