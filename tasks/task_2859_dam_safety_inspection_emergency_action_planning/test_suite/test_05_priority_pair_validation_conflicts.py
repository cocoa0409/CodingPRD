"""Requests that violate two rules at once and must report the higher-ranked one."""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import assert_cents
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    DECISION_DENY,
    DECISION_ISSUE,
    DELINQUENCY_DELINQUENT,
    HAZARD_SIGNIFICANT,
    INSPECTION_SCHEDULED,
    LICENSE_EXPIRED,
    PERMIT_SUBMITTED,
    PERMIT_TYPE_CONSTRUCTION,
    PERMIT_UNDER_ENGINEERING_REVIEW,
    SAFETY_SATISFACTORY,
    SAFETY_UNRATED,
)
from test_helpers.test_users import make_engineer_headers


# ---------------------------------------------------------------------------
# Permit state (rung 14) outranks owner delinquency (rung 35)
# ---------------------------------------------------------------------------
@pytest.fixture()
def unassigned_permit_with_delinquent_owner(program, base):
    """A SUBMITTED permit whose own 430,000-cent fee made its owner delinquent."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    permit = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_CONSTRUCTION,
        scope_description="New outlet works and stilling basin.",
        estimated_project_cost_cents=40_000_000,
    )
    return permit


def test_an_unassigned_permit_reports_invalid_state_not_delinquency(
    api, program, base, unassigned_permit_with_delinquent_owner
):
    """Two gates are violated at once and the state gate is the one reported.

    PRD 3.6: "The acting `X-User-ID` must equal the permit's `review_engineer_id`; on an unassigned permit this comparison is skipped and the request is instead reported as `ERR_PERMIT_INVALID_STATE`, because a permit with no reviewer is still `SUBMITTED`."

    Design: Difficulty/priority_pair_validation_conflict/permit_state_conflict_rejected_ahead_of_owner_delinquency
    """
    permit = unassigned_permit_with_delinquent_owner
    assert permit["status"] == PERMIT_SUBMITTED
    assert permit["review_engineer_id"] is None
    assert_cents(permit["total_fee_cents"], 430000, "total_fee_cents")

    owner = program.get_owner(base.owner_id)
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT
    assert_cents(owner["fee_balance_cents"], 430000, "fee_balance_cents")

    response = api.decide_permit(
        permit["id"],
        f.permit_decision_payload(decision=DECISION_ISSUE, findings="Design conforms."),
        make_engineer_headers(base.engineer_a_id),
    )
    validate_error(response, ApiErrorId.ERR_PERMIT_INVALID_STATE.value, 409)

    unchanged = program.get_permit(permit["id"])
    assert unchanged["status"] == PERMIT_SUBMITTED
    assert unchanged["issued_at"] is None


def test_once_assigned_the_same_request_reports_owner_delinquency(
    api, program, base, unassigned_permit_with_delinquent_owner
):
    """With the state gate satisfied the lower-ranked fiscal gate becomes visible.

    PRD 2.5: "**Owner not delinquent** — the owner's fee balance is below the delinquency threshold when a permit decision is taken; otherwise `ERR_OWNER_DELINQUENT` (402). Applies to the permit decision, and is outranked by the permit state check at rung 14."

    Design: Difficulty/priority_pair_validation_conflict/permit_state_conflict_rejected_ahead_of_owner_delinquency
    """
    permit = unassigned_permit_with_delinquent_owner
    assigned = program.assign_permit_review(permit["id"], base.engineer_a_id)
    assert assigned["status"] == PERMIT_UNDER_ENGINEERING_REVIEW

    response = api.decide_permit(
        permit["id"],
        f.permit_decision_payload(decision=DECISION_ISSUE, findings="Design conforms."),
        make_engineer_headers(base.engineer_a_id),
    )
    validate_error(response, ApiErrorId.ERR_OWNER_DELINQUENT.value, 402)

    unchanged = program.get_permit(permit["id"])
    assert unchanged["status"] == PERMIT_UNDER_ENGINEERING_REVIEW
    assert unchanged["issued_at"] is None
    owner = program.get_owner(base.owner_id)
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT
    assert_cents(owner["fee_balance_cents"], 430000, "fee_balance_cents")


def test_the_decision_gate_guards_a_denial_just_as_it_guards_an_issuance(
    api, program, base, unassigned_permit_with_delinquent_owner
):
    """A delinquent owner's permit cannot be denied on the merits either.

    PRD 3.6: "Note that all four gates guard the decision itself, not just an issuance: a delinquent owner's permit cannot even be denied on the merits until the balance is settled."

    Design: Difficulty/priority_pair_validation_conflict/permit_state_conflict_rejected_ahead_of_owner_delinquency
    """
    permit = unassigned_permit_with_delinquent_owner
    program.assign_permit_review(permit["id"], base.engineer_a_id)

    response = api.decide_permit(
        permit["id"],
        f.permit_decision_payload(
            decision=DECISION_DENY, findings="Spillway capacity not demonstrated."
        ),
        make_engineer_headers(base.engineer_a_id),
    )
    validate_error(response, ApiErrorId.ERR_OWNER_DELINQUENT.value, 402)
    assert program.get_permit(permit["id"])["status"] == PERMIT_UNDER_ENGINEERING_REVIEW
    assert program.get_permit(permit["id"])["issued_at"] is None


# ---------------------------------------------------------------------------
# Licence currency (rung 20) outranks the temporal window checks beneath it
# ---------------------------------------------------------------------------
@pytest.fixture()
def lapsed_engineer_inspection(program):
    """An inspection assigned to an engineer whose licence lapses before submission."""
    base = program.bootstrap(
        engineer_b={"license_expires_at": "2026-12-31T00:00:00Z"},
    )
    program.classify_significant(base.dam_id, base.engineer_a_id)
    inspection = program.schedule_inspection(
        base.dam_id,
        base.engineer_b_id,
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T12:00:00Z",
    )
    program.set_clock("2027-01-05T00:00:00Z")
    return {"base": base, "inspection": inspection}


def test_a_lapsed_licence_outranks_every_temporal_check_beneath_it(
    api, program, lapsed_engineer_inspection
):
    """The submission also sits outside its window, yet the licence rung reports first.

    PRD 2.5: "No unlicensed engineering act is ever recorded, which is why this rung outranks every temporal and constraint check beneath it."

    Design: Difficulty/priority_pair_validation_conflict/expired_license_rejected_ahead_of_the_inspection_window_check
    """
    base = lapsed_engineer_inspection["base"]
    inspection = lapsed_engineer_inspection["inspection"]

    response = api.submit_inspection(
        inspection["id"],
        f.inspection_submission_payload(
            performed_at="2026-08-05T12:00:00Z",
            condition_rating=SAFETY_SATISFACTORY,
            narrative="Walkover completed; no new deficiencies.",
        ),
        make_engineer_headers(base.engineer_b_id),
    )
    validate_error(response, ApiErrorId.ERR_ENGINEER_LICENSE_EXPIRED.value, 422)


def test_the_lapsed_licence_leaves_the_inspection_and_the_dam_untouched(
    api, program, lapsed_engineer_inspection
):
    """A rejected submission records nothing at all against the visit or the dam.

    PRD 2.10: "Advancing the clock past an engineer's expiry therefore silently disqualifies them from every engineering act in the program without any row being rewritten."

    Design: Difficulty/priority_pair_validation_conflict/expired_license_rejected_ahead_of_the_inspection_window_check
    """
    base = lapsed_engineer_inspection["base"]
    inspection = lapsed_engineer_inspection["inspection"]

    api.submit_inspection(
        inspection["id"],
        f.inspection_submission_payload(
            performed_at="2026-08-05T12:00:00Z",
            condition_rating=SAFETY_SATISFACTORY,
            narrative="Walkover completed; no new deficiencies.",
        ),
        make_engineer_headers(base.engineer_b_id),
    )

    engineer = program.get_engineer(base.engineer_b_id)
    assert engineer["license_status"] == LICENSE_EXPIRED

    stored = program.inspections_for(base.dam_id)[0]
    assert stored["id"] == inspection["id"]
    assert stored["status"] == INSPECTION_SCHEDULED
    assert stored["performed_at"] is None
    assert stored["condition_rating"] is None
    assert stored["return_count"] == 0

    dam = program.get_dam(base.dam_id)
    assert dam["safety_status"] == SAFETY_UNRATED
    assert dam["hazard_class"] == HAZARD_SIGNIFICANT
