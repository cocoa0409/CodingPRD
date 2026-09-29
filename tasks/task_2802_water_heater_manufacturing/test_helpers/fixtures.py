"""Composite scenario builders.

The harness restarts the service before every individual test, so each test opens
against an empty store and must build every precondition through the PRD's own
endpoints. These builders assemble the recurring chains once - a qualified
supply base, a certified and released model, a fired lining batch, a released
tank lot, a shipped unit - so tests state only the step under examination.

Every builder uses the lenient success reader so a fixture never masks the
assertion the test itself wants to make.
"""

from types import SimpleNamespace
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import MfgApiClient
from .test_users import (
    USER_APPROVER,
    USER_ENGINEER,
    certification_approver_headers,
    compliance_engineer_headers,
    plant_admin_headers,
    plant_operator_headers,
    quality_inspector_headers,
    supplier_quality_headers,
    warranty_analyst_headers,
    weld_operator_headers,
)
from .types import JsonDict


def data_of(response) -> JsonDict:
    """Read the ``data`` payload of any 2xx response."""
    return get_success_data(response)


def set_clock(api: MfgApiClient, instant: str) -> JsonDict:
    """Move the logical clock; only PlantAdmin may do so."""
    return data_of(api.set_clock(instant, plant_admin_headers()))


def read_clock(api: MfgApiClient) -> JsonDict:
    return data_of(api.read_clock(plant_admin_headers()))


def model_version(api: MfgApiClient, model_id: str) -> int:
    """Read the model's current version for the certification version pin."""
    return data_of(api.get_product_model(model_id, compliance_engineer_headers()))[
        "version"
    ]


def tank_lot_version(api: MfgApiClient, tank_lot_id: str) -> int:
    """Read the lot's current version for the lining-inspection version pin."""
    return data_of(api.get_tank_lot(tank_lot_id, quality_inspector_headers()))["version"]


# ----------------------------------------------------------------------
# Tier 1 - supply base
# ----------------------------------------------------------------------
def make_pending_supplier(api: MfgApiClient, **overrides) -> JsonDict:
    """Register one supplier; it starts PENDING with no score and no expiry."""
    return data_of(
        api.create_supplier(f.supplier_payload(**overrides), supplier_quality_headers())
    )


def make_qualified_supplier(
    api: MfgApiClient, payload: Optional[JsonDict] = None, **qualify_overrides
) -> JsonDict:
    """Register a supplier and score it into a qualified band."""
    supplier = data_of(
        api.create_supplier(payload or f.supplier_payload(), supplier_quality_headers())
    )
    return data_of(
        api.qualify_supplier(
            supplier["id"],
            f.qualify_payload(**qualify_overrides),
            supplier_quality_headers(),
        )
    )


def make_supply_base(api: MfgApiClient) -> SimpleNamespace:
    """Two qualified suppliers with one released lot each: gas control and T&P valve."""
    gas_supplier = make_qualified_supplier(api, f.supplier_payload())
    valve_supplier = data_of(
        api.create_supplier(
            f.safety_valve_supplier_payload(), supplier_quality_headers()
        )
    )
    data_of(
        api.qualify_supplier(
            valve_supplier["id"],
            f.qualify_payload(audit_score=92, defect_ppm=1500, open_capa_count=0),
            supplier_quality_headers(),
        )
    )
    gas_lot = data_of(
        api.create_component_lot(
            f.component_lot_payload(gas_supplier["id"]), supplier_quality_headers()
        )
    )
    data_of(api.release_component_lot(gas_lot["id"], quality_inspector_headers()))
    valve_lot = data_of(
        api.create_component_lot(
            f.safety_valve_lot_payload(valve_supplier["id"]), supplier_quality_headers()
        )
    )
    data_of(api.release_component_lot(valve_lot["id"], quality_inspector_headers()))
    return SimpleNamespace(
        gas_supplier_id=gas_supplier["id"],
        valve_supplier_id=valve_supplier["id"],
        gas_lot_id=gas_lot["id"],
        valve_lot_id=valve_lot["id"],
    )


# ----------------------------------------------------------------------
# Tier 2 - catalogue model, tests and certification
# ----------------------------------------------------------------------
def make_test_cell(api: MfgApiClient, **overrides) -> JsonDict:
    return data_of(api.create_test_cell(f.test_cell_payload(**overrides), plant_admin_headers()))


def make_model(api: MfgApiClient, payload: Optional[JsonDict] = None) -> JsonDict:
    return data_of(
        api.create_product_model(
            payload or f.product_model_payload(), compliance_engineer_headers()
        )
    )


def make_passing_test_suite(
    api: MfgApiClient,
    model_id: str,
    cell_id: str,
    uef_values=(0.585, 0.585, 0.584),
    fhr_value: float = 62.5,
    recovery_value: float = 41.25,
    clock: str = f.CLOCK_AFTER_ALL_WINDOWS,
) -> SimpleNamespace:
    """Schedule and record the three UEF, one FHR and one RECOVERY passing tests.

    The five windows are spaced so that each one clears the cell's per-model
    cooldown, and the clock is advanced past the last window before any result is
    recorded.
    """
    windows = (
        f.WINDOW_AUG02_06_10,
        f.WINDOW_AUG02_22_AUG03_02,
        f.WINDOW_AUG03_14_18,
    )
    uef_ids = []
    for window in windows:
        uef_ids.append(
            data_of(
                api.create_efficiency_test(
                    f.efficiency_test_payload(model_id, cell_id, window=window),
                    compliance_engineer_headers(),
                )
            )["id"]
        )
    fhr_id = data_of(
        api.create_efficiency_test(
            f.efficiency_test_payload(
                model_id,
                cell_id,
                window=f.WINDOW_AUG04_06_10,
                test_type="FIRST_HOUR_RATING",
            ),
            compliance_engineer_headers(),
        )
    )["id"]
    recovery_id = data_of(
        api.create_efficiency_test(
            f.efficiency_test_payload(
                model_id,
                cell_id,
                window=f.WINDOW_AUG04_22_AUG05_02,
                test_type="RECOVERY",
            ),
            compliance_engineer_headers(),
        )
    )["id"]
    set_clock(api, clock)
    for test_id, measured in zip(uef_ids, uef_values):
        data_of(
            api.record_test_result(
                test_id, {"measured_value": measured}, quality_inspector_headers()
            )
        )
    data_of(
        api.record_test_result(
            fhr_id, {"measured_value": fhr_value}, quality_inspector_headers()
        )
    )
    data_of(
        api.record_test_result(
            recovery_id, {"measured_value": recovery_value}, quality_inspector_headers()
        )
    )
    return SimpleNamespace(
        uef_test_ids=tuple(uef_ids), fhr_test_id=fhr_id, recovery_test_id=recovery_id
    )


def make_submitted_certification(
    api: MfgApiClient, model_id: str, submitter: str = USER_ENGINEER
) -> JsonDict:
    """Open a DRAFT certification pinned to the model's current version and submit it."""
    version = model_version(api, model_id)
    cert = data_of(
        api.create_certification(
            f.certification_payload(model_id, version),
            compliance_engineer_headers(submitter),
        )
    )
    return data_of(
        api.submit_certification(cert["id"], compliance_engineer_headers(submitter))
    )


def make_certified_model(
    api: MfgApiClient,
    model_payload: Optional[JsonDict] = None,
    cell_payload: Optional[JsonDict] = None,
    approver: str = USER_APPROVER,
) -> SimpleNamespace:
    """A model carrying CERTIFIED on its certification dimension and DRAFT on release."""
    model = make_model(api, model_payload)
    cell = data_of(
        api.create_test_cell(cell_payload or f.test_cell_payload(), plant_admin_headers())
    )
    tests = make_passing_test_suite(api, model["id"], cell["id"])
    cert = make_submitted_certification(api, model["id"])
    data_of(
        api.approve_certification(
            cert["id"], f.approve_payload(), certification_approver_headers(approver)
        )
    )
    return SimpleNamespace(
        model_id=model["id"],
        cell_id=cell["id"],
        cert_id=cert["id"],
        uef_test_ids=tests.uef_test_ids,
        fhr_test_id=tests.fhr_test_id,
        recovery_test_id=tests.recovery_test_id,
    )


def make_released_model(api: MfgApiClient, **kwargs) -> SimpleNamespace:
    """A model that is CERTIFIED and RELEASED, so labelling and shipping are open."""
    ctx = make_certified_model(api, **kwargs)
    data_of(api.release_model_to_channel(ctx.model_id, compliance_engineer_headers()))
    return ctx


# ----------------------------------------------------------------------
# Tier 3 - furnace, lining batch and tank lots
# ----------------------------------------------------------------------
def make_fired_batch(
    api: MfgApiClient,
    furnace_overrides: Optional[JsonDict] = None,
    batch_overrides: Optional[JsonDict] = None,
    clock: Optional[str] = f.CLOCK_AFTER_ALL_WINDOWS,
) -> SimpleNamespace:
    """A furnace with one batch whose firing window has elapsed and been fired."""
    furnace = data_of(
        api.create_furnace(f.furnace_payload(**(furnace_overrides or {})), plant_admin_headers())
    )
    batch = data_of(
        api.create_lining_batch(
            f.lining_batch_payload(furnace["id"], **(batch_overrides or {})),
            plant_operator_headers(),
        )
    )
    if clock is not None:
        set_clock(api, clock)
    data_of(api.fire_lining_batch(batch["id"], plant_operator_headers()))
    return SimpleNamespace(furnace_id=furnace["id"], batch_id=batch["id"])


def make_lined_tank_lot(
    api: MfgApiClient, model_id: str, batch_id: str, **lot_overrides
) -> str:
    """A lot welded by the weld operator and lined from a fired batch."""
    lot = data_of(
        api.create_tank_lot(
            f.tank_lot_payload(model_id, **lot_overrides), plant_operator_headers()
        )
    )
    data_of(api.weld_tank_lot(lot["id"], weld_operator_headers()))
    data_of(
        api.apply_lining(
            lot["id"], {"glass_lining_batch_id": batch_id}, plant_operator_headers()
        )
    )
    return lot["id"]


def make_verified_tank_lot(
    api: MfgApiClient, model_id: str, batch_id: str, **lot_overrides
) -> str:
    """A lined lot with one CURRENT passing record of each inspection type."""
    lot_id = make_lined_tank_lot(api, model_id, batch_id, **lot_overrides)
    data_of(
        api.create_lining_inspection(
            f.adhesion_inspection_payload(lot_id, tank_lot_version(api, lot_id)),
            quality_inspector_headers(),
        )
    )
    data_of(
        api.create_lining_inspection(
            f.holiday_inspection_payload(lot_id, tank_lot_version(api, lot_id)),
            quality_inspector_headers(),
        )
    )
    return lot_id


def make_released_tank_lot(
    api: MfgApiClient, model_id: str, batch_id: str, **lot_overrides
) -> str:
    """A lot carried all the way to RELEASED, so its whole plan is good tanks."""
    lot_id = make_verified_tank_lot(api, model_id, batch_id, **lot_overrides)
    data_of(api.foam_tank_lot(lot_id, f.foam_payload(), plant_operator_headers()))
    data_of(api.jacket_tank_lot(lot_id, plant_operator_headers()))
    data_of(api.release_tank_lot(lot_id, plant_operator_headers()))
    return lot_id


# ----------------------------------------------------------------------
# Tier 4 - the whole plant, ready to stage units
# ----------------------------------------------------------------------
def make_full_plant(api: MfgApiClient, planned_quantity: int = 120) -> SimpleNamespace:
    """Qualified supply base, certified and released model, released tank lot.

    This is the standing precondition for every unit-level rule: staging,
    assembly, labelling, shipping, warranty and recall all read from it.
    """
    supply = make_supply_base(api)
    model = make_released_model(api)
    batch = make_fired_batch(api)
    tank_lot_id = make_released_tank_lot(
        api, model.model_id, batch.batch_id, planned_quantity=planned_quantity
    )
    return SimpleNamespace(
        gas_supplier_id=supply.gas_supplier_id,
        valve_supplier_id=supply.valve_supplier_id,
        gas_lot_id=supply.gas_lot_id,
        valve_lot_id=supply.valve_lot_id,
        model_id=model.model_id,
        cell_id=model.cell_id,
        cert_id=model.cert_id,
        uef_test_ids=model.uef_test_ids,
        fhr_test_id=model.fhr_test_id,
        recovery_test_id=model.recovery_test_id,
        furnace_id=batch.furnace_id,
        batch_id=batch.batch_id,
        tank_lot_id=tank_lot_id,
    )


def stage_unit(api: MfgApiClient, plant: SimpleNamespace, **overrides) -> str:
    """Stage one unit against the plant's released lot and both component lots."""
    payload = f.heater_unit_payload(
        plant.tank_lot_id, plant.valve_lot_id, plant.gas_lot_id, **overrides
    )
    return data_of(api.create_heater_unit(payload, plant_operator_headers()))["id"]


def assemble_unit(api: MfgApiClient, plant: SimpleNamespace, **overrides) -> str:
    unit_id = stage_unit(api, plant, **overrides)
    data_of(api.assemble_unit(unit_id, plant_operator_headers()))
    return unit_id


def label_unit(api: MfgApiClient, plant: SimpleNamespace, **overrides) -> str:
    unit_id = assemble_unit(api, plant, **overrides)
    data_of(api.label_unit(unit_id, plant_operator_headers()))
    return unit_id


def ship_unit(
    api: MfgApiClient,
    plant: SimpleNamespace,
    hardness_gpg: float = 8.0,
    channel: str = "TRADE",
    **overrides,
) -> str:
    """Carry one unit all the way to SHIPPED with the given installation water."""
    unit_id = label_unit(api, plant, **overrides)
    data_of(
        api.ship_unit(
            unit_id,
            f.ship_payload(
                install_water_hardness_gpg=hardness_gpg, distribution_channel=channel
            ),
            plant_operator_headers(),
        )
    )
    return unit_id


# ----------------------------------------------------------------------
# Tier 5 - warranty and recall terminal states
# ----------------------------------------------------------------------
def make_open_claim(
    api: MfgApiClient, heater_unit_id: str, **overrides
) -> JsonDict:
    return data_of(
        api.create_warranty_claim(
            f.warranty_claim_payload(heater_unit_id, **overrides),
            warranty_analyst_headers(),
        )
    )


def make_validated_claim(api: MfgApiClient, heater_unit_id: str, **overrides) -> JsonDict:
    claim = make_open_claim(api, heater_unit_id, **overrides)
    return data_of(api.validate_claim(claim["id"], warranty_analyst_headers()))


def make_paid_claim(api: MfgApiClient, heater_unit_id: str, **overrides) -> JsonDict:
    claim = make_validated_claim(api, heater_unit_id, **overrides)
    return data_of(api.pay_claim(claim["id"], warranty_analyst_headers()))


def make_scoped_campaign(
    api: MfgApiClient,
    model_id: str,
    serial_range_start: str,
    serial_range_end: str,
    **campaign_overrides,
) -> JsonDict:
    campaign = data_of(
        api.create_recall_campaign(
            f.recall_campaign_payload(model_id, **campaign_overrides),
            warranty_analyst_headers(),
        )
    )
    return data_of(
        api.scope_campaign(
            campaign["id"],
            f.scope_payload(serial_range_start, serial_range_end),
            warranty_analyst_headers(),
        )
    )


def make_announced_campaign(
    api: MfgApiClient,
    model_id: str,
    serial_range_start: str,
    serial_range_end: str,
    **campaign_overrides,
) -> JsonDict:
    campaign = make_scoped_campaign(
        api, model_id, serial_range_start, serial_range_end, **campaign_overrides
    )
    return data_of(api.announce_campaign(campaign["id"], warranty_analyst_headers()))


def campaign_notices(api: MfgApiClient, campaign_id: str):
    """Every notice the campaign owns, in the order the announce fan-out wrote them."""
    response = api.list_recall_notices(
        warranty_analyst_headers(),
        {"recall_campaign_id": campaign_id, "limit": 100, "offset": 0},
    )
    return get_success_data(response)


def lot_inspections(api: MfgApiClient, tank_lot_id: str, **params):
    """Every inspection record ever written against one lot."""
    query = {"limit": 100, "offset": 0}
    query.update(params)
    response = api.list_lot_lining_inspections(
        tank_lot_id, quality_inspector_headers(), query
    )
    return get_success_data(response)
