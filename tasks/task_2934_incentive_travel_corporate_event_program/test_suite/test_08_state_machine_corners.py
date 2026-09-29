"""State-machine corners: initial states, undeclared edges, terminals, replays (PRD §3.1-§3.9)."""
from test_helpers import *  # noqa: F401,F403

# ─── Pinned figures (design index: Corner/state_machines) ────────────────────
PROGRAM_BUDGET_CENTS = 20000000
SMALL_BUDGET_CENTS = 5000000

# Estoril Palace defaults from test_helpers.constants: 12 rooms x 10 nights.
ROOM_NIGHTS_BLOCKED = 120

# GOLD rung against a 431757-cent per-person basis (PRD §3.2 pinned order):
#   winner 466298 (431757 * 10800 / 10000) + gratuity 15111 + upgrade allowance 40000
GOLD_TIER = {
    "tier_code": "GOLD",
    "tier_rank": 2,
    "qualification_threshold": 150000000,
    "budget_per_qualifier_cents": 1600000,
    "guest_allowance": 1,
    "air_cabin_class": "PREMIUM_ECONOMY",
    "upgrade_allowance_cents": 40000,
    "service_load_bp": 800,
}
LISBON_BASIS_CENTS = 431757
GOLD_COMMITTED_CENTS = 521409
GOLD_TAXABLE_CENTS = 443198             # 521409 - 78211 business-purpose exclusion
GOLD_REPORTED_VALUE_CENTS = 658052      # FULL_GROSS_UP on 443198 at 3265 bp
GOLD_GROSS_UP_CENTS = 214854

# Default 400000-cent basis: winner 400000 + gratuity 14000, no upgrade allowance.
DEFAULT_COMMITTED_CENTS = 414000

PD = TEST_USERS["program_director_headers"]
SM = TEST_USERS["sourcing_manager_headers"]
CA = TEST_USERS["contract_approver_headers"]
AN = TEST_USERS["sales_ops_analyst_headers"]
TD = TEST_USERS["travel_desk_headers"]
TAX = TEST_USERS["tax_officer_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# every_new_row_starts_in_its_declared_initial_state
# ═══════════════════════════════════════════════════════════════════════════

def test_new_program_lands_in_design_with_every_rollup_at_zero():
    """A newly chartered program opens on DESIGN with every computed field zeroed.

    PRD §3.1: "A newly chartered program lands in `DESIGN` with `gross_up_policy`
    set to `NONE`, `gross_up_policy_locked` false, `budget_posture` `OK`, and every
    computed money and count field at 0"

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)

    assert_program(program)
    assert program["status"] == "DESIGN"
    assert program["gross_up_policy"] == "NONE"
    assert program["gross_up_policy_locked"] is False
    assert program["budget_posture"] == "OK"
    for field in (
        "per_person_cost_basis_cents", "committed_budget_cents", "budget_headroom_cents",
        "cancellation_exposure_cents", "reported_award_total_cents",
        "qualified_count", "travelled_count",
    ):
        assert program[field] == 0, f"Program.{field} must open at 0, got {program[field]!r}"
    assert program["sales_lift_pct"] is None
    assert program["satisfaction_index"] is None
    assert program["cancellation_reason"] is None
    assert_version_is(program, 1, "Program")


def test_new_destination_lands_candidate_and_not_inspected_on_both_axes():
    """A fresh candidate opens CANDIDATE / NOT_INSPECTED even beside a shortlisted sibling.

    PRD §3.3: "A fresh candidate lands with `status` `CANDIDATE`,
    `inspection_status` `NOT_INSPECTED`, a null `inspection_score`, a null
    `inspected_by_user_id` and a null `inspected_at`."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)
    lisbon = create_destination(program["id"], city="Lisbon", risk_score=35)
    inspect_destination(lisbon["id"], 82)
    shortlist_destination(lisbon["id"])

    seville = create_destination(
        program["id"], city="Seville", country_code="ES",
        per_person_cost_cents=388000, risk_score=28, air_gateway_code="SVQ",
    )

    assert_destination(seville)
    assert seville["status"] == "CANDIDATE"
    assert seville["inspection_status"] == "NOT_INSPECTED"
    assert seville["inspection_score"] is None
    assert seville["inspected_by_user_id"] is None
    assert seville["inspected_at"] is None
    assert_version_is(seville, 1, "Destination")
    # The sibling really did move, so the fresh row's initial state is not a no-op.
    assert read_destination(lisbon["id"])["status"] == "SHORTLISTED"


def test_new_supplier_contract_lands_draft_with_an_empty_room_night_ledger():
    """A freshly opened contract sits in DRAFT with no rounds and no ledger.

    PRD §3.4: "A new contract lands in `DRAFT` with `round_count` 0,
    `room_nights_blocked`, `room_nights_confirmed` and `room_nights_available` all
    0, `attrition_posture` `CLEAR`, and null values for
    `last_proposed_by_user_id`, `last_countered_by_user_id`,
    `executed_by_user_id`, `executed_at` and `withdrawal_reason`."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    reset_logical_clock()
    base = setup_sourcing_program(program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS})
    contract = create_contract(base["program"]["id"], base["destination"]["id"])

    assert_supplier_contract(contract)
    assert contract["status"] == "DRAFT"
    assert contract["round_count"] == 0
    assert contract["room_nights_blocked"] == 0
    assert contract["room_nights_confirmed"] == 0
    assert contract["room_nights_available"] == 0
    assert contract["attrition_posture"] == "CLEAR"
    for field in (
        "last_proposed_by_user_id", "last_countered_by_user_id",
        "executed_by_user_id", "executed_at", "withdrawal_reason",
    ):
        assert contract[field] is None, f"SupplierContract.{field} must open null"
    assert_version_is(contract, 1, "SupplierContract")


def test_new_deposit_milestone_lands_scheduled_without_finance_review():
    """A newly appended milestone sits SCHEDULED, unreviewed and unpaid.

    PRD §3.5: "A new milestone lands `SCHEDULED`, with `requires_finance_review`
    false and a null `paid_at`."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    reset_logical_clock()
    base = setup_proposed_contract(program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS})
    milestone = create_milestone(
        base["contract"]["id"], sequence=1,
        due_at="2026-08-15T00:00:00Z", amount_cents=577500, refundable_bp=10000,
    )

    assert_deposit_milestone(milestone)
    assert milestone["status"] == "SCHEDULED"
    assert milestone["requires_finance_review"] is False
    assert milestone["paid_at"] is None
    assert_version_is(milestone, 1, "DepositMilestone")


def test_new_qualifier_lands_pending_review_with_tax_not_applicable():
    """A loaded qualifier row opens PENDING_REVIEW / NOT_APPLICABLE with no tier.

    PRD §3.2: "A new row lands with `award_status` `PENDING_REVIEW`, `tax_status`
    `NOT_APPLICABLE`, a null `assigned_tier_id`, `committed_cost_cents` and
    `taxable_award_cents` both 0, and a null `notified_at`."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)
    create_award_tier(program["id"], **GOLD_TIER)
    qualifier = create_qualifier(
        program["id"], baseline_metric=180000000, actual_metric=260000000, guest_count=1,
    )

    assert_qualifier(qualifier)
    assert qualifier["award_status"] == "PENDING_REVIEW"
    assert qualifier["tax_status"] == "NOT_APPLICABLE"
    assert qualifier["assigned_tier_id"] is None
    assert qualifier["committed_cost_cents"] == 0
    assert qualifier["taxable_award_cents"] == 0
    assert qualifier["notified_at"] is None
    assert_version_is(qualifier, 1, "Qualifier")


def test_new_registration_lands_invited_with_the_air_axis_not_requested():
    """A fresh seat opens INVITED on attendance and NOT_REQUESTED on air.

    PRD §3.6: "A fresh seat lands with `attendance_status` `INVITED`, `air_status`
    `NOT_REQUESTED`, `waiver_on_file` false, `room_nights` 0, `cost_cents` 0, a
    null `air_cabin_class`, `air_deviation_pre_days` and `air_deviation_post_days`
    both 0"

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    reset_logical_clock()
    base = setup_invited_registration()
    seat = base["registration"]

    assert_registration(seat)
    assert seat["attendance_status"] == "INVITED"
    assert seat["air_status"] == "NOT_REQUESTED"
    assert seat["waiver_on_file"] is False
    assert seat["room_nights"] == 0
    assert seat["cost_cents"] == 0
    assert seat["air_cabin_class"] is None
    for field in (
        "air_deviation_pre_days", "air_deviation_post_days", "air_base_fare_cents",
        "air_upgrade_cost_cents", "air_deviation_fee_cents", "air_change_count",
        "air_change_fee_total_cents",
    ):
        assert seat[field] == 0, f"Registration.{field} must open at 0, got {seat[field]!r}"
    assert seat["satisfaction_score"] is None
    assert seat["cancellation_reason"] is None
    assert_version_is(seat, 1, "Registration")


def test_new_onsite_activity_lands_open_with_both_counters_at_zero():
    """A published activity opens OPEN with an empty roster on both counters.

    PRD §3.8: "A new activity lands `OPEN` with `booked_count` and
    `waitlist_count` both 0."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    reset_logical_clock()
    base = setup_contracted_program(program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS})
    activity = create_activity(base["program"]["id"], name="Douro Valley Sail", capacity=4)

    assert_onsite_activity(activity)
    assert activity["status"] == "OPEN"
    assert_signup_counters(activity, 0, 0)
    assert_version_is(activity, 1, "OnsiteActivity")


def test_new_signup_lands_booked_when_booked_count_is_below_capacity():
    """The first signup on a roomy activity is admitted BOOKED, not waitlisted.

    PRD §3.8: "**Admission** is a strict comparison: the signup lands `BOOKED` when
    the activity's `booked_count` is strictly less than its `capacity`, and
    `WAITLISTED` otherwise."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    reset_logical_clock()
    base = setup_onsite_with_activity(activity_overrides={"capacity": 2})
    signup = create_signup(base["activity"]["id"], base["registration"]["id"])

    assert_activity_signup(signup)
    assert signup["status"] == "BOOKED"
    assert signup["promoted_at"] is None
    assert_signup_counters(read_activity(base["activity"]["id"]), 1, 0)
    assert_version_is(signup, 1, "ActivitySignup")


def test_new_signup_lands_waitlisted_on_a_zero_capacity_activity():
    """A capacity-0 activity waitlists the very first signup.

    PRD §3.8: "A `capacity` of 0 is legal and meaningful: it sends every signup,
    from the very first, onto the waitlist."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    reset_logical_clock()
    base = setup_onsite_with_activity(
        activity_overrides={"name": "Sunrise Yoga", "capacity": 0},
    )
    signup = create_signup(base["activity"]["id"], base["registration"]["id"])

    assert_activity_signup(signup)
    assert signup["status"] == "WAITLISTED"
    assert signup["promoted_at"] is None
    assert_signup_counters(read_activity(base["activity"]["id"]), 0, 1)


def test_new_tax_award_report_lands_draft_with_no_filing_or_void_trail():
    """A drafted report opens DRAFT with all four filing/void fields null.

    PRD §3.9: "The report lands in `DRAFT` with a null `filed_by_user_id`,
    `filed_at`, `voided_by_user_id` and `void_reason`."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    reset_logical_clock()
    base = setup_drafted_tax_report()
    report = base["report"]

    assert_tax_award_report(report)
    assert report["status"] == "DRAFT"
    for field in ("filed_by_user_id", "filed_at", "voided_by_user_id", "void_reason"):
        assert report[field] is None, f"TaxAwardReport.{field} must open null"
    assert_version_is(report, 1, "TaxAwardReport")


# ═══════════════════════════════════════════════════════════════════════════
# destination_inspection_and_shortlisting_transitions_fire_with_their_side_effects
# ═══════════════════════════════════════════════════════════════════════════

def test_site_inspection_stamps_the_inspection_axis_and_leaves_selection_alone():
    """Recording an inspection moves only the inspection dimension, with its stamps.

    PRD §3.3: "the destination moves `NOT_INSPECTED → INSPECTED`, the score is
    stored, `inspected_by_user_id` is stamped with the acting `X-User-ID`,
    `inspected_at` is stamped from the logical clock, and the destination's
    `version` increments."

    Design: Corner/state_machines/destination_inspection_and_shortlisting_transitions_fire_with_their_side_effects
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)
    destination = create_destination(program["id"], city="Lisbon", risk_score=35)

    inspected = inspect_destination(destination["id"], 82)

    assert inspected["inspection_status"] == "INSPECTED"
    assert inspected["inspection_score"] == 82
    assert inspected["inspected_by_user_id"] == USER_IDS["SOURCING_MANAGER"]
    assert_instant_equals(
        inspected["inspected_at"], LOGICAL_CLOCK_DEFAULT, "Destination.inspected_at"
    )
    assert inspected["status"] == "CANDIDATE", "Inspection must not touch the selection axis"
    assert_version_is(inspected, 2, "Destination")


def test_shortlisting_moves_the_selection_axis_without_revising_the_inspection():
    """Shortlisting promotes the selection axis and leaves the inspection record intact.

    PRD §3.3: "On success the destination moves `CANDIDATE → SHORTLISTED` and its
    `version` increments."

    Design: Corner/state_machines/destination_inspection_and_shortlisting_transitions_fire_with_their_side_effects
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)
    destination = create_destination(program["id"], city="Lisbon", risk_score=35)
    inspect_destination(destination["id"], 82)

    shortlisted = shortlist_destination(destination["id"])

    assert shortlisted["status"] == "SHORTLISTED"
    assert_version_is(shortlisted, 3, "Destination")
    assert shortlisted["inspection_status"] == "INSPECTED"
    assert shortlisted["inspection_score"] == 82, "Shortlisting must not revise the score"
    assert shortlisted["inspected_by_user_id"] == USER_IDS["SOURCING_MANAGER"]
    assert_instant_equals(
        shortlisted["inspected_at"], LOGICAL_CLOCK_DEFAULT, "Destination.inspected_at"
    )


def test_shortlisting_does_not_advance_the_program_or_select_the_destination():
    """A shortlist leaves the program in DESIGN; SELECTED is never request-driven.

    PRD §3.3: "Neither `SELECTED` nor `REJECTED` is ever reached by a request."

    Design: Corner/state_machines/destination_inspection_and_shortlisting_transitions_fire_with_their_side_effects
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)
    destination = create_destination(program["id"], city="Lisbon", risk_score=35)
    inspect_destination(destination["id"], 82)
    shortlist_destination(destination["id"])

    after = read_program(program["id"])
    assert after["status"] == "DESIGN", "Shortlisting is not a program transition"
    assert_version_is(after, 1, "Program")

    rows, meta = validate_paginated(
        api_client.list_destinations(SM, {"program_id": program["id"], "status": "SHORTLISTED"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == destination["id"]
    assert rows[0]["status"] == "SHORTLISTED"


# ═══════════════════════════════════════════════════════════════════════════
# shortlist_preconditions_each_produce_their_own_error
# ═══════════════════════════════════════════════════════════════════════════

def test_shortlisting_a_never_inspected_candidate_reports_destination_state_invalid():
    """The inspection precondition has its own error, distinct from the two gates.

    PRD §3.3: "a destination that is not a candidate or has never been inspected
    reports `ERR_DESTINATION_STATE_INVALID`."

    Design: Corner/state_machines/shortlist_preconditions_each_produce_their_own_error
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)
    # Risk 28 and no inspection at all: only the precondition can fail.
    destination = create_destination(program["id"], city="Lisbon", risk_score=28)

    response = api_client.shortlist_destination(destination["id"], SM)
    validate_error(response, ApiErrorId.ERR_DESTINATION_STATE_INVALID, 409)

    after = read_destination(destination["id"])
    assert after["status"] == "CANDIDATE"
    assert after["inspection_status"] == "NOT_INSPECTED"
    assert_version_is(after, 1, "Destination")


def test_shortlisting_an_under_inspected_destination_reports_the_inspection_floor():
    """69 is under the inspection floor and reports its own error, risk being fine.

    PRD §3.3: "Its `inspection_score` must be at least 70 — exactly 70 passes, 69
    does not, and falling short reports `ERR_INSPECTION_SCORE_BELOW_MINIMUM`."

    Design: Corner/state_machines/shortlist_preconditions_each_produce_their_own_error
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)
    destination = create_destination(program["id"], city="Lisbon", risk_score=28)
    inspect_destination(destination["id"], 69)

    response = api_client.shortlist_destination(destination["id"], SM)
    validate_error(response, ApiErrorId.ERR_INSPECTION_SCORE_BELOW_MINIMUM, 422)

    after = read_destination(destination["id"])
    assert after["status"] == "CANDIDATE"
    assert_version_is(after, 2, "Destination")


def test_shortlisting_a_too_risky_destination_reports_the_risk_ceiling():
    """A risk score of 61 reports the risk error even with a strong inspection.

    PRD §3.3: "The destination's `risk_score` must be at most 60 — a score of
    exactly 60 passes, 61 does not, and exceeding the ceiling reports
    `ERR_DESTINATION_RISK_TOO_HIGH`."

    Design: Corner/state_machines/shortlist_preconditions_each_produce_their_own_error
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)
    destination = create_destination(program["id"], city="Lisbon", risk_score=61)
    inspect_destination(destination["id"], 95)

    response = api_client.shortlist_destination(destination["id"], SM)
    validate_error(response, ApiErrorId.ERR_DESTINATION_RISK_TOO_HIGH, 422)

    after = read_destination(destination["id"])
    assert after["status"] == "CANDIDATE"
    assert_version_is(after, 2, "Destination")


def test_a_destination_failing_both_gates_reports_the_risk_failure_first():
    """When both commercial gates fail, the risk ceiling is the reported error.

    PRD §3.3: "The risk ceiling is evaluated before the inspection floor, so a
    destination that is both too risky and under-inspected reports the risk
    failure."

    Design: Corner/state_machines/shortlist_preconditions_each_produce_their_own_error
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)
    destination = create_destination(program["id"], city="Lisbon", risk_score=61)
    inspect_destination(destination["id"], 69)

    response = api_client.shortlist_destination(destination["id"], SM)
    validate_error(response, ApiErrorId.ERR_DESTINATION_RISK_TOO_HIGH, 422)


def test_the_shortlist_gates_pass_on_their_exact_boundary_values():
    """Risk exactly 60 with an inspection of exactly 70 shortlists successfully.

    PRD §3.3: "a score of exactly 60 passes, 61 does not"

    Design: Corner/state_machines/shortlist_preconditions_each_produce_their_own_error
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)
    destination = create_destination(program["id"], city="Lisbon", risk_score=60)
    inspect_destination(destination["id"], 70)

    shortlisted = shortlist_destination(destination["id"])
    assert shortlisted["status"] == "SHORTLISTED"
    assert_version_is(shortlisted, 3, "Destination")


# ═══════════════════════════════════════════════════════════════════════════
# triggers_that_are_not_declared_edges_are_refused_per_dimension
# ═══════════════════════════════════════════════════════════════════════════

def test_a_backward_program_advance_is_not_a_declared_edge():
    """REGISTRATION_OPEN → DESIGN runs against the arrow of every declared edge.

    PRD §3.1: "A requested `to_status` that is not a declared edge out of the
    current status — including any attempt to advance a terminal program — is
    rejected with `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/state_machines/triggers_that_are_not_declared_edges_are_refused_per_dimension
    """
    reset_logical_clock()
    base = setup_registration_open_program()
    program_id = base["program"]["id"]
    before = read_program(program_id)

    response = api_client.advance_program(program_id, advance_payload("DESIGN"), PD)
    validate_error(response, ApiErrorId.ERR_PROGRAM_STATE_INVALID, 409)

    after = read_program(program_id)
    assert after["status"] == "REGISTRATION_OPEN"
    assert_version_is(after, before["version"], "Program")


def test_requesting_the_system_only_sourcing_to_contracted_edge_is_refused():
    """CONTRACTED is reachable only through the execution cascade, never on request.

    PRD §3.1: "`SOURCING → CONTRACTED` is a **system-driven** edge only: it happens
    as part of the contract-execution cascade of §3.4 and can never be requested
    directly, so an advance naming `CONTRACTED` as its `to_status` also reports
    `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/state_machines/triggers_that_are_not_declared_edges_are_refused_per_dimension
    """
    reset_logical_clock()
    base = setup_sourcing_program(program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS})
    program_id = base["program"]["id"]
    before = read_program(program_id)
    assert before["status"] == "SOURCING"

    response = api_client.advance_program(program_id, advance_payload("CONTRACTED"), PD)
    validate_error(response, ApiErrorId.ERR_PROGRAM_STATE_INVALID, 409)

    after = read_program(program_id)
    assert after["status"] == "SOURCING"
    assert_version_is(after, before["version"], "Program")


def test_leapfrogging_intermediate_statuses_is_not_a_declared_edge():
    """DESIGN → ONSITE jumps over three statuses and is refused, not silently clamped.

    PRD §3.1: "Lifecycle advancement is a `ProgramDirector` capability that
    supplies the desired `to_status` and moves the program along exactly one
    declared edge."

    Design: Corner/state_machines/triggers_that_are_not_declared_edges_are_refused_per_dimension
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)

    response = api_client.advance_program(program["id"], advance_payload("ONSITE"), PD)
    validate_error(response, ApiErrorId.ERR_PROGRAM_STATE_INVALID, 409)

    after = read_program(program["id"])
    assert after["status"] == "DESIGN"
    assert_version_is(after, 1, "Program")


def test_ticketing_a_seat_with_no_air_request_is_refused_on_the_air_dimension():
    """TICKET and CHANGE are undeclared out of NOT_REQUESTED and use the air error.

    PRD §3.7: "Any other pairing — requesting twice, ticketing straight from
    `NOT_REQUESTED`, changing a record that is not `TICKETED`, or acting on a
    `VOIDED` record at all — reports `ERR_AIR_STATE_INVALID`."

    Design: Corner/state_machines/triggers_that_are_not_declared_edges_are_refused_per_dimension
    """
    reset_logical_clock()
    base = setup_accepted_registration()
    seat_id = base["registration"]["id"]
    before = read_registration(seat_id)
    assert before["air_status"] == "NOT_REQUESTED"

    for action in ("TICKET", "CHANGE"):
        response = api_client.air_registration(seat_id, air_payload(action), TD)
        validate_error(response, ApiErrorId.ERR_AIR_STATE_INVALID, 409)

    after = read_registration(seat_id)
    assert after["air_status"] == "NOT_REQUESTED"
    assert after["attendance_status"] == "ACCEPTED", "The attendance axis must not move either"
    assert_version_is(after, before["version"], "Registration")


def test_confirming_an_invited_seat_is_refused_on_the_attendance_dimension():
    """Confirmation is declared only out of ACCEPTED, so an INVITED seat is refused.

    PRD §3.7: "Confirming a seat that is not `ACCEPTED` — one still `INVITED`,
    already `CONFIRMED`, or terminal — reports `ERR_REGISTRATION_STATE_INVALID`."

    Design: Corner/state_machines/triggers_that_are_not_declared_edges_are_refused_per_dimension
    """
    reset_logical_clock()
    base = setup_invited_registration()
    seat_id = base["registration"]["id"]

    response = api_client.confirm_registration(seat_id, TD)
    validate_error(response, ApiErrorId.ERR_REGISTRATION_STATE_INVALID, 409)

    after = read_registration(seat_id)
    assert after["attendance_status"] == "INVITED"
    assert after["room_nights"] == 0
    assert after["cost_cents"] == 0
    assert_version_is(after, 1, "Registration")


# ═══════════════════════════════════════════════════════════════════════════
# terminal_states_accept_no_further_transitions
# ═══════════════════════════════════════════════════════════════════════════

def test_a_withdrawn_contract_refuses_negotiation_execution_and_a_second_withdrawal():
    """WITHDRAWN is terminal: every contract trigger bounces off it unchanged.

    PRD §3.4: "Any other pairing of current status and action — countering a
    `DRAFT`, proposing from `PROPOSED`, negotiating an `EXECUTED` or `WITHDRAWN`
    contract — is rejected with `ERR_CONTRACT_STATE_INVALID`."

    Design: Corner/state_machines/terminal_states_accept_no_further_transitions
    """
    reset_logical_clock()
    base = setup_proposed_contract(program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS})
    contract_id = base["contract"]["id"]

    withdrawn = validate_success(api_client.withdraw_contract(
        contract_id, {"withdrawal_reason": "Supplier lost the room block"}, SM,
    ))
    assert withdrawn["status"] == "WITHDRAWN"
    frozen_version = withdrawn["version"]

    validate_error(
        api_client.negotiate_contract(contract_id, negotiate_payload("PROPOSE"), SM),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID, 409,
    )
    validate_error(
        api_client.negotiate_contract(contract_id, negotiate_payload("COUNTER"), CA),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID, 409,
    )
    validate_error(
        api_client.execute_contract(contract_id, CA),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID, 409,
    )
    validate_error(
        api_client.withdraw_contract(contract_id, {"withdrawal_reason": "Second try"}, SM),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID, 409,
    )

    after = read_contract(contract_id)
    assert after["status"] == "WITHDRAWN"
    assert after["withdrawal_reason"] == "Supplier lost the room block"
    assert after["executed_by_user_id"] is None
    assert_version_is(after, frozen_version, "SupplierContract")


def test_a_milestone_cancelled_by_withdrawal_refuses_payment():
    """A milestone cascaded to CANCELLED is terminal and reports the milestone error.

    PRD §3.5: "A milestone that is not `SCHEDULED` when payment is attempted
    reports `ERR_MILESTONE_STATE_INVALID`."

    Design: Corner/state_machines/terminal_states_accept_no_further_transitions
    """
    reset_logical_clock()
    base = setup_proposed_contract(program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS})
    contract_id = base["contract"]["id"]
    milestone = create_milestone(
        contract_id, sequence=1,
        due_at="2026-08-15T00:00:00Z", amount_cents=577500, refundable_bp=10000,
    )
    validate_success(api_client.withdraw_contract(
        contract_id, {"withdrawal_reason": "Deadlocked negotiation"}, SM,
    ))

    cancelled = read_milestone(milestone["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["paid_at"] is None

    # Priority 11 (target entity state) outranks priority 12 (the contract guard).
    validate_error(
        api_client.pay_deposit_milestone(milestone["id"], CA),
        ApiErrorId.ERR_MILESTONE_STATE_INVALID, 409,
    )
    after = read_milestone(milestone["id"])
    assert after["status"] == "CANCELLED"
    assert after["paid_at"] is None
    assert_version_is(after, cancelled["version"], "DepositMilestone")


def test_a_disqualified_qualifier_cannot_be_re_adjudicated():
    """DISQUALIFIED is terminal on the award axis, so a re-review is refused.

    PRD §3.2: "The award track, `award_status`, runs through `PENDING_REVIEW`,
    `QUALIFIED`, `DISQUALIFIED`, `NOTIFIED`, `REGISTERED`, `TRAVELLED` and
    `WITHDRAWN`, with `DISQUALIFIED`, `TRAVELLED` and `WITHDRAWN` terminal."

    Design: Corner/state_machines/terminal_states_accept_no_further_transitions
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)
    create_award_tier(program["id"], **GOLD_TIER)
    # One cent short of the only rung on the ladder: the eligible pool is empty.
    qualifier = create_qualifier(
        program["id"], baseline_metric=140000000, actual_metric=149999999,
    )
    disqualified = review_qualifier(qualifier["id"])
    assert disqualified["award_status"] == "DISQUALIFIED"

    validate_error(
        api_client.review_qualifier(qualifier["id"], AN),
        ApiErrorId.ERR_QUALIFIER_STATE_INVALID, 409,
    )
    after = read_qualifier(qualifier["id"])
    assert after["award_status"] == "DISQUALIFIED"
    assert after["assigned_tier_id"] is None
    assert after["committed_cost_cents"] == 0
    assert_version_is(after, disqualified["version"], "Qualifier")


def test_a_declined_seat_refuses_both_confirmation_and_cancellation():
    """DECLINED is terminal on the attendance axis, whichever trigger arrives next.

    PRD §3.6: "Attendance runs `INVITED`, `ACCEPTED`, `DECLINED`, `CONFIRMED`,
    `CANCELLED` and `TRAVELLED`, with `DECLINED`, `CANCELLED` and `TRAVELLED`
    terminal."

    Design: Corner/state_machines/terminal_states_accept_no_further_transitions
    """
    reset_logical_clock()
    base = setup_invited_registration()
    seat_id = base["registration"]["id"]
    declined = respond_registration(seat_id, base["qualifier"]["id"], response="DECLINE")
    assert declined["attendance_status"] == "DECLINED"

    validate_error(
        api_client.confirm_registration(seat_id, TD),
        ApiErrorId.ERR_REGISTRATION_STATE_INVALID, 409,
    )
    validate_error(
        api_client.cancel_registration(seat_id, {"cancellation_reason": "Changed plans"}, TD),
        ApiErrorId.ERR_REGISTRATION_STATE_INVALID, 409,
    )
    after = read_registration(seat_id)
    assert after["attendance_status"] == "DECLINED"
    assert after["room_nights"] == 0
    assert_version_is(after, declined["version"], "Registration")


# ═══════════════════════════════════════════════════════════════════════════
# replaying_an_already_applied_trigger_is_rejected_not_silently_absorbed
# ═══════════════════════════════════════════════════════════════════════════

def test_replaying_shortlist_on_an_already_shortlisted_destination_is_rejected():
    """A duplicate shortlist errors rather than being absorbed as a no-op.

    PRD §3.3: "It requires the program to be in `DESIGN` or `SOURCING`, the
    destination to still be a `CANDIDATE`, and its `inspection_status` to be
    `INSPECTED`; a destination that is not a candidate or has never been inspected
    reports `ERR_DESTINATION_STATE_INVALID`."

    Design: Corner/state_machines/replaying_an_already_applied_trigger_is_rejected_not_silently_absorbed
    """
    reset_logical_clock()
    base = setup_sourcing_program(program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS})
    destination = base["destination"]
    assert destination["status"] == "SHORTLISTED"

    validate_error(
        api_client.shortlist_destination(destination["id"], SM),
        ApiErrorId.ERR_DESTINATION_STATE_INVALID, 409,
    )
    after = read_destination(destination["id"])
    assert after["status"] == "SHORTLISTED"
    assert_version_is(after, destination["version"], "Destination")


def test_replaying_a_site_inspection_cannot_revise_the_recorded_score():
    """The inspection score is recorded once; a replay is refused, not overwritten.

    PRD §3.3: "A second inspection of the same destination is rejected with
    `ERR_DESTINATION_STATE_INVALID` — the score is recorded once and is not
    revisable."

    Design: Corner/state_machines/replaying_an_already_applied_trigger_is_rejected_not_silently_absorbed
    """
    reset_logical_clock()
    base = setup_sourcing_program(program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS})
    destination = base["destination"]
    recorded_score = destination["inspection_score"]
    assert recorded_score == TEST_DEFAULTS["INSPECTION_SCORE"]

    validate_error(
        api_client.site_inspect_destination(
            destination["id"], {"inspection_score": 95}, SM,
        ),
        ApiErrorId.ERR_DESTINATION_STATE_INVALID, 409,
    )
    after = read_destination(destination["id"])
    assert after["inspection_score"] == recorded_score, "The score is not revisable"
    assert after["inspection_status"] == "INSPECTED"
    assert_version_is(after, destination["version"], "Destination")


def test_replaying_execution_does_not_restamp_the_executing_approver():
    """A second execution is refused and leaves the first approver's stamp intact.

    PRD §3.4: "It is only available from `PROPOSED` — executing a `DRAFT`, a
    `COUNTERED`, an already-`EXECUTED` or a `WITHDRAWN` contract reports
    `ERR_CONTRACT_STATE_INVALID`"

    Design: Corner/state_machines/replaying_an_already_applied_trigger_is_rejected_not_silently_absorbed
    """
    reset_logical_clock()
    base = setup_contracted_program(program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS})
    contract = base["contract"]
    assert contract["status"] == "EXECUTED"
    assert contract["executed_by_user_id"] == USER_IDS["CONTRACT_APPROVER"]
    assert contract["room_nights_blocked"] == ROOM_NIGHTS_BLOCKED

    # A different approver, so only the replay itself can be the failure.
    validate_error(
        api_client.execute_contract(
            contract["id"],
            make_contract_approver_headers(USER_IDS["CONTRACT_APPROVER_ALT"]),
        ),
        ApiErrorId.ERR_CONTRACT_STATE_INVALID, 409,
    )
    after = read_contract(contract["id"])
    assert after["status"] == "EXECUTED"
    assert after["executed_by_user_id"] == USER_IDS["CONTRACT_APPROVER"]
    assert after["room_nights_blocked"] == ROOM_NIGHTS_BLOCKED
    assert_room_nights_conserved(after)
    assert_version_is(after, contract["version"], "SupplierContract")


def test_replaying_adjudication_does_not_double_count_the_award_commitment():
    """A second review of a QUALIFIED row is refused and no rollup moves.

    PRD §3.2: "It is permitted only while the program is in `DESIGN`, `SOURCING`
    or `CONTRACTED` and only from `PENDING_REVIEW`; a qualifier that has already
    been adjudicated reports `ERR_QUALIFIER_STATE_INVALID`."

    Design: Corner/state_machines/replaying_an_already_applied_trigger_is_rejected_not_silently_absorbed
    """
    reset_logical_clock()
    base = setup_qualified_qualifier(
        program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS},
    )
    qualifier = base["qualifier"]
    program_before = read_program(base["program"]["id"])
    assert qualifier["award_status"] == "QUALIFIED"
    assert qualifier["committed_cost_cents"] == DEFAULT_COMMITTED_CENTS
    assert program_before["committed_budget_cents"] == DEFAULT_COMMITTED_CENTS
    assert program_before["qualified_count"] == 1

    validate_error(
        api_client.review_qualifier(qualifier["id"], AN),
        ApiErrorId.ERR_QUALIFIER_STATE_INVALID, 409,
    )

    after = read_qualifier(qualifier["id"])
    assert after["award_status"] == "QUALIFIED"
    assert after["assigned_tier_id"] == qualifier["assigned_tier_id"]
    assert after["committed_cost_cents"] == DEFAULT_COMMITTED_CENTS
    assert_version_is(after, qualifier["version"], "Qualifier")

    program_after = read_program(base["program"]["id"])
    assert program_after["committed_budget_cents"] == DEFAULT_COMMITTED_CENTS
    assert program_after["qualified_count"] == 1
    assert_version_is(program_after, program_before["version"], "Program")
    assert_budget_conserved(program_after)


# ═══════════════════════════════════════════════════════════════════════════
# program_cancellation_is_a_branching_edge_available_from_five_statuses
# ═══════════════════════════════════════════════════════════════════════════

def test_cancelling_a_contracted_program_withdraws_its_notified_qualifiers():
    """The cancel branch out of CONTRACTED lands CANCELLED and withdraws the cohort.

    PRD §3.9: "Every qualifier of the program whose `award_status` is `QUALIFIED`,
    `NOTIFIED` or `REGISTERED` moves to `WITHDRAWN`. Qualifiers already
    `DISQUALIFIED`, `TRAVELLED` or `WITHDRAWN` are left alone."

    Design: Corner/state_machines/program_cancellation_is_a_branching_edge_available_from_five_statuses
    """
    reset_logical_clock()
    base = setup_qualified_qualifier(
        program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS},
    )
    program_id = base["program"]["id"]
    notify_qualifiers(program_id)
    qualifier_before = read_qualifier(base["qualifier"]["id"])
    assert qualifier_before["award_status"] == "NOTIFIED"
    program_before = read_program(program_id)
    assert program_before["status"] == "CONTRACTED"

    cancelled = cancel_program(program_id, reason="Client pulled the incentive")

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "Client pulled the incentive"
    assert cancelled["version"] == program_before["version"] + 1
    assert_budget_conserved(cancelled)

    qualifier_after = read_qualifier(base["qualifier"]["id"])
    assert qualifier_after["award_status"] == "WITHDRAWN"
    assert qualifier_after["committed_cost_cents"] == 0
    assert qualifier_after["version"] == qualifier_before["version"] + 1


def test_program_cancellation_settles_the_deposit_schedule_three_ways():
    """Step 5 forks on milestone status and maturity: FORFEITED, REFUNDED, CANCELLED.

    PRD §3.9: "a `PAID` milestone whose `due_at` is at or before the current
    logical instant moves to `FORFEITED`, a `PAID` milestone whose `due_at` is
    still in the future moves to `REFUNDED`, and a `SCHEDULED` milestone moves to
    `CANCELLED`."

    Design: Corner/state_machines/program_cancellation_is_a_branching_edge_available_from_five_statuses
    """
    reset_logical_clock()
    base = setup_contract_with_schedule(
        [
            {"sequence": 1, "due_at": "2026-08-15T00:00:00Z",
             "amount_cents": 577500, "refundable_bp": 10000},
            {"sequence": 2, "due_at": "2026-09-15T00:00:00Z",
             "amount_cents": 577500, "refundable_bp": 5000},
            {"sequence": 3, "due_at": "2026-10-15T00:00:00Z",
             "amount_cents": 1155000, "refundable_bp": 0},
        ],
        program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS},
        execute=True,
        pay_sequences=[1, 2],
    )
    # Between the two paid due dates: sequence 1 has matured, sequence 2 has not.
    set_logical_clock("2026-09-01T00:00:00Z")

    cancel_program(base["program"]["id"], reason="Force majeure at destination")

    settled = {m["sequence"]: read_milestone(m["id"]) for m in base["milestones"]}
    assert settled[1]["status"] == "FORFEITED"
    assert settled[2]["status"] == "REFUNDED"
    assert settled[3]["status"] == "CANCELLED"
    for sequence, milestone in settled.items():
        assert milestone["version"] > base["milestones"][sequence - 1]["version"]

    # The contract itself is not a target of the cascade.
    assert read_contract(base["contract"]["id"])["status"] == "EXECUTED"


def test_a_cancelled_program_accepts_neither_a_forward_advance_nor_a_second_cancel():
    """CANCELLED is terminal, so both the lifecycle edge and the branch are closed.

    PRD §3.9: "A `RECONCILED` or `CLOSED` program cannot be cancelled — the trip
    has already happened — and that attempt reports `ERR_PROGRAM_STATE_INVALID`, as
    does cancelling an already-`CANCELLED` program."

    Design: Corner/state_machines/program_cancellation_is_a_branching_edge_available_from_five_statuses
    """
    reset_logical_clock()
    base = setup_contracted_program(program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS})
    program_id = base["program"]["id"]
    lock_gross_up_policy(program_id, "NONE")
    cancelled = cancel_program(program_id, reason="Budget frozen")
    assert cancelled["status"] == "CANCELLED"

    validate_error(
        api_client.advance_program(program_id, advance_payload("REGISTRATION_OPEN"), PD),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID, 409,
    )
    validate_error(
        api_client.cancel_program(program_id, {"cancellation_reason": "Again"}, PD),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID, 409,
    )
    after = read_program(program_id)
    assert after["status"] == "CANCELLED"
    assert after["cancellation_reason"] == "Budget frozen"
    assert_version_is(after, cancelled["version"], "Program")


def test_the_cancel_branch_is_available_from_design_with_no_downstream_rows():
    """DESIGN is one of the five statuses the branch leaves from.

    PRD §3.9: "It is available from `DESIGN`, `SOURCING`, `CONTRACTED`,
    `REGISTRATION_OPEN` and `ONSITE`."

    Design: Corner/state_machines/program_cancellation_is_a_branching_edge_available_from_five_statuses
    """
    reset_logical_clock()
    program = create_program(budget_total_cents=PROGRAM_BUDGET_CENTS)

    cancelled = cancel_program(program["id"], reason="Charter abandoned in design")

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "Charter abandoned in design"
    assert_version_is(cancelled, 2, "Program")


def test_a_reconciled_program_cannot_be_cancelled():
    """RECONCILED sits outside the branch's five source statuses.

    PRD §3.9: "A `RECONCILED` or `CLOSED` program cannot be cancelled — the trip
    has already happened — and that attempt reports `ERR_PROGRAM_STATE_INVALID`"

    Design: Corner/state_machines/program_cancellation_is_a_branching_edge_available_from_five_statuses
    """
    reset_logical_clock()
    base = setup_reconciled_program()
    program_before = read_program(base["program"]["id"])
    assert program_before["status"] == "RECONCILED"

    validate_error(
        api_client.cancel_program(
            program_before["id"], {"cancellation_reason": "Too late"}, PD,
        ),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID, 409,
    )
    after = read_program(program_before["id"])
    assert after["status"] == "RECONCILED"
    assert after["cancellation_reason"] is None
    assert_version_is(after, program_before["version"], "Program")


# ═══════════════════════════════════════════════════════════════════════════
# closing_registration_cancels_only_the_invited_rows
# ═══════════════════════════════════════════════════════════════════════════

# Winner A occupies one room from 2026-11-02 up to (not including) 2026-11-06.
COHORT_ROOM_NIGHTS_CONFIRMED = 4


def _build_three_seat_cohort() -> dict:
    """REGISTRATION_OPEN program holding one CONFIRMED, one ACCEPTED and one INVITED seat."""
    reset_logical_clock()
    base = setup_registration_open_program(
        num_qualifiers=2,
        qualifier_specs=[
            {"employee_code": "S-1001", "full_name": "Ana Reyes"},
            {"employee_code": "S-2001", "full_name": "Bruno Costa"},
        ],
        program_overrides={"budget_total_cents": PROGRAM_BUDGET_CENTS},
    )
    qualifier_a, qualifier_b = base["qualifiers"]

    # PRD §3.6 gates enrolment on the qualifier's award_status being exactly
    # NOTIFIED, and confirming a WINNER seat moves that qualifier
    # NOTIFIED -> REGISTERED (§3.7). Both of Ana's seats must therefore be
    # created while she is still NOTIFIED — the guest seat before the winner
    # seat is confirmed.
    winner_a = enrol_and_confirm(base, qualifier_a, confirm=False)
    guest_a = create_registration(
        qualifier_a["id"], program_id=base["program"]["id"],
        registration_kind="GUEST", guest_of_registration_id=winner_a["id"],
    )
    respond_registration(guest_a["id"], qualifier_a["id"], "ACCEPT")
    confirm_registration(winner_a["id"])
    winner_b = create_registration(qualifier_b["id"], program_id=base["program"]["id"])

    base["qualifier_a"], base["qualifier_b"] = qualifier_a, qualifier_b
    base["confirmed_seat"] = read_registration(winner_a["id"])
    base["accepted_seat"] = read_registration(guest_a["id"])
    base["invited_seat"] = read_registration(winner_b["id"])
    assert base["confirmed_seat"]["attendance_status"] == "CONFIRMED"
    assert base["accepted_seat"]["attendance_status"] == "ACCEPTED"
    assert base["invited_seat"]["attendance_status"] == "INVITED"
    return base


def test_closing_registration_cancels_the_invited_seat_with_the_literal_reason():
    """The ONSITE advance sweeps INVITED rows with a pinned cancellation reason.

    PRD §3.1: "every registration of the program still sitting at `INVITED` moves
    to `CANCELLED` with its `cancellation_reason` set to the literal string
    `REGISTRATION_WINDOW_CLOSED`, and each such row's `version` increments."

    Design: Corner/state_machines/closing_registration_cancels_only_the_invited_rows
    """
    base = _build_three_seat_cohort()
    invited_before = base["invited_seat"]

    advance_program(base["program"]["id"], "ONSITE")

    swept = read_registration(invited_before["id"])
    assert swept["attendance_status"] == "CANCELLED"
    assert swept["cancellation_reason"] == "REGISTRATION_WINDOW_CLOSED"
    assert swept["version"] == invited_before["version"] + 1


def test_closing_registration_leaves_confirmed_and_accepted_seats_untouched():
    """The sweep is selective: only INVITED rows move, and the others do not.

    PRD §3.1: "every registration of the program still sitting at `INVITED` moves
    to `CANCELLED` with its `cancellation_reason` set to the literal string
    `REGISTRATION_WINDOW_CLOSED`, and each such row's `version` increments."

    Design: Corner/state_machines/closing_registration_cancels_only_the_invited_rows
    """
    base = _build_three_seat_cohort()
    confirmed_before = base["confirmed_seat"]
    accepted_before = base["accepted_seat"]

    advance_program(base["program"]["id"], "ONSITE")

    confirmed_after = read_registration(confirmed_before["id"])
    assert confirmed_after["attendance_status"] == "CONFIRMED"
    assert confirmed_after["cancellation_reason"] is None
    assert_version_is(confirmed_after, confirmed_before["version"], "Registration")

    accepted_after = read_registration(accepted_before["id"])
    assert accepted_after["attendance_status"] == "ACCEPTED", (
        "An ACCEPTED seat is not INVITED, so the window sweep must not touch it"
    )
    assert accepted_after["cancellation_reason"] is None
    assert_version_is(accepted_after, accepted_before["version"], "Registration")


def test_closing_registration_moves_neither_the_ledger_nor_the_budget():
    """Sweeping an INVITED row releases no capacity and no money, since it held none.

    PRD §3.9: "Nothing else moves, because an invited seat never consumed capacity
    or budget."

    Design: Corner/state_machines/closing_registration_cancels_only_the_invited_rows
    """
    base = _build_three_seat_cohort()
    contract_before = read_contract(base["contract"]["id"])
    program_before = read_program(base["program"]["id"])
    assert contract_before["room_nights_confirmed"] == COHORT_ROOM_NIGHTS_CONFIRMED

    advance_program(base["program"]["id"], "ONSITE")

    contract_after = read_contract(base["contract"]["id"])
    assert contract_after["room_nights_blocked"] == ROOM_NIGHTS_BLOCKED
    assert contract_after["room_nights_confirmed"] == COHORT_ROOM_NIGHTS_CONFIRMED
    assert contract_after["room_nights_available"] == (
        ROOM_NIGHTS_BLOCKED - COHORT_ROOM_NIGHTS_CONFIRMED
    )
    assert_room_nights_conserved(contract_after)

    program_after = read_program(base["program"]["id"])
    assert program_after["committed_budget_cents"] == program_before["committed_budget_cents"]
    assert program_after["budget_headroom_cents"] == program_before["budget_headroom_cents"]
    assert_budget_conserved(program_after)

    # The sweep is a registration-axis cascade; the qualifier axis is not in it.
    assert read_qualifier(base["qualifier_b"]["id"])["award_status"] == "NOTIFIED"


# ═══════════════════════════════════════════════════════════════════════════
# voiding_a_filed_tax_report_exactly_reverses_the_program_reported_total
# ═══════════════════════════════════════════════════════════════════════════

def _build_gold_drafted_report() -> dict:
    """A RECONCILED GOLD winner with a FULL_GROSS_UP draft on the pinned figures."""
    reset_logical_clock()
    base = setup_drafted_tax_report(
        gross_up_policy="FULL_GROSS_UP",
        program_overrides={"budget_total_cents": SMALL_BUDGET_CENTS},
        tier_overrides=dict(GOLD_TIER),
        destination_overrides={"per_person_cost_cents": LISBON_BASIS_CENTS},
    )
    assert base["qualifier"]["committed_cost_cents"] == GOLD_COMMITTED_CENTS
    assert base["qualifier"]["taxable_award_cents"] == GOLD_TAXABLE_CENTS
    assert base["report"]["award_value_cents"] == GOLD_TAXABLE_CENTS
    assert base["report"]["reported_value_cents"] == GOLD_REPORTED_VALUE_CENTS
    assert base["report"]["gross_up_cents"] == GOLD_GROSS_UP_CENTS
    assert_reported_value_identity(base["report"])
    return base


def test_voiding_returns_the_program_reported_total_to_its_pre_filing_value():
    """Filing adds the reported value and voiding subtracts exactly the same figure.

    PRD §3.9: "subtracts the report's `reported_value_cents` from the program's
    `reported_award_total_cents` — an exact compensation, so that
    `reported_award_total_cents` always equals the sum of `reported_value_cents`
    over the program's reports that are currently `FILED`."

    Design: Corner/state_machines/voiding_a_filed_tax_report_exactly_reverses_the_program_reported_total
    """
    base = _build_gold_drafted_report()
    program_id = base["program"]["id"]
    report_id = base["report"]["id"]

    before_filing = read_program(program_id)["reported_award_total_cents"]
    assert before_filing == 0

    filed = file_tax_report(report_id)
    assert filed["status"] == "FILED"
    assert filed["filed_by_user_id"] == USER_IDS["TAX_OFFICER"]
    assert_instant_equals(filed["filed_at"], LOGICAL_CLOCK_DEFAULT, "TaxAwardReport.filed_at")
    after_filing = read_program(program_id)["reported_award_total_cents"]
    assert after_filing == GOLD_REPORTED_VALUE_CENTS
    assert read_qualifier(base["qualifier"]["id"])["tax_status"] == "REPORTED"

    voided = void_tax_report(report_id, reason="Filed against the wrong tax year")
    assert voided["status"] == "VOIDED"
    assert voided["voided_by_user_id"] == USER_IDS["TAX_OFFICER_ALT"]
    assert voided["void_reason"] == "Filed against the wrong tax year"

    after_voiding = read_program(program_id)["reported_award_total_cents"]
    assert after_voiding == before_filing, (
        f"Void must exactly reverse the filing: {before_filing} -> {after_filing} -> "
        f"{after_voiding}"
    )
    assert read_qualifier(base["qualifier"]["id"])["tax_status"] == "VOIDED"


def test_the_filer_cannot_void_their_own_filing_and_nothing_reverses():
    """A self-void is refused, so the reported total keeps the filed value.

    PRD §3.9: "The acting `X-User-ID` must differ from the report's
    `filed_by_user_id`, or the attempt reports `ERR_TAX_VOID_SELF_REVIEW`."

    Design: Corner/state_machines/voiding_a_filed_tax_report_exactly_reverses_the_program_reported_total
    """
    base = _build_gold_drafted_report()
    program_id = base["program"]["id"]
    report_id = base["report"]["id"]
    filed = file_tax_report(report_id, filer_user_id=USER_IDS["TAX_OFFICER"])

    response = api_client.void_tax_award_report(
        report_id, {"void_reason": "Second thoughts"},
        make_tax_officer_headers(USER_IDS["TAX_OFFICER"]),
    )
    validate_error(response, ApiErrorId.ERR_TAX_VOID_SELF_REVIEW, 422)

    after = read_tax_report(report_id)
    assert after["status"] == "FILED"
    assert after["voided_by_user_id"] is None
    assert after["void_reason"] is None
    assert_version_is(after, filed["version"], "TaxAwardReport")
    assert read_program(program_id)["reported_award_total_cents"] == GOLD_REPORTED_VALUE_CENTS
    assert read_qualifier(base["qualifier"]["id"])["tax_status"] == "REPORTED"


def test_a_replacement_draft_after_a_void_reopens_the_tax_cycle():
    """Voiding leaves the taxable base intact and a replacement draft reopens the cycle.

    PRD §3.9: "If the qualifier's `tax_status` was `VOIDED` at that moment, drafting
    a replacement moves it `VOIDED → PENDING_REPORT`, which is what closes the tax
    cycle and lets a mis-filed award be corrected before the program is closed."

    Design: Corner/state_machines/voiding_a_filed_tax_report_exactly_reverses_the_program_reported_total
    """
    base = _build_gold_drafted_report()
    qualifier_id = base["qualifier"]["id"]
    file_tax_report(base["report"]["id"])
    void_tax_report(base["report"]["id"])

    voided_qualifier = read_qualifier(qualifier_id)
    assert voided_qualifier["tax_status"] == "VOIDED"
    assert voided_qualifier["taxable_award_cents"] == GOLD_TAXABLE_CENTS

    replacement = draft_tax_report(qualifier_id, base["program"]["fiscal_year"])
    assert replacement["status"] == "DRAFT"
    assert replacement["award_value_cents"] == GOLD_TAXABLE_CENTS
    assert replacement["reported_value_cents"] == GOLD_REPORTED_VALUE_CENTS
    assert read_qualifier(qualifier_id)["tax_status"] == "PENDING_REPORT"
    # The void already removed the filed value; a draft adds nothing back.
    assert read_program(base["program"]["id"])["reported_award_total_cents"] == 0


def test_a_voided_award_blocks_program_closure_until_it_is_refiled():
    """After the reversal the winner is no longer REPORTED, so CLOSED is refused.

    PRD §3.1: "Moving into `CLOSED` requires that every qualifier of the program
    whose `taxable_award_cents` is greater than 0 carries `tax_status` `REPORTED`,
    and a program with an unreported taxable award reports
    `ERR_TAX_REPORTING_INCOMPLETE` rather than the generic prerequisite error."

    Design: Corner/state_machines/voiding_a_filed_tax_report_exactly_reverses_the_program_reported_total
    """
    base = _build_gold_drafted_report()
    program_id = base["program"]["id"]
    file_tax_report(base["report"]["id"])
    void_tax_report(base["report"]["id"])
    program_before = read_program(program_id)

    validate_error(
        api_client.advance_program(program_id, advance_payload("CLOSED"), PD),
        ApiErrorId.ERR_TAX_REPORTING_INCOMPLETE, 422,
    )
    after = read_program(program_id)
    assert after["status"] == "RECONCILED"
    assert after["reported_award_total_cents"] == 0
    assert_version_is(after, program_before["version"], "Program")
