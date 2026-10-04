"""Assurance argument: evidence coverage, revision loop cap, dual readiness scores."""
import pytest

from test_helpers import (
    EXPECTED_READINESS_AFTER_UNVERIFY,
    EXPECTED_READINESS_SELF_FULL,
    EXPECTED_READINESS_VERIFIED_9,
    EVIDENCE_PLAN_TEACHING_QUALITY_EXTRA,
    READINESS_VERIFIED_PLAN_9,
    ApiErrorId,
    add_evidence_item,
    create_assurance_argument,
    get_assurance_argument,
    make_liaison_headers,
    request_argument_revision,
    set_evidence_verified,
    setup_argument_draft,
    setup_cycle_materials_open,
    setup_locked_argument,
    setup_submitted_argument,
    submit_argument,
    validate_error,
    validate_paginated,
    validate_success,
    verify_evidence_plan,
    verify_payload,
)


def test_evidence_item_rejects_unknown_criterion_code(api):
    """PRD section 2.8: "Payloads that are structurally malformed — a missing required field, a value of the wrong type, an invalid enum member, or a missing type-specific detail field such as `requested_program_level` on a `PROGRAM_LEVEL` change — are rejected with `ERR_VALIDATION` (HTTP 400)."
    PRD section 3.4: "An evidence item is born with `verified` false and `verified_by_reviewer_id` null."

    Design: Corner/entities/evidence_item_invalid_enum_criterion_returns_invalid_request
    """
    ctx = setup_cycle_materials_open()
    institution_id = ctx["institution"]["id"]
    argument = create_assurance_argument(ctx["cycle"]["id"], institution_id)

    bad = api.create_evidence_item(
        argument["id"],
        {"criterion_code": "CRIT_VIBES", "evidence_type": "POLICY_DOCUMENT",
         "title": "Bad enum", "document_uri": "s3://ev/bad.pdf"},
        make_liaison_headers(institution_id),
    )
    validate_error(bad, ApiErrorId.ERR_VALIDATION)

    good = add_evidence_item(argument["id"], institution_id, "CRIT_MISSION", 1)
    assert good["verified"] is False
    assert good["verified_by_reviewer_id"] is None


def test_argument_resubmit_while_submitted_rejected(api):
    """PRD section 2.8: "A request that would fail several checks receives the error of the first check in the evaluation order — the first failure wins."
    PRD section 3.4: "A successful submission moves the argument to `SUBMITTED`, stamps `submitted_at`, and computes the self-reported readiness score onto `readiness_self_reported`."

    Design: Corner/state_machines/argument_resubmit_while_submitted_rejected
    """
    ctx = setup_submitted_argument()
    institution_id = ctx["institution"]["id"]
    argument_id = ctx["argument"]["id"]

    response = api.submit_assurance_argument(
        argument_id, {}, make_liaison_headers(institution_id)
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_assurance_argument(argument_id)["revision_count"] == 0


def test_revision_loop_terminates_at_cap_with_terminal_rejection(api, staff_headers):
    """PRD section 3.4: "The loop is bounded: requesting a revision when `revision_count` has already reached the maximum of 2 fails the call with `ERR_MAX_REVISIONS_EXCEEDED` (HTTP 409), and within that same rejected request the argument transitions to the terminal `REJECTED_AS_INSUFFICIENT`."

    Design: Difficulty/non_linear_state_machine/assurance_argument_revision_loop_terminates_at_cap
    """
    ctx = setup_argument_draft()
    institution_id = ctx["institution"]["id"]
    argument_id = ctx["argument"]["id"]

    submit_argument(argument_id, institution_id)
    first = request_argument_revision(argument_id)
    assert first["revision_count"] == 1
    assert first["status"] == "REVISION_REQUESTED"

    submit_argument(argument_id, institution_id)
    second = request_argument_revision(argument_id)
    assert second["revision_count"] == 2
    assert second["status"] == "REVISION_REQUESTED"

    submit_argument(argument_id, institution_id)
    third = api.request_argument_revision(argument_id, {}, staff_headers)
    validate_error(third, ApiErrorId.ERR_MAX_REVISIONS_EXCEEDED)
    assert get_assurance_argument(argument_id)["status"] == "REJECTED_AS_INSUFFICIENT"


def test_readiness_self_reported_differs_from_team_verified(api, staff_headers):
    """PRD section 3.4: "The two variants differ only in what counts as qualifying: the `SELF_REPORTED` variant, computed at every submission, counts every attached item regardless of verification, while the `TEAM_VERIFIED` variant counts only items whose `verified` flag is true, so the identical evidence set scores lower until the visiting team verifies it."
    PRD section 3.4: "For each criterion, the coverage fraction is the number of qualifying evidence items divided by the per-criterion requirement of 3, capped at 1.0; the readiness score is one hundred times the weighted sum of the five coverage fractions — weighted 0.15 for mission, 0.25 for integrity, 0.25 for teaching quality, 0.15 for teaching evaluation, and 0.20 for resources and planning — rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/readiness_self_reported_vs_team_verified
    """
    ctx = setup_locked_argument(evidence_plan=EVIDENCE_PLAN_TEACHING_QUALITY_EXTRA)
    argument_id = ctx["argument"]["id"]
    verifier_id = ctx["reviewers"]["members"][0]["id"]

    verify_evidence_plan(ctx["evidence"], READINESS_VERIFIED_PLAN_9, verifier_id)

    argument = get_assurance_argument(argument_id)
    assert argument["status"] == "REVIEW_LOCKED"
    # SELF_REPORTED: all 16 items count; the 4-item criterion still caps at 1.0.
    assert argument["readiness_self_reported"] == pytest.approx(
        EXPECTED_READINESS_SELF_FULL, abs=0.001
    )
    # TEAM_VERIFIED: coverage [1, 2/3, 1/3, 0, 1] -> 100 * 0.60.
    assert argument["readiness_team_verified"] == pytest.approx(
        EXPECTED_READINESS_VERIFIED_9, abs=0.001
    )


def test_verify_unverify_compensates_without_drift(api, staff_headers):
    """PRD section 3.4: "During the visit, accepted team members toggle verification on individual evidence items by passing `verified`; the call records the acting reviewer on `verified_by_reviewer_id`, resets that field to null whenever `verified` is set false, and recomputes the team-verified readiness on every toggle."

    Design: Difficulty/compensating_invariant/evidence_verify_unverify_partition_conserved
    """
    ctx = setup_locked_argument(evidence_plan=EVIDENCE_PLAN_TEACHING_QUALITY_EXTRA)
    argument_id = ctx["argument"]["id"]
    verifier_id = ctx["reviewers"]["members"][0]["id"]

    verify_evidence_plan(ctx["evidence"], READINESS_VERIFIED_PLAN_9, verifier_id)
    before = get_assurance_argument(argument_id)
    assert before["readiness_team_verified"] == pytest.approx(
        EXPECTED_READINESS_VERIFIED_9, abs=0.001
    )

    target = ctx["evidence"]["CRIT_TEACHING_QUALITY"][0]
    unverified = set_evidence_verified(target["id"], verifier_id, False)
    assert unverified["verified"] is False
    assert unverified["verified_by_reviewer_id"] is None
    # Verified coverage drops to [1, 2/3, 0, 0, 1] -> 100 * 0.516667 rounded.
    mid = get_assurance_argument(argument_id)
    assert mid["readiness_team_verified"] == pytest.approx(
        EXPECTED_READINESS_AFTER_UNVERIFY, abs=0.001
    )

    set_evidence_verified(target["id"], verifier_id, True)
    after = get_assurance_argument(argument_id)
    assert after["readiness_team_verified"] == pytest.approx(
        EXPECTED_READINESS_VERIFIED_9, abs=0.001
    )

    items, _meta = validate_paginated(
        api.list_evidence_items(argument_id, staff_headers, params={"limit": 100})
    )
    assert len(items) == 16


def test_staff_cannot_verify_evidence(api, staff_headers):
    """PRD section 2.1: "A request whose role is not among the roles authorized for the target endpoint, or that fails the entity-backed ownership binding described below, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD section 4: "| POST   | `/accreditation/evidence-items/{id}/verify` | Toggle an evidence item's verification during the visit | PeerReviewer |"

    Design: Corner/rbac/staff_cannot_verify_evidence
    """
    ctx = setup_locked_argument()
    argument_id = ctx["argument"]["id"]
    item = ctx["evidence"]["CRIT_MISSION"][0]

    response = api.verify_evidence_item(item["id"], verify_payload(True), staff_headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    items, _meta = validate_paginated(api.list_evidence_items(argument_id, staff_headers))
    current = {entry["id"]: entry for entry in items}
    assert current[item["id"]]["verified"] is False
