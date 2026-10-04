"""Difficulty-design translations: parallel state dimensions, the blend-batch
revision cycle, and cross-entity state gates.

Barrels carry two independent state dimensions (maturation x custody) joined
only at withdrawal (PRD §3.3/§3.4); blend batches cycle VALIDATED -> PROPOSED
before commit (PRD §3.5); blend validation depends on the label's state and
withdrawal depends on the bonded-report pipeline's state.
"""
from test_helpers import (
    ApiErrorId,
    DAYS_PER_MONTH,
    STANDARD_FILL_ISO,
    add_component,
    create_active_label,
    create_batch_with_component,
    create_blend_batch,
    create_commissioned_rickhouse,
    create_label_payload,
    create_report,
    dump_barrel,
    fill_mature_barrel,
    fill_placed_barrel,
    get_barrel_fresh,
    get_blend_batch_fresh,
    get_success_data,
    iso_plus_days,
    reconcile_report,
    set_clock,
    validate_error,
    validate_success,
)


def test_barrel_maturation_and_custody_dimensions_evolve_independently(api, warehouse_manager_headers):
    """PRD §3.3: "Every barrel carries two independent state dimensions." and
    "The two evolve independently with a single join gate — withdrawal demands
    the barrel be `DUMPED` first (§3.4)."
    PRD §3.3: "When the current logical clock reaches the barrel's `fill_date`
    plus `min_maturation_months` times thirty days, the barrel becomes
    `MATURE_ELIGIBLE`"
    PRD §3.4: "attempting withdrawal before the dump fails the join gate with
    `ERR_INVALID_STATE_TRANSITION` (HTTP 409)"

    Design: Difficulty/non_linear_state_machine/barrel_parallel_maturation_and_custody_dimensions
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-PD",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"])  # min_maturation_months 48
    # Creation advances FILLED -> AGING within the same request while custody
    # begins and stays BONDED (PRD §3.2).
    assert barrel["maturation_status"] == "AGING"
    assert barrel["custody_status"] == "BONDED"

    # fill_date 2028-09-01 + 48 x 30 = 1440 days == 2032-08-11T00:00:00Z.
    set_clock(iso_plus_days(STANDARD_FILL_ISO, 48 * DAYS_PER_MONTH))
    matured = validate_success(api.get_barrel(barrel["id"], warehouse_manager_headers))
    assert matured["maturation_status"] == "MATURE_ELIGIBLE"
    assert matured["custody_status"] == "BONDED"

    # Join gate: custody cannot leave BONDED while maturation is not DUMPED.
    validate_error(
        api.withdraw_barrel(barrel["id"], warehouse_manager_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )

    # Dump moves only the maturation dimension.
    dumped = validate_success(api.dump_barrel(barrel["id"], warehouse_manager_headers))
    assert dumped["maturation_status"] == "DUMPED"
    assert dumped["custody_status"] == "BONDED"


def test_blend_batch_revision_cycle_commits(api, master_blender_headers):
    """PRD §3.5: "Validation moves the batch `PROPOSED` → `VALIDATED`."
    PRD §3.5: "Revising sends it `VALIDATED` → `PROPOSED`, increments the
    `version`, and leaves its components in place — retained and editable again
    under the proposal-time rules above."
    PRD §3.5: "The batch freezes `final_blend_volume_liters` as the sum of its
    components' drawn volumes, stamps `committed_at`, moves to `COMMITTED`, and
    increments its own `version`."
    PRD §3.5: "Committing then draws down the barrels: each component's barrel
    ledger loses its `drawn_volume_liters` — a commit-draw ledger event stamped
    at the `committed_at` instant — and each such barrel's `version` increments."

    Design: Difficulty/non_linear_state_machine/blend_batch_revision_cycle_commits
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-BC",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"], min_maturation_months=24)
    label = create_active_label(name="Old Cycler", age_statement_years=2, spirit_type="BOURBON")

    set_clock("2030-08-25T00:00:00Z")
    batch = create_blend_batch(label["id"], "2030-09-01T00:00:00Z")
    v_create = batch["version"]

    add_component(batch["id"], barrel["id"], 120.0)
    after_add = get_blend_batch_fresh(batch["id"])
    assert after_add["version"] == v_create + 1, "component add increments the batch version (PRD §2.7)"

    validated = validate_success(api.validate_blend_batch(batch["id"], master_blender_headers))
    assert validated["state"] == "VALIDATED"
    assert validated["version"] == v_create + 2

    revised = validate_success(api.revise_blend_batch(batch["id"], master_blender_headers))
    assert revised["state"] == "PROPOSED"
    assert revised["version"] == v_create + 3

    revalidated = validate_success(api.validate_blend_batch(batch["id"], master_blender_headers))
    assert revalidated["state"] == "VALIDATED"
    assert revalidated["version"] == v_create + 4

    # Barrel age at the 2030-09-01 bottling is exactly 730 days = 2 x 365-day
    # years, meeting the label's age_statement_years 2 (PRD §3.5 inclusive >=).
    committed = validate_success(api.commit_blend_batch(batch["id"], master_blender_headers))
    assert committed["state"] == "COMMITTED"
    assert committed["version"] == v_create + 5
    assert committed["final_blend_volume_liters"] == 120.00
    assert committed["committed_at"] is not None

    barrel_after = get_barrel_fresh(barrel["id"])
    assert barrel_after["current_volume_ledger_liters"] == 80.00, (
        "commit draw deducts immediately: 200.00 - 120.00"
    )


def test_blend_validate_requires_label_active(api, master_blender_headers):
    """PRD §3.5: "The batch's label must be `ACTIVE` — a cross-entity gate that
    fails with `ERR_LABEL_NOT_ACTIVE` (HTTP 409) and is evaluated before the
    age-statement compliance check."

    Design: Difficulty/cross_entity_state_dependency/blend_validate_requires_label_active
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-LA",
    )
    barrel = fill_mature_barrel(ctx["slots"][0]["id"])
    # Label registered but never activated.
    label = get_success_data(
        api.create_label(
            create_label_payload(name="Young Buck", age_statement_years=1, spirit_type="BOURBON"),
            master_blender_headers,
        )
    )
    assert label["state"] == "REGISTERED"

    # Age obligation would pass (2 years at bottling >= statement 1), so the
    # label's state is the only failing gate.
    batch, _component = create_batch_with_component(
        label["id"], barrel["id"], 10.0, scheduled_bottling_date="2030-09-01T00:00:00Z"
    )
    validate_error(
        api.validate_blend_batch(batch["id"], master_blender_headers),
        ApiErrorId.ERR_LABEL_NOT_ACTIVE,
    )
    after = get_blend_batch_fresh(batch["id"])
    assert after["state"] == "PROPOSED", "failed validation leaves the batch unchanged"


def test_withdraw_requires_covering_report_filed(api, warehouse_manager_headers):
    """PRD §3.4: "Compliance: there must exist a bonded-period report in
    `FILED` or `ACCEPTED` state whose period covers the current instant —
    `period_start` at or before now and `period_end` at or after now —
    otherwise the withdrawal is rejected with `ERR_COVERING_REPORT_NOT_FILED`
    (HTTP 409)."
    PRD §3.7: "Filing moves a report `RECONCILED` → `FILED` under the same
    `BondedPreparer` role"

    Design: Difficulty/cross_entity_state_dependency/withdraw_requires_covering_report_filed
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-CR",
    )
    barrel = fill_mature_barrel(ctx["slots"][0]["id"])

    set_clock("2028-09-02T00:00:00Z")
    dumped = validate_success(api.dump_barrel(barrel["id"], warehouse_manager_headers))
    assert dumped["maturation_status"] == "DUMPED"

    # The report covers the withdrawal instant but stops at RECONCILED.
    report = create_report("2028-08-01T00:00:00Z", "2028-12-01T00:00:00Z")
    reconciled = reconcile_report(report["id"], at_clock="2028-12-01T00:00:00Z")
    assert reconciled["state"] == "RECONCILED"

    # Every barrel-local gate passes (DUMPED, BONDED, unreserved); only the
    # cross-entity covering-report rule fails because RECONCILED is neither
    # FILED nor ACCEPTED.
    validate_error(
        api.withdraw_barrel(barrel["id"], warehouse_manager_headers),
        ApiErrorId.ERR_COVERING_REPORT_NOT_FILED,
    )
    after = get_barrel_fresh(barrel["id"])
    assert after["custody_status"] == "BONDED", "rejected withdrawal leaves custody unchanged"
