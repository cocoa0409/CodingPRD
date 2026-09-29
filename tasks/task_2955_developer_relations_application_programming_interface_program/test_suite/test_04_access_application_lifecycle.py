"""The access-application review loop: submission, the claim that anchors segregation of duties,
the bounded request-changes / resubmit cycle, the decision, and the two uniqueness invariants that
allow one live application per developer and version and one entitlement per approval.
"""
from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields
from test_helpers.constants import CANONICAL_SCOPE, DEV_REL_MANAGER_ID
from test_helpers.test_users import (
    DEV_REL_MANAGER,
    DEV_REL_MANAGER_ALT,
    PLATFORM_ADMIN,
    make_platform_admin_headers,
)
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

CHANGES_NOTE = "Name the downstream systems that receive the catalog payload."


def _partner_draft(programme):
    """A product with a generally available version and one developer's DRAFT PARTNER application."""
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.draft_application(developer, version)
    return product, version, developer, application


def test_requesting_changes_returns_the_claimed_application_to_the_developer(api, programme):
    """A first submission puts the application on its first revision round, and the reviewer that
    claimed it can send it back with a note.

    PRD: "On success the application moves `DRAFT → SUBMITTED` and `revision_round` increments —
    reaching 1 on the very first submission."
    PRD: "The claiming reviewer may send the application back with a mandatory
    `changes_requested_note`, moving it `UNDER_REVIEW → CHANGES_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/access_application_revision_cycle_capped_at_three_rounds
    """
    _product, _version, developer, application = _partner_draft(programme)
    programme.submit_application(application, developer)
    programme.claim_application(application)

    returned = validate_success(
        api.request_application_changes(
            application["id"], f.request_changes_payload(changes_requested_note=CHANGES_NOTE),
            DEV_REL_MANAGER,
        )
    )

    assert_fields(
        returned, "AccessApplication",
        state="CHANGES_REQUESTED",
        revision_round=1,
        changes_requested_note=CHANGES_NOTE,
        reviewer_user_id=DEV_REL_MANAGER_ID,
    )


def test_resubmitting_after_a_change_request_advances_the_round_and_clears_the_note(api, programme):
    """The developer's answer to a change request moves the application back into review's queue,
    counts a further round and drops the reviewer's note.

    PRD: "A developer answering a change request resubmits, which moves the application
    `CHANGES_REQUESTED → SUBMITTED`, increments `revision_round` and clears `changes_requested_note`;
    that resubmission is likewise refused with `ERR_REVISION_LIMIT_REACHED` once `revision_round` has
    reached 3."

    Design: Difficulty/non_linear_state_machine/access_application_revision_cycle_capped_at_three_rounds
    """
    _product, _version, developer, application = _partner_draft(programme)
    programme.submit_application(application, developer)
    programme.claim_application(application)
    programme.request_changes(application, changes_requested_note=CHANGES_NOTE)

    resubmitted = validate_success(
        api.submit_access_application(
            application["id"], f.submit_application_payload(), programme.headers_for(developer)
        )
    )

    assert_fields(
        resubmitted, "AccessApplication",
        state="SUBMITTED",
        revision_round=2,
        changes_requested_note=None,
    )


def test_the_third_request_for_changes_is_refused_at_the_revision_cap(api, programme):
    """After two completed revision cycles the loop counter has reached the cap of three, so a third
    request for changes is refused and the application stays under review, still decidable.

    PRD: "Three conditions apply: the application must be in `UNDER_REVIEW`; the acting operator's
    `X-User-ID` must equal the recorded `reviewer_user_id`; and `revision_round` must still be below
    the cap of **3** completed rounds, otherwise `ERR_REVISION_LIMIT_REACHED` (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/access_application_revision_cycle_capped_at_three_rounds
    """
    _product, _version, developer, application = _partner_draft(programme)
    programme.submit_application(application, developer)
    programme.claim_application(application)
    programme.request_changes(application, changes_requested_note=CHANGES_NOTE)
    programme.submit_application(application, developer)
    programme.claim_application(application)
    programme.request_changes(
        application, changes_requested_note="State the retention period applied to cached records."
    )
    third_round = programme.submit_application(application, developer)
    assert_fields(third_round, "AccessApplication", state="SUBMITTED", revision_round=3)
    programme.claim_application(application)

    validate_error(
        api.request_application_changes(
            application["id"],
            f.request_changes_payload(changes_requested_note="One more clarification is needed."),
            DEV_REL_MANAGER,
        ),
        ApiError.REVISION_LIMIT_REACHED,
    )

    assert_fields(
        programme.read_application(application["id"]), "AccessApplication",
        state="UNDER_REVIEW",
        revision_round=3,
        reviewer_user_id=DEV_REL_MANAGER_ID,
    )


def test_submitting_against_a_version_whose_deprecation_was_announced_is_refused(api, programme):
    """Grantability is read off the pinned version's lifecycle state at submission time, so a draft
    that was legal when it was written is refused once its version has been deprecated.

    PRD: "A version in `DEPRECATION_ANNOUNCED` or `SUNSET` is grantable to no tier at all. Any
    mismatch is rejected with `ERR_VERSION_NOT_GRANTABLE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/application_submit_requires_grantable_version_lifecycle
    """
    _product, version, developer, application = _partner_draft(programme)
    announced = programme.announce_deprecation(version["id"], notice_days=30)
    assert_fields(
        announced, "ApiVersion",
        lifecycle_state="DEPRECATION_ANNOUNCED",
        required_notice_days=30,
        sunset_at="2026-08-31T00:00:00Z",
    )

    validate_error(
        api.submit_access_application(
            application["id"], f.submit_application_payload(), programme.headers_for(developer)
        ),
        ApiError.VERSION_NOT_GRANTABLE,
    )

    assert_fields(
        programme.read_application(application["id"]), "AccessApplication",
        state="DRAFT", revision_round=0,
    )


def test_a_draft_may_still_be_written_against_a_deprecated_version(api, programme):
    """The grantability gate belongs to submission, not to drafting: a brand-new application naming
    the deprecated version is still created, and only its submission is refused.

    PRD: "Two checks bite at draft time."
    PRD: "Grantability is a function of `lifecycle_state` and requested tier, and it is checked both
    when an application is submitted and when an entitlement is provisioned from it."

    Design: Difficulty/cross_entity_state_dependency/application_submit_requires_grantable_version_lifecycle
    """
    _product, version, _developer, _application = _partner_draft(programme)
    programme.announce_deprecation(version["id"], notice_days=30)
    latecomer = programme.onboarded_developer()

    payload = f.access_application_payload(latecomer["id"], version["id"])
    fresh = validate_success(
        api.create_access_application(payload, programme.headers_for(latecomer)), 201
    )

    assert_fields(fresh, "AccessApplication", state="DRAFT", revision_round=0)
    validate_error(
        api.submit_access_application(
            fresh["id"], f.submit_application_payload(), programme.headers_for(latecomer)
        ),
        ApiError.VERSION_NOT_GRANTABLE,
    )


def test_claiming_a_review_twice_is_refused_and_keeps_the_first_reviewer(api, programme):
    """The claim is not replayable: a second manager claiming an application that is already under
    review is refused, and the recorded reviewer is not overwritten.

    PRD: "A `DevRelManager` claims a `SUBMITTED` application, moving it `SUBMITTED → UNDER_REVIEW`
    and recording the claiming operator's `X-User-ID` as `reviewer_user_id`."
    PRD: "(11) The access application is in a state the requested transition permits —
    `ERR_APPLICATION_STATE_INVALID`, 409, on submit, claim-review, request-changes and decide."

    Design: Corner/state_machines/repeated_claim_review_and_repeated_release_rejected
    """
    _product, _version, developer, application = _partner_draft(programme)
    programme.submit_application(application, developer)
    claimed = programme.claim_application(application)
    assert_fields(
        claimed, "AccessApplication", state="UNDER_REVIEW", reviewer_user_id=DEV_REL_MANAGER_ID
    )

    validate_error(
        api.claim_application_review(application["id"], {}, DEV_REL_MANAGER_ALT),
        ApiError.APPLICATION_STATE_INVALID,
    )

    assert_fields(
        programme.read_application(application["id"]), "AccessApplication",
        state="UNDER_REVIEW", reviewer_user_id=DEV_REL_MANAGER_ID,
    )


def test_a_second_live_application_for_the_same_version_is_refused(api, programme):
    """A developer may keep only one application alive against a given version, so a cheaper second
    draft for the same target is refused and the developer's application list still counts one.

    PRD: "And a developer may not hold two applications that are still live for the same target
    version: if any application of this developer against this `target_api_version_id` sits in a
    non-terminal `state` — that is, anything other than `APPROVED` or `REJECTED` — the new draft is
    rejected with `ERR_DUPLICATE_APPLICATION` (HTTP 409)."

    Design: Corner/errors/one_live_application_and_one_assignment_per_approval
    """
    _product, version, developer, application = _partner_draft(programme)

    duplicate = f.access_application_payload(
        developer["id"], version["id"],
        requested_tier="STANDARD",
        requested_monthly_calls=200000,
        justification_text="A second, cheaper application for the very same catalogue version.",
    )
    validate_error(
        api.create_access_application(duplicate, programme.headers_for(developer)),
        ApiError.DUPLICATE_APPLICATION,
    )

    applications, meta = validate_paginated(
        api.list_access_applications(PLATFORM_ADMIN, {"developer_id": developer["id"]})
    )
    assert meta["total_count"] == 1, f"expected a single application, meta was {meta}"
    assert [item["id"] for item in applications] == [application["id"]], (
        f"unexpected application list: {[item['id'] for item in applications]}"
    )


def test_a_second_entitlement_for_one_approval_is_refused_even_with_a_current_product_view(
    api, programme
):
    """One approval backs exactly one entitlement: a second provisioning attempt that carries a
    freshly read product version passes the staleness guard and is still refused, and the product's
    reservation counter is untouched by the refusal.

    PRD: "An approved application may back exactly one entitlement; a second attempt against the same
    application is refused with `ERR_ASSIGNMENT_ALREADY_EXISTS` (HTTP 409)."
    PRD: "Against these the product maintains two reservation counters, `allocated_sustained_rpm` and
    `allocated_monthly_calls`, each defined as the sum over the product's entitlements in
    `entitlement_state` `PROVISIONED` or `ACTIVE` of that entitlement's `sustained_rpm` and
    `monthly_call_allowance` respectively; both counters start at 0."

    Design: Corner/errors/one_live_application_and_one_assignment_per_approval
    """
    product, version, developer, application = _partner_draft(programme)
    programme.submit_application(application, developer)
    programme.claim_application(application)
    programme.decide_application(
        application, decision="APPROVE", approved_tier="PARTNER",
        granted_scopes=[CANONICAL_SCOPE],
    )

    first = validate_success(
        api.create_quota_assignment(
            f.quota_assignment_payload(
                application["id"], programme.product_version_counter(product["id"])
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )
    assert_fields(first, "QuotaAssignment", entitlement_state="PROVISIONED")

    validate_error(
        api.create_quota_assignment(
            f.quota_assignment_payload(
                application["id"], programme.product_version_counter(product["id"])
            ),
            PLATFORM_ADMIN,
        ),
        ApiError.ASSIGNMENT_ALREADY_EXISTS,
    )

    _assignments, meta = validate_paginated(
        api.list_quota_assignments(
            PLATFORM_ADMIN, {"access_application_id": application["id"]}
        )
    )
    assert meta["total_count"] == 1, f"expected a single entitlement, meta was {meta}"
    assert_fields(
        programme.read_product(product["id"]), "ApiProduct",
        allocated_sustained_rpm=first["sustained_rpm"],
        allocated_monthly_calls=first["monthly_call_allowance"],
    )
    assert version["id"] == first["pinned_api_version_id"], (
        "the entitlement did not pin the application's target version"
    )


def test_the_operator_that_reviewed_the_application_may_not_decide_it(api, programme):
    """Segregation of duties compares acting identities rather than roles, so the manager that
    claimed the review is refused when it presents the administrator role to decide.

    PRD: "The acting operator's `X-User-ID` must differ from the recorded `reviewer_user_id`,
    otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

    Design: Corner/rbac/the_reviewer_may_not_decide_the_application_it_reviewed
    """
    _product, _version, developer, application = _partner_draft(programme)
    programme.submit_application(application, developer)
    programme.claim_application(application)

    validate_error(
        api.decide_access_application(
            application["id"],
            f.decide_application_payload(
                decision="APPROVE", approved_tier="PARTNER", granted_scopes=[CANONICAL_SCOPE]
            ),
            make_platform_admin_headers(DEV_REL_MANAGER_ID),
        ),
        ApiError.SEGREGATION_OF_DUTIES,
    )

    assert_fields(
        programme.read_application(application["id"]), "AccessApplication",
        state="UNDER_REVIEW", approver_user_id=None, decided_at=None,
    )


def test_a_second_operator_identity_decides_the_reviewed_application(api, programme):
    """A different acting identity on the deciding role approves the same application, which records
    the approver while leaving the recorded reviewer in place.

    PRD: "On approval the application moves `UNDER_REVIEW → APPROVED`, records `approver_user_id`
    from `X-User-ID`, stores `approved_tier` and `granted_scopes`, sets `decided_at` from the logical
    clock, and computes `data_access_limit` — the highest data sensitivity the approved tier may
    touch, which is `PUBLIC` at `SANDBOX`, `PERSONAL` at `STANDARD`, and `FINANCIAL` at both
    `PARTNER` and `PRIVILEGED`."

    Design: Corner/rbac/the_reviewer_may_not_decide_the_application_it_reviewed
    """
    _product, _version, developer, application = _partner_draft(programme)
    programme.submit_application(application, developer)
    programme.claim_application(application)

    decided = validate_success(
        api.decide_access_application(
            application["id"],
            f.decide_application_payload(
                decision="APPROVE", approved_tier="PARTNER", granted_scopes=[CANONICAL_SCOPE],
                decision_reason="Independent second pair of eyes.",
            ),
            PLATFORM_ADMIN,
        )
    )

    assert_fields(
        decided, "AccessApplication",
        state="APPROVED",
        approved_tier="PARTNER",
        granted_scopes=[CANONICAL_SCOPE],
        data_access_limit="FINANCIAL",
        reviewer_user_id=DEV_REL_MANAGER_ID,
    )
    assert decided["decided_at"] is not None, "an approval must record decided_at"
