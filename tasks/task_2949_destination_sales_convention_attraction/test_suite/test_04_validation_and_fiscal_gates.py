"""Validation gates and the fiscal ladder on an incentive decision.

Every test in this module translates exactly one instance of the
``validations`` section of the corner design index.  The clock is pinned as the
first server call of every test (directly or through a ``setup_*`` helper), and
each test builds 100% of its own preconditions.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_money_equals,
    create_bid_package_payload,
    create_room_block_commitment_payload,
    create_space_hold_payload,
    fixtures,
    incentive_decision_payload,
    offer_payload,
    pickup_record_payload,
    planner_response_payload,
    same_instant,
    submit_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    make_hotel_partner_headers,
    make_meeting_planner_headers,
)

CLOCK_2026 = "2026-08-01T00:00:00Z"
RESPONSE_DUE_2026 = "2026-09-01T00:00:00Z"
SINGLE_HARBORVIEW = (("Harborview Grand", 600, 2),)


def test_offer_rate_and_room_ceilings_are_inclusive_bounds():
    """An offer one cent over the rate ceiling and one room over the property's
    inventory both fail with ERR_RATE_CEILING_EXCEEDED, while an offer exactly
    at the ceiling is accepted.

    PRD: "Two ceilings bind the offer, and both produce `ERR_RATE_CEILING_EXCEEDED` with HTTP 422: the `rate_offered_amount` may not exceed the lead's `rate_ceiling_amount`, and `rooms_peak_offered` may not exceed the property's own `committable_rooms`." (PRD S3.5)
    PRD: "A successful offer stores the three fields, derives `cutoff_date` as the lead's `arrival_date` less `cutoff_days_before_arrival` days, and increments `offer_round` by one. From status `INVITED` the offer moves the commitment to `OFFERED`" (PRD S3.5)

    Design: Corner/validations/rate_ceiling_is_inclusive_and_an_over_ceiling_offer_is_refused
    """
    scenario = fixtures.setup_lead(clock=CLOCK_2026, hotel_specs=SINGLE_HARBORVIEW)
    hotel_id = scenario["hotels"][0]["id"]
    hotel_headers = make_hotel_partner_headers(hotel_id)
    commitment = fixtures.invite_hotel(scenario["opportunity_id"], hotel_id, 500)

    over_rate = api_client.offer_room_block_commitment(
        commitment["id"],
        offer_payload(
            rooms_peak_offered=500,
            rate_offered_amount=219.01,
            cutoff_days_before_arrival=30,
        ),
        hotel_headers,
    )
    validate_error(over_rate, ApiErrorId.ERR_RATE_CEILING_EXCEEDED.value, 422)

    over_rooms = api_client.offer_room_block_commitment(
        commitment["id"],
        offer_payload(
            rooms_peak_offered=601,
            rate_offered_amount=210.00,
            cutoff_days_before_arrival=30,
        ),
        hotel_headers,
    )
    validate_error(over_rooms, ApiErrorId.ERR_RATE_CEILING_EXCEEDED.value, 422)

    untouched = fixtures.read_commitment(commitment["id"])
    assert untouched["status"] == "INVITED", "a refused offer must not move the commitment"
    assert untouched["offer_round"] == 0, "a refused offer must not consume an offer round"
    assert untouched["rate_offered_amount"] is None, "a refused offer must store no rate"

    accepted = validate_success(
        api_client.offer_room_block_commitment(
            commitment["id"],
            offer_payload(
                rooms_peak_offered=500,
                rate_offered_amount=219.00,
                cutoff_days_before_arrival=30,
            ),
            hotel_headers,
        ),
        200,
    )
    assert accepted["status"] == "OFFERED"
    assert_money_equals(accepted["rate_offered_amount"], 219.00, "rate_offered_amount")
    assert accepted["offer_round"] == 1
    assert accepted["cutoff_date"] == "2028-03-11", (
        "cutoff_date is arrival_date 2028-04-10 less 30 days"
    )


def test_duplicate_invite_is_refused_until_the_live_row_is_withdrawn():
    """A second invitation for the same opportunity and hotel is refused while
    the first row is live, and succeeds once that row is WITHDRAWN.

    PRD: "It requires the lead to be in `QUALIFIED` or `BIDDING`, the property to be `PARTICIPATING`, and — importantly — no existing commitment for that same pair of opportunity and hotel to be live in status `INVITED`, `OFFERED` or `COMMITTED`. A second invitation to a property that is already in the block is refused with `ERR_DUPLICATE_COMMITMENT` and HTTP 409; a property whose earlier commitment ended in `WITHDRAWN` or `RELEASED` may be invited afresh." (PRD S3.5)
    PRD: "A new commitment starts in status `INVITED` with `offer_round` 0" (PRD S3.5)

    Design: Corner/validations/duplicate_invite_is_refused_until_the_live_row_is_withdrawn
    """
    scenario = fixtures.setup_lead(clock=CLOCK_2026, hotel_specs=SINGLE_HARBORVIEW)
    opportunity_id = scenario["opportunity_id"]
    hotel_id = scenario["hotels"][0]["id"]
    first = fixtures.invite_hotel(opportunity_id, hotel_id, 500)

    duplicate = api_client.create_room_block_commitment(
        create_room_block_commitment_payload(
            opportunity_id,
            hotel_id,
            fixtures.opportunity_version(opportunity_id),
            rooms_peak_invited=400,
        ),
        fixtures.SALES,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_COMMITMENT.value, 409)

    withdrawn = fixtures.withdraw_block(first["id"], hotel_id, "INVITE_DECLINED")
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdraw_reason"] == "INVITE_DECLINED"

    reinvited = validate_success(
        api_client.create_room_block_commitment(
            create_room_block_commitment_payload(
                opportunity_id,
                hotel_id,
                fixtures.opportunity_version(opportunity_id),
                rooms_peak_invited=400,
            ),
            fixtures.SALES,
        ),
        201,
    )
    assert reinvited["id"] != first["id"], "the fresh invite is a distinct commitment"
    assert reinvited["status"] == "INVITED"
    assert reinvited["offer_round"] == 0

    _, meta = validate_paginated(
        api_client.list_room_block_commitments(
            fixtures.SALES, params={"opportunity_id": opportunity_id}
        )
    )
    assert meta["total_count"] == 2, (
        "the withdrawn row is retained as history alongside the fresh invite"
    )


def test_pickup_nights_must_be_inside_the_event_range_and_unique_per_night():
    """The departure night and a pre-arrival night are both out of range, a
    repeat night is a duplicate, and neither refusal moves the pickup counters.

    PRD: "The `night_date` must fall inside the block's occupied nights — at or after `arrival_date` and strictly before `departure_date`, the departure night itself included in the rejection — or the filing is refused with `ERR_PICKUP_NIGHT_OUT_OF_RANGE`; and only one pickup record may exist per commitment and night, a repeat being refused with `ERR_DUPLICATE_PICKUP_NIGHT`, both with HTTP 422." (PRD S3.5)
    PRD: "The server derives `room_night_revenue_amount` as `rooms_picked_up` multiplied by `rate_charged_amount`, rounded half-up to two decimals, then raises the commitment's `picked_up_room_nights` and the property's `pickup_room_nights` by the rooms reported" (PRD S3.5)

    Design: Corner/validations/pickup_nights_must_be_inside_the_event_range_and_unique_per_night
    """
    scenario = fixtures.setup_block_assembled(
        clock="2027-03-01T00:00:00Z",
        allocations=((0, 500, 214.33, 30),),
    )
    commitment = scenario["commitments"][0]
    commitment_id = commitment["id"]
    hotel_id = commitment["hotel_id"]
    hotel_headers = make_hotel_partner_headers(hotel_id)
    fixtures.set_clock("2028-04-13T00:00:00Z")

    departure_night = api_client.create_pickup_record(
        commitment_id, pickup_record_payload("2028-04-12", 100, 214.33), hotel_headers
    )
    validate_error(
        departure_night, ApiErrorId.ERR_PICKUP_NIGHT_OUT_OF_RANGE.value, 422
    )

    pre_arrival_night = api_client.create_pickup_record(
        commitment_id, pickup_record_payload("2028-04-09", 100, 214.33), hotel_headers
    )
    validate_error(
        pre_arrival_night, ApiErrorId.ERR_PICKUP_NIGHT_OUT_OF_RANGE.value, 422
    )

    accepted = validate_success(
        api_client.create_pickup_record(
            commitment_id, pickup_record_payload("2028-04-10", 400, 214.33), hotel_headers
        ),
        201,
    )
    assert_money_equals(
        accepted["room_night_revenue_amount"], 85732.00, "room_night_revenue_amount"
    )

    repeat = api_client.create_pickup_record(
        commitment_id, pickup_record_payload("2028-04-10", 50, 214.33), hotel_headers
    )
    validate_error(repeat, ApiErrorId.ERR_DUPLICATE_PICKUP_NIGHT.value, 422)

    assert fixtures.read_commitment(commitment_id)["picked_up_room_nights"] == 400, (
        "neither rejected filing moved the commitment's pickup counter"
    )
    assert fixtures.read_hotel(hotel_id)["pickup_room_nights"] == 400, (
        "neither rejected filing moved the property's pickup counter"
    )


def _approved_bid_at_half_coverage(letter_types):
    """APPROVED bid whose lead has only 50.00 percent citywide coverage.

    Local helper (not a test): letters are attached while the package is still
    in DRAFT, as PRD S3.7 requires, and the incentive of 10,000.00 sits under
    the coverage-discounted cap of 11,086.88 so the approval clears every
    fiscal gate.
    """
    return fixtures.setup_bid_approved(
        clock=CLOCK_2026,
        letter_types=letter_types,
        allocations=((0, 500, 214.33, 30),),
        incentive_request_amount=10_000.00,
    )


def test_submit_reports_missing_letter_breadth_before_short_coverage():
    """A submission violating both the letters gate and the coverage gate
    returns the letters error; with two distinct letter types present the same
    short-coverage lead falls through to the coverage error.

    PRD: "When a single request violates several rules at once, the answer is deterministic: the rule with the lowest position in the following ladder wins, and the request carries that rule's error code." (PRD S2.7, where letters are rung 30 and coverage rung 31)
    PRD: "The package's `support_letter_type_count` must be at least 2, or the submission fails with `ERR_SUPPORT_LETTERS_INSUFFICIENT`; two letters of the same constituency do not satisfy the community-support requirement. The lead's `block_coverage_pct` must be at least 85.00, or the submission fails with `ERR_BLOCK_COVERAGE_INSUFFICIENT`" (PRD S3.8)

    Design: Corner/validations/submit_checks_support_letters_before_block_coverage
    """
    narrow = _approved_bid_at_half_coverage(("MAYOR", "MAYOR"))
    assert narrow["bid"]["support_letter_type_count"] == 1, (
        "two MAYOR letters raise the row count but not the distinct type count"
    )
    assert_money_equals(
        fixtures.read_opportunity(narrow["opportunity_id"])["block_coverage_pct"],
        50.00,
        "block_coverage_pct",
    )

    both_violated = api_client.submit_bid_package(
        narrow["bid_id"], submit_payload(RESPONSE_DUE_2026), fixtures.SALES
    )
    validate_error(
        both_violated, ApiErrorId.ERR_SUPPORT_LETTERS_INSUFFICIENT.value, 422
    )

    untouched = fixtures.read_bid(narrow["bid_id"])
    assert untouched["status"] == "APPROVED", "a refused submission writes nothing"
    assert untouched["submitted_at"] is None
    assert untouched["support_letter_type_count"] == 1

    broad = _approved_bid_at_half_coverage(("MAYOR", "CHAMBER"))
    assert broad["bid"]["support_letter_type_count"] == 2
    assert_money_equals(
        fixtures.read_opportunity(broad["opportunity_id"])["block_coverage_pct"],
        50.00,
        "block_coverage_pct",
    )

    coverage_only = api_client.submit_bid_package(
        broad["bid_id"], submit_payload(RESPONSE_DUE_2026), fixtures.SALES
    )
    validate_error(
        coverage_only, ApiErrorId.ERR_BLOCK_COVERAGE_INSUFFICIENT.value, 422
    )
    assert fixtures.read_bid(broad["bid_id"])["status"] == "APPROVED"


def test_cutoff_spread_beyond_tolerance_blocks_submit_until_realigned():
    """Individually legal cutoffs 30 and 45 days give a spread of 15 that blocks
    submission even at 90.00 coverage; re-doing the second block at 31 days
    leaves coverage untouched, drops the spread to 1 and lets the submit through.

    PRD: "And the lead's `cutoff_alignment_spread_days` must be at most 2, or the submission fails with `ERR_CUTOFF_MISALIGNED`; a block whose properties release unsold rooms more than two days apart cannot be advertised with a single citywide cutoff." (PRD S3.8)
    PRD: "`citywide_cutoff_days_before_arrival` is the **largest** `cutoff_days_before_arrival` among the committed properties, which is the citywide cutoff the bid will advertise, or 0 when nothing is committed; and `cutoff_alignment_spread_days` is the largest such value minus the smallest" (PRD S3.5)

    Design: Corner/validations/cutoff_spread_beyond_tolerance_blocks_submit_until_realigned
    """
    scenario = fixtures.setup_bid_approved(
        clock=CLOCK_2026,
        letter_types=("MAYOR", "CHAMBER"),
        allocations=((0, 500, 214.33, 30),),
        incentive_request_amount=10_000.00,
    )
    opportunity_id = scenario["opportunity_id"]
    bid_id = scenario["bid_id"]
    bayside_id = scenario["hotels"][1]["id"]

    misaligned_block = fixtures.add_committed_block(
        opportunity_id, bayside_id, 400, 209.77, 45
    )
    assert misaligned_block["rooms_peak_committed"] == 400
    misaligned = fixtures.read_opportunity(opportunity_id)
    assert_money_equals(misaligned["block_coverage_pct"], 90.00, "block_coverage_pct")
    assert misaligned["cutoff_alignment_spread_days"] == 15
    assert misaligned["citywide_cutoff_days_before_arrival"] == 45

    refused = api_client.submit_bid_package(
        bid_id, submit_payload(RESPONSE_DUE_2026), fixtures.SALES
    )
    validate_error(refused, ApiErrorId.ERR_CUTOFF_MISALIGNED.value, 422)
    assert fixtures.read_bid(bid_id)["status"] == "APPROVED"

    fixtures.withdraw_block(misaligned_block["id"], bayside_id, "RATE_DISPUTE")
    fixtures.add_committed_block(opportunity_id, bayside_id, 400, 209.77, 31)
    aligned = fixtures.read_opportunity(opportunity_id)
    assert_money_equals(aligned["block_coverage_pct"], 90.00, "block_coverage_pct")
    assert aligned["cutoff_alignment_spread_days"] == 1
    assert aligned["citywide_cutoff_days_before_arrival"] == 31

    submitted = validate_success(
        api_client.submit_bid_package(
            bid_id, submit_payload(RESPONSE_DUE_2026), fixtures.SALES
        ),
        200,
    )
    assert submitted["status"] == "SUBMITTED"
    assert same_instant(submitted["submitted_at"], CLOCK_2026), (
        "submitted_at is stamped from the logical clock"
    )
    assert same_instant(submitted["response_due_at"], RESPONSE_DUE_2026)
    assert fixtures.read_opportunity(opportunity_id)["sales_stage"] == "BIDDING"


def test_planner_response_after_the_due_date_returns_challenge_window_closed():
    """A planner answer one day after `response_due_at` is refused and fires no
    part of the acceptance cascade, while the same answer at exactly
    `response_due_at` is accepted.

    PRD: "The answer must arrive while the current logical clock is at or before `response_due_at`; a late answer is refused with `ERR_CHALLENGE_WINDOW_CLOSED` and HTTP 422." (PRD S3.8)
    PRD: "Whatever the verdict, it is stored on the package as `planner_response`" (PRD S3.8)

    Design: Corner/validations/planner_response_after_the_due_date_returns_challenge_window_closed
    """
    scenario = fixtures.setup_bid_submitted(response_due_at="2027-04-01T00:00:00Z")
    bid_id = scenario["bid_id"]
    planner_headers = make_meeting_planner_headers(scenario["planner_id"])
    fixtures.set_clock("2027-04-02T00:00:00Z")

    late = api_client.planner_response(
        bid_id, planner_response_payload("ACCEPTED"), planner_headers
    )
    validate_error(late, ApiErrorId.ERR_CHALLENGE_WINDOW_CLOSED.value, 422)

    bid = fixtures.read_bid(bid_id)
    assert bid["status"] == "SUBMITTED", "the late answer leaves the package submitted"
    assert bid["planner_response"] is None, "the late answer is not recorded"
    opportunity = fixtures.read_opportunity(scenario["opportunity_id"])
    assert opportunity["sales_stage"] == "BIDDING"
    assert opportunity["hold_posture"] == "TENTATIVE"
    assert fixtures.read_hold(scenario["hold_id"])["status"] == "HELD"

    fixtures.set_clock("2027-04-01T00:00:00Z")
    accepted = validate_success(
        api_client.planner_response(
            bid_id, planner_response_payload("ACCEPTED"), planner_headers
        ),
        200,
    )
    assert accepted["status"] == "ACCEPTED", (
        "the comparison is clock <= response_due_at, so the boundary is answerable"
    )
    assert accepted["planner_response"] == "ACCEPTED"


def test_confirmed_hold_and_undersized_hall_block_new_holds_with_distinct_errors():
    """A rival overlapping a CONFIRMED hold gets ERR_HALL_WINDOW_CONFLICT, the
    same rival on an undersized hall gets ERR_HALL_CAPACITY_INSUFFICIENT, and a
    window clearing the turnaround buffer is admitted as a FIRST-rank hold.

    PRD: "Three outcomes follow from that blocking set, evaluated in this order. If any blocking hold is `CONFIRMED`, the space is already sold and the request is refused with `ERR_HALL_WINDOW_CONFLICT`." (PRD S3.3)
    PRD: "the lead's `attendance_estimate` must not exceed the hall's `capacity_persons`, and its `exhibit_sqft_requested` must not exceed the hall's `exhibit_sqft`. A failure of either dimension is reported as `ERR_HALL_CAPACITY_INSUFFICIENT` with HTTP 422." (PRD S3.3)

    Design: Corner/validations/confirmed_hold_and_undersized_hall_block_new_holds_with_distinct_errors
    """
    scenario = fixtures.setup_definite_lead()
    hall_id = scenario["hall_id"]
    assert scenario["hold"]["status"] == "CONFIRMED", "the accepted lead confirmed its hold"

    small_hall = fixtures.register_hall(
        name="Ballroom C", exhibit_sqft=40_000, capacity_persons=3_000,
        turnaround_hours=24,
    )
    rival = fixtures.create_lead(
        scenario["planner_id"],
        event_name="Rival Congress 2028",
        arrival_date="2028-04-10",
        departure_date="2028-04-12",
        peak_rooms_requested=700,
        total_room_nights_requested=1200,
        attendance_estimate=6000,
        exhibit_sqft_requested=150_000,
        rate_ceiling_amount=209.00,
    )
    fixtures.qualify_lead(rival["id"])

    overlapping = api_client.create_space_hold(
        create_space_hold_payload(
            rival["id"], hall_id,
            move_in_start="2028-04-11T00:00:00Z",
            move_out_end="2028-04-16T00:00:00Z",
        ),
        fixtures.SCHEDULER,
    )
    validate_error(overlapping, ApiErrorId.ERR_HALL_WINDOW_CONFLICT.value, 409)

    undersized = api_client.create_space_hold(
        create_space_hold_payload(
            rival["id"], small_hall["id"],
            move_in_start="2028-04-09T00:00:00Z",
            move_out_end="2028-04-13T00:00:00Z",
        ),
        fixtures.SCHEDULER,
    )
    validate_error(undersized, ApiErrorId.ERR_HALL_CAPACITY_INSUFFICIENT.value, 422)

    clear_of_the_buffer = validate_success(
        api_client.create_space_hold(
            create_space_hold_payload(
                rival["id"], hall_id,
                move_in_start="2028-04-15T00:00:00Z",
                move_out_end="2028-04-18T00:00:00Z",
            ),
            fixtures.SCHEDULER,
        ),
        201,
    )
    assert clear_of_the_buffer["hold_rank"] == "FIRST"
    assert clear_of_the_buffer["status"] == "HELD"
    assert fixtures.read_hall(hall_id)["confirmed_hold_count"] == 1, (
        "the confirmed-hold counter never moved through the three attempts"
    )


def test_fund_residual_ladder_runs_insufficient_then_exact_zero_then_exhausted():
    """9,600.00 against a 10,000.00 fund fails on the fee-inclusive residual,
    9,523.81 lands on exactly 10,000.00 and exhausts the fund, and the next
    decision returns ERR_FUND_EXHAUSTED rather than the cap error.

    PRD: "The `approved_amount` must not exceed the incentive cap **recomputed at decision time** — not the value stored at request time — or the decision fails with `ERR_INCENTIVE_EXCEEDS_CAP`. The resulting `total_charge_amount` must not exceed the fund's `uncommitted_amount`, or the decision fails with `ERR_FUND_INSUFFICIENT`." (PRD S3.7)
    PRD: "When `uncommitted_amount` is exactly zero the posture is `EXHAUSTED`." (PRD S2.10) and "The named fund must not be in `posture` `EXHAUSTED`, or the decision fails with `ERR_FUND_EXHAUSTED` and HTTP 409" (PRD S3.7), which S2.7 ranks 34, ahead of the cap check at 35.

    Design: Corner/validations/fund_residual_ladder_runs_insufficient_then_exact_zero_then_exhausted
    """
    scenario = fixtures.setup_bid_incentive_pending(
        clock=CLOCK_2026,
        planner_overrides={"legacy_definite_count": 0, "legacy_definite_room_nights": 0},
        fund_overrides={"fiscal_year": 2028, "budget_amount": 10_000.00},
        opportunity_overrides={
            "arrival_date": "2028-04-10",
            "departure_date": "2028-04-16",
            "peak_rooms_requested": 500,
            "total_room_nights_requested": 3000,
            "rate_ceiling_amount": 219.00,
        },
        allocations=((0, 500, 214.33, 30),),
        incentive_request_amount=9_600.00,
    )
    fund_id = scenario["fund_id"]
    bid_x = scenario["bid_id"]
    assert fixtures.read_planner(scenario["planner_id"])["tier"] == "TIER_C"
    assert_money_equals(
        scenario["bid"]["incentive_cap_amount"], 14782.50, "incentive_cap_amount"
    )
    opening_fund = fixtures.read_fund(fund_id)
    assert_money_equals(opening_fund["uncommitted_amount"], 10000.00, "uncommitted_amount")
    assert opening_fund["posture"] == "OPEN"

    lead_y = fixtures.create_lead(scenario["planner_id"], event_name="CDA Regional 2028")
    fixtures.qualify_lead(lead_y["id"])
    bid_y = fixtures.open_bid(lead_y["id"])
    fixtures.ask_for_incentive(bid_y["id"], 100.00)

    over_the_residual = api_client.create_incentive_decision(
        bid_x,
        incentive_decision_payload(
            fund_id, "APPROVED", 9_600.00, fixtures.fund_version(fund_id),
            rationale="Too rich once the admin fee is added",
        ),
        fixtures.APPROVER,
    )
    validate_error(over_the_residual, ApiErrorId.ERR_FUND_INSUFFICIENT.value, 422)

    to_the_penny = validate_success(
        api_client.create_incentive_decision(
            bid_x,
            incentive_decision_payload(
                fund_id, "REDUCED", 9_523.81, fixtures.fund_version(fund_id),
                rationale="Charges the fund to exactly zero",
            ),
            fixtures.APPROVER,
        ),
        201,
    )
    assert_money_equals(to_the_penny["admin_fee_amount"], 476.19, "admin_fee_amount")
    assert_money_equals(to_the_penny["total_charge_amount"], 10000.00, "total_charge_amount")
    assert_money_equals(to_the_penny["tax_payback_ratio"], 9.86, "tax_payback_ratio")

    exhausted_fund = fixtures.read_fund(fund_id)
    assert_money_equals(exhausted_fund["committed_amount"], 10000.00, "committed_amount")
    assert_money_equals(exhausted_fund["uncommitted_amount"], 0.00, "uncommitted_amount")
    assert exhausted_fund["posture"] == "EXHAUSTED"

    nothing_left = api_client.create_incentive_decision(
        bid_y["id"],
        incentive_decision_payload(
            fund_id, "APPROVED", 100.00, fixtures.fund_version(fund_id),
            rationale="Nothing left to give",
        ),
        fixtures.APPROVER,
    )
    validate_error(nothing_left, ApiErrorId.ERR_FUND_EXHAUSTED.value, 409)

    _, meta = validate_paginated(
        api_client.list_fund_incentive_decisions(fund_id, fixtures.APPROVER)
    )
    assert meta["total_count"] == 1, "the two refused decisions stored no row"


def test_tax_payback_floor_rejects_an_incentive_that_sits_at_its_own_cap():
    """Approving the full 116,000.00 cap costs 120,640.00 once the 4 percent fee
    applies, giving a payback of 2.98 and a refusal; 110,000.00 costs 114,400.00
    and clears the floor at 3.15.

    PRD: "And the `tax_payback_ratio` must be at least 3.00 — the city insists on three dollars of projected lodging tax for every dollar of gross charge — or the decision fails with `ERR_TAX_PAYBACK_BELOW_FLOOR`." (PRD S3.7)
    PRD: "Select the administrative fee rate from **that gross figure only**: 0.05 when the gross is below 100,000.00, 0.04 when the gross is at or above 100,000.00 but below 250,000.00" and "`tax_payback_ratio` is the newest `PROVISIONAL` estimate's `lodging_tax_yield_amount` divided by `total_charge_amount`, rounded half-up to two decimals." (PRD S3.7)

    Design: Corner/validations/tax_payback_floor_rejects_an_incentive_that_sits_at_its_own_cap
    """
    scenario = fixtures.setup_bid_incentive_pending(
        clock=CLOCK_2026,
        planner_overrides={"legacy_definite_count": 5, "legacy_definite_room_nights": 0},
        opportunity_overrides={
            "peak_rooms_requested": 500,
            "total_room_nights_requested": 12000,
            "rate_ceiling_amount": 200.00,
        },
        allocations=((0, 500, 195.00, 30),),
        incentive_request_amount=116_000.00,
    )
    fund_id = scenario["fund_id"]
    bid_z = scenario["bid_id"]
    assert fixtures.read_planner(scenario["planner_id"])["tier"] == "TIER_A"
    assert_money_equals(
        scenario["bid"]["incentive_cap_amount"], 116000.00, "incentive_cap_amount"
    )

    at_the_cap = api_client.create_incentive_decision(
        bid_z,
        incentive_decision_payload(
            fund_id, "APPROVED", 116_000.00, fixtures.fund_version(fund_id),
            rationale="Exactly at the cap but the payback fails",
        ),
        fixtures.APPROVER,
    )
    validate_error(at_the_cap, ApiErrorId.ERR_TAX_PAYBACK_BELOW_FLOOR.value, 422)

    reduced = validate_success(
        api_client.create_incentive_decision(
            bid_z,
            incentive_decision_payload(
                fund_id, "REDUCED", 110_000.00, fixtures.fund_version(fund_id),
                rationale="Reduced so the lodging tax still pays back three times",
            ),
            fixtures.APPROVER,
        ),
        201,
    )
    assert reduced["decision"] == "REDUCED"
    assert_money_equals(reduced["admin_fee_amount"], 4400.00, "admin_fee_amount")
    assert_money_equals(reduced["total_charge_amount"], 114400.00, "total_charge_amount")
    assert_money_equals(reduced["tax_payback_ratio"], 3.15, "tax_payback_ratio")
    assert_money_equals(reduced["requested_amount"], 116000.00, "requested_amount")

    bid = fixtures.read_bid(bid_z)
    assert bid["status"] == "APPROVED", "a REDUCED verdict advances the bid like APPROVED"
    assert_money_equals(
        bid["approved_incentive_amount"], 110000.00, "approved_incentive_amount"
    )
    assert_money_equals(bid["tax_payback_ratio"], 3.15, "tax_payback_ratio")


def test_approving_one_cent_over_the_cap_returns_incentive_exceeds_cap():
    """8,869.51 against a recomputed cap of 8,869.50 is refused, while 8,869.50
    itself is granted with a 443.48 fee and a 9,312.98 charge.

    PRD: "The `approved_amount` must not exceed the incentive cap **recomputed at decision time** — not the value stored at request time — or the decision fails with `ERR_INCENTIVE_EXCEEDS_CAP`." (PRD S3.7)
    PRD: "The `admin_fee_amount` is the gross multiplied by that rate, rounded half-up to two decimals, and `total_charge_amount` is the gross plus that fee." (PRD S3.7)

    Design: Corner/validations/approving_one_cent_over_the_cap_returns_incentive_exceeds_cap
    """
    scenario = fixtures.setup_bid_incentive_pending(
        clock=CLOCK_2026,
        planner_overrides={"legacy_definite_count": 0, "legacy_definite_room_nights": 0},
        opportunity_overrides={
            "peak_rooms_requested": 500,
            "total_room_nights_requested": 1800,
            "rate_ceiling_amount": 219.00,
        },
        allocations=((0, 500, 214.33, 30),),
        incentive_request_amount=8_869.51,
    )
    fund_id = scenario["fund_id"]
    bid_id = scenario["bid_id"]
    assert fixtures.read_planner(scenario["planner_id"])["tier"] == "TIER_C"
    assert_money_equals(
        scenario["bid"]["incentive_cap_amount"], 8869.50, "incentive_cap_amount"
    )
    assert_money_equals(
        scenario["bid"]["incentive_request_amount"], 8869.51, "incentive_request_amount"
    )

    one_cent_over = api_client.create_incentive_decision(
        bid_id,
        incentive_decision_payload(
            fund_id, "APPROVED", 8_869.51, fixtures.fund_version(fund_id),
            rationale="One cent above the recomputed cap",
        ),
        fixtures.APPROVER,
    )
    validate_error(one_cent_over, ApiErrorId.ERR_INCENTIVE_EXCEEDS_CAP.value, 422)

    exactly_at_the_cap = validate_success(
        api_client.create_incentive_decision(
            bid_id,
            incentive_decision_payload(
                fund_id, "REDUCED", 8_869.50, fixtures.fund_version(fund_id),
                rationale="Exactly at the recomputed cap",
            ),
            fixtures.APPROVER,
        ),
        201,
    )
    assert_money_equals(exactly_at_the_cap["admin_fee_amount"], 443.48, "admin_fee_amount")
    assert_money_equals(
        exactly_at_the_cap["total_charge_amount"], 9312.98, "total_charge_amount"
    )
    assert_money_equals(exactly_at_the_cap["tax_payback_ratio"], 6.35, "tax_payback_ratio")

    fund = fixtures.read_fund(fund_id)
    assert_money_equals(fund["committed_amount"], 9312.98, "committed_amount")
    assert fund["posture"] == "OPEN"


def test_a_second_live_bid_package_returns_bid_round_limit_reached():
    """A `DRAFT` package blocks a second package on the same lead even when the
    second create carries a perfectly fresh opportunity version.

    PRD: "Only one package per lead may be live at a time: the create is refused with `ERR_BID_ROUND_LIMIT_REACHED` and HTTP 409 while any package of that lead is still in status `DRAFT`, `INCENTIVE_PENDING`, `APPROVED` or `SUBMITTED`." (PRD S3.7)
    PRD: "The new package is born in status `DRAFT` with `round_number` 1 and `prepared_by_user_id` set to the acting `X-User-ID`, and it increments the lead's `version` by one." (PRD S3.7)

    Design: Corner/validations/a_second_live_bid_package_returns_bid_round_limit_reached
    """
    scenario = fixtures.setup_lead(clock=CLOCK_2026)
    opportunity_id = scenario["opportunity_id"]
    version_before = fixtures.opportunity_version(opportunity_id)

    first = validate_success(
        api_client.create_bid_package(
            create_bid_package_payload(opportunity_id, version_before), fixtures.SALES
        ),
        201,
    )
    assert first["status"] == "DRAFT"
    assert first["round_number"] == 1

    version_after = fixtures.opportunity_version(opportunity_id)
    assert version_after == version_before + 1, "the create bumps the lead's version"

    second = api_client.create_bid_package(
        create_bid_package_payload(opportunity_id, version_after), fixtures.SALES
    )
    validate_error(second, ApiErrorId.ERR_BID_ROUND_LIMIT_REACHED.value, 409)

    data, meta = validate_paginated(
        api_client.list_bid_packages(
            fixtures.SALES, params={"opportunity_id": opportunity_id}
        )
    )
    assert meta["total_count"] == 1, "the refused create left no second package behind"
    assert data[0]["id"] == first["id"]
    assert data[0]["status"] == "DRAFT"
