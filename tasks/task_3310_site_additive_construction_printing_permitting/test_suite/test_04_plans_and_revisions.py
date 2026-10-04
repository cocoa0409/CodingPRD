"""Structural plan / revision lifecycle and cascade tests (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    PERMIT_COORD,
    assert_permit_application,
    create_approved_plan_revision,
    create_jurisdiction,
    create_permit_application_payload,
    create_plan_revision_payload,
    create_site,
    create_structural_plan_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_engineer_headers

ALICE = make_engineer_headers("eng-alice")
BOB = make_engineer_headers("eng-bob")


def _revision_by_id(api, plan_id, revision_id):
    revisions, _meta = validate_paginated(api.list_plan_revisions(plan_id, ALICE))
    return next(r for r in revisions if r["id"] == revision_id)


def test_plan_revision_approval_cascades_through_permits_and_structural_plan(api):
    """PRD §3.3: "Approval (`SUBMITTED` → `APPROVED`) stamps
    `approval_reviewer_id`, transitions the parent plan to `APPROVED`, sets both
    `approved_revision_id` and `current_revision_id` on the plan to the newly
    approved revision, and cascades any previously `APPROVED` revision on the
    same plan to `VOIDED`. That void, in turn, cascades any `PermitApplication`
    referencing the voided revision and still in `DRAFT` or `SUBMITTED` to
    `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/plan_revision_approval_cascades_through_permits_and_structural_plan
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(code="JD")
    plan, r1 = create_approved_plan_revision(plan_area_m2=80)
    site = create_site(jurisdiction["id"], address="21 G St")
    app = get_success_data(
        api.create_permit_application(
            site["id"], create_permit_application_payload(r1["id"]), PERMIT_COORD
        )
    )
    r2 = get_success_data(
        api.create_plan_revision(
            plan["id"],
            create_plan_revision_payload(supersedes_revision_id=r1["id"]),
            ALICE,
        )
    )
    get_success_data(api.plan_revision_action(plan["id"], r2["id"], {"action": "SUBMIT"}, ALICE))
    approved = validate_success(
        api.plan_revision_action(plan["id"], r2["id"], {"action": "APPROVE"}, BOB)
    )
    assert approved["status"] == "APPROVED"
    assert _revision_by_id(api, plan["id"], r1["id"])["status"] == "VOIDED"
    app_now = get_success_data(api.get_permit_application(site["id"], app["id"], PERMIT_COORD))
    assert app_now["status"] == "WITHDRAWN"


def test_superseded_revision_pointer_moves_to_new_approval(api):
    """PRD §3.3: "sets both `approved_revision_id` and `current_revision_id` on
    the plan to the newly approved revision, and cascades any previously
    `APPROVED` revision on the same plan to `VOIDED`."

    Design: Difficulty/transitive_cascade/plan_revision_approval_cascades_through_permits_and_structural_plan
    """
    set_clock("2026-09-01T00:00:00Z")
    plan, r1 = create_approved_plan_revision(plan_area_m2=80)
    r2 = get_success_data(
        api.create_plan_revision(plan["id"], create_plan_revision_payload(), ALICE)
    )
    get_success_data(api.plan_revision_action(plan["id"], r2["id"], {"action": "SUBMIT"}, ALICE))
    get_success_data(api.plan_revision_action(plan["id"], r2["id"], {"action": "APPROVE"}, BOB))
    revisions, _meta = validate_paginated(api.list_plan_revisions(plan["id"], ALICE))
    by_id = {r["id"]: r for r in revisions}
    assert by_id[r1["id"]]["status"] == "VOIDED"
    assert by_id[r2["id"]]["status"] == "APPROVED"


def test_concurrent_review_rejected(api):
    """PRD §3.3: "Only one revision per plan may be in `SUBMITTED` at a time; a
    second submission while another revision of the same plan is still
    `SUBMITTED` is rejected with `ERR_CONCURRENT_REVIEW`."

    Design: Difficulty/transitive_cascade/plan_revision_approval_cascades_through_permits_and_structural_plan
    """
    set_clock("2026-09-01T00:00:00Z")
    plan = get_success_data(
        api.create_structural_plan(create_structural_plan_payload(), ALICE)
    )
    r1 = get_success_data(
        api.create_plan_revision(plan["id"], create_plan_revision_payload(), ALICE)
    )
    r2 = get_success_data(
        api.create_plan_revision(plan["id"], create_plan_revision_payload(), ALICE)
    )
    get_success_data(api.plan_revision_action(plan["id"], r1["id"], {"action": "SUBMIT"}, ALICE))
    resp = api.plan_revision_action(plan["id"], r2["id"], {"action": "SUBMIT"}, ALICE)
    validate_error(resp, ApiErrorId.ERR_CONCURRENT_REVIEW)


def test_revision_number_counts_non_voided_revisions(api):
    """PRD §3.3: "The server assigns `revision_number` as one plus the count of
    prior non-`VOIDED` revisions on the same plan, ordered chronologically by
    `created_at`."

    Design: Difficulty/transitive_cascade/plan_revision_approval_cascades_through_permits_and_structural_plan
    """
    set_clock("2026-09-01T00:00:00Z")
    plan, r1 = create_approved_plan_revision(plan_area_m2=80)
    assert r1["revision_number"] == 1
    r2 = get_success_data(
        api.create_plan_revision(plan["id"], create_plan_revision_payload(), ALICE)
    )
    # r1 is APPROVED (non-VOIDED) so r2 gets revision_number 2.
    assert r2["revision_number"] == 2
