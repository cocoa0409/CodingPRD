"""Location grading, coverage gaps and the reallocation decision lifecycle."""
import pytest

from test_helpers import (
    activate_kettle_location_ok,
    apply_reallocation,
    approve_reallocation,
    cancel_shift,
    confirm_shift,
    create_collection,
    create_kettle_location,
    create_shift_ok,
    deposit_collection_ok,
    get_campaign,
    get_kettle_location,
    get_location_performance,
    no_show_shift,
    propose_reallocation,
    set_clock,
    setup_ringing_scenario,
    verify_collection_ok,
    work_shift,
)

EIGHT_HOURS = ("09:00:00Z", "17:00:00Z")


def test_location_performance_metrics_after_two_completions_and_a_cancellation(api):
    """PRD §3.9: "The `cents_per_hour` is the location total divided by the
    covered hours, floored to a whole cent, with the divisor never allowed below
    one".
    PRD §3.9: "The `performance_index` is the `cents_per_hour` multiplied by one
    hundred minus the disruption rate percentage, that product divided by one
    hundred, and floored to a whole number."

    Design: Difficulty/combinatorial_formula/location_performance_index_tiered_multi_input
    """
    network = setup_ringing_scenario()
    shift_a = create_shift_ok(network.location["id"], network.ringer["id"],
                              "2026-11-16T09:00:00Z", "2026-11-16T17:00:00Z")
    work_shift(shift_a["id"], network.ringer["id"], "2026-11-16T09:00:00Z")
    shift_b = create_shift_ok(network.location["id"], network.ringer["id"],
                              "2026-11-17T09:00:00Z", "2026-11-17T17:00:00Z")
    work_shift(shift_b["id"], network.ringer["id"], "2026-11-17T09:00:00Z")
    shift_c = create_shift_ok(network.location["id"], network.ringer["id"],
                              "2026-11-18T09:00:00Z", "2026-11-18T17:00:00Z")
    confirm_shift(shift_c["id"])
    cancel_shift(shift_c["id"], reason="site closed for inventory")

    collection = create_collection(network.location["id"], "2026-11-18T18:00:00Z",
                                   declared_cents=720000, currency_cents=720000)
    verify_collection_ok(collection["id"])
    deposit_collection_ok(collection["id"], 716400)

    performance = get_location_performance(network.location["id"],
                                           on_date="2026-11-16T00:00:00Z")
    assert performance["covered_hours"] == 16, "two 480-minute COMPLETED shifts"
    assert performance["cents_per_hour"] == 45000, "floor(720000 / 16)"
    assert performance["performance_index"] == 30150, "floor(45000 * (100 - 33) / 100)"
    assert performance["performance_tier"] == "PLATINUM"


def test_location_coverage_gap_flags_understaffed_days(api):
    """PRD §3.9: "for the evaluated date, it sums the durations in minutes of
    the location's `COMPLETED` shifts only — scheduled, confirmed, checked-in,
    cancelled and no-show shifts are all excluded — and divides that by the
    location's `daily_required_minutes`, floored to a whole percent".
    PRD §3.9: "A location is `understaffed` when that percentage is below 80".

    Design: Difficulty/combinatorial_formula/location_performance_index_tiered_multi_input
    """
    network = setup_ringing_scenario()
    shift_a = create_shift_ok(network.location["id"], network.ringer["id"],
                              "2026-11-16T09:00:00Z", "2026-11-16T17:00:00Z")
    work_shift(shift_a["id"], network.ringer["id"], "2026-11-16T09:00:00Z")
    shift_b = create_shift_ok(network.location["id"], network.ringer["id"],
                              "2026-11-17T09:00:00Z", "2026-11-17T17:00:00Z")
    work_shift(shift_b["id"], network.ringer["id"], "2026-11-17T09:00:00Z")
    shift_c = create_shift_ok(network.location["id"], network.ringer["id"],
                              "2026-11-18T09:00:00Z", "2026-11-18T17:00:00Z")
    confirm_shift(shift_c["id"])
    cancel_shift(shift_c["id"], reason="site closed for inventory")

    covered_day = get_location_performance(network.location["id"],
                                           on_date="2026-11-16T00:00:00Z")
    assert covered_day["coverage_pct"] == 100
    assert covered_day["understaffed"] is False

    gap_day = get_location_performance(network.location["id"],
                                       on_date="2026-11-18T00:00:00Z")
    assert gap_day["coverage_pct"] == 0, "the cancelled shift contributes no coverage"
    assert gap_day["understaffed"] is True


def test_location_performance_tier_demoted_by_disruption_rate(api):
    """PRD §3.9: "the tier is set by the cents-per-hour bands: below 4000 cents
    per hour is `BRONZE`, below 8000 is `SILVER`, below 12000 is `GOLD`, and
    12000 or more is `PLATINUM`."
    PRD §3.9: "a rated location whose `performance_index` falls below 2000 is
    demoted one step down the tier ladder".

    Design: Corner/calculations/location_performance_index_conditional_demotion_floor
    """
    network = setup_ringing_scenario()
    completed = create_shift_ok(network.location["id"], network.ringer["id"],
                                "2026-11-16T09:00:00Z", "2026-11-16T17:00:00Z")
    work_shift(completed["id"], network.ringer["id"], "2026-11-16T09:00:00Z")

    no_show_shifts = [
        create_shift_ok(network.location["id"], network.ringer["id"],
                        f"2026-11-{day}T09:00:00Z", f"2026-11-{day}T17:00:00Z")
        for day in ("17", "18", "19", "20", "21", "22")
    ]

    collection = create_collection(network.location["id"], "2026-11-16T18:00:00Z",
                                   declared_cents=100000, currency_cents=100000)
    verify_collection_ok(collection["id"])
    deposit_collection_ok(collection["id"], 99500)

    set_clock("2026-11-25T00:00:00Z")
    for shift in no_show_shifts:
        no_show_shift(shift["id"])

    performance = get_location_performance(network.location["id"],
                                           on_date="2026-11-16T00:00:00Z")
    assert performance["covered_hours"] == 8, "only the COMPLETED shift counts as coverage"
    assert performance["cents_per_hour"] == 12500
    assert performance["performance_index"] == 1875, "floor(12500 * (100 - 85) / 100)"
    assert performance["performance_tier"] == "GOLD", "demoted one step from PLATINUM"


def test_expected_lift_frozen_at_approval(api):
    """PRD §3.9: "computed as the moved hours multiplied by the target location's
    `cents_per_hour` minus the source location's `cents_per_hour`, where a
    negative difference is treated as zero".
    PRD §3.9: "approval freezes the `expected_lift_cents` at its previewed value".

    Design: Corner/calculations/reallocation_expected_lift_frozen_at_approval
    """
    network = setup_two_location_network()
    assert get_kettle_location(network["source"]["id"])["cents_per_hour"] == 3000
    assert get_kettle_location(network["target"]["id"])["cents_per_hour"] == 7500

    decision = propose_reallocation(network["campaign"]["id"], network["source"]["id"],
                                    network["target"]["id"], moved_hours=8,
                                    effective_on="2026-11-20T00:00:00Z")
    assert decision["expected_lift_cents"] == 36000, "8 moved hours times the 4500 gap"

    approved = approve_reallocation(decision["id"])
    assert approved["expected_lift_cents"] == 36000
    assert approved["status"] == "APPROVED"


def test_expected_lift_unchanged_after_apply(api):
    """PRD §3.9: "that frozen figure is never recomputed by the application step
    even though the locations will have changed by then."
    PRD §3.9: "Application moves the decision to `APPLIED`, which is terminal,
    stamps `applied_at` with the current logical clock instant, reduces the
    source location's `daily_required_minutes` by the moved hours multiplied by
    sixty and increases the target location's by the same amount".

    Design: Corner/calculations/reallocation_expected_lift_frozen_at_approval
    """
    network = setup_two_location_network()
    decision = propose_reallocation(network["campaign"]["id"], network["source"]["id"],
                                    network["target"]["id"], moved_hours=8,
                                    effective_on="2026-11-20T00:00:00Z")
    approve_reallocation(decision["id"])

    set_clock("2026-11-20T00:00:00Z")
    applied = apply_reallocation(decision["id"])

    assert applied["status"] == "APPLIED"
    assert applied["expected_lift_cents"] == 36000, "the frozen lift is not recomputed"
    assert get_kettle_location(network["source"]["id"])["daily_required_minutes"] == 0
    assert get_kettle_location(network["target"]["id"])["daily_required_minutes"] == 960


def setup_two_location_network() -> dict:
    """Source location (24000 cents over 8 hours) and target location (60000 over
    8 hours), each with a DEPOSITED collection, plus a future SCHEDULED shift on
    the source so eight moved hours stay within its remaining scheduled hours."""
    network = setup_ringing_scenario(screening_completed_at="2026-11-01T00:00:00Z")
    target = create_kettle_location(network.host_site["id"], network.campaign["id"],
                                    location_code="K-TGT", placement="INDOOR")
    target = activate_kettle_location_ok(target["id"])

    # The money is banked before the shifts complete, so the completion-time
    # recompute that PRD §3.3/§3.9 mandates ("Completion ... recomputes that
    # location's `cents_per_hour` and `performance_tier` per §3.9") sees the
    # reconciled total and both locations carry a well-defined cents_per_hour.
    source_collection = create_collection(network.location["id"], "2026-11-11T18:00:00Z",
                                          declared_cents=24000, currency_cents=24000)
    verify_collection_ok(source_collection["id"])
    deposit_collection_ok(source_collection["id"], 23880)
    target_collection = create_collection(target["id"], "2026-11-12T18:00:00Z",
                                          declared_cents=60000, currency_cents=60000)
    verify_collection_ok(target_collection["id"])
    deposit_collection_ok(target_collection["id"], 59700)

    source_shift = create_shift_ok(network.location["id"], network.ringer["id"],
                                   "2026-11-11T09:00:00Z", "2026-11-11T17:00:00Z")
    work_shift(source_shift["id"], network.ringer["id"], "2026-11-11T09:00:00Z")
    target_shift = create_shift_ok(target["id"], network.ringer["id"],
                                   "2026-11-12T09:00:00Z", "2026-11-12T17:00:00Z")
    work_shift(target_shift["id"], network.ringer["id"], "2026-11-12T09:00:00Z")
    create_shift_ok(network.location["id"], network.ringer["id"],
                    "2026-11-21T09:00:00Z", "2026-11-21T17:00:00Z")

    set_clock("2026-11-16T00:00:00Z")
    return {"source": network.location, "target": target, "campaign": network.campaign}
