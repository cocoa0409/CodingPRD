"""Service credits issued when a platform incident is resolved: which entitlements the
platform pays, the pinned per-entitlement rounding order that produces
`total_credit_calls`, the conservation of the product's committed capacity across the
credit, and the throttle relief a credit buys an entitlement that has already overrun
its monthly allowance.
"""
from typing import Any, Dict

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_entitlement_dimensions,
    assert_fields,
    assert_instant_equals,
    assert_measurement_fields,
    assert_pool_availability,
)
from test_helpers.test_users import PLATFORM_ADMIN, SUPPORT_AGENT


def _active_partner_entitlement(programme, product: Dict[str, Any], version: Dict[str, Any]):
    """One more activated PARTNER entitlement for a fresh developer on the same version."""
    developer = programme.onboarded_developer()
    application = programme.approved_application(developer, version)
    assignment = programme.provision_entitlement(application, product["id"])
    return programme.activate_entitlement(assignment)


def test_incident_credit_lands_in_bonus_credit_and_leaves_the_product_ledger_alone(
    api, programme, certified_partner_entitlement
):
    """Resolving a platform incident credits the entitlement's bonus balance only: its
    monthly allowance and the product's two reservation counters are untouched.

    PRD: "Each rounded credit is added to its entitlement's `bonus_call_credit`, `affected_assignment_count` records how many entitlements were credited, and each credited entitlement's `throttle_state` is then re-evaluated against its enlarged effective allowance — which is how an entitlement can fall from `HARD_THROTTLED` back to `SOFT_THROTTLED` or all the way to `NORMAL` without any new traffic being ingested."

    Design: Difficulty/compensating_invariant/sla_bonus_credit_leaves_product_monthly_allocation_unchanged
    """
    product_id = certified_partner_entitlement["product"]["id"]
    assignment = certified_partner_entitlement["assignment"]
    before = programme.read_product(product_id)

    programme.set_clock("2026-08-03T00:00:00Z")
    incident = programme.open_incident(
        product_id, severity="S1", started_at="2026-08-03T00:00:00Z"
    )
    programme.set_clock("2026-08-03T00:10:00Z")
    programme.add_communication(incident, "2026-08-03T00:10:00Z")
    programme.set_clock("2026-08-03T02:30:00Z")

    resolved = validate_success(
        api.resolve_support_case(incident["id"], f.resolve_support_payload(), SUPPORT_AGENT)
    )

    # 500000 x 0.10 x 1.5 x 150 / 1440 = 7812.5, rounded half up to 7813.
    assert_fields(
        resolved,
        "SupportCase",
        state="RESOLVED",
        downtime_minutes=150,
        affected_assignment_count=1,
        total_credit_calls=7813,
    )
    credited = programme.read_entitlement(assignment["id"])
    assert_fields(
        credited,
        "QuotaAssignment",
        bonus_call_credit=7813,
        monthly_call_allowance=500000,
        monthly_calls_consumed=0,
    )
    assert_entitlement_dimensions(credited, entitlement_state="ACTIVE", throttle_state="NORMAL")

    after = programme.read_product(product_id)
    assert_pool_availability(
        after,
        allocated_sustained_rpm=3000,
        allocated_monthly_calls=500000,
        available_sustained_rpm=17000,
        available_monthly_calls=49500000,
    )
    assert_fields(
        after,
        "ApiProduct",
        allocated_monthly_calls=before["allocated_monthly_calls"],
        available_monthly_calls=before["available_monthly_calls"],
    )


def test_a_second_incident_credit_accumulates_without_drawing_on_the_product_pool(
    api, programme, certified_partner_entitlement
):
    """A second resolved incident adds a second whole credit to the same entitlement, and
    the product's committed monthly capacity is still exactly the one allowance it reserved.

    PRD: "Against these the product maintains two reservation counters, `allocated_sustained_rpm` and `allocated_monthly_calls`, each defined as the sum over the product's entitlements in `entitlement_state` `PROVISIONED` or `ACTIVE` of that entitlement's `sustained_rpm` and `monthly_call_allowance` respectively; both counters start at 0."

    Design: Difficulty/compensating_invariant/sla_bonus_credit_leaves_product_monthly_allocation_unchanged
    """
    product_id = certified_partner_entitlement["product"]["id"]
    assignment = certified_partner_entitlement["assignment"]

    programme.set_clock("2026-08-03T00:00:00Z")
    first = programme.open_incident(
        product_id, severity="S1", started_at="2026-08-03T00:00:00Z"
    )
    programme.set_clock("2026-08-03T00:10:00Z")
    programme.add_communication(first, "2026-08-03T00:10:00Z")
    programme.set_clock("2026-08-03T02:30:00Z")
    programme.resolve_case(first)

    programme.set_clock("2026-08-03T04:00:00Z")
    second = programme.open_incident(
        product_id, severity="S1", started_at="2026-08-03T04:00:00Z"
    )
    programme.set_clock("2026-08-03T04:10:00Z")
    programme.add_communication(second, "2026-08-03T04:10:00Z")
    programme.set_clock("2026-08-03T06:30:00Z")

    resolved = validate_success(
        api.resolve_support_case(second["id"], f.resolve_support_payload(), SUPPORT_AGENT)
    )

    assert_fields(
        resolved, "SupportCase", downtime_minutes=150, affected_assignment_count=1,
        total_credit_calls=7813,
    )
    credited = programme.read_entitlement(assignment["id"])
    assert_fields(
        credited,
        "QuotaAssignment",
        bonus_call_credit=15626,
        monthly_call_allowance=500000,
    )
    assert_pool_availability(
        programme.read_product(product_id),
        allocated_monthly_calls=500000,
        available_monthly_calls=49500000,
    )


def test_incident_resolution_records_the_cadence_breach_that_uplifts_the_credit(
    api, programme
):
    """An S1 incident answered inside fifteen minutes but left silent for the last 140
    minutes resolves with the cadence breached and the credit uplift recorded as 1.5.

    PRD: "Resolution sets `resolved_at`, computes `downtime_minutes` as the whole minutes between `started_at` and `resolved_at`, floored, recomputes `max_communication_gap_minutes` and `comms_gap_breached` now that the trailing segment counts, and records `credit_uplift_applied` as **1.5** when `comms_gap_breached` is true at resolution and **1.0** otherwise."

    Design: Difficulty/combinatorial_formula/sla_credit_rounded_per_assignment_then_summed
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    _active_partner_entitlement(programme, product, version)
    _active_partner_entitlement(programme, product, version)

    programme.set_clock("2026-08-02T00:00:00Z")
    incident = programme.open_incident(
        product["id"], severity="S1", started_at="2026-08-02T00:00:00Z"
    )
    assert_fields(incident, "SupportCase", first_response_due_minutes=15)
    programme.set_clock("2026-08-02T00:10:00Z")
    programme.add_communication(incident, "2026-08-02T00:10:00Z")
    programme.set_clock("2026-08-02T02:30:00Z")

    resolved = validate_success(
        api.resolve_support_case(incident["id"], f.resolve_support_payload(), SUPPORT_AGENT)
    )

    assert_fields(
        resolved,
        "SupportCase",
        state="RESOLVED",
        first_response_due_minutes=15,
        first_response_breached=False,
        downtime_minutes=150,
        max_communication_gap_minutes=140,
        comms_gap_breached=True,
    )
    assert_instant_equals(resolved["resolved_at"], "2026-08-02T02:30:00Z", "resolved_at")
    assert_decimal_equals(resolved["credit_uplift_applied"], 1.5, "credit_uplift_applied")


def test_each_affected_entitlement_is_rounded_before_the_credits_are_summed(api, programme):
    """Two identically sized entitlements each earn a raw credit of exactly 7812.5 calls, so
    the pinned order — round each entitlement, then add — yields 15626 rather than 15625.

    PRD: "**The rounding order is pinned**: each entitlement's raw credit is rounded half up to a whole number of calls *before* anything is summed, and the sum of those per-entitlement whole numbers is `total_credit_calls`, which is never re-rounded."

    Design: Difficulty/combinatorial_formula/sla_credit_rounded_per_assignment_then_summed
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    first = _active_partner_entitlement(programme, product, version)
    second = _active_partner_entitlement(programme, product, version)

    programme.set_clock("2026-08-02T00:00:00Z")
    incident = programme.open_incident(
        product["id"], severity="S1", started_at="2026-08-02T00:00:00Z"
    )
    programme.set_clock("2026-08-02T00:10:00Z")
    programme.add_communication(incident, "2026-08-02T00:10:00Z")
    programme.set_clock("2026-08-02T02:30:00Z")

    resolved = validate_success(
        api.resolve_support_case(incident["id"], f.resolve_support_payload(), SUPPORT_AGENT)
    )

    assert_fields(
        resolved,
        "SupportCase",
        affected_assignment_count=2,
        total_credit_calls=15626,
    )
    for assignment in (first, second):
        credited = programme.read_entitlement(assignment["id"])
        assert_fields(
            credited,
            "QuotaAssignment",
            bonus_call_credit=7813,
            monthly_call_allowance=500000,
        )


def test_only_active_entitlements_on_the_incidents_product_are_credited(api, programme):
    """Of three PARTNER entitlements on the affected product — one active, one never
    activated and one suspended — the resolution credits exactly the active one.

    PRD: "Every entitlement in `entitlement_state` `ACTIVE` whose pinned version belongs to the incident's `api_product_id` is credited; entitlements in `PROVISIONED`, `SUSPENDED` or `RETIRED` are excluded."

    Design: Corner/calculations/sla_credit_counts_only_active_entitlements
    """
    product = programme.create_product()
    version = programme.grantable_version(product["id"])
    active = _active_partner_entitlement(programme, product, version)

    never_activated_developer = programme.onboarded_developer()
    never_activated_application = programme.approved_application(
        never_activated_developer, version
    )
    provisioned = programme.provision_entitlement(never_activated_application, product["id"])

    suspended = programme.suspend_entitlement(
        _active_partner_entitlement(programme, product, version)
    )

    incident = programme.open_incident(
        product["id"], severity="S2", started_at="2026-08-01T00:00:00Z"
    )
    programme.set_clock("2026-08-01T04:00:00Z")
    for sent_at in (
        "2026-08-01T00:20:00Z",
        "2026-08-01T01:20:00Z",
        "2026-08-01T02:20:00Z",
        "2026-08-01T03:20:00Z",
    ):
        programme.add_communication(incident, sent_at)

    resolved = validate_success(
        api.resolve_support_case(incident["id"], f.resolve_support_payload(), SUPPORT_AGENT)
    )

    # 500000 x 0.05 x 1.0 x 240 / 1440 = 4166.66..., rounded half up to 4167.
    assert_fields(
        resolved,
        "SupportCase",
        state="RESOLVED",
        first_response_breached=False,
        downtime_minutes=240,
        max_communication_gap_minutes=60,
        comms_gap_breached=False,
        affected_assignment_count=1,
        total_credit_calls=4167,
    )
    assert_instant_equals(resolved["resolved_at"], "2026-08-01T04:00:00Z", "resolved_at")
    assert_decimal_equals(resolved["credit_uplift_applied"], 1.0, "credit_uplift_applied")

    credited = programme.read_entitlement(active["id"])
    assert_fields(credited, "QuotaAssignment", bonus_call_credit=4167)
    assert_entitlement_dimensions(credited, entitlement_state="ACTIVE", throttle_state="NORMAL")

    untouched_provisioned = programme.read_entitlement(provisioned["id"])
    assert_fields(untouched_provisioned, "QuotaAssignment", bonus_call_credit=0)
    assert_entitlement_dimensions(untouched_provisioned, entitlement_state="PROVISIONED")

    untouched_suspended = programme.read_entitlement(suspended["id"])
    assert_fields(untouched_suspended, "QuotaAssignment", bonus_call_credit=0)
    assert_entitlement_dimensions(untouched_suspended, entitlement_state="SUSPENDED")


def test_incident_credit_lifts_a_hard_throttled_entitlement_back_into_the_soft_band(
    api, programme, partner_entitlement
):
    """An entitlement that has consumed 501000 of a 500000 allowance is HARD_THROTTLED, and
    the 7813-call incident credit lowers the recomputed ratio into the soft band with no
    new traffic ingested.

    PRD: "Relief runs the other way: `HARD_THROTTLED → SOFT_THROTTLED` when a credit lowers the recomputed ratio to at least 0.80 but below 1.00, and `SOFT_THROTTLED → NORMAL` when a credit or a monthly reset lowers the recomputed ratio below 0.80."

    Design: Difficulty/transitive_cascade/incident_resolution_credit_relieves_hard_throttle
    """
    product_id = partner_entitlement["product"]["id"]
    assignment = partner_entitlement["assignment"]

    programme.set_clock("2026-08-03T00:00:00Z")
    for window_start, total_calls in (
        ("2026-08-02T00:00:00Z", 100000),
        ("2026-08-02T01:00:00Z", 100000),
        ("2026-08-02T02:00:00Z", 100000),
        ("2026-08-02T03:00:00Z", 100000),
        ("2026-08-02T04:00:00Z", 101000),
    ):
        programme.record_window(assignment, window_start, total_calls)

    overrun = programme.read_entitlement(assignment["id"])
    assert_fields(
        overrun, "QuotaAssignment", monthly_calls_consumed=501000,
        monthly_call_allowance=500000, bonus_call_credit=0,
    )
    assert_entitlement_dimensions(overrun, throttle_state="HARD_THROTTLED")

    incident = programme.open_incident(
        product_id, severity="S1", started_at="2026-08-03T00:00:00Z"
    )
    programme.set_clock("2026-08-03T00:10:00Z")
    programme.add_communication(incident, "2026-08-03T00:10:00Z")
    programme.set_clock("2026-08-03T02:30:00Z")

    resolved = validate_success(
        api.resolve_support_case(incident["id"], f.resolve_support_payload(), SUPPORT_AGENT)
    )

    assert_fields(
        resolved, "SupportCase", downtime_minutes=150, affected_assignment_count=1,
        total_credit_calls=7813,
    )
    relieved = programme.read_entitlement(assignment["id"])
    assert_fields(
        relieved,
        "QuotaAssignment",
        bonus_call_credit=7813,
        monthly_call_allowance=500000,
        monthly_calls_consumed=501000,
    )
    assert_entitlement_dimensions(
        relieved, entitlement_state="ACTIVE", throttle_state="SOFT_THROTTLED"
    )


def test_the_credited_relief_leaves_the_hard_throttled_usage_window_row_untouched(
    api, programme, partner_entitlement
):
    """The window that recorded the overrun keeps its own verdict and its 1000 overage calls
    after the credit, while the entitlement it was measured against now reads SOFT_THROTTLED.

    PRD: "A usage window is an immutable record: it has no `updated_at` and no `version`."

    Design: Difficulty/transitive_cascade/incident_resolution_credit_relieves_hard_throttle
    """
    product_id = partner_entitlement["product"]["id"]
    assignment = partner_entitlement["assignment"]

    programme.set_clock("2026-08-03T00:00:00Z")
    for window_start, total_calls in (
        ("2026-08-02T00:00:00Z", 100000),
        ("2026-08-02T01:00:00Z", 100000),
        ("2026-08-02T02:00:00Z", 100000),
        ("2026-08-02T03:00:00Z", 100000),
        ("2026-08-02T04:00:00Z", 101000),
    ):
        overrun_window = programme.record_window(assignment, window_start, total_calls)

    assert_fields(
        overrun_window, "UsageWindow", resulting_throttle_state="HARD_THROTTLED",
        overage_calls=1000, monthly_calls_consumed_after=501000,
    )

    incident = programme.open_incident(
        product_id, severity="S1", started_at="2026-08-03T00:00:00Z"
    )
    programme.set_clock("2026-08-03T00:10:00Z")
    programme.add_communication(incident, "2026-08-03T00:10:00Z")
    programme.set_clock("2026-08-03T02:30:00Z")
    validate_success(
        api.resolve_support_case(incident["id"], f.resolve_support_payload(), SUPPORT_AGENT)
    )

    windows, meta = validate_paginated(
        api.list_usage_windows(assignment["id"], PLATFORM_ADMIN)
    )
    assert meta["total_count"] == 5, f"expected five recorded windows, got {meta['total_count']}"
    last_window = windows[-1]
    assert_measurement_fields(last_window, "UsageWindow")
    assert_fields(
        last_window,
        "UsageWindow",
        window_start="2026-08-02T04:00:00Z",
        total_calls=101000,
        resulting_throttle_state="HARD_THROTTLED",
        overage_calls=1000,
        monthly_calls_consumed_after=501000,
    )
    assert_entitlement_dimensions(
        programme.read_entitlement(assignment["id"]), throttle_state="SOFT_THROTTLED"
    )
