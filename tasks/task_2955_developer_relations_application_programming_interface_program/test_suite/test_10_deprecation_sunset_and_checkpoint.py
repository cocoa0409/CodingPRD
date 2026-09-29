"""Deprecation announcements and the checkpoint that closes them.

This file covers the announcement gate — the computed notice requirement and the per-product
cap on how many sunset windows may be open at once — and then the checkpoint-driven sunset
itself, with the retirement and upgrade-voiding cascades it fires and the discipline that a
checkpoint reports only the rows it actually moved.
"""
from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_nulls,
)
from test_helpers.test_users import PLATFORM_ADMIN


# --------------------------------------------------------------------------- builders
def _personal_product_with_versions(programme, semvers) -> Dict[str, Any]:
    """A PERSONAL-sensitivity product whose named versions are all generally available."""
    product = programme.create_product(
        name="Profile API",
        data_sensitivity="PERSONAL",
        scope_catalog=[f.scope_entry("profile.read", "PERSONAL")],
        sample_app_slugs=["profile-quickstart"],
        sustained_rpm_pool=6000,
        monthly_call_pool=2000000,
        required_tos_version=1,
    )
    versions = [
        programme.grantable_version(product["id"], semver=semver, breaking_change=False)
        for semver in semvers
    ]
    return {"product": product, "versions": versions}


def _partner_pin_with_pending_upgrade(programme) -> Dict[str, Any]:
    """An ACTIVE PARTNER entitlement pinned to a PUBLIC version, with a live upgrade ask.

    The entitlement draws 3000 x 0.75 = 2250 sustained rpm and 500000 monthly calls out of
    the product's 20000 / 50000000 pools, and the developer has asked for 4000 sustained rpm
    without anybody running the allocation waterfall.
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"], semver="1.0.0", breaking_change=False)
    developer = programme.onboarded_developer()
    application = programme.approved_application(developer, version)
    assignment = programme.provision_entitlement(application, product["id"])
    assignment = programme.activate_entitlement(assignment)
    upgrade = programme.request_upgrade(assignment, developer, 4000)
    return {
        "product": product,
        "version": version,
        "developer": developer,
        "assignment": assignment,
        "upgrade": upgrade,
    }


def _leases_and_entitlement_on_one_developer(programme) -> Dict[str, Any]:
    """One developer holding two adjacent sandbox leases and one ACTIVE PARTNER entitlement.

    The first lease occupies 2026-08-01 to 2026-08-03, the second 2026-08-03 to 2026-08-13,
    and the entitlement's ``last_reset_at`` is the provisioning instant 2026-08-01.
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"], semver="1.0.0", breaking_change=False)
    developer = programme.onboarded_developer()
    first_lease = programme.take_lease(
        developer, product["id"], "2026-08-01T00:00:00Z", lease_days=2
    )
    second_lease = programme.take_lease(
        developer, product["id"], "2026-08-03T00:00:00Z", lease_days=10
    )
    application = programme.approved_application(developer, version)
    assignment = programme.provision_entitlement(application, product["id"])
    assignment = programme.activate_entitlement(assignment)
    return {
        "product": product,
        "version": version,
        "developer": developer,
        "first_lease": first_lease,
        "second_lease": second_lease,
        "assignment": assignment,
    }


# ------------------------------------------- the computed notice requirement at its boundary
def test_notice_one_day_short_of_the_personal_baseline_is_refused(api, programme, clock_at_default):
    """A PERSONAL product's version demands 60 days of notice, so 59 days is refused and the
    version's deprecation timeline stays empty.

    PRD: "Start from the baseline for the product's `data_sensitivity`: **30 days** for `PUBLIC`, **60 days** for `PERSONAL`, **90 days** for `FINANCIAL`."

    PRD: "The submitted `notice_days` must be at least `required_notice_days`; the comparison is inclusive, so submitting exactly the required number passes, and submitting fewer is rejected with `ERR_NOTICE_PERIOD_TOO_SHORT` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/notice_days_exactly_equal_to_required_is_accepted
    """
    built = _personal_product_with_versions(programme, ["1.0.0"])
    version = built["versions"][0]

    response = api.announce_deprecation(
        version["id"], f.announce_deprecation_payload(59), PLATFORM_ADMIN
    )

    validate_error(response, ApiError.NOTICE_PERIOD_TOO_SHORT)
    unchanged = programme.read_version(version["id"])
    assert_fields(unchanged, "ApiVersion", lifecycle_state="GENERAL_AVAILABILITY")
    assert_nulls(
        unchanged,
        ["deprecation_announced_at", "sunset_at", "notice_days_at_announcement"],
        "ApiVersion",
    )


def test_notice_exactly_equal_to_the_personal_baseline_is_accepted(api, programme, clock_at_default):
    """Exactly 60 days of notice on a PERSONAL product is accepted and lands the sunset instant
    60 whole days after the announcement, on 2026-09-30.

    PRD: "On success the version records `deprecation_announced_at` from the logical clock, sets `sunset_at` to that instant advanced by the submitted `notice_days` whole days, records `notice_days_at_announcement` as the floor of the whole days between the logical clock and `sunset_at` at announcement time, and moves `GENERAL_AVAILABILITY → DEPRECATION_ANNOUNCED`."

    Design: Difficulty/boundary_precision_check/notice_days_exactly_equal_to_required_is_accepted
    """
    built = _personal_product_with_versions(programme, ["1.0.0"])
    version = built["versions"][0]

    announced = validate_success(
        api.announce_deprecation(version["id"], f.announce_deprecation_payload(60), PLATFORM_ADMIN),
        expected_status=200,
    )

    assert_fields(
        announced,
        "ApiVersion",
        lifecycle_state="DEPRECATION_ANNOUNCED",
        required_notice_days=60,
        notice_days_at_announcement=60,
    )
    assert_instant_equals(
        announced["deprecation_announced_at"], "2026-08-01T00:00:00Z", "deprecation_announced_at"
    )
    assert_instant_equals(announced["sunset_at"], "2026-09-30T00:00:00Z", "sunset_at")


# --------------------------------------- at most two open deprecation windows per product
def test_third_concurrent_deprecation_window_on_one_product_is_refused(
    api, programme, clock_at_default
):
    """Two versions of one product may sit in DEPRECATION_ANNOUNCED at once; a third
    announcement is refused on the aggregate count even though its notice period is exact.

    PRD: "And a product may carry at most **two** versions sitting in `DEPRECATION_ANNOUNCED` at any one time; an announcement that would make a third is rejected with `ERR_DEPRECATION_WINDOW_FULL` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/deprecation_window_aggregate_capacity_two_per_product
    """
    built = _personal_product_with_versions(programme, ["1.0.0", "1.1.0", "1.2.0"])
    first, second, third = built["versions"]

    validate_success(
        api.announce_deprecation(first["id"], f.announce_deprecation_payload(60), PLATFORM_ADMIN),
        expected_status=200,
    )
    validate_success(
        api.announce_deprecation(second["id"], f.announce_deprecation_payload(60), PLATFORM_ADMIN),
        expected_status=200,
    )
    refused = api.announce_deprecation(
        third["id"], f.announce_deprecation_payload(60), PLATFORM_ADMIN
    )

    validate_error(refused, ApiError.DEPRECATION_WINDOW_FULL)
    untouched = programme.read_version(third["id"])
    assert_fields(untouched, "ApiVersion", lifecycle_state="GENERAL_AVAILABILITY")
    assert_nulls(untouched, ["sunset_at", "deprecation_announced_at"], "ApiVersion")


def test_both_open_deprecation_windows_are_listed_against_the_product(
    api, programme, clock_at_default
):
    """The two accepted announcements are the two versions the product reports as
    DEPRECATION_ANNOUNCED, each carrying the same 2026-09-30 sunset instant.

    PRD: "On success the version records `deprecation_announced_at` from the logical clock, sets `sunset_at` to that instant advanced by the submitted `notice_days` whole days, records `notice_days_at_announcement` as the floor of the whole days between the logical clock and `sunset_at` at announcement time, and moves `GENERAL_AVAILABILITY → DEPRECATION_ANNOUNCED`."

    Design: Difficulty/resource_temporal_overlap/deprecation_window_aggregate_capacity_two_per_product
    """
    built = _personal_product_with_versions(programme, ["1.0.0", "1.1.0", "1.2.0"])
    first, second, third = built["versions"]
    programme.announce_deprecation(first["id"], 60)
    programme.announce_deprecation(second["id"], 60)

    items, meta = validate_paginated(
        api.list_api_versions(
            built["product"]["id"],
            PLATFORM_ADMIN,
            {"lifecycle_state": "DEPRECATION_ANNOUNCED"},
        )
    )

    assert meta["total_count"] == 2, f"expected two open windows, got {meta['total_count']}"
    assert {item["id"] for item in items} == {first["id"], second["id"]}, (
        f"unexpected announced versions: {[item['id'] for item in items]}"
    )
    assert third["id"] not in {item["id"] for item in items}, (
        "the refused version is reported as announced"
    )
    for item in items:
        assert_instant_equals(item["sunset_at"], "2026-09-30T00:00:00Z", "sunset_at")


def test_deprecation_capacity_is_released_once_the_checkpoint_closes_both_windows(
    api, programme, clock_at_default
):
    """Capacity is per-open-window, not per-lifetime: once the checkpoint has sunset both
    announced versions, the previously refused third announcement is accepted.

    PRD: "When a programme checkpoint finds a `DEPRECATION_ANNOUNCED` version whose `sunset_at` is at or before the logical clock, the version moves `DEPRECATION_ANNOUNCED → SUNSET` — a terminal state — and records `sunset_completed_at`."

    Design: Difficulty/resource_temporal_overlap/deprecation_window_aggregate_capacity_two_per_product
    """
    built = _personal_product_with_versions(programme, ["1.0.0", "1.1.0", "1.2.0"])
    first, second, third = built["versions"]
    programme.announce_deprecation(first["id"], 60)
    programme.announce_deprecation(second["id"], 60)
    validate_error(
        api.announce_deprecation(third["id"], f.announce_deprecation_payload(60), PLATFORM_ADMIN),
        ApiError.DEPRECATION_WINDOW_FULL,
    )
    programme.set_clock("2026-09-30T00:00:00Z")

    report = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN), expected_status=200)
    reannounced = validate_success(
        api.announce_deprecation(third["id"], f.announce_deprecation_payload(60), PLATFORM_ADMIN),
        expected_status=200,
    )

    assert sorted(report["sunset_version_ids"]) == sorted([first["id"], second["id"]]), (
        f"checkpoint sunset the wrong versions: {report['sunset_version_ids']}"
    )
    assert_fields(
        reannounced,
        "ApiVersion",
        lifecycle_state="DEPRECATION_ANNOUNCED",
        required_notice_days=60,
    )
    assert_instant_equals(reannounced["sunset_at"], "2026-11-29T00:00:00Z", "sunset_at")


# ------------------------------------- the sunset cascade fired by a programme checkpoint
def test_active_partner_pin_raises_the_required_notice_to_sixty_days(
    api, programme, clock_at_default
):
    """A PUBLIC product's baseline of 30 days is doubled by one ACTIVE PARTNER entitlement
    pinned to the version, so 60 days is the exact requirement and lands sunset on 2026-09-30.

    PRD: "If at least one entitlement pinned to this version is in `entitlement_state` `ACTIVE` and holds `tier` `PARTNER` or `PRIVILEGED`, add another **30 days**."

    Design: Difficulty/transitive_cascade/checkpoint_sunset_cascades_retirement_then_upgrade_voiding
    """
    built = _partner_pin_with_pending_upgrade(programme)

    announced = validate_success(
        api.announce_deprecation(
            built["version"]["id"], f.announce_deprecation_payload(60), PLATFORM_ADMIN
        ),
        expected_status=200,
    )

    assert_fields(
        announced,
        "ApiVersion",
        lifecycle_state="DEPRECATION_ANNOUNCED",
        required_notice_days=60,
        notice_days_at_announcement=60,
    )
    assert_instant_equals(announced["sunset_at"], "2026-09-30T00:00:00Z", "sunset_at")


def test_checkpoint_sunsets_the_announced_version_once_the_clock_reaches_its_sunset_instant(
    api, programme, clock_at_default
):
    """The checkpoint moves the announced version to the terminal SUNSET state and stamps
    ``sunset_completed_at`` from the logical clock, reporting it in ``sunset_version_ids``.

    PRD: "Every version in `lifecycle_state` `DEPRECATION_ANNOUNCED` whose `sunset_at` has passed becomes `SUNSET` and sets `sunset_completed_at`, and the full sunset cascade fires for each: entitlements pinned to that version in `entitlement_state` `ACTIVE` or `SUSPENDED` become `RETIRED` and release their pool reservations under the release-once rule, their `PENDING` upgrade requests become `VOIDED`, and access applications targeting that version in `SUBMITTED`, `UNDER_REVIEW` or `CHANGES_REQUESTED` become `REJECTED` with `decision_reason` `TARGET_VERSION_SUNSET`."

    Design: Difficulty/transitive_cascade/checkpoint_sunset_cascades_retirement_then_upgrade_voiding
    """
    built = _partner_pin_with_pending_upgrade(programme)
    programme.announce_deprecation(built["version"]["id"], 60)
    programme.set_clock("2026-09-30T00:00:00Z")

    report = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN), expected_status=200)

    assert report["sunset_version_ids"] == [built["version"]["id"]], (
        f"expected only the announced version to sunset, got {report['sunset_version_ids']}"
    )
    sunset_version = programme.read_version(built["version"]["id"])
    assert_fields(sunset_version, "ApiVersion", lifecycle_state="SUNSET")
    assert_instant_equals(
        sunset_version["sunset_completed_at"], "2026-09-30T00:00:00Z", "sunset_completed_at"
    )


def test_the_sunset_cascade_retires_the_pinned_entitlement_and_returns_both_reservations(
    api, programme, clock_at_default
):
    """The entitlement pinned to the sunset version is retired in the same pass, and the
    2250 sustained rpm and 500000 monthly calls it held go back to the product's pools.

    PRD: "Every entitlement pinned to this version whose `entitlement_state` is `ACTIVE` or `SUSPENDED` becomes `RETIRED`, releasing its pool reservations subject to the idempotency rule in §2.9."

    Design: Difficulty/transitive_cascade/checkpoint_sunset_cascades_retirement_then_upgrade_voiding
    """
    built = _partner_pin_with_pending_upgrade(programme)
    programme.announce_deprecation(built["version"]["id"], 60)
    programme.set_clock("2026-09-30T00:00:00Z")

    report = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN), expected_status=200)

    assert report["retired_assignment_ids"] == [built["assignment"]["id"]], (
        f"expected the pinned entitlement to be retired, got {report['retired_assignment_ids']}"
    )
    retired = programme.read_entitlement(built["assignment"]["id"])
    assert_fields(retired, "QuotaAssignment", entitlement_state="RETIRED")
    assert_instant_equals(retired["retired_at"], "2026-09-30T00:00:00Z", "retired_at")
    assert_fields(
        programme.read_product(built["product"]["id"]),
        "ApiProduct",
        allocated_sustained_rpm=0,
        available_sustained_rpm=20000,
        allocated_monthly_calls=0,
        available_monthly_calls=50000000,
    )


def test_the_sunset_cascade_voids_the_still_pending_upgrade_request(
    api, programme, clock_at_default
):
    """The upgrade request nobody ran through the waterfall dies with the entitlement it was
    filed against, moving to the terminal VOIDED state.

    PRD: "Every `PENDING` upgrade request on those entitlements becomes `VOIDED`."

    Design: Difficulty/transitive_cascade/checkpoint_sunset_cascades_retirement_then_upgrade_voiding
    """
    built = _partner_pin_with_pending_upgrade(programme)
    programme.announce_deprecation(built["version"]["id"], 60)
    programme.set_clock("2026-09-30T00:00:00Z")

    report = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN), expected_status=200)

    assert report["voided_upgrade_request_ids"] == [built["upgrade"]["id"]], (
        f"expected the pending upgrade to be voided, got {report['voided_upgrade_request_ids']}"
    )
    assert_fields(
        programme.read_upgrade_request(built["upgrade"]["id"]),
        "UpgradeRequest",
        state="VOIDED",
    )


# ------------------------------ the checkpoint reports only the rows it actually touched
def test_checkpoint_reports_only_the_lease_whose_interval_has_actually_closed(
    api, programme, clock_at_default
):
    """At 2026-08-04 only the lease that ran to 2026-08-03 is expired; the lease running to
    2026-08-13 and the entitlement three days into its 30-day period are left out entirely.

    PRD: "Every lease in `state` `ACTIVE` whose `expires_at` has passed becomes `EXPIRED` with `closed_reason` `CHECKPOINT_EXPIRY`. Their identifiers are returned in `expired_lease_ids`."

    Design: Corner/endpoints/checkpoint_reports_only_the_rows_it_actually_touched
    """
    built = _leases_and_entitlement_on_one_developer(programme)
    programme.set_clock("2026-08-04T00:00:00Z")

    report = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN), expected_status=200)

    assert report["expired_lease_ids"] == [built["first_lease"]["id"]], (
        f"expected only the closed lease, got {report['expired_lease_ids']}"
    )
    assert report["reset_assignment_ids"] == [], (
        f"an entitlement inside its 30-day period was reported reset: {report['reset_assignment_ids']}"
    )
    for population in (
        "sunset_version_ids",
        "retired_assignment_ids",
        "voided_upgrade_request_ids",
        "finalised_case_ids",
        "expired_certification_developer_ids",
    ):
        assert report[population] == [], f"{population} should be empty, got {report[population]}"
    expired = programme.read_lease(built["first_lease"]["id"])
    assert_fields(expired, "SandboxLease", state="EXPIRED", closed_reason="CHECKPOINT_EXPIRY")
    assert expired["released_at"] is not None, "an expired lease must carry released_at"
    assert_fields(
        programme.read_lease(built["second_lease"]["id"]), "SandboxLease", state="ACTIVE"
    )


def test_a_second_checkpoint_at_the_same_clock_repeats_no_already_swept_row(
    api, programme, clock_at_default
):
    """Re-running the checkpoint without moving the clock succeeds and reports nothing beyond
    the unconditional audited rescoring, rather than erroring or re-listing swept rows.

    PRD: "Every developer's `audited_trust_score` is recomputed under the enforcement-audit variant, which is the only way that field ever changes."

    Design: Corner/endpoints/checkpoint_reports_only_the_rows_it_actually_touched
    """
    built = _leases_and_entitlement_on_one_developer(programme)
    programme.set_clock("2026-08-04T00:00:00Z")
    programme.run_checkpoint()

    report = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN), expected_status=200)

    for population in (
        "expired_lease_ids",
        "expired_certification_developer_ids",
        "sunset_version_ids",
        "retired_assignment_ids",
        "voided_upgrade_request_ids",
        "finalised_case_ids",
        "reset_assignment_ids",
    ):
        assert report[population] == [], (
            f"{population} re-listed an already swept row: {report[population]}"
        )
    assert report["rescored_developer_ids"] == [built["developer"]["id"]], (
        f"every developer is rescored on every run, got {report['rescored_developer_ids']}"
    )


def test_a_later_checkpoint_reports_the_rows_whose_boundaries_the_clock_has_now_passed(
    api, programme, clock_at_default
):
    """A row that merely looked eligible earlier is reported once the clock passes its
    boundary: at 2026-08-31 the second lease expires and the entitlement's month resets.

    PRD: "Every entitlement in `entitlement_state` `ACTIVE` whose `last_reset_at` is **30 or more whole days** before the logical clock is reset: `monthly_calls_consumed` and `bonus_call_credit` are zeroed, `burst_credit_balance` is restored to `burst_rpm` multiplied by 10, `last_reset_at` is set to the logical clock, and `throttle_state` is re-evaluated — which, with consumption back at zero, returns the entitlement to `NORMAL` from `SOFT_THROTTLED` or `HARD_THROTTLED`."

    Design: Corner/endpoints/checkpoint_reports_only_the_rows_it_actually_touched
    """
    built = _leases_and_entitlement_on_one_developer(programme)
    programme.set_clock("2026-08-04T00:00:00Z")
    programme.record_window(built["assignment"], "2026-08-01T00:00:00Z", 200000)
    programme.run_checkpoint()
    programme.set_clock("2026-08-31T00:00:00Z")

    report = validate_success(api.run_program_checkpoint({}, PLATFORM_ADMIN), expected_status=200)

    assert report["expired_lease_ids"] == [built["second_lease"]["id"]], (
        f"expected the second lease to close now, got {report['expired_lease_ids']}"
    )
    assert report["reset_assignment_ids"] == [built["assignment"]["id"]], (
        f"expected the entitlement's month to reset, got {report['reset_assignment_ids']}"
    )
    reset = programme.read_entitlement(built["assignment"]["id"])
    assert_fields(
        reset,
        "QuotaAssignment",
        monthly_calls_consumed=0,
        bonus_call_credit=0,
        burst_credit_balance=67500,
        throttle_state="NORMAL",
        monthly_call_allowance=500000,
    )
    assert_instant_equals(reset["last_reset_at"], "2026-08-31T00:00:00Z", "last_reset_at")
