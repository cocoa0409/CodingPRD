"""Metering an entitlement's traffic one hour at a time.

This file covers the ingestion of hour-aligned usage windows: how an hour of traffic is
attributed between an entitlement's burst credit and its monthly allowance, how the two
inclusive throttle thresholds and the separate instantaneous rate-limit check resolve, how
the developer's traffic-quality counters move, the temporal gates that decide whether an
hour may be claimed at all, and the immutability of a stored window row.
"""
from test_helpers import factories as f
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_measurement_fields,
)
from test_helpers.test_users import PLATFORM_ADMIN
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success


# --------------------------------------------------------- attribution of an hour's traffic
def test_partner_window_pays_its_burst_calls_out_of_the_burst_credit_balance(
    api, programme, certified_partner_entitlement
):
    """An hour reported against a PARTNER entitlement whose burst credit covers the reported
    burst calls is attributed BURST_ISOLATED: only the non-burst calls are charged to the
    monthly allowance, and the credit balance falls by exactly the burst calls.

    PRD: "The window is attributed **`BURST_ISOLATED`** when — and only when — the entitlement's `tier` is `PARTNER` or `PRIVILEGED` *and* its current `burst_credit_balance` is at least the window's `burst_calls`. Under this variant `calls_charged_to_allowance` is `total_calls` less `burst_calls`, and `burst_credit_consumed` equals `burst_calls`."

    PRD: "The running ledger is then updated: `burst_credit_consumed` is subtracted from the entitlement's `burst_credit_balance`, `calls_charged_to_allowance` is added to its `monthly_calls_consumed`, and the resulting total is copied onto the window as `monthly_calls_consumed_after`."

    Design: Difficulty/dual_variant_calc/usage_attribution_isolated_then_inclusive_on_identical_window
    """
    assignment = certified_partner_entitlement["assignment"]
    before = programme.read_entitlement(assignment["id"])
    assert_fields(
        before,
        "QuotaAssignment",
        tier="PARTNER",
        burst_credit_balance=90000,
        monthly_call_allowance=500000,
        monthly_calls_consumed=0,
    )
    programme.set_clock("2026-08-02T00:00:00Z")

    window = validate_success(
        api.create_usage_window(
            assignment["id"],
            f.usage_window_payload("2026-08-01T00:00:00Z", total_calls=200000, burst_calls=50000),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert_fields(
        window,
        "UsageWindow",
        attribution_variant="BURST_ISOLATED",
        calls_charged_to_allowance=150000,
        burst_credit_consumed=50000,
        monthly_calls_consumed_after=150000,
        resulting_throttle_state="NORMAL",
        overage_calls=0,
    )
    after = programme.read_entitlement(assignment["id"])
    assert_fields(
        after,
        "QuotaAssignment",
        burst_credit_balance=40000,
        monthly_calls_consumed=150000,
        throttle_state="NORMAL",
    )


def test_identical_second_window_flips_to_burst_inclusive_once_credit_falls_short(
    api, programme, certified_partner_entitlement
):
    """A second hour with byte-identical inputs is attributed BURST_INCLUSIVE, because the
    first hour left the burst credit balance below the reported burst calls: the whole
    total_calls figure is then charged to the allowance and the credit balance is untouched.

    PRD: "The window is attributed **`BURST_INCLUSIVE`** in every other case — that is, whenever the `tier` is `SANDBOX` or `STANDARD`, or whenever `burst_credit_balance` is smaller than `burst_calls`. Under this variant `calls_charged_to_allowance` equals the whole `total_calls` figure and `burst_credit_consumed` is 0, leaving `burst_credit_balance` untouched."

    Design: Difficulty/dual_variant_calc/usage_attribution_isolated_then_inclusive_on_identical_window
    """
    assignment = certified_partner_entitlement["assignment"]
    programme.set_clock("2026-08-02T00:00:00Z")
    programme.record_window(assignment, "2026-08-01T00:00:00Z", total_calls=200000, burst_calls=50000)
    drained = programme.read_entitlement(assignment["id"])
    assert_fields(drained, "QuotaAssignment", burst_credit_balance=40000)

    window = validate_success(
        api.create_usage_window(
            assignment["id"],
            f.usage_window_payload("2026-08-01T01:00:00Z", total_calls=200000, burst_calls=50000),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert_fields(
        window,
        "UsageWindow",
        attribution_variant="BURST_INCLUSIVE",
        calls_charged_to_allowance=200000,
        burst_credit_consumed=0,
        monthly_calls_consumed_after=350000,
        resulting_throttle_state="NORMAL",
        overage_calls=0,
    )
    after = programme.read_entitlement(assignment["id"])
    assert_fields(
        after,
        "QuotaAssignment",
        burst_credit_balance=40000,
        monthly_calls_consumed=350000,
        throttle_state="NORMAL",
    )


# ----------------------------------------------------- the inclusive soft-throttle threshold
def test_consumption_one_call_short_of_eighty_percent_stays_normal_and_counts_as_clean(
    api, programme, partner_entitlement
):
    """An hour that leaves consumption at 399999 of a 500000 allowance — a ratio of
    0.799998 — resolves to NORMAL with no overage, and because the hour also stayed under
    the burst ceiling it counts as a clean window for the developer.

    PRD: "If the ratio is at least **1.00**, the window's `resulting_throttle_state` is `HARD_THROTTLED` and its `overage_calls` is `monthly_calls_consumed_after` less the effective allowance. If the ratio is at least **0.80** but below 1.00, `resulting_throttle_state` is `SOFT_THROTTLED` and `overage_calls` is 0. Otherwise `resulting_throttle_state` is `NORMAL` and `overage_calls` is 0."

    PRD: "Finally the developer's traffic-quality counters are updated exactly once per window: when `resulting_throttle_state` is `NORMAL` **and** `rate_limit_breach` is false, `clean_window_count` increments by one; in every other case `throttled_window_count` increments by one and `clean_window_count` is reset to 0."

    Design: Difficulty/boundary_precision_check/consumption_ratio_exactly_eighty_percent_soft_throttles
    """
    assignment = partner_entitlement["assignment"]
    developer = partner_entitlement["developer"]
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        sustained_rpm=2250,
        burst_rpm=6750,
        monthly_call_allowance=500000,
        bonus_call_credit=0,
    )
    programme.set_clock("2026-08-03T00:00:00Z")

    window = validate_success(
        api.create_usage_window(
            assignment["id"],
            f.usage_window_payload("2026-08-02T00:00:00Z", total_calls=399999, burst_calls=0),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert_fields(
        window,
        "UsageWindow",
        attribution_variant="BURST_ISOLATED",
        calls_charged_to_allowance=399999,
        monthly_calls_consumed_after=399999,
        resulting_throttle_state="NORMAL",
        overage_calls=0,
        rate_limit_breach=False,
    )
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        throttle_state="NORMAL",
        monthly_calls_consumed=399999,
    )
    assert_fields(
        programme.read_developer(developer["id"]),
        "Developer",
        clean_window_count=1,
        throttled_window_count=0,
    )


def test_consumption_reaching_exactly_eighty_percent_soft_throttles_and_clears_clean_count(
    api, programme, partner_entitlement
):
    """One further call takes the running total to exactly 400000 of 500000 — a ratio of
    exactly 0.80 — which soft-throttles the entitlement with overage still 0 and resets the
    developer's clean-window streak.

    PRD: "Throttle thresholds are inclusive lower bounds: a ratio of exactly 0.80 soft-throttles and a ratio of exactly 1.00 hard-throttles."

    PRD: "Whatever the window resolves to is written through to the entitlement's own `throttle_state`, which is why the same value appears in both places."

    Design: Difficulty/boundary_precision_check/consumption_ratio_exactly_eighty_percent_soft_throttles
    """
    assignment = partner_entitlement["assignment"]
    developer = partner_entitlement["developer"]
    programme.set_clock("2026-08-03T00:00:00Z")
    programme.record_window(assignment, "2026-08-02T00:00:00Z", total_calls=399999, burst_calls=0)

    window = validate_success(
        api.create_usage_window(
            assignment["id"],
            f.usage_window_payload("2026-08-02T01:00:00Z", total_calls=1, burst_calls=0),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert_fields(
        window,
        "UsageWindow",
        calls_charged_to_allowance=1,
        monthly_calls_consumed_after=400000,
        resulting_throttle_state="SOFT_THROTTLED",
        overage_calls=0,
        rate_limit_breach=False,
    )
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        throttle_state="SOFT_THROTTLED",
        monthly_calls_consumed=400000,
        burst_credit_balance=67500,
        entitlement_state="ACTIVE",
    )
    assert_fields(
        programme.read_developer(developer["id"]),
        "Developer",
        clean_window_count=0,
        throttled_window_count=1,
    )


# ------------------------------------------- the inclusive hard-throttle threshold and breach
def test_window_can_breach_the_burst_ceiling_while_staying_under_the_hard_bound(
    api, programme, partner_entitlement
):
    """An hour of 499999 calls against a burst ceiling of 6750 requests per minute breaches
    the instantaneous rate check, yet its monthly ratio of 499999/500000 is still below 1.00,
    so the window only soft-throttles and reports no overage: the two checks are independent.

    PRD: "It compares the window's average rate against the entitlement's burst ceiling: the window breaches when `total_calls` divided by the 60 minutes of the window exceeds `burst_rpm` — equivalently, when `total_calls` is strictly greater than `burst_rpm` multiplied by 60."

    PRD: "If the ratio is at least **0.80** but below 1.00, `resulting_throttle_state` is `SOFT_THROTTLED` and `overage_calls` is 0."

    Design: Corner/calculations/hard_throttle_at_exactly_full_consumption_with_zero_overage
    """
    assignment = partner_entitlement["assignment"]
    developer = partner_entitlement["developer"]
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        burst_rpm=6750,
        monthly_call_allowance=500000,
        bonus_call_credit=0,
    )
    programme.set_clock("2026-08-03T00:00:00Z")

    window = validate_success(
        api.create_usage_window(
            assignment["id"],
            f.usage_window_payload("2026-08-02T00:00:00Z", total_calls=499999, burst_calls=0),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert_fields(
        window,
        "UsageWindow",
        attribution_variant="BURST_ISOLATED",
        calls_charged_to_allowance=499999,
        burst_credit_consumed=0,
        monthly_calls_consumed_after=499999,
        resulting_throttle_state="SOFT_THROTTLED",
        overage_calls=0,
        rate_limit_breach=True,
    )
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        throttle_state="SOFT_THROTTLED",
        burst_credit_balance=67500,
    )
    assert_fields(
        programme.read_developer(developer["id"]),
        "Developer",
        clean_window_count=0,
        throttled_window_count=1,
    )


def test_consumption_reaching_exactly_the_allowance_hard_throttles_with_zero_overage(
    api, programme, partner_entitlement
):
    """The call that takes consumption to exactly the effective allowance produces a ratio of
    exactly 1.00, which hard-throttles the entitlement while overage_calls stays 0, and the
    entitlement keeps serving: the hard band is a throttle, not a suspension.

    PRD: "Throttle thresholds are inclusive lower bounds: a ratio of exactly 0.80 soft-throttles and a ratio of exactly 1.00 hard-throttles."

    PRD: "If the ratio is at least **1.00**, the window's `resulting_throttle_state` is `HARD_THROTTLED` and its `overage_calls` is `monthly_calls_consumed_after` less the effective allowance."

    Design: Corner/calculations/hard_throttle_at_exactly_full_consumption_with_zero_overage
    """
    assignment = partner_entitlement["assignment"]
    developer = partner_entitlement["developer"]
    programme.set_clock("2026-08-03T00:00:00Z")
    programme.record_window(assignment, "2026-08-02T00:00:00Z", total_calls=499999, burst_calls=0)

    window = validate_success(
        api.create_usage_window(
            assignment["id"],
            f.usage_window_payload("2026-08-02T01:00:00Z", total_calls=1, burst_calls=0),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert_fields(
        window,
        "UsageWindow",
        calls_charged_to_allowance=1,
        monthly_calls_consumed_after=500000,
        resulting_throttle_state="HARD_THROTTLED",
        overage_calls=0,
        rate_limit_breach=False,
    )
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        throttle_state="HARD_THROTTLED",
        monthly_calls_consumed=500000,
        burst_credit_balance=67500,
        entitlement_state="ACTIVE",
    )
    assert_fields(
        programme.read_developer(developer["id"]),
        "Developer",
        clean_window_count=0,
        throttled_window_count=2,
    )


# ------------------------------------------------------------ a stored window is a fixed row
def test_ingested_usage_window_carries_only_id_and_created_at_of_the_common_set(
    api, programme, partner_entitlement
):
    """A usage window is a measurement record: its payload carries id and created_at but
    neither updated_at nor version, alongside the derived window_end and the attribution
    counters, and the same shape comes back from the entitlement's window list.

    PRD: "`UsageWindow` is the single exception. A usage window is an immutable measurement record, so it carries only `id` and `created_at`; it has neither `updated_at` nor `version`, and neither field appears in its response payload."

    PRD: "The server derives `window_end` as `window_start` advanced by 60 minutes, and records the entitlement it was measured against as the window's `quota_assignment_id`."

    Design: Corner/entities/usage_window_is_immutable_and_carries_no_version
    """
    assignment = partner_entitlement["assignment"]
    programme.set_clock("2026-08-03T00:00:00Z")

    window = validate_success(
        api.create_usage_window(
            assignment["id"],
            f.usage_window_payload("2026-08-02T00:00:00Z", total_calls=100000, burst_calls=0),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert_measurement_fields(window, "UsageWindow")
    assert_fields(
        window,
        "UsageWindow",
        quota_assignment_id=assignment["id"],
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T01:00:00Z",
        total_calls=100000,
        calls_charged_to_allowance=100000,
    )
    listed, meta = validate_paginated(api.list_usage_windows(assignment["id"], PLATFORM_ADMIN))
    assert meta["total_count"] == 1, f"expected one stored window, got {meta['total_count']}"
    assert_measurement_fields(listed[0], "UsageWindow")


def test_resubmitting_a_stored_window_start_is_refused_and_changes_no_counter(
    api, programme, partner_entitlement
):
    """The only way to restate a stored hour is to resubmit its window_start, which is
    refused as a duplicate; the stored row keeps its original call count and the
    entitlement's consumption ledger is untouched.

    PRD: "And finally no window may already exist for this entitlement with the same `window_start`, otherwise `ERR_WINDOW_DUPLICATE` (HTTP 409)."

    PRD: "Because ordering is checked before duplication, an exact repeat of the latest `window_start` passes the ordering gate and lands on the duplicate gate."

    Design: Corner/entities/usage_window_is_immutable_and_carries_no_version
    """
    assignment = partner_entitlement["assignment"]
    programme.set_clock("2026-08-03T00:00:00Z")
    programme.record_window(assignment, "2026-08-02T00:00:00Z", total_calls=100000, burst_calls=0)

    refused = api.create_usage_window(
        assignment["id"],
        f.usage_window_payload("2026-08-02T00:00:00Z", total_calls=999999, burst_calls=0),
        PLATFORM_ADMIN,
    )

    validate_error(refused, ApiError.WINDOW_DUPLICATE)
    listed, meta = validate_paginated(api.list_usage_windows(assignment["id"], PLATFORM_ADMIN))
    assert meta["total_count"] == 1, f"expected one stored window, got {meta['total_count']}"
    assert_fields(
        listed[0],
        "UsageWindow",
        total_calls=100000,
        calls_charged_to_allowance=100000,
        window_end="2026-08-02T01:00:00Z",
    )
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        monthly_calls_consumed=100000,
    )


# ------------------------------------------------ the temporal gates guarding an ingested hour
def test_window_start_off_the_hour_is_refused_as_misaligned(api, programme, partner_entitlement):
    """A window_start at half past the hour is not a one-hour measurement bucket, so
    ingestion is refused with the alignment error and no window is stored.

    PRD: "`window_start` must be exactly hour-aligned — its minute, second and millisecond components all zero — and `window_end` must equal `window_start` plus 60 minutes, otherwise `ERR_WINDOW_NOT_ALIGNED` (HTTP 422)."

    Design: Corner/validations/usage_window_temporal_rules_and_clock_monotonicity
    """
    assignment = partner_entitlement["assignment"]
    programme.set_clock("2026-08-03T00:00:00Z")
    programme.record_window(assignment, "2026-08-02T00:00:00Z", total_calls=100000, burst_calls=0)

    refused = api.create_usage_window(
        assignment["id"],
        f.usage_window_payload("2026-08-02T02:30:00Z", total_calls=10, burst_calls=0),
        PLATFORM_ADMIN,
    )

    validate_error(refused, ApiError.WINDOW_NOT_ALIGNED)
    _, meta = validate_paginated(api.list_usage_windows(assignment["id"], PLATFORM_ADMIN))
    assert meta["total_count"] == 1, f"expected one stored window, got {meta['total_count']}"
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        monthly_calls_consumed=100000,
    )


def test_window_whose_end_passes_the_clock_is_refused_as_future_traffic(
    api, programme, partner_entitlement
):
    """An hour that starts exactly at the logical clock still ends an hour beyond it, so the
    traffic has not happened yet and ingestion is refused as a future window.

    PRD: "`window_end` must be at or before the current logical clock, so no future traffic can be claimed, otherwise `ERR_WINDOW_IN_FUTURE` (HTTP 422)."

    Design: Corner/validations/usage_window_temporal_rules_and_clock_monotonicity
    """
    assignment = partner_entitlement["assignment"]
    programme.set_clock("2026-08-03T00:00:00Z")
    programme.record_window(assignment, "2026-08-02T00:00:00Z", total_calls=100000, burst_calls=0)

    refused = api.create_usage_window(
        assignment["id"],
        f.usage_window_payload("2026-08-03T00:00:00Z", total_calls=10, burst_calls=0),
        PLATFORM_ADMIN,
    )

    validate_error(refused, ApiError.WINDOW_IN_FUTURE)
    _, meta = validate_paginated(api.list_usage_windows(assignment["id"], PLATFORM_ADMIN))
    assert meta["total_count"] == 1, f"expected one stored window, got {meta['total_count']}"
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        monthly_calls_consumed=100000,
    )


def test_window_earlier_than_the_newest_stored_hour_is_refused_as_out_of_order(
    api, programme, partner_entitlement
):
    """Hours must arrive in non-decreasing order, so a backfill for the hour before the newest
    stored window is refused and the stored ledger is unchanged.

    PRD: "`window_start` must be at or after the most recent `window_start` already recorded for this entitlement, so windows arrive in non-decreasing chronological order, otherwise `ERR_WINDOW_OUT_OF_ORDER` (HTTP 422)."

    Design: Corner/validations/usage_window_temporal_rules_and_clock_monotonicity
    """
    assignment = partner_entitlement["assignment"]
    programme.set_clock("2026-08-03T00:00:00Z")
    programme.record_window(assignment, "2026-08-02T00:00:00Z", total_calls=100000, burst_calls=0)

    refused = api.create_usage_window(
        assignment["id"],
        f.usage_window_payload("2026-08-01T23:00:00Z", total_calls=10, burst_calls=0),
        PLATFORM_ADMIN,
    )

    validate_error(refused, ApiError.WINDOW_OUT_OF_ORDER)
    _, meta = validate_paginated(api.list_usage_windows(assignment["id"], PLATFORM_ADMIN))
    assert meta["total_count"] == 1, f"expected one stored window, got {meta['total_count']}"
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        monthly_calls_consumed=100000,
    )


def test_moving_the_programme_clock_backwards_is_refused_and_leaves_it_where_it_was(
    api, programme, partner_entitlement
):
    """The logical clock that these window comparisons are evaluated against only moves
    forward: an attempt to set it to an instant strictly earlier than the current one is
    refused, and a subsequent read still reports the instant it had reached.

    PRD: "The clock only ever moves forward: a submitted instant strictly earlier than the current one is rejected with `ERR_CLOCK_REWIND` (HTTP 422)"

    Design: Corner/validations/usage_window_temporal_rules_and_clock_monotonicity
    """
    assignment = partner_entitlement["assignment"]
    programme.set_clock("2026-08-03T00:00:00Z")
    programme.record_window(assignment, "2026-08-02T00:00:00Z", total_calls=100000, burst_calls=0)

    refused = api.set_clock("2026-08-02T00:00:00Z", PLATFORM_ADMIN)

    validate_error(refused, ApiError.CLOCK_REWIND)
    clock = validate_success(api.get_clock())
    assert_instant_equals(clock["current_utc"], "2026-08-03T00:00:00Z", "current_utc")
    _, meta = validate_paginated(api.list_usage_windows(assignment["id"], PLATFORM_ADMIN))
    assert meta["total_count"] == 1, f"expected one stored window, got {meta['total_count']}"
    assert_fields(
        programme.read_entitlement(assignment["id"]),
        "QuotaAssignment",
        monthly_calls_consumed=100000,
    )
