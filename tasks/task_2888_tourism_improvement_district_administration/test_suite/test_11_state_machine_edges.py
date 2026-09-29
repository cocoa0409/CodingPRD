"""Edges of the declared state machines: the ones that move and the ones that do not.

Every transition in this system is declared, and anything undeclared is refused
at the state rung.  These tests walk the less obvious edges — an activation that
deliberately preserves the dates a previous transition stamped, a district-level
act whose whole point is the cascade it fires, terminal states that accept
nothing, and one-shot actions attempted twice.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_STATE_TRANSITION
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_ratio_four_dp,
)
from test_helpers.test_users import (
    ADMIN,
    BOARD_MEMBER,
    BOARD_MEMBER_2,
    BOARD_MEMBER_USER_ID,
    DMO_LIAISON,
    HEARING_OFFICER,
    operator_headers,
)

#: Certification stamps the term from the logical clock, and the roll factory
#: leaves the clock at the origin with a one-year term.
FORMED_ON = "2026-08-01T00:00:00Z"
EXPIRATION_DATE = "2027-08-01T00:00:00Z"


# --------------------------------------------------------------------------
# Activation preserves the term certification stamped
# --------------------------------------------------------------------------
def test_activation_leaves_the_term_dates_exactly_as_certification_stamped_them(api):
    """The clock has moved nineteen days past certification, yet activation
    re-reads neither formed_on nor expiration_date.

    PRD 3.2: "Activation sets status to ACTIVE and deliberately leaves formed_on
    and expiration_date exactly as certification stamped them; nothing about
    activation re-dates the term."

    Design: Corner/state_machines/district_moves_formed_to_active_without_restamping_its_term_dates
    """
    ctx = fx.formed_district(api)

    formed = validate_success(api.get_district(ctx.d_id))
    assert_fields(formed, status="FORMED", assessable_business_count=4, term_years=1)
    assert_instant_equals(formed["formed_on"], FORMED_ON, "formed_on")
    assert_instant_equals(formed["expiration_date"], EXPIRATION_DATE, "expiration_date")

    fx.set_clock(api, "2026-08-20T00:00:00Z")
    activated = fx.advance_district(api, ctx, "ACTIVE", effective_on="2026-08-20T00:00:00Z")

    assert_fields(activated, status="ACTIVE", assessable_business_count=4)
    assert_instant_equals(activated["formed_on"], FORMED_ON, "formed_on")
    assert_instant_equals(activated["expiration_date"], EXPIRATION_DATE, "expiration_date")
    assert activated["version"] == formed["version"] + 1, (
        f"activation left version at {activated['version']}, "
        f"expected {formed['version'] + 1}"
    )

    drive = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(drive, status="CERTIFIED")


def test_activation_is_refused_once_the_assessable_roll_has_collapsed_to_two(api):
    """Retiring two of the four properties between certification and activation
    leaves the roll at two, and the activation the district was otherwise ready
    for is refused.

    PRD 3.2: "It requires the district to be FORMED, requires the district's
    formation drive to be CERTIFIED, and requires assessable_business_count to
    still be at least three — a district whose assessable roll collapsed between
    certification and activation may not be activated."

    Design: Corner/state_machines/activation_is_refused_once_the_assessable_roll_falls_below_the_petition_pool
    """
    ctx = fx.formed_district(api)
    for business_key in ("b2_id", "b3_id"):
        retired = validate_success(
            api.revise_lodging_business(
                ctx[business_key], f.revision_payload(close_out=True), headers=ADMIN
            )
        )
        assert_fields(retired, status="CLOSED_OUT")

    collapsed = validate_success(api.get_district(ctx.d_id))
    assert_fields(
        collapsed,
        status="FORMED",
        assessable_business_count=2,
        assessable_basis_cents=65000000,
    )

    response = api.advance_district_lifecycle(
        ctx.d_id, f.lifecycle_advance_payload("ACTIVE"), headers=ADMIN
    )
    validate_error(response, ERR_INVALID_STATE_TRANSITION, expected_status=409)

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, status="FORMED", assessable_business_count=2)
    assert_instant_equals(district["expiration_date"], EXPIRATION_DATE, "expiration_date")


# --------------------------------------------------------------------------
# One boundary redefinition, four declared side effects
# --------------------------------------------------------------------------
def test_one_boundary_redefinition_fires_every_declared_side_effect(api):
    """Shrinking the district to its core zone moves two perimeter properties out,
    disqualifies the one that had signed, recomputes the district aggregates and
    re-scores the open drive — all from a single call.

    PRD 3.1: "every property on the roll is re-evaluated against the new set in
    one pass: properties whose boundary_zone has left the set move ASSESSABLE to
    OUTSIDE_BOUNDARY and have their VALID signatures on OPEN drives disqualified
    with reason OUTSIDE_BOUNDARY, properties whose zone has re-entered move
    OUTSIDE_BOUNDARY to ASSESSABLE, the district's assessable_basis_cents and
    assessable_business_count are recomputed, and support is re-scored for every
    OPEN drive of the district."

    Design: Corner/state_machines/boundary_revision_executes_every_declared_side_effect_in_one_call
    """
    ctx = fx.district_with_roll(api)
    fx.open_formation_drive(api, ctx)
    fx.sign(api, ctx, "b1_id")
    fx.sign(api, ctx, "b3_id")

    before_district = validate_success(api.get_district(ctx.d_id))
    assert_fields(
        before_district,
        included_zones=["ZONE_CORE", "ZONE_PERIMETER"],
        assessable_basis_cents=100000000,
        assessable_business_count=4,
    )
    before_drive = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(
        before_drive,
        status="OPEN",
        signed_basis_cents=75000000,
        valid_signature_count=2,
        assessable_basis_snapshot_cents=100000000,
        assessable_count_snapshot=4,
    )

    revised = validate_success(
        api.revise_district_boundary(
            ctx.d_id,
            f.boundary_revision_payload(["ZONE_CORE"], effective_on="2026-08-05T00:00:00Z"),
            headers=ADMIN,
        )
    )
    assert_fields(
        revised,
        included_zones=["ZONE_CORE"],
        assessable_basis_cents=80000000,
        assessable_business_count=2,
    )
    assert revised["version"] == before_district["version"] + 1, (
        f"the redefinition left the district at version {revised['version']}, "
        f"expected {before_district['version'] + 1}"
    )

    for business_key in ("b3_id", "b4_id"):
        pushed_out = validate_success(api.get_lodging_business(ctx[business_key], headers=ADMIN))
        assert_fields(pushed_out, status="OUTSIDE_BOUNDARY", boundary_zone="ZONE_PERIMETER")
    for business_key in ("b1_id", "b2_id"):
        retained = validate_success(api.get_lodging_business(ctx[business_key], headers=ADMIN))
        assert_fields(retained, status="ASSESSABLE", boundary_zone="ZONE_CORE")

    disqualified = validate_success(api.get_petition_signature(ctx.sig_b3, headers=ADMIN))
    assert_fields(
        disqualified,
        status="DISQUALIFIED",
        disqualification_reason="OUTSIDE_BOUNDARY",
        weight_basis_revenue_cents=15000000,
    )
    survivor = validate_success(api.get_petition_signature(ctx.sig_b1, headers=ADMIN))
    assert_fields(survivor, status="VALID", disqualification_reason="NONE")

    rescored = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(
        rescored,
        status="OPEN",
        signed_basis_cents=60000000,
        valid_signature_count=1,
        assessable_basis_snapshot_cents=80000000,
        assessable_count_snapshot=2,
    )
    assert_ratio_four_dp(rescored["weighted_support_pct"], 0.7500, "weighted_support_pct")
    assert_ratio_four_dp(rescored["headcount_support_pct"], 0.5000, "headcount_support_pct")


# --------------------------------------------------------------------------
# An action declared only from the state the dispute has already left
# --------------------------------------------------------------------------
def test_a_dispute_may_not_be_withdrawn_once_the_hearing_is_open(api):
    """WITHDRAW is declared from SUBMITTED alone, so the operator's attempt to
    abandon a matter already UNDER_REVIEW is refused and the dispute does not move.

    PRD 3.6: "WITHDRAW moves a SUBMITTED dispute to terminal WITHDRAWN. A dispute
    may be abandoned only before the hearing officer opens review; once review is
    open the matter runs to a resolution, and a withdrawal attempt from
    UNDER_REVIEW, INFO_REQUESTED or either resolved state is refused at the state
    rung."

    Design: Corner/state_machines/withdrawing_a_dispute_already_under_review_is_an_undeclared_transition
    """
    ctx = fx.statements_filed(api)
    fx.file_dispute(api, ctx)
    under_review = fx.open_dispute_review(api, ctx)
    assert_fields(under_review, status="UNDER_REVIEW", appeal_count=0)

    response = api.advance_dispute(
        ctx.dsp_id,
        f.proceeding_payload("WITHDRAW", "the property no longer wishes to be heard"),
        headers=operator_headers(ctx.b1_id),
    )
    validate_error(response, ERR_INVALID_STATE_TRANSITION, expected_status=409)

    dispute = validate_success(api.get_dispute(ctx.dsp_id, headers=HEARING_OFFICER))
    assert_fields(
        dispute,
        status="UNDER_REVIEW",
        granted_adjustment_cents=0,
        appeal_count=0,
        lodging_business_id=ctx.b1_id,
    )
    assert_null_fields(dispute, "resolved_by_user_id")

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(statement, effective_assessment_cents=824500)


# --------------------------------------------------------------------------
# A program's initial state carries no measurement at all
# --------------------------------------------------------------------------
def test_a_new_program_is_planned_with_every_performance_figure_still_empty(api):
    """Creation writes the funding terms and nothing else: the two costs per room
    night and the tier are null, the index is 0.0000 and the flag says the program
    has not been measured.

    PRD 3.8: "The program is created in PLANNED with spend_frozen false,
    verified_room_nights 0, gross_cost_per_room_night_cents, efficiency_tier and
    net_cost_per_room_night_cents all null, dmo_cost_share_cents and
    net_district_cost_cents 0, performance_index 0.0000, performance_flag
    NOT_MEASURED, and launched_at and closed_at null."

    Design: Corner/state_machines/marketing_program_starts_planned_with_no_performance_figures_yet
    """
    ctx = fx.statements_filed(api)
    plan = fx.approved_work_plan(api, ctx)
    assert_fields(plan, status="APPROVED", sales_and_marketing_cents=650000)

    program = fx.create_program(api, ctx)
    assert_fields(
        program,
        annual_work_plan_id=ctx.wp_id,
        status="PLANNED",
        channel="GROUP_SALES",
        committed_cents=62000,
        lodging_tax_matched_cents=0,
        spend_frozen=False,
        verified_room_nights=0,
        dmo_cost_share_cents=0,
        net_district_cost_cents=0,
        performance_flag="NOT_MEASURED",
        version=1,
    )
    assert_null_fields(
        program,
        "gross_cost_per_room_night_cents",
        "efficiency_tier",
        "net_cost_per_room_night_cents",
        "launched_at",
        "closed_at",
    )
    assert_ratio_four_dp(program["performance_index"], 0.0000, "performance_index")


# --------------------------------------------------------------------------
# Terminal states accept nothing
# --------------------------------------------------------------------------
def test_a_certified_drive_and_a_verified_claim_both_refuse_a_second_decision(api):
    """Re-tallying the drive that created the term and re-deciding a claim already
    allowed are both refused, and neither record moves.

    PRD 3.2: "the drive moves QUALIFIED to CERTIFIED, which is terminal."
    PRD 3.8: "Both target states are terminal, so a decision is final."

    Design: Corner/state_machines/certified_drive_and_verified_claim_both_refuse_any_further_action
    """
    ctx = fx.running_program(api)

    certified = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(
        certified, status="CERTIFIED", signed_basis_cents=60000000, valid_signature_count=1
    )
    assert_ratio_four_dp(certified["weighted_support_pct"], 0.6000, "weighted_support_pct")

    validate_error(
        api.tally_petition_drive(ctx.pd_id, headers=ADMIN),
        ERR_INVALID_STATE_TRANSITION,
        expected_status=409,
    )

    unmoved_drive = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(
        unmoved_drive,
        status="CERTIFIED",
        signed_basis_cents=60000000,
        valid_signature_count=1,
        short_reason="NONE",
    )
    assert_ratio_four_dp(unmoved_drive["weighted_support_pct"], 0.6000, "weighted_support_pct")

    fx.submit_claim(api, ctx)
    allowed = fx.verify_claim(api, ctx)
    assert_fields(allowed, status="VERIFIED", verified_room_nights=100, rejection_reason="NONE")

    validate_error(
        api.verify_room_night_claim(
            ctx.rnc_id,
            f.verification_payload("REJECT", rejection_reason="DUPLICATE_STAY"),
            headers=DMO_LIAISON,
        ),
        ERR_INVALID_STATE_TRANSITION,
        expected_status=409,
    )

    unmoved_claim = validate_success(api.get_room_night_claim(ctx.rnc_id, headers=DMO_LIAISON))
    assert_fields(
        unmoved_claim, status="VERIFIED", verified_room_nights=100, rejection_reason="NONE"
    )
    program = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(program, status="RUNNING", verified_room_nights=100)


# --------------------------------------------------------------------------
# One-shot actions attempted twice
# --------------------------------------------------------------------------
def test_a_second_sponsorship_and_a_second_period_closure_are_both_refused(api):
    """Sponsorship is declared from DRAFT and closure from OPEN, so once each has
    fired the record has left the only state its own action reads.

    PRD 3.7: "SPONSOR moves a DRAFT plan to BOARD_REVIEW, requires
    expenditure_lines to be non-empty, and records sponsor_user_id from the acting
    X-User-ID."

    PRD 3.3: "A DistrictAdministrator closes an OPEN period once the logical clock
    has reached period_end and at least one statement has been generated for it;
    the period moves OPEN to CLOSED and its billed_total_cents and
    collected_total_cents are recomputed from its statements."

    Design: Corner/state_machines/second_sponsor_action_and_second_period_closure_are_both_refused
    """
    ctx = fx.statements_filed(api)
    fx.draft_work_plan(api, ctx)
    sponsored = fx.sponsor_work_plan(api, ctx, headers=BOARD_MEMBER)
    assert_fields(sponsored, status="BOARD_REVIEW", sponsor_user_id=BOARD_MEMBER_USER_ID)

    validate_error(
        api.board_action(
            ctx.wp_id,
            f.board_action_payload("SPONSOR", "a second board member seconds the budget"),
            headers=BOARD_MEMBER_2,
        ),
        ERR_INVALID_STATE_TRANSITION,
        expected_status=409,
    )
    plan = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(
        plan,
        status="BOARD_REVIEW",
        sponsor_user_id=BOARD_MEMBER_USER_ID,
        revision_count=0,
    )

    fx.set_clock(api, "2026-11-16T00:00:00Z")
    closed = fx.close_period(api, ctx)
    assert_fields(
        closed,
        status="CLOSED",
        statement_count=4,
        billed_total_cents=1164500,
        collected_total_cents=0,
    )

    validate_error(
        api.close_assessment_period(ctx.ap_id, headers=ADMIN),
        ERR_INVALID_STATE_TRANSITION,
        expected_status=409,
    )
    period = validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN))
    assert_fields(period, status="CLOSED", billed_total_cents=1164500)
    assert period["version"] == closed["version"], (
        f"the refused closure moved the period to version {period['version']}, "
        f"expected {closed['version']}"
    )


# --------------------------------------------------------------------------
# Early dissolution reaches down two levels
# --------------------------------------------------------------------------
def test_dissolving_the_district_withdraws_its_open_drive_and_cancels_its_program(api):
    """A district dissolved with a closed period, an open renewal drive and a
    planned program carries both dependents to their terminal states while the
    already-terminal records are left alone.

    PRD 3.2: "On success status becomes DISESTABLISHED, every drive of the
    district still OPEN moves to WITHDRAWN, and every marketing program under any
    of the district's work plans whose status is PLANNED, RUNNING or
    SUSPENDED_PENDING_AMENDMENT moves to CANCELLED. Where a district is dissolved
    from ACTIVE, that cancellation also clears spend_frozen back to false on each
    cancelled program."

    Design: Corner/state_machines/disestablishment_cascades_down_into_planned_programs_and_open_drives
    """
    ctx = fx.statements_filed(api)
    fx.approved_work_plan(api, ctx)
    fx.create_program(api, ctx)
    fx.set_clock(api, "2026-11-16T00:00:00Z")
    fx.close_period(api, ctx)

    fx.set_clock(api, "2027-03-01T00:00:00Z")
    fx.open_renewal_drive(api, ctx, closes_at="2027-05-01T00:00:00Z")
    renewal = validate_success(api.get_petition_drive(ctx.renewal_pd_id))
    assert_fields(renewal, status="OPEN", drive_type="RENEWAL")

    dissolved = fx.advance_district(
        api,
        ctx,
        "DISESTABLISHED",
        effective_on="2027-03-01T00:00:00Z",
        reason="the board voted to dissolve the district early",
    )
    assert_fields(dissolved, status="DISESTABLISHED")

    withdrawn = validate_success(api.get_petition_drive(ctx.renewal_pd_id))
    assert_fields(withdrawn, status="WITHDRAWN")
    cancelled = validate_success(api.get_marketing_program(ctx.mp_id, headers=ADMIN))
    assert_fields(cancelled, status="CANCELLED", spend_frozen=False)

    formation = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(formation, status="CERTIFIED")
    plan = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(plan, status="APPROVED")
    period = validate_success(api.get_assessment_period(ctx.ap_id, headers=ADMIN))
    assert_fields(period, status="CLOSED", billed_total_cents=1164500)
    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(statement, effective_assessment_cents=824500)


# --------------------------------------------------------------------------
# A plan may not retire over a live program
# --------------------------------------------------------------------------
def test_the_plan_retires_only_once_its_last_program_has_gone_terminal(api):
    """CLOSE is refused while the plan's single program is still RUNNING, and
    accepted the moment that program closes with its measurement published.

    PRD 3.7: "CLOSE moves an APPROVED plan to terminal CLOSED, and requires that
    every marketing program of the plan already stands CLOSED or CANCELLED; a plan
    with a single PLANNED, RUNNING or SUSPENDED_PENDING_AMENDMENT program cannot
    be retired, so no live program is ever orphaned by closure."

    Design: Corner/state_machines/work_plan_closure_bubbles_up_only_after_every_program_is_terminal
    """
    ctx = fx.running_program(api)
    fx.submit_claim(api, ctx)
    fx.verify_claim(api, ctx)

    validate_error(
        api.board_action(
            ctx.wp_id,
            f.board_action_payload("CLOSE", "retiring the fiscal 2027 budget"),
            headers=BOARD_MEMBER,
        ),
        ERR_INVALID_STATE_TRANSITION,
        expected_status=409,
    )
    still_open = validate_success(api.get_work_plan(ctx.wp_id))
    assert_fields(still_open, status="APPROVED")

    fx.set_clock(api, "2026-09-25T00:00:00Z")
    measured = fx.close_program(api, ctx)
    assert_fields(
        measured,
        status="CLOSED",
        verified_room_nights=100,
        gross_cost_per_room_night_cents=620,
        efficiency_tier="TIER_EFFICIENT",
        dmo_cost_share_cents=24800,
        net_district_cost_cents=37200,
        net_cost_per_room_night_cents=372,
        performance_flag="MEETS_BENCHMARK",
    )
    assert_ratio_four_dp(measured["performance_index"], 6.7204, "performance_index")
    assert_instant_equals(measured["closed_at"], "2026-09-25T00:00:00Z", "closed_at")

    retired = validate_success(
        api.board_action(
            ctx.wp_id,
            f.board_action_payload("CLOSE", "retiring the fiscal 2027 budget"),
            headers=BOARD_MEMBER,
        )
    )
    assert_fields(retired, status="CLOSED")
