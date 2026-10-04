"""Usage threshold boundary precision, tier-upgrade posture reconciliation,
cycle rollover, and the proration dual variant."""

from test_helpers import (
    ApiErrorId,
    SYSTEM,
    activate_plan,
    add_machine,
    change_plan_tier,
    create_machine_payload,
    create_org,
    create_plan,
    create_data_plan_payload,
    ingest_batch,
    make_grower_manager_headers,
    provision_modem_success,
    read_machine,
    read_plan,
    set_clock,
    setup_connected_machine,
    setup_org_dealer,
    validate_error,
    validate_success,
)


def _add_connected_machine(ctx, api, serial, imei, tier="STANDARD",
                           proration_method="CALENDAR_DAY"):
    """Second machine on the context org/dealer carried to PROVISIONED modem +
    ACTIVE plan. Returns (machine, plan)."""
    machine = add_machine(ctx, api, serial_number=serial, modem_imei=imei)
    provision_modem_success(ctx, api, machine["id"])
    plan = create_plan(ctx, api, machine["id"], tier=tier,
                       proration_method=proration_method)
    activate_plan(ctx, api, plan["id"])
    return read_machine(ctx, api, machine["id"]), plan


def test_usage_throttle_at_exactly_eighty_percent_of_cap(api):
    """PRD section 2.6: "The boundaries are inclusive on both sides: exactly
    80.00% of the cap is `THROTTLED`, and exactly 100.00% of the cap is
    `EXHAUSTED`." STANDARD cap 20480 MB: exactly 16384 MB throttles while
    16383 MB stays NORMAL.

    Design: Difficulty/boundary_precision_check/usage_throttle_at_exactly_eighty_percent_of_cap
    """
    ctx = setup_connected_machine(api)
    machine_id = ctx["machine"]["id"]
    plan_id = ctx["plan"]["id"]
    machine2, plan2 = _add_connected_machine(ctx, api, "SN-0002", "IMEI-0002")

    ingest_batch(ctx, api, machine_id, batch_id="m1-a", payload_mb=10000,
                 start_hour_iso="2026-09-01T00:00:00Z")
    ingest_batch(ctx, api, machine2["id"], batch_id="m2-a", payload_mb=16383,
                 start_hour_iso="2026-09-01T00:00:00Z")
    ingest_batch(ctx, api, machine_id, batch_id="m1-b", payload_mb=6384,
                 start_hour_iso="2026-09-01T01:00:00Z")

    plan = read_plan(ctx, api, plan_id)
    assert plan["used_mb"] == 16384
    assert plan["usage_posture"] == "THROTTLED"
    plan2 = read_plan(ctx, api, plan2["id"])
    assert plan2["used_mb"] == 16383
    assert plan2["usage_posture"] == "NORMAL"


def test_usage_exhaustion_at_cap_blocks_next_ingest(api):
    """PRD section 2.6: "at or above 1.0 of the cap the posture is
    `EXHAUSTED`", and PRD section 2.5: "Telemetry ingestion is refused ... when
    usage is exhausted (`ERR_MACHINE_POSTURE_BLOCKED`); a throttled machine
    still ingests."

    Design: Difficulty/boundary_precision_check/usage_throttle_at_exactly_eighty_percent_of_cap
    """
    ctx = setup_connected_machine(api)
    machine_id = ctx["machine"]["id"]
    plan_id = ctx["plan"]["id"]

    ingest_batch(ctx, api, machine_id, batch_id="m1-a", payload_mb=10000,
                 start_hour_iso="2026-09-01T00:00:00Z")
    ingest_batch(ctx, api, machine_id, batch_id="m1-b", payload_mb=6384,
                 start_hour_iso="2026-09-01T01:00:00Z")
    ingest_batch(ctx, api, machine_id, batch_id="m1-c", payload_mb=4096,
                 start_hour_iso="2026-09-01T02:00:00Z")

    plan = read_plan(ctx, api, plan_id)
    assert plan["used_mb"] == 20480
    assert plan["usage_posture"] == "EXHAUSTED"

    response = api.telemetry_ingest(
        machine_id,
        {
            "batch_id": "m1-d",
            "start_hour_iso": "2026-09-01T03:00:00Z",
            "hour_count": 1,
            "payload_mb": 1,
        },
        headers=SYSTEM,
    )
    validate_error(response, ApiErrorId.ERR_MACHINE_POSTURE_BLOCKED)


def test_plan_proration_calendar_day_variant(api):
    """PRD section 3.2: "under `CALENDAR_DAY` it is the true calendar month —
    the number of calendar days in the month containing the current instant,
    28 through 31 — with the fraction formed from the days remaining after the
    current day-of-month over that month length, so October's 31 days yield a
    larger remaining fraction than the alternative for the same date".
    BASIC -> STANDARD on October 15: round_half_up(30000 * (31-15)/31) =
    15484.

    Design: Difficulty/dual_variant_calc/plan_proration_calendar_day_vs_thirty_day
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    plan = create_plan(ctx, api, machine["id"], tier="BASIC",
                       proration_method="CALENDAR_DAY")
    set_clock(api, "2026-10-01T00:00:00Z")
    activate_plan(ctx, api, plan["id"])
    version = read_plan(ctx, api, plan["id"])["version"]
    set_clock(api, "2026-10-15T00:00:00Z")

    plan = change_plan_tier(ctx, api, plan["id"], "STANDARD",
                            expected_plan_version=version)
    assert plan["last_proration_charge_cents"] == 15484
    persisted = read_plan(ctx, api, plan["id"])
    assert persisted["last_proration_charge_cents"] == 15484


def test_plan_proration_thirty_day_variant_diverges(api):
    """PRD section 3.2: "under `THIRTY_DAY` every cycle is treated as exactly
    30 days measured from `cycle_start_date`, and the fraction is the greater
    of zero and 30 minus the elapsed days, over 30." Identical BASIC ->
    STANDARD change on October 15 (cycle anchored October 1, 14 days elapsed):
    round_half_up(30000 * (30-14)/30) = 16000, which differs from the
    CALENDAR_DAY outcome of 15484 for the same delta and date.

    Design: Difficulty/dual_variant_calc/plan_proration_calendar_day_vs_thirty_day
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    plan_a = create_plan(ctx, api, machine["id"], tier="BASIC",
                         proration_method="CALENDAR_DAY")

    org2 = create_org(api, name="Cottonwood Creek Coop", region_code="US-KS")
    org2_headers = make_grower_manager_headers(org2["id"])
    machine2 = validate_success(
        api.create_machine(
            create_machine_payload(org2["id"], ctx["dealer"]["id"],
                                   serial_number="SN-0002",
                                   modem_imei="IMEI-0002"),
            headers=org2_headers,
        ),
        201,
    )
    plan_b = validate_success(
        api.create_data_plan(
            create_data_plan_payload(org2["id"], machine2["id"], tier="BASIC",
                                     proration_method="THIRTY_DAY"),
            headers=org2_headers,
        ),
        201,
    )

    set_clock(api, "2026-10-01T00:00:00Z")
    activate_plan(ctx, api, plan_a["id"])
    validate_success(
        api.activate_data_plan(plan_b["id"], headers=org2_headers), 200
    )
    version_a = read_plan(ctx, api, plan_a["id"])["version"]
    version_b = validate_success(
        api.get_data_plan(plan_b["id"], headers=org2_headers), 200
    )["version"]
    set_clock(api, "2026-10-15T00:00:00Z")

    plan_a = change_plan_tier(ctx, api, plan_a["id"], "STANDARD",
                              expected_plan_version=version_a)
    plan_b = validate_success(
        api.change_data_plan_tier(
            plan_b["id"],
            {"new_tier": "STANDARD", "expected_plan_version": version_b},
            headers=org2_headers,
        ),
        200,
    )
    assert plan_a["last_proration_charge_cents"] == 15484
    assert plan_b["last_proration_charge_cents"] == 16000
    assert (
        plan_a["last_proration_charge_cents"]
        != plan_b["last_proration_charge_cents"]
    )


def test_posture_recomputed_on_tier_upgrade_from_exhausted(api):
    """PRD section 2.6: "For an `UNLIMITED` plan the posture is always
    `NORMAL`" and PRD section 3.2: on a successful change-tier "`usage_posture`
    is recomputed against the new cap, the machine's posture is recomputed". A
    BASIC plan at 5120/5120 MB holds the machine at `EXHAUSTED`; upgrading to
    UNLIMITED flips it straight to `CONNECTED` in the same request.

    Design: Corner/cross_cutting/posture_recomputed_on_tier_upgrade_from_exhausted
    """
    ctx = setup_connected_machine(api, tier="BASIC")
    machine_id = ctx["machine"]["id"]
    plan_id = ctx["plan"]["id"]

    ingest_batch(ctx, api, machine_id, batch_id="b-full", payload_mb=5120,
                 start_hour_iso="2026-09-01T00:00:00Z", hour_count=2)
    machine = read_machine(ctx, api, machine_id)
    assert machine["connectivity_posture"] == "EXHAUSTED"

    version = read_plan(ctx, api, plan_id)["version"]
    change_plan_tier(ctx, api, plan_id, "UNLIMITED",
                     expected_plan_version=version)

    machine = read_machine(ctx, api, machine_id)
    assert machine["connectivity_posture"] == "CONNECTED"
    plan = read_plan(ctx, api, plan_id)
    assert plan["usage_posture"] == "NORMAL"


def test_clock_rollover_resets_cycle_usage(api):
    """PRD section 2.6: "while the next boundary — the current
    `cycle_start_date` advanced by whole months, landing on `cycle_anchor_day`
    — falls on or before the current logical date, `used_mb` resets to 0 and
    `cycle_start_date` moves to that boundary; afterwards `usage_posture` and
    the machine's `connectivity_posture` are recomputed."

    Design: Corner/cross_cutting/clock_rollover_resets_cycle_usage
    """
    ctx = setup_connected_machine(api)
    machine_id = ctx["machine"]["id"]
    plan_id = ctx["plan"]["id"]

    ingest_batch(ctx, api, machine_id, batch_id="b-80", payload_mb=16384,
                 start_hour_iso="2026-09-01T00:00:00Z", hour_count=2)
    plan = read_plan(ctx, api, plan_id)
    assert plan["used_mb"] == 16384
    assert plan["usage_posture"] == "THROTTLED"
    assert plan["cycle_start_date"] == "2026-09-01"

    set_clock(api, "2026-10-01T00:00:00Z")
    plan = read_plan(ctx, api, plan_id)
    assert plan["used_mb"] == 0
    assert plan["usage_posture"] == "NORMAL"
    assert plan["cycle_start_date"] == "2026-10-01"
