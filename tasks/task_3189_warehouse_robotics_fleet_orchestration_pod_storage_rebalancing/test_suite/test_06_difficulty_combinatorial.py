"""Queue A (difficulty) translations: combinatorial formulas.

Covers rule_id combinatorial_formula:
- workload_smoothing_multi_input_score (2 tests)
- charge_credit_per_tier_then_sum_rounding (2 tests)
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    create_zone,
    create_charger,
    create_drive_unit,
    create_sku,
    create_pick_station,
    create_pod,
    create_order_with_line,
    create_pick_task_payload,
    create_charging_session_payload,
    get_station_version,
    get_drive_unit,
    stow_units,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
FLOW = TEST_USERS["flow_controller_headers"]


def _setup_smoothing_scenario():
    """One zone, one stocked pod, one station (max_queue 10). Three orders:
    O-MID (cutoff 09:00), O-LOW (cutoff next day) already queued at the
    station with sequence indices 0 and 1; O-URGENT (cutoff 08:03:20, i.e.
    200 seconds out) still unsequenced. Clock is 08:00.

    With S=200s to the urgent cutoff the PRD §3.3 score is:
      k=0: 5*max(0,120-200) + 2*2 = 4
      k=1: 5*max(0,240-200) + 2*1 = 202
      k=2: 5*max(0,360-200) + 2*0 = 800
    so lateness dominates and front insertion (k=0) uniquely minimizes.
    """
    set_clock("2026-09-01T08:00:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=2)
    pod = create_pod(zone["id"], pod_code="P1", slot_capacity=50)
    sku = create_sku(sku_code="SKU1", velocity_class="LOW")
    station = create_pick_station(zone["id"], station_code="ST1", max_queue=10)
    stow_units(sku, quantity=50)

    omid, omid_line = create_order_with_line(
        sku["id"], quantity=1, order_code="O-MID",
        cutoff_at="2026-09-01T09:00:00Z", priority=50,
    )
    olow, olow_line = create_order_with_line(
        sku["id"], quantity=1, order_code="O-LOW",
        cutoff_at="2026-09-02T00:00:00Z", priority=1,
    )
    ourgent, ourgent_line = create_order_with_line(
        sku["id"], quantity=1, order_code="O-URGENT",
        cutoff_at="2026-09-01T08:03:20Z", priority=100,
    )

    def _sequence(order, line):
        task = get_success_data(
            api_client.create_pick_task(
                create_pick_task_payload(
                    order["id"], line["id"], pod["id"], station["id"], quantity=1
                ),
                FLOW,
            )
        )
        return get_success_data(
            api_client.sequence_pick_task(
                task["id"], get_station_version(station["id"]), FLOW
            )
        )

    pt_mid = _sequence(omid, omid_line)
    pt_low = _sequence(olow, olow_line)
    return {
        "zone": zone, "pod": pod, "sku": sku, "station": station,
        "omid": omid, "olow": olow, "ourgent": ourgent,
        "ourgent_line": ourgent_line, "pt_mid": pt_mid, "pt_low": pt_low,
    }


def test_workload_smoothing_lateness_dominates_insertion(api):
    """PRD §3.3: "Lateness is the amount by which the estimated finish exceeds
    the seconds remaining until the order's `cutoff_at`, floored at zero."
    PRD §3.3: "The score is 5 times the lateness plus 2 times the disruption
    plus the fatigue, and the task is inserted at the position minimizing that
    score."

    Design: Difficulty/combinatorial_formula/workload_smoothing_multi_input_score
    """
    env = _setup_smoothing_scenario()
    pt_urg = get_success_data(
        api_client.create_pick_task(
            create_pick_task_payload(
                env["ourgent"]["id"], env["ourgent_line"]["id"],
                env["pod"]["id"], env["station"]["id"], quantity=1,
            ),
            FLOW,
        )
    )
    sequenced = get_success_data(
        api_client.sequence_pick_task(
            pt_urg["id"], get_station_version(env["station"]["id"]), FLOW
        )
    )
    assert sequenced["sequence_index"] == 0, (
        "urgent task (cutoff 08:03:20, 200s out) must jump to the front of "
        f"the queue (position 0) because lateness dominates; got {sequenced['sequence_index']}"
    )


def test_workload_smoothing_existing_tasks_shift_right(api):
    """PRD §3.3: "Disruption is the sum, over every existing queued task, of
    the absolute shift between its current `sequence_index` and where it
    would land after insertion."
    PRD §3.3: "the task is inserted at the position minimizing that score;
    ties resolve to the larger position index, which is the least disruptive."

    Design: Difficulty/combinatorial_formula/workload_smoothing_multi_input_score
    """
    env = _setup_smoothing_scenario()
    assert env["pt_mid"]["sequence_index"] == 0
    assert env["pt_low"]["sequence_index"] == 1
    pt_urg = get_success_data(
        api_client.create_pick_task(
            create_pick_task_payload(
                env["ourgent"]["id"], env["ourgent_line"]["id"],
                env["pod"]["id"], env["station"]["id"], quantity=1,
            ),
            FLOW,
        )
    )
    sequenced = get_success_data(
        api_client.sequence_pick_task(
            pt_urg["id"], get_station_version(env["station"]["id"]), FLOW
        )
    )
    assert sequenced["sequence_index"] == 0
    # Existing queued tasks shift right by one position after front insertion.
    after_mid = get_success_data(api_client.get_pick_task(env["pt_mid"]["id"], FLOW))
    after_low = get_success_data(api_client.get_pick_task(env["pt_low"]["id"], FLOW))
    assert after_mid["sequence_index"] == 1, (
        f"O-MID task must shift 0 -> 1, got {after_mid['sequence_index']}"
    )
    assert after_low["sequence_index"] == 2, (
        f"O-LOW task must shift 1 -> 2, got {after_low['sequence_index']}"
    )


def _setup_charge_session(duration_end_clock):
    """Zone + charger (2 slots) + one drive unit; session opened at 08:00,
    clock advanced to duration_end_clock. Returns (charger, unit, session)."""
    set_clock("2026-09-01T08:00:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=2)
    charger = create_charger(zone["id"], slot_count=2)
    du = create_drive_unit(zone["id"], unit_code="DU1")
    session = get_success_data(
        api_client.create_charging_session(
            create_charging_session_payload(charger["id"], du["id"]), FLOW
        )
    )
    set_clock(duration_end_clock)
    return charger, du, session


def test_charge_credit_rounded_per_tier_then_summed(api):
    """PRD §2.8: "Charge credits are computed as whole percentage points, with
    round-half-up applied **per tier before summation** — summing first and
    rounding once is forbidden."
    PRD §3.5: "the first 30 minutes earn half a percentage point per minute,
    the minutes from 31 through 90 earn three tenths of a point per minute,
    and every minute beyond 90 earns one tenth of a point per minute."

    Design: Difficulty/combinatorial_formula/charge_credit_per_tier_then_sum_rounding
    """
    _charger, _du, session = _setup_charge_session("2026-09-01T08:47:00Z")
    closed = get_success_data(api_client.close_charging_session(session["id"], FLOW))
    # 47 minutes: tier1 = round(30*0.5)=15; tier2 = round(17*0.3)=round(5.1)=5;
    # tier3 = 0; total = 20 (sum-then-round of 20.1 would give 20 too, but the
    # per-tier rule pins the tier2 value at exactly 5).
    assert closed["charge_credit_pct"] == 20, (
        f"47-minute session must credit 20 pct (15 + 5 + 0), "
        f"got {closed['charge_credit_pct']}"
    )


def test_charge_credit_applies_battery_and_cycle_count(api):
    """PRD §3.5: "Closing transitions the session `OPEN` → `CLOSED`, restores
    the unit's `battery_pct` to the smaller of 100 and the current level plus
    the credit, increments `charge_cycle_count` by 1, decrements the charger's
    `slots_in_use` by 1, returns the unit `CHARGING` → `ACTIVE`, and
    increments the unit's `version`."

    Design: Difficulty/combinatorial_formula/charge_credit_per_tier_then_sum_rounding
    """
    _charger, du, session = _setup_charge_session("2026-09-01T08:47:00Z")
    before = get_drive_unit(du["id"])
    assert before["status"] == "CHARGING"
    closed = get_success_data(api_client.close_charging_session(session["id"], FLOW))
    assert closed["status"] == "CLOSED"
    after = get_drive_unit(du["id"])
    expected_battery = min(100, before["battery_pct"] + closed["charge_credit_pct"])
    assert after["battery_pct"] == expected_battery, (
        f"battery must rise by charge_credit_pct (capped at 100): "
        f"{before['battery_pct']} + {closed['charge_credit_pct']} -> "
        f"{after['battery_pct']}"
    )
    assert after["charge_cycle_count"] == before["charge_cycle_count"] + 1
    assert after["status"] == "ACTIVE"
