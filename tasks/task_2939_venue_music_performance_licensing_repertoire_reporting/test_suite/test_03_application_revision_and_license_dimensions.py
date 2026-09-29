"""
The two cyclic corners of the licensing lifecycle.

The first half pins the bounded revision cycle of a licence application: an
application may go round `RETURNED_FOR_REVISION -> SUBMITTED -> UNDER_REVIEW`
three times, and the fourth return leaves the cycle for a decline instead of
looping again.  The second half pins the two independent state dimensions a
single licence row carries: suspending coverage must not touch the billing
dimension, and paying the annual assessment in full must not restore coverage.
"""

from test_helpers import (
    APPLICATION_STATUS_DECLINED,
    APPLICATION_STATUS_UNDER_REVIEW,
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_STATUS_PAID,
    BILLING_INVOICED,
    BILLING_PAID,
    COVERAGE_ACTIVE,
    COVERAGE_SUSPENDED,
    DECLINE_REASON_REVISION_LIMIT_EXCEEDED,
    DISPOSITION_RETURN_FOR_REVISION,
    MAX_REVISION_ROUNDS,
    POSTURE_PARTIALLY_COVERED,
    POSTURE_UNCOVERED,
    RETURN_REASON_DECLARATION_MISMATCH,
    SHARE_BMI_BP,
    SUSPENSION_REASON_NONPAYMENT,
    accept_for_review,
    admin_headers,
    application_row,
    assert_assessment,
    assert_count,
    assert_coverage,
    assert_empty_list,
    assert_license_dimensions,
    assert_money,
    assert_venue_ledger,
    assessments_of_license,
    given_effective_schedule,
    given_licensed_venue,
    given_society,
    given_submitted_application,
    given_venue,
    license_row,
    payment_payload,
    review_payload,
    suspend_payload,
    validate_success,
    venue_operator_headers,
    venue_row,
)

# The verified annual fee of the 180-occupancy MIXED bar and grill for a 4600 bp
# society on an unadjusted schedule, derived through PRD §3.5: second-tier base
# 78000 plus occupancy 43200 plus cover 56700, scaled by 11000 bp and
# apportioned at 4600 bp.
_ANNUAL_FEE_CENTS = 90017

# The suspension case wants the annual term to contain the logical clock instant
# the server starts at, so the term opens exactly there.
_TERM_START_AT_CLOCK_START = "2026-08-01T00:00:00Z"


def _return_for_revision(api, application_id):
    """Review one application with the returning disposition."""
    return validate_success(
        api.review_application(
            application_id,
            review_payload(
                DISPOSITION_RETURN_FOR_REVISION,
                return_reason=RETURN_REASON_DECLARATION_MISMATCH,
            ),
            admin_headers(),
        )
    )


def _application_at_the_revision_limit(api):
    """Drive one application round the revision cycle until it sits at round 3.

    Returns the venue row and the application as it reads after the third
    resubmission has been accepted for review, so the caller is holding an
    `UNDER_REVIEW` application whose `revision_round` is at the maximum.
    """
    society = given_society(api)
    venue = given_venue(api)
    given_effective_schedule(api, society["id"], venue["venue_category"])
    application = given_submitted_application(api, venue, society["id"])
    operator = venue_operator_headers(venue["id"])
    for _ in range(MAX_REVISION_ROUNDS):
        accept_for_review(api, application["id"])
        _return_for_revision(api, application["id"])
        validate_success(api.submit_application(application["id"], operator))
    return venue, accept_for_review(api, application["id"])


def _suspended_license_world(api):
    """A venue with one ACTIVE, INVOICED licence whose term is already running."""
    return given_licensed_venue(
        api, requested_term_start=_TERM_START_AT_CLOCK_START
    )


def test_revision_cycle_three_returns_leave_the_application_under_review_at_round_three(api):
    """Three returns and three resubmissions raise the revision round to exactly 3.

    Each return increments the counter by one and each resubmission puts the
    application back in front of the reviewer, so after the third acceptance the
    application is under review with the counter standing at the maximum the
    contract allows.

    PRD §3.4: "That conversion, rather than a refusal, is the termination guard
    on the cycle `RETURNED_FOR_REVISION → SUBMITTED → UNDER_REVIEW →
    RETURNED_FOR_REVISION`; a fourth return declines the application."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_bounded_at_three_rounds
    """
    _venue, under_review = _application_at_the_revision_limit(api)

    assert under_review["status"] == APPLICATION_STATUS_UNDER_REVIEW, (
        "the third resubmission must be accepted back into review, "
        f"but the application reads {under_review['status']!r}"
    )
    assert_count(
        under_review["revision_round"], MAX_REVISION_ROUNDS, "revision_round"
    )
    assert under_review["decline_reason"] is None, (
        "an application still in the cycle carries no decline reason, "
        f"but read {under_review['decline_reason']!r}"
    )


def test_revision_cycle_fourth_return_declines_instead_of_looping(api):
    """The fourth return leaves the cycle for the terminal declined state.

    Reviewing an application that already sits at three revision rounds with the
    returning disposition does not loop a fourth time and is not refused either:
    it converts into a decline, and the revision counter stops where it was.

    PRD §3.4: "When the application's `revision_round` already equals 3, the very
    same request instead takes the application from `UNDER_REVIEW` to `DECLINED`
    with `decline_reason` set to `REVISION_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_bounded_at_three_rounds
    """
    _venue, under_review = _application_at_the_revision_limit(api)
    assert_count(
        under_review["revision_round"], MAX_REVISION_ROUNDS, "revision_round"
    )

    declined = _return_for_revision(api, under_review["id"])

    assert declined["status"] == APPLICATION_STATUS_DECLINED, (
        "a fourth return must decline the application, "
        f"but it reads {declined['status']!r}"
    )
    assert declined["decline_reason"] == DECLINE_REASON_REVISION_LIMIT_EXCEEDED, (
        "the decline reason must record the exhausted revision allowance, "
        f"but read {declined['decline_reason']!r}"
    )
    assert_count(declined["revision_round"], MAX_REVISION_ROUNDS, "revision_round")

    reread = application_row(api, under_review["id"])
    assert reread["status"] == APPLICATION_STATUS_DECLINED
    assert_count(reread["revision_round"], MAX_REVISION_ROUNDS, "revision_round")


def test_revision_cycle_declined_application_never_mints_a_license(api):
    """A declined application leaves no licence behind it.

    Only an approving review creates the licence row, so the application that
    ran out of revision rounds ends its life with nothing pinned to it.

    PRD §3.4: "`APPROVE` is the consequential one, and it departs only from
    `UNDER_REVIEW`."

    PRD §3.4: "The three terminal states of an application are `APPROVED`,
    `DECLINED` and `WITHDRAWN`."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_bounded_at_three_rounds
    """
    _venue, under_review = _application_at_the_revision_limit(api)

    declined = _return_for_revision(api, under_review["id"])
    assert declined["status"] == APPLICATION_STATUS_DECLINED

    assert_empty_list(
        api.list_licenses(admin_headers(), {"application_id": under_review["id"]})
    )


def test_dimensions_suspending_coverage_leaves_the_billing_dimension_invoiced(api):
    """Suspending coverage moves only the coverage dimension of the licence.

    An active, invoiced licence that is suspended for non-payment lands on
    `SUSPENDED` coverage while its billing dimension stays exactly where the
    activation invoice left it, and the supplied reason is recorded on the row.

    PRD §2.11: "The two advance independently on the same row: a licence may
    legitimately be `ACTIVE` and `DELINQUENT` at the same time, or `SUSPENDED`
    and `PAID`."

    PRD §3.7: "The licence's `coverage_status` becomes `SUSPENDED`, the supplied
    reason is stored, and its `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/license_coverage_and_billing_dimensions_move_independently
    """
    world = _suspended_license_world(api)
    licence = world["license"]
    assert_license_dimensions(licence, COVERAGE_ACTIVE, BILLING_INVOICED)
    assert_money(licence["annual_fee_cents"], _ANNUAL_FEE_CENTS, "annual_fee_cents")

    suspended = validate_success(
        api.suspend_license(
            licence["id"],
            suspend_payload(SUSPENSION_REASON_NONPAYMENT),
            admin_headers(),
        )
    )

    assert_license_dimensions(suspended, COVERAGE_SUSPENDED, BILLING_INVOICED)
    assert suspended["suspension_reason"] == SUSPENSION_REASON_NONPAYMENT, (
        "the suspension reason must be stored on the licence, "
        f"but read {suspended['suspension_reason']!r}"
    )
    assert_license_dimensions(
        license_row(api, licence["id"]), COVERAGE_SUSPENDED, BILLING_INVOICED
    )


def test_dimensions_suspension_empties_the_venue_covered_share(api):
    """The venue's coverage roll-up drops to nothing the moment coverage is suspended.

    While the licence is active and its annual window spans the current logical
    instant the society's whole repertoire share counts towards the venue; once
    the licence is suspended it counts for nothing at all.

    PRD §2.10: "Licences in `PENDING_ACTIVATION`, `SUSPENDED`, `EXPIRED` or
    `TERMINATED` contribute nothing at all."

    PRD §2.10: "`coverage_posture` is then read off that sum: `FULLY_COVERED`
    when `covered_share_bp` is at least 9500, `PARTIALLY_COVERED` when
    `covered_share_bp` is at least 1 and below 9500, and `UNCOVERED` when
    `covered_share_bp` is exactly 0."

    Design: Difficulty/non_linear_state_machine/license_coverage_and_billing_dimensions_move_independently
    """
    world = _suspended_license_world(api)
    licence = world["license"]
    assert_coverage(world["venue"], SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)

    validate_success(
        api.suspend_license(
            licence["id"],
            suspend_payload(SUSPENSION_REASON_NONPAYMENT),
            admin_headers(),
        )
    )

    assert_coverage(venue_row(api, world["venue"]["id"]), 0, POSTURE_UNCOVERED)


def test_dimensions_paying_the_annual_assessment_does_not_restore_coverage(api):
    """Settling the annual invoice moves only the billing dimension.

    Paying the whole initial assessment of a suspended licence clears the venue's
    outstanding balance and advances the billing dimension to paid, yet coverage
    stays suspended — payment is not reinstatement.

    PRD §2.11: "`INVOICED` to `PAID` happens when a payment clears the last
    still-`ISSUED` assessment of that licence."

    PRD §3.9: "**A payment for exactly the remainder** sets `paid_amount_cents`
    to the assessment's full `amount_cents`, moves `status` to the terminal
    `PAID`, and increments `version`."

    Design: Difficulty/non_linear_state_machine/license_coverage_and_billing_dimensions_move_independently
    """
    world = _suspended_license_world(api)
    licence = world["license"]
    venue_id = world["venue"]["id"]
    validate_success(
        api.suspend_license(
            licence["id"],
            suspend_payload(SUSPENSION_REASON_NONPAYMENT),
            admin_headers(),
        )
    )
    issued = assessments_of_license(api, licence["id"])
    assert len(issued) == 1, (
        f"activation raises exactly one initial assessment, got {len(issued)}"
    )

    paid = validate_success(
        api.pay_assessment(
            issued[0]["id"],
            payment_payload(_ANNUAL_FEE_CENTS),
            venue_operator_headers(venue_id),
        )
    )

    assert_assessment(
        paid,
        ASSESSMENT_KIND_INITIAL,
        _ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_PAID,
        paid=_ANNUAL_FEE_CENTS,
    )
    assert_license_dimensions(
        license_row(api, licence["id"]), COVERAGE_SUSPENDED, BILLING_PAID
    )
    assert_venue_ledger(
        venue_row(api, venue_id), 0, _ANNUAL_FEE_CENTS, 0, _ANNUAL_FEE_CENTS
    )
