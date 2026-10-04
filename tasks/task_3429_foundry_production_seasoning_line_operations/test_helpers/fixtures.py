"""Composite setup fixtures — multi-step API chains the test designs rely on.

Everything here is built from API calls through the shared client (never from
implementation internals) and uses get_success_data so a setup failure surfaces
as a clear "Setup failed" message rather than an assertion tangle.

Identity defaults (op-1 / qi-1 / sl-1 / eo-1 / eo-2 / fm-1 / rp-1 / om-1) are
distinct across roles, so segregation-of-duties checks pass on the happy path;
the breach-remediation chain uses eo-1 to cause the breach and eo-2 (or fm-1)
to clear it, per the PRD §2.1 segregation rules.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_certify_chemistry_payload,
    create_charge_payload,
    create_chemistry_readings_payload,
    create_clock_payload,
    create_disposition_payload,
    create_emissions_reading_payload,
    create_environmental_permit_payload,
    create_inspect_payload,
    create_melt_batch_payload,
    create_mold_payload,
    create_order_completion_payload,
    create_outlet_sale_payload,
    create_pour_payload,
    create_product_payload,
    create_production_order_payload,
    create_qa_release_payload,
    create_reclaim_payload,
    create_retail_allocation_payload,
    create_seasoning_batch_payload,
    create_start_bake_payload,
    create_tap_payload,
)
from .test_users import TEST_USERS

_FM = TEST_USERS["foundry_manager_headers"]
_OP = TEST_USERS["melt_operator_headers"]
_QI = TEST_USERS["quality_inspector_headers"]
_SL = TEST_USERS["seasoning_lead_headers"]
_EO = TEST_USERS["environmental_officer_headers"]
_EO2 = TEST_USERS["environmental_officer_2_headers"]
_RP = TEST_USERS["retail_planner_headers"]
_OM = TEST_USERS["outlet_manager_headers"]


class SetupFailedError(AssertionError):
    """Raised when a fixture setup call does not return the expected status."""


def _setup(resp, expected_status, step):
    data = get_success_data(resp)
    actual = resp.status_code
    if actual != expected_status:
        raise SetupFailedError(
            f"Setup failed at step '{step}': expected HTTP {expected_status}, "
            f"got {actual}: {resp.text}")
    return data


# --- Logical clock (PRD §2.4) --------------------------------------------------

def advance_clock(to_iso8601, headers=None):
    """Advance the logical clock via the API. Returns the new current_utc.

    Fixture datetimes must stay strictly monotonic: the supplied instant must
    be strictly after the current logical time (initial 2026-09-01T00:00:00Z).
    """
    resp = api_client.set_clock(create_clock_payload(to_iso8601), headers or _FM)
    data = _setup(resp, 200, "set clock")
    return data["current_utc"]


# --- Granular step helpers ------------------------------------------------------

def create_product(headers=None, **overrides):
    resp = api_client.create_product(create_product_payload(**overrides),
                                     headers or _FM)
    return _setup(resp, 201, "create product")


def get_product(product_id, headers=None):
    resp = api_client.get_product(product_id, headers or _FM)
    return _setup(resp, 200, "get product")


def discontinue_product(product_id, headers=None):
    resp = api_client.discontinue_product(product_id, headers or _FM)
    return _setup(resp, 200, "discontinue product")


def create_order(product_id, headers=None, **overrides):
    resp = api_client.create_production_order(
        create_production_order_payload(product_id, **overrides), headers or _FM)
    return _setup(resp, 201, "create production order")


def get_order(order_id, headers=None):
    resp = api_client.get_production_order(order_id, headers or _FM)
    return _setup(resp, 200, "get production order")


def get_order_version(order_id, headers=None):
    return get_order(order_id, headers)["version"]


def release_order(order_id, headers=None):
    resp = api_client.release_production_order(order_id, headers or _FM)
    return _setup(resp, 200, "release production order")


def complete_order(order_id, headers=None, **overrides):
    resp = api_client.complete_production_order(
        order_id, create_order_completion_payload(**overrides), headers or _FM)
    return _setup(resp, 200, "complete production order")


def cancel_order(order_id, headers=None):
    resp = api_client.cancel_production_order(order_id, headers or _FM)
    return _setup(resp, 200, "cancel production order")


def create_melt(order_id, expected_version=None, headers=None, **overrides):
    """Create a melt batch, OCC-pinning the order's CURRENT version unless
    expected_version is supplied explicitly (PRD §2.6)."""
    if expected_version is None:
        expected_version = get_order_version(order_id)
    resp = api_client.create_melt_batch(
        create_melt_batch_payload(order_id, expected_version, **overrides),
        headers or _OP)
    return _setup(resp, 201, "create melt batch")


def get_melt(batch_id, headers=None):
    resp = api_client.get_melt_batch(batch_id, headers or _OP)
    return _setup(resp, 200, "get melt batch")


def charge_melt(batch_id, headers=None, **overrides):
    resp = api_client.charge_melt_batch(batch_id, create_charge_payload(**overrides),
                                        headers or _OP)
    return _setup(resp, 200, "charge melt batch")


def record_chemistry(batch_id, headers=None, **overrides):
    resp = api_client.record_chemistry_readings(
        batch_id, create_chemistry_readings_payload(**overrides), headers or _OP)
    return _setup(resp, 200, "record chemistry readings")


def certify_melt(batch_id, decision="CERTIFY", headers=None):
    resp = api_client.certify_chemistry(
        batch_id, create_certify_chemistry_payload(decision), headers or _QI)
    return _setup(resp, 200, "certify chemistry")


def tap_melt(batch_id, headers=None, **overrides):
    resp = api_client.tap_melt_batch(batch_id, create_tap_payload(**overrides),
                                     headers or _OP)
    return _setup(resp, 200, "tap melt batch")


def create_mold_for_order(order_id, headers=None, **overrides):
    resp = api_client.create_mold(create_mold_payload(order_id, **overrides),
                                  headers or _FM)
    return _setup(resp, 201, "create mold")


def get_mold(order_id, mold_id, headers=None):
    """Molds have no single-resource GET; resolve via the order's mold list."""
    resp = api_client.list_order_molds(order_id, headers or _FM,
                                       params={"limit": 100})
    molds = _setup(resp, 200, "list order molds")
    for mold in molds:
        if mold["id"] == mold_id:
            return mold
    raise SetupFailedError(f"mold {mold_id} not found under order {order_id}")


def pour_units(batch_id, mold_id, unit_count=1, pour_weight_per_unit_oz=128.0,
               headers=None):
    """Pour `unit_count` castings; returns the list of created unit dicts."""
    resp = api_client.pour_melt_batch(
        batch_id,
        create_pour_payload(mold_id, unit_count=unit_count,
                            pour_weight_per_unit_oz=pour_weight_per_unit_oz),
        headers or _OP)
    return _setup(resp, 201, "pour units")


def shakeout(mold_id, headers=None):
    resp = api_client.shakeout_mold(mold_id, headers or _OP)
    return _setup(resp, 200, "shakeout mold")


def get_unit(unit_id, headers=None):
    resp = api_client.get_casting_unit(unit_id, headers or _QI)
    return _setup(resp, 200, "get casting unit")


def inspect_unit_pass(unit_id, headers=None, **overrides):
    resp = api_client.inspect_casting_unit(
        unit_id, create_inspect_payload("PASS", **overrides), headers or _QI)
    return _setup(resp, 200, "inspect unit PASS")


def inspect_unit_defect(unit_id, defect_type="POROSITY", severity="MAJOR",
                        notes=None, headers=None, **overrides):
    """Inspect with outcome DEFECT; returns (unit, open_report_id)."""
    payload = create_inspect_payload("DEFECT", defect_type=defect_type,
                                     severity=severity, notes=notes, **overrides)
    resp = api_client.inspect_casting_unit(unit_id, payload, headers or _QI)
    unit = _setup(resp, 200, "inspect unit DEFECT")
    resp = api_client.list_unit_defect_reports(unit_id, headers or _QI)
    reports = _setup(resp, 200, "list unit defect reports")
    open_reports = [r for r in reports if r["status"] == "OPEN"]
    if not open_reports:
        raise SetupFailedError(f"no OPEN defect report found for unit {unit_id}")
    return unit, open_reports[-1]["id"]


def disposition_report(report_id, disposition, headers=None):
    resp = api_client.disposition_defect_report(
        report_id, create_disposition_payload(disposition), headers or _QI)
    return _setup(resp, 200, f"disposition report {disposition}")


def complete_rework(unit_id, headers=None):
    resp = api_client.complete_rework(unit_id, headers or _OP)
    return _setup(resp, 200, "complete rework")


def scrap_unit_via_defect(unit_id, defect_type="POROSITY", severity="MAJOR",
                          headers=None):
    """DEFECT-inspect then SCRAP-disposition. Returns (scrapped_unit, report)."""
    _, report_id = inspect_unit_defect(unit_id, defect_type=defect_type,
                                       severity=severity, headers=headers)
    report = disposition_report(report_id, "SCRAP", headers=headers)
    return get_unit(unit_id), report


def rework_unit_via_defect(unit_id, defect_type="POROSITY", severity="MINOR",
                           headers=None):
    """One full rework loop: DEFECT -> REWORK -> complete-rework ->
    SHAKEOUT_DONE. Returns the unit back in SHAKEOUT_DONE."""
    _, report_id = inspect_unit_defect(unit_id, defect_type=defect_type,
                                       severity=severity, headers=headers)
    disposition_report(report_id, "REWORK", headers=headers)
    return complete_rework(unit_id)


def create_seasoning_batch(order_id, unit_ids, headers=None, **overrides):
    resp = api_client.create_seasoning_batch(
        create_seasoning_batch_payload(order_id, unit_ids, **overrides),
        headers or _SL)
    return _setup(resp, 201, "create seasoning batch")


def get_seasoning_batch(batch_id, headers=None):
    resp = api_client.get_seasoning_batch(batch_id, headers or _SL)
    return _setup(resp, 200, "get seasoning batch")


def start_bake(batch_id, headers=None, **overrides):
    resp = api_client.start_bake(batch_id, create_start_bake_payload(**overrides),
                                 headers or _SL)
    return _setup(resp, 200, "start bake")


def qa_release(batch_id, headers=None, **overrides):
    resp = api_client.qa_release_seasoning_batch(
        batch_id, create_qa_release_payload(**overrides), headers or _QI)
    return _setup(resp, 200, "qa release")


# --- Composite chains ------------------------------------------------------------
# Every composite returns a context dict of the resource snapshots it created.

def setup_released_order(product_overrides=None, order_overrides=None):
    """Product + order + release. Order is MOLDING, posture OPEN."""
    product = create_product(**(product_overrides or {}))
    order = create_order(product["id"], **(order_overrides or {}))
    order = release_order(order["id"])
    return {"product": product, "order": order}


def setup_charging_melt(melt_overrides=None, **order_kwargs):
    """Released order + one melt batch in CHARGING."""
    ctx = setup_released_order(**order_kwargs)
    melt = create_melt(ctx["order"]["id"], **(melt_overrides or {}))
    ctx["melt"] = melt
    return ctx


def setup_certified_melt(melt_overrides=None, chemistry_overrides=None,
                         **order_kwargs):
    """Melt walked to CERTIFIED (charge -> readings -> CERTIFY)."""
    ctx = setup_charging_melt(melt_overrides=melt_overrides, **order_kwargs)
    batch_id = ctx["melt"]["id"]
    charge_melt(batch_id)
    record_chemistry(batch_id, **(chemistry_overrides or {}))
    ctx["melt"] = certify_melt(batch_id)
    return ctx


def setup_tapped_melt(tap_overrides=None, **kwargs):
    """Melt walked to TAPPED (certified, then tapped; iron ledger open)."""
    ctx = setup_certified_melt(**kwargs)
    ctx["melt"] = tap_melt(ctx["melt"]["id"], **(tap_overrides or {}))
    return ctx


def setup_poured_units(num_units=3, pour_weight_per_unit_oz=128.0,
                       mold_overrides=None, **kwargs):
    """Tapped melt + mold + pour. Units are POURED; order is POURING.

    The default tap (2010 lbs) covers about 250 units at 128 oz; pass
    tap_overrides={"tapped_lbs": ...} for larger pours.
    """
    ctx = setup_tapped_melt(**kwargs)
    mold = create_mold_for_order(ctx["order"]["id"], **(mold_overrides or {}))
    units = pour_units(ctx["melt"]["id"], mold["id"], unit_count=num_units,
                       pour_weight_per_unit_oz=pour_weight_per_unit_oz)
    ctx["mold"] = mold
    ctx["units"] = units
    ctx["unit_ids"] = [u["id"] for u in units]
    return ctx


def setup_shaken_units(num_units=3, **kwargs):
    """Poured units shaken out: units SHAKEOUT_DONE, mold SHAKEOUT_DONE."""
    ctx = setup_poured_units(num_units=num_units, **kwargs)
    ctx["mold"] = shakeout(ctx["mold"]["id"])
    return ctx


def setup_finished_units(num_units=3, inspect_overrides=None, **kwargs):
    """All poured units inspected PASS: units FINISHED, order FINISHING."""
    ctx = setup_shaken_units(num_units=num_units, **kwargs)
    for unit_id in ctx["unit_ids"]:
        inspect_unit_pass(unit_id, **(inspect_overrides or {}))
    ctx["units"] = [get_unit(u) for u in ctx["unit_ids"]]
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_seasoning_batch_ctx(num_units=3, seasoning_overrides=None, **kwargs):
    """Finished units queued into a COATING seasoning batch.

    The batch's creation moves the order to SEASONING (first batch)."""
    ctx = setup_finished_units(num_units=num_units, **kwargs)
    batch = create_seasoning_batch(ctx["order"]["id"], ctx["unit_ids"],
                                   **(seasoning_overrides or {}))
    ctx["seasoning_batch"] = batch
    return ctx


def setup_baking_batch(bake_overrides=None, **kwargs):
    """Seasoning batch walked to BAKING (start-bake recorded by sl-1)."""
    ctx = setup_seasoning_batch_ctx(**kwargs)
    ctx["seasoning_batch"] = start_bake(ctx["seasoning_batch"]["id"],
                                        **(bake_overrides or {}))
    return ctx


def setup_seasoned_units(num_units=3, qa_overrides=None, **kwargs):
    """Full line: batch RELEASED; units SEASONED; inventory credited.

    order_overrides default planned_quantity == num_units keeps the 85% yield
    gate satisfied for a later completion. on_hand_units == num_units.
    """
    kwargs.setdefault("order_overrides", {"planned_quantity": num_units})
    ctx = setup_baking_batch(num_units=num_units, **kwargs)
    ctx["seasoning_batch"] = qa_release(ctx["seasoning_batch"]["id"],
                                        **(qa_overrides or {}))
    ctx["units"] = [get_unit(u) for u in ctx["unit_ids"]]
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_completed_order(num_units=3, completion_overrides=None, **kwargs):
    """Full lifecycle to COMPLETE: seasoned units, then order completion with
    labor/energy actuals. Post-completion lockdown tests start here."""
    ctx = setup_seasoned_units(num_units=num_units, **kwargs)
    ctx["order"] = complete_order(ctx["order"]["id"],
                                  **(completion_overrides or {}))
    return ctx


def setup_restricted_order(num_units=25, scrap_count=2, scrap_severity="MINOR",
                           **kwargs):
    """Order driven to posture RESTRICTED by defect scrap: with the defaults,
    2 plain scraps over 25 poured units gives scrap_index exactly 0.0800 (RED).

    Units 0..scrap_count-1 are scrapped; the rest stay SHAKEOUT_DONE.
    """
    ctx = setup_shaken_units(num_units=num_units, **kwargs)
    ctx["scrapped_unit_ids"] = []
    for unit_id in ctx["unit_ids"][:scrap_count]:
        scrap_unit_via_defect(unit_id, severity=scrap_severity)
        ctx["scrapped_unit_ids"].append(unit_id)
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


# --- Environmental permits (PRD §3.7) ------------------------------------------

def create_permit(permit_type="AIR_EMISSIONS", limit_value=100.0,
                  measurement_unit=None, headers=None, **overrides):
    if measurement_unit is None:
        measurement_unit = "rate" if permit_type == "SAND_RECLAMATION" else "mg_m3"
    resp = api_client.create_environmental_permit(
        create_environmental_permit_payload(
            permit_type=permit_type, limit_value=limit_value,
            measurement_unit=measurement_unit, **overrides),
        headers or _EO)
    return _setup(resp, 201, "create environmental permit")


def get_permit(permit_id, headers=None):
    resp = api_client.get_environmental_permit(permit_id, headers or _EO)
    return _setup(resp, 200, "get environmental permit")


def record_reading(permit_id, reading_value, source="MELT_FURNACE", headers=None):
    resp = api_client.record_emissions_reading(
        permit_id,
        create_emissions_reading_payload(reading_value, source=source),
        headers or _EO)
    return _setup(resp, 201, "record emissions reading")


def warn_permit(permit_id, limit_value, headers=None):
    """One over-limit reading: ACTIVE -> WARNING with count 1."""
    record_reading(permit_id, reading_value=limit_value * 1.2, headers=headers)
    return get_permit(permit_id)


def breach_permit_with_readings(permit_id, limit_value, headers=None):
    """Counting-path breach: two over-limit readings in the same calendar
    month (default clock is September 2026). Returns the BREACH permit."""
    record_reading(permit_id, reading_value=limit_value * 1.2, headers=headers)
    record_reading(permit_id, reading_value=limit_value * 1.3, headers=headers)
    return get_permit(permit_id)


def breach_permit_immediately(permit_id, limit_value, headers=None):
    """Immediate breach: one reading at exactly 1.5x the limit."""
    record_reading(permit_id, reading_value=limit_value * 1.5, headers=headers)
    return get_permit(permit_id)


def acknowledge_breach(permit_id, headers=None):
    resp = api_client.acknowledge_breach(permit_id, headers or _FM)
    return _setup(resp, 200, "acknowledge breach")


def certify_remediation(permit_id, headers=None):
    resp = api_client.certify_remediation(permit_id, headers or _EO2)
    return _setup(resp, 200, "certify remediation")


def remediate_permit(permit_id, manager_headers=None, officer_headers=None):
    """Full two-person recovery chain: acknowledge (manager) then certify
    (a SECOND officer, not the one whose reading caused the breach).
    Returns the ACTIVE permit."""
    acknowledge_breach(permit_id, headers=manager_headers)
    return certify_remediation(permit_id, headers=officer_headers)


def reclaim_mold(mold_id, reclaimed_sand_lbs=450.0, dust_collected_lbs=50.0,
                 headers=None):
    resp = api_client.reclaim_mold(
        mold_id,
        create_reclaim_payload(reclaimed_sand_lbs=reclaimed_sand_lbs,
                               dust_collected_lbs=dust_collected_lbs),
        headers or _EO)
    return _setup(resp, 200, "reclaim mold")


def setup_frozen_order(melt_stage="CERTIFIED", permit_limit=100.0, **kwargs):
    """AIR_EMISSIONS breach freeze: certified in-flight melt held, order FROZEN.

    melt_stage controls how far the melt gets before the breach:
    "CHARGING", "MELTING", "CHEMISTRY_CHECK", or "CERTIFIED" (default).
    Returns ctx with keys product, order, melt, permit.
    """
    ctx = setup_released_order(**kwargs)
    permit = create_permit("AIR_EMISSIONS", limit_value=permit_limit)
    melt = create_melt(ctx["order"]["id"])
    batch_id = melt["id"]
    if melt_stage in ("MELTING", "CHEMISTRY_CHECK", "CERTIFIED"):
        melt = charge_melt(batch_id)
    if melt_stage in ("CHEMISTRY_CHECK", "CERTIFIED"):
        melt = record_chemistry(batch_id)
    if melt_stage == "CERTIFIED":
        melt = certify_melt(batch_id)
    ctx["melt"] = melt
    ctx["permit"] = breach_permit_with_readings(permit["id"], permit_limit)
    ctx["melt"] = get_melt(batch_id)
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


# --- Inventory, allocations, outlet sales (PRD §3.8) ----------------------------

def get_inventory_record_for_product(product_id, headers=None):
    resp = api_client.list_inventory_records(headers or _RP,
                                             params={"product_id": product_id})
    records = _setup(resp, 200, "list inventory records")
    if not records:
        raise SetupFailedError(f"no inventory record for product {product_id}")
    return records[0]


def get_inventory_record(record_id, headers=None):
    resp = api_client.get_inventory_record(record_id, headers or _RP)
    return _setup(resp, 200, "get inventory record")


def get_inventory_version(record_id, headers=None):
    return get_inventory_record(record_id, headers)["version"]


def setup_inventory_with_stock(num_units=3, **kwargs):
    """Full production run so the product's InventoryRecord holds num_units
    on hand. Returns the seasoned-units ctx plus inventory_record."""
    ctx = setup_seasoned_units(num_units=num_units, **kwargs)
    ctx["inventory_record"] = get_inventory_record_for_product(ctx["product"]["id"])
    return ctx


def create_allocation(record_id, allocated_qty=1, channel="RETAIL_CHAIN",
                      ship_week="2026-11-16", expected_version=None,
                      headers=None, **overrides):
    """Create a PROPOSED allocation, OCC-pinning the record's CURRENT version
    unless expected_version is supplied explicitly (PRD §2.6)."""
    if expected_version is None:
        expected_version = get_inventory_version(record_id)
    resp = api_client.create_retail_allocation(
        create_retail_allocation_payload(
            record_id, expected_version, allocated_qty=allocated_qty,
            channel=channel, ship_week=ship_week, **overrides),
        headers or _RP)
    return _setup(resp, 201, "create retail allocation")


def get_allocation(allocation_id, headers=None):
    resp = api_client.get_retail_allocation(allocation_id, headers or _RP)
    return _setup(resp, 200, "get retail allocation")


def confirm_allocation(allocation_id, headers=None):
    resp = api_client.confirm_retail_allocation(allocation_id, headers or _RP)
    return _setup(resp, 200, "confirm retail allocation")


def cancel_allocation(allocation_id, headers=None):
    resp = api_client.cancel_retail_allocation(allocation_id, headers or _RP)
    return _setup(resp, 200, "cancel retail allocation")


def ship_allocation(allocation_id, headers=None):
    resp = api_client.ship_retail_allocation(allocation_id, headers or _RP)
    return _setup(resp, 200, "ship retail allocation")


def setup_confirmed_allocation(num_units=3, allocated_qty=1,
                               ship_week="2026-11-16", channel="RETAIL_CHAIN",
                               **kwargs):
    """Stocked inventory + one CONFIRMED allocation. Returns ctx with
    inventory_record and allocation keys."""
    ctx = setup_inventory_with_stock(num_units=num_units, **kwargs)
    allocation = create_allocation(ctx["inventory_record"]["id"],
                                   allocated_qty=allocated_qty, channel=channel,
                                   ship_week=ship_week)
    allocation = confirm_allocation(allocation["id"])
    ctx["allocation"] = allocation
    ctx["inventory_record"] = get_inventory_record(ctx["inventory_record"]["id"])
    return ctx


def record_outlet_sale(product_id, qty=1, unit_price_cents=2200,
                       channel="FACTORY_OUTLET", headers=None, **overrides):
    resp = api_client.create_outlet_sale(
        create_outlet_sale_payload(product_id, qty=qty,
                                   unit_price_cents=unit_price_cents,
                                   channel=channel, **overrides),
        headers or _OM)
    return _setup(resp, 201, "record outlet sale")
