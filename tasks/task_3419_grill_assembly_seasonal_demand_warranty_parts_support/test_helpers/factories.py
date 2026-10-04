"""Payload factories — one per entity, input fields only (PRD sections 3 and 4).

Also carries the clock helpers: the PRD-declared clock-driving mechanism is
POST /grillops/_clock/set_current_utc with a PlannerAdmin caller (PRD 2.4), and
set_logical_clock() is the single helper every fixture uses to move the clock.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO  # noqa: F401  (re-exported for convenience)
from .test_users import TEST_USERS

_counter = itertools.count(1)


def unique_suffix() -> int:
    """Monotonic per-process counter for unique serials, SKUs, part numbers."""
    return next(_counter)


def unique_serial(prefix: str = "SN") -> str:
    """Globally-unique serial string (serials must be unique across all sales, PRD 3.5)."""
    return f"{prefix}-{next(_counter)}"


# ---------------------------------------------------------------------------
# Entity create payloads (input fields only; server defaults left unset)
# ---------------------------------------------------------------------------
def create_clock_payload(to_iso8601: str = DEFAULT_CLOCK_ISO) -> dict:
    return {"to_iso8601": to_iso8601}


def create_season_payload(**overrides) -> dict:
    defaults = {
        "name": "Grilling Season 2026",
        "year": 2026,
        "build_start": "2026-01-05T00:00:00Z",
        "allocation_open": "2026-02-01T00:00:00Z",
        "in_season_start": "2026-03-01T00:00:00Z",
        "clearance_start": "2026-08-01T00:00:00Z",
        "season_end": "2026-09-30T00:00:00Z",
        "demand_forecast_units": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": "GX-100",
        "model_family": "GX",
        "model_year": 2026,
        "base_price_cents": 100000,
        "demand_share_bp": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_channel_payload(**overrides) -> dict:
    defaults = {
        "name": "BigBox",
        "channel_type": "HOME_CENTER",
        "allocation_priority": 10,
        "credit_limit_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(model_id: str, **overrides) -> dict:
    defaults = {
        "model_id": model_id,
        "build_week": "2026-W06",
        "units_built": 50,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(season_id: str, channel_account_id: str, model_id: str,
                              allocated_units: int, expected_season_version: int,
                              **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "channel_account_id": channel_account_id,
        "model_id": model_id,
        "allocated_units": allocated_units,
        "expected_season_version": expected_season_version,
    }
    defaults.update(overrides)
    return defaults


def create_assembler_payload(**overrides) -> dict:
    defaults = {
        "name": f"ASM-{unique_suffix()}",
        "service_regions": ["NW"],
    }
    defaults.update(overrides)
    return defaults


def create_assembly_job_payload(sale_id: str, job_type: str = "RETAIL_ASSEMBLY",
                                **overrides) -> dict:
    defaults = {
        "sale_id": sale_id,
        "job_type": job_type,
    }
    defaults.update(overrides)
    return defaults


def create_accessory(sku: str = None, accessory_type: str = "COVER",
                     unit_price_cents: int = 1999) -> dict:
    """One attach item: { sku, accessory_type: COVER|TOOLS|FUEL|OTHER, unit_price_cents } (PRD 3.5)."""
    return {
        "sku": sku or f"ACC-{unique_suffix()}",
        "accessory_type": accessory_type,
        "unit_price_cents": unit_price_cents,
    }


def create_sale_payload(season_id: str, model_id: str, channel_account_id: str,
                        quantity: int = 1, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "model_id": model_id,
        "channel_account_id": channel_account_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(sale_id: str, component: str = "BURNER",
                                  failure_description: str = "Component failed in normal use",
                                  **overrides) -> dict:
    defaults = {
        "sale_id": sale_id,
        "component": component,
        "failure_description": failure_description,
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    n = unique_suffix()
    defaults = {
        "part_number": f"PRT-{n}",
        "component": "BURNER",
        "compatible_model_codes": ["GX-100"],
        "supersession_chain_id": f"CH-{n}",
        "chain_position": 1,
        "unit_cost_cents": 3200,
        "stock_quantity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_parts_order_payload(part_id: str, sale_id: str, quantity: int = 1,
                               fulfillment_type: str = "PAID", **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "sale_id": sale_id,
        "quantity": quantity,
        "fulfillment_type": fulfillment_type,
    }
    defaults.update(overrides)
    return defaults


def create_device_pair_payload(sale_id: str, app_account_id: str = None,
                               **overrides) -> dict:
    defaults = {
        "sale_id": sale_id,
        "app_account_id": app_account_id or f"acct-{unique_suffix()}",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Action / lifecycle payloads
# ---------------------------------------------------------------------------
def advance_season_payload(target_status: str) -> dict:
    return {"target_status": target_status}


def model_lifecycle_payload(action: str) -> dict:
    return {"action": action}


def respond_allocation_payload(action: str, expected_allocation_version: int,
                               allocated_units: int = None) -> dict:
    payload = {"action": action, "expected_allocation_version": expected_allocation_version}
    if allocated_units is not None:
        payload["allocated_units"] = allocated_units
    return payload


def assembler_status_payload(action: str) -> dict:
    return {"action": action}


def job_assign_payload(assembler_id: str, window_start: str, window_end: str) -> dict:
    return {
        "action": "ASSIGN",
        "assembler_id": assembler_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def job_action_payload(action: str) -> dict:
    return {"action": action}


def sale_transition_payload(action: str, proof_of_purchase_token: str = None) -> dict:
    payload = {"action": action}
    if proof_of_purchase_token is not None:
        payload["proof_of_purchase_token"] = proof_of_purchase_token
    return payload


def adjudicate_claim_payload(action: str, goodwill_justification: str = None,
                             actual_labor_cents: int = None) -> dict:
    payload = {"action": action}
    if goodwill_justification is not None:
        payload["goodwill_justification"] = goodwill_justification
    if actual_labor_cents is not None:
        payload["actual_labor_cents"] = actual_labor_cents
    return payload


def part_transition_payload(action: str, quantity: int = None,
                            successor_part_id: str = None) -> dict:
    payload = {"action": action}
    if quantity is not None:
        payload["quantity"] = quantity
    if successor_part_id is not None:
        payload["successor_part_id"] = successor_part_id
    return payload


def parts_order_transition_payload(action: str) -> dict:
    return {"action": action}


def firmware_payload(action: str, target_version: str = None) -> dict:
    payload = {"action": action}
    if target_version is not None:
        payload["target_version"] = target_version
    return payload


# ---------------------------------------------------------------------------
# Clock driving (PRD 2.4: PlannerAdmin-only test-driving capability)
# ---------------------------------------------------------------------------
def set_logical_clock(to_iso8601: str) -> dict:
    """Set the server logical clock via POST /grillops/_clock/set_current_utc.

    Returns the clock payload ({"current_utc": ...}). Every fixture routes clock
    movement through here so a test never touches the clock endpoint raw.
    """
    resp = api_client.set_clock(
        create_clock_payload(to_iso8601),
        headers=TEST_USERS["planner_admin_headers"],
    )
    return get_success_data(resp)


__all__ = [
    "unique_suffix",
    "unique_serial",
    "create_clock_payload",
    "create_season_payload",
    "create_model_payload",
    "create_channel_payload",
    "create_lot_payload",
    "create_allocation_payload",
    "create_assembler_payload",
    "create_assembly_job_payload",
    "create_accessory",
    "create_sale_payload",
    "create_warranty_claim_payload",
    "create_part_payload",
    "create_parts_order_payload",
    "create_device_pair_payload",
    "advance_season_payload",
    "model_lifecycle_payload",
    "respond_allocation_payload",
    "assembler_status_payload",
    "job_assign_payload",
    "job_action_payload",
    "sale_transition_payload",
    "adjudicate_claim_payload",
    "part_transition_payload",
    "parts_order_transition_payload",
    "firmware_payload",
    "set_logical_clock",
    "DEFAULT_CLOCK_ISO",
]
