"""Cross-entity state gates and temporal interval overlap (PRD §3.5, §3.7, §3.8, §3.9)."""
from test_helpers import *  # noqa: F401,F403

_CA = TEST_USERS["contract_approver_headers"]
_TD = TEST_USERS["travel_desk_headers"]
_TAX = TEST_USERS["tax_officer_headers"]

# ─── Shared payload shapes (copied from the design index's setup_api_calls) ───

_LISBON = {"per_person_cost_cents": 431757, "risk_score": 35}
_CONTRACT_5N = {"contracted_nights": 5, "stay_start_at": "2026-11-08T00:00:00Z"}
_STAY_FULL_WINDOW = {
    "arrival_date": "2026-11-08T00:00:00Z",
    "departure_date": "2026-11-13T00:00:00Z",
    "rooms": 1,
}
_GOLD_TIER = {
    "tier_code": "GOLD",
    "tier_rank": 1,
    "qualification_threshold": 150000000,
    "budget_per_qualifier_cents": 1600000,
    "guest_allowance": 1,
    "air_cabin_class": "PREMIUM_ECONOMY",
    "upgrade_allowance_cents": 40000,
    "service_load_bp": 800,
}
_QUALIFIER_B = {
    "employee_code": "S-2001",
    "full_name": "Ben Ortiz",
    "baseline_metric": 120000000,
    "actual_metric": 155000000,
    "guest_count": 0,
}
_MILESTONE_SCHEDULE = [
    {"sequence": 1, "due_at": "2026-08-15T00:00:00Z", "amount_cents": 577500,
     "refundable_bp": 10000},
    {"sequence": 2, "due_at": "2026-09-15T00:00:00Z", "amount_cents": 577500,
     "refundable_bp": 5000},
    {"sequence": 3, "due_at": "2026-10-15T00:00:00Z", "amount_cents": 1155000,
     "refundable_bp": 0},
]


def _proposed_contract_with_schedule():
    """SOURCING program, HOTEL contract PROPOSED (12 rooms x 5 nights x 38500 =
    2310000) carrying three SCHEDULED milestones summing to exactly that value."""
    return setup_contract_with_schedule(
        _MILESTONE_SCHEDULE,
        contract_overrides=dict(_CONTRACT_5N),
        destination_overrides=dict(_LISBON),
        execute=False,
    )


def test_deposit_milestone_pay_is_gated_on_the_parent_contract_being_executed():
    """Paying a SCHEDULED milestone is refused while its parent contract is only
    PROPOSED, and the identical call succeeds once the parent is EXECUTED.

    PRD §3.5: "This is a guarded cross-entity transition — the parent contract
    must be `EXECUTED`, and paying a milestone that hangs off a `DRAFT`,
    `PROPOSED` or `COUNTERED` contract reports `ERR_CONTRACT_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/deposit_milestone_payment_gated_on_parent_contract_executed
    """
    base = _proposed_contract_with_schedule()
    contract_id = base["contract"]["id"]
    m1, m2, m3 = base["milestones"]
    assert base["contract"]["status"] == "PROPOSED"
    assert m1["status"] == "SCHEDULED"

    blocked = api_client.pay_deposit_milestone(m1["id"], _CA)
    validate_error(blocked, ApiErrorId.ERR_CONTRACT_STATE_INVALID, 409)

    execute_contract(contract_id)
    assert read_contract(contract_id)["status"] == "EXECUTED"
    assert read_program(base["program"]["id"])["status"] == "CONTRACTED"

    paid = validate_success(api_client.pay_deposit_milestone(m1["id"], _CA), 200)
    assert_deposit_milestone(paid)
    assert paid["status"] == "PAID"
    assert_instant_equals(paid["paid_at"], "2026-08-01T00:00:00Z", "DepositMilestone.paid_at")
    assert read_milestone(m2["id"])["status"] == "SCHEDULED"
    assert read_milestone(m3["id"])["status"] == "SCHEDULED"


def test_gated_pay_refusal_leaves_the_milestone_and_the_exposure_untouched():
    """The refused payment is a no-op on the milestone, and the binding attrition
    exposure the successful payment re-runs ignores the deposit schedule entirely.

    PRD §2.8: "a deposit milestone may only be paid when its supplier contract is
    `EXECUTED` (`ERR_CONTRACT_STATE_INVALID`)"

    Design: Difficulty/cross_entity_state_dependency/deposit_milestone_payment_gated_on_parent_contract_executed
    """
    base = _proposed_contract_with_schedule()
    program_id = base["program"]["id"]
    contract_id = base["contract"]["id"]
    m1 = base["milestones"][0]
    version_before = m1["version"]

    validate_error(
        api_client.pay_deposit_milestone(m1["id"], _CA),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID,
        409,
    )

    after_refusal = read_milestone(m1["id"])
    assert after_refusal["status"] == "SCHEDULED"
    assert after_refusal["paid_at"] is None
    assert_version_is(after_refusal, version_before, "DepositMilestone")

    execute_contract(contract_id)
    # 48 unfilled room-nights * 38500 under the binding ATTRITION_BASIS.
    assert read_program(program_id)["cancellation_exposure_cents"] == 1848000

    pay_milestone(m1["id"])
    program = read_program(program_id)
    assert program["cancellation_exposure_cents"] == 1848000
    assert program["budget_posture"] == "OK"
    for milestone in base["milestones"]:
        assert read_milestone(milestone["id"])["requires_finance_review"] is False


def test_deposit_milestone_pay_refused_on_draft_and_countered_parent_contracts():
    """The gate reads the parent's status, so DRAFT and COUNTERED parents refuse
    payment with the same contract-state error a PROPOSED parent does.

    PRD §3.5: "This is a guarded cross-entity transition — the parent contract
    must be `EXECUTED`, and paying a milestone that hangs off a `DRAFT`,
    `PROPOSED` or `COUNTERED` contract reports `ERR_CONTRACT_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/deposit_milestone_payment_gated_on_parent_contract_executed
    """
    base = setup_sourcing_program(destination_overrides=dict(_LISBON))
    contract = create_contract(base["program"]["id"], base["destination"]["id"])
    assert contract["status"] == "DRAFT"
    milestone = create_milestone(contract["id"], sequence=1, amount_cents=577500)

    validate_error(
        api_client.pay_deposit_milestone(milestone["id"], _CA),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID,
        409,
    )
    assert read_milestone(milestone["id"])["status"] == "SCHEDULED"

    propose_contract(contract["id"])
    counter_contract(contract["id"])
    assert read_contract(contract["id"])["status"] == "COUNTERED"

    validate_error(
        api_client.pay_deposit_milestone(milestone["id"], _CA),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID,
        409,
    )
    still_scheduled = read_milestone(milestone["id"])
    assert still_scheduled["status"] == "SCHEDULED"
    assert still_scheduled["paid_at"] is None


# ─── cross_entity_state_dependency / tax report draft gate ───────────────────

def _registered_winner_program(gross_up_policy="FULL_GROSS_UP"):
    """REGISTRATION_OPEN program whose only winner's seat is CONFIRMED, so the
    qualifier's award_status is REGISTERED and its tax_status NOT_APPLICABLE."""
    return setup_confirmed_registration(
        waiver_signed=True,
        registration_overrides=dict(_STAY_FULL_WINDOW),
        gross_up_policy=gross_up_policy,
        qualifier_overrides=dict(_QUALIFIER_B),
        program_overrides={"budget_total_cents": 5000000},
        tier_overrides=dict(_GOLD_TIER),
        destination_overrides=dict(_LISBON),
        contract_overrides=dict(_CONTRACT_5N),
    )


def test_tax_report_draft_is_gated_on_the_qualifier_having_travelled():
    """A draft is refused while the qualifier is only REGISTERED and succeeds
    once the reconciliation advance moves that same qualifier to TRAVELLED.

    PRD §3.9: "the referenced qualifier's `award_status` must be `TRAVELLED`, and
    drafting against a qualifier who has not travelled reports
    `ERR_QUALIFIER_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/tax_report_draft_gated_on_qualifier_award_status_travelled
    """
    base = _registered_winner_program()
    program_id = base["program"]["id"]
    qualifier_id = base["qualifier"]["id"]
    assert read_qualifier(qualifier_id)["award_status"] == "REGISTERED"

    blocked = api_client.create_tax_award_report(
        create_tax_award_report_payload(qualifier_id, 2026), _TAX
    )
    validate_error(blocked, ApiErrorId.ERR_QUALIFIER_STATE_INVALID, 409)

    advance_program(program_id, "ONSITE")
    advance_program(program_id, "RECONCILED")

    qualifier = read_qualifier(qualifier_id)
    assert qualifier["award_status"] == "TRAVELLED"
    assert qualifier["taxable_award_cents"] == 443198
    assert qualifier["tax_status"] == "PENDING_REPORT"
    assert read_registration(base["registration"]["id"])["attendance_status"] == "TRAVELLED"

    created = validate_success(
        api_client.create_tax_award_report(
            create_tax_award_report_payload(qualifier_id, 2026), _TAX
        ),
        201,
    )
    assert_tax_award_report(created)
    assert created["status"] == "DRAFT"
    assert created["award_value_cents"] == 443198
    assert created["gross_up_method"] == "FULL_GROSS_UP"
    assert created["combined_rate_bp"] == 3265
    assert created["reported_value_cents"] == 658052
    assert_reported_value_identity(created)
    # Drafting is not filing.
    assert read_program(program_id)["reported_award_total_cents"] == 0


def test_tax_report_draft_refusal_is_a_qualifier_error_not_a_program_state_error():
    """The refused draft persists nothing and reports the cross-entity qualifier
    error even though the program is still REGISTRATION_OPEN.

    PRD §3.9: "Drafting is deliberately **not** gated on the program's lifecycle
    status — any status except `CANCELLED` is accepted"

    Design: Difficulty/cross_entity_state_dependency/tax_report_draft_gated_on_qualifier_award_status_travelled
    """
    base = _registered_winner_program()
    qualifier_id = base["qualifier"]["id"]
    assert read_program(base["program"]["id"])["status"] == "REGISTRATION_OPEN"

    blocked = api_client.create_tax_award_report(
        create_tax_award_report_payload(qualifier_id, 2026), _TAX
    )
    validate_error(blocked, ApiErrorId.ERR_QUALIFIER_STATE_INVALID, 409)

    rows, meta = validate_paginated(
        api_client.list_tax_award_reports(_TAX, params={"qualifier_id": qualifier_id})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_qualifier(qualifier_id)["tax_status"] == "NOT_APPLICABLE"


def test_tax_report_draft_refused_for_a_notified_qualifier_who_never_travelled():
    """The gate compares the qualifier's own award axis, so a merely NOTIFIED
    winner is refused exactly as a REGISTERED one is.

    PRD §3.9: "the referenced qualifier's `award_status` must be `TRAVELLED`, and
    drafting against a qualifier who has not travelled reports
    `ERR_QUALIFIER_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/tax_report_draft_gated_on_qualifier_award_status_travelled
    """
    base = setup_registration_open_program(
        num_qualifiers=1,
        gross_up_policy="FULL_GROSS_UP",
        qualifier_overrides=dict(_QUALIFIER_B),
        program_overrides={"budget_total_cents": 5000000},
        tier_overrides=dict(_GOLD_TIER),
        destination_overrides=dict(_LISBON),
        contract_overrides=dict(_CONTRACT_5N),
    )
    qualifier_id = base["qualifier"]["id"]
    assert read_qualifier(qualifier_id)["award_status"] == "NOTIFIED"

    blocked = api_client.create_tax_award_report(
        create_tax_award_report_payload(qualifier_id, 2026), _TAX
    )
    validate_error(blocked, ApiErrorId.ERR_QUALIFIER_STATE_INVALID, 409)
    assert read_qualifier(qualifier_id)["tax_status"] == "NOT_APPLICABLE"


# ─── resource_temporal_overlap / activity agenda transfer buffer ──────────────

def _onsite_with_booked_anchor():
    """ONSITE program, one CONFIRMED winner, and a BOOKED signup on a LOW-risk
    capacity-5 activity running 2026-11-10 10:00:00Z - 13:00:00Z."""
    base = setup_onsite_program(num_qualifiers=1, waiver_signed=True)
    anchor = create_activity(
        base["program"]["id"],
        name="Sintra palace tour",
        start_at="2026-11-10T10:00:00Z",
        end_at="2026-11-10T13:00:00Z",
        capacity=5,
        risk_level="LOW",
    )
    signup = create_signup(anchor["id"], base["registration"]["id"])
    base["anchor"] = read_activity(anchor["id"])
    base["anchor_signup"] = read_signup(signup["id"])
    return base


def _attempt_signup(activity_id, registration_id):
    """Raw POST /activity-signups carrying the activity's live version."""
    return api_client.create_activity_signup(
        create_activity_signup_payload(
            activity_id, registration_id, activity_version(activity_id)
        ),
        _TD,
    )


def test_agenda_conflict_refuses_a_44_minute_gap_and_accepts_the_45_minute_boundary():
    """The transfer buffer boundary is closed: 13:44:00Z after a 13:00:00Z finish
    conflicts, 13:45:00Z does not.

    PRD §3.8: "Because both comparisons are strict, a gap of exactly 45 minutes is
    accepted and a gap of 44 minutes is refused: against an activity ending at
    2026-11-10T13:00:00Z, a signup starting at 13:44:00Z conflicts while one
    starting at 13:45:00Z does not."

    Design: Difficulty/resource_temporal_overlap/activity_agenda_overlap_uses_closed_transfer_buffer_boundary
    """
    base = _onsite_with_booked_anchor()
    program_id = base["program"]["id"]
    registration_id = base["registration"]["id"]
    assert base["anchor_signup"]["status"] == "BOOKED"

    too_close = create_activity(
        program_id,
        name="Belem walking tour",
        start_at="2026-11-10T13:44:00Z",
        end_at="2026-11-10T16:00:00Z",
        capacity=5,
        risk_level="LOW",
    )
    on_boundary = create_activity(
        program_id,
        name="Alfama food crawl",
        start_at="2026-11-10T13:45:00Z",
        end_at="2026-11-10T16:30:00Z",
        capacity=5,
        risk_level="LOW",
    )

    validate_error(
        _attempt_signup(too_close["id"], registration_id),
        ApiErrorId.ERR_ACTIVITY_TIME_CONFLICT,
        409,
    )

    accepted = validate_success(_attempt_signup(on_boundary["id"], registration_id), 201)
    assert_activity_signup(accepted)
    assert accepted["status"] == "BOOKED"
    assert_signup_counters(read_activity(on_boundary["id"]), booked=1, waitlisted=0)


def test_agenda_conflict_refusal_creates_no_signup_and_leaves_the_agenda_intact():
    """The refused signup persists nothing: the rejected activity's counters stay
    at 0 and the pre-existing booked slot is undisturbed.

    PRD §3.8: "For each of the participant's existing signups whose `status` is
    `BOOKED` or `WAITLISTED`, the requested activity conflicts when its `start_at`
    is strictly before the existing activity's `end_at` advanced by 45 minutes
    **and** the existing activity's `start_at` is strictly before the requested
    activity's `end_at` advanced by 45 minutes"

    Design: Difficulty/resource_temporal_overlap/activity_agenda_overlap_uses_closed_transfer_buffer_boundary
    """
    base = _onsite_with_booked_anchor()
    registration_id = base["registration"]["id"]

    too_close = create_activity(
        base["program"]["id"],
        name="Belem walking tour",
        start_at="2026-11-10T13:44:00Z",
        end_at="2026-11-10T16:00:00Z",
        capacity=5,
        risk_level="LOW",
    )
    validate_error(
        _attempt_signup(too_close["id"], registration_id),
        ApiErrorId.ERR_ACTIVITY_TIME_CONFLICT,
        409,
    )

    assert_signup_counters(read_activity(too_close["id"]), booked=0, waitlisted=0)
    rows, meta = validate_paginated(
        api_client.list_activity_signups(_TD, params={"activity_id": too_close["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    anchor_signup = read_signup(base["anchor_signup"]["id"])
    assert anchor_signup["status"] == "BOOKED"
    assert_signup_counters(read_activity(base["anchor"]["id"]), booked=1, waitlisted=0)


def test_agenda_buffer_pads_the_requested_interval_on_its_trailing_side_too():
    """The buffer is applied on both sides, so an activity finishing 44 minutes
    before the booked one conflicts while one finishing 45 minutes before does not.

    PRD §3.8: "**Schedule conflicts** are checked against the participant's own
    agenda, and every activity interval is padded by a 45-minute transfer buffer
    on both sides."

    Design: Difficulty/resource_temporal_overlap/activity_agenda_overlap_uses_closed_transfer_buffer_boundary
    """
    base = _onsite_with_booked_anchor()
    program_id = base["program"]["id"]
    registration_id = base["registration"]["id"]

    ends_too_late = create_activity(
        program_id,
        name="Cascais morning ride",
        start_at="2026-11-10T07:00:00Z",
        end_at="2026-11-10T09:16:00Z",
        capacity=5,
        risk_level="LOW",
    )
    ends_on_boundary = create_activity(
        program_id,
        name="Estoril sunrise run",
        start_at="2026-11-10T07:00:00Z",
        end_at="2026-11-10T09:15:00Z",
        capacity=5,
        risk_level="LOW",
    )

    validate_error(
        _attempt_signup(ends_too_late["id"], registration_id),
        ApiErrorId.ERR_ACTIVITY_TIME_CONFLICT,
        409,
    )
    assert_signup_counters(read_activity(ends_too_late["id"]), booked=0, waitlisted=0)

    accepted = validate_success(_attempt_signup(ends_on_boundary["id"], registration_id), 201)
    assert accepted["status"] == "BOOKED"
    assert_signup_counters(read_activity(ends_on_boundary["id"]), booked=1, waitlisted=0)


# ─── resource_temporal_overlap / per-night room block occupancy ───────────────

_ROOM_BLOCK_TIER = {
    "tier_code": "GOLD",
    "tier_rank": 1,
    "qualification_threshold": 100000000,
    "budget_per_qualifier_cents": 1600000,
    "guest_allowance": 0,
    "air_cabin_class": "PREMIUM_ECONOMY",
    "upgrade_allowance_cents": 40000,
    "service_load_bp": 800,
}
_ROOM_BLOCK_QUALIFIERS = [
    {"employee_code": "S-4001", "full_name": "Iris Kade", "baseline_metric": 100000000,
     "actual_metric": 150000000, "guest_count": 0},
    {"employee_code": "S-4002", "full_name": "Jonas Pike", "baseline_metric": 100000000,
     "actual_metric": 150000000, "guest_count": 0},
    {"employee_code": "S-4003", "full_name": "Kemi Adeyi", "baseline_metric": 100000000,
     "actual_metric": 150000000, "guest_count": 0},
]


def _two_room_block_program():
    """A 2-room, 5-night block (stay window 2026-11-08 -> 2026-11-13) with seat X
    CONFIRMED over the nights of 08, 09 and 10 November, and seats Y and Z ACCEPTED.

    X: q1, 2 rooms, 08 Nov -> 11 Nov.  Y: q2, 1 room, 10 Nov -> 12 Nov.
    Z: q3, 2 rooms, 11 Nov -> 13 Nov.
    """
    base = setup_registration_open_program(
        qualifier_specs=[dict(spec) for spec in _ROOM_BLOCK_QUALIFIERS],
        gross_up_policy="NONE",
        program_overrides={"name": "FY26 Room Block Probe", "budget_total_cents": 20000000},
        tier_overrides=dict(_ROOM_BLOCK_TIER),
        destination_overrides=dict(_LISBON),
        contract_overrides={
            "room_block_count": 2,
            "contracted_nights": 5,
            "stay_start_at": "2026-11-08T00:00:00Z",
        },
    )
    program_id = base["program"]["id"]
    q1, q2, q3 = base["qualifiers"]

    seat_x = create_registration(
        q1["id"], program_id=program_id, arrival_date="2026-11-08T00:00:00Z",
        departure_date="2026-11-11T00:00:00Z", rooms=2,
    )
    respond_registration(seat_x["id"], q1["id"], "ACCEPT")
    confirm_registration(seat_x["id"])

    seat_y = create_registration(
        q2["id"], program_id=program_id, arrival_date="2026-11-10T00:00:00Z",
        departure_date="2026-11-12T00:00:00Z", rooms=1,
    )
    respond_registration(seat_y["id"], q2["id"], "ACCEPT")

    seat_z = create_registration(
        q3["id"], program_id=program_id, arrival_date="2026-11-11T00:00:00Z",
        departure_date="2026-11-13T00:00:00Z", rooms=2,
    )
    respond_registration(seat_z["id"], q3["id"], "ACCEPT")

    base["seat_x"] = read_registration(seat_x["id"])
    base["seat_y"] = read_registration(seat_y["id"])
    base["seat_z"] = read_registration(seat_z["id"])
    base["contract"] = read_contract(base["contract"]["id"])
    return base


def test_room_block_refuses_an_overlapping_night_but_admits_a_touching_stay():
    """A 1-room stay across the already-full night of 10 November is refused, while
    a 2-room stay arriving on the incumbent's departure date is confirmed.

    PRD §3.7: "Because the intervals are half-open, a departing seat and an
    arriving seat may share the same calendar date without contending for a room on
    that night."

    Design: Difficulty/resource_temporal_overlap/room_block_occupancy_is_per_night_over_half_open_stay_intervals
    """
    base = _two_room_block_program()
    assert base["contract"]["room_block_count"] == 2
    assert base["seat_x"]["attendance_status"] == "CONFIRMED"

    refused = api_client.confirm_registration(base["seat_y"]["id"], _TD)
    validate_error(refused, ApiErrorId.ERR_ROOM_BLOCK_EXHAUSTED, 409)

    confirmed = validate_success(
        api_client.confirm_registration(base["seat_z"]["id"], _TD), 200
    )
    assert_registration(confirmed)
    assert confirmed["attendance_status"] == "CONFIRMED"
    assert confirmed["room_nights"] == 4


def test_room_block_refusal_leaves_the_seat_and_the_room_night_ledger_untouched():
    """The rejected confirmation books nothing: the seat stays ACCEPTED with 0
    room-nights and the contract's ledger still shows only the incumbent's 6.

    PRD §3.7: "For each night in the candidate seat's half-open interval, the
    server sums the `rooms` of every seat of the same program whose
    `attendance_status` is `CONFIRMED` or `TRAVELLED` and whose own half-open
    interval covers that night"

    Design: Difficulty/resource_temporal_overlap/room_block_occupancy_is_per_night_over_half_open_stay_intervals
    """
    base = _two_room_block_program()
    contract_id = base["contract"]["id"]

    validate_error(
        api_client.confirm_registration(base["seat_y"]["id"], _TD),
        ApiErrorId.ERR_ROOM_BLOCK_EXHAUSTED,
        409,
    )

    seat_y = read_registration(base["seat_y"]["id"])
    assert seat_y["attendance_status"] == "ACCEPTED"
    assert seat_y["room_nights"] == 0

    contract = read_contract(contract_id)
    assert contract["room_nights_blocked"] == 10
    assert contract["room_nights_confirmed"] == 6
    assert contract["room_nights_available"] == 4
    assert_room_nights_conserved(contract)

    # Z's confirmation proves ACCEPTED seat Y never occupied the night of the 11th.
    confirm_registration(base["seat_z"]["id"])
    assert read_registration(base["seat_z"]["id"])["attendance_status"] == "CONFIRMED"


def test_confirmed_room_nights_count_half_open_nights_and_fill_the_block_exactly():
    """Room-nights are counted over the half-open stay interval, so X consumes 6 and
    the touching Z consumes 4, filling the 10-room-night block exactly.

    PRD §3.7: "A seat's `room_nights` is its `rooms` multiplied by the number of
    whole days from `arrival_date` up to but excluding `departure_date` — two rooms
    arriving on the 10th and departing on the 14th consume eight room-nights, not
    ten."

    Design: Difficulty/resource_temporal_overlap/room_block_occupancy_is_per_night_over_half_open_stay_intervals
    """
    base = _two_room_block_program()
    contract_id = base["contract"]["id"]
    assert base["seat_x"]["room_nights"] == 6

    confirm_registration(base["seat_z"]["id"])
    assert read_registration(base["seat_z"]["id"])["room_nights"] == 4

    contract = read_contract(contract_id)
    assert contract["room_nights_blocked"] == 10
    assert contract["room_nights_confirmed"] == 10
    assert contract["room_nights_available"] == 0
    assert_room_nights_conserved(contract)
    assert contract["attrition_posture"] == "CLEAR"

    projection = read_exposure_projection(contract_id)
    assert projection["room_nights_blocked"] == 10
    assert projection["room_nights_confirmed"] == 10
    assert projection["attrition_floor_room_nights"] == 8
    assert projection["shortfall_room_nights"] == 0
