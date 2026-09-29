"""Sandbox environment leases: the half-open occupancy interval and its arithmetic, the
per-developer-per-product exclusion that refuses an overlapping lease while admitting an exactly
adjacent one, the developer-driven validate and release actions, and the checkpoint step that
expires a lease whose end instant has fallen behind the logical clock.
"""
from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields, assert_instant_equals
from test_helpers.constants import CANONICAL_SAMPLE_APP_SLUG
from test_helpers.test_users import PLATFORM_ADMIN
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

SECOND_PRODUCT_SLUG = "profile-quickstart"


def _catalog_product(programme):
    """The public catalogue product whose sandbox the canonical developer leases."""
    return programme.create_product(sample_app_slugs=[CANONICAL_SAMPLE_APP_SLUG])


def _profile_product(programme):
    """A second, unrelated product with its own sample application slug."""
    return programme.create_product(
        name="Profile API",
        data_sensitivity="PERSONAL",
        scope_catalog=[f.scope_entry("profile.read", "PERSONAL")],
        sample_app_slugs=[SECOND_PRODUCT_SLUG],
        sustained_rpm_pool=6000,
        monthly_call_pool=2000000,
    )


def test_lease_expiry_is_the_start_instant_advanced_by_the_lease_length(api, programme):
    """A fourteen-day lease taken at the clock opens ACTIVE and ends fourteen whole days later,
    with neither close field populated.

    PRD: "The server derives `expires_at` as `starts_at` advanced by `lease_days` whole days, and
    the lease occupies the half-open interval that includes `starts_at` and excludes `expires_at`."

    Design: Difficulty/resource_temporal_overlap/sandbox_lease_adjacent_start_allowed_overlap_rejected
    """
    product = _catalog_product(programme)
    developer = programme.onboarded_developer()

    payload = f.sandbox_lease_payload(
        developer["id"], product["id"], "2026-08-01T00:00:00Z", lease_days=14,
        sample_app_slug=CANONICAL_SAMPLE_APP_SLUG,
    )
    lease = validate_success(
        api.create_sandbox_lease(payload, programme.headers_for(developer)), 201
    )

    assert_fields(lease, "SandboxLease", state="ACTIVE", released_at=None, closed_reason=None)
    assert_instant_equals(lease["starts_at"], "2026-08-01T00:00:00Z", "starts_at")
    assert_instant_equals(lease["expires_at"], "2026-08-15T00:00:00Z", "expires_at")


def test_a_lease_overlapping_an_active_lease_on_the_same_product_is_refused(api, programme):
    """A second lease that would begin one day before the incumbent's end instant lands inside the
    occupied interval and is refused.

    PRD: "If the requested interval overlaps the interval of an existing `ACTIVE` lease held by the
    same developer on the same product, the request is rejected with `ERR_SANDBOX_INTERVAL_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/sandbox_lease_adjacent_start_allowed_overlap_rejected
    """
    product = _catalog_product(programme)
    developer = programme.onboarded_developer()
    programme.take_lease(developer, product["id"], "2026-08-01T00:00:00Z", lease_days=14)

    payload = f.sandbox_lease_payload(
        developer["id"], product["id"], "2026-08-14T00:00:00Z", lease_days=7,
        sample_app_slug=CANONICAL_SAMPLE_APP_SLUG,
    )
    response = api.create_sandbox_lease(payload, programme.headers_for(developer))

    validate_error(response, ApiError.SANDBOX_INTERVAL_OVERLAP)


def test_a_lease_starting_exactly_at_the_incumbent_expiry_is_accepted(api, programme):
    """A replacement lease whose start instant is exactly the incumbent's end instant does not
    overlap it, so it is created and runs for its own seven whole days.

    PRD: "Because the interval excludes its own end instant, exact adjacency is legitimate: a new
    lease whose `starts_at` equals an existing lease's `expires_at` does not overlap and is
    accepted."

    Design: Difficulty/resource_temporal_overlap/sandbox_lease_adjacent_start_allowed_overlap_rejected
    """
    product = _catalog_product(programme)
    developer = programme.onboarded_developer()
    incumbent = programme.take_lease(developer, product["id"], "2026-08-01T00:00:00Z", lease_days=14)
    assert_instant_equals(incumbent["expires_at"], "2026-08-15T00:00:00Z", "incumbent expires_at")

    payload = f.sandbox_lease_payload(
        developer["id"], product["id"], "2026-08-15T00:00:00Z", lease_days=7,
        sample_app_slug=CANONICAL_SAMPLE_APP_SLUG,
    )
    adjacent = validate_success(
        api.create_sandbox_lease(payload, programme.headers_for(developer)), 201
    )

    assert_fields(adjacent, "SandboxLease", state="ACTIVE")
    assert_instant_equals(adjacent["expires_at"], "2026-08-22T00:00:00Z", "expires_at")


def test_the_same_overlapping_interval_on_another_product_is_accepted(api, programme):
    """The exclusion is scoped to one developer on one product, so the interval that was refused on
    the leased product is granted on a different product.

    PRD: "If the requested interval overlaps the interval of an existing `ACTIVE` lease held by the
    same developer on the same product, the request is rejected with `ERR_SANDBOX_INTERVAL_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/sandbox_lease_adjacent_start_allowed_overlap_rejected
    """
    product = _catalog_product(programme)
    other_product = _profile_product(programme)
    developer = programme.onboarded_developer()
    programme.take_lease(developer, product["id"], "2026-08-01T00:00:00Z", lease_days=14)

    payload = f.sandbox_lease_payload(
        developer["id"], other_product["id"], "2026-08-14T00:00:00Z", lease_days=7,
        sample_app_slug=SECOND_PRODUCT_SLUG,
    )
    lease = validate_success(
        api.create_sandbox_lease(payload, programme.headers_for(developer)), 201
    )

    assert_fields(lease, "SandboxLease", state="ACTIVE", api_product_id=other_product["id"])
    assert_instant_equals(lease["expires_at"], "2026-08-21T00:00:00Z", "expires_at")


def test_releasing_the_incumbent_frees_the_interval_for_a_replacement_lease(api, programme):
    """Only ACTIVE leases occupy an interval, so once the incumbent is released the previously
    overlapping start instant becomes available.

    PRD: "**Releasing** the lease hands the environment back early: `state` moves
    `ACTIVE → RELEASED`, `released_at` is set from the logical clock and `closed_reason` becomes
    `DEVELOPER_RELEASE`, which frees the interval so a replacement lease may be taken."

    Design: Difficulty/resource_temporal_overlap/sandbox_lease_adjacent_start_allowed_overlap_rejected
    """
    product = _catalog_product(programme)
    developer = programme.onboarded_developer()
    incumbent = programme.take_lease(developer, product["id"], "2026-08-01T00:00:00Z", lease_days=14)

    released = validate_success(
        api.release_sandbox_lease(incumbent["id"], {}, programme.headers_for(developer))
    )
    assert_fields(
        released, "SandboxLease", state="RELEASED", closed_reason="DEVELOPER_RELEASE"
    )

    payload = f.sandbox_lease_payload(
        developer["id"], product["id"], "2026-08-14T00:00:00Z", lease_days=7,
        sample_app_slug=CANONICAL_SAMPLE_APP_SLUG,
    )
    replacement = validate_success(
        api.create_sandbox_lease(payload, programme.headers_for(developer)), 201
    )

    assert_fields(replacement, "SandboxLease", state="ACTIVE")
    assert_instant_equals(replacement["expires_at"], "2026-08-21T00:00:00Z", "expires_at")


def test_the_developer_holds_three_active_leases_across_the_two_products(api, programme):
    """The adjacent lease, the lease on the other product and the incumbent all remain ACTIVE
    together, so the filtered lease list counts three.

    PRD: "Leases can be filtered by `developer_id`, `api_product_id` and `state`."
    PRD: "`total_count` is the number of items matching the request's filters before pagination is
    applied, and `has_more` is true exactly when items matching the filters remain beyond the
    returned page."

    Design: Difficulty/resource_temporal_overlap/sandbox_lease_adjacent_start_allowed_overlap_rejected
    """
    product = _catalog_product(programme)
    other_product = _profile_product(programme)
    developer = programme.onboarded_developer()
    incumbent = programme.take_lease(developer, product["id"], "2026-08-01T00:00:00Z", lease_days=14)
    adjacent = programme.take_lease(developer, product["id"], "2026-08-15T00:00:00Z", lease_days=7)
    elsewhere = programme.take_lease(
        developer, other_product["id"], "2026-08-14T00:00:00Z", lease_days=7,
        sample_app_slug=SECOND_PRODUCT_SLUG,
    )

    leases, meta = validate_paginated(
        api.list_sandbox_leases(PLATFORM_ADMIN, {"developer_id": developer["id"], "state": "ACTIVE"})
    )

    assert meta["total_count"] == 3, f"expected three ACTIVE leases, meta was {meta}"
    assert {lease["id"] for lease in leases} == {
        incumbent["id"], adjacent["id"], elsewhere["id"]
    }, f"unexpected lease set: {[lease['id'] for lease in leases]}"


def test_a_checkpoint_run_before_the_expiry_instant_leaves_the_lease_active(api, programme):
    """A checkpoint run while the clock still sits inside the lease interval reports no expiries and
    leaves the lease ACTIVE with both close fields null.

    PRD: "Every lease in `state` `ACTIVE` whose `expires_at` has passed becomes `EXPIRED` with
    `closed_reason` `CHECKPOINT_EXPIRY`. Their identifiers are returned in `expired_lease_ids`."

    Design: Corner/state_machines/checkpoint_expires_lease_once_expiry_is_behind_the_clock
    """
    product = _catalog_product(programme)
    developer = programme.onboarded_developer()
    lease = programme.take_lease(developer, product["id"], "2026-08-01T00:00:00Z", lease_days=3)
    assert_instant_equals(lease["expires_at"], "2026-08-04T00:00:00Z", "expires_at")
    programme.set_clock("2026-08-02T00:00:00Z")

    checkpoint = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN))

    assert checkpoint["expired_lease_ids"] == [], (
        f"expected no expiries, got {checkpoint['expired_lease_ids']}"
    )
    assert_fields(
        programme.read_lease(lease["id"]), "SandboxLease",
        state="ACTIVE", released_at=None, closed_reason=None,
    )


def test_a_checkpoint_run_past_the_expiry_instant_expires_the_lease(api, programme):
    """Once the clock has moved beyond the lease's end instant the checkpoint expires it, names it in
    `expired_lease_ids`, stamps the checkpoint close reason, and the lease can no longer be released.

    PRD: "Every lease in `state` `ACTIVE` whose `expires_at` has passed becomes `EXPIRED` with
    `closed_reason` `CHECKPOINT_EXPIRY`. Their identifiers are returned in `expired_lease_ids`."

    Design: Corner/state_machines/checkpoint_expires_lease_once_expiry_is_behind_the_clock
    """
    product = _catalog_product(programme)
    developer = programme.onboarded_developer()
    lease = programme.take_lease(developer, product["id"], "2026-08-01T00:00:00Z", lease_days=3)
    programme.set_clock("2026-08-04T06:00:00Z")

    checkpoint = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN))

    assert checkpoint["expired_lease_ids"] == [lease["id"]], (
        f"expected exactly the expired lease, got {checkpoint['expired_lease_ids']}"
    )
    assert_fields(
        programme.read_lease(lease["id"]), "SandboxLease",
        state="EXPIRED", closed_reason="CHECKPOINT_EXPIRY",
    )
    validate_error(
        api.release_sandbox_lease(lease["id"], {}, programme.headers_for(developer)),
        ApiError.LEASE_NOT_ACTIVE,
    )


def test_validating_an_active_lease_advances_the_developer_onboarding_state(api, programme):
    """Validating the seeded sample application is an empty-bodied action whose observable effect
    lands on the developer: onboarding moves on while the trust score, which the sandbox step does
    not itself reward, stays at its documentation-acknowledged value.

    PRD: "**Validating** the lease declares the seeded sample application successfully exercised;
    the lease records the validated sample application, the developer's `onboarding_state` advances
    `DOCS_ACKNOWLEDGED → SANDBOX_VALIDATED`, and `trust_score` is recomputed under the
    onboarding-snapshot variant."

    Design: Corner/endpoints/sandbox_validation_is_an_action_with_a_state_precondition
    """
    product = _catalog_product(programme)
    developer = programme.onboarded_developer()
    assert_fields(developer, "Developer", onboarding_state="DOCS_ACKNOWLEDGED", trust_score=56)
    lease = programme.take_lease(developer, product["id"], "2026-08-01T00:00:00Z", lease_days=7)
    assert_instant_equals(lease["expires_at"], "2026-08-08T00:00:00Z", "expires_at")

    validate_success(
        api.validate_sandbox_lease(lease["id"], {}, programme.headers_for(developer))
    )

    assert_fields(
        programme.read_developer(developer["id"]), "Developer",
        onboarding_state="SANDBOX_VALIDATED", trust_score=56,
    )


def test_validating_a_released_lease_is_refused_and_onboarding_is_not_replayed(api, programme):
    """The validate action's precondition is the lease state, so the very same call is refused once
    the lease has been handed back, and the developer's onboarding stays where the first validation
    left it.

    PRD: "Two developer-driven lease actions exist, and both require the lease to be `ACTIVE` —
    otherwise `ERR_LEASE_NOT_ACTIVE` (HTTP 409) — and require the acting developer to own it."

    Design: Corner/endpoints/sandbox_validation_is_an_action_with_a_state_precondition
    """
    product = _catalog_product(programme)
    developer = programme.onboarded_developer()
    headers = programme.headers_for(developer)
    lease = programme.take_lease(developer, product["id"], "2026-08-01T00:00:00Z", lease_days=7)
    validate_success(api.validate_sandbox_lease(lease["id"], {}, headers))

    released = validate_success(api.release_sandbox_lease(lease["id"], {}, headers))
    assert_fields(released, "SandboxLease", state="RELEASED", closed_reason="DEVELOPER_RELEASE")
    assert_instant_equals(released["released_at"], "2026-08-01T00:00:00Z", "released_at")

    validate_error(
        api.validate_sandbox_lease(lease["id"], {}, headers), ApiError.LEASE_NOT_ACTIVE
    )
    assert_fields(
        programme.read_developer(developer["id"]), "Developer",
        onboarding_state="SANDBOX_VALIDATED",
    )
