"""Two entities whose state graphs are cyclic rather than linear.

An enrollment carries two orthogonal dimensions that advance independently and
revisit states they already left, and a determination walks
CERTIFIED -> UNDER_APPEAL -> CERTIFIED twice with two different outcomes.
"""
from test_helpers import assert_instant_equals, get_success_data
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    COMPLIANCE_1,
    COUNSELOR_1,
    make_compliance_officer_headers,
    make_enrollment_counselor_headers,
    make_retiree_headers,
)


def _billed_and_activated_enrollment(api):
    """R1 enrolled on PRE65-CORE with a January invoice, then aged to 2027-01-01
    and swept once so coverage has activated.

    Returns {"retiree_id", "enrollment", "invoice_id", "activation_run"}. The
    invoice is raised while the clock is still 2026-10-20, before any sweep, so
    the activation run is the enrollment's first state change.
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    option_id = program["pre65_core"]["id"]

    certified = fx.make_certified_retiree(api, plan_year_id, f.retiree_r1_payload())
    retiree_id = certified["retiree"]["id"]
    enrolled = fx.make_enrollment(api, retiree_id, plan_year_id, option_id)
    enrollment = enrolled["enrollment"]
    assert enrollment["coverage_status"] == "PENDING"
    assert enrollment["billing_status"] == "CURRENT"

    invoice = fx.make_invoice(
        api, enrollment["id"], "2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z"
    )
    assert invoice["net_due_cents"] == 15422
    assert_instant_equals(
        invoice["past_due_at"], "2027-03-03T00:00:00.000Z", "past_due_at"
    )

    fx.set_clock(api, "2027-01-01T00:00:00Z")
    activation_run = fx.run_daily(api)
    return {
        "retiree_id": retiree_id,
        "enrollment": fx.reload_enrollment(api, enrollment["id"]),
        "invoice_id": invoice["id"],
        "activation_run": activation_run,
    }


def test_coverage_activates_while_billing_stays_current_then_suspends(api):
    """(PENDING, CURRENT) -> (ACTIVE, CURRENT) -> (SUSPENDED, DELINQUENT).

    PRD 3.9: "Every enrollment whose `coverage_status` is `PENDING` and whose
    `coverage_effective_date` is at or before the clock moves to `ACTIVE`,
    processed in `created_at` ascending order." and "Its `billing_status` is
    untouched." The later sweep at 2027-03-05 then runs the delinquency chain:
    "Hop two, caused by hop one, touches the owning enrollment:
    `consecutive_unpaid_periods` increments by 1,
    `delinquency_first_unpaid_period_start` is set to that invoice's
    `billing_period_start` if it was previously null and left alone otherwise,
    and `billing_status` moves from `CURRENT` or `REINSTATED` to `DELINQUENT`."
    With only one unpaid period the chain stops there — hop four "fires only when
    `consecutive_unpaid_periods` has reached 3" — so lapse_date stays null.

    Design: Difficulty/non_linear_state_machine/enrollment_coverage_and_billing_dimensions_move_independently
    """
    state = _billed_and_activated_enrollment(api)
    activated = state["enrollment"]

    assert activated["coverage_status"] == "ACTIVE"
    assert activated["billing_status"] == "CURRENT"
    assert activated["consecutive_unpaid_periods"] == 0
    assert activated["delinquency_first_unpaid_period_start"] is None
    assert state["activation_run"]["activated_enrollment_count"] == 1
    assert state["activation_run"]["suspended_enrollment_count"] == 0

    fx.set_clock(api, "2027-03-05T00:00:00Z")
    swept = fx.run_daily(api)

    assert swept["processed_invoice_count"] == 1
    assert swept["suspended_enrollment_count"] == 1
    assert swept["lapsed_enrollment_count"] == 0

    invoice = fx.reload_invoice(api, state["invoice_id"])
    assert invoice["status"] == "PAST_DUE"

    delinquent = fx.reload_enrollment(api, activated["id"])
    assert delinquent["coverage_status"] == "SUSPENDED"
    assert delinquent["billing_status"] == "DELINQUENT"
    assert delinquent["consecutive_unpaid_periods"] == 1
    assert_instant_equals(
        delinquent["delinquency_first_unpaid_period_start"],
        "2027-01-01T00:00:00.000Z",
        "delinquency_first_unpaid_period_start",
    )
    assert delinquent["lapse_date"] is None
    assert delinquent["reinstatement_deadline"] is None
    assert delinquent["termination_reason"] is None


def test_full_payment_returns_coverage_to_active_and_billing_to_current(api):
    """Paying the past-due invoice closes the ACTIVE -> SUSPENDED -> ACTIVE cycle.

    PRD 3.8: "Full payment of an invoice that had aged into `PAST_DUE` unwinds
    delinquency. The owning enrollment's `consecutive_unpaid_periods` decrements
    by 1, and when it reaches 0 — equivalently, when no invoice on that
    enrollment is left in `PAST_DUE` — `billing_status` moves from `DELINQUENT`
    back to `CURRENT`, `delinquency_first_unpaid_period_start` is cleared to
    null, `coverage_status` moves from `SUSPENDED` back to `ACTIVE`, and the
    enrollment's `version` increments." The retiree pays in their own right, so
    the payment is posted as the `Retiree` who owns the enrollment.

    Design: Difficulty/non_linear_state_machine/enrollment_coverage_and_billing_dimensions_move_independently
    """
    state = _billed_and_activated_enrollment(api)
    enrollment_id = state["enrollment"]["id"]

    fx.set_clock(api, "2027-03-05T00:00:00Z")
    fx.run_daily(api)
    suspended = fx.reload_enrollment(api, enrollment_id)
    assert suspended["coverage_status"] == "SUSPENDED"
    assert suspended["billing_status"] == "DELINQUENT"

    paid = fx.pay_invoice(
        api,
        state["invoice_id"],
        15422,
        make_retiree_headers(state["retiree_id"]),
    )

    assert paid["status"] == "PAID"
    assert paid["paid_cents"] == 15422

    restored = fx.reload_enrollment(api, enrollment_id)
    assert restored["consecutive_unpaid_periods"] == 0
    assert restored["billing_status"] == "CURRENT"
    assert restored["coverage_status"] == "ACTIVE"
    assert restored["delinquency_first_unpaid_period_start"] is None
    assert restored["lapse_date"] is None
    assert restored["version"] > suspended["version"]


def _certified_ineligible_determination(api):
    """R3 with a CERTIFIED, INELIGIBLE determination for plan year 2027.

    Returns {"retiree_id", "determination"}. R3 carries 143 credited months, so
    service years are 11 and eligibility points 74 — one short of the threshold.
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    certified = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r3_payload())
    return {
        "retiree_id": certified["retiree"]["id"],
        "determination": certified["determination"],
    }


def test_appeal_reversal_flips_the_outcome_and_resynchronises_the_retiree(api):
    """CERTIFIED -> UNDER_APPEAL -> CERTIFIED turns INELIGIBLE into ELIGIBLE.

    PRD 3.4: "Opening the appeal moves `status` from `CERTIFIED` to
    `UNDER_APPEAL`, stores the `appeal_reason`, and — because the retiree's
    eligibility is no longer settled — returns the subject retiree's
    `eligibility_status` to `UNDETERMINED`, incrementing the retiree's `version`
    as well as the determination's." The reversal branch then applies: "`REVERSE`
    flips `outcome` — an `ELIGIBLE` determination becomes `INELIGIBLE` and an
    `INELIGIBLE` determination becomes `ELIGIBLE` — so the retiree's
    `eligibility_status` is resynchronised to the flipped verdict." The retiree
    opens the appeal in their own name, which the PRD permits because
    "`X-User-ID` must equal the determination's `retiree_id`".

    Design: Difficulty/non_linear_state_machine/determination_certified_appeal_reversal_cycle
    """
    state = _certified_ineligible_determination(api)
    determination = state["determination"]
    retiree_id = state["retiree_id"]

    assert determination["points"] == 74
    assert determination["outcome"] == "INELIGIBLE"
    assert determination["status"] == "CERTIFIED"
    assert fx.reload_retiree(api, retiree_id)["eligibility_status"] == "INELIGIBLE"

    appealed = get_success_data(
        api.appeal_determination(
            determination["id"],
            f.appeal_payload(
                "Two additional years of leased-employee service were omitted"
                " from the credited service record."
            ),
            make_retiree_headers(retiree_id),
        )
    )

    assert appealed["status"] == "UNDER_APPEAL"
    assert fx.reload_retiree(api, retiree_id)["eligibility_status"] == "UNDETERMINED"

    reversed_row = get_success_data(
        api.decide_appeal(
            determination["id"],
            f.appeal_decision_payload("REVERSE"),
            make_compliance_officer_headers(COMPLIANCE_1),
        )
    )

    assert reversed_row["status"] == "CERTIFIED"
    assert reversed_row["outcome"] == "ELIGIBLE"
    assert reversed_row["appeal_decision"] == "REVERSE"
    assert reversed_row["appeal_decided_by_user_id"] == COMPLIANCE_1
    assert fx.reload_retiree(api, retiree_id)["eligibility_status"] == "ELIGIBLE"


def test_second_appeal_cycle_upheld_leaves_the_reversed_outcome_standing(api):
    """The cycle repeats, and UPHOLD returns to CERTIFIED changing nothing.

    PRD 3.4: "The two branches differ in exactly one respect, and the difference
    is the whole point of the mechanism: `UPHOLD` leaves `outcome` as it stands,
    so the retiree returns to the eligibility they had before the appeal, while
    `REVERSE` flips `outcome`". The cycle itself is unbounded — "The
    `CERTIFIED → UNDER_APPEAL → CERTIFIED` cycle is repeatable without bound" —
    and the second appeal is opened by an `EnrollmentCounselor` acting for the
    retiree. Because a decision never re-runs the eligibility rules, `points`
    still reads 74 after both cycles even though the outcome now says ELIGIBLE.

    Design: Difficulty/non_linear_state_machine/determination_certified_appeal_reversal_cycle
    """
    state = _certified_ineligible_determination(api)
    determination_id = state["determination"]["id"]
    retiree_id = state["retiree_id"]

    get_success_data(
        api.appeal_determination(
            determination_id,
            f.appeal_payload(
                "Two additional years of leased-employee service were omitted"
                " from the credited service record."
            ),
            make_retiree_headers(retiree_id),
        )
    )
    get_success_data(
        api.decide_appeal(
            determination_id,
            f.appeal_decision_payload("REVERSE"),
            make_compliance_officer_headers(COMPLIANCE_1),
        )
    )

    second_appeal = get_success_data(
        api.appeal_determination(
            determination_id,
            f.appeal_payload("Plan sponsor requests a second-level review of the reversal."),
            make_enrollment_counselor_headers(COUNSELOR_1),
        )
    )

    assert second_appeal["status"] == "UNDER_APPEAL"
    assert second_appeal["outcome"] == "ELIGIBLE"
    assert fx.reload_retiree(api, retiree_id)["eligibility_status"] == "UNDETERMINED"

    upheld = get_success_data(
        api.decide_appeal(
            determination_id,
            f.appeal_decision_payload("UPHOLD"),
            make_compliance_officer_headers(COMPLIANCE_1),
        )
    )

    assert upheld["status"] == "CERTIFIED"
    assert upheld["outcome"] == "ELIGIBLE"
    assert upheld["appeal_decision"] == "UPHOLD"
    assert upheld["points"] == 74
    assert fx.reload_retiree(api, retiree_id)["eligibility_status"] == "ELIGIBLE"
