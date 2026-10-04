"""Mileage ledger: boundaries, exemptions, invariants, reversal, OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_mileage_ledger_invariant,
    get_policy,
    record_usage,
    record_usage_ok,
    setup_active_policy,
    validate_error,
    validate_success,
)

UW = TEST_USERS["underwriter_headers"]


def test_mileage_allowance_exact_boundary_no_overage(api):
    """PRD §3.7: "Each event's overage is the growth of the cumulative
    total's excess over the allowance: the excess of the new cumulative total
    over `annual_mileage_allowance`, minus whatever excess existed before the
    event, floored at zero."
    PRD §3.7: "`remaining_allowance_miles` is the allowance minus that total,
    which may go negative."

    Design: Difficulty/boundary_precision_check/mileage_allowance_exact_boundary
    """
    ctx = setup_active_policy(annual_mileage_allowance=3000)
    event = record_usage_ok(ctx, 3000, "2026-10-01T00:00:00Z")
    assert event["overage_charge_cents"] == 0, (
        "An event landing exactly at the allowance charges no overage"
    )
    policy = get_policy(ctx["policy"]["id"])
    assert policy["billable_miles_used"] == 3000
    assert policy["remaining_allowance_miles"] == 0


def test_mileage_allowance_boundary_plus_one_mile_charged(api):
    """PRD §3.7: "That overage in miles is charged at 12.5 cents per mile,
    rounded half-up per event, and the policy's `overage_charge_cents` is the
    sum of those per-event rounded charges — the per-event rounding precedes
    the summation, and the order is pinned."

    Design: Difficulty/boundary_precision_check/mileage_allowance_exact_boundary
    """
    ctx = setup_active_policy(annual_mileage_allowance=3000)
    record_usage_ok(ctx, 3000, "2026-10-01T00:00:00Z")
    event2 = record_usage_ok(ctx, 1, "2026-10-02T00:00:00Z")
    # round_half_up(1 * 12.5) = 13
    assert event2["overage_charge_cents"] == 13, (
        f"One mile over the allowance must charge 13 cents, got "
        f"{event2['overage_charge_cents']}"
    )
    policy = get_policy(ctx["policy"]["id"])
    assert policy["billable_miles_used"] == 3001
    assert policy["overage_charge_cents"] == 13
    assert_mileage_ledger_invariant(policy)


def test_mileage_ledger_record_reverse_invariant_restored(api):
    """PRD §3.7: "The compensating invariant holds at all times:
    `billable_miles_used` plus `remaining_allowance_miles` always equals
    `annual_mileage_allowance`."
    PRD §3.7: "reversal excludes the event and recomputes the entire ledger
    chronologically over the remaining recorded events, restoring the
    invariant exactly."

    Design: Difficulty/compensating_invariant/mileage_ledger_record_reverse_invariant
    """
    ctx = setup_active_policy(annual_mileage_allowance=3000)
    event = record_usage_ok(ctx, 1500, "2026-10-01T00:00:00Z")
    after_record = get_policy(ctx["policy"]["id"])
    assert after_record["billable_miles_used"] == 1500
    assert after_record["remaining_allowance_miles"] == 1500
    assert_mileage_ledger_invariant(after_record)

    validate_success(api.reverse_usage_event(event["id"], ctx["member_headers"]))
    after_reverse = get_policy(ctx["policy"]["id"])
    assert after_reverse["billable_miles_used"] == 0
    assert after_reverse["remaining_allowance_miles"] == 3000
    assert after_reverse["overage_charge_cents"] == 0
    assert_mileage_ledger_invariant(after_reverse)


def test_mileage_ledger_reverse_excludes_reversed_event(api):
    """PRD §3.7: "The member may reverse a recorded event, moving it to
    `REVERSED`; reversal excludes the event and recomputes the entire ledger
    chronologically over the remaining recorded events, restoring the
    invariant exactly."

    Design: Difficulty/compensating_invariant/mileage_ledger_record_reverse_invariant
    """
    ctx = setup_active_policy(annual_mileage_allowance=3000)
    record_usage_ok(ctx, 500, "2026-10-01T00:00:00Z")
    second = record_usage_ok(ctx, 700, "2026-10-02T00:00:00Z")
    mid = get_policy(ctx["policy"]["id"])
    assert mid["billable_miles_used"] == 1200
    validate_success(api.reverse_usage_event(second["id"], ctx["member_headers"]))
    after = get_policy(ctx["policy"]["id"])
    assert after["billable_miles_used"] == 500, (
        "Reversing the second event leaves only the first event billable"
    )
    assert after["remaining_allowance_miles"] == 2500
    assert_mileage_ledger_invariant(after)


def test_club_event_mileage_exemption(api):
    """PRD §3.7: "Non-ordinary kinds — club events, parades, exhibitions —
    are mileage-exempt: their `billable_miles` is zero, while an ordinary
    drive bills its full `reported_miles`."

    Design: Corner/calculations/club_event_mileage_exemption
    """
    ctx = setup_active_policy(annual_mileage_allowance=3000)
    event = record_usage_ok(ctx, 500, "2026-10-01T00:00:00Z", event_kind="CLUB_EVENT")
    assert event["billable_miles"] == 0, (
        f"CLUB_EVENT usage must be mileage-exempt, got {event['billable_miles']}"
    )
    policy = get_policy(ctx["policy"]["id"])
    assert policy["billable_miles_used"] == 0
    assert policy["overage_charge_cents"] == 0


def test_usage_temporal_vs_business_fiscal_priority(api):
    """PRD §2.8: "Business rules follow in their own fixed order — driver
    eligibility, body-referenced id existence
    (`ERR_REFERENCED_NOT_FOUND`), certified-appraisal linkage
    (`ERR_APPRAISAL_NOT_CERTIFIED`), uniqueness constraints, activation
    gates, period overlap, venue conflicts, capacity, temporal window checks,
    valuation staleness, the sanity band, the mileage hard cap,
    auction-comp sufficiency, and finally shop-certification and roadside
    rules".
    PRD §3.7: "an `event_date` that must fall inside the policy's coverage
    window (outside it the event is rejected with
    `ERR_USAGE_OUT_OF_PERIOD`)".

    Design: Difficulty/priority_pair_validation_conflict/usage_temporal_vs_business_fiscal_priority
    """
    ctx = setup_active_policy(annual_mileage_allowance=100)
    # 200 miles would breach the 150-mile hard cap AND the date 2028-01-01 is
    # outside [2026-09-01, 2027-09-01): the temporal check must win.
    policy = get_policy(ctx["policy"]["id"])
    resp = api.record_usage_event(
        policy["id"],
        {
            "reported_miles": 200,
            "event_date": "2028-01-01T00:00:00Z",
            "event_kind": "ORDINARY",
            "expected_policy_version": policy["version"],
        },
        ctx["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_USAGE_OUT_OF_PERIOD)


def test_usage_event_out_of_period_rejected_isolated(api):
    """PRD §3.7: "an `event_date` that must fall inside the policy's coverage
    window (outside it the event is rejected with
    `ERR_USAGE_OUT_OF_PERIOD`)".
    PRD §3.6: "a coverage window from `period_start` inclusive to
    `period_end` exclusive, a half-open interval".

    Design: Difficulty/priority_pair_validation_conflict/usage_temporal_vs_business_fiscal_priority
    """
    ctx = setup_active_policy(annual_mileage_allowance=3000)
    policy = get_policy(ctx["policy"]["id"])
    # Out-of-window date alone (miles well under the hard cap): the temporal
    # rule fires on its own.
    resp = api.record_usage_event(
        policy["id"],
        {
            "reported_miles": 10,
            "event_date": "2027-09-01T00:00:00Z",
            "event_kind": "ORDINARY",
            "expected_policy_version": policy["version"],
        },
        ctx["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_USAGE_OUT_OF_PERIOD)


def test_occ_stale_policy_version_on_usage_event(api):
    """PRD §2.7: "Recording a usage event against a policy requires the
    request to carry `expected_policy_version`, the client-observed `version`
    of the target `Policy`. Mileage-ledger decisions (remaining allowance,
    overage projection) are computed from a policy snapshot, so a request
    whose `expected_policy_version` does not match the policy's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than
    being serialized blindly."

    Design: Corner/cross_cutting_layers/occ_stale_policy_version_on_usage_event
    """
    ctx = setup_active_policy(annual_mileage_allowance=3000)
    stale_version = ctx["policy"]["version"]
    record_usage_ok(ctx, 100, "2026-10-01T00:00:00Z")
    resp = api.record_usage_event(
        ctx["policy"]["id"],
        {
            "reported_miles": 50,
            "event_date": "2026-10-02T00:00:00Z",
            "event_kind": "ORDINARY",
            "expected_policy_version": stale_version,
        },
        ctx["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_derived_field_reconciliation_after_reverse(api):
    """PRD §3.7: "`billable_miles_used` is the final cumulative total, and
    `remaining_allowance_miles` is the allowance minus that total, which may
    go negative."
    PRD §3.7: "reversal excludes the event and recomputes the entire ledger
    chronologically over the remaining recorded events, restoring the
    invariant exactly."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_after_reverse
    """
    ctx = setup_active_policy(annual_mileage_allowance=3000)
    event = record_usage_ok(ctx, 100, "2026-10-01T00:00:00Z")
    after_record = get_policy(ctx["policy"]["id"])
    assert after_record["remaining_allowance_miles"] == 2900
    validate_success(api.reverse_usage_event(event["id"], ctx["member_headers"]))
    after_reverse = get_policy(ctx["policy"]["id"])
    assert after_reverse["remaining_allowance_miles"] == 3000, (
        "remaining_allowance_miles must reconcile back to the full allowance"
    )
