"""Two-variant arithmetic: assignment pay and interpreter quality scores.

The PROVISIONAL and FINAL pay variants read one assignment row and diverge on the
window and the mileage they measure (PRD §3.7, §3.8); the rolling-12-month and
lifetime quality scores read one set of disciplinary rows and diverge on the
365-day lookback term (PRD §3.2).
"""

import test_helpers.fixtures as fixtures
from test_helpers import validate_success

# The scheduled window is 2026-09-10T09:00Z-11:00Z (2.00 h) and the served window
# runs from a 09:00Z check-in to a 12:10Z end (3h10m, billed as 3.25 h).
SERVED_CHECK_IN_CLOCK = "2026-09-10T09:00:00Z"
SERVED_ACTUAL_END_UTC = "2026-09-10T12:10:00.000Z"
ONE_WAY_MILES = 33.7

PROVISIONAL_BILLABLE_HOURS = 2.00
PROVISIONAL_SERVICE_CENTS = 17500
PROVISIONAL_TRAVEL_CENTS = 4550
PROVISIONAL_TOTAL_CENTS = 22050

FINAL_BILLABLE_HOURS = 3.25
FINAL_SERVICE_CENTS = 28438
FINAL_TRAVEL_CENTS = 4550
FINAL_TOTAL_CENTS = 32988
VARIANT_DIVERGENCE_CENTS = 10938

PAY_BUDGET_CENTS = 5_000_000

# Two sanction eras: the logical clock is monotonic, so the older sanction is
# recorded first and the clock then moves forward past the 365-day lookback.
OLD_SANCTION_CLOCK = "2026-08-01T00:00:00Z"
RECENT_SANCTION_CLOCK = "2027-08-02T00:00:00Z"
PROBATION_POINTS = 10
LETTER_POINTS = 5


def _confirmed_assignment_bundle():
    """Config + ACTIVE CERTIFIED interpreter + hearing + CONFIRMED assignment."""
    return fixtures.setup_confirmed_assignment(
        assignment_overrides={"estimated_one_way_miles": ONE_WAY_MILES},
    )


def _served_assignment_bundle():
    """The same bundle driven through check-in and completion."""
    return fixtures.setup_served_assignment(
        SERVED_CHECK_IN_CLOCK,
        SERVED_ACTUAL_END_UTC,
        ONE_WAY_MILES,
        assignment_overrides={"estimated_one_way_miles": ONE_WAY_MILES},
    )


def _interpreter_with_older_and_recent_sanctions():
    """One PROBATION dated 2026-08-01 and one LETTER dated 2027-08-02."""
    fixtures.set_clock(OLD_SANCTION_CLOCK)
    interpreter = fixtures.enrol_interpreter()
    fixtures.setup_sanction(
        interpreter["id"], "PROBATION", severity="MAJOR",
        category="PROFESSIONALISM",
        narrative="Repeated late arrival to the arraignment calendar.",
    )
    fixtures.set_clock(RECENT_SANCTION_CLOCK)
    fixtures.setup_sanction(
        interpreter["id"], "LETTER", severity="MINOR", category="ACCURACY",
        narrative="Omitted a qualifier during a plea colloquy.",
    )
    return interpreter


def test_provisional_variant_bills_the_scheduled_window_at_confirmation():
    """PRD §3.7: "The claim is created in `ENCUMBERED` status with `variant` set to
    `PROVISIONAL` and its `provisional_total_cents` computed by the provisional
    arithmetic of §3.8; the courthouse's `encumbered_pay_cents` and
    `available_pay_cents` are recomputed; the hearing bubbles `SCHEDULED → COVERED`;
    and the assignment's `version` is incremented by 1."
    PRD §3.8: "The `PROVISIONAL` variant measures the *scheduled* window, from the
    hearing's `scheduled_start` up to but not including its `scheduled_end`, and takes
    its mileage from the assignment's `estimated_one_way_miles`."
    PRD §3.8: "Then take the larger of that rounded figure and the rate schedule's
    `minimum_call_hours`; the result is `billable_hours`, always a multiple of 0.25 and
    always carried to two decimal places."
    PRD §3.8: "Multiply `billable_hours` by the selected hourly rate and then by the
    multiplier, and round the product to whole cents half up; that is `service_cents`."
    PRD §3.8: "Otherwise the reimbursable mileage is twice the one-way figure, because
    the interpreter drives there and back once past the radius."

    Design: Difficulty/dual_variant_calc/provisional_then_final_assignment_pay_diverges_on_served_window
    """
    bundle = _confirmed_assignment_bundle()
    claim = bundle["pay_claim"]

    assert claim["variant"] == "PROVISIONAL", (
        f"expected variant PROVISIONAL, got {claim['variant']} on the encumbrance claim"
    )
    assert claim["status"] == "ENCUMBERED", (
        f"expected status ENCUMBERED, got {claim['status']} after confirm"
    )
    assert claim["billable_hours"] == PROVISIONAL_BILLABLE_HOURS, (
        f"expected billable_hours {PROVISIONAL_BILLABLE_HOURS}, got "
        f"{claim['billable_hours']} for the 09:00-11:00 scheduled window"
    )
    assert claim["service_cents"] == PROVISIONAL_SERVICE_CENTS, (
        f"expected service_cents {PROVISIONAL_SERVICE_CENTS}, got {claim['service_cents']}"
    )
    assert claim["rare_premium_cents"] == 0, (
        f"expected rare_premium_cents 0 for a DESIGNATED language, got "
        f"{claim['rare_premium_cents']}"
    )
    assert claim["travel_cents"] == PROVISIONAL_TRAVEL_CENTS, (
        f"expected travel_cents {PROVISIONAL_TRAVEL_CENTS}, got {claim['travel_cents']} "
        f"for {ONE_WAY_MILES} one-way estimated miles"
    )
    assert claim["provisional_total_cents"] == PROVISIONAL_TOTAL_CENTS, (
        f"expected provisional_total_cents {PROVISIONAL_TOTAL_CENTS}, got "
        f"{claim['provisional_total_cents']}"
    )
    assert claim["final_total_cents"] is None, (
        f"final_total_cents must stay null while the claim is ENCUMBERED, got "
        f"{claim['final_total_cents']}"
    )

    courthouse = fixtures.read_courthouse(bundle["courthouse"]["id"])
    assert courthouse["encumbered_pay_cents"] == PROVISIONAL_TOTAL_CENTS, (
        f"expected encumbered_pay_cents {PROVISIONAL_TOTAL_CENTS}, got "
        f"{courthouse['encumbered_pay_cents']} after confirm"
    )
    assert courthouse["obligated_pay_cents"] == 0, (
        f"expected obligated_pay_cents 0 before completion, got "
        f"{courthouse['obligated_pay_cents']}"
    )
    assert courthouse["available_pay_cents"] == PAY_BUDGET_CENTS - PROVISIONAL_TOTAL_CENTS, (
        f"expected available_pay_cents {PAY_BUDGET_CENTS - PROVISIONAL_TOTAL_CENTS}, got "
        f"{courthouse['available_pay_cents']}"
    )
    assert bundle["hearing"]["status"] == "COVERED", (
        f"expected hearing status COVERED, got {bundle['hearing']['status']} after confirm"
    )


def test_final_variant_bills_the_served_window_and_diverges_from_the_provisional_total():
    """PRD §3.8: "The `FINAL` variant measures the *served* window, from the
    assignment's `check_in_utc` up to but not including its `actual_end_utc`, and takes
    its mileage from `actual_one_way_miles`."
    PRD §3.8: "Multiply that figure by four, round the product *up* to the next whole
    number, and divide by four again — the effect is that any part-used quarter hour is
    billed as a whole quarter hour."
    PRD §3.8: "The `PROVISIONAL` variant writes that total to `provisional_total_cents`;
    the `FINAL` and `LATE_CANCELLATION` variants write it to `final_total_cents` and
    leave `provisional_total_cents` frozen at whatever the provisional run produced."
    PRD §3.8: "`FINAL` is computed at completion from the check-in-to-actual-end window
    and the reported mileage; it writes `final_total_cents`, releases the encumbrance and
    adds to `obligated_pay_cents`, and it diverges from the provisional figure whenever
    the served window or the reported mileage differs from what was scheduled or
    estimated."

    Design: Difficulty/dual_variant_calc/provisional_then_final_assignment_pay_diverges_on_served_window
    """
    bundle = _served_assignment_bundle()
    claim = bundle["pay_claim"]

    assert claim["variant"] == "FINAL", (
        f"expected variant FINAL, got {claim['variant']} after completion"
    )
    assert claim["status"] == "FINALIZED", (
        f"expected status FINALIZED, got {claim['status']} after completion"
    )
    assert claim["billable_hours"] == FINAL_BILLABLE_HOURS, (
        f"expected billable_hours {FINAL_BILLABLE_HOURS} for the 3h10m served window, "
        f"got {claim['billable_hours']}"
    )
    assert claim["service_cents"] == FINAL_SERVICE_CENTS, (
        f"expected service_cents {FINAL_SERVICE_CENTS}, got {claim['service_cents']}"
    )
    assert claim["travel_cents"] == FINAL_TRAVEL_CENTS, (
        f"expected travel_cents {FINAL_TRAVEL_CENTS}, got {claim['travel_cents']}"
    )
    assert claim["final_total_cents"] == FINAL_TOTAL_CENTS, (
        f"expected final_total_cents {FINAL_TOTAL_CENTS}, got {claim['final_total_cents']}"
    )
    assert claim["provisional_total_cents"] == PROVISIONAL_TOTAL_CENTS, (
        f"provisional_total_cents must stay frozen at {PROVISIONAL_TOTAL_CENTS}, got "
        f"{claim['provisional_total_cents']}"
    )
    divergence = claim["final_total_cents"] - claim["provisional_total_cents"]
    assert divergence == VARIANT_DIVERGENCE_CENTS, (
        f"expected the two variants to diverge by {VARIANT_DIVERGENCE_CENTS} cents, "
        f"got {divergence}"
    )
    assert bundle["assignment"]["service_status"] == "COMPLETED", (
        f"expected service_status COMPLETED, got {bundle['assignment']['service_status']}"
    )
    assert bundle["hearing"]["status"] == "SERVED", (
        f"expected hearing status SERVED, got {bundle['hearing']['status']}"
    )


def test_completion_migrates_the_encumbrance_into_the_obligation_and_pending_pay():
    """PRD §3.7: "For a rostered interpreter, completion also settles the money: the pay
    claim moves `ENCUMBERED → FINALIZED` with `variant` set to `FINAL` and
    `final_total_cents` computed by the final arithmetic of §3.8, the courthouse's
    `encumbered_pay_cents`, `obligated_pay_cents` and `available_pay_cents` are all
    recomputed, and the interpreter's `pending_pay_cents` is recomputed to include the
    newly finalized amount."
    PRD §2.9: "`obligated_pay_cents` is the sum of `final_total_cents` over every pay
    claim whose `status` is one of `FINALIZED`, `SUBMITTED`, `APPROVED`, or `PAID`,
    reached through the same assignment-to-hearing-to-courthouse path."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents`
    less `obligated_pay_cents`."
    PRD §3.2: "`pending_pay_cents` is the sum of `final_total_cents` over this
    interpreter's pay claims whose status is `FINALIZED`, `SUBMITTED`, or `APPROVED`, and
    `paid_pay_cents` is the same sum restricted to claims in `PAID`."

    Design: Difficulty/dual_variant_calc/provisional_then_final_assignment_pay_diverges_on_served_window
    """
    bundle = _served_assignment_bundle()

    courthouse = fixtures.read_courthouse(bundle["courthouse"]["id"])
    assert courthouse["encumbered_pay_cents"] == 0, (
        f"expected encumbered_pay_cents 0 once the claim left ENCUMBERED, got "
        f"{courthouse['encumbered_pay_cents']}"
    )
    assert courthouse["obligated_pay_cents"] == FINAL_TOTAL_CENTS, (
        f"expected obligated_pay_cents {FINAL_TOTAL_CENTS}, got "
        f"{courthouse['obligated_pay_cents']} after completion"
    )
    assert courthouse["available_pay_cents"] == PAY_BUDGET_CENTS - FINAL_TOTAL_CENTS, (
        f"expected available_pay_cents {PAY_BUDGET_CENTS - FINAL_TOTAL_CENTS}, got "
        f"{courthouse['available_pay_cents']}"
    )

    interpreter = fixtures.read_interpreter(bundle["interpreter"]["id"])
    assert interpreter["pending_pay_cents"] == FINAL_TOTAL_CENTS, (
        f"expected pending_pay_cents {FINAL_TOTAL_CENTS}, got "
        f"{interpreter['pending_pay_cents']} after the claim finalized"
    )
    assert interpreter["paid_pay_cents"] == 0, (
        f"expected paid_pay_cents 0 before any warrant is issued, got "
        f"{interpreter['paid_pay_cents']}"
    )


def test_rolling_twelve_month_score_counts_only_the_recent_sanction(
        api, quality_reviewer_third_headers):
    """PRD §3.2: "Take the current logical-clock date and subtract 365 days to obtain a
    cutoff; an action whose `effective_from` falls on or after that cutoff is *recent*,
    and an action whose `effective_from` falls strictly before it is *older* — the
    boundary is inclusive on the recent side, so an action dated exactly on the cutoff
    counts as recent."
    PRD §3.2: "Sum the points of the recent actions to obtain the recent-points figure and
    the points of the older actions to obtain the older-points figure."
    PRD §3.2: "Then `rolling_12_month_score` is 100 less four times the recent-points
    figure, floored at 0 so it never reports a negative number."
    PRD §3.2: "Each action contributes `points`, and points accrue by sanction type: a
    letter of instruction is worth 5 points, probation 10 points, a suspension 12 points,
    and a revocation 20 points."

    Design: Difficulty/dual_variant_calc/rolling_twelve_month_and_lifetime_quality_scores_diverge_on_same_rows
    """
    interpreter = _interpreter_with_older_and_recent_sanctions()

    scores = validate_success(
        api.get_quality_score(interpreter["id"], quality_reviewer_third_headers)
    )
    assert scores["recent_points"] == LETTER_POINTS, (
        f"expected recent_points {LETTER_POINTS} from the 2027-08-02 LETTER alone, got "
        f"{scores['recent_points']}"
    )
    assert scores["rolling_12_month_score"] == 100 - 4 * LETTER_POINTS, (
        f"expected rolling_12_month_score {100 - 4 * LETTER_POINTS}, got "
        f"{scores['rolling_12_month_score']}"
    )

    row = fixtures.read_interpreter(interpreter["id"])
    assert row["rolling_12_month_score"] == 100 - 4 * LETTER_POINTS, (
        f"expected the interpreter row to carry rolling_12_month_score "
        f"{100 - 4 * LETTER_POINTS}, got {row['rolling_12_month_score']}"
    )


def test_lifetime_score_adds_the_older_sanction_the_rolling_variant_ignores(
        api, quality_reviewer_third_headers):
    """PRD §3.2: "And `lifetime_score` is 100 less four times the recent-points figure
    less twice the older-points figure, also floored at 0."
    PRD §3.2: "Because the lifetime variant adds the older term while reading exactly the
    same rows, an interpreter carrying old sanctions always scores strictly lower on
    `lifetime_score` than on `rolling_12_month_score`, while an interpreter whose entire
    history is inside the last year scores identically on both."
    PRD §3.2: "Both are computed from the interpreter's disciplinary actions whose status
    is either `IN_EFFECT` or `EXPIRED`; a `RESCINDED` action is invisible to both."

    Design: Difficulty/dual_variant_calc/rolling_twelve_month_and_lifetime_quality_scores_diverge_on_same_rows
    """
    interpreter = _interpreter_with_older_and_recent_sanctions()
    expected_lifetime = 100 - 4 * LETTER_POINTS - 2 * PROBATION_POINTS

    scores = validate_success(
        api.get_quality_score(interpreter["id"], quality_reviewer_third_headers)
    )
    assert scores["older_points"] == PROBATION_POINTS, (
        f"expected older_points {PROBATION_POINTS} from the 2026-08-01 PROBATION, got "
        f"{scores['older_points']}"
    )
    assert scores["lifetime_score"] == expected_lifetime, (
        f"expected lifetime_score {expected_lifetime}, got {scores['lifetime_score']}"
    )
    assert scores["lifetime_score"] < scores["rolling_12_month_score"], (
        f"lifetime_score {scores['lifetime_score']} must be strictly lower than "
        f"rolling_12_month_score {scores['rolling_12_month_score']} for an interpreter "
        "carrying an older sanction"
    )

    row = fixtures.read_interpreter(interpreter["id"])
    assert row["lifetime_score"] == expected_lifetime, (
        f"expected the interpreter row to carry lifetime_score {expected_lifetime}, got "
        f"{row['lifetime_score']}"
    )


def test_complaint_points_sums_the_same_rows_without_decay_or_weighting(
        api, quality_reviewer_third_headers):
    """PRD §3.2: "The separate field `complaint_points` is the plain, unweighted sum of
    `points` over the same `IN_EFFECT` and `EXPIRED` rows, with no decay and no floor."
    PRD §3.2: "A dedicated computed read exposes the two side by side for one interpreter,
    returning `interpreter_id`, `rolling_12_month_score`, `lifetime_score`,
    `complaint_points`, and the two intermediate figures `recent_points` and
    `older_points` that the formula above derived."
    PRD §3.2: "`APPLICANT` is where enrolment leaves the interpreter."

    Design: Difficulty/dual_variant_calc/rolling_twelve_month_and_lifetime_quality_scores_diverge_on_same_rows
    """
    interpreter = _interpreter_with_older_and_recent_sanctions()
    expected_points = PROBATION_POINTS + LETTER_POINTS

    scores = validate_success(
        api.get_quality_score(interpreter["id"], quality_reviewer_third_headers)
    )
    assert scores["interpreter_id"] == interpreter["id"], (
        f"expected interpreter_id {interpreter['id']}, got {scores['interpreter_id']}"
    )
    assert scores["complaint_points"] == expected_points, (
        f"expected complaint_points {expected_points} (10 + 5, unweighted), got "
        f"{scores['complaint_points']}"
    )

    row = fixtures.read_interpreter(interpreter["id"])
    assert row["complaint_points"] == expected_points, (
        f"expected the interpreter row to carry complaint_points {expected_points}, got "
        f"{row['complaint_points']}"
    )
    assert row["roster_status"] == "APPLICANT", (
        f"expected roster_status APPLICANT — neither a letter nor probation moves roster "
        f"standing — got {row['roster_status']}"
    )
