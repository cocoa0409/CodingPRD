"""Publishing API products and driving their version lifecycle.

This file covers the catalogue side of the programme: declaring an API product with its
scope catalogue and its two finite capacity pools, resizing those pools through the
programme-adjustment action that is the product's only update path, and walking a version
from `PREVIEW` through promotion to a gated deprecation announcement with its migration
guide and computed notice period.
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
    assert_decimal_equals,
    assert_fields,
    assert_instant_equals,
    assert_nulls,
    assert_pool_availability,
)
from test_helpers.constants import (
    CANONICAL_MONTHLY_CALL_POOL,
    CANONICAL_REQUESTED_MONTHLY_CALLS,
    CANONICAL_SUSTAINED_RPM_POOL,
    UNKNOWN_ID,
)
from test_helpers.test_users import PLATFORM_ADMIN


# --------------------------------------------------------------- publishing a product
def test_creating_a_product_without_a_monthly_call_pool_is_rejected(api, clock_at_default):
    """Omitting `monthly_call_pool`, which has no declared default, is a malformed body and
    persists no product at all.

    PRD: "A `PlatformAdmin` publishes an **API product** by declaring its `name` (1 to 120
    characters), its `data_sensitivity` — the highest data class it exposes, one of `PUBLIC`,
    `PERSONAL` or `FINANCIAL` — its `scope_catalog`, its `sample_app_slugs`, and the two finite
    pools `sustained_rpm_pool` and `monthly_call_pool`, each at least 1."

    PRD: "The body parses, every required field is present, and every field satisfies its
    declared type, enum domain and length or range constraint; pagination `limit` lies between
    1 and 100 inclusive and `offset` is at least 0. Any violation is `ERR_INVALID_REQUEST`,
    400, on every endpoint."

    Design: Corner/entities/create_api_product_without_monthly_call_pool_rejected
    """
    payload = f.api_product_payload()
    payload.pop("monthly_call_pool")

    resp = api.create_api_product(payload, PLATFORM_ADMIN)
    validate_error(resp, ApiError.INVALID_REQUEST)

    catalogue, meta = validate_paginated(api.list_api_products(PLATFORM_ADMIN))
    assert meta["total_count"] == 0, "the rejected creation persisted a product"
    assert catalogue == []


def test_product_required_tos_version_defaults_to_one(api, clock_at_default):
    """The one optional input defaults to 1, both allocated counters open at 0 so availability
    equals the declared pools, and the demand index opens at the two-decimal 0.00.

    PRD: "An optional `required_tos_version` of at least 1 defaults to 1 when omitted. At
    creation both allocated counters sit at 0, so `available_sustained_rpm` and
    `available_monthly_calls` equal the declared pools, and `demand_index` starts at 0.00."

    Design: Corner/entities/api_product_required_tos_version_defaults_to_one
    """
    # The builder omits `required_tos_version` entirely unless a test supplies one.
    payload = f.api_product_payload()
    assert "required_tos_version" not in payload

    product = validate_success(api.create_api_product(payload, PLATFORM_ADMIN), expected_status=201)

    assert_common_fields(product, "ApiProduct")
    assert_fields(
        product,
        "ApiProduct",
        required_tos_version=1,
        version=1,
        sustained_rpm_pool=CANONICAL_SUSTAINED_RPM_POOL,
        monthly_call_pool=CANONICAL_MONTHLY_CALL_POOL,
        allocated_sustained_rpm=0,
        available_sustained_rpm=CANONICAL_SUSTAINED_RPM_POOL,
        allocated_monthly_calls=0,
        available_monthly_calls=CANONICAL_MONTHLY_CALL_POOL,
    )
    assert_decimal_equals(product["demand_index"], 0.00, "ApiProduct.demand_index")


def test_creating_a_version_under_an_unknown_product_is_not_found(api, product):
    """A version is addressed through its parent product's path segment, so an unminted parent
    identifier is refused before the well-formed body buys anything, and no orphan version
    appears under the product that does exist.

    PRD: "Every identifier appearing in the URL path resolves to an existing resource, checked
    strictly left to right, yielding whichever of `ERR_DEVELOPER_NOT_FOUND`,
    `ERR_API_PRODUCT_NOT_FOUND`, `ERR_API_VERSION_NOT_FOUND`,
    `ERR_ACCESS_APPLICATION_NOT_FOUND`, `ERR_QUOTA_ASSIGNMENT_NOT_FOUND`,
    `ERR_UPGRADE_REQUEST_NOT_FOUND`, `ERR_SANDBOX_LEASE_NOT_FOUND`,
    `ERR_VIOLATION_CASE_NOT_FOUND`, `ERR_SUPPORT_CASE_NOT_FOUND` or
    `ERR_FEEDBACK_ITEM_NOT_FOUND` matches the first unresolvable segment — all HTTP 404."

    Design: Corner/entities/version_creation_under_unknown_product_returns_not_found
    """
    resp = api.create_api_version(
        UNKNOWN_ID, f.api_version_payload(semver="1.0.0", breaking_change=False), PLATFORM_ADMIN
    )
    validate_error(resp, ApiError.API_PRODUCT_NOT_FOUND)

    versions, meta = validate_paginated(api.list_api_versions(product["id"], PLATFORM_ADMIN))
    assert meta["total_count"] == 0, "the refused creation attached a version to the real product"
    assert versions == []


# ------------------------------------------------------------- the version lifecycle
def test_promotion_moves_a_preview_version_to_general_availability(api, programme, product):
    """The one transition out of `PREVIEW` flips the lifecycle state and makes the version
    grantable, while leaving every deprecation-timeline field untouched at null.

    PRD: "Promotion moves a version `PREVIEW → GENERAL_AVAILABILITY`, which is what makes it
    grantable to the `STANDARD`, `PARTNER` and `PRIVILEGED` tiers; attempting to promote a
    version that is not in `PREVIEW` yields `ERR_VERSION_STATE_INVALID`."

    Design: Corner/state_machines/promote_preview_version_to_general_availability
    """
    version = programme.create_version(product["id"], semver="1.0.0", breaking_change=False)
    assert version["lifecycle_state"] == "PREVIEW"

    promoted = validate_success(api.promote_api_version(version["id"], {}, PLATFORM_ADMIN))

    assert_fields(
        promoted,
        "ApiVersion",
        id=version["id"],
        lifecycle_state="GENERAL_AVAILABILITY",
        api_product_id=product["id"],
    )
    assert_nulls(
        promoted,
        [
            "deprecation_announced_at",
            "sunset_at",
            "required_notice_days",
            "notice_days_at_announcement",
            "sunset_completed_at",
        ],
        "ApiVersion",
    )

    listed, meta = validate_paginated(
        api.list_api_versions(
            product["id"], PLATFORM_ADMIN, params={"lifecycle_state": "GENERAL_AVAILABILITY"}
        )
    )
    assert meta["total_count"] == 1, "the promoted version is not visible under the GA filter"
    assert listed[0]["id"] == version["id"]


def test_promotion_bumps_only_the_version_row_not_the_product(api, programme, product):
    """Promotion allocates nothing out of the pools, so it advances the version's own revision
    counter while the parent product's optimistic-concurrency counter stands still.

    PRD: "`version` (integer): a monotonically increasing revision counter that increments by
    one on every mutation of the resource, whether that mutation was requested directly by a
    client or applied by a cascade."

    Design: Corner/state_machines/promote_preview_version_to_general_availability
    """
    version = programme.create_version(product["id"], semver="1.0.0", breaking_change=False)
    product_version_before = programme.product_version_counter(product["id"])

    promoted = validate_success(api.promote_api_version(version["id"], {}, PLATFORM_ADMIN))

    assert promoted["version"] == version["version"] + 1, (
        "promotion did not bump the version row's own revision counter"
    )
    after = validate_success(api.get_api_product(product["id"], PLATFORM_ADMIN))
    assert after["version"] == product_version_before, (
        "promotion moved the product's optimistic-concurrency counter"
    )
    assert_pool_availability(
        after,
        available_sustained_rpm=CANONICAL_SUSTAINED_RPM_POOL,
        available_monthly_calls=CANONICAL_MONTHLY_CALL_POOL,
        allocated_sustained_rpm=0,
        allocated_monthly_calls=0,
    )


def test_announcing_deprecation_from_preview_is_refused(api, programme, product):
    """A deprecation announcement is legal only from general availability, so a version still
    sitting in preview is refused and keeps an empty deprecation timeline.

    PRD: "The version must be in `GENERAL_AVAILABILITY`, or the announcement fails with
    `ERR_VERSION_STATE_INVALID`."

    Design: Corner/state_machines/promote_and_announce_from_wrong_lifecycle_state
    """
    version = programme.create_version(product["id"], semver="1.0.0", breaking_change=False)

    resp = api.announce_deprecation(
        version["id"], f.announce_deprecation_payload(30), PLATFORM_ADMIN
    )
    validate_error(resp, ApiError.VERSION_STATE_INVALID)

    unchanged = validate_success(api.get_api_version(version["id"], PLATFORM_ADMIN))
    assert_fields(unchanged, "ApiVersion", lifecycle_state="PREVIEW", version=version["version"])
    assert_nulls(
        unchanged, ["deprecation_announced_at", "sunset_at", "required_notice_days"], "ApiVersion"
    )


def test_promoting_an_already_available_version_is_refused(api, programme, product):
    """General availability has no promotion edge of its own, so a second promotion of the same
    version is refused and the revision counter shows exactly one accepted write.

    PRD: "Promotion moves a version `PREVIEW → GENERAL_AVAILABILITY`, which is what makes it
    grantable to the `STANDARD`, `PARTNER` and `PRIVILEGED` tiers; attempting to promote a
    version that is not in `PREVIEW` yields `ERR_VERSION_STATE_INVALID`."

    Design: Corner/state_machines/promote_and_announce_from_wrong_lifecycle_state
    """
    version = programme.create_version(product["id"], semver="1.0.0", breaking_change=False)

    promoted = validate_success(api.promote_api_version(version["id"], {}, PLATFORM_ADMIN))
    assert promoted["lifecycle_state"] == "GENERAL_AVAILABILITY"

    resp = api.promote_api_version(version["id"], {}, PLATFORM_ADMIN)
    validate_error(resp, ApiError.VERSION_STATE_INVALID)

    after = validate_success(api.get_api_version(version["id"], PLATFORM_ADMIN))
    assert_fields(
        after,
        "ApiVersion",
        lifecycle_state="GENERAL_AVAILABILITY",
        version=version["version"] + 1,
    )


# ----------------------------------------------- the migration guide as a deprecation gate
GUIDE_URL = "https://docs.example.com/catalog/migrate-1-to-2"


def test_non_breaking_deprecation_needs_no_migration_guide(
    api, programme, clock_at_default, product
):
    """A non-breaking version of a public product deprecates on thirty days' notice with no
    guide published at all, sunsetting thirty whole days after the announcement instant.

    PRD: "Start from the baseline for the product's `data_sensitivity`: **30 days** for
    `PUBLIC`, **60 days** for `PERSONAL`, **90 days** for `FINANCIAL`."

    PRD: "On success the version records `deprecation_announced_at` from the logical clock, sets
    `sunset_at` to that instant advanced by the submitted `notice_days` whole days, records
    `notice_days_at_announcement` as the floor of the whole days between the logical clock and
    `sunset_at` at announcement time, and moves `GENERAL_AVAILABILITY → DEPRECATION_ANNOUNCED`."

    Design: Corner/validations/migration_guide_is_required_only_for_breaking_versions
    """
    version = programme.grantable_version(product["id"], semver="1.0.0", breaking_change=False)
    assert version["migration_guide_url"] is None

    announced = validate_success(
        api.announce_deprecation(version["id"], f.announce_deprecation_payload(30), PLATFORM_ADMIN)
    )

    assert_fields(
        announced,
        "ApiVersion",
        lifecycle_state="DEPRECATION_ANNOUNCED",
        required_notice_days=30,
        notice_days_at_announcement=30,
        deprecation_announced_at="2026-08-01T00:00:00Z",
        sunset_at="2026-08-31T00:00:00Z",
    )
    assert announced["migration_guide_url"] is None, (
        "a non-breaking deprecation invented a migration guide"
    )


def test_breaking_deprecation_without_a_published_guide_is_refused(
    api, programme, clock_at_default, product
):
    """The breaking version of the same product cannot be deprecated while its migration path
    is unpublished, and the refusal leaves it in general availability.

    PRD: "A version whose `breaking_change` is true must already have a published
    `migration_guide_url` before its deprecation may be announced, otherwise
    `ERR_MIGRATION_GUIDE_MISSING` (HTTP 422) — a breaking change with no migration path is not
    a notice, it is an outage."

    Design: Corner/validations/migration_guide_is_required_only_for_breaking_versions
    """
    breaking = programme.grantable_version(product["id"], semver="2.0.0", breaking_change=True)
    assert breaking["migration_guide_url"] is None

    resp = api.announce_deprecation(
        breaking["id"], f.announce_deprecation_payload(60), PLATFORM_ADMIN
    )
    validate_error(resp, ApiError.MIGRATION_GUIDE_MISSING)

    unchanged = validate_success(api.get_api_version(breaking["id"], PLATFORM_ADMIN))
    assert unchanged["lifecycle_state"] == "GENERAL_AVAILABILITY"
    assert_nulls(unchanged, ["deprecation_announced_at", "sunset_at"], "ApiVersion")


def test_publishing_the_guide_unblocks_the_breaking_deprecation(
    api, programme, clock_at_default, product
):
    """Publishing the guide records it against the logical clock and is the only thing the
    breaking announcement was waiting for: the retry lands on sixty days of notice, filling the
    product's two-version deprecation window.

    PRD: "**Publishing a migration guide** records `migration_guide_url` on the version
    together with `migration_guide_published_at` taken from the logical clock."

    PRD: "If the version's `breaking_change` flag is true, add a further **30 days**."

    Design: Corner/validations/migration_guide_is_required_only_for_breaking_versions
    """
    plain = programme.grantable_version(product["id"], semver="1.0.0", breaking_change=False)
    programme.announce_deprecation(plain["id"], 30)
    breaking = programme.grantable_version(product["id"], semver="2.0.0", breaking_change=True)
    validate_error(
        api.announce_deprecation(breaking["id"], f.announce_deprecation_payload(60), PLATFORM_ADMIN),
        ApiError.MIGRATION_GUIDE_MISSING,
    )

    published = validate_success(
        api.publish_migration_guide(
            breaking["id"], f.migration_guide_payload(migration_guide_url=GUIDE_URL), PLATFORM_ADMIN
        )
    )
    assert_fields(
        published,
        "ApiVersion",
        migration_guide_url=GUIDE_URL,
        migration_guide_published_at="2026-08-01T00:00:00Z",
        lifecycle_state="GENERAL_AVAILABILITY",
    )

    announced = validate_success(
        api.announce_deprecation(breaking["id"], f.announce_deprecation_payload(60), PLATFORM_ADMIN)
    )
    assert_fields(
        announced,
        "ApiVersion",
        lifecycle_state="DEPRECATION_ANNOUNCED",
        required_notice_days=60,
        sunset_at="2026-09-30T00:00:00Z",
    )
    assert_instant_equals(
        announced["deprecation_announced_at"], "2026-08-01T00:00:00Z",
        "ApiVersion.deprecation_announced_at",
    )

    deprecated, meta = validate_paginated(
        api.list_api_versions(
            product["id"], PLATFORM_ADMIN, params={"lifecycle_state": "DEPRECATION_ANNOUNCED"}
        )
    )
    assert meta["total_count"] == 2, "the product should hold exactly two announced deprecations"
    assert {v["id"] for v in deprecated} == {plain["id"], breaking["id"]}


# --------------------------------------- the programme adjustment as the only update path
# A partner-tier entitlement for an uncertified onboarded developer draws 3000 rpm scaled by the
# 0.75 multiplier of the 40-59 trust band, so it commits 2250 sustained requests per minute.
UNCERTIFIED_PARTNER_SUSTAINED_RPM = 2250
UPLIFTED_SUSTAINED_RPM_POOL = 24000


def test_programme_adjustment_resizes_one_pool_and_bumps_the_product_version(
    api, programme, clock_at_default
):
    """A product opens with both pools free and is resized only through the adjustment action,
    which applies just the fields it was given, recomputes availability and advances the
    product's concurrency counter by one.

    PRD: "Pools are resizable through a **programme adjustment**, which accepts any combination
    of a new `sustained_rpm_pool`, a new `monthly_call_pool` and a new `required_tos_version`,
    together with a mandatory `adjustment_reason`. The adjustment recomputes
    `available_sustained_rpm` and `available_monthly_calls` and increments the product's
    `version` by one — which is exactly why a caller holding an older product `version` is
    refused when it later tries to provision against these pools."

    Design: Corner/endpoints/product_pool_adjustment_is_the_update_path
    """
    created = programme.create_product()
    at_rest = validate_success(api.get_api_product(created["id"], PLATFORM_ADMIN))
    assert_fields(at_rest, "ApiProduct", version=1, sustained_rpm_pool=CANONICAL_SUSTAINED_RPM_POOL)
    assert_pool_availability(
        at_rest,
        available_sustained_rpm=CANONICAL_SUSTAINED_RPM_POOL,
        allocated_sustained_rpm=0,
    )

    adjusted = validate_success(
        api.adjust_program(
            created["id"],
            f.program_adjustment_payload(
                sustained_rpm_pool=UPLIFTED_SUSTAINED_RPM_POOL,
                adjustment_reason="Capacity uplift ahead of the settlement season.",
            ),
            PLATFORM_ADMIN,
        )
    )
    assert_fields(
        adjusted,
        "ApiProduct",
        version=2,
        sustained_rpm_pool=UPLIFTED_SUSTAINED_RPM_POOL,
        monthly_call_pool=CANONICAL_MONTHLY_CALL_POOL,
    )
    assert_pool_availability(
        adjusted,
        available_sustained_rpm=UPLIFTED_SUSTAINED_RPM_POOL,
        available_monthly_calls=CANONICAL_MONTHLY_CALL_POOL,
        allocated_sustained_rpm=0,
        allocated_monthly_calls=0,
    )


def test_reducing_a_pool_below_what_is_allocated_is_refused(api, programme, clock_at_default):
    """Once a live entitlement has committed capacity out of a pool, an adjustment that would
    strand that commitment is refused and the product is left exactly as it was.

    PRD: "Pools may be resized after the fact, but never below what is already committed. A
    programme adjustment that would set `sustained_rpm_pool` below the product's current
    `allocated_sustained_rpm`, or `monthly_call_pool` below its current
    `allocated_monthly_calls`, is rejected with `ERR_POOL_BELOW_ALLOCATED` (HTTP 422)."

    Design: Corner/endpoints/product_pool_adjustment_is_the_update_path
    """
    product = programme.create_product()
    programme.adjust_product(
        product["id"],
        sustained_rpm_pool=UPLIFTED_SUSTAINED_RPM_POOL,
        adjustment_reason="Capacity uplift ahead of the settlement season.",
    )
    programme.entitlement_chain(product=product)

    committed = validate_success(api.get_api_product(product["id"], PLATFORM_ADMIN))
    assert_pool_availability(
        committed,
        available_sustained_rpm=UPLIFTED_SUSTAINED_RPM_POOL - UNCERTIFIED_PARTNER_SUSTAINED_RPM,
        allocated_sustained_rpm=UNCERTIFIED_PARTNER_SUSTAINED_RPM,
        allocated_monthly_calls=CANONICAL_REQUESTED_MONTHLY_CALLS,
    )

    resp = api.adjust_program(
        product["id"],
        f.program_adjustment_payload(
            sustained_rpm_pool=2000,
            adjustment_reason="Attempted reduction below the allocated total.",
        ),
        PLATFORM_ADMIN,
    )
    validate_error(resp, ApiError.POOL_BELOW_ALLOCATED)

    after = validate_success(api.get_api_product(product["id"], PLATFORM_ADMIN))
    assert_fields(
        after,
        "ApiProduct",
        sustained_rpm_pool=UPLIFTED_SUSTAINED_RPM_POOL,
        version=committed["version"],
    )
    assert_pool_availability(
        after,
        available_sustained_rpm=UPLIFTED_SUSTAINED_RPM_POOL - UNCERTIFIED_PARTNER_SUSTAINED_RPM,
        allocated_sustained_rpm=UNCERTIFIED_PARTNER_SUSTAINED_RPM,
    )


def test_reducing_a_pool_to_exactly_the_allocated_amount_is_permitted(
    api, programme, clock_at_default
):
    """Trimming the pool down to precisely what is committed is allowed, drives availability to
    zero, and carries the new terms revision alongside while leaving the untouched monthly pool
    where it was.

    PRD: "An adjustment that would leave either pool below the matching allocated counter is
    refused with `ERR_POOL_BELOW_ALLOCATED`."

    PRD: "Pools are resizable through a **programme adjustment**, which accepts any combination
    of a new `sustained_rpm_pool`, a new `monthly_call_pool` and a new `required_tos_version`,
    together with a mandatory `adjustment_reason`."

    Design: Corner/endpoints/product_pool_adjustment_is_the_update_path
    """
    product = programme.create_product()
    programme.adjust_product(
        product["id"],
        sustained_rpm_pool=UPLIFTED_SUSTAINED_RPM_POOL,
        adjustment_reason="Capacity uplift ahead of the settlement season.",
    )
    programme.entitlement_chain(product=product)
    before = validate_success(api.get_api_product(product["id"], PLATFORM_ADMIN))

    trimmed = validate_success(
        api.adjust_program(
            product["id"],
            f.program_adjustment_payload(
                sustained_rpm_pool=UNCERTIFIED_PARTNER_SUSTAINED_RPM,
                required_tos_version=2,
                adjustment_reason="Right-size the pool to the current allocation and publish terms v2.",
            ),
            PLATFORM_ADMIN,
        )
    )

    assert_fields(
        trimmed,
        "ApiProduct",
        sustained_rpm_pool=UNCERTIFIED_PARTNER_SUSTAINED_RPM,
        required_tos_version=2,
        monthly_call_pool=CANONICAL_MONTHLY_CALL_POOL,
        version=before["version"] + 1,
    )
    assert_pool_availability(
        trimmed,
        available_sustained_rpm=0,
        allocated_sustained_rpm=UNCERTIFIED_PARTNER_SUSTAINED_RPM,
        available_monthly_calls=CANONICAL_MONTHLY_CALL_POOL - CANONICAL_REQUESTED_MONTHLY_CALLS,
        allocated_monthly_calls=CANONICAL_REQUESTED_MONTHLY_CALLS,
    )
