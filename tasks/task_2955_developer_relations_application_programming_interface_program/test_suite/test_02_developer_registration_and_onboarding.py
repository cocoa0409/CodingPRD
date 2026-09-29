"""Registering developers and carrying them through onboarding into the public directory.

This file covers the developer side of the programme: self-registration and its declared
defaults, the single-resource and collection reads over the developer population, the
shape constraints that are refused before anything is stored, the initial states every
lifecycle opens in, the activation bubble that completes onboarding, the trust points
earned by certification and hackathon awards, and the directory listing that only a
production-active certified developer may submit.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_common_fields,
    assert_contains_ids,
    assert_decimal_equals,
    assert_fields,
    assert_instant_equals,
    assert_nulls,
    assert_pool_availability,
    assert_request_id,
    assert_trust_scores,
)
from test_helpers.constants import (
    CANONICAL_SAMPLE_APP_SLUG,
    CANONICAL_SUSTAINED_RPM_POOL,
    CLOCK_DEFAULT,
    DEFAULT_LIMIT,
    TRUST_OFFICER_ID,
)
from test_helpers.test_users import (
    ANONYMOUS,
    DEV_REL_MANAGER,
    PLATFORM_ADMIN,
    SUPPORT_AGENT,
    TRUST_OFFICER,
)

# A partner-tier entitlement for an uncertified onboarded developer draws 3000 rpm scaled by
# the 0.75 multiplier of the 40-59 trust band, so it commits 2250 sustained requests per minute.
UNCERTIFIED_PARTNER_SUSTAINED_RPM = 2250


def sandbox_validated_chain(programme):
    """Everything up to a provisioned entitlement, with the developer at SANDBOX_VALIDATED."""
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.register_developer()
    programme.acknowledge(developer)
    lease = programme.take_lease(developer, product["id"], CLOCK_DEFAULT, lease_days=14)
    programme.validate_lease(lease, developer)
    application = programme.approved_application(developer, version)
    assignment = programme.provision_entitlement(application, product["id"])
    return {
        "product": product,
        "version": version,
        "developer": developer,
        "lease": lease,
        "application": application,
        "assignment": assignment,
    }


# ------------------------------------------------------------------------- registration
def test_registering_a_developer_returns_the_declared_defaults(api, clock_at_default):
    """A bare self-registration comes back with every state dimension, counter and trust score
    at the value the programme declares for a brand-new account.

    PRD: "The new record starts at `onboarding_state` `REGISTERED`, `standing`
    `GOOD_STANDING`, `directory_state` `NOT_LISTED` and `certification_level` `NONE`, with
    `certification_expires_at`, `directory_summary`, `docs_version_acknowledged`,
    `tos_version_accepted` and `revoked_at` all null, with `hackathon_award_count`,
    `clean_window_count`, `throttled_window_count` and `violation_points` all 0, and with both
    `trust_score` and `audited_trust_score` seeded at 50."

    Design: Corner/entities/developer_registration_returns_full_default_shape
    """
    payload = f.developer_payload(
        org_name="Northwind Labs", contact_email="dev1@northwind.example", region_code="EU"
    )

    developer = validate_success(api.register_developer(payload, ANONYMOUS), expected_status=201)

    assert_fields(
        developer,
        "Developer",
        org_name="Northwind Labs",
        contact_email="dev1@northwind.example",
        region_code="EU",
        onboarding_state="REGISTERED",
        standing="GOOD_STANDING",
        directory_state="NOT_LISTED",
        certification_level="NONE",
        hackathon_award_count=0,
        clean_window_count=0,
        throttled_window_count=0,
        violation_points=0,
    )
    assert_nulls(
        developer,
        [
            "certification_expires_at",
            "directory_summary",
            "docs_version_acknowledged",
            "tos_version_accepted",
            "revoked_at",
        ],
        "Developer",
    )
    assert_trust_scores(developer, trust_score=50, audited_trust_score=50)


def test_registration_returns_a_prefix_free_identity_in_the_success_envelope(api, clock_at_default):
    """The creation responds inside the standard object envelope with a request identifier, a
    bare UUID id, revision counter 1, and creation and update instants both reading the
    programme clock.

    PRD: "Every persisted resource exposes an `id`, which is a server-minted UUID string
    carrying no type prefix."

    PRD: "The `api_request_id` is a server-generated unique identifier for the request that
    starts with `req_`."

    Design: Corner/entities/developer_registration_returns_full_default_shape
    """
    response = api.register_developer(f.developer_payload(region_code="EU"), ANONYMOUS)
    developer = validate_success(response, expected_status=201)
    body = response.json()

    assert_request_id(body)
    assert body["response_type"] == "object", (
        f"a single-resource creation must report an object envelope, got {body['response_type']!r}"
    )
    assert_common_fields(developer, "Developer")
    assert developer["version"] == 1, "a freshly created developer is at revision 1"
    assert_instant_equals(developer["created_at"], CLOCK_DEFAULT, "Developer.created_at")
    assert_instant_equals(developer["updated_at"], CLOCK_DEFAULT, "Developer.updated_at")


def test_reading_one_developer_returns_the_stored_record(api, programme, clock_at_default):
    """An operator who never touched the row reads back exactly what registration stored, with
    the revision counter still at 1 because a read is not a mutation.

    PRD: "`updated_at` (string): the ISO 8601 UTC instant, in the same format, at which the
    resource was last modified. Any change to any stored property refreshes it — including
    changes the server makes on its own initiative, such as a derived counter moving or a
    cascade reaching the resource."

    Design: Corner/entities/get_developer_returns_stored_entity
    """
    registered = programme.register_developer(
        org_name="Northwind Labs", contact_email="dev1@northwind.example", region_code="EU"
    )

    stored = validate_success(api.get_developer(registered["id"], TRUST_OFFICER))

    assert_fields(
        stored,
        "Developer",
        id=registered["id"],
        version=1,
        org_name="Northwind Labs",
        region_code="EU",
        standing="GOOD_STANDING",
        onboarding_state="REGISTERED",
    )
    assert_instant_equals(stored["updated_at"], CLOCK_DEFAULT, "Developer.updated_at")


def test_developer_list_pages_over_the_whole_population(api, programme, clock_at_default):
    """The collection read reports the size of the whole matching set rather than of the page,
    and only signals more items while a further page really exists.

    PRD: "`total_count` is the number of items matching the request's filters before pagination
    is applied, and `has_more` is true exactly when items matching the filters remain beyond
    the returned page."

    Design: Corner/entities/developer_list_is_paginated_and_filterable
    """
    first = programme.register_developer(org_name="Northwind Labs", region_code="EU")
    second = programme.register_developer(org_name="Southgate Data", region_code="US")
    third = programme.register_developer(org_name="Eastvale Tools", region_code="APAC")

    page_one, meta_one = validate_paginated(
        api.list_developers(DEV_REL_MANAGER, params={"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2, f"the first page should hold two developers, got {len(page_one)}"
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        api.list_developers(DEV_REL_MANAGER, params={"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1, f"the second page should hold one developer, got {len(page_two)}"
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2

    assert_contains_ids(page_one + page_two, [first["id"], second["id"], third["id"]])


def test_developer_list_filtered_by_onboarding_state_counts_only_the_matches(
    api, programme, clock_at_default
):
    """Filtering the population by onboarding progress narrows the reported total to the
    matching developers alone, under the default page window.

    PRD: "Operators browsing the population can narrow the developer list by `directory_state`
    — which is how the public directory view is assembled — and by `standing` and
    `onboarding_state`, alongside the usual `limit` and `offset`."

    PRD: "`limit` caps the number of items returned; when omitted it defaults to 10, its
    minimum accepted value is 1 and its maximum accepted value is 100."

    Design: Corner/entities/developer_list_is_paginated_and_filterable
    """
    programme.create_product()
    acknowledged = programme.register_developer(org_name="Northwind Labs", region_code="EU")
    programme.acknowledge(acknowledged)
    programme.register_developer(org_name="Southgate Data", region_code="US")
    programme.register_developer(org_name="Eastvale Tools", region_code="APAC")

    matches, meta = validate_paginated(
        api.list_developers(DEV_REL_MANAGER, params={"onboarding_state": "DOCS_ACKNOWLEDGED"})
    )

    assert meta["total_count"] == 1, "the filter must count only the acknowledged developer"
    assert len(matches) == 1
    assert matches[0]["id"] == acknowledged["id"]
    assert meta["limit"] == DEFAULT_LIMIT
    assert meta["offset"] == 0


# ------------------------------------------------- shape constraints refused before a write
def test_out_of_domain_region_code_is_rejected_and_stores_nothing(api, programme, clock_at_default):
    """A residency region outside the three declared values is a malformed body, and the refused
    registration leaves the population exactly as it was.

    PRD: "`region_code`, the data-residency region the account is provisioned in, which must be
    exactly one of `US`, `EU` or `APAC`."

    PRD: "Any violation is `ERR_INVALID_REQUEST`, 400, on every endpoint."

    Design: Corner/entities/enum_and_range_constraints_rejected_before_any_write
    """
    programme.register_developer(org_name="Northwind Labs", region_code="EU")

    resp = api.register_developer(
        f.developer_payload(
            org_name="Polar Systems",
            contact_email="dev9@polar.example",
            region_code="ANTARCTICA",
        ),
        DEV_REL_MANAGER,
    )
    validate_error(resp, ApiError.INVALID_REQUEST)

    _, meta = validate_paginated(api.list_developers(DEV_REL_MANAGER))
    assert meta["total_count"] == 1, "the rejected registration stored a developer"


def test_lease_length_above_thirty_days_is_rejected_and_stores_nothing(
    api, programme, product, clock_at_default
):
    """A lease longer than the declared maximum is refused on shape alone, even though every
    other precondition for the lease is satisfied, and no lease is stored.

    PRD: "A developer provisions a sandbox environment by naming the `developer_id` it is acting
    as, the `api_product_id` whose sandbox it wants, the `starts_at` instant at which occupation
    begins, a `lease_days` length between 1 and 30 whole days inclusive, and a `sample_app_slug`
    naming the sample application to seed into the environment."

    Design: Corner/entities/enum_and_range_constraints_rejected_before_any_write
    """
    developer = programme.register_developer()
    programme.acknowledge(developer)

    resp = api.create_sandbox_lease(
        f.sandbox_lease_payload(
            developer["id"],
            product["id"],
            CLOCK_DEFAULT,
            lease_days=31,
            sample_app_slug=CANONICAL_SAMPLE_APP_SLUG,
        ),
        programme.headers_for(developer),
    )
    validate_error(resp, ApiError.INVALID_REQUEST)

    _, meta = validate_paginated(
        api.list_sandbox_leases(DEV_REL_MANAGER, params={"developer_id": developer["id"]})
    )
    assert meta["total_count"] == 0, "the rejected lease was stored anyway"


def test_pagination_limit_above_one_hundred_is_rejected(api, clock_at_default):
    """A page size beyond the declared maximum is the same malformed-request failure as any bad
    body field, on a list endpoint that would otherwise have returned an empty page.

    PRD: "A `limit` outside the range 1 to 100 inclusive, or a negative `offset`, is a malformed
    request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/enum_and_range_constraints_rejected_before_any_write
    """
    resp = api.list_sandbox_leases(DEV_REL_MANAGER, params={"limit": 101})
    validate_error(resp, ApiError.INVALID_REQUEST)


# ------------------------------------------------------- the declared initial states
def test_a_new_version_opens_in_preview_with_an_empty_deprecation_timeline(
    api, product, clock_at_default
):
    """A version is born in preview with nothing on its deprecation timeline yet.

    PRD: "A newly created version enters `lifecycle_state` `PREVIEW` with `migration_guide_url`,
    `migration_guide_published_at`, `deprecation_announced_at`, `sunset_at`,
    `required_notice_days`, `notice_days_at_announcement` and `sunset_completed_at` all null."

    Design: Corner/state_machines/initial_states_are_declared_across_all_lifecycles
    """
    version = validate_success(
        api.create_api_version(
            product["id"],
            f.api_version_payload(semver="1.0.0", breaking_change=False),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert_fields(
        version, "ApiVersion", lifecycle_state="PREVIEW", api_product_id=product["id"]
    )
    assert_nulls(
        version,
        [
            "migration_guide_url",
            "migration_guide_published_at",
            "deprecation_announced_at",
            "sunset_at",
            "required_notice_days",
            "notice_days_at_announcement",
            "sunset_completed_at",
        ],
        "ApiVersion",
    )


def test_a_new_sandbox_lease_opens_active_with_a_derived_expiry(
    api, programme, product, clock_at_default
):
    """A lease is born active, and its expiry is derived from the requested start advanced by
    the requested number of whole days.

    PRD: "The server derives `expires_at` as `starts_at` advanced by `lease_days` whole days,
    and the lease occupies the half-open interval that includes `starts_at` and excludes
    `expires_at`. A lease begins in `state` `ACTIVE` with `released_at` and `closed_reason`
    null."

    Design: Corner/state_machines/initial_states_are_declared_across_all_lifecycles
    """
    developer = programme.register_developer()
    programme.acknowledge(developer)

    lease = validate_success(
        api.create_sandbox_lease(
            f.sandbox_lease_payload(
                developer["id"], product["id"], CLOCK_DEFAULT, lease_days=3,
                sample_app_slug=CANONICAL_SAMPLE_APP_SLUG,
            ),
            programme.headers_for(developer),
        ),
        expected_status=201,
    )

    assert_fields(
        lease,
        "SandboxLease",
        state="ACTIVE",
        developer_id=developer["id"],
        api_product_id=product["id"],
        starts_at=CLOCK_DEFAULT,
        expires_at="2026-08-04T00:00:00Z",
    )
    assert_nulls(lease, ["released_at", "closed_reason"], "SandboxLease")


def test_a_new_violation_case_opens_with_its_penalty_points_computed(
    api, programme, clock_at_default
):
    """A case is born in the opened state with its prospective penalty already computed from
    category and severity, nothing applied to the developer yet, and the opening officer
    recorded.

    PRD: "The case is created in `state` `OPENED` with `points_applied` 0, `appeal_count` 0,
    `opened_by_user_id` taken from `X-User-ID`, and `investigator_user_id`,
    `adjudicator_user_id`, `remediation_deadline`, `appeal_deadline`, `outcome`, `appeal_reason`
    and `decision_note` all null."

    PRD: "Category base points are 10 for `RATE_ABUSE`, 15 for `SCOPE_OVERREACH`, 20 for
    `DATA_RETENTION` and 25 for `RESALE`. The severity factor is 1 for `LOW`, 2 for `MEDIUM` and
    3 for `HIGH`."

    Design: Corner/state_machines/initial_states_are_declared_across_all_lifecycles
    """
    developer = programme.register_developer()

    case = validate_success(
        api.create_violation_case(
            f.violation_case_payload(
                developer["id"],
                category="RATE_ABUSE",
                severity="MEDIUM",
                summary="Sustained request rate above the provisioned ceiling for three hours.",
            ),
            TRUST_OFFICER,
        ),
        expected_status=201,
    )

    assert_fields(
        case,
        "ViolationCase",
        state="OPENED",
        developer_id=developer["id"],
        penalty_points=20,
        points_applied=0,
        appeal_count=0,
        opened_by_user_id=TRUST_OFFICER_ID,
    )
    assert_nulls(
        case,
        [
            "investigator_user_id",
            "adjudicator_user_id",
            "remediation_deadline",
            "appeal_deadline",
            "outcome",
            "appeal_reason",
            "decision_note",
        ],
        "ViolationCase",
    )


def test_a_new_support_case_opens_with_its_first_response_commitment_fixed(
    api, product, clock_at_default
):
    """A platform incident is born open, un-escalated, with no communications, and with the
    first-response commitment its kind and severity pair demands.

    PRD: "A new case starts in `state` `OPEN` with `escalation_tier` 0, `communication_count` 0,
    `max_communication_gap_minutes` 0, `first_response_breached` false, and `first_response_at`,
    `last_communication_at`, `resolved_at`, `downtime_minutes`, `credit_uplift_applied` and
    `resolution_note` null, `affected_assignment_count` 0 and `total_credit_calls` 0."

    PRD: "For a `PLATFORM_INCIDENT` the platform holds itself to a tighter standard: **15
    minutes** at `S1`, **30 minutes** at `S2`, **120 minutes** at `S3` and **240 minutes** at
    `S4`."

    Design: Corner/state_machines/initial_states_are_declared_across_all_lifecycles
    """
    case = validate_success(
        api.create_support_case(
            f.support_case_payload(
                product["id"],
                kind="PLATFORM_INCIDENT",
                severity="S3",
                title="Elevated catalogue read latency",
                started_at=CLOCK_DEFAULT,
            ),
            SUPPORT_AGENT,
        ),
        expected_status=201,
    )

    assert_fields(
        case,
        "SupportCase",
        state="OPEN",
        kind="PLATFORM_INCIDENT",
        severity="S3",
        escalation_tier=0,
        communication_count=0,
        max_communication_gap_minutes=0,
        first_response_breached=False,
        first_response_due_minutes=120,
        affected_assignment_count=0,
        total_credit_calls=0,
    )
    assert_nulls(
        case,
        [
            "first_response_at",
            "last_communication_at",
            "resolved_at",
            "downtime_minutes",
            "credit_uplift_applied",
            "resolution_note",
        ],
        "SupportCase",
    )


def test_a_new_feedback_item_opens_unscored_and_outside_the_demand_index(
    api, programme, product, clock_at_default
):
    """A feedback item is born submitted with none of its scoring fields resolved, and an
    untriaged item contributes nothing to its product's demand index.

    PRD: "The item starts in `state` `SUBMITTED` with `author_top_tier`, `raw_impact`,
    `priority_score`, `triaged_by_user_id`, `decision_note` and `triaged_at` all null."

    PRD: "Items in `SUBMITTED` are not yet scored and do not count; items in `DECLINED` have
    been removed from the index and do not count."

    Design: Corner/state_machines/initial_states_are_declared_across_all_lifecycles
    """
    developer = programme.register_developer()
    programme.acknowledge(developer)

    item = validate_success(
        api.create_feedback_item(
            f.feedback_item_payload(
                developer["id"],
                product["id"],
                category="DOC_GAP",
                body="Burst credit accounting is undocumented for the partner tier.",
            ),
            programme.headers_for(developer),
        ),
        expected_status=201,
    )

    assert_fields(
        item,
        "FeedbackItem",
        state="SUBMITTED",
        developer_id=developer["id"],
        api_product_id=product["id"],
        category="DOC_GAP",
    )
    assert_nulls(
        item,
        [
            "author_top_tier",
            "raw_impact",
            "priority_score",
            "triaged_by_user_id",
            "decision_note",
            "triaged_at",
        ],
        "FeedbackItem",
    )

    unmoved = validate_success(api.get_api_product(product["id"], PLATFORM_ADMIN))
    assert_decimal_equals(unmoved["demand_index"], 0.00, "ApiProduct.demand_index")


# ------------------------------------------------------- activation completes onboarding
def test_activation_puts_the_entitlement_live_without_touching_the_pools(
    api, programme, clock_at_default
):
    """Activation moves a provisioned entitlement to live and stamps the moment it happened,
    while the capacity it drew at provisioning is neither drawn again nor released.

    PRD: "It moves `PROVISIONED → ACTIVE`, sets `activated_at` from the logical clock, and
    bubbles the developer's `onboarding_state` from `SANDBOX_VALIDATED` to `PRODUCTION_ACTIVE`
    if it was sitting there."

    Design: Corner/state_machines/activation_bubbles_onboarding_to_production_active
    """
    chain = sandbox_validated_chain(programme)
    assert chain["assignment"]["entitlement_state"] == "PROVISIONED"

    activated = validate_success(
        api.activate_quota_assignment(chain["assignment"]["id"], {}, PLATFORM_ADMIN)
    )

    assert_fields(
        activated,
        "QuotaAssignment",
        entitlement_state="ACTIVE",
        throttle_state="NORMAL",
        activated_at=CLOCK_DEFAULT,
        sustained_rpm=UNCERTIFIED_PARTNER_SUSTAINED_RPM,
    )

    product = validate_success(api.get_api_product(chain["product"]["id"], PLATFORM_ADMIN))
    assert_pool_availability(
        product,
        allocated_sustained_rpm=UNCERTIFIED_PARTNER_SUSTAINED_RPM,
        available_sustained_rpm=CANONICAL_SUSTAINED_RPM_POOL - UNCERTIFIED_PARTNER_SUSTAINED_RPM,
    )


def test_activation_bubbles_a_sandbox_validated_developer_to_production_active(
    api, programme, clock_at_default
):
    """The developer's own lifecycle advances as a side effect of its first entitlement going
    live, and the lease that earned sandbox validation is left untouched by the bubble.

    PRD: "When a developer's first entitlement reaches `entitlement_state` `ACTIVE`, the server
    bubbles the developer's `onboarding_state` from `SANDBOX_VALIDATED` up to
    `PRODUCTION_ACTIVE`, which is the state that makes the developer eligible to submit a public
    directory listing."

    Design: Corner/state_machines/activation_bubbles_onboarding_to_production_active
    """
    chain = sandbox_validated_chain(programme)
    before = validate_success(api.get_developer(chain["developer"]["id"], DEV_REL_MANAGER))
    assert before["onboarding_state"] == "SANDBOX_VALIDATED", (
        "sandbox validation should have advanced the developer before activation"
    )

    validate_success(api.activate_quota_assignment(chain["assignment"]["id"], {}, PLATFORM_ADMIN))

    after = validate_success(api.get_developer(chain["developer"]["id"], DEV_REL_MANAGER))
    assert_fields(
        after, "Developer", onboarding_state="PRODUCTION_ACTIVE", standing="GOOD_STANDING"
    )
    lease = validate_success(api.get_sandbox_lease(chain["lease"]["id"], PLATFORM_ADMIN))
    assert_fields(lease, "SandboxLease", state="ACTIVE")
    assert_nulls(lease, ["released_at", "closed_reason"], "SandboxLease")


def test_activating_an_already_live_entitlement_is_refused(api, programme, clock_at_default):
    """Activation is only available from the provisioned state, so repeating it is refused and
    the onboarding progress it already produced is left where it is.

    PRD: "Activation by a `PlatformAdmin` requires `entitlement_state` `PROVISIONED` — otherwise
    `ERR_ASSIGNMENT_STATE_INVALID` (HTTP 409) — requires the developer at `GOOD_STANDING`, and
    requires the pinned version's `lifecycle_state` not to be `SUNSET`."

    Design: Corner/state_machines/activation_bubbles_onboarding_to_production_active
    """
    chain = sandbox_validated_chain(programme)
    validate_success(api.activate_quota_assignment(chain["assignment"]["id"], {}, PLATFORM_ADMIN))

    resp = api.activate_quota_assignment(chain["assignment"]["id"], {}, PLATFORM_ADMIN)
    validate_error(resp, ApiError.ASSIGNMENT_STATE_INVALID)

    assignment = validate_success(
        api.get_quota_assignment(chain["assignment"]["id"], PLATFORM_ADMIN)
    )
    assert assignment["entitlement_state"] == "ACTIVE"
    developer = validate_success(api.get_developer(chain["developer"]["id"], DEV_REL_MANAGER))
    assert developer["onboarding_state"] == "PRODUCTION_ACTIVE", (
        "the refused second activation rolled back the onboarding bubble"
    )


# -------------------------------------------------- certification and hackathon trust points
ASSOCIATE_EXPIRY = "2026-08-10T00:00:00Z"
LONG_LIVED_EXPIRY = "2027-08-01T00:00:00Z"


def test_an_unexpired_associate_certification_earns_its_eight_points(
    api, programme, clock_at_default
):
    """A docs-acknowledged developer holding a live associate certification scores base plus
    documentation plus certification, and the checkpoint's audit agrees with the snapshot while
    the expiry is still ahead of the clock.

    PRD: "The shared components are: a base of **50 points**; a certification component worth 0
    points at `certification_level` `NONE`, **8 points** at `ASSOCIATE` and **15 points** at
    `PROFESSIONAL`, which counts for nothing at all when `certification_expires_at` is null or
    strictly earlier than the logical clock; a documentation component worth **6 points** when
    `docs_version_acknowledged` is at least the current documentation revision of 2 and 0 points
    otherwise; a hackathon component worth **4 points** for each recorded award, counting at most
    **3 awards** — so `hackathon_award_count` values above 3 contribute the same 12 points as
    exactly 3; and a clean-traffic component worth **1 point** for each clean usage window,
    counting at most **10 windows**, taken from `clean_window_count`."

    PRD: "Developers whose `certification_expires_at` has passed are noted in
    `expired_certification_developer_ids`."

    Design: Corner/calculations/expired_certification_stops_earning_its_points
    """
    programme.create_product()
    developer = programme.register_developer()
    programme.acknowledge(developer)
    programme.record_participation(
        developer, certification_level="ASSOCIATE", certification_expires_at=ASSOCIATE_EXPIRY
    )

    scored = validate_success(api.get_developer(developer["id"], DEV_REL_MANAGER))
    assert_trust_scores(scored, trust_score=64)

    checkpoint = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN))
    assert checkpoint["expired_certification_developer_ids"] == [], (
        "a certification expiring on 2026-08-10 has not lapsed at 2026-08-01"
    )
    assert developer["id"] in checkpoint["rescored_developer_ids"]

    audited = validate_success(api.get_developer(developer["id"], DEV_REL_MANAGER))
    assert_trust_scores(audited, trust_score=64, audited_trust_score=64)


def test_a_lapsed_certification_is_withdrawn_from_the_audited_score_only(
    api, programme, clock_at_default
):
    """Once the clock passes the expiry, the certification stops earning its points in the
    audited score while the snapshot score keeps the figure it was last computed at, and nothing
    rewrites the recorded level or expiry.

    PRD: "A developer whose `certification_expires_at` has fallen behind the clock **keeps** its
    recorded `certification_level`; what it loses is the certification's contribution to trust
    scoring, which the trust calculation voids whenever the expiry is null or strictly earlier
    than the clock."

    PRD: "**Audited rescoring.** Every developer's `audited_trust_score` is recomputed under the
    enforcement-audit variant, which is the only way that field ever changes."

    Design: Corner/calculations/expired_certification_stops_earning_its_points
    """
    programme.create_product()
    developer = programme.register_developer()
    programme.acknowledge(developer)
    programme.record_participation(
        developer, certification_level="ASSOCIATE", certification_expires_at=ASSOCIATE_EXPIRY
    )
    programme.run_checkpoint()
    programme.set_clock("2026-08-11T00:00:00Z")

    checkpoint = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN))

    assert checkpoint["expired_certification_developer_ids"] == [developer["id"]]
    assert developer["id"] in checkpoint["rescored_developer_ids"]

    lapsed = validate_success(api.get_developer(developer["id"], DEV_REL_MANAGER))
    assert_trust_scores(lapsed, trust_score=64, audited_trust_score=56)
    assert_fields(lapsed, "Developer", certification_level="ASSOCIATE")
    assert_instant_equals(
        lapsed["certification_expires_at"], ASSOCIATE_EXPIRY, "Developer.certification_expires_at"
    )


def test_hackathon_trust_points_saturate_at_three_awards(api, programme, clock_at_default):
    """Recording five awards in one go grows the ledger to five while the trust contribution
    stops at the three-award cap of twelve points.

    PRD: "a hackathon component worth **4 points** for each recorded award, counting at most
    **3 awards** — so `hackathon_award_count` values above 3 contribute the same 12 points as
    exactly 3"

    PRD: "The recorded level and expiry replace the stored `certification_level` and
    `certification_expires_at`; the delta is added to `hackathon_award_count`, which is left
    unchanged when the field is omitted."

    Design: Corner/calculations/hackathon_awards_stop_counting_after_three
    """
    programme.create_product()
    developer = programme.register_developer()
    programme.acknowledge(developer)
    programme.record_participation(
        developer, certification_level="ASSOCIATE", certification_expires_at=LONG_LIVED_EXPIRY
    )
    certified = validate_success(api.get_developer(developer["id"], DEV_REL_MANAGER))
    assert_fields(certified, "Developer", hackathon_award_count=0)
    assert_trust_scores(certified, trust_score=64)

    awarded = validate_success(
        api.record_ecosystem_participation(
            developer["id"],
            f.ecosystem_participation_payload(
                certification_level="ASSOCIATE",
                certification_expires_at=LONG_LIVED_EXPIRY,
                hackathon_awards_delta=5,
            ),
            DEV_REL_MANAGER,
        )
    )

    assert_fields(awarded, "Developer", hackathon_award_count=5)
    assert_trust_scores(awarded, trust_score=76)


def test_further_hackathon_awards_grow_the_ledger_without_moving_trust(
    api, programme, clock_at_default
):
    """The award ledger is programme data and keeps growing past the cap, but the weighted term
    it feeds has already saturated, so the trust score does not move.

    PRD: "a hackathon component worth **4 points** for each recorded award, counting at most
    **3 awards** — so `hackathon_award_count` values above 3 contribute the same 12 points as
    exactly 3"

    Design: Corner/calculations/hackathon_awards_stop_counting_after_three
    """
    programme.create_product()
    developer = programme.register_developer()
    programme.acknowledge(developer)
    programme.record_participation(
        developer,
        certification_level="ASSOCIATE",
        certification_expires_at=LONG_LIVED_EXPIRY,
        hackathon_awards_delta=5,
    )

    topped_up = validate_success(
        api.record_ecosystem_participation(
            developer["id"],
            f.ecosystem_participation_payload(
                certification_level="ASSOCIATE",
                certification_expires_at=LONG_LIVED_EXPIRY,
                hackathon_awards_delta=2,
            ),
            DEV_REL_MANAGER,
        )
    )

    assert_fields(topped_up, "Developer", hackathon_award_count=7)
    assert_trust_scores(topped_up, trust_score=76)


# ------------------------------------------------------------ the public directory gate
DIRECTORY_SUMMARY = "Settlement reconciliation for regulated trading venues."
DIRECTORY_CERT_EXPIRY = "2026-12-31T00:00:00Z"


def _production_active_developer(programme):
    """A developer carried all the way to PRODUCTION_ACTIVE, holding no certification."""
    chain = sandbox_validated_chain(programme)
    programme.activate_entitlement(chain["assignment"])
    return chain["developer"]


def test_directory_submission_is_refused_without_a_certification(api, programme, clock_at_default):
    """Reaching production is not enough on its own: an uncertified developer's listing is
    refused and its directory dimension stays where it started.

    PRD: "Three prerequisites are checked together: `onboarding_state` must be
    `PRODUCTION_ACTIVE`, `standing` must be `GOOD_STANDING`, and `certification_level` must be
    something other than `NONE` and unexpired. A submission failing any of them is refused with
    `ERR_DIRECTORY_PREREQUISITES_UNMET` (HTTP 422)."

    Design: Corner/endpoints/directory_submission_is_allowed_only_when_both_prerequisites_hold
    """
    developer = _production_active_developer(programme)
    live = validate_success(api.get_developer(developer["id"], DEV_REL_MANAGER))
    assert_fields(
        live, "Developer", onboarding_state="PRODUCTION_ACTIVE", certification_level="NONE"
    )

    resp = api.submit_directory_listing(
        developer["id"],
        f.directory_submission_payload(directory_summary=DIRECTORY_SUMMARY),
        programme.headers_for(developer),
    )
    validate_error(resp, ApiError.DIRECTORY_PREREQUISITES_UNMET)

    after = validate_success(api.get_developer(developer["id"], DEV_REL_MANAGER))
    assert_fields(after, "Developer", directory_state="NOT_LISTED")
    assert after["directory_summary"] is None, "the refused submission stored a blurb"


def test_directory_submission_is_refused_without_production_onboarding(
    api, programme, clock_at_default
):
    """A live certification is equally insufficient on its own: a developer that never reached
    production is refused with the same complaint.

    PRD: "Three prerequisites are checked together: `onboarding_state` must be
    `PRODUCTION_ACTIVE`, `standing` must be `GOOD_STANDING`, and `certification_level` must be
    something other than `NONE` and unexpired. A submission failing any of them is refused with
    `ERR_DIRECTORY_PREREQUISITES_UNMET` (HTTP 422)."

    Design: Corner/endpoints/directory_submission_is_allowed_only_when_both_prerequisites_hold
    """
    programme.create_product()
    developer = programme.register_developer(org_name="Certified Only", region_code="US")
    programme.acknowledge(developer)
    programme.record_participation(
        developer,
        certification_level="ASSOCIATE",
        certification_expires_at=DIRECTORY_CERT_EXPIRY,
    )
    certified = validate_success(api.get_developer(developer["id"], DEV_REL_MANAGER))
    assert_fields(
        certified,
        "Developer",
        onboarding_state="DOCS_ACKNOWLEDGED",
        certification_level="ASSOCIATE",
    )

    resp = api.submit_directory_listing(
        developer["id"],
        f.directory_submission_payload(directory_summary="Certified integration studio work."),
        programme.headers_for(developer),
    )
    validate_error(resp, ApiError.DIRECTORY_PREREQUISITES_UNMET)

    after = validate_success(api.get_developer(developer["id"], DEV_REL_MANAGER))
    assert_fields(after, "Developer", directory_state="NOT_LISTED")


def test_certifying_a_production_developer_admits_its_listing_to_review(
    api, programme, clock_at_default
):
    """Recording the missing certification both lifts the developer's trust score and satisfies
    the last prerequisite, so the retried submission is admitted to review with its blurb stored.

    PRD: "On success `directory_state` moves `NOT_LISTED → PENDING_REVIEW` on a first
    submission, or `DELISTED → PENDING_REVIEW` on a resubmission after standing has recovered;
    both transitions record the supplied `directory_summary`, and the two are governed by exactly
    the same prerequisites."

    PRD: "Every ecosystem update then recomputes the developer's `trust_score` under the
    onboarding-snapshot variant, so a fresh certification or a new hackathon award can
    immediately raise the trust multiplier the next entitlement provisioning will read."

    Design: Corner/endpoints/directory_submission_is_allowed_only_when_both_prerequisites_hold
    """
    developer = _production_active_developer(programme)
    uncertified = validate_success(api.get_developer(developer["id"], DEV_REL_MANAGER))
    assert_trust_scores(uncertified, trust_score=56)

    certified = validate_success(
        api.record_ecosystem_participation(
            developer["id"],
            f.ecosystem_participation_payload(
                certification_level="ASSOCIATE",
                certification_expires_at=DIRECTORY_CERT_EXPIRY,
            ),
            DEV_REL_MANAGER,
        )
    )
    assert_trust_scores(certified, trust_score=64)

    submitted = validate_success(
        api.submit_directory_listing(
            developer["id"],
            f.directory_submission_payload(directory_summary=DIRECTORY_SUMMARY),
            programme.headers_for(developer),
        )
    )
    assert_fields(
        submitted,
        "Developer",
        directory_state="PENDING_REVIEW",
        directory_summary=DIRECTORY_SUMMARY,
        onboarding_state="PRODUCTION_ACTIVE",
    )


def test_approving_a_pending_listing_publishes_it(api, programme, clock_at_default):
    """The developer-relations owner's approval is what actually publishes the listing.

    PRD: "Approval additionally requires the developer to still be in `GOOD_STANDING` at review
    time, and moves `PENDING_REVIEW → LISTED`."

    Design: Corner/endpoints/directory_submission_is_allowed_only_when_both_prerequisites_hold
    """
    developer = _production_active_developer(programme)
    programme.record_participation(
        developer,
        certification_level="ASSOCIATE",
        certification_expires_at=DIRECTORY_CERT_EXPIRY,
    )
    programme.submit_directory(developer, directory_summary=DIRECTORY_SUMMARY)

    reviewed = validate_success(
        api.review_directory_listing(
            developer["id"],
            f.directory_review_payload(decision="APPROVE", review_note="Listing copy checked."),
            DEV_REL_MANAGER,
        )
    )

    assert_fields(
        reviewed,
        "Developer",
        directory_state="LISTED",
        directory_summary=DIRECTORY_SUMMARY,
        standing="GOOD_STANDING",
    )
