"""Turning an approved application into a live entitlement.

This file covers provisioning: the three-factor sustained-rate calculation with its nested
clamp against the product's finite pools, the burst headroom derived from the clamped
figure, the three-way monthly allowance, the fields the server mints for itself when an
entitlement comes into existence, the standing gate that guards activation, and the
optimistic-concurrency guard on the product whose pools the provisioning draws from.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_nulls,
    assert_pool_availability,
    assert_request_id,
    assert_three_fractional_digits,
)
from test_helpers.constants import CANONICAL_SCOPE, CLOCK_DEFAULT, UNKNOWN_ID
from test_helpers.test_users import PLATFORM_ADMIN


def _ledger_programme(programme):
    """A FINANCIAL product sized to a single partner, with one PERSONAL and one FINANCIAL scope.

    The pools are 1500 sustained rpm and 8,000,000 monthly calls, and the developer holds no
    certification, so its onboarding-snapshot trust score sits in the 40-through-59 band.
    """
    product = programme.create_product(
        name="Ledger API",
        data_sensitivity="FINANCIAL",
        scope_catalog=[
            f.scope_entry("profile.read", "PERSONAL"),
            f.scope_entry("ledger.read", "FINANCIAL"),
        ],
        sample_app_slugs=["ledger-quickstart"],
        sustained_rpm_pool=1500,
        monthly_call_pool=8000000,
    )
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.approved_application(
        developer,
        version,
        requested_tier="PARTNER",
        requested_scopes=["profile.read", "ledger.read"],
        requested_monthly_calls=20000000,
    )
    return {
        "product": product,
        "version": version,
        "developer": developer,
        "application": application,
    }


def _provision(api, programme, application, product_id):
    """Provision against the product version the caller has just observed."""
    expected_version = programme.product_version_counter(product_id)
    payload = f.quota_assignment_payload(application["id"], expected_version)
    return expected_version, api.create_quota_assignment(payload, PLATFORM_ADMIN)


# --------------------------------------------------------- the provisioning calculation
def test_sustained_rate_is_floored_from_three_factors_then_clamped_to_the_available_pool(
    api, programme
):
    """A partner whose uncertified trust lands in the 0.75 band and whose two sensitive scopes
    discount the rate to 0.85 desires 1912 rpm, but the product only has 1500 rpm left to give,
    so the entitlement is written at the clamped 1500 with the applied multiplier recorded.

    PRD: "The desired sustained rate is the tier base multiplied by the trust multiplier multiplied by the scope factor, with the final product floored to a whole number."

    PRD: "The entitlement's `sustained_rpm` is the smaller of the desired sustained rate and the product's current `available_sustained_rpm`."

    Design: Difficulty/combinatorial_formula/quota_provisioning_three_factor_nested_clamp
    """
    chain = _ledger_programme(programme)
    developer = programme.read_developer(chain["developer"]["id"])
    assert_fields(developer, "Developer", trust_score=56)

    _, response = _provision(api, programme, chain["application"], chain["product"]["id"])

    assignment = validate_success(response, expected_status=201)
    assert_fields(
        assignment,
        "QuotaAssignment",
        trust_multiplier_applied=0.75,
        sustained_rpm=1500,
        tier="PARTNER",
        entitlement_state="PROVISIONED",
    )


def test_burst_headroom_is_derived_from_the_clamped_rate_and_not_from_the_desired_one(
    api, programme
):
    """Burst uplift is taken from the 1500 rpm the entitlement actually holds, giving 4500 rpm of
    burst ceiling and ten windows' worth of burst credit, rather than from the 1912 rpm the three
    factors desired before the pool clamp bit.

    PRD: "This is the step implementers most often get wrong: `burst_rpm` is built from the **clamped** `sustained_rpm` of step two, never from the unclamped desire of step one."

    PRD: "The entitlement's opening `burst_credit_balance` is `burst_rpm` multiplied by **10**, representing ten windows' worth of burst-attributed calls, and that same figure is restored at every monthly reset."

    Design: Difficulty/combinatorial_formula/quota_provisioning_three_factor_nested_clamp
    """
    chain = _ledger_programme(programme)

    _, response = _provision(api, programme, chain["application"], chain["product"]["id"])

    assignment = validate_success(response, expected_status=201)
    assert_fields(
        assignment,
        "QuotaAssignment",
        sustained_rpm=1500,
        burst_rpm=4500,
        burst_credit_balance=45000,
    )


def test_monthly_allowance_lands_on_the_pool_limit_and_both_reservations_are_taken(
    api, programme
):
    """The allowance is the smallest of the requested 20,000,000, the partner cap of 10,000,000 and
    the product's remaining 8,000,000, so it settles on the pool figure; both clamped figures are
    then reserved, leaving the product with nothing available on either dimension.

    PRD: "`monthly_call_allowance` is the smallest of three numbers: the application's `requested_monthly_calls`, the tier's monthly cap — 50,000 at `SANDBOX`, 1,000,000 at `STANDARD`, 10,000,000 at `PARTNER` and 60,000,000 at `PRIVILEGED` — and the product's current `available_monthly_calls`."

    PRD: "Two derived read-only figures follow: `available_sustained_rpm` is `sustained_rpm_pool` less `allocated_sustained_rpm`, and `available_monthly_calls` is `monthly_call_pool` less `allocated_monthly_calls`."

    Design: Difficulty/combinatorial_formula/quota_provisioning_three_factor_nested_clamp
    """
    chain = _ledger_programme(programme)

    _, response = _provision(api, programme, chain["application"], chain["product"]["id"])

    assignment = validate_success(response, expected_status=201)
    assert_fields(assignment, "QuotaAssignment", monthly_call_allowance=8000000)

    product = programme.read_product(chain["product"]["id"])
    assert_pool_availability(
        product,
        allocated_sustained_rpm=1500,
        available_sustained_rpm=0,
        allocated_monthly_calls=8000000,
        available_monthly_calls=0,
    )


# ------------------------------------------------------- computed and server-minted fields
def test_entitlement_quota_comes_from_the_calculation_and_never_from_the_request_body(
    api, programme
):
    """A standard-tier developer asking for 5,000,000 monthly calls is written at the tier cap of
    1,000,000 with sustained 450, burst 900 and credit 9000 — none of which the two-field
    provisioning body could have carried.

    PRD: "An approved application is turned into a live **entitlement** by a `PlatformAdmin`, who supplies only two fields: the `access_application_id` being realised and the `expected_api_product_version` proving which view of the product's pools the caller is allocating against."

    PRD: "The **tier base** is 60 requests per minute at `SANDBOX`, 600 at `STANDARD`, 3,000 at `PARTNER` and 12,000 at `PRIVILEGED`."

    Design: Corner/entities/assignment_computed_fields_derive_from_calculation_not_from_request
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.approved_application(
        developer, version, requested_tier="STANDARD", requested_monthly_calls=5000000
    )
    assert_fields(programme.read_developer(developer["id"]), "Developer", trust_score=56)

    _, response = _provision(api, programme, application, product["id"])

    assignment = validate_success(response, expected_status=201)
    assert_fields(
        assignment,
        "QuotaAssignment",
        tier="STANDARD",
        trust_multiplier_applied=0.75,
        sustained_rpm=450,
        burst_rpm=900,
        burst_credit_balance=9000,
        monthly_call_allowance=1000000,
        granted_scopes=[CANONICAL_SCOPE],
        pinned_api_version_id=version["id"],
    )
    assert_pool_availability(
        programme.read_product(product["id"]),
        available_sustained_rpm=19550,
        available_monthly_calls=49000000,
    )


def test_new_entitlement_opens_at_provisioned_and_normal_with_every_lifecycle_stamp_null(
    api, programme
):
    """The entitlement's identity and tier are copied from the application it realises rather than
    supplied, its two state dimensions open at `PROVISIONED` and `NORMAL` with the whole lifecycle
    stamp set still null, and the product's revision counter moves because its pools were written.

    PRD: "The entitlement copies `developer_id` from the application, freezes `pinned_api_version_id` from the application's `target_api_version_id`, copies `tier` from `approved_tier` and `granted_scopes` from the application's granted set, starts `entitlement_state` at `PROVISIONED` and `throttle_state` at `NORMAL`, sets `bonus_call_credit` and `monthly_calls_consumed` to 0, sets `last_reset_at` from the logical clock, and leaves `activated_at`, `suspended_at`, `suspension_reason` and `retired_at` null."

    PRD: "Finally, the product's `version` increments by one, which invalidates every other caller's older observation of these pools."

    Design: Corner/entities/assignment_system_fields_and_state_defaults_are_server_minted
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.approved_application(developer, version)

    observed_version, response = _provision(api, programme, application, product["id"])

    assignment = validate_success(response, expected_status=201)
    assert_common_fields(assignment, "QuotaAssignment")
    assert_fields(
        assignment,
        "QuotaAssignment",
        developer_id=developer["id"],
        access_application_id=application["id"],
        pinned_api_version_id=version["id"],
        tier="PARTNER",
        entitlement_state="PROVISIONED",
        throttle_state="NORMAL",
        bonus_call_credit=0,
        monthly_calls_consumed=0,
        version=1,
    )
    assert_nulls(
        assignment,
        ["activated_at", "suspended_at", "suspension_reason", "retired_at"],
        "QuotaAssignment",
    )
    assert_three_fractional_digits(assignment["created_at"], "QuotaAssignment.created_at")
    assert_instant_equals(assignment["created_at"], CLOCK_DEFAULT, "QuotaAssignment.created_at")
    assert_instant_equals(assignment["last_reset_at"], CLOCK_DEFAULT, "last_reset_at")
    assert_fields(
        programme.read_product(product["id"]), "ApiProduct", version=observed_version + 1
    )


def test_reading_an_unminted_entitlement_id_reports_the_entitlement_not_found_error(
    api, programme
):
    """A syntactically valid identifier that no entitlement in the programme has ever carried is a
    not-found on the entitlement collection specifically, returned in the declared error envelope.

    PRD: "(6) Every identifier appearing in the URL path resolves to an existing resource, checked strictly left to right, yielding whichever of `ERR_DEVELOPER_NOT_FOUND`, `ERR_API_PRODUCT_NOT_FOUND`, `ERR_API_VERSION_NOT_FOUND`, `ERR_ACCESS_APPLICATION_NOT_FOUND`, `ERR_QUOTA_ASSIGNMENT_NOT_FOUND`, `ERR_UPGRADE_REQUEST_NOT_FOUND`, `ERR_SANDBOX_LEASE_NOT_FOUND`, `ERR_VIOLATION_CASE_NOT_FOUND`, `ERR_SUPPORT_CASE_NOT_FOUND` or `ERR_FEEDBACK_ITEM_NOT_FOUND` matches the first unresolvable segment — all HTTP 404."

    Design: Corner/entities/get_unknown_quota_assignment_returns_not_found
    """
    response = api.get_quota_assignment(UNKNOWN_ID, PLATFORM_ADMIN)

    error = validate_error(response, ApiError.QUOTA_ASSIGNMENT_NOT_FOUND)
    assert error["message"].strip(), "the error body carries no human-readable message"
    assert_request_id(response.json())


# ---------------------------------------------------- the standing gate on activation
def test_activation_is_blocked_while_an_investigation_holds_the_developer_under_review(
    api, programme
):
    """An officer opening an investigation moves the developer off good standing, and that state
    change on a third entity — not on the entitlement, not on the product — is what makes the
    provisioned entitlement unactivatable.

    PRD: "Opening an investigation also moves the developer's `standing` from `GOOD_STANDING` to `UNDER_REVIEW`."

    PRD: "Submitting an access application, provisioning an entitlement, activating one, reinstating one, creating a sandbox lease and submitting a directory listing all require the relevant developer to sit at `GOOD_STANDING`; any of `UNDER_REVIEW`, `RESTRICTED` or `REVOKED` blocks them with `ERR_DEVELOPER_STANDING_BLOCKED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_requires_developer_good_standing
    """
    bundle = programme.entitlement_chain(certified=True, activate=False)
    case = programme.open_case(
        bundle["developer"],
        category="RATE_ABUSE",
        severity="LOW",
        summary="Sustained rate exceeded on the pre-production key for three consecutive hours.",
    )
    programme.investigate_case(case)
    assert_fields(
        programme.read_case(case["id"]), "ViolationCase", state="INVESTIGATING", penalty_points=10
    )
    assert_fields(
        programme.read_developer(bundle["developer"]["id"]), "Developer", standing="UNDER_REVIEW"
    )

    response = api.activate_quota_assignment(bundle["assignment"]["id"], {}, PLATFORM_ADMIN)

    validate_error(response, ApiError.DEVELOPER_STANDING_BLOCKED)


def test_blocked_activation_leaves_the_entitlement_provisioned_with_its_reservation_intact(
    api, programme
):
    """The refused activation releases nothing: the entitlement stays `PROVISIONED` with no
    activation stamp, its reservation is still deducted from both product pools, and the developer's
    onboarding progress does not move because no entitlement ever reached `ACTIVE`.

    PRD: "Activation by a `PlatformAdmin` requires `entitlement_state` `PROVISIONED` — otherwise `ERR_ASSIGNMENT_STATE_INVALID` (HTTP 409) — requires the developer at `GOOD_STANDING`, and requires the pinned version's `lifecycle_state` not to be `SUNSET`."

    PRD: "A developer that has not yet reached `SANDBOX_VALIDATED` when an entitlement activates keeps whatever `onboarding_state` it had."

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_requires_developer_good_standing
    """
    bundle = programme.entitlement_chain(certified=True, activate=False)
    case = programme.open_case(
        bundle["developer"],
        category="RATE_ABUSE",
        severity="LOW",
        summary="Sustained rate exceeded on the pre-production key for three consecutive hours.",
    )
    programme.investigate_case(case)

    response = api.activate_quota_assignment(bundle["assignment"]["id"], {}, PLATFORM_ADMIN)
    validate_error(response, ApiError.DEVELOPER_STANDING_BLOCKED)

    assignment = programme.read_entitlement(bundle["assignment"]["id"])
    assert_fields(
        assignment,
        "QuotaAssignment",
        entitlement_state="PROVISIONED",
        sustained_rpm=3000,
        monthly_call_allowance=500000,
    )
    assert_nulls(assignment, ["activated_at"], "QuotaAssignment")
    assert_pool_availability(
        programme.read_product(bundle["product"]["id"]),
        available_sustained_rpm=17000,
        available_monthly_calls=49500000,
    )
    assert_fields(
        programme.read_developer(bundle["developer"]["id"]),
        "Developer",
        onboarding_state="DOCS_ACKNOWLEDGED",
    )


# ----------------------------------------- optimistic concurrency on the product's pools
def test_provisioning_from_a_stale_product_view_is_refused_before_anything_is_allocated(
    api, programme
):
    """An operator that read the product before a capacity adjustment moved the pools underneath it
    is told its view is stale, and the refusal allocates nothing and mints no entitlement — even
    though the application it was realising never changed.

    PRD: "The adjustment recomputes `available_sustained_rpm` and `available_monthly_calls` and increments the product's `version` by one — which is exactly why a caller holding an older product `version` is refused when it later tries to provision against these pools."

    PRD: "If `expected_api_product_version` does not equal the product's current `version`, the request is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412): the pools have moved since the caller read them, and the clamped figures the caller computed from that stale view are no longer valid."

    Design: Corner/cross_cutting_complexity_layers/provisioning_requires_the_product_version_it_read
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.approved_application(developer, version)
    stale_version = programme.product_version_counter(product["id"])
    programme.adjust_product(product["id"], sustained_rpm_pool=24000)

    response = api.create_quota_assignment(
        f.quota_assignment_payload(application["id"], stale_version), PLATFORM_ADMIN
    )

    validate_error(response, ApiError.STALE_PRODUCT_VERSION)
    fresh_version = programme.product_version_counter(product["id"])
    assert fresh_version == stale_version + 1, (
        f"the adjustment should have moved the product to {stale_version + 1}, "
        f"but it reads {fresh_version}"
    )
    assert_pool_availability(
        programme.read_product(product["id"]),
        allocated_sustained_rpm=0,
        allocated_monthly_calls=0,
    )
    listed, meta = validate_paginated(
        api.list_quota_assignments(PLATFORM_ADMIN, params={"access_application_id": application["id"]})
    )
    assert meta["total_count"] == 0, f"the refused provisioning minted an entitlement: {listed}"

    retry = api.create_quota_assignment(
        f.quota_assignment_payload(application["id"], fresh_version), PLATFORM_ADMIN
    )
    validate_success(retry, expected_status=201)


def test_reusing_the_product_version_an_accepted_provisioning_consumed_is_refused_as_stale(
    api, programme
):
    """The accepted provisioning is itself a write to the product's pools, so the very number that
    authorised it is stale for the next caller — and staleness is reported ahead of the rule that
    one application may back only one entitlement.

    PRD: "A successful provisioning itself increments the product's `version` by one, so the next caller working from the older number is likewise refused."

    PRD: "Because these rungs sit above every state and business check, a caller holding a stale view learns that fact before learning anything about the target's state."

    Design: Corner/cross_cutting_complexity_layers/provisioning_requires_the_product_version_it_read
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.approved_application(developer, version)
    observed_version = programme.product_version_counter(product["id"])
    first = api.create_quota_assignment(
        f.quota_assignment_payload(application["id"], observed_version), PLATFORM_ADMIN
    )
    validate_success(first, expected_status=201)

    response = api.create_quota_assignment(
        f.quota_assignment_payload(application["id"], observed_version), PLATFORM_ADMIN
    )

    validate_error(response, ApiError.STALE_PRODUCT_VERSION)
    assert_fields(
        programme.read_product(product["id"]), "ApiProduct", version=observed_version + 1
    )


# ------------------------------------------------ derived state is visible immediately
def test_provisioning_response_already_carries_the_derived_quota_and_the_deducted_pools(
    api, programme
):
    """No second read is needed to see the outcome of the calculation: the creation response itself
    carries the clamped sustained rate, the burst figures derived from it and the allowance, and the
    product read that immediately follows already shows both reservations taken.

    PRD: "**The provisioning calculation** runs in a pinned, observable order — sustained rate, then pool deduction, then burst, then monthly allowance — and no later step ever revises an earlier one."

    PRD: "Otherwise `sustained_rpm` is added to the product's `allocated_sustained_rpm`."

    Design: Corner/consistency_model/derived_state_is_visible_in_the_same_response
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    developer = programme.onboarded_developer()
    application = programme.approved_application(developer, version)

    _, response = _provision(api, programme, application, product["id"])

    assignment = validate_success(response, expected_status=201)
    assert_fields(
        assignment,
        "QuotaAssignment",
        sustained_rpm=2250,
        burst_rpm=6750,
        burst_credit_balance=67500,
        monthly_call_allowance=500000,
    )
    assert_pool_availability(
        programme.read_product(product["id"]),
        allocated_sustained_rpm=2250,
        available_sustained_rpm=17750,
        allocated_monthly_calls=500000,
        available_monthly_calls=49500000,
    )
