"""Derived-figure arithmetic: hearing priority scoring and pay-claim money.

Every test in this module exercises one computed quantity the PRD pins down with
an exact value — the clamped priority score and its class ladder (PRD §3.5), the
rate schedule selected by the hearing date (PRD §3.7, §3.8), the remote delivery
multiplier and the travel cliff (PRD §3.8), the quarter-hour round-up together
with round-half-up on whole cents (PRD §2.8, §3.8), and the live-row filter that
decides an interval conflict (PRD §3.6).

The server is relaunched before every test, so each test builds its own world.
"""

from test_helpers import (
    ApiErrorId,
    assert_courthouse_ledger_invariants,
    assert_pay_components_sum,
    create_assignment_payload,
    make_interpreter_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
import test_helpers.fixtures as fixtures


# ---------------------------------------------------------------------------
# Hearing priority scoring (PRD §3.5)
# ---------------------------------------------------------------------------
def test_priority_score_is_clamped_to_one_hundred_for_a_rare_in_custody_arraignment(api):
    """PRD §3.5: "First, a **type weight** taken from the event type: an arraignment scores 50, a detention review 45, a trial 40, a plea 30, a sentencing 30, a motion 20, and a civil motion 10."
    PRD §3.5: "Second, a **custody bonus** of 25 points added when `in_custody` is true and nothing added when it is false."
    PRD §3.5: "Third, a **rarity bonus** taken from the needed language's `tier_class`: 15 points for a `RARE` language, 5 points for a `NON_DESIGNATED` one, and 0 for a `DESIGNATED` one."
    PRD §3.5: "Fifth, an **urgency term**: start from 20 points, subtract 2 points for each whole day of `lead_time_days`, and treat any negative result as 0 — so a hearing 10 or more days out contributes no urgency at all while one starting the same day contributes the full 20."
    PRD §3.5: "Add the type weight, the custody bonus, the rarity bonus and the urgency term, then cap the sum at 100; the result is `priority_score`."

    Design: Corner/Calculations/priority_score_clamps_at_one_hundred_and_class_b_floor_is_inclusive_at_fifty_five
    """
    config = fixtures.setup_program_config(
        with_rare_language=True, with_rate_schedule=False
    )
    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["rare_language"]["id"],
        case_number="CR-2026-1001",
        hearing_type="ARRAIGNMENT",
        in_custody=True,
        scheduled_start="2026-08-01T09:00:00.000Z",
        scheduled_end="2026-08-01T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )

    assert hearing["lead_time_days"] == 0, (
        f"expected lead_time_days 0 for a hearing nine hours out, got "
        f"{hearing['lead_time_days']}"
    )
    assert hearing["priority_score"] == 100, (
        f"expected the raw sum 50+25+15+20=110 to be capped at 100, got "
        f"{hearing['priority_score']}"
    )
    assert hearing["priority_class"] == "A", (
        f"expected priority_class A at score 100, got {hearing['priority_class']}"
    )
    assert hearing["status"] == "SCHEDULED", (
        f"expected a freshly placed hearing to be SCHEDULED, got {hearing['status']}"
    )
    assert hearing["continuance_count"] == 0, (
        f"expected continuance_count 0 on creation, got {hearing['continuance_count']}"
    )


def test_priority_class_b_floor_is_inclusive_at_a_score_of_exactly_fifty_five(api):
    """PRD §3.5: "Fourth, a **lead-time figure** stored on the row as `lead_time_days`: take the difference between `scheduled_start` and the logical clock at the moment of creation, express it in whole days by discarding any remaining fraction of a day, and then treat any negative result as 0."
    PRD §3.5: "From it the program derives `priority_class`: `A` when `priority_score` is 80 or more, `B` when it is 55 or more but below 80, and `C` otherwise."
    PRD §3.5: "Both boundaries are inclusive at the floor, so a score of exactly 80 is class `A` and a score of exactly 55 is class `B`."

    Design: Corner/Calculations/priority_score_clamps_at_one_hundred_and_class_b_floor_is_inclusive_at_fifty_five
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-1002",
        hearing_type="PLEA",
        in_custody=True,
        scheduled_start="2026-09-15T09:00:00.000Z",
        scheduled_end="2026-09-15T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )

    assert hearing["lead_time_days"] == 45, (
        f"expected 45 whole days between 2026-08-01T00:00Z and 2026-09-15T09:00Z, "
        f"got {hearing['lead_time_days']}"
    )
    assert hearing["priority_score"] == 55, (
        f"expected 30 (plea) + 25 (custody) + 0 (designated) + 0 (urgency) == 55, "
        f"got {hearing['priority_score']}"
    )
    assert hearing["priority_class"] == "B", (
        f"expected a score of exactly 55 to be class B, got {hearing['priority_class']}"
    )
    assert hearing["status"] == "SCHEDULED", (
        f"expected a freshly placed hearing to be SCHEDULED, got {hearing['status']}"
    )


def test_priority_class_drops_to_c_one_point_under_the_class_b_floor(api):
    """PRD §3.5: "Fifth, an **urgency term**: start from 20 points, subtract 2 points for each whole day of `lead_time_days`, and treat any negative result as 0 — so a hearing 10 or more days out contributes no urgency at all while one starting the same day contributes the full 20."
    PRD §3.5: "From it the program derives `priority_class`: `A` when `priority_score` is 80 or more, `B` when it is 55 or more but below 80, and `C` otherwise."

    Design: Corner/Calculations/priority_score_clamps_at_one_hundred_and_class_b_floor_is_inclusive_at_fifty_five
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-1003",
        hearing_type="TRIAL",
        in_custody=False,
        scheduled_start="2026-08-04T09:00:00.000Z",
        scheduled_end="2026-08-04T12:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )

    assert hearing["lead_time_days"] == 3, (
        f"expected 3 whole days (the extra nine hours are discarded), got "
        f"{hearing['lead_time_days']}"
    )
    assert hearing["priority_score"] == 54, (
        f"expected 40 (trial) + 0 (no custody) + 0 (designated) + 14 (urgency) == 54, "
        f"got {hearing['priority_score']}"
    )
    assert hearing["priority_class"] == "C", (
        f"expected a score of 54 to fall to class C, got {hearing['priority_class']}"
    )
    assert hearing["continuance_count"] == 0, (
        f"expected continuance_count 0 on creation, got {hearing['continuance_count']}"
    )


# ---------------------------------------------------------------------------
# Rate-schedule pinning (PRD §3.7, §3.8)
# ---------------------------------------------------------------------------
def test_pay_claim_pins_the_schedule_effective_on_the_hearing_date_not_the_newest_one(
    api, program_admin_headers, fiscal_officer_headers
):
    """PRD §3.7: "Exactly one rate schedule must be in effect for the date part of the hearing's `scheduled_start` — its `effective_from` at or before that date, and either a null `effective_through` or an `effective_through` at or on that date — and if none is, confirmation is refused with `ERR_RATE_SCHEDULE_NOT_EFFECTIVE`."
    PRD §3.7: "That schedule's `id` is pinned onto a freshly created pay claim as `rate_schedule_id`, and a schedule published later never changes an existing claim."
    PRD §3.8: "Every variant reads exactly one assignment, that assignment's hearing, that hearing's language, and the rate schedule pinned on the claim — nothing else, and never a rate schedule published afterwards."
    PRD §3.8: "Then take the larger of that rounded figure and the rate schedule's `minimum_call_hours`; the result is `billable_hours`, always a multiple of 0.25 and always carried to two decimal places."
    PRD §3.1: "Rate schedules are readable by list, optionally restricted to the single schedule in effect on a given date supplied as `effective_on`, and by direct fetch."

    Design: Corner/Calculations/pay_claim_pins_the_rate_schedule_effective_on_the_hearing_date_not_the_newest_one
    """
    config = fixtures.setup_program_config(
        rate_overrides={"effective_through": "2026-08-31", "certified_hourly_cents": 8750}
    )
    rs1 = config["rate_schedule"]
    rostered = fixtures.setup_active_interpreter(config["language"]["id"])
    interpreter = rostered["interpreter"]

    hearing_august = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-1101",
        hearing_type="MOTION",
        in_custody=False,
        scheduled_start="2026-08-25T09:00:00.000Z",
        scheduled_end="2026-08-25T10:00:00.000Z",
    )
    assignment_august = fixtures.propose_assignment(
        hearing_august["id"], interpreter["id"]
    )
    fixtures.confirm_assignment(assignment_august["id"], interpreter["id"])
    claim_august = fixtures.pay_claim_for_assignment(assignment_august["id"])

    assert claim_august["rate_schedule_id"] == rs1["id"], (
        f"expected the August claim pinned to the January schedule {rs1['id']}, got "
        f"{claim_august['rate_schedule_id']}"
    )
    assert claim_august["billable_hours"] == 2.00, (
        f"expected a one-hour hearing lifted to the 2.0-hour minimum call, got "
        f"{claim_august['billable_hours']}"
    )
    assert claim_august["provisional_total_cents"] == 17500, (
        f"expected 2.00 x 8750 == 17500, got {claim_august['provisional_total_cents']}"
    )

    # A newer schedule governing September only.
    rs2 = fixtures.bootstrap_rate_schedule(
        effective_from="2026-09-01",
        master_hourly_cents=11000,
        certified_hourly_cents=9000,
        registered_hourly_cents=6700,
        provisional_hourly_cents=5000,
        travel_mileage_rate_cents=70.0,
    )

    hearing_september = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-1102",
        hearing_type="MOTION",
        in_custody=False,
        scheduled_start="2026-09-15T09:00:00.000Z",
        scheduled_end="2026-09-15T10:00:00.000Z",
    )
    assignment_september = fixtures.propose_assignment(
        hearing_september["id"], interpreter["id"]
    )
    fixtures.confirm_assignment(assignment_september["id"], interpreter["id"])
    claim_september = fixtures.pay_claim_for_assignment(assignment_september["id"])

    assert claim_september["rate_schedule_id"] == rs2["id"], (
        f"expected the September claim pinned to the September schedule {rs2['id']}, "
        f"got {claim_september['rate_schedule_id']}"
    )
    assert claim_september["provisional_total_cents"] == 18000, (
        f"expected 2.00 x 9000 == 18000 even though the clock never left 2026-08-01, "
        f"got {claim_september['provisional_total_cents']}"
    )

    reread_august = fixtures.read_pay_claim(claim_august["id"])
    assert reread_august["rate_schedule_id"] == rs1["id"], (
        "publishing a later schedule must not repoint an existing claim, got "
        f"{reread_august['rate_schedule_id']}"
    )
    assert reread_august["provisional_total_cents"] == 17500, (
        f"expected the August claim to stay at 17500, got "
        f"{reread_august['provisional_total_cents']}"
    )

    for on_date, expected_id in (("2026-09-15", rs2["id"]), ("2026-08-25", rs1["id"])):
        rows, meta = validate_paginated(
            api.list_rate_schedules(program_admin_headers, {"effective_on": on_date})
        )
        assert meta["total_count"] == 1, (
            f"expected exactly one schedule in effect on {on_date}, got "
            f"{meta['total_count']}"
        )
        assert rows[0]["id"] == expected_id, (
            f"expected schedule {expected_id} in effect on {on_date}, got {rows[0]['id']}"
        )

    courthouse = validate_success(
        api.get_courthouse(config["courthouse"]["id"], fiscal_officer_headers)
    )
    assert courthouse["encumbered_pay_cents"] == 35500, (
        f"expected 17500 + 18000 == 35500 encumbered, got "
        f"{courthouse['encumbered_pay_cents']}"
    )
    assert courthouse["available_pay_cents"] == 4964500, (
        f"expected 5000000 - 35500 == 4964500 available, got "
        f"{courthouse['available_pay_cents']}"
    )
    assert_courthouse_ledger_invariants(courthouse)


# ---------------------------------------------------------------------------
# Delivery multiplier and the travel cliff (PRD §3.8)
# ---------------------------------------------------------------------------
def test_remote_multiplier_discounts_the_service_component_and_suppresses_travel(
    api, fiscal_officer_headers
):
    """PRD §3.8: "Select the hourly rate by the assignment's `credential_tier_snapshot`: `master_hourly_cents` for a `MASTER` snapshot, `certified_hourly_cents` for `CERTIFIED`, `registered_hourly_cents` for `REGISTERED`, and `provisional_hourly_cents` for `PROVISIONAL`."
    PRD §3.8: "Select the delivery multiplier by the assignment's `delivery_mode`: exactly 1 for `IN_PERSON`, and the schedule's `remote_rate_multiplier` for both `VRI` and `TELEPHONIC`."
    PRD §3.8: "Multiply `billable_hours` by the selected hourly rate and then by the multiplier, and round the product to whole cents half up; that is `service_cents`."
    PRD §3.8: "If the assignment's `delivery_mode` is anything other than `IN_PERSON`, or if the variant's one-way mileage is at or below the schedule's `travel_free_radius_miles`, the reimbursable mileage is 0."
    PRD §3.8: "For any language that is not `RARE`, `rare_premium_cents` is 0."
    PRD §3.7: "The claim is created in `ENCUMBERED` status with `variant` set to `PROVISIONAL` and its `provisional_total_cents` computed by the provisional arithmetic of §3.8; the courthouse's `encumbered_pay_cents` and `available_pay_cents` are recomputed; the hearing bubbles `SCHEDULED → COVERED`; and the assignment's `version` is incremented by 1."

    Design: Corner/Calculations/remote_multiplier_discounts_the_service_component_and_suppresses_travel_entirely
    """
    config = fixtures.setup_program_config()
    rostered = fixtures.setup_active_interpreter(config["language"]["id"])
    interpreter = rostered["interpreter"]

    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-1201",
        hearing_type="MOTION",
        in_custody=False,
        scheduled_start="2026-08-25T09:00:00.000Z",
        scheduled_end="2026-08-25T10:00:00.000Z",
        requested_delivery_mode="VRI",
    )
    assignment = fixtures.propose_assignment(
        hearing["id"],
        interpreter["id"],
        delivery_mode="VRI",
        estimated_one_way_miles=40.0,
    )
    assert assignment["credential_tier_snapshot"] == "CERTIFIED", (
        "expected the CERTIFIED credential pinned on the assignment, got "
        f"{assignment['credential_tier_snapshot']}"
    )

    confirmed = validate_success(
        api.confirm_assignment(
            assignment["id"], make_interpreter_headers(interpreter["id"])
        )
    )
    assert confirmed["service_status"] == "CONFIRMED", (
        f"expected CONFIRMED after acceptance, got {confirmed['service_status']}"
    )

    claim = fixtures.pay_claim_for_assignment(assignment["id"])
    assert claim["billable_hours"] == 2.00, (
        f"expected the 2.0-hour minimum call, got {claim['billable_hours']}"
    )
    assert claim["service_cents"] == 15750, (
        f"expected 2.00 x 8750 x 0.90 == 15750, got {claim['service_cents']}"
    )
    assert claim["travel_cents"] == 0, (
        "expected travel suppressed entirely by the VRI delivery mode despite 40.0 "
        f"one-way miles, got {claim['travel_cents']}"
    )
    assert claim["rare_premium_cents"] == 0, (
        f"expected no rare premium for a DESIGNATED language, got "
        f"{claim['rare_premium_cents']}"
    )
    assert claim["variant"] == "PROVISIONAL", (
        f"expected variant PROVISIONAL at confirmation, got {claim['variant']}"
    )
    assert claim["status"] == "ENCUMBERED", (
        f"expected status ENCUMBERED at confirmation, got {claim['status']}"
    )
    assert claim["provisional_total_cents"] == 15750, (
        f"expected 15750 + 0 + 0 == 15750, got {claim['provisional_total_cents']}"
    )
    assert_pay_components_sum(claim, "provisional_total_cents")

    courthouse = validate_success(
        api.get_courthouse(config["courthouse"]["id"], fiscal_officer_headers)
    )
    assert courthouse["encumbered_pay_cents"] == 15750, (
        f"expected 15750 encumbered, got {courthouse['encumbered_pay_cents']}"
    )
    assert courthouse["obligated_pay_cents"] == 0, (
        f"expected nothing obligated before completion, got "
        f"{courthouse['obligated_pay_cents']}"
    )
    assert courthouse["available_pay_cents"] == 4984250, (
        f"expected 5000000 - 15750 == 4984250, got {courthouse['available_pay_cents']}"
    )

    assert fixtures.read_hearing(hearing["id"])["status"] == "COVERED", (
        "expected the hearing to bubble SCHEDULED -> COVERED on confirmation"
    )


# ---------------------------------------------------------------------------
# Quarter-hour round-up and round-half-up on whole cents (PRD §2.8, §3.8)
# ---------------------------------------------------------------------------
def test_one_extra_minute_buys_a_whole_quarter_hour_and_lands_on_a_half_cent(
    api, fiscal_officer_headers
):
    """PRD §3.8: "The `FINAL` variant measures the *served* window, from the assignment's `check_in_utc` up to but not including its `actual_end_utc`, and takes its mileage from `actual_one_way_miles`."
    PRD §3.8: "Multiply that figure by four, round the product *up* to the next whole number, and divide by four again — the effect is that any part-used quarter hour is billed as a whole quarter hour."
    PRD §2.8: "Each monetary component of a claim — the service component, the rare-language premium, and the travel reimbursement — is rounded to whole cents using **round half up** (a value ending in exactly half a cent rounds away from zero) **before** the three components are summed."
    PRD §3.8: "The `PROVISIONAL` variant writes that total to `provisional_total_cents`; the `FINAL` and `LATE_CANCELLATION` variants write it to `final_total_cents` and leave `provisional_total_cents` frozen at whatever the provisional run produced."
    PRD §3.7: "For a rostered interpreter, completion also settles the money: the pay claim moves `ENCUMBERED → FINALIZED` with `variant` set to `FINAL` and `final_total_cents` computed by the final arithmetic of §3.8, the courthouse's `encumbered_pay_cents`, `obligated_pay_cents` and `available_pay_cents` are all recomputed, and the interpreter's `pending_pay_cents` is recomputed to include the newly finalized amount."

    Design: Corner/Calculations/quarter_hour_round_up_and_half_cent_round_half_up_on_a_ragged_served_window
    """
    config = fixtures.setup_program_config()
    rostered = fixtures.setup_active_interpreter(config["language"]["id"])
    interpreter = rostered["interpreter"]

    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-1301",
        hearing_type="MOTION",
        in_custody=False,
        scheduled_start="2026-08-25T09:00:00.000Z",
        scheduled_end="2026-08-25T12:00:00.000Z",
    )
    assignment = fixtures.propose_assignment(
        hearing["id"], interpreter["id"], estimated_one_way_miles=10.0
    )
    fixtures.confirm_assignment(assignment["id"], interpreter["id"])

    provisional = fixtures.pay_claim_for_assignment(assignment["id"])
    assert provisional["billable_hours"] == 3.00, (
        f"expected the scheduled three-hour window to need no rounding, got "
        f"{provisional['billable_hours']}"
    )
    assert provisional["provisional_total_cents"] == 26250, (
        f"expected 3.00 x 8750 == 26250, got {provisional['provisional_total_cents']}"
    )

    fixtures.set_clock("2026-08-25T09:00:00Z")
    checked_in = fixtures.check_in_assignment(assignment["id"], interpreter["id"])
    assert checked_in["check_in_utc"] == "2026-08-25T09:00:00.000Z", (
        f"expected check_in_utc at the logical clock instant, got "
        f"{checked_in['check_in_utc']}"
    )

    completed = fixtures.complete_assignment(
        assignment["id"],
        interpreter["id"],
        actual_end_utc="2026-08-25T12:01:00.000Z",
        one_way_miles=10.0,
    )
    assert completed["service_status"] == "COMPLETED", (
        f"expected COMPLETED after completion, got {completed['service_status']}"
    )
    assert completed["actual_end_utc"] == "2026-08-25T12:01:00.000Z", (
        f"expected the reported end instant stored verbatim, got "
        f"{completed['actual_end_utc']}"
    )
    assert completed["actual_one_way_miles"] == 10.0, (
        f"expected actual_one_way_miles 10.0, got {completed['actual_one_way_miles']}"
    )

    final = fixtures.read_pay_claim(provisional["id"])
    assert final["billable_hours"] == 3.25, (
        "expected 3.01666.. served hours rounded UP to 3.25, got "
        f"{final['billable_hours']}"
    )
    assert final["service_cents"] == 28438, (
        f"expected 3.25 x 8750 == 28437.5 resolved half up to 28438, got "
        f"{final['service_cents']}"
    )
    assert final["travel_cents"] == 0, (
        f"expected no travel inside the 30.0-mile free radius, got {final['travel_cents']}"
    )
    assert final["rare_premium_cents"] == 0, (
        f"expected no rare premium for a DESIGNATED language, got "
        f"{final['rare_premium_cents']}"
    )
    assert final["final_total_cents"] == 28438, (
        f"expected 28438 + 0 + 0 == 28438, got {final['final_total_cents']}"
    )
    assert final["variant"] == "FINAL", (
        f"expected variant FINAL after completion, got {final['variant']}"
    )
    assert final["status"] == "FINALIZED", (
        f"expected status FINALIZED after completion, got {final['status']}"
    )
    assert final["late_cancellation"] is False, (
        "expected late_cancellation false on a served appearance"
    )
    assert final["provisional_total_cents"] == 26250, (
        "expected provisional_total_cents frozen at 26250, got "
        f"{final['provisional_total_cents']}"
    )
    assert_pay_components_sum(final, "final_total_cents")

    courthouse = validate_success(
        api.get_courthouse(config["courthouse"]["id"], fiscal_officer_headers)
    )
    assert courthouse["encumbered_pay_cents"] == 0, (
        f"expected the encumbrance released, got {courthouse['encumbered_pay_cents']}"
    )
    assert courthouse["obligated_pay_cents"] == 28438, (
        f"expected 28438 obligated, got {courthouse['obligated_pay_cents']}"
    )
    assert courthouse["available_pay_cents"] == 4971562, (
        f"expected 5000000 - 28438 == 4971562, got {courthouse['available_pay_cents']}"
    )

    assert fixtures.read_interpreter(interpreter["id"])["pending_pay_cents"] == 28438, (
        "expected the interpreter's pending_pay_cents recomputed to 28438"
    )


# ---------------------------------------------------------------------------
# The live-row filter behind an interval conflict (PRD §3.6)
# ---------------------------------------------------------------------------
def _three_overlapping_motion_hearings(courthouse_id, language_id):
    """H1 09:00-10:00, H2 09:30-10:30 and H3 10:00-11:00 on 2026-08-25."""
    windows = (
        ("CR-2026-1401", "09:00", "10:00"),
        ("CR-2026-1402", "09:30", "10:30"),
        ("CR-2026-1403", "10:00", "11:00"),
    )
    return [
        fixtures.schedule_hearing(
            courthouse_id,
            language_id,
            case_number=case_number,
            hearing_type="MOTION",
            in_custody=False,
            scheduled_start=f"2026-08-25T{start}:00.000Z",
            scheduled_end=f"2026-08-25T{end}:00.000Z",
        )
        for case_number, start, end in windows
    ]


def test_a_declined_assignment_does_not_block_an_overlapping_proposal(api):
    """PRD §3.6: "Two exclusivity rules protect the interpreter as an occupied resource, and both consider only that interpreter's own assignments whose `service_status` is `PROPOSED`, `CONFIRMED`, or `CHECKED_IN`; rows in `DECLINED`, `CANCELLED`, `SUPERSEDED`, `NO_SHOW`, or `COMPLETED` are ignored entirely."
    PRD §3.7: "Declining is the interpreter's own refusal, `PROPOSED → DECLINED`, and only the assignment's own interpreter may do it."

    Design: Corner/Calculations/interval_conflict_ignores_declined_rows_but_still_blocks_a_live_overlap
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    rostered = fixtures.setup_active_interpreter(config["language"]["id"])
    interpreter = rostered["interpreter"]
    first, second, _third = _three_overlapping_motion_hearings(
        config["courthouse"]["id"], config["language"]["id"]
    )

    on_first = fixtures.propose_assignment(
        first["id"], interpreter["id"], estimated_one_way_miles=5.0
    )
    declined = fixtures.decline_assignment(on_first["id"], interpreter["id"])
    assert declined["service_status"] == "DECLINED", (
        f"expected DECLINED after the interpreter's refusal, got "
        f"{declined['service_status']}"
    )
    assert fixtures.read_hearing(first["id"])["status"] == "SCHEDULED", (
        "expected a declined proposal to leave the hearing SCHEDULED"
    )

    on_second = fixtures.propose_assignment(
        second["id"], interpreter["id"], estimated_one_way_miles=5.0
    )
    assert on_second["service_status"] == "PROPOSED", (
        "expected the overlapping proposal accepted because the colliding row is "
        f"DECLINED, got {on_second['service_status']}"
    )
    assert on_second["interpreter_id"] == interpreter["id"], (
        f"expected the same interpreter named, got {on_second['interpreter_id']}"
    )


def test_a_live_proposed_assignment_still_blocks_an_overlapping_proposal(
    api, scheduling_coordinator_headers
):
    """PRD §3.6: "Two exclusivity rules protect the interpreter as an occupied resource, and both consider only that interpreter's own assignments whose `service_status` is `PROPOSED`, `CONFIRMED`, or `CHECKED_IN`; rows in `DECLINED`, `CANCELLED`, `SUPERSEDED`, `NO_SHOW`, or `COMPLETED` are ignored entirely."
    PRD §3.6: "Treat each hearing window as half-open — it includes its start instant and excludes its end instant — and reject the proposal with `ERR_INTERPRETER_DOUBLE_BOOKED` when an existing window starts before the new window ends *and* the new window starts before that existing window ends."
    PRD §2.12: "30. The hearing window does not overlap another live assignment of the same interpreter — otherwise `ERR_INTERPRETER_DOUBLE_BOOKED` (409). Applies to `POST /assignments`."

    Design: Corner/Calculations/interval_conflict_ignores_declined_rows_but_still_blocks_a_live_overlap
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    rostered = fixtures.setup_active_interpreter(config["language"]["id"])
    interpreter = rostered["interpreter"]
    first, second, third = _three_overlapping_motion_hearings(
        config["courthouse"]["id"], config["language"]["id"]
    )

    on_first = fixtures.propose_assignment(
        first["id"], interpreter["id"], estimated_one_way_miles=5.0
    )
    fixtures.decline_assignment(on_first["id"], interpreter["id"])
    fixtures.propose_assignment(
        second["id"], interpreter["id"], estimated_one_way_miles=5.0
    )

    # H3 runs 10:00-11:00 and the live PROPOSED row on H2 runs 09:30-10:30.
    response = api.create_assignment(
        create_assignment_payload(
            third["id"],
            fixtures.read_hearing(third["id"])["version"],
            interpreter["id"],
            estimated_one_way_miles=5.0,
        ),
        scheduling_coordinator_headers,
    )
    validate_error(response, ApiErrorId.ERR_INTERPRETER_DOUBLE_BOOKED, 409)
