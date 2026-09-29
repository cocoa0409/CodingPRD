"""Three temporal shapes with three deliberately different conventions.

Coverage intervals are half-open per retiree, billing periods are closed per
enrollment, and a plan-change notice is a whole-day buffer with no second
interval at all.
"""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_1,
    BILLING_1,
    COUNSELOR_1,
    COUNSELOR_2,
    make_benefits_admin_headers,
    make_billing_clerk_headers,
    make_enrollment_counselor_headers,
)


def _open_ended_coverage_and_a_reviewed_marriage_election(api):
    """R1 covered from 2027-01-01 with no end date, plus a reviewed MARRIAGE
    election whose coverage would start 2027-03-01.

    Returns {"retiree_id", "plan_option_id", "enrollment_a", "marriage_election"}.
    The clock ends at 2027-02-10, inside the life-event window.
    """
    enrolled = fx.enrolled_retiree(api)
    enrollment_a = enrolled["enrollment"]
    assert enrollment_a["coverage_end_date"] is None

    fx.set_clock(api, "2027-02-10T00:00:00Z")
    fx.run_daily(api)
    enrollment_a = fx.reload_enrollment(api, enrollment_a["id"])
    assert enrollment_a["coverage_status"] == "ACTIVE"

    marriage = fx.make_election_event(
        api,
        enrolled["retiree"]["id"],
        enrolled["plan_year"]["id"],
        enrolled["pre65_core"]["id"],
        event_type="MARRIAGE",
        event_date="2027-02-05",
        review=True,
    )
    return {
        "retiree_id": enrolled["retiree"]["id"],
        "plan_option_id": enrolled["pre65_core"]["id"],
        "enrollment_a": enrollment_a,
        "marriage_election": marriage,
    }


def test_open_ended_coverage_blocks_a_later_overlapping_election(api):
    """An open-ended interval overlaps every later start, so approval is refused.

    PRD 3.5: "The two collide when the proposed start is strictly earlier than the
    existing end and the existing start is strictly earlier than the proposed
    end; on the first collision the approval is refused with
    `ERR_DUPLICATE_ENROLLMENT_PERIOD`." The candidate scope is deliberately wide:
    "The candidate set is **every** enrollment of the electing retiree, across
    every plan year and regardless of `coverage_status`". The proposed interval is
    fixed by PRD 3.5 for a life event: "`window_deadline` is the `event_date`
    taken at midnight UTC plus 31 days" and "Its `coverage_effective_date` is the
    first day of the calendar month **after** the month containing `event_date`".

    Design: Difficulty/resource_temporal_overlap/coverage_interval_half_open_adjacency_per_retiree
    """
    state = _open_ended_coverage_and_a_reviewed_marriage_election(api)
    election = state["marriage_election"]

    assert_instant_equals(
        election["window_deadline"], "2027-03-08T00:00:00.000Z", "window_deadline"
    )
    assert_instant_equals(
        election["coverage_effective_date"],
        "2027-03-01T00:00:00.000Z",
        "coverage_effective_date",
    )

    response = api.decide_election_event(
        election["id"],
        f.election_decision_payload("APPROVE"),
        make_enrollment_counselor_headers(COUNSELOR_2),
    )

    validate_error(
        response, ApiErrorId.ERR_DUPLICATE_ENROLLMENT_PERIOD.value, expected_status=409
    )

    unchanged = fx.reload_election_event(api, election["id"])
    assert unchanged["status"] == "UNDER_REVIEW"
    assert unchanged["resulting_enrollment_id"] is None
    assert fx.reload_plan_option(api, state["plan_option_id"])["enrolled_count"] == 1


def test_terminating_at_the_new_effective_instant_makes_the_intervals_adjacent(api):
    """Closing the first interval exactly where the second opens admits the retry.

    PRD 3.5: "Because the semantics are half-open, an existing enrollment whose
    `coverage_end_date` equals the proposed `coverage_effective_date` is adjacent,
    not overlapping, and the approval proceeds." Termination is what closes it:
    "Termination sets `coverage_status` to `TERMINATED`, closes the coverage
    interval by setting `coverage_end_date` to the logical clock, stores the
    supplied `termination_reason`, decrements the option's `enrolled_count` by 1".
    The terminated row remains a candidate for the overlap scan, so it must still
    be listed against the retiree afterwards.

    Design: Difficulty/resource_temporal_overlap/coverage_interval_half_open_adjacency_per_retiree
    """
    state = _open_ended_coverage_and_a_reviewed_marriage_election(api)
    election_id = state["marriage_election"]["id"]

    validate_error(
        api.decide_election_event(
            election_id,
            f.election_decision_payload("APPROVE"),
            make_enrollment_counselor_headers(COUNSELOR_2),
        ),
        ApiErrorId.ERR_DUPLICATE_ENROLLMENT_PERIOD.value,
        expected_status=409,
    )

    fx.set_clock(api, "2027-03-01T00:00:00Z")
    terminated = fx.terminate_enrollment(
        api,
        state["enrollment_a"]["id"],
        "PLAN_CHANGE_ON_MARRIAGE",
        make_enrollment_counselor_headers(COUNSELOR_1),
    )
    assert terminated["coverage_status"] == "TERMINATED"
    assert_instant_equals(
        terminated["coverage_end_date"], "2027-03-01T00:00:00.000Z", "coverage_end_date"
    )
    assert terminated["termination_reason"] == "PLAN_CHANGE_ON_MARRIAGE"
    assert fx.reload_plan_option(api, state["plan_option_id"])["enrolled_count"] == 0

    approved = validate_success(
        api.decide_election_event(
            election_id,
            f.election_decision_payload("APPROVE"),
            make_enrollment_counselor_headers(COUNSELOR_2),
        )
    )
    assert approved["status"] == "APPROVED"

    enrollment_b = fx.reload_enrollment(api, approved["resulting_enrollment_id"])
    assert_instant_equals(
        enrollment_b["coverage_effective_date"],
        "2027-03-01T00:00:00.000Z",
        "coverage_effective_date",
    )
    assert enrollment_b["coverage_status"] == "ACTIVE"
    assert fx.reload_plan_option(api, state["plan_option_id"])["enrolled_count"] == 1

    rows, meta = validate_paginated(
        api.list_enrollments(
            make_enrollment_counselor_headers(COUNSELOR_1),
            {"retiree_id": state["retiree_id"]},
        )
    )
    assert meta["total_count"] == 2
    assert sorted(fx.list_ids(rows)) == sorted(
        [state["enrollment_a"]["id"], enrollment_b["id"]]
    )


def _january_invoice_only(api):
    """R1 with a single ISSUED January invoice and the clock at 2027-01-05, so
    nothing has aged out of the overlap candidate set.

    Returns {"enrollment_id", "january_invoice"}.
    """
    enrolled = fx.enrolled_retiree(api)
    enrollment_id = enrolled["enrollment"]["id"]
    fx.set_clock(api, "2027-01-05T00:00:00Z")
    invoice = fx.make_invoice(
        api, enrollment_id, "2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z"
    )
    assert invoice["status"] == "ISSUED"
    assert invoice["net_due_cents"] == 15422
    return {"enrollment_id": enrollment_id, "january_invoice": invoice}


def test_billing_period_starting_on_the_prior_end_instant_is_a_collision(api):
    """Closed endpoints mean 2027-01-31 to 2027-02-28 collides with January.

    PRD 2.9: "**Billing periods** are closed on both ends. An invoice bills from
    `billing_period_start` inclusive through `billing_period_end` inclusive, and
    `billing_period_end` must be strictly later than `billing_period_start`. Two
    billing periods collide when the new period's start is not later than the
    existing period's end and the existing period's start is not later than the
    new period's end. The practical consequence is the opposite of the coverage
    rule: a new period whose start equals a prior period's end **is** a collision,
    so contiguous monthly billing must begin strictly after the prior period
    ends." No row is written, so the enrollment still has exactly one invoice.

    Design: Difficulty/resource_temporal_overlap/billing_period_closed_interval_touching_endpoints
    """
    state = _january_invoice_only(api)
    billing = make_billing_clerk_headers(BILLING_1)

    response = api.create_invoice(
        f.invoice_payload(
            state["enrollment_id"], "2027-01-31T00:00:00Z", "2027-02-28T00:00:00Z"
        ),
        billing,
    )

    validate_error(
        response, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP.value, expected_status=409
    )

    rows, meta = validate_paginated(
        api.list_invoices(billing, {"enrollment_id": state["enrollment_id"]})
    )
    assert meta["total_count"] == 1
    assert fx.list_ids(rows) == [state["january_invoice"]["id"]]


def test_billing_period_starting_strictly_after_the_prior_end_is_admitted(api):
    """February from the 1st clears January's closed end and bills identically.

    PRD 3.8 step 9: "`due_date` is `billing_period_start` plus 30 days.
    `past_due_at` is `due_date` plus the plan year's `premium_grace_period_days`,
    and it is the instant at which the nightly sweep will age the invoice." The
    period starts 2027-02-01, strictly after January's inclusive end, so the
    collision test passes and the waterfall reproduces the same 15422-cent net due
    on the unchanged 74500-cent premium with no reimbursement account to offset it.

    Design: Difficulty/resource_temporal_overlap/billing_period_closed_interval_touching_endpoints
    """
    state = _january_invoice_only(api)
    billing = make_billing_clerk_headers(BILLING_1)

    february = validate_success(
        api.create_invoice(
            f.invoice_payload(
                state["enrollment_id"], "2027-02-01T00:00:00Z", "2027-02-28T00:00:00Z"
            ),
            billing,
        ),
        expected_status=201,
    )

    assert_instant_equals(
        february["due_date"], "2027-03-03T00:00:00.000Z", "due_date"
    )
    assert_instant_equals(
        february["past_due_at"], "2027-04-03T00:00:00.000Z", "past_due_at"
    )
    assert february["net_due_cents"] == 15422
    assert february["hra_applied_cents"] == 0
    assert february["status"] == "ISSUED"

    rows, meta = validate_paginated(
        api.list_invoices(billing, {"enrollment_id": state["enrollment_id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(fx.list_ids(rows)) == sorted(
        [state["january_invoice"]["id"], february["id"]]
    )


def _active_option_awaiting_a_notice(api):
    """An ACTIVE PRE65-CORE with no staged change and the clock at 2026-10-20."""
    program = fx.standard_program(api)
    option = program["pre65_core"]
    assert option["status"] == "ACTIVE"
    assert option["change_notice_issued_at"] is None
    assert option["pending_change_type"] is None
    assert option["monthly_premium_cents"] == 74500
    return option


def test_change_notice_one_day_short_of_the_lead_buffer_is_refused(api):
    """59 whole days of separation is a shortfall and stages nothing.

    PRD 3.1: "Issuance is gated on lead time: taking the difference between
    `effective_date` and the logical clock and truncating it to whole
    86400-second days must yield at least the plan year's `notice_lead_days`, and
    a shortfall is refused with `ERR_NOTICE_LEAD_TIME_INSUFFICIENT`; a separation
    exactly equal to `notice_lead_days` is accepted." From 2026-10-20 to
    2026-12-18 is 59 whole days against a 60-day requirement, and the separation
    crosses two month boundaries so it cannot be reduced to month arithmetic.

    Design: Difficulty/resource_temporal_overlap/plan_change_notice_lead_time_buffer_separation
    """
    option = _active_option_awaiting_a_notice(api)

    response = api.issue_change_notice(
        option["id"],
        f.change_notice_payload("PREMIUM_INCREASE", "2026-12-18T00:00:00Z", 79900),
        make_benefits_admin_headers(ADMIN_1),
    )

    validate_error(
        response,
        ApiErrorId.ERR_NOTICE_LEAD_TIME_INSUFFICIENT.value,
        expected_status=422,
    )

    unchanged = fx.reload_plan_option(api, option["id"])
    assert unchanged["change_notice_issued_at"] is None
    assert unchanged["pending_change_type"] is None
    assert unchanged["pending_change_effective_date"] is None
    assert unchanged["pending_new_monthly_premium_cents"] is None
    assert unchanged["monthly_premium_cents"] == 74500


def test_change_notice_exactly_at_the_lead_buffer_stages_the_increase(api):
    """Exactly 60 whole days is admitted and only stages the change.

    PRD 3.1: "On admission the option records `change_notice_issued_at` at the
    logical clock, `pending_change_type`, `pending_change_effective_date` and
    `pending_new_monthly_premium_cents`, and nothing else changes yet — the
    announced change is applied later, by the nightly sweep, when the clock
    reaches the effective instant." The issued-at instant is therefore the clock
    2026-10-20 rather than the effective date, and monthly_premium_cents still
    reads the old 74500.

    Design: Difficulty/resource_temporal_overlap/plan_change_notice_lead_time_buffer_separation
    """
    option = _active_option_awaiting_a_notice(api)

    noticed = validate_success(
        api.issue_change_notice(
            option["id"],
            f.change_notice_payload("PREMIUM_INCREASE", "2026-12-19T00:00:00Z", 79900),
            make_benefits_admin_headers(ADMIN_1),
        )
    )

    assert_instant_equals(
        noticed["change_notice_issued_at"],
        "2026-10-20T00:00:00.000Z",
        "change_notice_issued_at",
    )
    assert noticed["pending_change_type"] == "PREMIUM_INCREASE"
    assert_instant_equals(
        noticed["pending_change_effective_date"],
        "2026-12-19T00:00:00.000Z",
        "pending_change_effective_date",
    )
    assert noticed["pending_new_monthly_premium_cents"] == 79900
    assert noticed["monthly_premium_cents"] == 74500
    assert noticed["status"] == "ACTIVE"
