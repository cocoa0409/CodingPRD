"""Global ladder precedence and the exact boundary values around it.

Queue A (difficulty index) translations for the
``priority_pair_validation_conflict`` and ``boundary_precision_check`` rules:
three requests that each break two or three rungs of the Section 2.7 ladder at
once, the strict 48-hour turnaround edge, and the strict ten-percent fund
posture line.
"""
from test_helpers import api_client, same_instant, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fund_conservation_identity,
    assert_money_equals,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    create_space_hold_payload,
    incentive_decision_payload,
)
from test_helpers.test_users import (
    INCENTIVE_APPROVER_USER_ID,
    SALES_MANAGER_2_USER_ID,
    make_incentive_approver_headers,
    make_sales_manager_headers,
)
from test_helpers.types import (
    BidPackageStatus,
    FundPosture,
    HoldPosture,
    HoldRank,
    SpaceHoldStatus,
)


# --- priority_pair_validation_conflict ---------------------------------------

def _draft_bid_against_a_small_fund() -> dict:
    """A QUALIFIED lead, a 5000.00 fund and a package still in DRAFT."""
    scenario = fx.setup_lead(fund_overrides={"budget_amount": 5_000.00})
    bid = fx.open_bid(scenario["opportunity_id"])
    scenario["bid_id"] = bid["id"]
    scenario["bid"] = bid
    return scenario


def test_invalid_bid_state_outranks_both_fiscal_gates_on_a_decision(api):
    """Rung 12 answers a call that also breaks rungs 35 and 36.

    PRD: "When a single request violates several rules at once, the answer is
    deterministic: the rule with the lowest position in the following ladder
    wins, and the request carries that rule's error code. The ladder is global"
    (PRD 2.7).
    PRD: "12. The bid package's `status` being a declared from-state --
    `ERR_INVALID_BID_STATE`, 409, on support-letter attachment, incentive
    request, incentive decision, submission and planner response" (PRD 2.7).
    PRD: "35. The approved amount within the recomputed cap --
    `ERR_INCENTIVE_EXCEEDS_CAP` ... 36. The total charge within the fund's
    uncommitted balance -- `ERR_FUND_INSUFFICIENT`" (PRD 2.7).

    Design: Difficulty/priority_pair_validation_conflict/invalid_bid_state_priority_12_outranks_fund_insufficient_priority_36
    """
    scenario = _draft_bid_against_a_small_fund()
    assert scenario["bid"]["status"] == BidPackageStatus.DRAFT.value
    fund_before = fx.read_fund(scenario["fund_id"])

    response = api_client.create_incentive_decision(
        scenario["bid_id"],
        incentive_decision_payload(
            scenario["fund_id"], "APPROVED", 96_000.00, fund_before["version"],
            rationale="Attempt to approve a draft bid far beyond the balance",
        ),
        make_incentive_approver_headers(INCENTIVE_APPROVER_USER_ID),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_BID_STATE.value, 409)
    # A refused call writes nothing at all.
    fund_after = fx.read_fund(scenario["fund_id"])
    assert_money_equals(fund_after["committed_amount"], 0.00, "committed_amount")
    assert fund_after["version"] == fund_before["version"]
    rows, _meta = validate_paginated(
        api_client.list_bid_incentive_decisions(scenario["bid_id"], fx.APPROVER)
    )
    assert rows == []


def test_the_cap_gate_does_surface_once_the_bid_state_gate_is_satisfied(api):
    """With the package legitimately pending, the lowest live rung is 35.

    PRD: "Fourth and last, the result is clamped down to the named fund's
    `uncommitted_amount`, so the cap can never exceed money the fund actually
    still has" (PRD 3.7).
    PRD: "The `approved_amount` must not exceed the incentive cap **recomputed at
    decision time** -- not the value stored at request time -- or the decision
    fails with `ERR_INCENTIVE_EXCEEDS_CAP`" (PRD 3.7).

    Design: Difficulty/priority_pair_validation_conflict/invalid_bid_state_priority_12_outranks_fund_insufficient_priority_36
    """
    scenario = _draft_bid_against_a_small_fund()
    fx.ask_for_incentive(scenario["bid_id"], 96_000.00)

    response = api_client.create_incentive_decision(
        scenario["bid_id"],
        incentive_decision_payload(
            scenario["fund_id"], "APPROVED", 96_000.00,
            fx.fund_version(scenario["fund_id"]),
            rationale="Approval far beyond the residual of a 5000.00 fund",
        ),
        make_incentive_approver_headers(INCENTIVE_APPROVER_USER_ID),
    )

    # The decision-time cap is clamped to the 5000.00 residual, so rung 35 --
    # not rung 36 -- is the lowest rung this request breaks.
    validate_error(response, ApiErrorId.ERR_INCENTIVE_EXCEEDS_CAP.value, 422)
    assert fx.read_bid(scenario["bid_id"])["status"] == (
        BidPackageStatus.INCENTIVE_PENDING.value
    )


def _self_approval_scenario() -> dict:
    """One sales manager prepares AND requests; no block, so coverage is 0.00."""
    scenario = fx.setup_lead()
    preparer = make_sales_manager_headers(SALES_MANAGER_2_USER_ID)
    bid = fx.open_bid(scenario["opportunity_id"], headers=preparer)
    fx.ask_for_incentive(bid["id"], 60_000.00, headers=preparer)
    scenario["bid_id"] = bid["id"]
    scenario["bid"] = fx.read_bid(bid["id"])
    return scenario


def test_segregation_of_duties_outranks_the_incentive_cap_check(api):
    """Rung 15 answers a self-approval that also blows through the cap.

    PRD: "that value must differ from **both** captured identifiers. If it equals
    either one, the decision is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP
    403 -- and, per the ladder in Section 2.7, that refusal happens before any
    cap, balance or payback check is performed" (PRD 2.11).
    PRD: "15. Segregation of duties on the deciding officer --
    `ERR_SEGREGATION_OF_DUTIES`, 403, on incentive-decision creation" (PRD 2.7).

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_priority_15_outranks_incentive_exceeds_cap_priority_35
    """
    scenario = _self_approval_scenario()
    bid = scenario["bid"]
    assert bid["prepared_by_user_id"] == SALES_MANAGER_2_USER_ID
    assert bid["incentive_requested_by_user_id"] == SALES_MANAGER_2_USER_ID
    # min(21600.00 band, 14782.50 yield) * 0.75 coverage factor = 11086.88.
    assert_money_equals(bid["incentive_cap_amount"], 11086.88, "incentive_cap_amount")

    response = api_client.create_incentive_decision(
        scenario["bid_id"],
        incentive_decision_payload(
            scenario["fund_id"], "APPROVED", 60_000.00,
            fx.fund_version(scenario["fund_id"]),
            rationale="Self-approval attempt well above the recomputed cap",
        ),
        make_incentive_approver_headers(SALES_MANAGER_2_USER_ID),
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    after = fx.read_bid(scenario["bid_id"])
    assert after["status"] == BidPackageStatus.INCENTIVE_PENDING.value
    assert after["approved_incentive_amount"] is None


def test_a_different_approver_reaches_the_cap_check_the_duties_gate_hid(api):
    """The same amount from an eligible approver fails on rung 35 instead.

    PRD: "The `approved_amount` must not exceed the incentive cap **recomputed at
    decision time** ... or the decision fails with `ERR_INCENTIVE_EXCEEDS_CAP`"
    (PRD 3.7).
    PRD: "35. The approved amount within the recomputed cap --
    `ERR_INCENTIVE_EXCEEDS_CAP`, 422, on incentive-decision creation" (PRD 2.7).

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_priority_15_outranks_incentive_exceeds_cap_priority_35
    """
    scenario = _self_approval_scenario()

    response = api_client.create_incentive_decision(
        scenario["bid_id"],
        incentive_decision_payload(
            scenario["fund_id"], "APPROVED", 60_000.00,
            fx.fund_version(scenario["fund_id"]),
            rationale="Eligible approver, but the ask still exceeds the ceiling",
        ),
        make_incentive_approver_headers(INCENTIVE_APPROVER_USER_ID),
    )

    validate_error(response, ApiErrorId.ERR_INCENTIVE_EXCEEDS_CAP.value, 422)
    assert fx.read_bid(scenario["bid_id"])["status"] == (
        BidPackageStatus.INCENTIVE_PENDING.value
    )


OVERSIZED_LEAD = {
    "event_name": "Global Manufacturing Expo 2028",
    "arrival_date": "2028-04-10",
    "departure_date": "2028-04-12",
    "peak_rooms_requested": 2_000,
    "total_room_nights_requested": 3_600,
    "attendance_estimate": 20_000,
    "exhibit_sqft_requested": 400_000,
    "rate_ceiling_amount": 229.00,
}


def _hall_with_both_options_sold() -> dict:
    """Grand Hall A carrying a FIRST and a SECOND hold, plus an oversized lead C."""
    scenario = fx.setup_lead()
    hall_id = scenario["hall_id"]
    hold_a = fx.place_hold(scenario["opportunity_id"], hall_id)

    lead_b = fx.qualify_lead(
        fx.create_lead(
            scenario["planner_id"], event_name="Coastal Dentistry Forum 2028"
        )["id"]
    )
    hold_b = fx.place_hold(lead_b["id"], hall_id)

    lead_c = fx.qualify_lead(
        fx.create_lead(scenario["planner_id"], **dict(OVERSIZED_LEAD))["id"]
    )
    scenario["hold_a"] = hold_a
    scenario["hold_b"] = hold_b
    scenario["lead_c_id"] = lead_c["id"]
    return scenario


def test_the_hold_limit_outranks_the_hall_capacity_check(api):
    """Rung 22 answers a third hold that is also far too big for the hall.

    PRD: "if the blocking set contains two or more holds, the hall has already
    sold both of the options it offers on that window and the request is refused
    with `ERR_HALL_HOLD_LIMIT_REACHED` -- the center sells a first option and a
    second option on any buffered window and nothing beyond" (PRD 3.3).
    PRD: "22. Fewer than the permitted number of live holds already conflicting --
    `ERR_HALL_HOLD_LIMIT_REACHED`, 409 ... 25. The hall being large enough for the
    event -- `ERR_HALL_CAPACITY_INSUFFICIENT`, 422" (PRD 2.7).

    Design: Difficulty/priority_pair_validation_conflict/hall_hold_limit_priority_22_outranks_hall_capacity_insufficient_priority_25
    """
    scenario = _hall_with_both_options_sold()
    assert scenario["hold_a"]["hold_rank"] == HoldRank.FIRST.value
    assert scenario["hold_b"]["hold_rank"] == HoldRank.SECOND.value

    response = api_client.create_space_hold(
        create_space_hold_payload(
            scenario["lead_c_id"], scenario["hall_id"],
            move_in_start="2028-04-09T00:00:00Z",
            move_out_end="2028-04-14T00:00:00Z",
        ),
        fx.SCHEDULER,
    )

    validate_error(response, ApiErrorId.ERR_HALL_HOLD_LIMIT_REACHED.value, 409)
    rows, _meta = validate_paginated(
        api_client.list_space_holds(
            fx.SCHEDULER, params={"center_hall_id": scenario["hall_id"]}
        )
    )
    assert {row["id"] for row in rows} == {
        scenario["hold_a"]["id"], scenario["hold_b"]["id"]
    }
    assert fx.read_opportunity(scenario["lead_c_id"])["hold_posture"] == (
        HoldPosture.NONE.value
    )


def test_the_capacity_gate_surfaces_on_a_window_the_hold_limit_leaves_alone(api):
    """The same oversized lead on a free window fails on rung 25 instead.

    PRD: "the hall must be big enough for the event on both dimensions: the lead's
    `attendance_estimate` must not exceed the hall's `capacity_persons`, and its
    `exhibit_sqft_requested` must not exceed the hall's `exhibit_sqft`. A failure
    of either dimension is reported as `ERR_HALL_CAPACITY_INSUFFICIENT` with HTTP
    422" (PRD 3.3).
    PRD: "two holds on one hall must be separated by at least the buffer between
    one hold's `move_out_end` and the next hold's `move_in_start`" (PRD 3.3).

    Design: Difficulty/priority_pair_validation_conflict/hall_hold_limit_priority_22_outranks_hall_capacity_insufficient_priority_25
    """
    scenario = _hall_with_both_options_sold()

    response = api_client.create_space_hold(
        create_space_hold_payload(
            scenario["lead_c_id"], scenario["hall_id"],
            move_in_start="2028-06-01T00:00:00Z",
            move_out_end="2028-06-04T00:00:00Z",
        ),
        fx.SCHEDULER,
    )

    # Seven weeks clear of the incumbents, so rung 22 is not in play at all.
    validate_error(response, ApiErrorId.ERR_HALL_CAPACITY_INSUFFICIENT.value, 422)
    rows, _meta = validate_paginated(
        api_client.list_space_holds(
            fx.SCHEDULER, params={"center_hall_id": scenario["hall_id"]}
        )
    )
    assert len(rows) == 2


# --- boundary_precision_check ------------------------------------------------

def _twin_halls_with_incumbents() -> dict:
    """Two identical 48h halls, each already carrying one FIRST-rank incumbent."""
    scenario = fx.setup_lead()
    hall_a_id = scenario["hall_id"]
    hall_b_id = fx.register_hall(name="Grand Hall B")["id"]
    incumbent_a = fx.place_hold(scenario["opportunity_id"], hall_a_id)

    lead_b = fx.qualify_lead(
        fx.create_lead(scenario["planner_id"], event_name="Coastal Dentistry Forum 2028")["id"]
    )
    incumbent_b = fx.place_hold(lead_b["id"], hall_b_id)

    probe_exact = fx.qualify_lead(
        fx.create_lead(scenario["planner_id"], event_name="Exact Gap Probe 2028")["id"]
    )
    probe_short = fx.qualify_lead(
        fx.create_lead(scenario["planner_id"], event_name="Short Gap Probe 2028")["id"]
    )
    return {
        "hall_a_id": hall_a_id,
        "hall_b_id": hall_b_id,
        "incumbent_a": incumbent_a,
        "incumbent_b": incumbent_b,
        "probe_exact_id": probe_exact["id"],
        "probe_short_id": probe_short["id"],
    }


def test_a_gap_of_exactly_the_turnaround_buffer_clears_the_conflict_test(api):
    """Move-in exactly 48h after the incumbent's move-out ranks FIRST.

    PRD: "Because both comparisons are strict, exact adjacency at the buffer edge
    is permitted -- a candidate whose `move_in_start` falls exactly at an existing
    hold's `move_out_end` plus the buffer does not conflict with it. Instants are
    compared at millisecond resolution. A hall with the default 48-hour turnaround
    therefore accepts a move-in exactly two days after the previous show's
    move-out" (PRD 3.3).
    PRD: "the hold is created in status `HELD`, with `hold_rank` set to `FIRST`
    when the blocking set was empty" (PRD 3.3).

    Design: Difficulty/boundary_precision_check/hall_turnaround_buffer_allows_exactly_48h_gap_and_rejects_47h
    """
    ctx = _twin_halls_with_incumbents()
    assert ctx["incumbent_a"]["hold_rank"] == HoldRank.FIRST.value
    assert same_instant(ctx["incumbent_a"]["move_out_end"], "2028-04-13T00:00:00Z")

    # 2028-04-13T00:00:00Z + 48h, to the instant.
    exact = fx.place_hold(
        ctx["probe_exact_id"], ctx["hall_a_id"],
        move_in_start="2028-04-15T00:00:00Z", move_out_end="2028-04-20T00:00:00Z",
    )

    assert exact["hold_rank"] == HoldRank.FIRST.value
    assert exact["status"] == SpaceHoldStatus.HELD.value
    assert fx.read_opportunity(ctx["probe_exact_id"])["hold_posture"] == (
        HoldPosture.TENTATIVE.value
    )
    seconds, _meta = validate_paginated(
        api_client.list_space_holds(
            fx.SCHEDULER,
            params={"center_hall_id": ctx["hall_a_id"],
                    "hold_rank": HoldRank.SECOND.value},
        )
    )
    assert seconds == []


def test_one_hour_inside_the_turnaround_buffer_still_conflicts(api):
    """Move-in 47h after the incumbent's move-out is queued as the second option.

    PRD: "two holds on the same hall conflict when, and only when, both of the
    following hold simultaneously: the first hold's `move_in_start` pulled back by
    the buffer is strictly earlier than the second hold's `move_out_end`, **and**
    the second hold's `move_in_start` pulled back by the buffer is strictly earlier
    than the first hold's `move_out_end`" (PRD 3.3) -- and it "rejects one an
    instant earlier" (PRD 3.3).
    PRD: "`hold_rank` set to ... `SECOND` when it contained exactly one hold" and
    "Creating a `SECOND`-rank hold leaves `hold_posture` exactly as it was; being
    somebody's backup is not a tentative booking" (PRD 3.3).

    Design: Difficulty/boundary_precision_check/hall_turnaround_buffer_allows_exactly_48h_gap_and_rejects_47h
    """
    ctx = _twin_halls_with_incumbents()

    short = fx.place_hold(
        ctx["probe_short_id"], ctx["hall_b_id"],
        move_in_start="2028-04-14T23:00:00Z", move_out_end="2028-04-20T00:00:00Z",
    )

    assert short["hold_rank"] == HoldRank.SECOND.value
    assert short["status"] == SpaceHoldStatus.HELD.value
    assert fx.read_opportunity(ctx["probe_short_id"])["hold_posture"] == (
        HoldPosture.NONE.value
    )
    assert short["id"] != ctx["incumbent_b"]["id"]
    seconds, _meta = validate_paginated(
        api_client.list_space_holds(
            fx.SCHEDULER,
            params={"center_hall_id": ctx["hall_b_id"],
                    "hold_rank": HoldRank.SECOND.value},
        )
    )
    assert [row["id"] for row in seconds] == [short["id"]]


SMALL_LEAD = {
    "event_name": "Small Regional Seminar 2028",
    "arrival_date": "2028-05-10",
    "departure_date": "2028-05-12",
    "peak_rooms_requested": 120,
    "total_room_nights_requested": 200,
    "attendance_estimate": 500,
    "exhibit_sqft_requested": 10_000,
    "rate_ceiling_amount": 200.00,
}


def _fund_left_exactly_on_the_ten_percent_line() -> dict:
    """A 10500.00 fund charged 9450.00, leaving exactly 1050.00 uncommitted."""
    scenario = fx.setup_lead(fund_overrides={"budget_amount": 10_500.00})
    bid = fx.open_bid(scenario["opportunity_id"])
    requested = fx.ask_for_incentive(bid["id"], 9_000.00)
    decision = fx.decide_incentive(
        bid["id"], scenario["fund_id"], "APPROVED", 9_000.00,
        rationale="Charge that lands the fund exactly on the ten percent line",
    )
    scenario["bid_one_id"] = bid["id"]
    scenario["cap_one"] = requested["incentive_cap_amount"]
    scenario["decision_one"] = decision
    return scenario


def test_the_fund_stays_open_at_exactly_ten_percent_uncommitted(api):
    """A residual of exactly 1050.00 of 10500.00 is still OPEN.

    PRD: "When it is strictly greater than zero but strictly less than ten percent
    of `budget_amount`, the posture is `CONSTRAINED`; the boundary is strict, so a
    residual exactly equal to ten percent of the budget leaves the posture `OPEN`"
    (PRD 2.10).
    PRD: "Select the administrative fee rate from **that gross figure only**: 0.05
    when the gross is below 100,000.00 ... The `admin_fee_amount` is the gross
    multiplied by that rate, rounded half-up to two decimals, and
    `total_charge_amount` is the gross plus that fee ... Finally `tax_payback_ratio`
    is the newest `PROVISIONAL` estimate's `lodging_tax_yield_amount` divided by
    `total_charge_amount`, rounded half-up to two decimals" (PRD 3.7).

    Design: Difficulty/boundary_precision_check/fund_posture_holds_open_at_exactly_ten_percent_and_flips_one_charge_later
    """
    scenario = _fund_left_exactly_on_the_ten_percent_line()

    # min(21600.00 band, 14782.50 yield) * 0.75 coverage factor = 11086.88.
    assert_money_equals(scenario["cap_one"], 11086.88, "incentive_cap_amount")
    decision = scenario["decision_one"]
    assert_money_equals(decision["admin_fee_amount"], 450.00, "admin_fee_amount")
    assert_money_equals(decision["total_charge_amount"], 9450.00, "total_charge_amount")
    assert_money_equals(decision["tax_payback_ratio"], 6.26, "tax_payback_ratio")

    fund = fx.read_fund(scenario["fund_id"])
    assert_money_equals(fund["uncommitted_amount"], 1050.00, "uncommitted_amount")
    # 1050.00 is not strictly below 1050.00, so the band does not open.
    assert fund["posture"] == FundPosture.OPEN.value
    assert_fund_conservation_identity(fund)


def test_one_further_charge_tips_the_fund_into_constrained(api):
    """105.00 more takes the residual to 945.00 and flips the posture.

    PRD: "The fund's `posture` is derived from that residual and is recomputed
    after any change to `committed_amount`, `disbursed_amount` or `budget_amount`
    ... When it is strictly greater than zero but strictly less than ten percent of
    `budget_amount`, the posture is `CONSTRAINED`" (PRD 2.10).
    PRD: "Fourth and last, the result is clamped down to the named fund's
    `uncommitted_amount` ... That final clamp is skipped when the cap is computed
    at request time, because no fund has been named yet; it applies when the cap is
    recomputed at decision time against the fund the approver names" (PRD 3.7).

    Design: Difficulty/boundary_precision_check/fund_posture_holds_open_at_exactly_ten_percent_and_flips_one_charge_later
    """
    scenario = _fund_left_exactly_on_the_ten_percent_line()
    second_lead = fx.qualify_lead(
        fx.create_lead(scenario["planner_id"], **dict(SMALL_LEAD))["id"]
    )
    bid_two = fx.open_bid(second_lead["id"])
    requested = fx.ask_for_incentive(bid_two["id"], 100.00)

    # min(2400.00 band, 1500.00 yield) * 0.75 = 1125.00; no fund named yet, so the
    # 1050.00 residual does not clamp it here.
    assert_money_equals(requested["incentive_cap_amount"], 1125.00, "request-time cap")

    decision = fx.decide_incentive(
        bid_two["id"], scenario["fund_id"], "APPROVED", 100.00,
        rationale="Small charge that tips the fund over the line",
    )

    # The decision-time cap is min(1125.00, 1050.00) = 1050.00, still above 100.00.
    assert_money_equals(decision["admin_fee_amount"], 5.00, "admin_fee_amount")
    assert_money_equals(decision["total_charge_amount"], 105.00, "total_charge_amount")
    assert_money_equals(decision["tax_payback_ratio"], 57.14, "tax_payback_ratio")

    fund = fx.read_fund(scenario["fund_id"])
    assert_money_equals(fund["committed_amount"], 9_555.00, "committed_amount")
    assert_money_equals(fund["uncommitted_amount"], 945.00, "uncommitted_amount")
    assert fund["posture"] == FundPosture.CONSTRAINED.value
    assert_fund_conservation_identity(fund)
