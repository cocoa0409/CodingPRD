"""State machines with loops, and one row carrying two independent state axes."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_STATE
from test_helpers.assertions import assert_integer, assert_load
from test_helpers.test_users import ADMIN, ANALYST, PERMITTEE_1, PERMIT_WRITER


def test_revision_round_accumulates_across_two_stakeholder_loops(api):
    """Two full comment-and-rework cycles leave the counter at 2, never reset.

    "`revision_round` is deliberately never reset, so an assessment that cycles
    repeatedly accumulates an ever-growing revision count."

    Design: Difficulty/non_linear_state_machine/tmdl_public_comment_revision_loop_twice_then_approval_only_from_public_comment
    """
    world = fx.scr_allocated(api)
    assessment_id = world["assessment_id"]

    published = fx.publish_assessment(api, assessment_id)
    assert published["status"] == "PUBLIC_COMMENT", published
    assert_integer(published["revision_round"], 0, "revision_round before any rework")

    first_revision = get_success_data(
        api.set_assessment_status(assessment_id, f.assessment_status_payload("REVISION"), ADMIN)
    )
    assert first_revision["status"] == "REVISION", first_revision
    assert_integer(first_revision["revision_round"], 1, "revision_round after the first rework")

    republished = fx.publish_assessment(api, assessment_id)
    assert republished["status"] == "PUBLIC_COMMENT", republished
    assert_integer(republished["revision_round"], 1, "revision_round is not reset by re-publishing")

    second_revision = get_success_data(
        api.set_assessment_status(assessment_id, f.assessment_status_payload("REVISION"), ADMIN)
    )
    assert second_revision["status"] == "REVISION", second_revision
    assert_integer(second_revision["revision_round"], 2, "revision_round after the second rework")

    fx.publish_assessment(api, assessment_id)
    approved = fx.approve_assessment(api, assessment_id)
    assert approved["status"] == "APPROVED", approved
    assert_integer(approved["revision_round"], 2, "revision_round survives approval")


def test_approval_is_refused_from_revision_and_accepted_from_public_comment(api):
    """Only the public-comment state declares the approval transition.

    "Approval is the pivotal transition and is reserved to a
    `ProgramAdministrator`, who moves the assessment `PUBLIC_COMMENT → APPROVED`."

    Design: Difficulty/non_linear_state_machine/tmdl_public_comment_revision_loop_twice_then_approval_only_from_public_comment
    """
    world = fx.scr_allocated(api)
    assessment_id = world["assessment_id"]
    fx.publish_assessment(api, assessment_id)
    in_revision = get_success_data(
        api.set_assessment_status(assessment_id, f.assessment_status_payload("REVISION"), ADMIN)
    )
    assert in_revision["status"] == "REVISION", in_revision

    refused = api.set_assessment_status(
        assessment_id, f.assessment_status_payload("APPROVED"), ADMIN
    )
    validate_error(refused, ERR_INVALID_STATE, 409)

    still_in_revision = get_success_data(api.get_tmdl_assessment(assessment_id, ANALYST))
    assert still_in_revision["status"] == "REVISION", still_in_revision
    assert still_in_revision["approved_at"] is None, still_in_revision
    assert_integer(still_in_revision["revision_round"], 1, "revision_round")

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert watershed["program_status"] == "PROVISIONAL", watershed

    fx.publish_assessment(api, assessment_id)
    approved = fx.approve_assessment(api, assessment_id)
    assert approved["status"] == "APPROVED", approved
    assert approved["approved_at"] is not None, approved


def _permit_in_compliance(api):
    """A derived permit reporting 22000.00 lbs, which clears its interim limit."""
    world = fx.scr_allocated(api)
    permit = fx.make_permit(api, world["watershed_id"], world["sa_p1"]["id"])
    derived = fx.derive_limits(api, permit["id"])
    assert derived["limit_status"] == "INTERIM", derived
    assert_load(derived["interim_limit_lbs_yr"], 23916.00, "interim_limit_lbs_yr")
    assert_load(derived["final_limit_lbs_yr"], 21888.00, "final_limit_lbs_yr")
    reported = fx.file_annual_report(api, permit["id"], 22000.00)
    assert reported["compliance_status"] == "IN_COMPLIANCE", reported
    assert_load(reported["compliance_gap_lbs"], 0.00, "compliance_gap_lbs")
    world["permit"] = reported
    world["permit_id"] = permit["id"]
    return world


def test_finalizing_limits_moves_the_compliance_axis_from_compliance_to_shortfall(api):
    """Tightening the applicable limit pushes a compliant permit backwards.

    "When limit finalization tightens `applicable_limit_lbs_yr` from the interim
    limit to the final limit, a permit that was `IN_COMPLIANCE` with a non-null
    `reported_annual_load_lbs` and whose recomputed gap against the tightened
    limit comes out above 0.00, with the logical clock's date on or before
    `compliance_schedule_end_date`, moves `IN_COMPLIANCE → SHORTFALL`."

    Design: Difficulty/non_linear_state_machine/permit_dual_axis_limit_transition_moves_compliance_axis_backwards
    """
    world = _permit_in_compliance(api)
    fx.publish_and_approve(api, world["assessment_id"])

    finalized = fx.finalize_limits(api, world["permit_id"])

    assert finalized["limit_status"] == "FINAL", finalized
    assert_load(finalized["applicable_limit_lbs_yr"], 21888.00, "applicable_limit_lbs_yr")
    assert finalized["compliance_status"] == "SHORTFALL", finalized
    assert_load(finalized["compliance_gap_lbs"], 112.00, "compliance_gap_lbs")
    assert finalized["enforcement_flag"] is False, finalized
    assert_load(finalized["reported_annual_load_lbs"], 22000.00, "reported_annual_load_lbs")


def test_finalization_increments_the_version_once_for_both_axes(api):
    """One write moving two axes bumps the row's version exactly once.

    "The permit's `version` increments by exactly 1 for the whole request even
    when both axes move, because finalization is one write."

    Design: Difficulty/non_linear_state_machine/permit_dual_axis_limit_transition_moves_compliance_axis_backwards
    """
    world = _permit_in_compliance(api)
    fx.publish_and_approve(api, world["assessment_id"])
    before = validate_success(api.get_permit(world["permit_id"], PERMIT_WRITER))

    finalized = fx.finalize_limits(api, world["permit_id"])

    assert finalized["limit_status"] == "FINAL", finalized
    assert finalized["compliance_status"] == "SHORTFALL", finalized
    assert_integer(
        finalized["version"], before["version"] + 1, "version after a two-axis finalization"
    )

    reread = validate_success(api.get_permit(world["permit_id"], PERMITTEE_1))
    assert_integer(reread["version"], before["version"] + 1, "version on re-read")
