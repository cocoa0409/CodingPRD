"""Writes gated on the state of a third entity the request only names.

A quantification run is legal only when the named baseline is approved and belongs
to the same enrollment, and a verification is legal only when the named body is
accredited — a status axis that is checked well before its accreditation scope.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_BASELINE_ENROLLMENT_MISMATCH,
    ERR_BASELINE_NOT_APPROVED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NO_QUALIFYING_DATA,
    ERR_PRACTICE_NOT_ACCREDITED,
    ERR_VERIFICATION_BODY_SUSPENDED,
)
from test_helpers.assertions import assert_pct, assert_tonnes
from test_helpers.constants import (
    BASELINE_REJECTED,
    BODY_ACCREDITED,
    BODY_SUSPENDED,
    METHOD_MODEL,
    OPINION_PENDING,
    PRACTICE_REDUCED_TILLAGE,
    RUN_DRAFT,
    RUN_SUBMITTED,
)
from test_helpers.factories import (
    baseline_rejection_payload,
    quantification_run_payload,
    verification_body_payload,
    verification_payload,
)
from test_helpers.test_users import ADMIN_BASELINE_HEADERS, ADMIN_HEADERS


def _enrollment_with_a_rejected_baseline(scenario):
    """An active enrollment whose first baseline was rejected and whose second was approved."""
    scenario.accepted_enrollment()
    rejected = scenario.propose_baseline()
    get_success_data(
        scenario.api.reject_baseline(
            rejected["id"], baseline_rejection_payload(), ADMIN_BASELINE_HEADERS
        )
    )
    approved = scenario.propose_baseline()
    scenario.approve_baseline(approved["id"])
    scenario.passed_packet()
    return rejected, approved


def test_run_creation_refuses_a_baseline_that_is_not_approved(scenario):
    """The rejected baseline belongs to the right enrollment but is in the wrong state, and
    the refusal names the approval gate rather than the enrollment's own state.

    PRD §3.6: "the named baseline must belong to that same enrollment (otherwise
    `ERR_BASELINE_ENROLLMENT_MISMATCH`) and must be in `APPROVED` status (otherwise
    `ERR_BASELINE_NOT_APPROVED`)."

    Design: Difficulty/cross_entity_state_dependency/run_creation_gated_on_baseline_status_and_ownership
    """
    rejected, _approved = _enrollment_with_a_rejected_baseline(scenario)
    assert get_success_data(scenario.api.get_baseline(rejected["id"], ADMIN_HEADERS))[
        "status"] == BASELINE_REJECTED
    version = scenario.enrollment_version

    response = scenario.api.create_quantification_run(
        quantification_run_payload(scenario.enrollment_id, rejected["id"], version, 2026,
                                   METHOD_MODEL),
        ADMIN_HEADERS,
    )

    validate_error(response, ERR_BASELINE_NOT_APPROVED, 422)
    # The enrollment is active and a passed packet exists, so neither of those gates fired.
    assert ERR_INVALID_STATE_TRANSITION not in response.text
    assert ERR_NO_QUALIFYING_DATA not in response.text
    assert scenario.enrollment_version == version


def test_run_creation_refuses_an_approved_baseline_of_another_enrollment(scenario):
    """A baseline that is approved but hangs from a sibling enrollment is a linkage failure,
    and the stale-free version token still opens the run once the right baseline is named.

    PRD §2.10: "**Cross-entity linkage coherence.** The baseline named on a quantification
    run belongs to the same enrollment and is `APPROVED`; the verification body's
    `accredited_practices` contains the enrollment's `practice_code`; a batch naming
    `supersedes_batch_id` references a batch of the same enrollment → otherwise
    `ERR_BASELINE_NOT_APPROVED`, `ERR_BASELINE_ENROLLMENT_MISMATCH`,
    `ERR_PRACTICE_NOT_ACCREDITED` or `ERR_SUPERSEDED_BATCH_MISMATCH` (all 422)."

    Design: Difficulty/cross_entity_state_dependency/run_creation_gated_on_baseline_status_and_ownership
    """
    _rejected, approved = _enrollment_with_a_rejected_baseline(scenario)
    first_enrollment_id = scenario.enrollment_id
    _sibling, sibling_baseline, _field = scenario.additional_active_enrollment()
    version = scenario.reload_enrollment(first_enrollment_id)["version"]

    response = scenario.api.create_quantification_run(
        quantification_run_payload(first_enrollment_id, sibling_baseline["id"], version, 2026,
                                   METHOD_MODEL),
        ADMIN_HEADERS,
    )

    validate_error(response, ERR_BASELINE_ENROLLMENT_MISMATCH, 422)

    run = get_success_data(
        scenario.api.create_quantification_run(
            quantification_run_payload(first_enrollment_id, approved["id"], version, 2026,
                                       METHOD_MODEL),
            ADMIN_HEADERS,
        )
    )

    assert run["status"] == RUN_DRAFT
    assert_tonnes(run["net_removals_t"], 283.360)
    runs, _meta = validate_paginated(
        scenario.api.list_quantification_runs({"enrollment_id": first_enrollment_id},
                                             ADMIN_HEADERS)
    )
    assert len(runs) == 1


def test_verification_refuses_a_suspended_body_before_checking_its_scope(scenario):
    """A suspended body is refused on its standing axis, while a second body that is
    accredited for a different practice is refused on the scope axis instead.

    PRD §2.10: "**Verification-body standing.** The verification body involved in the write
    is `ACCREDITED` rather than `SUSPENDED` at the moment of the write → otherwise
    `ERR_VERIFICATION_BODY_SUSPENDED` (409). Applies to four operations: verification
    assignment, site-visit recording, opinion issuance and resampling."

    Design: Difficulty/cross_entity_state_dependency/verification_gated_on_verification_body_accreditation_axis
    """
    scenario.active_enrollment()
    scenario.passed_packet()
    scenario.create_run(METHOD_MODEL)
    scenario.submit_run()
    scenario.accredit_body()
    suspended = get_success_data(
        scenario.api.suspend_verification_body(scenario.body_id, None, ADMIN_HEADERS)
    )
    assert suspended["status"] == BODY_SUSPENDED
    other = get_success_data(
        scenario.api.create_verification_body(
            verification_body_payload(accredited_practices=[PRACTICE_REDUCED_TILLAGE]),
            ADMIN_HEADERS,
        )
    )

    refused_standing = scenario.api.create_verification(
        verification_payload(scenario.run_id, scenario.body_id, sample_pct=20.00), ADMIN_HEADERS
    )
    refused_scope = scenario.api.create_verification(
        verification_payload(scenario.run_id, other["id"], sample_pct=20.00), ADMIN_HEADERS
    )

    validate_error(refused_standing, ERR_VERIFICATION_BODY_SUSPENDED, 409)
    validate_error(refused_scope, ERR_PRACTICE_NOT_ACCREDITED, 422)
    assert other["status"] == BODY_ACCREDITED
    assert scenario.reload_run()["status"] == RUN_SUBMITTED


def test_reinstating_the_body_makes_the_identical_request_succeed(scenario):
    """Reinstatement changes nothing but the body's standing, and the byte-identical
    assignment then opens exactly one pending verification.

    PRD §3.6: "Reinstatement, permitted only while the body is `SUSPENDED`, returns it to
    `ACCREDITED` and makes its pending verifications actionable again with their original
    site-visit windows intact."

    Design: Difficulty/cross_entity_state_dependency/verification_gated_on_verification_body_accreditation_axis
    """
    scenario.active_enrollment()
    scenario.passed_packet()
    scenario.create_run(METHOD_MODEL)
    scenario.submit_run()
    scenario.accredit_body()
    get_success_data(scenario.api.suspend_verification_body(scenario.body_id, None, ADMIN_HEADERS))
    payload = verification_payload(scenario.run_id, scenario.body_id, sample_pct=20.00)
    validate_error(
        scenario.api.create_verification(payload, ADMIN_HEADERS),
        ERR_VERIFICATION_BODY_SUSPENDED, 409,
    )

    reinstated = get_success_data(
        scenario.api.reinstate_verification_body(scenario.body_id, None, ADMIN_HEADERS)
    )

    assert reinstated["status"] == BODY_ACCREDITED

    verification = get_success_data(scenario.api.create_verification(payload, ADMIN_HEADERS))

    assert verification["opinion"] == OPINION_PENDING
    assert_pct(verification["sample_pct"], 20.00)
    assert scenario.reload_run()["status"] == RUN_SUBMITTED
    listed, _meta = validate_paginated(
        scenario.api.list_verifications({"quantification_run_id": scenario.run_id}, ADMIN_HEADERS)
    )
    assert len(listed) == 1
