"""Composite setup helpers.

Every test starts against an empty store, so each helper builds its
preconditions from scratch through the declared endpoints. Setup calls go
through ``get_success_data`` so a setup failure surfaces as a setup error
rather than as a masked assertion.

The helpers are layered:

* tier 1 - single writes that move one resource one step
* tier 2 - entity hierarchies (site, train, charge; slate and storage)
* tier 3 - lifecycle shortcuts (an approved, running or settled campaign)
* tier 4 - accumulation and threshold targeting (activity, posture, position)
* tier 5 - finalisation and terminal states (delivered movement, closed outage)
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    CM_AUTHOR,
    ENG_APPROVER,
    ENG_AUTHOR,
    LOGISTICS,
    REG_ADMIN,
    SO_APPROVER,
    SO_REVIEWER,
    make_commercial_manager_headers,
    make_logistics_coordinator_headers,
    make_process_engineer_headers,
    make_regulatory_admin_headers,
    make_safety_officer_headers,
    make_terminal_operator_headers,
)


# ===========================================================================
# Tier 1 - single writes
# ===========================================================================
def set_clock(api, to_iso8601, user_id=REG_ADMIN):
    """Move the logical UTC clock and return the new current_utc payload."""
    return get_success_data(
        api.set_clock(to_iso8601, make_regulatory_admin_headers(user_id))
    )


def register_plant(api, **overrides):
    """Register a plant as a RegulatoryAdmin."""
    return get_success_data(
        api.create_plant(f.plant_payload(**overrides), make_regulatory_admin_headers())
    )


def commission_train(api, plant_id, **overrides):
    """Commission a reformer train as a ProcessEngineer."""
    return get_success_data(
        api.create_reformer_train(
            f.reformer_train_payload(plant_id, **overrides),
            make_process_engineer_headers(),
        )
    )


def install_charge(api, train_id, **overrides):
    """Load a catalyst charge into a train as a ProcessEngineer."""
    return get_success_data(
        api.create_catalyst_charge(
            f.catalyst_charge_payload(train_id, **overrides),
            make_process_engineer_headers(),
        )
    )


def book_hedge_lot(api, plant_id, **overrides):
    """Book a fixed-strike hedge lot as a CommercialManager."""
    return get_success_data(
        api.create_gas_hedge_lot(
            f.gas_hedge_lot_payload(plant_id, **overrides),
            make_commercial_manager_headers(),
        )
    )


def define_product_line(api, plant_id, **overrides):
    """Define a product line as a CommercialManager."""
    return get_success_data(
        api.create_product_line(
            f.product_line_payload(plant_id, **overrides),
            make_commercial_manager_headers(),
        )
    )


def register_storage_asset(api, plant_id, **overrides):
    """Register a dome, tank or terminal as a LogisticsCoordinator."""
    return get_success_data(
        api.create_storage_asset(
            f.storage_asset_payload(plant_id, **overrides),
            make_logistics_coordinator_headers(),
        )
    )


def set_opening_balance(api, asset_id, tons):
    """State an asset's counted opening position."""
    return get_success_data(
        api.set_opening_balance(asset_id, tons, make_logistics_coordinator_headers())
    )


def set_permit_status(api, plant_id, permit_status):
    """Record an air-permit standing change as a RegulatoryAdmin."""
    return get_success_data(
        api.post_permit_status(plant_id, permit_status, make_regulatory_admin_headers())
    )


def set_psm_program_status(api, plant_id, psm_program_status, user_id=SO_APPROVER):
    """Record a process-safety-program standing change as a SafetyOfficer."""
    return get_success_data(
        api.post_psm_program_status(
            plant_id, psm_program_status, make_safety_officer_headers(user_id)
        )
    )


def post_gas_index(api, plant_id, spot_gas_index_usd_per_mmbtu):
    """Publish a fresh spot gas index as a RegulatoryAdmin."""
    return get_success_data(
        api.post_gas_index(
            plant_id, spot_gas_index_usd_per_mmbtu, make_regulatory_admin_headers()
        )
    )


def ingest_reading(api, plant_id, **overrides):
    """Ingest one continuous-emissions-monitoring reading."""
    return get_success_data(
        api.create_emissions_reading(
            f.emissions_reading_payload(plant_id, **overrides),
            make_regulatory_admin_headers(),
        )
    )


def schedule_run(api, train_id, author=ENG_AUTHOR, **overrides):
    """Schedule a campaign, recording the author as created_by_user_id."""
    return get_success_data(
        api.create_production_run(
            f.production_run_payload(train_id, **overrides),
            make_process_engineer_headers(author),
        )
    )


def approve_run(api, run_id, approver=ENG_APPROVER):
    """Approve a planned campaign under a second signature."""
    return get_success_data(
        api.approve_production_run(run_id, make_process_engineer_headers(approver))
    )


def start_run(api, run_id, actor=ENG_APPROVER):
    """Put an approved campaign on line."""
    return get_success_data(
        api.start_production_run(run_id, make_process_engineer_headers(actor))
    )


def complete_run(api, run_id, actual_ammonia_tons, actual_operating_hours,
                 actor=ENG_APPROVER):
    """Settle a running campaign at the final feedstock variant."""
    return get_success_data(
        api.complete_production_run(
            run_id,
            actual_ammonia_tons,
            actual_operating_hours,
            make_process_engineer_headers(actor),
        )
    )


def create_order(api, run_id, product_line_id, destination_asset_id,
                 author=CM_AUTHOR, **overrides):
    """Book a finished-product order against a campaign."""
    return get_success_data(
        api.create_production_order(
            f.production_order_payload(
                run_id, product_line_id, destination_asset_id, **overrides
            ),
            make_commercial_manager_headers(author),
        )
    )


def reserve_order(api, order_id, run_id, reserve_tons, actor=CM_AUTHOR):
    """Reserve tons against a campaign, re-reading the run's version first.

    A successful reservation advances the run's version, so the expectation is
    always read immediately before the write rather than cached by the caller.
    """
    run = get_success_data(
        api.get_production_run(run_id, make_commercial_manager_headers(actor))
    )
    return get_success_data(
        api.reserve_production_order(
            order_id,
            reserve_tons,
            run["version"],
            make_commercial_manager_headers(actor),
        )
    )


def release_order(api, order_id, release_reason, actor=CM_AUTHOR):
    """Release a reservation back to the campaign's ammonia pool."""
    return get_success_data(
        api.release_production_order(
            order_id, release_reason, make_commercial_manager_headers(actor)
        )
    )


def security_check(api, order_id, decision, actor=SO_REVIEWER):
    """Record the regulated-substance clearance decision on an order."""
    return get_success_data(
        api.security_check_production_order(
            order_id, decision, make_safety_officer_headers(actor)
        )
    )


def produce_order(api, order_id, produced_tons, actor=ENG_APPROVER):
    """Book the finished tons actually made into the destination asset."""
    return get_success_data(
        api.produce_production_order(
            order_id, produced_tons, make_process_engineer_headers(actor)
        )
    )


def draft_shipment(api, origin_asset_id, dest_asset_id, **overrides):
    """Draft a movement between two storage assets."""
    return get_success_data(
        api.create_shipment(
            f.shipment_payload(origin_asset_id, dest_asset_id, **overrides),
            make_logistics_coordinator_headers(),
        )
    )


def book_shipment(api, shipment_id, origin_asset_id, actor=LOGISTICS):
    """Book a drafted movement, re-reading the origin asset's version first."""
    origin = get_success_data(
        api.get_storage_asset(origin_asset_id, make_logistics_coordinator_headers(actor))
    )
    return get_success_data(
        api.book_shipment(
            shipment_id, origin["version"], make_logistics_coordinator_headers(actor)
        )
    )


def depart_shipment(api, shipment_id):
    """Mark a booked movement departed."""
    return get_success_data(
        api.depart_shipment(shipment_id, make_logistics_coordinator_headers())
    )


def deliver_shipment(api, shipment_id, dest_asset_id, received_tons):
    """Acknowledge receipt as the destination asset's own terminal operator."""
    return get_success_data(
        api.deliver_shipment(
            shipment_id, received_tons, make_terminal_operator_headers(dest_asset_id)
        )
    )


def draft_quote(api, plant_id, product_line_id, **overrides):
    """Draft a customer price quote."""
    return get_success_data(
        api.create_price_quote(
            f.price_quote_payload(plant_id, product_line_id, **overrides),
            make_commercial_manager_headers(),
        )
    )


def issue_quote(api, quote_id):
    """Issue a drafted quote, snapshotting the gas basis."""
    return get_success_data(
        api.issue_price_quote(quote_id, make_commercial_manager_headers())
    )


def author_turnaround(api, plant_id, train_id, author=ENG_AUTHOR, **overrides):
    """Author an outage, recording the author as authored_by_user_id."""
    return get_success_data(
        api.create_turnaround(
            f.turnaround_payload(plant_id, train_id, **overrides),
            make_process_engineer_headers(author),
        )
    )


def add_task(api, turnaround_id, duration_days, predecessor_task_id=None, **overrides):
    """Add a work step to a DRAFT or SUBMITTED outage."""
    return get_success_data(
        api.create_turnaround_task(
            f.turnaround_task_payload(
                turnaround_id,
                duration_days=duration_days,
                predecessor_task_id=predecessor_task_id,
                **overrides,
            ),
            make_process_engineer_headers(),
        )
    )


def submit_turnaround(api, turnaround_id, actor=ENG_AUTHOR):
    """Submit an authored outage for safety review."""
    return get_success_data(
        api.submit_turnaround(turnaround_id, make_process_engineer_headers(actor))
    )


def psm_review(api, turnaround_id, decision="ENDORSED", findings_count=0,
               reviewer=SO_REVIEWER):
    """Sign the pre-startup safety review; the outage stays SUBMITTED."""
    return get_success_data(
        api.psm_review_turnaround(
            turnaround_id,
            decision,
            findings_count,
            make_safety_officer_headers(reviewer),
        )
    )


def approve_turnaround(api, turnaround_id, approver=SO_APPROVER):
    """Approve a submitted outage as the third distinct signature."""
    return get_success_data(
        api.approve_turnaround(turnaround_id, make_safety_officer_headers(approver))
    )


def reject_turnaround(api, turnaround_id, rejection_reason, approver=SO_APPROVER):
    """Reject a submitted outage, voiding the review and blocking its steps."""
    return get_success_data(
        api.reject_turnaround(
            turnaround_id, rejection_reason, make_safety_officer_headers(approver)
        )
    )


def start_turnaround(api, turnaround_id, actor=ENG_AUTHOR):
    """Take the train down and begin the outage."""
    return get_success_data(
        api.start_turnaround(turnaround_id, make_process_engineer_headers(actor))
    )


def complete_task(api, task_id, actor=ENG_AUTHOR):
    """Mark a ready work step done, releasing its successors."""
    return get_success_data(
        api.complete_turnaround_task(task_id, make_process_engineer_headers(actor))
    )


# ===========================================================================
# Tier 2 - entity hierarchies
# ===========================================================================
def commissioned_site(api, spot_gas_index_usd_per_mmbtu=4.2000,
                      permit_limit_tons_30d=12.00, design_life_hours=40000.0,
                      baseline_operating_hours=None, poisoning_index=None,
                      rated_ammonia_tpd=1800.0):
    """A plant with one reformer train carrying one ACTIVE catalyst charge.

    Omitting ``baseline_operating_hours`` leaves the charge on a fresh meter, so
    its activity opens at 100.00.
    """
    plant = register_plant(
        api,
        spot_gas_index_usd_per_mmbtu=spot_gas_index_usd_per_mmbtu,
        permit_limit_tons_30d=permit_limit_tons_30d,
    )
    train = commission_train(api, plant["id"], rated_ammonia_tpd=rated_ammonia_tpd)
    charge = install_charge(
        api,
        train["id"],
        design_life_hours=design_life_hours,
        baseline_operating_hours=baseline_operating_hours,
        poisoning_index=poisoning_index,
    )
    return {"plant": plant, "train": train, "charge": charge}


def two_train_site(api, **overrides):
    """A plant with two independently charged reformer trains."""
    site = commissioned_site(api, **overrides)
    train_b = commission_train(api, site["plant"]["id"])
    charge_b = install_charge(
        api,
        train_b["id"],
        design_life_hours=overrides.get("design_life_hours", 40000.0),
        baseline_operating_hours=overrides.get("baseline_operating_hours"),
    )
    site["train_b"] = train_b
    site["charge_b"] = charge_b
    return site


def slate_and_storage(api, plant_id, product_code="UREA", regulated=False,
                      ammonia_tons_per_product_ton=0.580,
                      conversion_cost_usd_per_ton=38.000, priority_rank=10,
                      asset_kind="TANK", capacity_tons=20000.000,
                      security_class="BASIC", seasonal_reserve_pct=None,
                      opening_balance_tons=None):
    """One product line plus one storage asset that may legally hold it."""
    line = define_product_line(
        api,
        plant_id,
        product_code=product_code,
        regulated=regulated,
        ammonia_tons_per_product_ton=ammonia_tons_per_product_ton,
        conversion_cost_usd_per_ton=conversion_cost_usd_per_ton,
        priority_rank=priority_rank,
    )
    asset = register_storage_asset(
        api,
        plant_id,
        asset_kind=asset_kind,
        product_code=product_code,
        capacity_tons=capacity_tons,
        security_class=security_class,
        seasonal_reserve_pct=seasonal_reserve_pct,
    )
    if opening_balance_tons is not None:
        asset = set_opening_balance(api, asset["id"], opening_balance_tons)
    return {"line": line, "asset": asset}


def terminal_pair(api, plant_id, product_code="UREA", capacity_tons=20000.000,
                  security_class="BASIC", seasonal_reserve_pct=None,
                  origin_opening_tons=None):
    """Two same-product assets on one plant: a shipping origin and a receiver."""
    origin = register_storage_asset(
        api,
        plant_id,
        asset_kind="TERMINAL",
        product_code=product_code,
        capacity_tons=capacity_tons,
        security_class=security_class,
        seasonal_reserve_pct=seasonal_reserve_pct,
    )
    dest = register_storage_asset(
        api,
        plant_id,
        asset_kind="TERMINAL",
        product_code=product_code,
        capacity_tons=capacity_tons,
        security_class=security_class,
        seasonal_reserve_pct=seasonal_reserve_pct,
    )
    if origin_opening_tons is not None:
        origin = set_opening_balance(api, origin["id"], origin_opening_tons)
    return {"origin": origin, "dest": dest}


# ===========================================================================
# Tier 3 - campaign lifecycle shortcuts
# ===========================================================================
def approved_run(api, train_id, author=ENG_AUTHOR, approver=ENG_APPROVER, **overrides):
    """A campaign carried from PLANNED to APPROVED under two signatures."""
    run = schedule_run(api, train_id, author=author, **overrides)
    return approve_run(api, run["id"], approver=approver)


def running_run(api, train_id, clock_at=None, author=ENG_AUTHOR,
                approver=ENG_APPROVER, **overrides):
    """A campaign on line, with its catalyst charge pinned.

    ``clock_at`` moves the logical clock to the campaign window before the
    start, because starting requires the clock to have reached window_start.
    """
    run = approved_run(api, train_id, author=author, approver=approver, **overrides)
    if clock_at is not None:
        set_clock(api, clock_at)
    return start_run(api, run["id"], actor=approver)


def settled_run(api, train_id, actual_ammonia_tons, actual_operating_hours,
                clock_at="2026-09-01T00:00:00Z", author=ENG_AUTHOR,
                approver=ENG_APPROVER, **overrides):
    """A campaign carried all the way to COMPLETED with a final unit cost."""
    run = running_run(
        api, train_id, clock_at=clock_at, author=author, approver=approver, **overrides
    )
    return complete_run(
        api, run["id"], actual_ammonia_tons, actual_operating_hours, actor=approver
    )


# ===========================================================================
# Tier 4 - accumulation and threshold targeting
# ===========================================================================
def reserved_order(api, run_id, product_line_id, destination_asset_id, reserve_tons,
                   requested_tons=None, author=CM_AUTHOR):
    """An order carried from UNALLOCATED to RESERVED against a campaign."""
    order = create_order(
        api,
        run_id,
        product_line_id,
        destination_asset_id,
        author=author,
        requested_tons=requested_tons if requested_tons is not None else reserve_tons,
    )
    return reserve_order(api, order["id"], run_id, reserve_tons, actor=author)


def booked_shipment(api, origin_asset_id, dest_asset_id, **overrides):
    """A movement carried from DRAFT to BOOKED with its freight priced."""
    shipment = draft_shipment(api, origin_asset_id, dest_asset_id, **overrides)
    return book_shipment(api, shipment["id"], origin_asset_id)


def issued_quote(api, plant_id, product_line_id, **overrides):
    """A quote carried from DRAFT to ISSUED with its gas basis snapshotted."""
    quote = draft_quote(api, plant_id, product_line_id, **overrides)
    return issue_quote(api, quote["id"])


def chained_tasks(api, turnaround_id, durations):
    """A single dependency chain of work steps, each behind the previous one."""
    tasks = []
    predecessor = None
    for duration in durations:
        task = add_task(api, turnaround_id, duration, predecessor_task_id=predecessor)
        tasks.append(task)
        predecessor = task["id"]
    return tasks


def endorsed_turnaround(api, plant_id, train_id, durations=(7, 14),
                        findings_count=0, scope="CATALYST_CHANGE",
                        author=ENG_AUTHOR, reviewer=SO_REVIEWER, **overrides):
    """A SUBMITTED outage carrying an ENDORSED safety review and a task chain."""
    turnaround = author_turnaround(
        api, plant_id, train_id, author=author, scope=scope, **overrides
    )
    tasks = chained_tasks(api, turnaround["id"], durations)
    submit_turnaround(api, turnaround["id"], actor=author)
    reviewed = psm_review(
        api,
        turnaround["id"],
        decision="ENDORSED",
        findings_count=findings_count,
        reviewer=reviewer,
    )
    return {"turnaround": reviewed, "tasks": tasks}


def approved_turnaround_world(api, plant_id, train_id, approver=SO_APPROVER, **overrides):
    """An outage carried to APPROVED behind three distinct signatures."""
    world = endorsed_turnaround(api, plant_id, train_id, **overrides)
    world["turnaround"] = approve_turnaround(
        api, world["turnaround"]["id"], approver=approver
    )
    return world


# ===========================================================================
# Tier 5 - finalisation and terminal states
# ===========================================================================
def in_progress_turnaround(api, plant_id, train_id, clock_at, **overrides):
    """An outage started against the clock, with the train taken down."""
    world = approved_turnaround_world(api, plant_id, train_id, **overrides)
    set_clock(api, clock_at)
    world["turnaround"] = start_turnaround(api, world["turnaround"]["id"])
    return world


def delivered_shipment(api, origin_asset_id, dest_asset_id, received_tons,
                       depart_at=None, **overrides):
    """A movement carried all the way to DELIVERED by the receiving operator."""
    shipment = booked_shipment(api, origin_asset_id, dest_asset_id, **overrides)
    if depart_at is not None:
        set_clock(api, depart_at)
    depart_shipment(api, shipment["id"])
    return deliver_shipment(api, shipment["id"], dest_asset_id, received_tons)


def consumed_order(api, run_id, product_line_id, destination_asset_id, reserve_tons,
                   produced_tons, cleared_by=None):
    """An order carried to CONSUMED with its landed cost settled.

    ``cleared_by`` records the clearance decision first, which a regulated line
    requires before any tons may be produced.
    """
    order = reserved_order(
        api, run_id, product_line_id, destination_asset_id, reserve_tons
    )
    if cleared_by is not None:
        security_check(api, order["id"], "CLEARED", actor=cleared_by)
    return produce_order(api, order["id"], produced_tons)
