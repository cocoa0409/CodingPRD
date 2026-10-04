"""Run execution: start/complete/abort/release lifecycle effects, the
depth-3 completion cascade, batch birth fields, capacity ledger, and
read-your-writes visibility (PRD sections 2.7, 3.5, 3.7)."""
from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_error, validate_success,
    run_transition_payload,
    move_line_operational,
    set_clock, setup_production_scenario, setup_run_in_progress,
    setup_completed_batch, schedule_run, start_run, complete_run,
    abort_run, release_run, get_run_batch,
    fetch_line, fetch_lot, fetch_run, fetch_batch, fetch_supplier,
    current_line_version,
    assert_finished_goods_batch, assert_batch_expiry_matches_shelf_life,
)

_PLANT = TEST_USERS["plant_manager_headers"]
_QM = TEST_USERS["quality_manager_headers"]


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_run_start_moves_line_to_running(api):
    """PRD section 3.5: "A started run moves the line's `operational_status`
    to `RUNNING`." — the line flips IDLE -> RUNNING as a side effect of the
    run transition, not through a separate operational-transitions call.

    Design: Corner/state_machines/cn_sm_run_start_moves_line_running
    """
    ctx = setup_run_in_progress()
    assert ctx["run"]["status"] == "IN_PROGRESS"
    assert fetch_line(ctx["line"]["id"])["operational_status"] == "RUNNING"


def test_run_completion_creates_batch_with_channel_shelf_life(api):
    """PRD section 3.7: a batch "fixes `quantity_cases` immutably at the
    run's `cases_produced`, copies the run's `unit_cost_cents_per_case`,
    stamps `produced_at` from the logical clock at completion, and computes
    `expiry_date` by adding the channel's shelf life to `produced_at`: ...
    270 days for `RETAIL_FROZEN`". A 100 kg run at the default clock yields
    10 cases, produced 2026-09-01, expiring 2027-05-29, at
    round_half_up(85 x 535 / 10) = 4548 cents per case.

    Design: Corner/state_machines/cn_sm_run_complete_creates_batch_with_channel_shelf_life
    """
    ctx = setup_completed_batch()
    batch = ctx["batch"]
    assert_finished_goods_batch(batch)
    assert batch["quantity_cases"] == 10
    assert batch["channel"] == "RETAIL_FROZEN"
    assert batch["product_id"] == ctx["product"]["id"]
    assert _parse_iso(batch["produced_at"]) == _parse_iso(
        "2026-09-01T00:00:00Z")
    assert _parse_iso(batch["expiry_date"]) == _parse_iso(
        "2027-05-29T00:00:00Z")
    assert_batch_expiry_matches_shelf_life(batch)
    assert batch["derived_status"] == "AVAILABLE"
    assert batch["available_cases"] == 10
    assert batch["reserved_cases"] == 0
    assert batch["written_off_cases"] == 0
    assert batch["unit_cost_cents_per_case"] == 4548
    run = fetch_run(ctx["run"]["id"])
    assert run["consumed_lot_ids"] == [ctx["lot"]["id"]]
    assert run["required_isolate_kg"] == 85


def test_foodservice_batch_expires_after_45_days(api):
    """PRD section 3.7: "computes `expiry_date` by adding the channel's shelf
    life to `produced_at`: 45 days for `FOODSERVICE`" — a FOODSERVICE batch
    produced at the default clock expires 2026-10-16.

    Design: Corner/calculations/cn_calc_expiry_foodservice_45_days
    """
    ctx = setup_completed_batch(channel="FOODSERVICE", actual_quantity_kg=100)
    batch = ctx["batch"]
    assert batch["channel"] == "FOODSERVICE"
    assert_batch_expiry_matches_shelf_life(batch)
    assert _parse_iso(batch["expiry_date"]) == _parse_iso(
        "2026-10-16T00:00:00Z")


def test_run_completion_depletes_lot_and_completes_agreement(api):
    """PRD section 3.2: "When consumption drives a lot's `remaining_kg` to
    zero, the system moves the lot to `DEPLETED`, decrements the supplier's
    `open_lot_count` by one, and re-evaluates agreement completion once more."
    PRD section 3.1: "an `ACTIVE` agreement whose `delivered_volume_kg` has
    reached or passed its `committed_volume_kg` while its `open_lot_count`
    stands at zero moves to `COMPLETED`." An 85 kg lot consumed to zero by a
    100 kg run (required isolate ceil(100 x 0.85) = 85) completes the
    depth-3 chain.

    Design: Difficulty/transitive_cascade/tc_run_completion_depth3
    """
    ctx = setup_completed_batch(
        supplier_overrides={"supplier_code": "SUP-TC-1",
                            "committed_volume_kg": 85},
        lot_overrides={"lot_code": "LOT-TC-1", "quantity_kg": 85},
        line_overrides={"line_code": "LINE-TC-1",
                        "supported_isolate_types": ["PEA"]},
        product_overrides={"product_code": "PROD-TC-1"})
    lot = fetch_lot(ctx["lot"]["id"])
    assert lot["remaining_kg"] == 0
    assert lot["qc_status"] == "DEPLETED"
    supplier = fetch_supplier(ctx["supplier"]["id"])
    assert supplier["agreement_status"] == "COMPLETED"


def test_run_completion_writes_batch_run_and_line_effects(api):
    """PRD section 3.5: "First, eligible lots are consumed in FIFO order
    (§3.2) until the requirement is covered; ... the ordered lot
    identifiers are recorded as the run's `consumed_lot_ids`" and "Finally
    the line drops to `CLEANING`". The 100 kg run consumes exactly the 85 kg
    lot, yields floor(100/10) = 10 cases at round_half_up(85 x 535 / 10) =
    4548 cents per case.

    Design: Difficulty/transitive_cascade/tc_run_completion_depth3
    """
    ctx = setup_completed_batch(
        supplier_overrides={"supplier_code": "SUP-TC-1",
                            "committed_volume_kg": 85},
        lot_overrides={"lot_code": "LOT-TC-1", "quantity_kg": 85},
        line_overrides={"line_code": "LINE-TC-1",
                        "supported_isolate_types": ["PEA"]},
        product_overrides={"product_code": "PROD-TC-1"})
    batch = ctx["batch"]
    assert batch["quantity_cases"] == 10
    assert batch["unit_cost_cents_per_case"] == 4548
    run = fetch_run(ctx["run"]["id"])
    assert run["consumed_lot_ids"] == [ctx["lot"]["id"]]
    assert fetch_line(ctx["line"]["id"])["operational_status"] == "CLEANING"


def test_run_start_rejected_while_line_down(api):
    """PRD section 3.5: "the operational dimension must be `IDLE` or `SETUP`
    — for a dedicated run, stricter still, exactly `IDLE` — with violations
    drawing `ERR_LINE_OPERATIONAL_FORBIDDEN`." A line in DOWN rejects the
    start even though certification is CERTIFIED.

    Design: Corner/validations/cn_val_line_operational_forbidden
    """
    ctx = setup_production_scenario(
        product_overrides={"product_code": "PROD-K-40"})
    run = schedule_run(ctx)
    move_line_operational(ctx["line"]["id"], "DOWN")
    resp = api.production_run_transition(
        run["id"], run_transition_payload("IN_PROGRESS"), _PLANT)
    validate_error(resp, ApiErrorId.ERR_LINE_OPERATIONAL_FORBIDDEN)
    assert fetch_run(run["id"])["status"] == "SCHEDULED"


def test_completion_without_enough_released_isolate_fails(api):
    """PRD section 3.5: "the summed `remaining_kg` across `RELEASED` lots
    whose supplier's isolate type matches the product's must cover the run's
    `required_isolate_kg` — the actual output multiplied by 85 percent and
    rounded up to a whole kilogram — or the completion fails with
    `ERR_INSUFFICIENT_ISOLATE`." With 50 kg released against 85 required, the
    run stays IN_PROGRESS with no partial consumption.

    Design: Corner/validations/cn_val_insufficient_isolate_at_completion
    """
    ctx = setup_run_in_progress(
        lot_overrides={"lot_code": "LOT-K-43", "quantity_kg": 50},
        product_overrides={"product_code": "PROD-K-43"})
    resp = api.production_run_transition(
        ctx["run"]["id"],
        run_transition_payload("COMPLETED", actual_quantity_kg=100),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ISOLATE)
    run = fetch_run(ctx["run"]["id"])
    assert run["status"] == "IN_PROGRESS"
    assert run["consumed_lot_ids"] == []
    assert fetch_lot(ctx["lot"]["id"])["remaining_kg"] == 50


def test_run_create_reserves_planned_capacity_on_line(api):
    """PRD section 3.5: "A successfully scheduled run lands in `SCHEDULED`,
    adds its `planned_quantity_kg` to the line's `reserved_capacity_kg`" — a
    500 kg plan moves the ledger from 0 to 500.

    Design: Difficulty/compensating_invariant/ci_line_capacity_create_abort
    """
    ctx = setup_production_scenario(
        line_overrides={"line_code": "LINE-CI-2"},
        product_overrides={"product_code": "PROD-CI-2"})
    schedule_run(ctx, planned_quantity_kg=500,
                 scheduled_start="2026-09-12T08:00:00Z",
                 scheduled_end="2026-09-12T12:00:00Z")
    assert fetch_line(ctx["line"]["id"])["reserved_capacity_kg"] == 500


def test_run_abort_releases_reserved_capacity(api):
    """PRD section 3.5: "Abortion is available from `SCHEDULED` or
    `IN_PROGRESS` and always releases the run's reserved capacity from the
    line" — after abort the ledger returns to 0, and an abort from SCHEDULED
    leaves the operational dimension at IDLE.

    Design: Difficulty/compensating_invariant/ci_line_capacity_create_abort
    """
    ctx = setup_production_scenario(
        line_overrides={"line_code": "LINE-CI-2"},
        product_overrides={"product_code": "PROD-CI-2"})
    run = schedule_run(ctx, planned_quantity_kg=500,
                       scheduled_start="2026-09-12T08:00:00Z",
                       scheduled_end="2026-09-12T12:00:00Z")
    abort_run(run["id"])
    line = fetch_line(ctx["line"]["id"])
    assert line["reserved_capacity_kg"] == 0
    assert line["operational_status"] == "IDLE"
    assert fetch_run(run["id"])["status"] == "ABORTED"


def test_line_ledger_visible_immediately_on_plain_get(api):
    """PRD section 3.3: "The line also tracks `reserved_capacity_kg`, the
    summed `planned_quantity_kg` of its runs in `SCHEDULED` or `IN_PROGRESS`
    status". PRD section 2.7: "scheduling a run increments the line's
    `version` by one". A plain GET right after creation already shows the
    reservation and the single version advance; after abort it shows zero.

    Design: Corner/cross_cutting_layers/cn_xc_immediate_consistency_line_ledger
    """
    ctx = setup_production_scenario(
        product_overrides={"product_code": "PROD-K-62"})
    version_at_create = ctx["line"]["version"]
    run = schedule_run(ctx)
    line_after_create = fetch_line(ctx["line"]["id"])
    assert line_after_create["reserved_capacity_kg"] == 100
    assert line_after_create["version"] == version_at_create + 1
    abort_run(run["id"])
    assert fetch_line(ctx["line"]["id"])["reserved_capacity_kg"] == 0


def test_completion_response_carries_recomputed_run(api):
    """PRD section 2.2: "operations that create or modify a resource will
    return the created or updated resource object in the data field" — the
    COMPLETED transition's own response carries the recomputed run:
    `cases_produced` 10, `required_isolate_kg` 85, `unit_cost_cents_per_case`
    4548, and the FIFO `consumed_lot_ids` (PRD section 3.5), with no
    follow-up fetch needed.

    Design: Corner/consistency_model/cn_cons_complete_response_carries_full_run
    """
    ctx = setup_run_in_progress()
    resp = api.production_run_transition(
        ctx["run"]["id"],
        run_transition_payload("COMPLETED", actual_quantity_kg=100),
        _PLANT)
    run = validate_success(resp)
    assert run["status"] == "COMPLETED"
    assert run["cases_produced"] == 10
    assert run["required_isolate_kg"] == 85
    assert run["unit_cost_cents_per_case"] == 4548
    assert run["consumed_lot_ids"] == [ctx["lot"]["id"]]


def test_qa_release_lands_released_without_touching_batch(api):
    """PRD section 3.5: "releasing a run (`COMPLETED` → `RELEASED`) marks it
    sellable" — the disposition mutates only the run; the batch keeps its
    full availability and a clear recall flag.

    Design: Corner/endpoints/cn_ep_qa_release_satisfaction
    """
    ctx = setup_completed_batch()
    run = release_run(ctx["run"]["id"])
    assert run["status"] == "RELEASED"
    batch = fetch_batch(ctx["batch"]["id"])
    assert batch["available_cases"] == 10
    assert batch["recall_flag"] is False


def test_plantmanager_cannot_release_run(api):
    """PRD section 2.1: "driving a run to `IN_PROGRESS`, `COMPLETED`, or
    `ABORTED` is reserved to `PlantManager`, while driving it to `RELEASED`
    or `RECALLED` is reserved to `QualityManager`" — a PlantManager targeting
    RELEASED is refused `ERR_UNAUTHORIZED` (403).

    Design: Corner/rbac/cn_rbac_plantmanager_cannot_release_run
    """
    ctx = setup_completed_batch()
    resp = api.production_run_transition(
        ctx["run"]["id"], run_transition_payload("RELEASED"), _PLANT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert fetch_run(ctx["run"]["id"])["status"] == "COMPLETED"
