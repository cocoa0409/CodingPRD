"""State machines that are not a straight line.

A public notification can return to a state it has already occupied, bounded
only by a monotonic revision counter; a capital project carries two lifecycles
that advance independently of one another.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_decimal,
    assert_entry_point_posture,
    assert_equals,
    assert_instant_equals,
    assert_is_null,
    assert_money_cents,
    assert_rate_ladder,
    assert_same_members,
    assert_status,
)
from test_helpers.constants import MANDATORY_CONTENT_ELEMENTS
from test_helpers.fixtures import (
    accepted_quarters,
    apply_for_funding,
    award_funding,
    build_registry,
    draft_determination,
    issue_determination,
    notification_of,
    piloted_evaluation,
    project_of_evaluation,
    read_entry_point,
    read_notification,
    read_project,
    register_entry_point,
    select_technology,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    OFFICER_USER_ID,
    STATE_REGULATOR_HEADERS,
)

_REJECTION_NOTE = "Health effects language must cite the state advisory."


def _submitted_tier_2_notification(api):
    """Four quarters averaging 4.50 issue a non-acute violation and a TIER_2 notice."""
    registry = build_registry(api)
    accepted_quarters(
        api,
        registry,
        [("2025Q3", 3.00), ("2025Q4", 3.00), ("2026Q1", 3.00), ("2026Q2", 9.00)],
    )
    determination = draft_determination(
        api, registry["entry_point_id"], registry["contaminant_id"], period_end="2026Q2"
    )
    issued = issue_determination(api, determination["id"])
    notification = notification_of(api, issued["id"])
    submitted = validate_success(
        api.submit_notification(
            notification["id"], f.notification_submit_payload(), COMPLIANCE_OFFICER_HEADERS
        )
    )
    return registry, issued, submitted


def _reject(api, notification_id):
    return validate_success(
        api.review_notification(
            notification_id,
            f.notification_review_payload(approve=False, review_note=_REJECTION_NOTE),
            STATE_REGULATOR_HEADERS,
        )
    )


def test_a_rejected_notice_returns_to_draft_stripped_of_its_content(api):
    """Re-entering DRAFT is destructive and moves the bounded counter to one.

    A regulator's rejection sends the submitted TIER_2 notice back to DRAFT,
    raises revision_count from zero to one and empties both content_elements and
    delivery_methods, so the officer has to re-assemble all six mandatory
    disclosures rather than resubmitting what was already there.

    PRD: "Rejection moves it `SUBMITTED → DRAFT`, raises `revision_count` by
    one, clears both `content_elements` and `delivery_methods` back to empty
    arrays so the officer must re-assemble the notice from scratch, and requires
    a `review_note` explaining the deficiency, else `ERR_INVALID_REQUEST`."

    Design: Difficulty/non_linear_state_machine/notification_revision_cycle_clears_the_draft_and_increments_the_bounded_counter
    """
    registry, issued, submitted = _submitted_tier_2_notification(api)
    assert_status(submitted, "SUBMITTED")

    rejected = _reject(api, submitted["id"])

    assert_status(rejected, "DRAFT")
    assert_equals(rejected, "revision_count", 1)
    assert_equals(rejected, "content_elements", [])
    assert_equals(rejected, "delivery_methods", [])
    assert_equals(rejected, "review_note", _REJECTION_NOTE)
    assert_equals(rejected, "tier", "TIER_2")
    assert_instant_equals(
        rejected["required_by_at"], "2026-08-31T00:00:00.000Z", label="required_by_at"
    )

    assert_status(issued, "ISSUED")
    assert_equals(issued, "determination", "MCL_VIOLATION")
    assert_equals(issued, "violation_type", "NON_ACUTE")
    assert_decimal(issued["lraa_ng_per_l"], 4.50, label="lraa_ng_per_l")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]),
        posture="VIOLATION_PENDING",
        max_compliance_ratio=1.1250,
        open_violation_count=1,
    )


def test_resubmitting_after_a_rejection_leaves_the_revision_counter_where_it_was(api):
    """A second lap through DRAFT does not give the counter back.

    Re-supplying the six mandatory elements and the TIER_2 channels moves the
    notice DRAFT to SUBMITTED again, but revision_count stays at the one the
    rejection put there — the counter is monotonic, which is what makes the cycle
    terminate at the fourth revision.

    PRD: "The `revision_count` must be no greater than three; a notification
    sent back for revision a fourth time can no longer be submitted, and the
    attempt is refused with `ERR_NOTIFICATION_REVISION_LIMIT`."

    Design: Difficulty/non_linear_state_machine/notification_revision_cycle_clears_the_draft_and_increments_the_bounded_counter
    """
    _, _, submitted = _submitted_tier_2_notification(api)
    _reject(api, submitted["id"])

    resubmitted = validate_success(
        api.submit_notification(
            submitted["id"], f.notification_submit_payload(), COMPLIANCE_OFFICER_HEADERS
        )
    )

    assert_status(resubmitted, "SUBMITTED")
    assert_equals(resubmitted, "revision_count", 1)
    assert len(resubmitted["content_elements"]) == 6, (
        f"Expected six content elements, got {resubmitted['content_elements']}"
    )
    assert_same_members(
        resubmitted["content_elements"], MANDATORY_CONTENT_ELEMENTS, label="content_elements"
    )
    assert_same_members(
        resubmitted["delivery_methods"], ["MAIL", "POSTING"], label="delivery_methods"
    )
    assert_equals(resubmitted, "drafted_by_user_id", OFFICER_USER_ID)
    assert_is_null(read_notification(api, submitted["id"]), "distributed_at", "late_by_hours")


def _awarded_project(api):
    """A GAC project with a fully awarded standard SRF loan of 400000000 cents."""
    entry_point = register_entry_point(api)
    piloted = piloted_evaluation(api, entry_point["id"])
    select_technology(api, piloted["evaluation_id"])
    project = project_of_evaluation(api, piloted["evaluation_id"])
    application = apply_for_funding(
        api, project["id"], amount_requested_cents=400000000, disadvantaged_community=False
    )
    return project, application


def test_the_funding_dimension_moves_while_construction_stays_planned(api):
    """Applying and then winning money never touches construction_status.

    The project's derived funding_status walks NOT_APPLIED to APPLIED on the
    application and on to AWARDED once the regulator awards the full 400000000
    cents, while construction_status sits at PLANNED throughout; a standard loan
    forgives nothing, so borrowed_cents stays at 680000000 and the rate impact
    stays at 7.18 percent.

    PRD: "The two dimensions advance independently, so a project can be in
    construction with funding denied, or awarded funding while still merely
    planned."

    Design: Difficulty/non_linear_state_machine/capital_project_funding_and_construction_dimensions_advance_independently
    """
    project, application = _awarded_project(api)

    applied = read_project(api, project["id"])
    assert_equals(applied, "funding_status", "APPLIED")
    assert_equals(applied, "construction_status", "PLANNED")

    awarded_application = award_funding(api, application["id"], 400000000)
    awarded = read_project(api, project["id"])

    assert_status(awarded_application, "AWARDED")
    assert_money_cents(awarded_application["awarded_cents"], 400000000, "awarded_cents")
    assert_money_cents(awarded_application["forgiven_cents"], 0, "forgiven_cents")
    assert_decimal(awarded_application["forgiveness_pct"], 0.00, label="forgiveness_pct")

    assert_equals(awarded, "funding_status", "AWARDED")
    assert_equals(awarded, "construction_status", "PLANNED")
    assert_money_cents(awarded["funding_awarded_cents"], 400000000, "funding_awarded_cents")
    assert_money_cents(awarded["loan_principal_cents"], 400000000, "loan_principal_cents")
    assert_money_cents(awarded["grant_equivalent_cents"], 0, "grant_equivalent_cents")
    assert_rate_ladder(
        awarded,
        local_share_cents=280000000,
        borrowed_cents=680000000,
        annual_debt_service_cents=41586568,
        rate_impact_pct=7.18,
        uniform_monthly_increase_cents=341,
    )


def test_moving_into_bidding_leaves_the_funding_ledger_untouched(api):
    """The combined AWARDED-and-BIDDING state is reachable only in that order.

    With the award in hand the project may advance PLANNED to BIDDING, and that
    physical move changes nothing on the funding side: funding_status is still
    AWARDED, the ladder is unchanged, and the GAC selection's residuals
    attributes still stand.

    PRD: "The move into `BIDDING` carries two extra preconditions, checked in
    this order: when the project's `concentrate_permit_required` is true, a
    `concentrate_permit_ref` must be supplied, else
    `ERR_CONCENTRATE_PERMIT_REQUIRED`; and the project's `funding_status` must be
    `AWARDED`, else `ERR_FUNDING_NOT_SECURED`."

    Design: Difficulty/non_linear_state_machine/capital_project_funding_and_construction_dimensions_advance_independently
    """
    project, application = _awarded_project(api)
    award_funding(api, application["id"], 400000000)

    bidding = validate_success(
        api.advance_construction(
            project["id"], f.construction_status_payload("BIDDING"), FINANCE_OFFICER_HEADERS
        )
    )

    assert_equals(bidding, "construction_status", "BIDDING")
    assert_equals(bidding, "funding_status", "AWARDED")
    assert_equals(bidding, "required_disposal_method", "REACTIVATION")
    assert_equals(bidding, "concentrate_permit_required", False)
    assert_rate_ladder(
        bidding,
        local_share_cents=280000000,
        borrowed_cents=680000000,
        annual_debt_service_cents=41586568,
        rate_impact_pct=7.18,
        uniform_monthly_increase_cents=341,
    )
