"""Composite setup fixtures for the seasonal-confection domain.

Every fixture builds its preconditions from an empty database using only
PRD-declared endpoints (the harness restarts the server before every test).
The domain is window-driven, so fixtures drive the logical clock forward
through the same waypoints the PRD §2.5 window chain defines; all waypoints
sit after the clock's startup default (2026-09-01T00:00:00Z) and are ordered
consistently with the default program window dates in factories.py.

Fixture chains provided (see the named wrappers at the bottom):
  setup_program / setup_open_program / setup_locked_program /
  setup_in_production_program / setup_ready_for_allocation /
  setup_allocated_program / setup_on_shelf_program / setup_disposition_program /
  setup_closed_program / setup_warehouse_with_load /
  setup_locked_with_in_progress_run / setup_delivered_shipment /
  setup_heat_claim_under_review

All setup calls use get_success_data() so a broken precondition surfaces as a
clear "Setup step failed" error instead of an assertion tangle.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import TEST_USERS, make_retailer_headers
from .types import ProgramAdvanceTarget

# ===========================================================================
# Logical-clock waypoints (fixture data, ordered to match the default program
# window chain in factories.DEFAULT_PROGRAM_WINDOWS)
# ===========================================================================

CLOCK_BASELINE = "2027-01-05T00:00:00Z"               # before commitment_open_on
CLOCK_WITHIN_COMMITMENT_WINDOW = "2027-01-20T00:00:00Z"  # inside [01-10, 02-15)
CLOCK_AT_COMMITMENT_CLOSE = "2027-02-15T00:00:00Z"    # == commitment_close_on
CLOCK_AT_SHIP_WINDOW_OPEN = "2027-07-15T00:00:00Z"    # == ship_window_open_on
CLOCK_DELIVER_TIME = "2027-08-02T00:00:00Z"           # summer month (8)
CLOCK_AT_ON_SHELF = "2027-09-20T00:00:00Z"            # == on_shelf_on
CLOCK_AT_PULL = "2027-11-15T00:00:00Z"                # == pull_on
CLOCK_PAST_DESTROY_BY = "2028-01-01T00:00:00Z"        # after destroy_by_on

DEFAULT_SHIP_ON = "2027-08-02T00:00:00Z"   # inside both default ship windows
DEFAULT_REPORT_WEEK = "2027-10-04T00:00:00Z"  # a Monday in [on_shelf, pull]

_ADMIN = TEST_USERS["platform_admin_headers"]
_PLANNER = TEST_USERS["production_planner_headers"]
_CM = TEST_USERS["category_manager_headers"]        # cm-alice (proposer)
_CM_B = TEST_USERS["category_manager_b_headers"]    # cm-bob (approver)
_LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
_ADJUSTER = TEST_USERS["claims_adjuster_headers"]

# Stage ordering used by the drive_program_to engine.
_STAGE_ORDER = ["OPEN", "LOCKED", "IN_PRODUCTION", "SHIPPING", "ON_SHELF", "DISPOSITION"]


# ===========================================================================
# Low-level primitives
# ===========================================================================

def set_clock(to_iso8601: str) -> dict:
    """Set the server logical clock (PRD §2.5). Returns {"current_utc": ...}."""
    return get_success_data(api_client.set_logical_clock(to_iso8601, _ADMIN))


def get_program(program_id: str) -> dict:
    return get_success_data(api_client.get_seasonal_program(program_id, _ADMIN))


def advance_program_to(program_id: str, to_state: str) -> dict:
    """OCC-safe advance: re-reads the program version, then advances.

    Returns the updated program. Tests that need to exercise ERR_STALE_VERSION
    call api_client.advance_program directly with a pinned version instead.
    """
    current = get_program(program_id)
    return get_success_data(api_client.advance_program(
        program_id,
        {"to_state": to_state, "expected_program_version": current["version"]},
        _ADMIN,
    ))


def get_warehouse(warehouse_id: str) -> dict:
    return get_success_data(api_client.get_warehouse(warehouse_id, _ADMIN))


def get_commitment(commitment_id: str) -> dict:
    return get_success_data(api_client.get_commitment(commitment_id, _ADMIN))


def get_shipment(shipment_id: str) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, _ADMIN))


def get_heat_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_heat_claim(claim_id, _ADMIN))


def get_production_run(run_id: str) -> dict:
    return get_success_data(api_client.get_production_run(run_id, _ADMIN))


def get_retailer_account(retailer_id: str) -> dict:
    return get_success_data(api_client.get_retailer_account(retailer_id, _ADMIN))


def get_lot_for_run(run_id: str) -> dict:
    """The single InventoryLot created by a completing run (PRD §3.2)."""
    lots = get_success_data(api_client.list_inventory_lots(
        _ADMIN, params={"production_run_id": run_id},
    ))
    assert len(lots) == 1, f"expected exactly one lot for run {run_id}, got {len(lots)}"
    return lots[0]


def get_inventory_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_inventory_lot(lot_id, _ADMIN))


# ===========================================================================
# Simple creators (one POST each)
# ===========================================================================

def create_program(**overrides) -> dict:
    """Create a PLANNING program. Does not touch the logical clock."""
    return get_success_data(api_client.create_seasonal_program(
        factories.create_program_payload(**overrides), _ADMIN,
    ))


def create_retailer(**overrides) -> dict:
    return get_success_data(api_client.create_retailer_account(
        factories.create_retailer_account_payload(**overrides), _ADMIN,
    ))


def create_warehouse(**overrides) -> dict:
    return get_success_data(api_client.create_warehouse(
        factories.create_warehouse_payload(**overrides), _ADMIN,
    ))


def create_product(program_id, **overrides) -> dict:
    """Create a SEASONAL product of the given program."""
    return get_success_data(api_client.create_product(
        factories.create_product_payload(program_id=program_id, **overrides), _ADMIN,
    ))


def create_everyday_product(**overrides) -> dict:
    """Create an EVERYDAY product (null program_id, PRD §3.1)."""
    return get_success_data(api_client.create_product(
        factories.create_everyday_product_payload(**overrides), _ADMIN,
    ))


def create_contract(program_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_commodity_contract(
        factories.create_commodity_contract_payload(program_id=program_id, **overrides),
        _ADMIN,
    ))


def settle_contract(contract_id: str, spot_price_cents_per_unit: int = 95) -> dict:
    return get_success_data(api_client.settle_commodity_contract(
        contract_id,
        factories.settle_contract_payload(spot_price_cents_per_unit),
        _ADMIN,
    ))


# ===========================================================================
# Commitment chain (PRD §3.4)
# ===========================================================================

def create_draft_commitment(program: dict, retailer: dict, product: dict,
                            committed_units: int = 10, **overrides) -> dict:
    """Create a DRAFT commitment as the owning retailer (ownership-threaded).
    Requires the program to be OPEN_FOR_COMMITMENTS. Does not move the clock:
    submission has its own window gate, so callers control the clock."""
    return get_success_data(api_client.create_commitment(
        factories.create_commitment_payload(
            program_id=program["id"], retailer_id=retailer["id"],
            product_id=product["id"], committed_units=committed_units,
            **overrides,
        ),
        make_retailer_headers(retailer["id"]),
    ))


def submit_commitment(commitment: dict, retailer: dict) -> dict:
    """DRAFT -> SUBMITTED. Caller must have parked the clock inside the
    half-open collection window (see create_submitted_commitment)."""
    return get_success_data(api_client.submit_commitment(
        commitment["id"], make_retailer_headers(retailer["id"]),
    ))


def confirm_commitment(commitment: dict, cm_headers=None) -> dict:
    """SUBMITTED -> CONFIRMED by a CategoryManager (PRD §3.4 shelf-cap check)."""
    return get_success_data(api_client.confirm_commitment(
        commitment["id"], cm_headers or _CM,
    ))


def create_submitted_commitment(program: dict, retailer: dict, product: dict,
                                committed_units: int = 10, **overrides) -> dict:
    """Create + submit. Parks the clock inside the collection window first."""
    set_clock(CLOCK_WITHIN_COMMITMENT_WINDOW)
    commitment = create_draft_commitment(
        program, retailer, product, committed_units, **overrides,
    )
    return submit_commitment(commitment, retailer)


def create_confirmed_commitment(program: dict, retailer: dict, product: dict,
                                committed_units: int = 10, **overrides) -> dict:
    """Create + submit + confirm. Parks the clock inside the window first."""
    return confirm_commitment(
        create_submitted_commitment(program, retailer, product, committed_units, **overrides)
    )


def cancel_commitment(commitment: dict, retailer: dict) -> dict:
    """DRAFT/SUBMITTED/CONFIRMED -> CANCELLED by the owning retailer."""
    return get_success_data(api_client.cancel_commitment(
        commitment["id"], make_retailer_headers(retailer["id"]),
    ))


# ===========================================================================
# Production run chain (PRD §3.2, §2.10)
# ===========================================================================

def create_scheduled_run(product: dict, program: dict = None,
                         planned_units: int = 10, **overrides) -> dict:
    """Create a SCHEDULED run. program must be given iff the product is
    SEASONAL; pass program=None for everyday runs."""
    program_id = program["id"] if program else None
    return get_success_data(api_client.create_production_run(
        factories.create_production_run_payload(
            product_id=product["id"], program_id=program_id,
            planned_units=planned_units, **overrides,
        ),
        _PLANNER,
    ))


def start_run(run: dict) -> dict:
    """SCHEDULED -> IN_PROGRESS (seasonal runs need program LOCKED/IN_PRODUCTION)."""
    return get_success_data(api_client.start_production_run(run["id"], _PLANNER))


def complete_run(run: dict, warehouse: dict, produced_units: int) -> dict:
    """IN_PROGRESS -> COMPLETE; creates the run's InventoryLot at the warehouse."""
    return get_success_data(api_client.complete_production_run(
        run["id"],
        factories.complete_run_payload(warehouse_id=warehouse["id"],
                                       produced_units=produced_units),
        _PLANNER,
    ))


def cancel_run(run: dict) -> dict:
    """SCHEDULED -> CANCELLED; drops the run from overlap/changeover checks."""
    return get_success_data(api_client.cancel_production_run(run["id"], _PLANNER))


# ===========================================================================
# Shipment chain (PRD §3.6)
# ===========================================================================

def create_planned_shipment(commitment: dict, warehouse: dict, units: int = 10,
                            ship_on: str = DEFAULT_SHIP_ON,
                            temp_controlled: bool = True,
                            temp_control_declined: bool = False,
                            **overrides) -> dict:
    """Create a PLANNED shipment (FEFO draw from the warehouse's AVAILABLE
    lots of the commitment's product). Requires the commitment ALLOCATED or
    SHORTED (i.e. the program past the SHIPPING allocation advance)."""
    return get_success_data(api_client.create_shipment(
        factories.create_shipment_payload(
            commitment_id=commitment["id"], warehouse_id=warehouse["id"],
            units=units, ship_on=ship_on, temp_controlled=temp_controlled,
            temp_control_declined_by_retailer=temp_control_declined,
            **overrides,
        ),
        _LOGISTICS,
    ))


def deliver_shipment(shipment: dict, deliver_time: str = CLOCK_DELIVER_TIME) -> dict:
    """PLANNED -> DELIVERED; delivered_on is set from the logical clock, so the
    clock is parked at deliver_time first for a deterministic timestamp."""
    set_clock(deliver_time)
    return get_success_data(api_client.deliver_shipment(shipment["id"], _LOGISTICS))


# ===========================================================================
# Heat-claim chain (PRD §3.8)
# ===========================================================================

def file_heat_claim(shipment: dict, retailer: dict, claimed_units: int = 1,
                    reason: str = "MELT",
                    evidence_note: str = "evidence attached") -> dict:
    """File a claim as the owning retailer. The shipment must be DELIVERED; the
    persisted claim lands in UNDER_REVIEW via the automatic FILED hop."""
    return get_success_data(api_client.create_heat_claim(
        factories.create_heat_claim_payload(
            shipment_id=shipment["id"], claimed_units=claimed_units,
            reason=reason, evidence_note=evidence_note,
        ),
        make_retailer_headers(retailer["id"]),
    ))


def decide_claim(claim_id: str, decision: str) -> dict:
    """ClaimsAdjuster decision: APPROVE | REJECT | REQUEST_MORE_INFO."""
    return get_success_data(api_client.decide_heat_claim(
        claim_id, {"decision": decision}, _ADJUSTER,
    ))


def provide_claim_info(claim_id: str, retailer: dict, evidence_note: str) -> dict:
    """MORE_INFO -> UNDER_REVIEW with fresh evidence from the owning retailer."""
    return get_success_data(api_client.provide_heat_claim_info(
        claim_id, {"evidence_note": evidence_note}, make_retailer_headers(retailer["id"]),
    ))


# ===========================================================================
# Sell-through reports (PRD §3.7)
# ===========================================================================

def file_sell_through_report(program: dict, retailer: dict,
                             week_of_on: str = DEFAULT_REPORT_WEEK,
                             seasonal_units_sold: int = 120,
                             seasonal_units_on_hand: int = 300,
                             everyday_units_sold: int = 880) -> dict:
    """File the weekly report as the owning retailer; both cannibalization
    variants are computed at creation."""
    return get_success_data(api_client.create_sell_through_report(
        factories.create_sell_through_report_payload(
            retailer_id=retailer["id"], program_id=program["id"],
            week_of_on=week_of_on, seasonal_units_sold=seasonal_units_sold,
            seasonal_units_on_hand=seasonal_units_on_hand,
            everyday_units_sold=everyday_units_sold,
        ),
        make_retailer_headers(retailer["id"]),
    ))


# ===========================================================================
# Disposition chain (PRD §3.9)
# ===========================================================================

def propose_disposition(program: dict, product: dict, warehouse: dict,
                        units: int, channel: str = "DESTRUCTION",
                        markdown_pct=None, proposer_headers=None) -> dict:
    """Propose a DispositionOrder as a CategoryManager (default cm-alice).
    The program must be in DISPOSITION."""
    overrides = {"units": units, "channel": channel}
    if markdown_pct is not None:
        overrides["markdown_pct"] = markdown_pct
    return get_success_data(api_client.create_disposition_order(
        factories.create_disposition_order_payload(
            program_id=program["id"], product_id=product["id"],
            warehouse_id=warehouse["id"], **overrides,
        ),
        proposer_headers or _CM,
    ))


def decide_disposition(order_id: str, decision: str = "APPROVE",
                       approver_headers=None) -> dict:
    """Approve or reject a PROPOSED order. The approver (default cm-bob) must
    differ from the proposer — segregation of duties (PRD §3.9)."""
    return get_success_data(api_client.approve_disposition_order(
        order_id, {"decision": decision}, approver_headers or _CM_B,
    ))


def execute_disposition(order_id: str) -> dict:
    """Execute an APPROVED order as a LogisticsCoordinator; consumes the
    QUARANTINED lots and settles recovered_value_cents."""
    return get_success_data(api_client.execute_disposition_order(order_id, _LOGISTICS))


def create_approved_disposition(program: dict, product: dict, warehouse: dict,
                                units: int, channel: str = "DESTRUCTION",
                                markdown_pct=None) -> dict:
    """Propose (cm-alice) + approve (cm-bob). Returns the APPROVED order."""
    order = propose_disposition(program, product, warehouse, units,
                                channel=channel, markdown_pct=markdown_pct)
    return decide_disposition(order["id"], "APPROVE")


def create_executed_disposition(program: dict, product: dict, warehouse: dict,
                                units: int, channel: str = "DESTRUCTION",
                                markdown_pct=None) -> dict:
    """Propose + approve + execute. Returns the EXECUTED order."""
    approved = create_approved_disposition(
        program, product, warehouse, units, channel=channel, markdown_pct=markdown_pct,
    )
    return execute_disposition(approved["id"])


# ===========================================================================
# drive_program_to: the program-lifecycle engine
# ===========================================================================

def drive_program_to(stage: str, *, commitment_specs=(), produced_units=None,
                     run_stage=None, warehouse_capacity=1000,
                     shipment_specs=(), program_overrides=None,
                     product_overrides=None, warehouse_overrides=None,
                     default_retailer_overrides=None,
                     with_everyday_product=False,
                     everyday_product_overrides=None,
                     line_code="LINE-A", run_overrides=None) -> dict:
    """Build a world and drive its program to the requested stage.

    stage: one of "OPEN", "LOCKED", "IN_PRODUCTION", "SHIPPING", "ON_SHELF",
    "DISPOSITION" (the forward path of the PRD program state machine).

    Parameters:
      commitment_specs: list of dicts, one per CONFIRMED commitment to create
        during the collection window. Keys: "tier" (default "GOLD"), "units"
        (default 10), "use_default_retailer" (bool — reuse the world's GOLD
        retailer instead of creating a fresh account), "retailer_overrides"
        (dict), "ship_window_open_on"/"ship_window_close_on" (ISO strings).
      produced_units: units the driver's own run completes with. None means no
        run is created (not legal for stages past LOCKED, where a run must
        exist; the engine defaults it to 10 there).
      run_stage: how far to take the driver's run — "none", "schedule",
        "start", or "complete". Default: "complete" for stages past LOCKED,
        otherwise "schedule" when produced_units is set, else "none".
      warehouse_capacity: capacity_units of the world warehouse (default 1000).
      shipment_specs: list of dicts created after the SHIPPING allocation.
        Keys: "commitment_index" (default 0), "units" (default 10), "ship_on",
        "temp_controlled", "declined", "deliver" (bool — deliver immediately).

    Returns a world dict with refreshed entities:
      program, retailer (default GOLD account), warehouse, product,
      everyday_product (or None), commitments (list, current state),
      commitment_retailers (parallel list), commitment (first, or None),
      run (or None), lot (or None), shipments (list), shipment (first or None).
    """
    stage_index = _STAGE_ORDER.index(stage)
    locked_index = _STAGE_ORDER.index("LOCKED")
    in_production_index = _STAGE_ORDER.index("IN_PRODUCTION")
    shipping_index = _STAGE_ORDER.index("SHIPPING")
    on_shelf_index = _STAGE_ORDER.index("ON_SHELF")

    if stage_index >= in_production_index and produced_units is None:
        produced_units = 10  # IN_PRODUCTION requires a non-CANCELLED run

    # --- reference data + OPEN advance -------------------------------------
    set_clock(CLOCK_BASELINE)
    program = create_program(**(program_overrides or {}))
    program = advance_program_to(program["id"], ProgramAdvanceTarget.OPEN_FOR_COMMITMENTS.value)
    retailer = create_retailer(**(default_retailer_overrides or {}))
    warehouse = create_warehouse(capacity_units=warehouse_capacity,
                                 **(warehouse_overrides or {}))
    product = create_product(program["id"], **(product_overrides or {}))
    everyday_product = (
        create_everyday_product(**(everyday_product_overrides or {}))
        if with_everyday_product else None
    )

    # --- commitments during the collection window ---------------------------
    commitments = []
    if commitment_specs:
        set_clock(CLOCK_WITHIN_COMMITMENT_WINDOW)
        for spec in commitment_specs:
            if spec.get("use_default_retailer"):
                spec_retailer = retailer
            else:
                spec_retailer = create_retailer(
                    tier=spec.get("tier", "GOLD"),
                    **(spec.get("retailer_overrides") or {}),
                )
            commitment_overrides = {}
            for key in ("ship_window_open_on", "ship_window_close_on"):
                if key in spec:
                    commitment_overrides[key] = spec[key]
            draft = create_draft_commitment(
                program, spec_retailer, product,
                committed_units=spec.get("units", 10), **commitment_overrides,
            )
            submitted = submit_commitment(draft, spec_retailer)
            confirmed = confirm_commitment(submitted)
            commitments.append({
                "commitment": confirmed, "retailer": spec_retailer, "spec": spec,
            })

    # --- production run -------------------------------------------------------
    run = None
    if produced_units is not None:
        run = create_scheduled_run(
            product, program, planned_units=produced_units,
            line_code=line_code, **(run_overrides or {}),
        )

    if stage == "OPEN":
        return _assemble_world(program, retailer, warehouse, product,
                               everyday_product, commitments, run, None, [])

    # --- LOCKED ---------------------------------------------------------------
    set_clock(CLOCK_AT_COMMITMENT_CLOSE)
    program = advance_program_to(program["id"], ProgramAdvanceTarget.LOCKED.value)

    effective_run_stage = run_stage
    if effective_run_stage is None:
        if stage_index >= in_production_index:
            effective_run_stage = "complete"
        elif run is not None:
            effective_run_stage = "schedule"
        else:
            effective_run_stage = "none"

    lot = None
    if run is not None and effective_run_stage in ("start", "complete"):
        run = start_run(run)
    if run is not None and effective_run_stage == "complete":
        run = complete_run(run, warehouse, produced_units)
        lot = get_lot_for_run(run["id"])

    if stage == "LOCKED":
        return _assemble_world(program, retailer, warehouse, product,
                               everyday_product, commitments, run, lot, [])

    # --- IN_PRODUCTION ----------------------------------------------------------
    program = advance_program_to(program["id"], ProgramAdvanceTarget.IN_PRODUCTION.value)
    if stage == "IN_PRODUCTION":
        return _assemble_world(program, retailer, warehouse, product,
                               everyday_product, commitments, run, lot, [])

    # --- SHIPPING (the allocation waterfall runs on this advance) ---------------
    set_clock(CLOCK_AT_SHIP_WINDOW_OPEN)
    program = advance_program_to(program["id"], ProgramAdvanceTarget.SHIPPING.value)

    shipments = []
    for spec in shipment_specs:
        entry = commitments[spec.get("commitment_index", 0)]
        shipment = create_planned_shipment(
            entry["commitment"], warehouse,
            units=spec.get("units", 10),
            ship_on=spec.get("ship_on", DEFAULT_SHIP_ON),
            temp_controlled=spec.get("temp_controlled", True),
            temp_control_declined=spec.get("declined", False),
        )
        if spec.get("deliver"):
            shipment = deliver_shipment(shipment)
        shipments.append(shipment)

    if stage == "SHIPPING":
        return _assemble_world(program, retailer, warehouse, product,
                               everyday_product, commitments, run, lot, shipments)

    # --- ON_SHELF ----------------------------------------------------------------
    set_clock(CLOCK_AT_ON_SHELF)
    program = advance_program_to(program["id"], ProgramAdvanceTarget.ON_SHELF.value)
    if stage == "ON_SHELF":
        return _assemble_world(program, retailer, warehouse, product,
                               everyday_product, commitments, run, lot, shipments)

    # --- DISPOSITION (the pull cascade quarantines seasonal lots and cancels
    #     still-PLANNED shipments, restoring their units) -------------------------
    set_clock(CLOCK_AT_PULL)
    program = advance_program_to(program["id"], ProgramAdvanceTarget.DISPOSITION.value)
    return _assemble_world(program, retailer, warehouse, product,
                           everyday_product, commitments, run, lot, shipments)


def _assemble_world(program, retailer, warehouse, product, everyday_product,
                    commitments, run, lot, shipments) -> dict:
    """Re-read every entity so the world reflects the latest server state."""
    program_now = get_program(program["id"])
    run_now = get_production_run(run["id"]) if run else None
    if run is not None and run_now["status"] == "COMPLETE":
        lot = get_lot_for_run(run["id"])
    world = {
        "program": program_now,
        "retailer": retailer,
        "warehouse": get_warehouse(warehouse["id"]),
        "product": product,
        "everyday_product": everyday_product,
        "commitments": [get_commitment(c["commitment"]["id"]) for c in commitments],
        "commitment_retailers": [c["retailer"] for c in commitments],
        "commitment_specs": [c["spec"] for c in commitments],
        "run": run_now,
        "lot": lot,
        "shipments": [get_shipment(s["id"]) for s in shipments],
    }
    world["commitment"] = world["commitments"][0] if world["commitments"] else None
    world["shipment"] = world["shipments"][0] if world["shipments"] else None
    return world


# ===========================================================================
# Named stage wrappers — the fixture API Stage 2 requests by name
# ===========================================================================

def setup_program(**overrides) -> dict:
    """A bare PLANNING program (clock parked at the baseline). Returns the
    program dict itself, not a world."""
    set_clock(CLOCK_BASELINE)
    return create_program(**overrides)


def setup_open_program(**kwargs) -> dict:
    """World with the program OPEN_FOR_COMMITMENTS (no clock-gated steps run)."""
    return drive_program_to("OPEN", **kwargs)


def setup_locked_program(**kwargs) -> dict:
    """World with the program LOCKED (collection window closed)."""
    return drive_program_to("LOCKED", **kwargs)


def setup_in_production_program(**kwargs) -> dict:
    """World with the program IN_PRODUCTION; the driver's run is COMPLETE and
    its lot sits AVAILABLE at the warehouse."""
    return drive_program_to("IN_PRODUCTION", **kwargs)


def setup_ready_for_allocation(commitment_specs, produced_units=100, **kwargs) -> dict:
    """IN_PRODUCTION with CONFIRMED commitments and a COMPLETE run; the clock
    is parked at ship_window_open_on so the SHIPPING advance (which runs the
    supply waterfall) is the caller's trigger."""
    world = drive_program_to(
        "IN_PRODUCTION", commitment_specs=commitment_specs,
        produced_units=produced_units, **kwargs,
    )
    set_clock(CLOCK_AT_SHIP_WINDOW_OPEN)
    return world


def setup_allocated_program(commitment_specs=None, produced_units=100,
                            shipment_specs=(), **kwargs) -> dict:
    """World in SHIPPING after the allocation waterfall: commitments are
    ALLOCATED or SHORTED, shortfall credits posted. Default shape: one GOLD
    commitment of 10 against a 100-unit pool."""
    if commitment_specs is None:
        commitment_specs = [{"tier": "GOLD", "units": 10, "use_default_retailer": True}]
    return drive_program_to(
        "SHIPPING", commitment_specs=commitment_specs,
        produced_units=produced_units, shipment_specs=shipment_specs, **kwargs,
    )


def setup_on_shelf_program(**kwargs) -> dict:
    """World in ON_SHELF (sell-through reporting is open)."""
    kwargs.setdefault("produced_units", 10)
    return drive_program_to("ON_SHELF", **kwargs)


def setup_disposition_program(**kwargs) -> dict:
    """World in DISPOSITION after the pull cascade: the program's seasonal lot
    is QUARANTINED and any still-PLANNED shipments were cancelled with their
    units restored."""
    kwargs.setdefault("produced_units", 10)
    return drive_program_to("DISPOSITION", **kwargs)


def setup_locked_with_in_progress_run(planned_units=10, warehouse_capacity=1000,
                                      **kwargs) -> dict:
    """Program LOCKED; warehouse created; one run IN_PROGRESS and NOT yet
    completed — the complete call is the intended trigger (warehouse posture,
    capacity and lot-creation tests)."""
    return drive_program_to(
        "LOCKED", produced_units=planned_units, run_stage="start",
        warehouse_capacity=warehouse_capacity, **kwargs,
    )


def setup_warehouse_with_load(load_units, capacity=1000, **kwargs) -> dict:
    """Program LOCKED with the warehouse already holding exactly load_units
    AVAILABLE units of the seasonal product (one completed run). Tests add and
    complete further runs to probe the posture/capacity boundaries."""
    return drive_program_to(
        "LOCKED", produced_units=load_units, run_stage="complete",
        warehouse_capacity=capacity, **kwargs,
    )


def setup_delivered_shipment(commitment_units=10, ship_units=10,
                             temp_controlled=True, temp_control_declined=False,
                             ship_on=DEFAULT_SHIP_ON, produced_units=None,
                             **kwargs) -> dict:
    """World in SHIPPING: one GOLD commitment fully ALLOCATED and one shipment
    of ship_units already DELIVERED (delivered_on == CLOCK_DELIVER_TIME)."""
    produced = produced_units if produced_units is not None else max(
        commitment_units, ship_units,
    )
    return drive_program_to(
        "SHIPPING",
        commitment_specs=[{
            "tier": "GOLD", "units": commitment_units, "use_default_retailer": True,
        }],
        produced_units=produced,
        shipment_specs=[{
            "units": ship_units, "ship_on": ship_on,
            "temp_controlled": temp_controlled, "declined": temp_control_declined,
            "deliver": True,
        }],
        **kwargs,
    )


def setup_heat_claim_under_review(claimed_units, reason="MELT",
                                  evidence_note="evidence attached",
                                  **kwargs) -> dict:
    """A DELIVERED shipment plus a filed claim in UNDER_REVIEW (the automatic
    FILED -> UNDER_REVIEW hop happens within the filing request). Shipment
    shape is controlled via the setup_delivered_shipment kwargs."""
    world = setup_delivered_shipment(**kwargs)
    world["claim"] = file_heat_claim(
        world["shipment"], world["retailer"], claimed_units,
        reason=reason, evidence_note=evidence_note,
    )
    return world


def dispose_all_quarantined(world: dict) -> None:
    """Destroy every quarantined unit of the world's seasonal product at the
    world warehouse, so the program can advance DISPOSITION -> CLOSED."""
    lots = get_success_data(api_client.list_inventory_lots(
        _ADMIN, params={
            "product_id": world["product"]["id"],
            "warehouse_id": world["warehouse"]["id"],
            "status": "QUARANTINED",
        },
    ))
    remaining = sum(lot["units_on_hand"] for lot in lots)
    if remaining > 0:
        create_executed_disposition(
            world["program"], world["product"], world["warehouse"],
            remaining, channel="DESTRUCTION",
        )


def setup_closed_program(**kwargs) -> dict:
    """Full lifecycle through CLOSED: DISPOSITION, all quarantined stock
    destroyed, then the final advance. For post-terminal lockdown tests."""
    world = setup_disposition_program(**kwargs)
    dispose_all_quarantined(world)
    world["program"] = advance_program_to(
        world["program"]["id"], ProgramAdvanceTarget.CLOSED.value,
    )
    if world.get("run"):
        world["lot"] = get_lot_for_run(world["run"]["id"])
    world["warehouse"] = get_warehouse(world["warehouse"]["id"])
    return world


def cancel_program(program_id: str) -> dict:
    """Advance a program to CANCELLED (from PLANNING or OPEN_FOR_COMMITMENTS);
    cascades cancellation onto its DRAFT/SUBMITTED/CONFIRMED commitments."""
    return advance_program_to(program_id, ProgramAdvanceTarget.CANCELLED.value)


def setup_cancelled_program(open_first=False, **kwargs) -> dict:
    """A program already in terminal CANCELLED. With open_first=True the
    program passed through OPEN_FOR_COMMITMENTS first."""
    if open_first:
        world = setup_open_program(**kwargs)
        program_id = world["program"]["id"]
    else:
        program_id = setup_program()["id"]
    return advance_program_to(program_id, ProgramAdvanceTarget.CANCELLED.value)
