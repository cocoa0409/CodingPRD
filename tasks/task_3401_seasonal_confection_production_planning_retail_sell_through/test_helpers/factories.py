"""Payload factories — one per creatable entity, input fields only (PRD §3).

The default seasonal-program window chain satisfies the PRD §2.5 ordering
constraint and sits entirely after the logical-clock startup default of
2026-09-01T00:00:00Z, so fixtures can drive the clock forward monotonically:

  commitment [2027-01-10, 2027-02-15) <= production deadline 2027-06-30
  <= ship window [2027-07-15, 2027-09-15] <= on-shelf 2027-09-20
  < pull 2027-11-15 < destroy-by 2027-12-31
"""
import itertools

_sku_counter = itertools.count(1)
_retailer_counter = itertools.count(1)


def unique_sku_code(prefix: str = "SKU") -> str:
    """Globally unique sku_code (PRD §3.1 enforces uniqueness)."""
    return f"{prefix}-{next(_sku_counter):06d}"


def unique_retailer_name(prefix: str = "Retailer") -> str:
    """Distinct retailer banner names for multi-retailer scenarios."""
    return f"{prefix}-{next(_retailer_counter):03d}"


# --- SeasonalProgram ---------------------------------------------------------

DEFAULT_PROGRAM_WINDOWS = {
    "commitment_open_on": "2027-01-10T00:00:00Z",
    "commitment_close_on": "2027-02-15T00:00:00Z",
    "production_deadline_on": "2027-06-30T00:00:00Z",
    "ship_window_open_on": "2027-07-15T00:00:00Z",
    "ship_window_close_on": "2027-09-15T00:00:00Z",
    "on_shelf_on": "2027-09-20T00:00:00Z",
    "pull_on": "2027-11-15T00:00:00Z",
    "destroy_by_on": "2027-12-31T00:00:00Z",
}


def create_program_payload(**overrides) -> dict:
    """Twelve-field program create body (PRD §2.5, §3.1)."""
    defaults = {
        "season_code": "HALLOWEEN",
        "season_year": 2027,
        "retail_price_cents": 499,
        "forecast_units": 100000,
    }
    defaults.update(DEFAULT_PROGRAM_WINDOWS)
    defaults.update(overrides)
    return defaults


# --- Product -----------------------------------------------------------------

def create_product_payload(program_id=None, **overrides) -> dict:
    """SEASONAL product by default; pass program_id of the owning program."""
    defaults = {
        "program_id": program_id,
        "sku_code": unique_sku_code("SEAS"),
        "kind": "SEASONAL",
        "molded_shape": "pumpkin",
        "brand_protected": True,
        "requires_temp_control": True,
        "units_per_case": 24,
    }
    defaults.update(overrides)
    return defaults


def create_everyday_product_payload(**overrides) -> dict:
    """EVERYDAY product: program_id must be null (PRD §3.1)."""
    defaults = {
        "program_id": None,
        "sku_code": unique_sku_code("EV"),
        "kind": "EVERYDAY",
        "molded_shape": "standard-bar",
        "brand_protected": False,
        "requires_temp_control": False,
        "units_per_case": 48,
    }
    defaults.update(overrides)
    return defaults


# --- ProductionRun -----------------------------------------------------------

def create_production_run_payload(product_id=None, program_id=None, **overrides) -> dict:
    """Run create body; seasonal runs name program_id, everyday runs null it."""
    defaults = {
        "program_id": program_id,
        "product_id": product_id,
        "line_code": "LINE-A",
        "planned_units": 10,
        "scheduled_start_on": "2027-03-01T08:00:00Z",
        "scheduled_end_on": "2027-03-02T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_run_payload(warehouse_id=None, produced_units=10, **overrides) -> dict:
    defaults = {"produced_units": produced_units, "warehouse_id": warehouse_id}
    defaults.update(overrides)
    return defaults


# --- RetailerAccount -----------------------------------------------------------

def create_retailer_account_payload(**overrides) -> dict:
    defaults = {
        "name": unique_retailer_name(),
        "region": "NE",
        "tier": "GOLD",
        "max_seasonal_units": 100000,
        "everyday_baseline_weekly_units": 1000,
    }
    defaults.update(overrides)
    return defaults


# --- RetailerCommitment --------------------------------------------------------

def create_commitment_payload(program_id=None, retailer_id=None, product_id=None,
                              **overrides) -> dict:
    """DRAFT commitment create body (PRD §3.4). The retailer-specific ship
    window defaults to a slice strictly inside the default program window."""
    defaults = {
        "program_id": program_id,
        "retailer_id": retailer_id,
        "product_id": product_id,
        "committed_units": 10,
        "ship_window_open_on": "2027-08-01T00:00:00Z",
        "ship_window_close_on": "2027-09-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def revise_commitment_payload(committed_units=25, expected_commitment_version=None,
                              **overrides) -> dict:
    defaults = {
        "committed_units": committed_units,
        "expected_commitment_version": expected_commitment_version,
    }
    defaults.update(overrides)
    return defaults


# --- Shipment ------------------------------------------------------------------

def create_shipment_payload(commitment_id=None, warehouse_id=None, **overrides) -> dict:
    """PLANNED shipment body (PRD §3.6). Default ship_on lies inside both the
    default commitment window and the default program ship window, in a summer
    month (August) so heat-claim summer rules are exercisable."""
    defaults = {
        "commitment_id": commitment_id,
        "warehouse_id": warehouse_id,
        "units": 10,
        "ship_on": "2027-08-02T00:00:00Z",
        "temp_controlled": True,
        "temp_control_declined_by_retailer": False,
    }
    defaults.update(overrides)
    return defaults


# --- HeatClaim -----------------------------------------------------------------

def create_heat_claim_payload(shipment_id=None, **overrides) -> dict:
    defaults = {
        "shipment_id": shipment_id,
        "claimed_units": 1,
        "reason": "MELT",
        "evidence_note": "evidence attached",
    }
    defaults.update(overrides)
    return defaults


# --- Warehouse -----------------------------------------------------------------

def create_warehouse_payload(**overrides) -> dict:
    defaults = {
        "name": "W1",
        "temp_controlled": True,
        "capacity_units": 1000,
    }
    defaults.update(overrides)
    return defaults


# --- DispositionOrder ----------------------------------------------------------

def create_disposition_order_payload(program_id=None, product_id=None,
                                     warehouse_id=None, **overrides) -> dict:
    """Propose body (PRD §3.9). For channel MARKDOWN also pass markdown_pct."""
    defaults = {
        "program_id": program_id,
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "units": 1,
        "channel": "DESTRUCTION",
    }
    defaults.update(overrides)
    return defaults


# --- CommodityContract ---------------------------------------------------------

def create_commodity_contract_payload(program_id=None, **overrides) -> dict:
    """Contract create body (PRD §3.3). Hedge fields omitted unless supplied;
    hedged_quantity_units defaults server-side to 0."""
    defaults = {
        "program_id": program_id,
        "commodity": "COCOA",
        "quantity_units": 5000,
        "contract_price_cents_per_unit": 200,
    }
    defaults.update(overrides)
    return defaults


def settle_contract_payload(spot_price_cents_per_unit=95, **overrides) -> dict:
    defaults = {"spot_price_cents_per_unit": spot_price_cents_per_unit}
    defaults.update(overrides)
    return defaults


# --- SellThroughReport ---------------------------------------------------------

def create_sell_through_report_payload(retailer_id=None, program_id=None,
                                       **overrides) -> dict:
    """Weekly report body (PRD §3.7). Default week_of_on is a Monday inside the
    default program's [on_shelf_on, pull_on] interval."""
    defaults = {
        "retailer_id": retailer_id,
        "program_id": program_id,
        "week_of_on": "2027-10-04T00:00:00Z",
        "seasonal_units_sold": 120,
        "seasonal_units_on_hand": 300,
        "everyday_units_sold": 880,
    }
    defaults.update(overrides)
    return defaults
