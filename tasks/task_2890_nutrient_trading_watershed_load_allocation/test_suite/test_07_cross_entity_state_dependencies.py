"""Operations whose precondition lives on a different row from the one they mutate."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_PROJECT_NOT_CERTIFIED, ERR_TMDL_NOT_APPROVED
from test_helpers.assertions import (
    assert_batch_buckets,
    assert_integer,
    assert_load,
    assert_ratio,
)
from test_helpers.test_users import PERMIT_WRITER, REGISTRY


def _issued_batch_pending_reverification(api):
    """A minted-but-unlisted batch whose generating project has slipped out of CERTIFIED."""
    world = fx.scr_active_program(api)
    world["producer"] = fx.make_producer(api)
    project = fx.implemented_project(
        api, world["producer"]["id"], world["reaches"]["r_up"]["id"], "T-101"
    )
    batch = fx.certify_project(api, project["id"])
    assert batch["status"] == "ISSUED", batch
    assert_integer(batch["issued_lbs"], 520, "issued_lbs")

    fx.reverify(api, project["id"], "PARTIAL", verified_acres=60.00)
    world["project_id"] = project["id"]
    world["batch_id"] = batch["id"]
    world["project"] = get_success_data(api.get_practice_project(project["id"], REGISTRY))
    world["batch"] = get_success_data(api.get_credit_batch(batch["id"], REGISTRY))
    assert world["project"]["status"] == "PENDING_REVERIFICATION", world["project"]
    assert_ratio(world["batch"]["verified_ratio"], 0.7500, "verified_ratio after PARTIAL")
    return world


def test_listing_is_refused_while_the_generating_project_awaits_reverification(api):
    """The batch is in the right state; its project is not, and that decides it.

    "Listing requires that the generating project's status is still `CERTIFIED` —
    a project sitting in `PENDING_REVERIFICATION` cannot have new batches listed
    and the attempt is rejected with `ERR_PROJECT_NOT_CERTIFIED`"

    Design: Difficulty/cross_entity_state_dependency/batch_listing_blocked_while_generating_project_sits_in_pending_reverification
    """
    world = _issued_batch_pending_reverification(api)

    refused = api.list_credit_batch(world["batch_id"], REGISTRY)

    validate_error(refused, ERR_PROJECT_NOT_CERTIFIED, 409)

    batch = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert batch["status"] == "ISSUED", batch
    assert_batch_buckets(batch, available=520.00, reserved=0.00, retired=0.00, invalidated=0.00)


def test_a_passing_reverification_restores_the_project_and_unblocks_listing(api):
    """Closing the reverification loop lets the same batch list unchanged.

    "A `REVERIFICATION` event with outcome `PASS` moves the project
    `PENDING_REVERIFICATION → CERTIFIED` ... Every batch of this project whose
    `status` is `ISSUED` or `LISTED` has its `verified_ratio` restored to 1.0000"

    Design: Difficulty/cross_entity_state_dependency/batch_listing_blocked_while_generating_project_sits_in_pending_reverification
    """
    world = _issued_batch_pending_reverification(api)

    event = fx.reverify(api, world["project_id"], "PASS", verified_acres=80.00)

    assert event["resulting_project_status"] == "CERTIFIED", event
    restored = get_success_data(api.get_credit_batch(world["batch_id"], REGISTRY))
    assert_ratio(restored["verified_ratio"], 1.0000, "verified_ratio after PASS")
    assert_integer(restored["issued_lbs"], 520, "issued_lbs is never restated")

    listed = fx.list_batch(api, world["batch_id"])
    assert listed["status"] == "LISTED", listed
    assert_batch_buckets(listed, available=520.00, reserved=0.00, retired=0.00, invalidated=0.00)


def _reported_permit_on_an_unapproved_assessment(api):
    """A derived, reporting permit whose governing assessment has never been approved."""
    world = fx.scr_allocated(api)
    permit = fx.make_permit(api, world["watershed_id"], world["sa_p1"]["id"])
    derived = fx.derive_limits(api, permit["id"])
    assert derived["limit_status"] == "INTERIM", derived
    assert_load(derived["interim_limit_lbs_yr"], 23916.00, "interim_limit_lbs_yr")
    assert_load(derived["final_limit_lbs_yr"], 21888.00, "final_limit_lbs_yr")
    reported = fx.file_annual_report(api, permit["id"], 22000.00)
    assert_load(reported["applicable_limit_lbs_yr"], 23916.00, "applicable_limit_lbs_yr")
    assert reported["compliance_status"] == "IN_COMPLIANCE", reported
    assert_load(reported["compliance_gap_lbs"], 0.00, "compliance_gap_lbs")
    world["permit_id"] = permit["id"]
    return world


def test_finalization_is_refused_until_the_governing_assessment_is_approved(api):
    """Neither DRAFT nor PUBLIC_COMMENT satisfies the finalization precondition.

    "It requires that the assessment reached from the permit's source assessment
    has status `APPROVED`; finalizing against an unapproved assessment is rejected
    with `ERR_TMDL_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/permit_finalization_gated_on_tmdl_approval_then_tightened_limit_flips_compliance
    """
    world = _reported_permit_on_an_unapproved_assessment(api)

    while_draft = api.finalize_limits(world["permit_id"], PERMIT_WRITER)
    validate_error(while_draft, ERR_TMDL_NOT_APPROVED, 409)

    published = fx.publish_assessment(api, world["assessment_id"])
    assert published["status"] == "PUBLIC_COMMENT", published
    while_in_comment = api.finalize_limits(world["permit_id"], PERMIT_WRITER)
    validate_error(while_in_comment, ERR_TMDL_NOT_APPROVED, 409)

    permit = validate_success(api.get_permit(world["permit_id"], PERMIT_WRITER))
    assert permit["limit_status"] == "INTERIM", permit
    assert_load(permit["applicable_limit_lbs_yr"], 23916.00, "applicable_limit_lbs_yr")
    assert permit["compliance_status"] == "IN_COMPLIANCE", permit


def test_approval_unblocks_finalization_which_then_tightens_the_applicable_limit(api):
    """The approved assessment lets the limit move, and the tighter limit reopens a gap.

    "On success `applicable_limit_lbs_yr` is repointed from the interim limit to
    `final_limit_lbs_yr`. If the permit has already reported — that is, if
    `reported_annual_load_lbs` is not null — the compliance reconciliation of §3.5
    re-runs against the now-tighter applicable limit, and the compliance posture
    may move as a result."

    Design: Difficulty/cross_entity_state_dependency/permit_finalization_gated_on_tmdl_approval_then_tightened_limit_flips_compliance
    """
    world = _reported_permit_on_an_unapproved_assessment(api)
    fx.publish_assessment(api, world["assessment_id"])
    approved = fx.approve_assessment(api, world["assessment_id"])
    assert approved["status"] == "APPROVED", approved

    finalized = fx.finalize_limits(api, world["permit_id"])

    assert finalized["limit_status"] == "FINAL", finalized
    assert_load(finalized["applicable_limit_lbs_yr"], 21888.00, "applicable_limit_lbs_yr")
    assert_load(finalized["compliance_gap_lbs"], 112.00, "compliance_gap_lbs")
    assert finalized["compliance_status"] == "SHORTFALL", finalized
    assert finalized["enforcement_flag"] is False, finalized
    assert_load(finalized["reported_annual_load_lbs"], 22000.00, "reported_annual_load_lbs")
