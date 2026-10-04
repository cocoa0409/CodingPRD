"""Corner-design translations: error-catalog triggers.

Each test drives one error_id from the PRD §5 catalogue through the workflow
that §2/§3 prose assigns to it: period overlap vs adjacency, the construction
lag boundary, the FULL-posture placement gate, reservation eligibility, the
duplicate-component guard, the withdrawal referential gate, the committed-blend
dump guard, commit-time volume re-check, the evaporation-reading consistency
rule, and logical-clock monotonicity.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    DAYS_PER_MONTH,
    DEFAULT_CLOCK_ISO,
    LIMIT_MAX,
    add_blend_component_payload,
    add_component,
    create_active_label,
    create_assessment_payload,
    create_barrel_payload,
    create_blend_batch,
    create_bonded_report_payload,
    create_label_payload,
    create_commissioned_rickhouse,
    create_committed_batch,
    create_expansion_project_payload,
    create_filed_report,
    create_program,
    create_report,
    create_reservation,
    create_reservation_payload,
    create_validated_batch,
    dump_barrel,
    fill_barrels_on_slots,
    fill_mature_barrel,
    fill_placed_barrel,
    get_barrel_fresh,
    get_blend_batch_fresh,
    get_program_fresh,
    get_success_data,
    iso_plus_days,
    record_evaporation_reading,
    set_clock,
    set_clock_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_report_period_overlap_rejected_adjacency_allowed(api, bonded_preparer_headers):
    """PRD §3.7: "A new period may not overlap any existing report whose state
    is not `REJECTED`; an overlap is rejected with `ERR_REPORT_PERIOD_OVERLAP`
    (HTTP 409), while adjacency — one report's `period_start` equaling
    another's `period_end` — is allowed."
    PRD §3.7: "The report is created `OPEN`."

    Design: Corner/errors/report_period_overlap_rejected_adjacency_allowed
    """
    set_clock(DEFAULT_CLOCK_ISO)
    first = create_report("2028-01-01T00:00:00Z", "2028-07-01T00:00:00Z")
    assert first["state"] == "OPEN"

    # Interior overlap: [2028-06-01, 2029-01-01) intersects [2028-01-01, 2028-07-01).
    resp = api.create_bonded_report(
        create_bonded_report_payload("2028-06-01T00:00:00Z", "2029-01-01T00:00:00Z"),
        bonded_preparer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

    # Adjacency: the new period starts exactly at the first period's end.
    adjacent = validate_success(
        api.create_bonded_report(
            create_bonded_report_payload("2028-07-01T00:00:00Z", "2029-01-01T00:00:00Z"),
            bonded_preparer_headers,
        ),
        expected_status=201,
    )
    assert adjacent["state"] == "OPEN"
    assert adjacent["period_start"].startswith("2028-07-01")
    assert adjacent["id"] != first["id"]


def test_commission_before_lag_rejected_at_boundary(
    api, distillery_planner_headers, operations_director_headers,
):
    """PRD §3.1: "The same director commissions an `APPROVED` project — but
    only once the construction lag has fully elapsed: the current logical clock
    must have reached `approved_at` plus `construction_lag_months` times thirty
    days, and an early attempt is rejected with
    `ERR_CONSTRUCTION_LAG_NOT_ELAPSED` (HTTP 409)."
    PRD §2.4: "Calendar arithmetic is uniform by design: every month is 30 days
    and every year is 365 days."

    Design: Corner/errors/commission_before_lag_rejected_at_boundary
    """
    set_clock(DEFAULT_CLOCK_ISO)
    project = get_success_data(
        api.create_expansion_project(
            create_expansion_project_payload(
                name="RH-R2", region_code="TN", construction_lag_months=24,
            ),
            distillery_planner_headers,
        )
    )
    approved = get_success_data(
        api.approve_expansion_project(project["id"], operations_director_headers)
    )
    # 24 months x 30 days = 720 days after approval is the boundary instant.
    commissionable_iso = iso_plus_days(approved["approved_at"], 24 * DAYS_PER_MONTH)
    one_day_early_iso = iso_plus_days(approved["approved_at"], 24 * DAYS_PER_MONTH - 1)

    set_clock(one_day_early_iso)
    validate_error(
        api.commission_expansion_project(project["id"], operations_director_headers),
        ApiErrorId.ERR_CONSTRUCTION_LAG_NOT_ELAPSED,
    )

    set_clock(commissionable_iso)
    commissioned = validate_success(
        api.commission_expansion_project(project["id"], operations_director_headers)
    )
    assert commissioned["state"] == "COMMISSIONED", (
        "the commission succeeds at exactly approved_at + lag x 30 days"
    )


def test_fill_into_full_rickhouse_rejected(api, warehouse_manager_headers):
    """PRD §3.2: "The destination slot's rickhouse must be `OPERATING`: a house
    still `PLANNED` or already `FULL` rejects the placement with
    `ERR_RICKHOUSE_NOT_OPERATING` (HTTP 409)."
    PRD §3.2: "Once commissioned, the posture is `FULL` the moment
    `occupied_slots` reaches `total_slots` — equality is the trigger, so a
    house one slot short of capacity remains `OPERATING` — and it returns to
    `OPERATING` whenever occupancy drops back below capacity."

    Design: Corner/errors/fill_into_full_rickhouse_rejected
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=2, positions_per_row=2, name="RH-R3",
    )
    fill_barrels_on_slots(
        ctx["slots"], fill_volume_liters=100.0, min_maturation_months=12,
    )
    rickhouse = get_success_data(api.get_rickhouse(ctx["rickhouse"]["id"], warehouse_manager_headers))
    assert rickhouse["occupied_slots"] == 4 and rickhouse["total_slots"] == 4
    assert rickhouse["posture"] == "FULL", "Setup failed: the house should be FULL"

    # The target slot is also occupied, but gate 6 (rickhouse posture) masks
    # gate 8 (slot-occupancy overlap) per PRD §2.10's "An earlier gate masks
    # every later one."
    resp = api.create_barrel(
        create_barrel_payload(
            ctx["slots"][0]["id"], fill_volume_liters=100.0, min_maturation_months=12,
        ),
        warehouse_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RICKHOUSE_NOT_OPERATING)

    barrels, meta = validate_paginated(
        api.list_barrels(warehouse_manager_headers, params={"limit": LIMIT_MAX})
    )
    assert meta["total_count"] == 4 and len(barrels) == 4, "no fifth barrel is created"


def test_reserve_non_mature_barrel_rejected(api, program_director_headers):
    """PRD §3.6: "A barrel is a candidate when it is `BONDED` in custody,
    `MATURE_ELIGIBLE` in maturation, of the program's `spirit_type`, free of
    any reservation in `ACTIVE` or `CONSUMED`, free of any component on a
    `COMMITTED` blend batch, and carrying a latest quality score of at least
    the program's `min_quality_score`."
    PRD §3.6: "only then does a barrel failing the eligibility predicate above
    draw `ERR_BARREL_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/errors/reserve_non_mature_barrel_rejected
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-R4",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"], min_maturation_months=48)  # AGING
    program = create_program(
        name="Early Pick", min_quality_score=0,
        required_barrel_count=1, reservation_window_days=45,
    )

    program_now = get_program_fresh(program["id"])
    resp = api.create_reservation(
        program["id"],
        create_reservation_payload(barrel["id"], program_now["version"]),
        program_director_headers,
    )
    validate_error(resp, ApiErrorId.ERR_BARREL_NOT_ELIGIBLE)

    program_after = get_program_fresh(program["id"])
    assert program_after["available_slots"] == 1, (
        "the rejected reservation leaves the quota untouched"
    )


def test_same_barrel_twice_in_batch_rejected(api, master_blender_headers):
    """PRD §3.5: "Two constraints guard composition: the same barrel may not
    appear twice in one batch — a repeat is rejected with
    `ERR_DUPLICATE_BLEND_COMPONENT` (HTTP 409) — and the draw may not exceed
    the barrel's current ledger volume, else `ERR_INSUFFICIENT_VOLUME`
    (HTTP 422); the volume check is made when the component is added and made
    again at commit."

    Design: Corner/errors/same_barrel_twice_in_batch_rejected
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-R5",
    )
    barrel = fill_mature_barrel(ctx["slots"][0]["id"])
    label = get_success_data(
        api.create_label(
            create_label_payload(name="Dup Guard", age_statement_years=1, spirit_type="BOURBON"),
            master_blender_headers,
        )
    )
    batch = create_blend_batch(label["id"], "2030-09-01T00:00:00Z")
    add_component(batch["id"], barrel["id"], 10.0)

    # Second add of the same barrel with a fresh, correct OCC version.
    fresh = get_blend_batch_fresh(batch["id"])
    resp = api.add_blend_component(
        batch["id"],
        add_blend_component_payload(barrel["id"], 5.0, fresh["version"]),
        master_blender_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BLEND_COMPONENT)

    components, _meta = validate_paginated(
        api.list_blend_components(batch["id"], master_blender_headers)
    )
    assert len(components) == 1, "the batch still carries exactly one component"


def test_withdraw_with_active_reservation_after_report_filed(api, warehouse_manager_headers):
    """PRD §3.4: "Compliance: there must exist a bonded-period report in
    `FILED` or `ACCEPTED` state whose period covers the current instant —
    `period_start` at or before now and `period_end` at or after now —
    otherwise the withdrawal is rejected with `ERR_COVERING_REPORT_NOT_FILED`
    (HTTP 409)."
    PRD §3.4: "Referential: no reservation on this barrel may be `ACTIVE`, else
    `ERR_BARREL_RESERVED` (HTTP 409)."

    Design: Corner/errors/withdraw_with_active_reservation_after_report_filed
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-R6",
    )
    barrel = fill_mature_barrel(ctx["slots"][0]["id"])  # MATURE_ELIGIBLE at fill
    # FILED report whose period_end equals the coming clock still covers the
    # current instant ("period_end at or after now"), so the compliance gate
    # is satisfied and the referential gate is the one that fires.
    report = create_filed_report(
        "2028-08-01T00:00:00Z", "2028-12-01T00:00:00Z",
        at_clock="2028-12-01T00:00:00Z", preparer_user_id="prep-1",
    )
    assert report["state"] == "FILED"

    program = create_program(
        name="Late Pick", min_quality_score=0,
        required_barrel_count=1, reservation_window_days=45,
    )
    reservation = create_reservation(program["id"], barrel["id"])
    assert reservation["state"] == "ACTIVE"  # expires 45 days out, still live

    dumped = dump_barrel(barrel["id"])
    assert dumped["maturation_status"] == "DUMPED"

    resp = api.withdraw_barrel(barrel["id"], warehouse_manager_headers)
    validate_error(resp, ApiErrorId.ERR_BARREL_RESERVED)

    after = get_barrel_fresh(barrel["id"])
    assert after["custody_status"] == "BONDED", "the rejected withdrawal moves nothing"


def test_dump_barrel_in_committed_blend_rejected(api, warehouse_manager_headers):
    """PRD §3.4: "A `WarehouseManager` may dump a barrel in either `AGING` or
    `MATURE_ELIGIBLE`; from both states the destination is `DUMPED`, and both
    paths enforce the same referential guard: if any blend component naming
    this barrel belongs to a `COMMITTED` batch, the dump is rejected with
    `ERR_BARREL_IN_COMMITTED_BLEND` (HTTP 409)."

    Design: Corner/errors/dump_barrel_in_committed_blend_rejected
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-R7",
    )
    barrel = fill_mature_barrel(ctx["slots"][0]["id"])
    label = create_active_label(name="Committed Guard", age_statement_years=1, spirit_type="BOURBON")
    batch = create_committed_batch(label["id"], barrel["id"], 10.0)
    assert batch["state"] == "COMMITTED"

    resp = api.dump_barrel(barrel["id"], warehouse_manager_headers)
    validate_error(resp, ApiErrorId.ERR_BARREL_IN_COMMITTED_BLEND)

    after = get_barrel_fresh(barrel["id"])
    assert after["maturation_status"] != "DUMPED", (
        "the referential guard leaves the barrel's maturation unchanged"
    )


def test_commit_rechecks_volume_after_reading(api, master_blender_headers):
    """PRD §3.5: "From `VALIDATED`, the commit re-checks that the label is
    still `ACTIVE`, re-checks every component's age at the
    `scheduled_bottling_date` against the same inclusive obligation (a
    component that has fallen under-age fails with
    `ERR_AGE_STATEMENT_VIOLATION`), and re-checks each `drawn_volume_liters`
    against its barrel's current ledger volume (`ERR_INSUFFICIENT_VOLUME`)."
    PRD §3.3: "an `EVAPORATION_READING` assessment resets the running volume
    outright to its `measured_volume_liters` — an authoritative measurement of
    what is actually in the barrel, not a delta".

    Design: Corner/errors/commit_rechecks_volume_after_reading
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-R8",
    )
    barrel = fill_mature_barrel(ctx["slots"][0]["id"])  # 200.0 L ledger at fill
    label = create_active_label(name="Recheck", age_statement_years=1, spirit_type="BOURBON")
    batch = create_validated_batch(label["id"], barrel["id"], 150.0)
    assert batch["state"] == "VALIDATED"

    # The draw was legal against the 200.00 ledger at add time; the intervening
    # reading resets the ledger to 100.00, so 150.0 no longer fits at commit.
    set_clock("2028-10-01T00:00:00Z")
    record_evaporation_reading(barrel["id"], 100.0)
    assert get_barrel_fresh(barrel["id"])["current_volume_ledger_liters"] == pytest.approx(100.00, abs=0.01)

    resp = api.commit_blend_batch(batch["id"], master_blender_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VOLUME)

    batch_after = get_blend_batch_fresh(batch["id"])
    assert batch_after["state"] == "VALIDATED", "the failed commit changes nothing"
    barrel_after = get_barrel_fresh(barrel["id"])
    assert barrel_after["current_volume_ledger_liters"] == pytest.approx(100.00, abs=0.01), (
        "no partial deduction: the ledger still shows the reading's 100.00"
    )


def test_reading_above_ledger_rejected(api, warehouse_manager_headers):
    """PRD §3.3: "An evaporation reading requires `measured_volume_liters`, the
    authoritative gauge of what remains; it may not exceed the barrel's current
    ledger volume — a reading that does is rejected with
    `ERR_ASSESSMENT_VOLUME_INCONSISTENT` (HTTP 422)."

    Design: Corner/errors/reading_above_ledger_rejected
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-R9",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"])  # 200.0 L ledger
    set_clock("2029-01-01T00:00:00Z")

    resp = api.create_barrel_assessment(
        barrel["id"],
        create_assessment_payload("EVAPORATION_READING", measured_volume_liters=250.0),
        warehouse_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_VOLUME_INCONSISTENT)

    after = get_barrel_fresh(barrel["id"])
    assert after["current_volume_ledger_liters"] == pytest.approx(200.00, abs=0.01), (
        "the rejected reading never touches the ledger"
    )


def test_clock_cannot_move_backwards(api, platform_admin_headers):
    """PRD §2.4: "The clock is monotonic non-decreasing: a `PlatformAdmin`
    advances it through the clock-setting capability by supplying `to_iso8601`,
    and an attempt to set it earlier than the current instant is rejected with
    `ERR_CLOCK_REGRESSION` (HTTP 422)."
    PRD §2.4: "Before any clock call the server's clock reads exactly
    2026-09-01T00:00:00Z, and it never falls back to wall-clock time."
    PRD §2.4: "A successful set responds with the new `current_utc` and
    immediately re-evaluates every lazy auto-transition in the system."

    Design: Corner/errors/clock_cannot_move_backwards
    """
    set_clock(DEFAULT_CLOCK_ISO)  # 2026-09-01T00:00:00Z

    resp = api.set_clock(set_clock_payload("2026-08-31T00:00:00Z"), platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)

    # Probe: an instant later than the rejected target but still earlier than
    # the standing clock must also be rejected — proving the failed set left
    # the clock at 2026-09-01 rather than moving it to 2026-08-31.
    probe = api.set_clock(set_clock_payload("2026-08-31T12:00:00Z"), platform_admin_headers)
    validate_error(probe, ApiErrorId.ERR_CLOCK_REGRESSION)

    # An equal instant is not "earlier than the current instant", so it is
    # accepted and reports the standing clock.
    ok = validate_success(
        api.set_clock(set_clock_payload(DEFAULT_CLOCK_ISO), platform_admin_headers)
    )
    assert ok["current_utc"].startswith("2026-09-01"), (
        f"the clock still stands at the startup instant, got {ok['current_utc']!r}"
    )
