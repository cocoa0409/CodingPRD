"""Computed reads, terminal workflow endpoints and their observable side effects."""

from test_helpers import (
    ApiErrorId,
    CAP_SOURCE_DEMAND,
    FEED_RECONCILED,
    FISH_QUARANTINED,
    FISH_RELEASED,
    KIOSK_OPERATING,
    KIOSK_SUSPENDED,
    LICENSE_ACTIVE,
    LICENSE_SUSPENDED,
    PACK_ON_SHELF,
    PACK_SOLD_OUT,
    PLAN_LOCKED,
    PLAN_RECONCILED,
    POSTURE_CLEAR,
    QUARANTINE_REASON_COLD_CHAIN_BREACH,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    add_cold_chain_readings,
    add_pack_lot,
    add_received_fish_lot,
    add_submitted_audit,
    add_submitted_feed,
    assert_close,
    assert_risk_summary,
    base_world,
    feed_line,
    packed_world,
    pos_sales_feed_payload,
    release_rationale_payload,
    shelf_ready_world,
    suspension_payload,
    validate_error,
    validate_success,
)


def test_kiosk_risk_summary_returns_the_full_decomposition(api):
    """The computed read explains every term behind the posture band.

    "A computed read returns the kiosk's current risk decomposition as an object
    with `kiosk_id`, the per-severity counts of findings still carrying weight as
    `minor_open`, `major_open` and `critical_open`, the `approved_variance_count`,
    the `quarantined_lot_count`, the `clean_audit_credit` that was subtracted,
    `raw_risk_points` as the total before clamping, `risk_points` as the clamped
    total, `sanitation_posture` as the band it lands in, and
    `posture_forced_by_critical`."

    Design: Corner/endpoints/kiosk_risk_summary_returns_risk_decomposition
    """
    world = base_world()
    add_submitted_audit(
        world,
        severities=(SEVERITY_MINOR, SEVERITY_MAJOR),
        codes=["FS-LABEL-WEAR", "FS-SANITISER-CONCENTRATION"],
    )

    summary = validate_success(
        api.get_kiosk_risk_summary(world["kiosk_id"], world["ops_headers"])
    )
    assert_risk_summary(summary)

    assert summary["kiosk_id"] == world["kiosk_id"]
    assert summary["minor_open"] == 1
    assert summary["major_open"] == 1
    assert summary["critical_open"] == 0
    assert summary["approved_variance_count"] == 0
    assert summary["quarantined_lot_count"] == 0
    assert summary["clean_audit_credit"] == 0
    assert summary["raw_risk_points"] == 5
    assert summary["risk_points"] == 5
    assert summary["sanitation_posture"] == POSTURE_CLEAR
    assert summary["posture_forced_by_critical"] is False

    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert kiosk["risk_points"] == 5
    assert kiosk["sanitation_posture"] == POSTURE_CLEAR


def test_locking_then_reconciling_a_plan_closes_the_day(api):
    """Reconciliation needs every feed for the date terminal and then sets the variance.

    "`LOCKED → RECONCILED` is a franchisor-operations act and requires every
    point-of-sale feed of the kiosk's host store whose `business_date` equals the
    plan's `production_date` to have reached a terminal state, either
    `RECONCILED` or `REJECTED`; a feed still `SUBMITTED` blocks the plan with
    `ERR_PERIOD_FEED_NOT_RECONCILED`."

    Design: Corner/endpoints/production_plan_lock_then_reconcile_closes_the_day
    """
    world = shelf_ready_world()
    add_pack_lot(world, world["rice_batch_id"], world["fish_lot_id"])

    locked = validate_success(
        api.lock_production_plan(world["plan_id"], world["chef_headers"])
    )
    assert locked["status"] == PLAN_LOCKED
    assert locked["binding_cap_source"] == CAP_SOURCE_DEMAND
    assert locked["forecast_variance_pct"] is None

    feed = add_submitted_feed(world)
    validate_error(
        api.reconcile_production_plan(world["plan_id"], world["ops_headers"]),
        ApiErrorId.ERR_PERIOD_FEED_NOT_RECONCILED.value,
        422,
    )

    validate_success(api.reconcile_pos_sales_feed(feed["id"], world["ops_headers"]))
    reconciled = validate_success(
        api.reconcile_production_plan(world["plan_id"], world["ops_headers"])
    )
    assert reconciled["status"] == PLAN_RECONCILED
    assert reconciled["actual_pack_count"] == 160
    assert_close(reconciled["forecast_variance_pct"], -1.23, places=2)

    validate_error(
        api.reconcile_production_plan(world["plan_id"], world["ops_headers"]),
        ApiErrorId.ERR_PLAN_INVALID_STATE.value,
        409,
    )


def test_feed_lines_drive_the_pack_lot_sold_count(api):
    """Reconciled register lines are the only thing that sells packs.

    "Reconciliation then sets `reconciled_unit_total` to the sum of `units_sold`
    across the lines, increments each referenced lot's `sold_count` and decrements
    its `unsold_count` by the same amount, moves any lot whose `unsold_count`
    reaches zero to `SOLD_OUT`."

    Design: Corner/endpoints/pos_feed_line_links_pack_lot_and_updates_sold_count
    """
    world = packed_world()

    first_feed = validate_success(
        api.create_pos_sales_feed(
            pos_sales_feed_payload(
                world["host_store_id"], lines=[feed_line(world["pack_lot_id"], 40)]
            ),
            world["manager_headers"],
        ),
        201,
    )
    assert first_feed["reconciled_unit_total"] == 0

    reconciled = validate_success(
        api.reconcile_pos_sales_feed(first_feed["id"], world["ops_headers"])
    )
    assert reconciled["status"] == FEED_RECONCILED
    assert reconciled["reconciled_unit_total"] == 40

    lot = validate_success(api.get_pack_lot(world["pack_lot_id"], world["ops_headers"]))
    assert lot["sold_count"] == 40
    assert lot["unsold_count"] == 120
    assert lot["status"] == PACK_ON_SHELF

    second_feed = validate_success(
        api.create_pos_sales_feed(
            pos_sales_feed_payload(
                world["host_store_id"],
                business_date="2026-08-04",
                lines=[feed_line(world["pack_lot_id"], 120, was_markdown=True)],
            ),
            world["manager_headers"],
        ),
        201,
    )
    validate_success(api.reconcile_pos_sales_feed(second_feed["id"], world["ops_headers"]))

    sold_out = validate_success(
        api.get_pack_lot(world["pack_lot_id"], world["ops_headers"])
    )
    assert sold_out["sold_count"] == 160
    assert sold_out["unsold_count"] == 0
    assert sold_out["status"] == PACK_SOLD_OUT


def test_quarantined_lot_needs_a_rationale_to_go_back_into_production(api):
    """A breached lot may only be released on the record.

    "Releasing a lot out of `QUARANTINED` requires the same parasite-destruction
    condition plus an explicit `release_rationale` in the body — the auditor must
    say on the record why a breached lot is going back into production; without
    that rationale the release is refused with
    `ERR_COLD_CHAIN_BREACH_BLOCKS_RELEASE`."

    Design: Corner/endpoints/fish_lot_release_with_rationale_overrides_breach_block
    """
    world = base_world()
    lot = add_received_fish_lot(
        world, received_at="2026-08-03T06:00:00Z", receiving_temp_c=2.0
    )
    add_cold_chain_readings(
        world,
        lot["id"],
        [
            ("2026-08-03T08:00:00Z", 2.0),
            ("2026-08-03T09:00:00Z", 6.0),
            ("2026-08-03T09:20:00Z", 6.0),
        ],
    )

    quarantined = validate_success(api.get_fish_lot(lot["id"], world["ops_headers"]))
    assert quarantined["status"] == FISH_QUARANTINED
    assert quarantined["quarantine_reason"] == QUARANTINE_REASON_COLD_CHAIN_BREACH
    assert quarantined["cold_chain_breach_minutes"] == 50
    breached_kiosk = validate_success(
        api.get_kiosk(world["kiosk_id"], world["ops_headers"])
    )
    assert breached_kiosk["risk_points"] == 6

    validate_error(
        api.release_fish_lot(lot["id"], world["auditor_headers"]),
        ApiErrorId.ERR_COLD_CHAIN_BREACH_BLOCKS_RELEASE.value,
        422,
    )

    released = validate_success(
        api.release_fish_lot(
            lot["id"], world["auditor_headers"], release_rationale_payload()
        )
    )
    assert released["status"] == FISH_RELEASED
    assert released["quarantine_reason"] is None
    assert_close(released["remaining_kg"], 12.0)
    assert released["cold_chain_breach_minutes"] == 50

    cleared_kiosk = validate_success(
        api.get_kiosk(world["kiosk_id"], world["ops_headers"])
    )
    assert cleared_kiosk["risk_points"] == 0


def test_agreement_suspension_and_reinstatement_round_trip(api):
    """Suspension takes the kiosks down with it; reinstatement does not revive them.

    "Coming back the other way — `SUSPENDED → ACTIVE` … clears `suspension_reason`
    and increments `version`, but deliberately does **not** revive the kiosks: each
    suspended kiosk needs its own reinstatement."

    Design: Corner/endpoints/license_agreement_suspend_and_reinstate_round_trip
    """
    world = base_world()

    suspended = validate_success(
        api.suspend_license_agreement(
            world["agreement_id"], suspension_payload(), world["ops_headers"]
        )
    )
    assert suspended["status"] == LICENSE_SUSPENDED
    assert suspended["suspension_reason"] == "HOST_CHAIN_REMODEL_PAUSE"
    assert suspended["active_kiosk_count"] == 0

    down = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert down["operational_state"] == KIOSK_SUSPENDED

    reinstated = validate_success(
        api.reinstate_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert reinstated["status"] == LICENSE_ACTIVE
    assert reinstated["suspension_reason"] is None
    assert reinstated["active_kiosk_count"] == 0

    still_down = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert still_down["operational_state"] == KIOSK_SUSPENDED

    back_up = validate_success(
        api.reinstate_kiosk(world["kiosk_id"], world["ops_headers"])
    )
    assert back_up["operational_state"] == KIOSK_OPERATING
    assert back_up["suspension_reason"] is None

    final_agreement = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert final_agreement["active_kiosk_count"] == 1
