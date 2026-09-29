"""
Composite setups built exclusively out of PRD endpoints.

The server is restarted before every test, so each of these helpers starts from
an empty database and drives state forward through public calls only.  Every
setup call is unwrapped with `get_success_data`, which turns a broken
precondition into a clear "Setup step failed" message instead of a confusing
assertion inside the test body.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import EthanolOpsApiClient
from .test_users import (
    COMPLIANCE_OFFICER,
    GRAIN_ACCOUNTANT,
    GRAIN_BUYER,
    LOGISTICS_COORDINATOR,
    PLANT_MANAGER,
    PROCESS_OPERATOR,
    RISK_MANAGER,
    SCALE_OPERATOR,
)

# ─── Tier 1: the facility, the clock and the marks ─────

def advance_clock(api: EthanolOpsApiClient, instant: str, headers=PLANT_MANAGER) -> None:
    """Drive the logical clock forward to `instant`."""
    get_success_data(api.set_clock(instant, headers))


def commission_plant(api: EthanolOpsApiClient, **overrides) -> Dict[str, Any]:
    """Commission the singleton plant, taking every declared default."""
    return get_success_data(
        api.create_plant(f.plant_payload(**overrides), PLANT_MANAGER)
    )


def commission_plant_with_low_floor(
    api: EthanolOpsApiClient, coverage_floor_bushels: int = 5000, **overrides
) -> Dict[str, Any]:
    """
    A plant whose coverage floor is low enough that one ordinary contract keeps
    procurement `ADEQUATE`, so the grind cap stays at the unrestricted base.
    """
    overrides.setdefault("coverage_floor_bushels", coverage_floor_bushels)
    return commission_plant(api, **overrides)


def post_marks(
    api: EthanolOpsApiClient, plant_id: str, headers=PLANT_MANAGER, **overrides
) -> Dict[str, Any]:
    """Post all five market marks for a contract month."""
    return get_success_data(
        api.post_market_marks(plant_id, f.market_marks_payload(**overrides), headers)
    )


def read_plant(api: EthanolOpsApiClient, plant_id: str, headers=PLANT_MANAGER) -> Dict[str, Any]:
    return get_success_data(api.get_plant(plant_id, headers))


# ─── Tier 2: the tank farm ─────────────────────────────

def commission_tank(
    api: EthanolOpsApiClient,
    tank_code: str,
    product_type: str,
    capacity_gallons: float = 1000000.00,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_tank(
            f.tank_payload(
                tank_code=tank_code,
                product_type=product_type,
                capacity_gallons=capacity_gallons,
                **overrides,
            ),
            PROCESS_OPERATOR,
        )
    )


def standard_tank_farm(
    api: EthanolOpsApiClient,
    neat_opening: Optional[float] = None,
    denaturant_opening: Optional[float] = None,
    e100_opening: Optional[float] = None,
    capacity_gallons: float = 1000000.00,
) -> Dict[str, Dict[str, Any]]:
    """
    One tank of each product type: T-101 neat ethanol, T-201 denaturant and
    T-301 finished denatured E100.
    """
    neat_kwargs = {} if neat_opening is None else {"opening_gallons": neat_opening}
    den_kwargs = {} if denaturant_opening is None else {"opening_gallons": denaturant_opening}
    e100_kwargs = {} if e100_opening is None else {"opening_gallons": e100_opening}
    return {
        "neat": commission_tank(
            api, "T-101", "ETHANOL_200_PROOF", capacity_gallons, **neat_kwargs
        ),
        "denaturant": commission_tank(
            api, "T-201", "DENATURANT", capacity_gallons, **den_kwargs
        ),
        "e100": commission_tank(
            api, "T-301", "DENATURED_E100", capacity_gallons, **e100_kwargs
        ),
    }


def hold_tank(api: EthanolOpsApiClient, tank_id: str, hold_reason: str) -> Dict[str, Any]:
    return get_success_data(
        api.hold_tank(tank_id, f.hold_payload(hold_reason), PROCESS_OPERATOR)
    )


def release_tank(api: EthanolOpsApiClient, tank_id: str) -> Dict[str, Any]:
    return get_success_data(api.release_tank(tank_id, PROCESS_OPERATOR))


# ─── Tier 3: procurement, grading and settlement ───────

def open_contract(api: EthanolOpsApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_contract(f.contract_payload(**overrides), GRAIN_BUYER)
    )


def priced_contract(
    api: EthanolOpsApiClient,
    futures_price_cents_per_bushel: float = 458.0,
    **overrides,
) -> Dict[str, Any]:
    """An OPEN contract whose futures leg has been fixed, so it can settle."""
    contract = open_contract(api, **overrides)
    return get_success_data(
        api.price_contract(
            contract["id"], f.price_payload(futures_price_cents_per_bushel), GRAIN_BUYER
        )
    )


def book_delivery(api: EthanolOpsApiClient, contract_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_delivery(contract_id, f.delivery_payload(**overrides), SCALE_OPERATOR)
    )


def grade_delivery(api: EthanolOpsApiClient, delivery_id: str, **overrides) -> Dict[str, Any]:
    """Grade a booked load at the scale house identity `scale-01`."""
    return get_success_data(
        api.grade_delivery(delivery_id, f.grade_payload(**overrides), SCALE_OPERATOR)
    )


def settle_delivery(api: EthanolOpsApiClient, delivery_id: str) -> Dict[str, Any]:
    """Settle a graded load as grain accounting, a different identity to the grader."""
    return get_success_data(api.settle_delivery(delivery_id, GRAIN_ACCOUNTANT))


def graded_load(
    api: EthanolOpsApiClient,
    contract_id: str,
    delivery_overrides: Optional[Dict[str, Any]] = None,
    grade_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    delivery = book_delivery(api, contract_id, **(delivery_overrides or {}))
    return grade_delivery(api, delivery["id"], **(grade_overrides or {}))


def settled_load(
    api: EthanolOpsApiClient,
    contract_id: str,
    delivery_overrides: Optional[Dict[str, Any]] = None,
    grade_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Book, grade and settle one load.  With the default weights the load is
    940.00 net dry bushels at 440.00 cents per bushel, settling at 413600 cents.
    """
    graded = graded_load(api, contract_id, delivery_overrides, grade_overrides)
    return settle_delivery(api, graded["id"])


def corn_on_hand(
    api: EthanolOpsApiClient,
    bushels_contracted: float = 200000.00,
    delivery_overrides: Optional[Dict[str, Any]] = None,
    grade_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Put settled corn into plant inventory: one priced contract and one settled
    load against it.  Returns both rows.
    """
    contract = priced_contract(api, bushels_contracted=bushels_contracted)
    delivery = settled_load(api, contract["id"], delivery_overrides, grade_overrides)
    return {"contract": contract, "delivery": delivery}


# ─── Tier 4: fermentation ──────────────────────────────

def charge_batch(
    api: EthanolOpsApiClient, destination_tank_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_batch(
            f.batch_payload(destination_tank_id, **overrides), PROCESS_OPERATOR
        )
    )


def append_health_reading(
    api: EthanolOpsApiClient, batch_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_health_reading(
            batch_id, f.health_reading_payload(**overrides), PROCESS_OPERATOR
        )
    )


def fermenting_batch(
    api: EthanolOpsApiClient, destination_tank_id: str, reading: Optional[Dict[str, Any]] = None, **overrides
) -> Dict[str, Any]:
    """A charged batch lifted to FERMENTING by one healthy reading."""
    batch = charge_batch(api, destination_tank_id, **overrides)
    append_health_reading(api, batch["id"], **(reading or {}))
    return get_success_data(api.get_batch(batch["id"], PROCESS_OPERATOR))


def distilling_batch(
    api: EthanolOpsApiClient, destination_tank_id: str, reading: Optional[Dict[str, Any]] = None, **overrides
) -> Dict[str, Any]:
    batch = fermenting_batch(api, destination_tank_id, reading, **overrides)
    return get_success_data(api.distill_batch(batch["id"], PROCESS_OPERATOR))


def completed_batch(
    api: EthanolOpsApiClient, destination_tank_id: str, reading: Optional[Dict[str, Any]] = None, **overrides
) -> Dict[str, Any]:
    """
    A batch walked all the way to COMPLETED, which credits ethanol to the
    destination tank, books the co-products and mints one credit batch.
    """
    batch = distilling_batch(api, destination_tank_id, reading, **overrides)
    return get_success_data(api.complete_batch(batch["id"], PROCESS_OPERATOR))


# ─── Tier 4: blending ──────────────────────────────────

def schedule_blend(
    api: EthanolOpsApiClient,
    neat_source_tank_id: str,
    denaturant_source_tank_id: str,
    destination_tank_id: str,
    expected_destination_tank_version: int,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_blend(
            f.blend_payload(
                neat_source_tank_id,
                denaturant_source_tank_id,
                destination_tank_id,
                expected_destination_tank_version,
                **overrides,
            ),
            PROCESS_OPERATOR,
        )
    )


def executed_blend(
    api: EthanolOpsApiClient,
    neat_source_tank_id: str,
    denaturant_source_tank_id: str,
    destination_tank_id: str,
    expected_destination_tank_version: int,
    **overrides,
) -> Dict[str, Any]:
    blend = schedule_blend(
        api,
        neat_source_tank_id,
        denaturant_source_tank_id,
        destination_tank_id,
        expected_destination_tank_version,
        **overrides,
    )
    return get_success_data(api.execute_blend(blend["id"], PROCESS_OPERATOR))


def denatured_inventory(
    api: EthanolOpsApiClient, gallons: float = 400000.00
) -> Dict[str, Dict[str, Any]]:
    """
    A tank farm whose finished-product tank already holds `gallons` of denatured
    E100, using the commissioning opening balance rather than a blend.
    """
    return standard_tank_farm(api, e100_opening=gallons)


# ─── Tier 4: rail logistics ────────────────────────────

def commission_track(api: EthanolOpsApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_track(f.track_payload(**overrides), LOGISTICS_COORDINATOR)
    )


def schedule_shipment(
    api: EthanolOpsApiClient,
    track_id: str,
    source_tank_id: str,
    expected_track_version: int,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_shipment(
            f.shipment_payload(
                track_id, source_tank_id, expected_track_version, **overrides
            ),
            LOGISTICS_COORDINATOR,
        )
    )


def loaded_shipment(
    api: EthanolOpsApiClient,
    track_id: str,
    source_tank_id: str,
    expected_track_version: int,
    **overrides,
) -> Dict[str, Any]:
    shipment = schedule_shipment(
        api, track_id, source_tank_id, expected_track_version, **overrides
    )
    return get_success_data(api.load_shipment(shipment["id"], LOGISTICS_COORDINATOR))


def documented_shipment(
    api: EthanolOpsApiClient,
    track_id: str,
    source_tank_id: str,
    expected_track_version: int,
    bol_number: str = "BOL-0001",
    **overrides,
) -> Dict[str, Any]:
    """A loaded train carrying its bill of lading, which is where credits separate."""
    shipment = loaded_shipment(
        api, track_id, source_tank_id, expected_track_version, **overrides
    )
    return get_success_data(
        api.issue_bill_of_lading(
            shipment["id"], f.bol_payload(bol_number), LOGISTICS_COORDINATOR
        )
    )


def invoiced_shipment(
    api: EthanolOpsApiClient,
    track_id: str,
    source_tank_id: str,
    expected_track_version: int,
    bol_number: str = "BOL-0001",
    **overrides,
) -> Dict[str, Any]:
    shipment = documented_shipment(
        api, track_id, source_tank_id, expected_track_version, bol_number, **overrides
    )
    return get_success_data(
        api.invoice_shipment(shipment["id"], LOGISTICS_COORDINATOR)
    )


# ─── Tier 4: co-product sales ──────────────────────────

def quote_flat_sale(api: EthanolOpsApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_sale(f.flat_sale_payload(**overrides), GRAIN_BUYER)
    )


def quote_index_sale(api: EthanolOpsApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_sale(f.index_sale_payload(**overrides), GRAIN_BUYER)
    )


def accept_sale(api: EthanolOpsApiClient, sale_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.respond_to_sale(sale_id, f.respond_payload("ACCEPT"), GRAIN_BUYER)
    )


def decline_sale(api: EthanolOpsApiClient, sale_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.respond_to_sale(sale_id, f.respond_payload("DECLINE"), GRAIN_BUYER)
    )


def shipped_sale(api: EthanolOpsApiClient, sale_id: str) -> Dict[str, Any]:
    return get_success_data(api.ship_sale(sale_id, LOGISTICS_COORDINATOR))


# ─── Tier 4: carbon projects ───────────────────────────

def draft_project(api: EthanolOpsApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_carbon_project(f.carbon_project_payload(**overrides), COMPLIANCE_OFFICER)
    )


def submitted_project(api: EthanolOpsApiClient, **overrides) -> Dict[str, Any]:
    project = draft_project(api, **overrides)
    return get_success_data(
        api.submit_carbon_project(project["id"], f.submit_payload(), COMPLIANCE_OFFICER)
    )


def certified_project(
    api: EthanolOpsApiClient,
    verified_reduction_g_per_mj: Optional[float] = None,
    **overrides,
) -> Dict[str, Any]:
    """A project walked DRAFT → SUBMITTED → CERTIFIED, which re-runs the waterfall."""
    project = submitted_project(api, **overrides)
    review = f.review_payload("CERTIFY")
    if verified_reduction_g_per_mj is not None:
        review["verified_reduction_g_per_mj"] = verified_reduction_g_per_mj
    return get_success_data(
        api.review_carbon_project(project["id"], review, PLANT_MANAGER)
    )


# ─── Tier 4: futures book ──────────────────────────────

def open_hedge(api: EthanolOpsApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_hedge_position(f.hedge_payload(**overrides), RISK_MANAGER)
    )


def close_hedge(
    api: EthanolOpsApiClient, position_id: str, contracts_to_close: int, exit_price: float
) -> Dict[str, Any]:
    return get_success_data(
        api.close_hedge_position(
            position_id, f.close_payload(contracts_to_close, exit_price), RISK_MANAGER
        )
    )


# ─── Tier 5: permit conditions ─────────────────────────

def register_condition(api: EthanolOpsApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_permit_condition(
            f.permit_condition_payload(**overrides), COMPLIANCE_OFFICER
        )
    )


def append_permit_reading(
    api: EthanolOpsApiClient,
    condition_id: str,
    measured_at: str,
    value: float,
    sample_reference: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_permit_reading(
            condition_id,
            f.permit_reading_payload(measured_at, value, sample_reference),
            COMPLIANCE_OFFICER,
        )
    )


def condition_in_exceedance(
    api: EthanolOpsApiClient,
    measured_at: str = "2026-09-04T12:00:00Z",
    value: float = 13.000,
    **overrides,
) -> Dict[str, Any]:
    """
    A permit condition driven into EXCEEDANCE by a single reading above its
    limit, which is what raises the plant's compliance posture.
    """
    condition = register_condition(api, **overrides)
    append_permit_reading(api, condition["id"], measured_at, value)
    return get_success_data(
        api.get_permit_condition(condition["id"], COMPLIANCE_OFFICER)
    )
