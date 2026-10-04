"""Employer partners, placements, milestones, and requisition conservation."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    validate_error, validate_success,
)
from test_helpers import factories, fixtures

CAREER = TEST_USERS["career_counselor_headers"]


def test_placement_requisition_conservation(api):
    """PRD section 3.6: "A successful placement starts in `ACTIVE`, decrements
    the employer's `open_requisitions` by 1, and bumps the employer partner's
    `version` by 1."
    PRD section 3.6: "separating from `ACTIVE` or `MILESTONE_30` — that is, any
    time before the day-90 milestone — restores the employer's
    `open_requisitions` by 1, while separating from `MILESTONE_90` or later does
    not."

    Design: Difficulty/compensating_invariant/placement_requisition_conservation
    """
    fixtures.reset_clock()
    member, track, enrollment = fixtures.setup_member_with_active_career_enrollment(
        member_name="Job Vet")
    employer = fixtures.create_employer_partner(
        name="Logistics Co", industry="LOGISTICS", open_requisitions=2)

    resp = api.create_placement(
        factories.create_placement_payload(member["id"], employer["id"],
                                           start_date="2026-09-15T00:00:00Z",
                                           salary_cents=6000000),
        CAREER)
    placement = validate_success(resp, 201)
    assert placement["status"] == "ACTIVE"
    assert fixtures.get_employer_by_name("Logistics Co")["open_requisitions"] == 1

    separated = fixtures.transition_placement(
        placement["id"], "SEPARATE", separation_reason="resigned in week one")
    assert separated["status"] == "SEPARATED", "separated from ACTIVE, before MILESTONE_90"

    assert fixtures.get_employer_by_name("Logistics Co")["open_requisitions"] == 2, (
        "create + early-separate is exactly compensating")


def test_milestone_confirm_temporal_boundary(api):
    """PRD section 3.6: "the day-30 confirmation requires the logical clock to
    be at or after `start_date` plus 30 days, day-90 at or after 90 days, and
    day-180 at or after 180 days. The exact day is allowed; confirming earlier is
    rejected with `ERR_MILESTONE_TOO_EARLY` (HTTP 422)."

    Design: Corner/validations/milestone_confirm_temporal_boundary
    """
    fixtures.reset_clock()
    member, track, enrollment = fixtures.setup_member_with_active_career_enrollment(
        member_name="Milestone Vet")
    employer = fixtures.create_employer_partner(
        name="Milestone Co", industry="RETAIL", open_requisitions=1)
    placement = fixtures.create_placement(
        member["id"], employer["id"], start_date="2026-09-10T09:00:00Z",
        salary_cents=5200000)

    fixtures.set_clock("2026-10-10T08:59:59Z")
    err_resp = api.transition_placement(
        placement["id"],
        factories.placement_transition_payload("CONFIRM_MILESTONE", milestone="DAY_30"),
        CAREER)
    validate_error(err_resp, ApiErrorId.ERR_MILESTONE_TOO_EARLY)
    placements = fixtures.list_placements(member_id=member["id"])
    assert placements[0]["status"] == "ACTIVE", "the failed attempt left the placement ACTIVE"

    fixtures.set_clock("2026-10-10T09:00:00Z")
    ok_resp = api.transition_placement(
        placement["id"],
        factories.placement_transition_payload("CONFIRM_MILESTONE", milestone="DAY_30"),
        CAREER)
    confirmed = validate_success(ok_resp)
    assert confirmed["status"] == "MILESTONE_30", "exactly start_date + 30 days is allowed"


def test_placement_without_career_enrollment_rejected(api):
    """PRD section 3.6: "The member must hold an enrollment on a `CAREER` track
    in `ACTIVE` status — placement without one is rejected with
    `ERR_NO_ACTIVE_CAREER_ENROLLMENT` (HTTP 409)."

    Design: Corner/validations/placement_without_career_enrollment_rejected
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="No Career Vet")
    employer = fixtures.create_employer_partner(
        name="Hiring Co", industry="RETAIL", open_requisitions=1)

    err_resp = api.create_placement(
        factories.create_placement_payload(member["id"], employer["id"]), CAREER)
    validate_error(err_resp, ApiErrorId.ERR_NO_ACTIVE_CAREER_ENROLLMENT)
    assert fixtures.get_employer_by_name("Hiring Co")["open_requisitions"] == 1, (
        "no decrement on failure")


def test_placement_at_zero_requisitions_rejected(api):
    """PRD section 3.6: "And the employer must actually have a requisition open:
    when `open_requisitions` is 0 the create is rejected with
    `ERR_NO_OPEN_REQUISITIONS` (HTTP 409)."

    Design: Corner/validations/placement_at_zero_requisitions_rejected
    """
    fixtures.reset_clock()
    member, track, enrollment = fixtures.setup_member_with_active_career_enrollment(
        member_name="Zero Req Vet")
    employer = fixtures.create_employer_partner(
        name="Full Co", industry="ENERGY", open_requisitions=0)

    err_resp = api.create_placement(
        factories.create_placement_payload(member["id"], employer["id"]), CAREER)
    validate_error(err_resp, ApiErrorId.ERR_NO_OPEN_REQUISITIONS)
    assert fixtures.list_placements(member_id=member["id"]) == []


def test_placement_create_unknown_employer_returns_employer_not_found(api):
    """PRD section 2.9: "Request-body foreign keys are likewise resolved in the
    order the endpoint's input list declares them."
    PRD section 2.7: "A missing reference yields the matching 404 identifier"

    Design: Corner/entities/placement_create_unknown_employer_returns_employer_not_found
    """
    fixtures.reset_clock()
    member = fixtures.create_member(full_name="FK Vet")
    resp = api.create_placement(
        factories.create_placement_payload(member["id"], NON_EXISTENT_UUID), CAREER)
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_NOT_FOUND)
    assert resp.json()["data"]["error_id"] != "ERR_NO_ACTIVE_CAREER_ENROLLMENT", (
        "existence runs before the referential gate")


def test_placement_transition_unknown_id_returns_placement_not_found(api):
    """PRD section 2.7: "A missing reference yields the matching 404 identifier"

    Design: Corner/entities/placement_transition_unknown_id_returns_placement_not_found
    """
    fixtures.reset_clock()
    resp = api.transition_placement(
        NON_EXISTENT_UUID, factories.placement_transition_payload("SEPARATE"), CAREER)
    validate_error(resp, ApiErrorId.ERR_PLACEMENT_NOT_FOUND)
