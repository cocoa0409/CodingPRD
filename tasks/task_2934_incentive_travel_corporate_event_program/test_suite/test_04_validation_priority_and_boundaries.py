"""Validation-priority conflicts and exact-equality boundaries (PRD §2.8, §3.2, §3.8)."""
from test_helpers import *  # noqa: F401,F403

# ─── Shared ladder / sourcing shape (PRD §3.1, §3.2, §3.4) ───────────────────
# A per-person basis of 431757 cents against these two rungs pins the award side
# of the budget rollup at 1443174 cents: PLATINUM 921765 + GOLD 521409.

_PLATINUM = {
    "tier_code": "PLATINUM",
    "tier_rank": 1,
    "qualification_threshold": 250_000_000,
    "budget_per_qualifier_cents": 2_500_000,
    "guest_allowance": 1,
    "air_cabin_class": "BUSINESS",
    "upgrade_allowance_cents": 150_000,
    "service_load_bp": 1275,
}

_GOLD = {
    "tier_code": "GOLD",
    "tier_rank": 2,
    "qualification_threshold": 150_000_000,
    "budget_per_qualifier_cents": 1_600_000,
    "guest_allowance": 1,
    "air_cabin_class": "PREMIUM_ECONOMY",
    "upgrade_allowance_cents": 40_000,
    "service_load_bp": 800,
}

_DESTINATION = {
    "city": "Lisbon",
    "country_code": "PT",
    "per_person_cost_cents": 431_757,
    "risk_score": 35,
    "air_gateway_code": "LIS",
}

_CONTRACT = {
    "supplier_name": "Estoril Palace",
    "supplier_kind": "HOTEL",
    "room_block_count": 12,
    "contracted_nights": 5,
    "stay_start_at": "2026-11-08T00:00:00Z",
    "nightly_rate_cents": 38_500,
    "attrition_allowance_bp": 2000,
    "force_majeure_clause": "STANDARD",
    "exposure_basis": "ATTRITION_BASIS",
}

_QUALIFIER_A = {
    "employee_code": "S-1001",
    "full_name": "Ana Reyes",
    "baseline_metric": 180_000_000,
    "actual_metric": 260_000_000,
    "guest_count": 1,
}

_QUALIFIER_B = {
    "employee_code": "S-2001",
    "full_name": "Ben Ortiz",
    "baseline_metric": 120_000_000,
    "actual_metric": 155_000_000,
    "guest_count": 0,
}

# stay_start_at 2026-11-08 plus 5 contracted nights makes stay_end_at
# 2026-11-13, the exclusive upper bound of the stay window (PRD §3.4).
_SEAT = {
    "arrival_date": "2026-11-08T00:00:00Z",
    "departure_date": "2026-11-13T00:00:00Z",
    "rooms": 1,
}


def _registration_open_pair(budget_total_cents):
    """REGISTRATION_OPEN program with both winners adjudicated and NOTIFIED."""
    return setup_registration_open_program(
        qualifier_specs=[_QUALIFIER_A, _QUALIFIER_B],
        gross_up_policy="FULL_GROSS_UP",
        program_overrides={"budget_total_cents": budget_total_cents},
        tier_specs=[_PLATINUM, _GOLD],
        destination_overrides=_DESTINATION,
        contract_overrides=_CONTRACT,
    )


def _headroom_squeezed_seat():
    """Winner B's seat left INVITED and priced at 105500 cents against a
    remaining headroom of only 56826 cents, so a confirm violates both the
    priority-11 attendance-state gate and the priority-30 headroom gate."""
    base = _registration_open_pair(1_500_000)
    qualifier_b = base["qualifiers"][1]
    registration = create_registration(
        qualifier_b["id"], program_id=base["program"]["id"], **_SEAT
    )
    air_action(
        registration["id"],
        "REQUEST",
        cabin_class="BUSINESS",
        deviation_pre_days=3,
        deviation_post_days=2,
        base_fare_cents=214_000,
    )
    base["qualifier_b"] = qualifier_b
    base["registration"] = read_registration(registration["id"])
    base["program"] = read_program(base["program"]["id"])
    return base


def test_confirm_reports_state_error_when_attendance_and_headroom_both_fail():
    """Confirming an INVITED seat the program cannot fund reports the state error.

    PRD §2.8: "When a single request would fail more than one check, the check
    with the lowest priority number below wins and its error is the one
    returned."

    Design: Difficulty/priority_pair_validation_conflict/registration_state_check_precedes_budget_headroom_check_on_confirm
    """
    base = _headroom_squeezed_seat()
    registration = base["registration"]
    assert registration["attendance_status"] == "INVITED"
    assert registration["cost_cents"] == 105_500
    assert base["program"]["committed_budget_cents"] == 1_443_174
    assert base["program"]["budget_headroom_cents"] == 56_826

    response = api_client.confirm_registration(
        registration["id"], TEST_USERS["travel_desk_headers"]
    )
    validate_error(response, ApiErrorId.ERR_REGISTRATION_STATE_INVALID, 409)

    after = read_registration(registration["id"])
    assert after["attendance_status"] == "INVITED"
    assert after["room_nights"] == 0
    program = read_program(base["program"]["id"])
    assert program["committed_budget_cents"] == 1_443_174
    assert program["budget_headroom_cents"] == 56_826
    assert_budget_conserved(program)


def test_confirm_reports_headroom_error_once_the_state_violation_is_removed():
    """With the seat ACCEPTED the same unaffordable confirm reports the fiscal error.

    PRD §2.8: "Budget headroom — the program's `budget_headroom_cents` is at
    least the registration's `cost_cents` at confirmation."

    Design: Difficulty/priority_pair_validation_conflict/registration_state_check_precedes_budget_headroom_check_on_confirm
    """
    base = _headroom_squeezed_seat()
    registration = base["registration"]
    accepted = respond_registration(
        registration["id"], base["qualifier_b"]["id"], "ACCEPT"
    )
    assert accepted["attendance_status"] == "ACCEPTED"
    assert accepted["cost_cents"] == 105_500

    response = api_client.confirm_registration(
        registration["id"], TEST_USERS["travel_desk_headers"]
    )
    validate_error(response, ApiErrorId.ERR_BUDGET_HEADROOM_EXCEEDED, 422)

    after = read_registration(registration["id"])
    assert after["attendance_status"] == "ACCEPTED"
    assert after["room_nights"] == 0
    contract = read_contract(base["contract"]["id"])
    assert contract["room_nights_confirmed"] == 0
    program = read_program(base["program"]["id"])
    assert program["budget_posture"] == "WATCH"
    assert program["committed_budget_cents"] == 1_443_174
    assert_budget_conserved(program)
    assert_room_nights_conserved(contract)


def test_confirm_state_and_headroom_gates_are_ordered_on_one_seat():
    """The same seat surfaces the state error first and the fiscal error second.

    PRD §2.8: "The ordering is normative — an implementation that reports a
    budget failure on a request that also has a bad role has reported the wrong
    error."

    Design: Difficulty/priority_pair_validation_conflict/registration_state_check_precedes_budget_headroom_check_on_confirm
    """
    base = _headroom_squeezed_seat()
    registration_id = base["registration"]["id"]
    travel_desk = TEST_USERS["travel_desk_headers"]

    first = api_client.confirm_registration(registration_id, travel_desk)
    validate_error(first, ApiErrorId.ERR_REGISTRATION_STATE_INVALID, 409)

    respond_registration(registration_id, base["qualifier_b"]["id"], "ACCEPT")

    second = api_client.confirm_registration(registration_id, travel_desk)
    validate_error(second, ApiErrorId.ERR_BUDGET_HEADROOM_EXCEEDED, 422)

    program = read_program(base["program"]["id"])
    assert program["committed_budget_cents"] == 1_443_174
    assert program["budget_headroom_cents"] == 56_826
    assert read_registration(registration_id)["attendance_status"] == "ACCEPTED"


# ─── Waiver (priority 16) versus transfer buffer (priority 24) ────────────────
# A1 ends 13:00 and A2 starts 13:30, a 30-minute gap that is inside the
# 45-minute transfer buffer of PRD §3.8, so A2 collides with A1 for anyone who
# already holds an A1 slot.

_ACTIVITY_LOW = {
    "name": "Sintra palace tour",
    "start_at": "2026-11-10T10:00:00Z",
    "end_at": "2026-11-10T13:00:00Z",
    "capacity": 5,
    "risk_level": "LOW",
}

_ACTIVITY_HIGH = {
    "name": "Atlantic coast canyoning",
    "start_at": "2026-11-10T13:30:00Z",
    "end_at": "2026-11-10T16:00:00Z",
    "capacity": 5,
    "risk_level": "HIGH",
}


def _onsite_pair_with_mixed_waivers():
    """ONSITE program where winner A carries no waiver and winner B does, and
    both already hold a BOOKED slot on the LOW-risk activity."""
    base = _registration_open_pair(5_000_000)
    seat_a = enrol_and_confirm(
        base, base["qualifiers"][0], registration_overrides=_SEAT, waiver_signed=False
    )
    seat_b = enrol_and_confirm(
        base, base["qualifiers"][1], registration_overrides=_SEAT, waiver_signed=True
    )
    advance_program(base["program"]["id"], "ONSITE")
    assert read_registration(seat_a["id"])["waiver_on_file"] is False
    assert read_registration(seat_b["id"])["waiver_on_file"] is True

    program_id = base["program"]["id"]
    activity_low = create_activity(program_id, **_ACTIVITY_LOW)
    activity_high = create_activity(program_id, **_ACTIVITY_HIGH)
    signup_a = create_signup(activity_low["id"], seat_a["id"])
    signup_b = create_signup(activity_low["id"], seat_b["id"])
    assert signup_a["status"] == "BOOKED"
    assert signup_b["status"] == "BOOKED"

    base["seat_a"] = seat_a
    base["seat_b"] = seat_b
    base["activity_low"] = activity_low
    base["activity_high"] = read_activity(activity_high["id"])
    base["signup_a"] = signup_a
    base["signup_b"] = signup_b
    return base


def _attempt_high_risk_signup(base, seat):
    activity_id = base["activity_high"]["id"]
    payload = create_activity_signup_payload(
        activity_id, seat["id"], activity_version(activity_id)
    )
    return api_client.create_activity_signup(payload, TEST_USERS["travel_desk_headers"])


def test_high_risk_signup_reports_waiver_error_when_waiver_and_buffer_both_fail():
    """A waiverless winner inside the transfer buffer reports the waiver error.

    PRD §3.8: "An activity whose `risk_level` is `HIGH` additionally demands
    that the registration carry `waiver_on_file` as true — the waiver the
    participant signed when accepting the invitation — and a signup without it
    reports `ERR_ACTIVITY_WAIVER_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/activity_waiver_safety_check_precedes_transfer_buffer_temporal_check
    """
    base = _onsite_pair_with_mixed_waivers()
    response = _attempt_high_risk_signup(base, base["seat_a"])
    validate_error(response, ApiErrorId.ERR_ACTIVITY_WAIVER_REQUIRED, 422)

    activity = read_activity(base["activity_high"]["id"])
    assert_signup_counters(activity, 0, 0)


def test_high_risk_signup_reports_time_conflict_when_only_the_buffer_is_violated():
    """A waivered winner inside the same buffer reports the temporal error.

    PRD §3.8: "Because both comparisons are strict, a gap of exactly 45 minutes
    is accepted and a gap of 44 minutes is refused"

    Design: Difficulty/priority_pair_validation_conflict/activity_waiver_safety_check_precedes_transfer_buffer_temporal_check
    """
    base = _onsite_pair_with_mixed_waivers()
    response = _attempt_high_risk_signup(base, base["seat_b"])
    validate_error(response, ApiErrorId.ERR_ACTIVITY_TIME_CONFLICT, 409)

    activity = read_activity(base["activity_high"]["id"])
    assert_signup_counters(activity, 0, 0)


def test_outranked_high_risk_rejections_create_no_row_and_bump_no_version():
    """Neither outranked rejection mints a signup or moves the activity.

    PRD §2.8: "When a single request would fail more than one check, the check
    with the lowest priority number below wins and its error is the one
    returned."

    Design: Difficulty/priority_pair_validation_conflict/activity_waiver_safety_check_precedes_transfer_buffer_temporal_check
    """
    base = _onsite_pair_with_mixed_waivers()
    activity_id = base["activity_high"]["id"]
    version_before = base["activity_high"]["version"]

    validate_error(
        _attempt_high_risk_signup(base, base["seat_a"]),
        ApiErrorId.ERR_ACTIVITY_WAIVER_REQUIRED,
        422,
    )
    validate_error(
        _attempt_high_risk_signup(base, base["seat_b"]),
        ApiErrorId.ERR_ACTIVITY_TIME_CONFLICT,
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_activity_signups(
            TEST_USERS["travel_desk_headers"], params={"activity_id": activity_id}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    activity = read_activity(activity_id)
    assert_version_is(activity, version_before, "OnsiteActivity")
    assert_signup_counters(activity, 0, 0)
    assert read_signup(base["signup_a"]["id"])["status"] == "BOOKED"
    assert read_signup(base["signup_b"]["id"])["status"] == "BOOKED"


# ─── Tier threshold inclusivity at exact equality (PRD §3.2) ──────────────────
# The program stays in DESIGN, so per_person_cost_basis_cents is still 0 and
# committed_cost_cents collapses to the chosen rung's upgrade_allowance_cents.

_PROBE_ON_THRESHOLD = {
    "employee_code": "S-5001",
    "full_name": "Xu Wen",
    "baseline_metric": 100_000_000,
    "actual_metric": 250_000_000,
    "guest_count": 0,
}

_PROBE_ONE_BELOW_PLATINUM = {
    "employee_code": "S-5002",
    "full_name": "Yara Diop",
    "baseline_metric": 100_000_000,
    "actual_metric": 249_999_999,
    "guest_count": 0,
}

_PROBE_ONE_BELOW_GOLD = {
    "employee_code": "S-5003",
    "full_name": "Zane Holt",
    "baseline_metric": 100_000_000,
    "actual_metric": 149_999_999,
    "guest_count": 0,
}


def _threshold_probe_program():
    """A DESIGN program carrying the PLATINUM/GOLD ladder and nothing else."""
    return setup_program_with_tier_ladder(
        [_PLATINUM, _GOLD],
        program_overrides={
            "name": "FY26 Threshold Probe",
            "budget_total_cents": 20_000_000,
        },
    )


def test_actual_metric_exactly_at_the_threshold_clears_the_senior_rung():
    """An actual_metric equal to the threshold qualifies on that rung.

    PRD §3.2: "The comparison is inclusive — a salesperson landing exactly on a
    threshold clears that rung."

    Design: Difficulty/boundary_precision_check/tier_qualification_threshold_is_inclusive_at_exact_equality
    """
    base = _threshold_probe_program()
    platinum, gold = base["tiers"][0], base["tiers"][1]
    assert platinum["qualification_threshold"] == 250_000_000

    qualifier = create_qualifier(base["program"]["id"], **_PROBE_ON_THRESHOLD)
    reviewed = review_qualifier(qualifier["id"])
    assert_qualifier(reviewed)
    assert reviewed["award_status"] == "QUALIFIED"
    assert reviewed["assigned_tier_id"] == platinum["id"]
    assert reviewed["assigned_tier_id"] != gold["id"]
    assert reviewed["committed_cost_cents"] == 150_000


def test_one_metric_unit_below_the_senior_threshold_falls_to_the_next_rung():
    """249999999 misses PLATINUM by one unit and lands on GOLD instead.

    PRD §3.2: "If the pool is non-empty, the winner is the **richest rung
    actually cleared**"

    Design: Difficulty/boundary_precision_check/tier_qualification_threshold_is_inclusive_at_exact_equality
    """
    base = _threshold_probe_program()
    platinum, gold = base["tiers"][0], base["tiers"][1]

    qualifier = create_qualifier(base["program"]["id"], **_PROBE_ONE_BELOW_PLATINUM)
    reviewed = review_qualifier(qualifier["id"])
    assert reviewed["award_status"] == "QUALIFIED"
    assert reviewed["assigned_tier_id"] == gold["id"]
    assert reviewed["assigned_tier_id"] != platinum["id"]
    assert reviewed["committed_cost_cents"] == 40_000


def test_one_metric_unit_below_the_lowest_threshold_disqualifies():
    """149999999 clears no rung at all, so the qualifier is DISQUALIFIED.

    PRD §3.2: "If the eligible pool is empty, because the `actual_metric` fell
    below every rung on the ladder, the qualifier moves `PENDING_REVIEW →
    DISQUALIFIED`, `assigned_tier_id` stays null and `committed_cost_cents`
    stays 0."

    Design: Difficulty/boundary_precision_check/tier_qualification_threshold_is_inclusive_at_exact_equality
    """
    base = _threshold_probe_program()

    qualifier = create_qualifier(base["program"]["id"], **_PROBE_ONE_BELOW_GOLD)
    reviewed = review_qualifier(qualifier["id"])
    assert reviewed["award_status"] == "DISQUALIFIED"
    assert reviewed["assigned_tier_id"] is None
    assert reviewed["committed_cost_cents"] == 0


def test_threshold_boundary_rollup_counts_only_the_two_cleared_rungs():
    """Across all three probes the rollup excludes the DISQUALIFIED row.

    PRD §3.2: "The program's `qualified_count` is the number of its qualifiers
    whose `award_status` is `QUALIFIED`, `NOTIFIED`, `REGISTERED` or
    `TRAVELLED`"

    Design: Difficulty/boundary_precision_check/tier_qualification_threshold_is_inclusive_at_exact_equality
    """
    base = _threshold_probe_program()
    program_id = base["program"]["id"]
    for spec in (_PROBE_ON_THRESHOLD, _PROBE_ONE_BELOW_PLATINUM, _PROBE_ONE_BELOW_GOLD):
        qualifier = create_qualifier(program_id, **spec)
        review_qualifier(qualifier["id"])

    program = read_program(program_id)
    assert program["qualified_count"] == 2
    assert program["committed_budget_cents"] == 190_000
    assert program["budget_posture"] == "OK"
    assert_budget_conserved(program)


# ─── Strict booked_count < capacity admission (PRD §3.8) ──────────────────────
# The two activities sit a full day apart so the 45-minute transfer buffer never
# interferes with the capacity boundary being probed.

_ACTIVITY_ZERO_CAPACITY = {
    "name": "Fado dinner (sold out)",
    "start_at": "2026-11-11T09:00:00Z",
    "end_at": "2026-11-11T11:00:00Z",
    "capacity": 0,
    "risk_level": "LOW",
}

_ACTIVITY_ONE_CAPACITY = {
    "name": "Tram city tour",
    "start_at": "2026-11-12T09:00:00Z",
    "end_at": "2026-11-12T11:00:00Z",
    "capacity": 1,
    "risk_level": "LOW",
}


def _onsite_pair():
    """ONSITE program with both winners CONFIRMED and carrying a waiver."""
    return setup_onsite_program(
        qualifier_specs=[_QUALIFIER_A, _QUALIFIER_B],
        registration_overrides=_SEAT,
        waiver_signed=True,
        gross_up_policy="FULL_GROSS_UP",
        program_overrides={"budget_total_cents": 5_000_000},
        tier_specs=[_PLATINUM, _GOLD],
        destination_overrides=_DESTINATION,
        contract_overrides=_CONTRACT,
    )


def _signup_response(activity_id, registration_id):
    payload = create_activity_signup_payload(
        activity_id, registration_id, activity_version(activity_id)
    )
    return api_client.create_activity_signup(payload, TEST_USERS["travel_desk_headers"])


def test_zero_capacity_activity_waitlists_its_very_first_signup():
    """A capacity-0 activity waitlists the first signup because 0 < 0 is false.

    PRD §3.8: "A `capacity` of 0 is legal and meaningful: it sends every signup,
    from the very first, onto the waitlist."

    Design: Difficulty/boundary_precision_check/activity_admission_uses_strict_less_than_so_zero_capacity_waitlists_first_signup
    """
    base = _onsite_pair()
    activity = create_activity(base["program"]["id"], **_ACTIVITY_ZERO_CAPACITY)
    assert activity["capacity"] == 0

    signup = validate_success(
        _signup_response(activity["id"], base["registrations"][0]["id"]), 201
    )
    assert_activity_signup(signup)
    assert signup["status"] == "WAITLISTED"
    assert signup["promoted_at"] is None
    assert_signup_counters(read_activity(activity["id"]), 0, 1)


def test_capacity_one_activity_books_the_first_signup_and_waitlists_at_exact_fill():
    """One seat is filled at 0 < 1 and the next signup is waitlisted at 1 < 1.

    PRD §3.8: "Admission is a strict comparison: the signup lands `BOOKED` when
    the activity's `booked_count` is strictly less than its `capacity`, and
    `WAITLISTED` otherwise."

    Design: Difficulty/boundary_precision_check/activity_admission_uses_strict_less_than_so_zero_capacity_waitlists_first_signup
    """
    base = _onsite_pair()
    activity = create_activity(base["program"]["id"], **_ACTIVITY_ONE_CAPACITY)
    assert activity["capacity"] == 1

    first = validate_success(
        _signup_response(activity["id"], base["registrations"][0]["id"]), 201
    )
    assert first["status"] == "BOOKED"
    assert_signup_counters(read_activity(activity["id"]), 1, 0)

    second = validate_success(
        _signup_response(activity["id"], base["registrations"][1]["id"]), 201
    )
    assert second["status"] == "WAITLISTED"
    assert second["promoted_at"] is None
    assert_signup_counters(read_activity(activity["id"]), 1, 1)


def test_capacity_boundary_changes_the_signup_status_never_the_http_result():
    """All three boundary signups are real 201-created rows, none rejected.

    PRD §3.8: "An activity whose `booked_count` already equals its `capacity`
    waitlists the next signup rather than overbooking it."

    Design: Difficulty/boundary_precision_check/activity_admission_uses_strict_less_than_so_zero_capacity_waitlists_first_signup
    """
    base = _onsite_pair()
    program_id = base["program"]["id"]
    seat_a, seat_b = base["registrations"][0], base["registrations"][1]
    sold_out = create_activity(program_id, **_ACTIVITY_ZERO_CAPACITY)
    one_seat = create_activity(program_id, **_ACTIVITY_ONE_CAPACITY)

    waitlisted = validate_success(_signup_response(sold_out["id"], seat_a["id"]), 201)
    booked = validate_success(_signup_response(one_seat["id"], seat_a["id"]), 201)
    overflow = validate_success(_signup_response(one_seat["id"], seat_b["id"]), 201)
    assert [waitlisted["status"], booked["status"], overflow["status"]] == [
        "WAITLISTED",
        "BOOKED",
        "WAITLISTED",
    ]

    assert_signup_counters(read_activity(sold_out["id"]), 0, 1)
    assert_signup_counters(read_activity(one_seat["id"]), 1, 1)

    rows, meta = validate_paginated(
        api_client.list_activity_signups(
            TEST_USERS["travel_desk_headers"], params={"registration_id": seat_a["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
