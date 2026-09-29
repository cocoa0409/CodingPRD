"""Negotiation cycles, two-axis independence and transitive cascades (PRD §3.4, §3.7, §3.9)."""
from test_helpers import *  # noqa: F401,F403

# ── Reference payload fragments (the pinned figures of the design index) ──────

PLATINUM_TIER = {
    "tier_code": "PLATINUM",
    "tier_rank": 1,
    "qualification_threshold": 250_000_000,
    "budget_per_qualifier_cents": 2_500_000,
    "guest_allowance": 1,
    "air_cabin_class": "BUSINESS",
    "upgrade_allowance_cents": 150_000,
    "service_load_bp": 1275,
}

GOLD_TIER = {
    "tier_code": "GOLD",
    "tier_rank": 2,
    "qualification_threshold": 150_000_000,
    "budget_per_qualifier_cents": 1_600_000,
    "guest_allowance": 1,
    "air_cabin_class": "PREMIUM_ECONOMY",
    "upgrade_allowance_cents": 40_000,
    "service_load_bp": 800,
}

LISBON = {
    "city": "Lisbon",
    "country_code": "PT",
    "per_person_cost_cents": 431757,
    "risk_score": 35,
    "air_gateway_code": "LIS",
}

SEVILLE = {
    "city": "Seville",
    "country_code": "ES",
    "per_person_cost_cents": 388000,
    "risk_score": 28,
    "air_gateway_code": "SVQ",
}

LISBON_CONTRACT = {
    "supplier_name": "Estoril Palace",
    "supplier_kind": "HOTEL",
    "room_block_count": 12,
    "contracted_nights": 5,
    "stay_start_at": "2026-11-08T00:00:00Z",
    "nightly_rate_cents": 38500,
    "attrition_allowance_bp": 2000,
    "force_majeure_clause": "STANDARD",
    "exposure_basis": "ATTRITION_BASIS",
}

# The seat must sit inside the contract's stay window 2026-11-08 .. 2026-11-13.
STAY = {
    "arrival_date": "2026-11-08T00:00:00Z",
    "departure_date": "2026-11-13T00:00:00Z",
    "rooms": 1,
}

QUALIFIER_A = {
    "employee_code": "S-1001",
    "full_name": "Ana Reyes",
    "baseline_metric": 180_000_000,
    "actual_metric": 260_000_000,
    "guest_count": 1,
}

QUALIFIER_B = {
    "employee_code": "S-2001",
    "full_name": "Ben Ortiz",
    "baseline_metric": 120_000_000,
    "actual_metric": 155_000_000,
    "guest_count": 0,
}

QUALIFIER_C = {
    "employee_code": "S-3001",
    "full_name": "Cara Neves",
    "baseline_metric": 120_000_000,
    "actual_metric": 155_000_000,
    "guest_count": 0,
}


def _sourcing_contract():
    """SOURCING program plus a DRAFT Lisbon hotel contract at round_count 0."""
    base = setup_sourcing_program(
        program_overrides={"budget_total_cents": 5_000_000},
        destination_overrides=dict(LISBON),
    )
    base["contract"] = create_contract(
        base["program"]["id"], base["destination"]["id"], **LISBON_CONTRACT
    )
    return base


def _play_five_rounds(contract_id):
    """PROPOSE / COUNTER / PROPOSE / COUNTER / PROPOSE — the full round budget."""
    propose_contract(contract_id, "sm-01", nightly_rate_cents=41000, note="round 1 opening rate")
    counter_contract(contract_id, "ca-01", nightly_rate_cents=36000, note="round 2 buyer counter")
    propose_contract(contract_id, "sm-01", nightly_rate_cents=38500, room_block_count=12)
    counter_contract(contract_id, "ca-01", nightly_rate_cents=37000)
    return propose_contract(contract_id, "sm-01", nightly_rate_cents=38500)


def test_negotiation_cycle_reenters_proposed_across_rounds_three_four_and_five():
    """Rounds 3, 4 and 5 keep looping COUNTERED -> PROPOSED -> COUNTERED -> PROPOSED.

    PRD §3.4: "A `SourcingManager` proposing moves the contract `DRAFT → PROPOSED`
    or, closing the loop, `COUNTERED → PROPOSED`; a `ContractApprover` countering
    moves it `PROPOSED → COUNTERED`."

    Design: Difficulty/non_linear_state_machine/supplier_contract_propose_counter_negotiation_cycle_terminates_at_five_rounds
    """
    base = _sourcing_contract()
    contract_id = base["contract"]["id"]
    assert base["contract"]["status"] == "DRAFT"
    assert base["contract"]["round_count"] == 0
    assert_version_is(base["contract"], 1, "SupplierContract at creation")

    round_1 = propose_contract(
        contract_id, "sm-01", nightly_rate_cents=41000, note="round 1 opening rate"
    )
    assert round_1["status"] == "PROPOSED"
    assert round_1["round_count"] == 1

    round_2 = counter_contract(
        contract_id, "ca-01", nightly_rate_cents=36000, note="round 2 buyer counter"
    )
    assert round_2["status"] == "COUNTERED"
    assert round_2["round_count"] == 2

    round_3 = propose_contract(
        contract_id, "sm-01", nightly_rate_cents=38500, room_block_count=12
    )
    assert round_3["status"] == "PROPOSED"
    assert round_3["round_count"] == 3
    assert round_3["nightly_rate_cents"] == 38500
    assert round_3["room_block_count"] == 12

    round_4 = counter_contract(contract_id, "ca-01", nightly_rate_cents=37000)
    assert round_4["status"] == "COUNTERED"
    assert round_4["round_count"] == 4
    assert round_4["nightly_rate_cents"] == 37000

    round_5 = propose_contract(contract_id, "sm-01", nightly_rate_cents=38500)
    assert round_5["status"] == "PROPOSED"
    assert round_5["round_count"] == 5
    assert round_5["nightly_rate_cents"] == 38500
    assert_supplier_contract(round_5)

    # The same state was re-entered three times; the stamps and the recomputed
    # stay window survive every loop (PRD §3.4).
    assert round_5["last_proposed_by_user_id"] == "sm-01"
    assert round_5["last_countered_by_user_id"] == "ca-01"
    assert_instant_equals(round_5["stay_end_at"], "2026-11-13T00:00:00Z", "stay_end_at")
    assert_version_is(round_5, 6, "SupplierContract after five rounds")


def test_sixth_negotiation_round_is_rejected_and_leaves_round_count_at_five():
    """The loop terminates on the counter, not on the edge set: round 6 is refused.

    PRD §3.4: "Five rounds is the ceiling: a proposing or countering round
    attempted while `round_count` has already reached 5 is rejected with
    `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`, so a contract can traverse `PROPOSED →
    COUNTERED → PROPOSED` at most until the budget is spent, and a deadlocked
    negotiation must be withdrawn rather than looped forever."

    Design: Difficulty/non_linear_state_machine/supplier_contract_propose_counter_negotiation_cycle_terminates_at_five_rounds
    """
    base = _sourcing_contract()
    contract_id = base["contract"]["id"]
    fifth = _play_five_rounds(contract_id)
    assert fifth["status"] == "PROPOSED"
    assert fifth["round_count"] == 5

    # COUNTERED -> PROPOSED is a declared edge and ca-01 is a permitted
    # counterer, so only the round budget can stop this call.
    response = api_client.negotiate_contract(
        contract_id, negotiate_payload("COUNTER"), make_contract_approver_headers("ca-01")
    )
    validate_error(response, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED)

    after = read_contract(contract_id)
    assert after["status"] == "PROPOSED"
    assert after["round_count"] == 5
    assert_version_is(after, 6, "SupplierContract after the refused round")
    assert after["last_proposed_by_user_id"] == "sm-01"
    assert after["last_countered_by_user_id"] == "ca-01"
    assert after["nightly_rate_cents"] == 38500


def test_round_count_advances_on_counter_rounds_as_well_as_propose_rounds():
    """A COUNTER consumes the round budget exactly like a PROPOSE does.

    PRD §3.4: "Every accepted round increments `round_count` by 1 and the
    contract's `version` by 1."

    Design: Difficulty/non_linear_state_machine/supplier_contract_propose_counter_negotiation_cycle_terminates_at_five_rounds
    """
    base = _sourcing_contract()
    contract_id = base["contract"]["id"]

    first = propose_contract(contract_id, "sm-01", nightly_rate_cents=41000)
    assert first["round_count"] == 1
    # A counter is a round in its own right — counting only proposals would
    # leave this at 1 and buy the negotiation extra loops.
    second = counter_contract(contract_id, "ca-01", nightly_rate_cents=40000)
    assert second["round_count"] == 2
    third = propose_contract(contract_id, "sm-01", nightly_rate_cents=39500)
    assert third["round_count"] == 3
    fourth = counter_contract(contract_id, "ca-01", nightly_rate_cents=39000)
    assert fourth["round_count"] == 4
    assert_version_is(fourth, 5, "SupplierContract after four rounds")

    # round_count 4 is strictly less than 5, so the fifth round is still bought.
    fifth = propose_contract(contract_id, "sm-01", nightly_rate_cents=38500)
    assert fifth["round_count"] == 5
    assert fifth["status"] == "PROPOSED"

    exhausted = api_client.negotiate_contract(
        contract_id, negotiate_payload("COUNTER", nightly_rate_cents=38000),
        make_contract_approver_headers("ca-01"),
    )
    validate_error(exhausted, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED)
    assert read_contract(contract_id)["nightly_rate_cents"] == 38500


# ── Registration's two independent state dimensions (PRD §3.6, §3.7) ──────────

def _registration_open_base():
    """REGISTRATION_OPEN program: Lisbon EXECUTED, winners A (PLATINUM) and B
    (GOLD) NOTIFIED, so committed_budget_cents is 921765 + 521409 = 1443174."""
    return setup_registration_open_program(
        qualifier_specs=[dict(QUALIFIER_A), dict(QUALIFIER_B)],
        gross_up_policy="FULL_GROSS_UP",
        program_overrides={"budget_total_cents": 5_000_000},
        tier_specs=[dict(PLATINUM_TIER), dict(GOLD_TIER)],
        destination_overrides=dict(LISBON),
        contract_overrides=dict(LISBON_CONTRACT),
    )


def _seat_with_air_requested(base):
    """A WINNER seat at (attendance INVITED, air REQUESTED) in BUSINESS."""
    registration = create_registration(
        base["qualifier"]["id"], program_id=base["program"]["id"], **STAY
    )
    air_action(
        registration["id"], "REQUEST",
        cabin_class="BUSINESS", deviation_pre_days=0, deviation_post_days=0,
        base_fare_cents=214000,
    )
    return read_registration(registration["id"])


def test_attendance_and_air_axes_each_advance_without_moving_the_other():
    """Respond, ticket, confirm, change and re-ticket each move exactly one axis.

    PRD §3.7: "**Air travel management** is a `TravelDesk` operation carrying an
    `action` of `REQUEST`, `TICKET` or `CHANGE`, and it drives the seat's second,
    fully independent state dimension: `air_status` runs `NOT_REQUESTED`,
    `REQUESTED`, `TICKETED`, `CHANGE_PENDING` and `VOIDED`, with only `VOIDED`
    terminal."

    Design: Difficulty/non_linear_state_machine/registration_attendance_and_air_dimensions_advance_independently
    """
    base = _registration_open_base()
    qualifier = base["qualifier"]
    seat = _seat_with_air_requested(base)
    assert seat["attendance_status"] == "INVITED"
    assert seat["air_status"] == "REQUESTED"

    after_respond = respond_registration(seat["id"], qualifier["id"], "ACCEPT")
    assert after_respond["attendance_status"] == "ACCEPTED"
    assert after_respond["air_status"] == "REQUESTED"

    after_ticket = air_action(seat["id"], "TICKET")
    assert after_ticket["air_status"] == "TICKETED"
    assert after_ticket["attendance_status"] == "ACCEPTED"
    assert after_ticket["air_change_count"] == 0

    after_confirm = confirm_registration(seat["id"])
    assert after_confirm["attendance_status"] == "CONFIRMED"
    assert after_confirm["air_status"] == "TICKETED"

    after_change = air_action(seat["id"], "CHANGE")
    assert after_change["air_status"] == "CHANGE_PENDING"
    assert after_change["attendance_status"] == "CONFIRMED"
    assert after_change["air_change_count"] == 0

    reticketed = air_action(seat["id"], "TICKET")
    assert reticketed["attendance_status"] == "CONFIRMED"
    assert reticketed["air_status"] == "TICKETED"
    assert reticketed["air_change_count"] == 1
    assert_registration(reticketed)

    # PLATINUM already grants BUSINESS: max(0, 165000 - 165000) == 0.
    assert reticketed["air_upgrade_cost_cents"] == 0
    assert reticketed["air_deviation_fee_cents"] == 0
    assert reticketed["air_change_fee_total_cents"] == 12500
    assert reticketed["cost_cents"] == 12500

    # The re-ticketing is folded into the rollup only because the attendance
    # axis is CONFIRMED (PRD §3.7). Aggregates are re-read from the parent row.
    program = read_program(base["program"]["id"])
    assert program["committed_budget_cents"] == 1455674
    assert program["budget_headroom_cents"] == 3544326
    assert_budget_conserved(program)


def test_accepting_and_confirming_a_seat_leaves_every_air_field_untouched():
    """The attendance axis advances twice while the ticketed air record stands.

    PRD §3.7: "Ticketing moves it `REQUESTED → TICKETED` on first issue and
    `CHANGE_PENDING → TICKETED` on re-issue."

    Design: Difficulty/non_linear_state_machine/registration_attendance_and_air_dimensions_advance_independently
    """
    base = _registration_open_base()
    qualifier = base["qualifier"]
    seat = _seat_with_air_requested(base)

    accepted = respond_registration(seat["id"], qualifier["id"], "ACCEPT", waiver_signed=True)
    assert accepted["attendance_status"] == "ACCEPTED"
    assert accepted["air_status"] == "REQUESTED"

    ticketed = air_action(seat["id"], "TICKET")
    assert ticketed["attendance_status"] == "ACCEPTED"
    assert ticketed["air_status"] == "TICKETED"
    assert ticketed["air_cabin_class"] == "BUSINESS"
    assert ticketed["air_base_fare_cents"] == 214000
    assert ticketed["air_change_count"] == 0

    confirmed = confirm_registration(seat["id"])
    assert confirmed["attendance_status"] == "CONFIRMED"
    # The confirmation stamps the attendance side only; the air record is not
    # re-opened, reset or re-priced by it.
    assert confirmed["air_status"] == "TICKETED"
    assert confirmed["air_cabin_class"] == "BUSINESS"
    assert confirmed["air_base_fare_cents"] == 214000
    assert confirmed["air_deviation_pre_days"] == 0
    assert confirmed["air_deviation_post_days"] == 0
    assert confirmed["air_change_count"] == 0
    assert confirmed["air_change_fee_total_cents"] == 0
    assert confirmed["room_nights"] == 5
    assert confirmed["cost_cents"] == 0

    program = read_program(base["program"]["id"])
    assert program["committed_budget_cents"] == 1443174
    assert_budget_conserved(program)


def test_air_request_is_accepted_while_attendance_is_still_invited():
    """The air axis leaves NOT_REQUESTED without the attendance axis moving.

    PRD §3.7: "Requesting moves the seat `NOT_REQUESTED → REQUESTED` and is
    deliberately allowed while attendance is still `INVITED`, `ACCEPTED` or
    `CONFIRMED`, because the travel desk collects air preferences with the
    invitation rather than after the answer."

    Design: Difficulty/non_linear_state_machine/registration_attendance_and_air_dimensions_advance_independently
    """
    base = _registration_open_base()
    fresh = create_registration(
        base["qualifier"]["id"], program_id=base["program"]["id"], **STAY
    )
    assert fresh["attendance_status"] == "INVITED"
    assert fresh["air_status"] == "NOT_REQUESTED"

    requested = air_action(
        fresh["id"], "REQUEST",
        cabin_class="BUSINESS", deviation_pre_days=0, deviation_post_days=0,
        base_fare_cents=214000,
    )
    assert requested["air_status"] == "REQUESTED"
    assert requested["attendance_status"] == "INVITED"
    assert requested["air_cabin_class"] == "BUSINESS"
    assert requested["air_base_fare_cents"] == 214000
    assert requested["air_change_count"] == 0
    assert_version_is(requested, 2, "Registration after one air action")

    # An INVITED seat sits outside the budget rollup's air side, so opening the
    # air record moves no money (PRD §3.7).
    program = read_program(base["program"]["id"])
    assert program["committed_budget_cents"] == 1443174
    assert program["budget_headroom_cents"] == 3556826
    assert_budget_conserved(program)


# ── The five-level contract-execution cascade (PRD §3.4) ──────────────────────

def _five_level_cascade_setup(budget_total_cents=1_400_000, supplier_kind="HOTEL"):
    """A PROPOSED contract whose execution has five levels of work waiting.

    Lisbon is SHORTLISTED and Seville is left CANDIDATE; both winners are
    adjudicated while `per_person_cost_basis_cents` is still 0, so their
    committed costs are 150000 and 40000 and the posture is OK; the deposit
    schedule sums to exactly the 2310000 contract value.
    """
    program = create_program(budget_total_cents=budget_total_cents)
    create_award_tier(program["id"], **PLATINUM_TIER)
    create_award_tier(program["id"], **GOLD_TIER)
    lisbon = create_destination(program["id"], **LISBON)
    seville = create_destination(program["id"], **SEVILLE)
    inspect_destination(lisbon["id"], 82)
    shortlist_destination(lisbon["id"])

    qualifier_a = create_qualifier(program["id"], **QUALIFIER_A)
    review_qualifier(qualifier_a["id"])
    qualifier_b = create_qualifier(program["id"], **QUALIFIER_B)
    review_qualifier(qualifier_b["id"])

    advance_program(program["id"], "SOURCING")
    terms = dict(LISBON_CONTRACT)
    terms["supplier_kind"] = supplier_kind
    contract = create_contract(program["id"], lisbon["id"], **terms)
    milestones = [
        create_milestone(
            contract["id"], sequence=1, due_at="2026-08-15T00:00:00Z",
            amount_cents=577500, refundable_bp=10000,
        ),
        create_milestone(
            contract["id"], sequence=2, due_at="2026-09-15T00:00:00Z",
            amount_cents=577500, refundable_bp=5000,
        ),
        create_milestone(
            contract["id"], sequence=3, due_at="2026-10-15T00:00:00Z",
            amount_cents=1155000, refundable_bp=0,
        ),
    ]
    propose_contract(contract["id"], "sm-01", note="opening room block and rate")
    return {
        "program": read_program(program["id"]),
        "lisbon": lisbon,
        "seville": seville,
        "qualifier_a": qualifier_a,
        "qualifier_b": qualifier_b,
        "contract": read_contract(contract["id"]),
        "milestones": milestones,
    }


def test_contract_execution_cascades_five_levels_into_deposit_finance_review():
    """One execute call walks contract, destinations, program, qualifiers, deposits.

    PRD §3.4: "An accepted execution runs a cascade five levels deep, in this
    fixed order:"

    Design: Difficulty/transitive_cascade/contract_execution_cascades_five_levels_into_deposit_finance_review
    """
    base = _five_level_cascade_setup()
    assert base["program"]["per_person_cost_basis_cents"] == 0
    assert base["program"]["budget_posture"] == "OK"
    assert read_qualifier(base["qualifier_a"]["id"])["committed_cost_cents"] == 150000
    assert read_qualifier(base["qualifier_b"]["id"])["committed_cost_cents"] == 40000

    # sm-01 proposed, so ca-01 may execute (PRD §2.9 compares identities).
    execute_contract(base["contract"]["id"], "ca-01")

    # level 1 — the contract itself.
    contract = read_contract(base["contract"]["id"])
    assert contract["status"] == "EXECUTED"
    assert contract["executed_by_user_id"] == "ca-01"
    assert_instant_equals(contract["executed_at"], "2026-08-01T00:00:00Z", "executed_at")
    assert contract["room_nights_blocked"] == 60
    assert contract["room_nights_confirmed"] == 0
    assert contract["room_nights_available"] == 60
    assert contract["attrition_posture"] == "AT_RISK"
    assert_room_nights_conserved(contract)

    # level 2 — the selected destination and the losing sibling.
    assert read_destination(base["lisbon"]["id"])["status"] == "SELECTED"
    assert read_destination(base["seville"]["id"])["status"] == "REJECTED"

    # level 3 — the program, whose cost basis is read from level 2's selection.
    program = read_program(base["program"]["id"])
    assert program["status"] == "CONTRACTED"
    assert program["per_person_cost_basis_cents"] == 431757

    # level 4 — both committed costs recomputed against the now-known basis.
    assert read_qualifier(base["qualifier_a"]["id"])["committed_cost_cents"] == 921765
    assert read_qualifier(base["qualifier_b"]["id"])["committed_cost_cents"] == 521409
    assert program["committed_budget_cents"] == 1443174
    assert program["budget_headroom_cents"] == -43174
    assert program["budget_posture"] == "OVERCOMMITTED"
    assert_budget_conserved(program)
    assert program["cancellation_exposure_cents"] == 1848000

    # level 5 — reachable only because level 4 landed on OVERCOMMITTED.
    for milestone in base["milestones"]:
        row = read_milestone(milestone["id"])
        assert row["requires_finance_review"] is True
        assert row["status"] == "SCHEDULED"
        assert_version_is(row, 2, "DepositMilestone after the cascade")


def test_level_five_does_not_fire_when_the_rollup_leaves_the_posture_ok():
    """Levels 1 to 4 fire, but a healthy posture leaves the deposit schedule alone.

    PRD §3.4: "If the rollup at level 4 left `budget_posture` at
    `OVERCOMMITTED`, every deposit milestone of *this* contract whose `status` is
    `SCHEDULED` has `requires_finance_review` set to true, each with a `version`
    increment. If the posture is `OK` or `WATCH`, no milestone is touched."

    Design: Difficulty/transitive_cascade/contract_execution_cascades_five_levels_into_deposit_finance_review
    """
    base = _five_level_cascade_setup(budget_total_cents=5_000_000)
    execute_contract(base["contract"]["id"], "ca-01")

    # The first four levels are unchanged by the wider budget.
    assert read_contract(base["contract"]["id"])["status"] == "EXECUTED"
    assert read_destination(base["lisbon"]["id"])["status"] == "SELECTED"
    assert read_destination(base["seville"]["id"])["status"] == "REJECTED"
    program = read_program(base["program"]["id"])
    assert program["status"] == "CONTRACTED"
    assert program["per_person_cost_basis_cents"] == 431757
    assert program["committed_budget_cents"] == 1443174
    assert program["budget_headroom_cents"] == 3556826
    assert program["budget_posture"] == "OK"
    assert_budget_conserved(program)

    # Level 5 found no work to do, so the milestones were never mutated at all.
    for milestone in base["milestones"]:
        row = read_milestone(milestone["id"])
        assert row["requires_finance_review"] is False
        assert row["status"] == "SCHEDULED"
        assert_version_is(row, 1, "DepositMilestone untouched by the cascade")


def test_executing_a_dmc_contract_stops_the_cascade_after_level_one():
    """A non-hotel execution never reaches the destination, program or qualifiers.

    PRD §3.4: "Only `HOTEL` contracts drive destination selection and program
    advancement; `DMC` and `AIR_CONSOLIDATOR` contracts negotiate and execute on
    exactly the same machine but trigger neither."

    Design: Difficulty/transitive_cascade/contract_execution_cascades_five_levels_into_deposit_finance_review
    """
    base = _five_level_cascade_setup(supplier_kind="DMC")
    execute_contract(base["contract"]["id"], "ca-01")

    # level 1 still runs in full.
    contract = read_contract(base["contract"]["id"])
    assert contract["status"] == "EXECUTED"
    assert contract["supplier_kind"] == "DMC"
    assert contract["executed_by_user_id"] == "ca-01"
    assert contract["room_nights_blocked"] == 60
    assert_room_nights_conserved(contract)

    # levels 2, 3, 4 and 5 are all hotel-driven, so none of them fired.
    assert read_destination(base["lisbon"]["id"])["status"] == "SHORTLISTED"
    assert read_destination(base["seville"]["id"])["status"] == "CANDIDATE"
    program = read_program(base["program"]["id"])
    assert program["status"] == "SOURCING"
    assert program["per_person_cost_basis_cents"] == 0
    assert read_qualifier(base["qualifier_a"]["id"])["committed_cost_cents"] == 150000
    assert read_qualifier(base["qualifier_b"]["id"])["committed_cost_cents"] == 40000
    assert program["committed_budget_cents"] == 190000
    assert program["budget_posture"] == "OK"
    assert_budget_conserved(program)
    for milestone in base["milestones"]:
        assert read_milestone(milestone["id"])["requires_finance_review"] is False


# ── The registration-cancellation cascade (PRD §3.8, §3.9) ────────────────────

def _onsite_with_waitlist(qualifier_specs, capacity=1):
    """ONSITE program whose winners are CONFIRMED for 5 room-nights each, with
    one capacity-`capacity` activity signed up in qualifier order."""
    base = setup_onsite_program(
        qualifier_specs=[dict(spec) for spec in qualifier_specs],
        registration_overrides=dict(STAY),
        gross_up_policy="FULL_GROSS_UP",
        program_overrides={"budget_total_cents": 5_000_000},
        tier_specs=[dict(PLATINUM_TIER), dict(GOLD_TIER)],
        destination_overrides=dict(LISBON),
        contract_overrides=dict(LISBON_CONTRACT),
    )
    activity = create_activity(
        base["program"]["id"], name="Sintra palace tour",
        start_at="2026-11-10T10:00:00Z", end_at="2026-11-10T13:00:00Z",
        capacity=capacity, risk_level="LOW",
    )
    base["signups"] = [
        create_signup(activity["id"], registration["id"])
        for registration in base["registrations"]
    ]
    base["activity"] = read_activity(activity["id"])
    return base


def test_registration_cancel_cascades_three_levels_into_waitlist_promotion():
    """Cancelling a confirmed seat releases its slot and promotes the waitlist.

    PRD §3.9: "Every activity signup of this seat whose `status` is `BOOKED` or
    `WAITLISTED` moves to `CANCELLED`, and for each activity that thereby lost a
    `BOOKED` signup, one waitlist promotion runs exactly as described in §3.8,
    stamping the winner's `promoted_at`."

    Design: Difficulty/transitive_cascade/registration_cancel_cascades_three_levels_into_waitlist_promotion
    """
    base = _onsite_with_waitlist([QUALIFIER_A, QUALIFIER_B])
    seat_a, seat_b = base["registrations"]
    signup_a, signup_b = base["signups"]
    assert signup_a["status"] == "BOOKED"
    assert signup_b["status"] == "WAITLISTED"
    assert_signup_counters(base["activity"], 1, 1)

    cancel_registration(seat_a["id"], reason="family emergency")

    # level 1 — the seat itself.
    cancelled = read_registration(seat_a["id"])
    assert cancelled["attendance_status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "family emergency"
    assert cancelled["air_status"] == "NOT_REQUESTED"

    # level 2 — its booked signup, released by level 1 and not by a direct call.
    assert read_signup(signup_a["id"])["status"] == "CANCELLED"

    # level 3 — the promotion that only exists because level 2 freed a seat.
    promoted = read_signup(signup_b["id"])
    assert promoted["status"] == "BOOKED"
    assert_instant_equals(promoted["promoted_at"], "2026-08-01T00:00:00Z", "promoted_at")

    activity = read_activity(base["activity"]["id"])
    assert_signup_counters(activity, 1, 0)

    # The winner rolls back to NOTIFIED; the untouched winner stays REGISTERED.
    assert read_qualifier(base["qualifiers"][0]["id"])["award_status"] == "NOTIFIED"
    assert read_qualifier(base["qualifiers"][1]["id"])["award_status"] == "REGISTERED"
    assert read_registration(seat_b["id"])["attendance_status"] == "CONFIRMED"

    # Both conserved identities hold again once the reversal has run (PRD §2.10).
    contract = read_contract(base["contract"]["id"])
    assert contract["room_nights_confirmed"] == 5
    assert contract["room_nights_available"] == 55
    assert_room_nights_conserved(contract)
    program = read_program(base["program"]["id"])
    assert program["committed_budget_cents"] == 1443174
    assert_budget_conserved(program)


def test_only_the_earliest_waitlisted_signup_is_promoted_by_one_released_seat():
    """One released booked seat promotes exactly one waitlisted signup, the earliest.

    PRD §3.8: "**Waitlist promotion** runs exactly once per released booked seat,
    and only while the parent activity is `OPEN`."

    Design: Difficulty/transitive_cascade/registration_cancel_cascades_three_levels_into_waitlist_promotion
    """
    base = _onsite_with_waitlist([QUALIFIER_A, QUALIFIER_B, QUALIFIER_C])
    seat_a = base["registrations"][0]
    signup_a, signup_b, signup_c = base["signups"]
    assert signup_a["status"] == "BOOKED"
    assert signup_b["status"] == "WAITLISTED"
    assert signup_c["status"] == "WAITLISTED"
    assert_signup_counters(base["activity"], 1, 2)

    cancel_registration(seat_a["id"], reason="family emergency")

    assert read_signup(signup_a["id"])["status"] == "CANCELLED"
    # B was created first, so B wins; the cascade does not drain the whole queue.
    assert read_signup(signup_b["id"])["status"] == "BOOKED"
    assert read_signup(signup_c["id"])["status"] == "WAITLISTED"
    assert_signup_counters(read_activity(base["activity"]["id"]), 1, 1)


def test_waitlist_promotion_stamps_promoted_at_from_the_logical_clock():
    """The promotion inside the cancel cascade reads the logical clock, not wall time.

    PRD §2.5: "The fields written from the logical clock are `notified_at` on a
    `Qualifier`, `inspected_at` on a `Destination`, `executed_at` on a
    `SupplierContract`, `paid_at` on a `DepositMilestone`, `promoted_at` on an
    `ActivitySignup`, and `filed_at` on a `TaxAwardReport`."

    Design: Difficulty/transitive_cascade/registration_cancel_cascades_three_levels_into_waitlist_promotion
    """
    base = _onsite_with_waitlist([QUALIFIER_A, QUALIFIER_B])
    seat_a = base["registrations"][0]
    signup_a, signup_b = base["signups"]

    set_logical_clock("2026-11-09T08:30:00Z")
    cancel_registration(seat_a["id"], reason="family emergency")

    assert read_signup(signup_a["id"])["status"] == "CANCELLED"
    promoted = read_signup(signup_b["id"])
    assert promoted["status"] == "BOOKED"
    assert_instant_equals(promoted["promoted_at"], "2026-11-09T08:30:00Z", "promoted_at")
