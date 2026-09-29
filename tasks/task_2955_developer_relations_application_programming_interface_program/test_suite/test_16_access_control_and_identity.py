"""Who may call what in the developer relations programme, and how the server refuses everyone else.

This file covers the identity surface: the two mandatory caller headers and the single endpoint
exempt from them, the four distinct authentication and authorisation refusals plus the ownership
refusal that only bites a well-authenticated developer reaching for another developer's row, the
fact that every path identifier family names its own not-found error, and the role table itself —
each role reaching its own exclusive operations and no role reaching another role's.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_nulls,
)
from test_helpers.constants import (
    ADMIN_ID,
    CANONICAL_SCOPE,
    DEV_REL_MANAGER_ID,
    TRUST_OFFICER_ID,
    UNKNOWN_ID,
)
from test_helpers.test_users import (
    ANONYMOUS,
    DEV_REL_MANAGER,
    NO_HEADERS,
    PLATFORM_ADMIN,
    SUPPORT_AGENT,
    TRUST_OFFICER,
    headers_with_blank_role,
    headers_with_blank_user_id,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_developer_headers,
)


# --------------------------------------------------------------------------------------
# Identity: the header pair, the refusals it produces, and the one exempt endpoint
# --------------------------------------------------------------------------------------
def test_the_logical_clock_read_is_exempt_from_the_identity_headers(api):
    """Reading the programme clock succeeds with no caller headers at all, and reports the startup default.

    PRD: "Reading the clock returns `current_utc` and, uniquely in this API, requires no authentication headers."

    Design: Corner/errors/auth_identity_and_ownership_errors_are_distinct
    """
    data = validate_success(api.get_clock(NO_HEADERS))

    assert_instant_equals(data["current_utc"], "2026-08-01T00:00:00Z", "current_utc")


def test_absent_or_empty_identity_headers_are_refused_as_missing_auth_headers(api, programme):
    """An application read that omits either identity header, or sends it as the empty string, is refused for missing headers.

    PRD: "Both headers must be present and non-empty on every endpoint in this specification with exactly one exception — reading the logical programme clock requires no authentication headers at all. A request that is missing either header, or that supplies an empty string for either, is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

    Design: Corner/errors/auth_identity_and_ownership_errors_are_distinct
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    owner = programme.onboarded_developer()
    application = programme.draft_application(owner, version, requested_tier="STANDARD")

    # The same read the owner is entitled to make, once per mutilated header pair.
    validate_error(
        api.get_access_application(application["id"], headers_without_role(owner["id"])),
        ApiError.MISSING_AUTH_HEADERS,
    )
    validate_error(
        api.get_access_application(application["id"], headers_with_blank_role(owner["id"])),
        ApiError.MISSING_AUTH_HEADERS,
    )
    validate_error(
        api.get_access_application(application["id"], headers_without_user_id()),
        ApiError.MISSING_AUTH_HEADERS,
    )
    validate_error(
        api.get_access_application(application["id"], headers_with_blank_user_id()),
        ApiError.MISSING_AUTH_HEADERS,
    )

    # The unmutilated read still works, so nothing above was refused for another reason.
    data = validate_success(
        api.get_access_application(application["id"], programme.headers_for(owner))
    )
    assert_fields(data, "AccessApplication", id=application["id"])


def test_an_undeclared_role_name_is_refused_before_authorisation(api, programme):
    """A caller declaring a role outside the six recognised names is refused as an unknown role, not as an unauthorised one.

    PRD: "A request whose `X-User-Role` is not one of the six role names declared below is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401), and this check applies to every endpoint including the clock read."

    Design: Corner/errors/auth_identity_and_ownership_errors_are_distinct
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    owner = programme.onboarded_developer()
    application = programme.draft_application(owner, version, requested_tier="STANDARD")

    validate_error(
        api.get_access_application(
            application["id"], headers_with_unknown_role(owner["id"], "Operator")
        ),
        ApiError.UNKNOWN_ROLE,
    )


def test_a_developer_identity_naming_no_developer_row_is_refused(api, programme):
    """A caller acting as `Developer` whose `X-User-ID` is not a registered developer is refused on identity, not on ownership.

    PRD: "When `X-User-Role` is `Developer`, `X-User-ID` is the `id` of the acting `Developer` record; if that value is not the `id` of an existing `Developer`, the request is rejected with `ERR_UNKNOWN_DEVELOPER_IDENTITY` (HTTP 401)."

    Design: Corner/errors/auth_identity_and_ownership_errors_are_distinct
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    owner = programme.onboarded_developer()
    application = programme.draft_application(owner, version, requested_tier="STANDARD")

    validate_error(
        api.get_access_application(application["id"], make_developer_headers(UNKNOWN_ID)),
        ApiError.UNKNOWN_DEVELOPER_IDENTITY,
    )


def test_a_role_outside_the_endpoints_authorised_list_is_refused_as_unauthorized(api, programme):
    """A registered developer reaching for the product catalogue write is refused, and no product comes into existence.

    PRD: "When the acting role does not appear in the authorised-roles list for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/errors/auth_identity_and_ownership_errors_are_distinct
    """
    developer = programme.register_developer()

    validate_error(
        api.create_api_product(f.api_product_payload(), programme.headers_for(developer)),
        ApiError.UNAUTHORIZED,
    )

    catalogue, meta = validate_paginated(api.list_api_products(PLATFORM_ADMIN))
    assert catalogue == [], f"a refused create still produced a product: {catalogue}"
    assert meta["total_count"] == 0, f"total_count should be 0, got {meta['total_count']}"


def test_a_developer_reading_another_developers_application_is_refused_as_not_owner(api, programme):
    """The owner reads its own application, while a second authentic developer reading the same row is refused as not its owner.

    PRD: "A `Developer` acting on a resource owned by a different developer is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403); this applies both to `Developer`-role writes and to `Developer`-role single-resource reads."

    Design: Corner/errors/auth_identity_and_ownership_errors_are_distinct
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    owner = programme.onboarded_developer()
    application = programme.draft_application(owner, version, requested_tier="STANDARD")
    other_developer = programme.register_developer()

    owned = validate_success(
        api.get_access_application(application["id"], programme.headers_for(owner))
    )
    assert_fields(owned, "AccessApplication", id=application["id"], developer_id=owner["id"])

    validate_error(
        api.get_access_application(application["id"], programme.headers_for(other_developer)),
        ApiError.NOT_RESOURCE_OWNER,
    )


# --------------------------------------------------------------------------------------
# Existence: one not-found error per path identifier family
# --------------------------------------------------------------------------------------
def test_an_unknown_api_version_id_names_the_api_version_family(api):
    """An unknown identifier in the api-versions path is refused with the error belonging to versions.

    PRD: "Every identifier appearing in the URL path resolves to an existing resource, checked strictly left to right, yielding whichever of `ERR_DEVELOPER_NOT_FOUND`, `ERR_API_PRODUCT_NOT_FOUND`, `ERR_API_VERSION_NOT_FOUND`, `ERR_ACCESS_APPLICATION_NOT_FOUND`, `ERR_QUOTA_ASSIGNMENT_NOT_FOUND`, `ERR_UPGRADE_REQUEST_NOT_FOUND`, `ERR_SANDBOX_LEASE_NOT_FOUND`, `ERR_VIOLATION_CASE_NOT_FOUND`, `ERR_SUPPORT_CASE_NOT_FOUND` or `ERR_FEEDBACK_ITEM_NOT_FOUND` matches the first unresolvable segment — all HTTP 404."

    Design: Corner/errors/every_path_id_family_has_its_own_not_found
    """
    validate_error(api.get_api_version(UNKNOWN_ID, PLATFORM_ADMIN), ApiError.API_VERSION_NOT_FOUND)


def test_an_unknown_access_application_id_names_the_access_application_family(api):
    """An unknown identifier in the access-applications path is refused with the error belonging to applications.

    PRD: "Every identifier appearing in the URL path resolves to an existing resource, checked strictly left to right, yielding whichever of `ERR_DEVELOPER_NOT_FOUND`, `ERR_API_PRODUCT_NOT_FOUND`, `ERR_API_VERSION_NOT_FOUND`, `ERR_ACCESS_APPLICATION_NOT_FOUND`, `ERR_QUOTA_ASSIGNMENT_NOT_FOUND`, `ERR_UPGRADE_REQUEST_NOT_FOUND`, `ERR_SANDBOX_LEASE_NOT_FOUND`, `ERR_VIOLATION_CASE_NOT_FOUND`, `ERR_SUPPORT_CASE_NOT_FOUND` or `ERR_FEEDBACK_ITEM_NOT_FOUND` matches the first unresolvable segment — all HTTP 404."

    Design: Corner/errors/every_path_id_family_has_its_own_not_found
    """
    validate_error(
        api.get_access_application(UNKNOWN_ID, PLATFORM_ADMIN),
        ApiError.ACCESS_APPLICATION_NOT_FOUND,
    )


def test_an_unknown_upgrade_request_id_names_the_upgrade_request_family(api):
    """An unknown identifier in the upgrade-requests path is refused with the error belonging to upgrade requests.

    PRD: "Every identifier appearing in the URL path resolves to an existing resource, checked strictly left to right, yielding whichever of `ERR_DEVELOPER_NOT_FOUND`, `ERR_API_PRODUCT_NOT_FOUND`, `ERR_API_VERSION_NOT_FOUND`, `ERR_ACCESS_APPLICATION_NOT_FOUND`, `ERR_QUOTA_ASSIGNMENT_NOT_FOUND`, `ERR_UPGRADE_REQUEST_NOT_FOUND`, `ERR_SANDBOX_LEASE_NOT_FOUND`, `ERR_VIOLATION_CASE_NOT_FOUND`, `ERR_SUPPORT_CASE_NOT_FOUND` or `ERR_FEEDBACK_ITEM_NOT_FOUND` matches the first unresolvable segment — all HTTP 404."

    Design: Corner/errors/every_path_id_family_has_its_own_not_found
    """
    validate_error(
        api.get_upgrade_request(UNKNOWN_ID, PLATFORM_ADMIN), ApiError.UPGRADE_REQUEST_NOT_FOUND
    )


def test_an_unknown_sandbox_lease_id_names_the_sandbox_lease_family(api):
    """An unknown identifier in the sandbox-leases path is refused with the error belonging to leases.

    PRD: "Every identifier appearing in the URL path resolves to an existing resource, checked strictly left to right, yielding whichever of `ERR_DEVELOPER_NOT_FOUND`, `ERR_API_PRODUCT_NOT_FOUND`, `ERR_API_VERSION_NOT_FOUND`, `ERR_ACCESS_APPLICATION_NOT_FOUND`, `ERR_QUOTA_ASSIGNMENT_NOT_FOUND`, `ERR_UPGRADE_REQUEST_NOT_FOUND`, `ERR_SANDBOX_LEASE_NOT_FOUND`, `ERR_VIOLATION_CASE_NOT_FOUND`, `ERR_SUPPORT_CASE_NOT_FOUND` or `ERR_FEEDBACK_ITEM_NOT_FOUND` matches the first unresolvable segment — all HTTP 404."

    Design: Corner/errors/every_path_id_family_has_its_own_not_found
    """
    validate_error(
        api.get_sandbox_lease(UNKNOWN_ID, PLATFORM_ADMIN), ApiError.SANDBOX_LEASE_NOT_FOUND
    )


def test_an_unknown_violation_case_id_names_the_violation_case_family(api):
    """An unknown identifier in the violation-cases path is refused with the error belonging to cases, for a role the endpoint permits.

    PRD: "Every identifier appearing in the URL path resolves to an existing resource, checked strictly left to right, yielding whichever of `ERR_DEVELOPER_NOT_FOUND`, `ERR_API_PRODUCT_NOT_FOUND`, `ERR_API_VERSION_NOT_FOUND`, `ERR_ACCESS_APPLICATION_NOT_FOUND`, `ERR_QUOTA_ASSIGNMENT_NOT_FOUND`, `ERR_UPGRADE_REQUEST_NOT_FOUND`, `ERR_SANDBOX_LEASE_NOT_FOUND`, `ERR_VIOLATION_CASE_NOT_FOUND`, `ERR_SUPPORT_CASE_NOT_FOUND` or `ERR_FEEDBACK_ITEM_NOT_FOUND` matches the first unresolvable segment — all HTTP 404."

    Design: Corner/errors/every_path_id_family_has_its_own_not_found
    """
    validate_error(
        api.get_violation_case(UNKNOWN_ID, TRUST_OFFICER), ApiError.VIOLATION_CASE_NOT_FOUND
    )


def test_an_unknown_support_case_id_names_the_support_case_family(api):
    """An unknown identifier in the support-cases path is refused with the error belonging to support cases, for a role the endpoint permits.

    PRD: "Every identifier appearing in the URL path resolves to an existing resource, checked strictly left to right, yielding whichever of `ERR_DEVELOPER_NOT_FOUND`, `ERR_API_PRODUCT_NOT_FOUND`, `ERR_API_VERSION_NOT_FOUND`, `ERR_ACCESS_APPLICATION_NOT_FOUND`, `ERR_QUOTA_ASSIGNMENT_NOT_FOUND`, `ERR_UPGRADE_REQUEST_NOT_FOUND`, `ERR_SANDBOX_LEASE_NOT_FOUND`, `ERR_VIOLATION_CASE_NOT_FOUND`, `ERR_SUPPORT_CASE_NOT_FOUND` or `ERR_FEEDBACK_ITEM_NOT_FOUND` matches the first unresolvable segment — all HTTP 404."

    Design: Corner/errors/every_path_id_family_has_its_own_not_found
    """
    validate_error(
        api.get_support_case(UNKNOWN_ID, SUPPORT_AGENT), ApiError.SUPPORT_CASE_NOT_FOUND
    )


def test_an_unknown_feedback_item_id_names_the_feedback_item_family(api):
    """An unknown identifier in the feedback-items path is refused with the error belonging to feedback items.

    PRD: "Every identifier appearing in the URL path resolves to an existing resource, checked strictly left to right, yielding whichever of `ERR_DEVELOPER_NOT_FOUND`, `ERR_API_PRODUCT_NOT_FOUND`, `ERR_API_VERSION_NOT_FOUND`, `ERR_ACCESS_APPLICATION_NOT_FOUND`, `ERR_QUOTA_ASSIGNMENT_NOT_FOUND`, `ERR_UPGRADE_REQUEST_NOT_FOUND`, `ERR_SANDBOX_LEASE_NOT_FOUND`, `ERR_VIOLATION_CASE_NOT_FOUND`, `ERR_SUPPORT_CASE_NOT_FOUND` or `ERR_FEEDBACK_ITEM_NOT_FOUND` matches the first unresolvable segment — all HTTP 404."

    Design: Corner/errors/every_path_id_family_has_its_own_not_found
    """
    validate_error(
        api.get_feedback_item(UNKNOWN_ID, DEV_REL_MANAGER), ApiError.FEEDBACK_ITEM_NOT_FOUND
    )


def test_a_nested_version_list_fails_on_the_unresolved_product_segment(api, programme):
    """Listing the versions of an unknown product names the product, the leftmost unresolved segment, and not the child collection.

    PRD: "For all of these the server resolves path identifiers strictly left to right and fails on the first segment that does not resolve, with the not-found error belonging to that segment's resource type."

    Design: Corner/errors/every_path_id_family_has_its_own_not_found
    """
    product = programme.create_product()

    # The same nested collection resolves for a product that exists.
    versions, meta = validate_paginated(api.list_api_versions(product["id"], PLATFORM_ADMIN))
    assert versions == [], f"a fresh product should carry no versions yet: {versions}"
    assert meta["total_count"] == 0, f"total_count should be 0, got {meta['total_count']}"

    validate_error(
        api.list_api_versions(UNKNOWN_ID, PLATFORM_ADMIN), ApiError.API_PRODUCT_NOT_FOUND
    )


# --------------------------------------------------------------------------------------
# The role table, positive half: every role reaches its own exclusive operations
# --------------------------------------------------------------------------------------
def test_anonymous_self_registration_yields_a_usable_developer_identity(api, programme):
    """The unauthenticated surface registers a developer, and the minted id acts immediately as the `Developer` identity.

    PRD: "`Anonymous` is the unauthenticated self-service surface: developer self-registration and reading the logical clock."
    PRD: "On success the two submitted numbers are recorded on the developer as `docs_version_acknowledged` and `tos_version_accepted`, `onboarding_state` advances `REGISTERED → DOCS_ACKNOWLEDGED`, and the developer's `trust_score` is recomputed under the onboarding-snapshot variant described below."

    Design: Corner/rbac/every_role_reaches_its_own_exclusive_operations
    """
    programme.create_product()  # the acknowledgement accepts a terms version some product requires

    registered = validate_success(
        api.register_developer(f.developer_payload(region_code="EU"), ANONYMOUS),
        expected_status=201,
    )
    assert_common_fields(registered, "Developer")
    assert_fields(
        registered,
        "Developer",
        onboarding_state="REGISTERED",
        standing="GOOD_STANDING",
        directory_state="NOT_LISTED",
    )

    acknowledged = validate_success(
        api.acknowledge_onboarding(
            registered["id"],
            f.onboarding_acknowledgement_payload(docs_version=2, tos_version=1),
            make_developer_headers(registered["id"]),
        )
    )
    assert_fields(
        acknowledged,
        "Developer",
        id=registered["id"],
        onboarding_state="DOCS_ACKNOWLEDGED",
        docs_version_acknowledged=2,
        tos_version_accepted=1,
    )


def test_a_developer_acknowledges_and_applies_on_its_own_row(api, programme):
    """A developer reaches the three operations reserved to it: acknowledging onboarding, drafting an application and submitting it.

    PRD: "Only the developer itself may act."
    PRD: "On success the application moves `DRAFT → SUBMITTED` and `revision_round` increments — reaching 1 on the very first submission."

    Design: Corner/rbac/every_role_reaches_its_own_exclusive_operations
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.register_developer()
    developer_headers = programme.headers_for(developer)

    acknowledged = validate_success(
        api.acknowledge_onboarding(
            developer["id"], f.onboarding_acknowledgement_payload(), developer_headers
        )
    )
    assert_fields(acknowledged, "Developer", onboarding_state="DOCS_ACKNOWLEDGED")

    draft = validate_success(
        api.create_access_application(
            f.access_application_payload(developer["id"], version["id"], requested_tier="PARTNER"),
            developer_headers,
        ),
        expected_status=201,
    )
    assert_fields(draft, "AccessApplication", state="DRAFT", revision_round=0)

    submitted = validate_success(
        api.submit_access_application(draft["id"], {}, developer_headers)
    )
    assert_fields(submitted, "AccessApplication", state="SUBMITTED", revision_round=1)


def test_a_dev_rel_manager_records_ecosystem_outcomes_and_claims_the_review(api, programme):
    """The developer-relations owner reaches both of its own verbs: recording an ecosystem outcome and claiming an application review.

    PRD: "A `DevRelManager` records ecosystem outcomes on a developer by submitting `certification_level` — `NONE`, `ASSOCIATE` or `PROFESSIONAL` — together with `certification_expires_at`, the instant the recorded certification lapses, and optionally `hackathon_awards_delta`, the number of newly recorded hackathon awards."
    PRD: "A `DevRelManager` claims a `SUBMITTED` application, moving it `SUBMITTED → UNDER_REVIEW` and recording the claiming operator's `X-User-ID` as `reviewer_user_id`."

    Design: Corner/rbac/every_role_reaches_its_own_exclusive_operations
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()

    recorded = validate_success(
        api.record_ecosystem_participation(
            developer["id"],
            f.ecosystem_participation_payload(
                certification_level="ASSOCIATE",
                certification_expires_at="2026-12-31T00:00:00Z",
                hackathon_awards_delta=1,
            ),
            DEV_REL_MANAGER,
        )
    )
    assert_fields(
        recorded,
        "Developer",
        certification_level="ASSOCIATE",
        certification_expires_at="2026-12-31T00:00:00Z",
        hackathon_award_count=1,
    )

    application = programme.draft_application(developer, version)
    programme.submit_application(application, developer)

    claimed = validate_success(api.claim_application_review(application["id"], {}, DEV_REL_MANAGER))
    assert_fields(
        claimed,
        "AccessApplication",
        state="UNDER_REVIEW",
        reviewer_user_id=DEV_REL_MANAGER_ID,
    )


def test_a_platform_admin_decides_the_claimed_application(api, programme):
    """The platform operator reaches the decision that no other role may take, and is recorded as the approver.

    PRD: "Only a `PlatformAdmin` decides, and never the operator who reviewed."
    PRD: "On approval the application moves `UNDER_REVIEW → APPROVED`, records `approver_user_id` from `X-User-ID`, stores `approved_tier` and `granted_scopes`, sets `decided_at` from the logical clock, and computes `data_access_limit` — the highest data sensitivity the approved tier may touch, which is `PUBLIC` at `SANDBOX`, `PERSONAL` at `STANDARD`, and `FINANCIAL` at both `PARTNER` and `PRIVILEGED`."

    Design: Corner/rbac/every_role_reaches_its_own_exclusive_operations
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.draft_application(developer, version)
    programme.submit_application(application, developer)
    programme.claim_application(application)

    decided = validate_success(
        api.decide_access_application(
            application["id"],
            f.decide_application_payload(
                decision="APPROVE", approved_tier="PARTNER", granted_scopes=[CANONICAL_SCOPE]
            ),
            PLATFORM_ADMIN,
        )
    )
    assert_fields(
        decided,
        "AccessApplication",
        state="APPROVED",
        approver_user_id=ADMIN_ID,
        approved_tier="PARTNER",
        granted_scopes=[CANONICAL_SCOPE],
        data_access_limit="FINANCIAL",
    )
    assert_instant_equals(decided["decided_at"], "2026-08-01T00:00:00Z", "decided_at")


def test_a_trust_and_safety_officer_opens_a_violation_case(api, programme):
    """The enforcement officer reaches case creation, which records it as the opening operator and prices the allegation.

    PRD: "The case is created in `state` `OPENED` with `points_applied` 0, `appeal_count` 0, `opened_by_user_id` taken from `X-User-ID`, and `investigator_user_id`, `adjudicator_user_id`, `remediation_deadline`, `appeal_deadline`, `outcome`, `appeal_reason` and `decision_note` all null."
    PRD: "Category base points are 10 for `RATE_ABUSE`, 15 for `SCOPE_OVERREACH`, 20 for `DATA_RETENTION` and 25 for `RESALE`. The severity factor is 1 for `LOW`, 2 for `MEDIUM` and 3 for `HIGH`."

    Design: Corner/rbac/every_role_reaches_its_own_exclusive_operations
    """
    developer = programme.register_developer()

    case = validate_success(
        api.create_violation_case(
            f.violation_case_payload(
                developer["id"],
                category="RATE_ABUSE",
                severity="LOW",
                summary="One borderline window flagged by monitoring.",
            ),
            TRUST_OFFICER,
        ),
        expected_status=201,
    )
    assert_fields(
        case,
        "ViolationCase",
        state="OPENED",
        penalty_points=10,
        points_applied=0,
        appeal_count=0,
        opened_by_user_id=TRUST_OFFICER_ID,
    )
    assert_nulls(case, ["investigator_user_id", "adjudicator_user_id", "outcome"], "ViolationCase")


def test_a_partner_support_agent_records_an_incident_and_its_communication(api, programme):
    """The support owner reaches both incident creation and the first incident communication, which moves the case to responding.

    PRD: "A new case starts in `state` `OPEN` with `escalation_tier` 0, `communication_count` 0, `max_communication_gap_minutes` 0, `first_response_breached` false, and `first_response_at`, `last_communication_at`, `resolved_at`, `downtime_minutes`, `credit_uplift_applied` and `resolution_note` null, `affected_assignment_count` 0 and `total_credit_calls` 0."
    PRD: "The first one additionally sets `first_response_at` and moves the case `OPEN → RESPONDING`; subsequent ones leave the case in `RESPONDING` — the self-transition `RESPONDING → RESPONDING` — while re-evaluating the cadence figures."

    Design: Corner/rbac/every_role_reaches_its_own_exclusive_operations
    """
    product = programme.create_product()

    incident = validate_success(
        api.create_support_case(
            f.support_case_payload(
                product["id"],
                kind="PLATFORM_INCIDENT",
                severity="S3",
                title="Elevated catalogue latency",
                started_at="2026-08-01T00:00:00Z",
            ),
            SUPPORT_AGENT,
        ),
        expected_status=201,
    )
    assert_fields(
        incident,
        "SupportCase",
        kind="PLATFORM_INCIDENT",
        state="OPEN",
        escalation_tier=0,
        communication_count=0,
    )

    responding = validate_success(
        api.create_support_communication(
            incident["id"],
            f.communication_payload("2026-08-01T00:00:00Z"),
            SUPPORT_AGENT,
        )
    )
    assert_fields(responding, "SupportCase", state="RESPONDING", communication_count=1)
    assert_instant_equals(
        responding["first_response_at"], "2026-08-01T00:00:00Z", "first_response_at"
    )


# --------------------------------------------------------------------------------------
# The role table, negative half: no role reaches another role's exclusive operation
# --------------------------------------------------------------------------------------
def test_a_dev_rel_manager_may_not_decide_an_application_under_review(api, programme):
    """The reviewing manager replaying the decision request is refused on the role rung, before any state or duties check, and the admin decision then lands once.

    PRD: "When the acting role does not appear in the authorised-roles list for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "Only a `PlatformAdmin` decides, and never the operator who reviewed."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.draft_application(developer, version)
    programme.submit_application(application, developer)
    programme.claim_application(application)

    decision = f.decide_application_payload(
        decision="APPROVE", approved_tier="PARTNER", granted_scopes=[CANONICAL_SCOPE]
    )
    validate_error(
        api.decide_access_application(application["id"], decision, DEV_REL_MANAGER),
        ApiError.UNAUTHORIZED,
    )
    assert_fields(
        programme.read_application(application["id"]), "AccessApplication", state="UNDER_REVIEW"
    )

    decided = validate_success(
        api.decide_access_application(application["id"], decision, PLATFORM_ADMIN)
    )
    assert_fields(decided, "AccessApplication", state="APPROVED", approver_user_id=ADMIN_ID)


def test_a_platform_admin_may_not_triage_a_submitted_feedback_item(api, programme):
    """Triage belongs to the developer-relations owner, so the platform operator is refused even though the item sits in exactly the right state.

    PRD: "When the acting role does not appear in the authorised-roles list for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "**Triage** is a `DevRelManager` action carrying an optional `decision_note`."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation
    """
    product = programme.create_product()
    developer = programme.onboarded_developer()
    item = programme.submit_feedback(
        developer,
        product["id"],
        category="DOC_GAP",
        body="The rate limit headers are undocumented.",
    )
    assert_fields(item, "FeedbackItem", state="SUBMITTED")

    validate_error(
        api.triage_feedback_item(item["id"], f.triage_payload(), PLATFORM_ADMIN),
        ApiError.UNAUTHORIZED,
    )

    untouched = programme.read_feedback(item["id"])
    assert_fields(untouched, "FeedbackItem", state="SUBMITTED")
    assert_nulls(untouched, ["triaged_by_user_id", "triaged_at", "priority_score"], "FeedbackItem")


def test_a_platform_admin_may_not_investigate_an_opened_violation_case(api, programme):
    """Investigation belongs to the enforcement officer alone: the platform operator is refused, and the officer then succeeds on the untouched case.

    PRD: "When the acting role does not appear in the authorised-roles list for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "A `TrustAndSafetyOfficer` may open and investigate a case but may never decide it; a `PlatformAdmin` decides but never investigates."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation
    """
    developer = programme.register_developer()
    case = programme.open_case(developer)

    validate_error(
        api.investigate_violation_case(case["id"], {}, PLATFORM_ADMIN), ApiError.UNAUTHORIZED
    )
    assert_fields(programme.read_case(case["id"]), "ViolationCase", state="OPENED")

    investigated = validate_success(
        api.investigate_violation_case(case["id"], {}, TRUST_OFFICER)
    )
    assert_fields(
        investigated,
        "ViolationCase",
        state="INVESTIGATING",
        investigator_user_id=TRUST_OFFICER_ID,
    )


def test_a_dev_rel_manager_may_not_create_an_api_product(api):
    """The product catalogue is the platform operator's alone, so a manager's create is refused and leaves the catalogue empty.

    PRD: "When the acting role does not appear in the authorised-roles list for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "A `PlatformAdmin` is the platform operator: owns the product catalogue and version lifecycle, provisions and suspends entitlements, decides applications, adjudicates violation cases, revokes access, and drives the logical clock and the programme checkpoint."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation
    """
    validate_error(
        api.create_api_product(f.api_product_payload(), DEV_REL_MANAGER), ApiError.UNAUTHORIZED
    )

    catalogue, meta = validate_paginated(api.list_api_products(PLATFORM_ADMIN))
    assert catalogue == [], f"the refused create still produced a product: {catalogue}"
    assert meta["total_count"] == 0, f"total_count should be 0, got {meta['total_count']}"

    created = validate_success(
        api.create_api_product(f.api_product_payload(), PLATFORM_ADMIN), expected_status=201
    )
    assert_common_fields(created, "ApiProduct")


def test_a_dev_rel_manager_may_not_provision_an_entitlement(api, programme):
    """Provisioning against the product pools is the platform operator's alone: the manager is refused and no entitlement appears, while the same request from the operator succeeds.

    PRD: "When the acting role does not appear in the authorised-roles list for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "A `PlatformAdmin` is the platform operator: owns the product catalogue and version lifecycle, provisions and suspends entitlements, decides applications, adjudicates violation cases, revokes access, and drives the logical clock and the programme checkpoint."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.approved_application(developer, version)
    payload = f.quota_assignment_payload(
        application["id"], programme.product_version_counter(product["id"])
    )

    validate_error(
        api.create_quota_assignment(payload, DEV_REL_MANAGER), ApiError.UNAUTHORIZED
    )

    entitlements, meta = validate_paginated(
        api.list_quota_assignments(PLATFORM_ADMIN, {"access_application_id": application["id"]})
    )
    assert entitlements == [], f"the refused provisioning still created an entitlement: {entitlements}"
    assert meta["total_count"] == 0, f"total_count should be 0, got {meta['total_count']}"

    provisioned = validate_success(
        api.create_quota_assignment(payload, PLATFORM_ADMIN), expected_status=201
    )
    assert_fields(
        provisioned,
        "QuotaAssignment",
        entitlement_state="PROVISIONED",
        access_application_id=application["id"],
    )


def test_a_platform_admin_may_not_resolve_a_support_case(api, programme):
    """Resolution with its service credits belongs to the support agent, so the platform operator is refused on a case that is otherwise ready to resolve.

    PRD: "When the acting role does not appear in the authorised-roles list for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "A `PartnerSupportAgent` owns support cases, escalation channels, incident communications and resolution with service credits."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation
    """
    product = programme.create_product()
    incident = programme.open_incident(
        product["id"], severity="S3", started_at="2026-08-01T00:00:00Z"
    )
    programme.add_communication(incident, "2026-08-01T00:00:00Z")
    programme.set_clock("2026-08-01T02:00:00Z")

    validate_error(
        api.resolve_support_case(incident["id"], f.resolve_support_payload(), PLATFORM_ADMIN),
        ApiError.UNAUTHORIZED,
    )
    assert_fields(programme.read_support_case(incident["id"]), "SupportCase", state="RESPONDING")

    resolved = validate_success(
        api.resolve_support_case(incident["id"], f.resolve_support_payload(), SUPPORT_AGENT)
    )
    assert_fields(resolved, "SupportCase", state="RESOLVED")


def test_a_developer_may_not_read_the_product_roadmap(api, programme):
    """A read can be exclusive too: the roadmap ranking is refused to a developer and served to the developer-relations owner.

    PRD: "When the acting role does not appear in the authorised-roles list for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "The product's roadmap read returns the product's `TRIAGED` and `ROADMAP_ACCEPTED` items ordered by `priority_score` descending, then `raw_impact` descending, then `created_at` ascending, and is available to a `DevRelManager` or a `PlatformAdmin`."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation
    """
    product = programme.create_product()
    developer = programme.register_developer()

    validate_error(
        api.get_product_roadmap(product["id"], programme.headers_for(developer)),
        ApiError.UNAUTHORIZED,
    )

    ranked, meta = validate_paginated(api.get_product_roadmap(product["id"], DEV_REL_MANAGER))
    assert ranked == [], f"a product with no triaged feedback should rank nothing: {ranked}"
    assert meta["total_count"] == 0, f"total_count should be 0, got {meta['total_count']}"


def test_anonymous_may_register_a_developer_but_may_not_list_developers(api):
    """The unauthenticated surface reaches exactly one creation and nothing else: the developer list is refused to it and served to the manager.

    PRD: "Registration is the only creation in this system that an unauthenticated role may perform."
    PRD: "When the acting role does not appear in the authorised-roles list for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation
    """
    registered = validate_success(
        api.register_developer(f.developer_payload(), ANONYMOUS), expected_status=201
    )
    assert_common_fields(registered, "Developer")

    validate_error(api.list_developers(ANONYMOUS), ApiError.UNAUTHORIZED)

    population, meta = validate_paginated(api.list_developers(DEV_REL_MANAGER))
    assert [d["id"] for d in population] == [registered["id"]], (
        f"the manager should see exactly the registered developer, saw {population}"
    )
    assert meta["total_count"] == 1, f"total_count should be 1, got {meta['total_count']}"
