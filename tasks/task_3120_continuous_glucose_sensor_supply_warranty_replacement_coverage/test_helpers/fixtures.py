"""Composite setup helpers.

The harness restarts the API server before every test, so each fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls
use get_success_data() so a failure surfaces as a clear "Setup failed" error.

Naming: functions return small dicts of created entities keyed by role in the
scenario (e.g. {"patient": ..., "prescriber": ..., "order": ..., ...}).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_adverse_event_report_payload,
    create_coverage_verification_payload,
    create_device_binding_payload,
    create_patient_payload,
    create_payer_payload,
    create_prescriber_payload,
    create_prescription_payload,
    create_sensor_lot_payload,
    create_sensor_order_payload,
    create_sensor_product_payload,
    create_sensor_unit_payload,
    create_support_enrollment_payload,
    create_warranty_claim_payload,
)
from .test_users import TEST_USERS, make_patient_headers, make_prescriber_headers

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["coverage_reviewer_headers"]
FULFILL = TEST_USERS["fulfillment_agent_headers"]
BILLING = TEST_USERS["billing_agent_headers"]
WARRANTY = TEST_USERS["warranty_reviewer_headers"]
QE = TEST_USERS["quality_engineer_headers"]
SUPPORT = TEST_USERS["patient_support_agent_headers"]

CLOCK_DEFAULT = TEST_DEFAULTS["CLOCK_DEFAULT"]


def _ok(resp, label, expected=None):
    if expected is not None:
        assert resp.status_code == expected, f"Setup failed ({label}): {resp.status_code} {resp.text}"
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed ({label}): {resp.status_code} {resp.text}"
    return data


def set_clock(iso=CLOCK_DEFAULT):
    resp = api_client.set_clock({"to_iso8601": iso}, ADMIN)
    assert resp.status_code == 200, f"Setup failed (set_clock): {resp.status_code} {resp.text}"


# ---------------------------------------------------------------------------
# Tier 1: registry primitives
# ---------------------------------------------------------------------------

def create_patient(**overrides):
    return _ok(api_client.create_patient(create_patient_payload(**overrides), ADMIN), "create patient", 201)


def create_prescriber(**overrides):
    return _ok(api_client.create_prescriber(create_prescriber_payload(**overrides), ADMIN), "create prescriber", 201)


def create_payer(**overrides):
    return _ok(api_client.create_payer(create_payer_payload(**overrides), ADMIN), "create payer", 201)


def create_product(**overrides):
    return _ok(api_client.create_sensor_product(create_sensor_product_payload(**overrides), ADMIN), "create product", 201)


def create_lot(product, **overrides):
    return _ok(
        api_client.create_sensor_lot(product["id"], create_sensor_lot_payload(**overrides), ADMIN),
        "create lot", 201,
    )


def create_units(lot, count, serial_prefix=None):
    """Register `count` serialized units into the lot. Returns list of units."""
    units = []
    for i in range(count):
        payload = create_sensor_unit_payload()
        if serial_prefix is not None:
            payload["serial_number"] = f"{serial_prefix}-{i + 1}"
        units.append(_ok(api_client.create_sensor_unit(lot["id"], payload, ADMIN), "create unit", 201))
    return units


# ---------------------------------------------------------------------------
# Tier 2: prescription + coverage verification
# ---------------------------------------------------------------------------

def create_prescription(patient, prescriber, product, **overrides):
    """Create a prescription; uses the patient's current version for OCC."""
    version = overrides.pop("expected_patient_version", patient["version"])
    payload = create_prescription_payload(prescriber["id"], product["id"], version, **overrides)
    return _ok(
        api_client.create_prescription(patient["id"], payload, make_prescriber_headers(prescriber["id"])),
        "create prescription", 201,
    )


def run_verification(prescription, payer):
    """Run a coverage verification (starts PENDING)."""
    return _ok(
        api_client.create_coverage_verification(
            prescription["id"], create_coverage_verification_payload(payer["id"]), REVIEWER
        ),
        "run verification", 201,
    )


def decide_verification(verification, decision="APPROVED", denial_reason=None):
    payload = {"decision": decision}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return _ok(
        api_client.decide_coverage_verification(verification["id"], payload, REVIEWER),
        "decide verification",
    )


def create_approved_verification(prescription, payer):
    """Run a verification and decide it APPROVED. Returns decided verification."""
    cv = run_verification(prescription, payer)
    return decide_verification(cv, "APPROVED")


# ---------------------------------------------------------------------------
# Tier 3: orders and their lifecycle
# ---------------------------------------------------------------------------

def create_order(patient, prescription, verification, lot, quantity=None):
    qty = quantity if quantity is not None else prescription["quantity_per_fill"]
    payload = create_sensor_order_payload(prescription["id"], verification["id"], lot["id"], qty)
    return _ok(api_client.create_sensor_order(patient["id"], payload, FULFILL), "create order", 201)


def adjudicate_order(order):
    return _ok(
        api_client.adjudicate_sensor_order(order["id"], {"expected_order_version": order["version"]}, BILLING),
        "adjudicate order",
    )


def pick_order(order):
    return _ok(api_client.pick_sensor_order(order["id"], FULFILL), "pick order")


def ship_order(order):
    return _ok(api_client.ship_sensor_order(order["id"], FULFILL), "ship order")


def deliver_order(order):
    return _ok(api_client.deliver_sensor_order(order["id"], FULFILL), "deliver order")


def adjudicate_pick_ship_deliver(order):
    """Walk an order ADJUDICATED -> PICKED -> SHIPPED -> DELIVERED. Returns the
    final order payload."""
    adjudicate_order(order)
    pick_order(order)
    ship_order(order)
    return deliver_order(order)


# ---------------------------------------------------------------------------
# Tier 4: full supply pipeline (registry -> delivered units in hand)
# ---------------------------------------------------------------------------

def setup_supply_pipeline(
    num_units=1,
    quantity_per_fill=1,
    fills_authorized=12,
    payer_overrides=None,
    product_overrides=None,
    patient_overrides=None,
    lot_quantity=10,
):
    """Clock at default; patient, prescriber, product, lot with units, payer,
    prescription, APPROVED verification. Returns a dict of everything."""
    set_clock()
    patient = create_patient(**(patient_overrides or {}))
    prescriber = create_prescriber()
    product = create_product(**(product_overrides or {}))
    lot = create_lot(product, quantity_manufactured=lot_quantity)
    units = create_units(lot, num_units)
    payer = create_payer(**(payer_overrides or {}))
    rx = create_prescription(
        patient, prescriber, product,
        quantity_per_fill=quantity_per_fill, fills_authorized=fills_authorized,
    )
    cv = create_approved_verification(rx, payer)
    return {
        "patient": patient,
        "prescriber": prescriber,
        "product": product,
        "lot": lot,
        "units": units,
        "payer": payer,
        "prescription": rx,
        "verification": cv,
    }


def setup_order_pipeline(**kwargs):
    """setup_supply_pipeline + one created order (PENDING_PICK x UNBILLED)."""
    ctx = setup_supply_pipeline(**kwargs)
    order = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    ctx["order"] = order
    return ctx


def setup_delivered_unit(num_units=1, **kwargs):
    """Full pipeline through delivery: units land IN_HAND with the patient."""
    kwargs.setdefault("num_units", num_units)
    ctx = setup_order_pipeline(**kwargs)
    ctx["order"] = adjudicate_pick_ship_deliver(ctx["order"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: activation, early failure, warranty claims
# ---------------------------------------------------------------------------

def activate_unit(patient, unit, channel="READER"):
    return _ok(
        api_client.create_device_binding(
            patient["id"],
            create_device_binding_payload(unit["id"], channel),
            make_patient_headers(patient["id"]),
        ),
        "activate unit", 201,
    )


def report_failure(patient, unit):
    return _ok(
        api_client.report_early_failure(unit["id"], make_patient_headers(patient["id"])),
        "report early failure",
    )


def setup_failed_unit(failure_day_index=3, device_data_attached=True, **kwargs):
    """Failed unit + warranty claim filed (SUBMITTED). Returns ctx with
    'claim' and 'unit' keys.

    Provisions one spare IN_STOCK unit beyond the delivered unit so the
    PRD §3.8 approval path ("a replacement unit is allocated from a lot of the
    same product whose complaint_posture is NORMAL") has stock to allocate.
    """
    kwargs.setdefault("num_units", 2)
    ctx = setup_delivered_unit(**kwargs)
    patient, unit = ctx["patient"], ctx["units"][0]
    ctx["binding"] = activate_unit(patient, unit)
    ctx["unit"] = report_failure(patient, unit)
    claim = _ok(
        api_client.create_warranty_claim(
            unit["id"],
            create_warranty_claim_payload(
                reported_failure_day_index=failure_day_index,
                device_data_attached=device_data_attached,
            ),
            make_patient_headers(patient["id"]),
        ),
        "create warranty claim", 201,
    )
    ctx["claim"] = claim
    return ctx


def setup_claim_in_data_review(**kwargs):
    """Failed unit + claim moved SUBMITTED -> DATA_REVIEW."""
    ctx = setup_failed_unit(**kwargs)
    ctx["claim"] = _ok(
        api_client.begin_review_warranty_claim(ctx["claim"]["id"], WARRANTY),
        "begin review",
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 6: adverse events / lot posture
# ---------------------------------------------------------------------------

def file_and_close_aer(lot, unit, patient_id, outcome="SUBSTANTIATED", severity="HIGH", event_type="SKIN_IRRITATION"):
    """File an AER, investigate, close with the given outcome. Returns the
    closed report."""
    aer = _ok(
        api_client.create_adverse_event_report(
            lot["id"],
            create_adverse_event_report_payload(unit["id"], patient_id, severity=severity, event_type=event_type),
            QE,
        ),
        "create AER", 201,
    )
    _ok(api_client.investigate_adverse_event_report(aer["id"], QE), "investigate AER")
    return _ok(
        api_client.close_adverse_event_report(aer["id"], {"outcome": outcome}, QE),
        "close AER",
    )


def setup_lot_with_substantiated_complaints(complaint_count):
    """Create a lot whose complaint_count has been raised to `complaint_count`
    via CLOSED_SUBSTANTIATED AERs. Returns dict with lot/product/units/patient."""
    patient = create_patient()
    product = create_product()
    lot = create_lot(product, quantity_manufactured=complaint_count + 5)
    # two spare units beyond those referenced by AERs (for further AERs / picks)
    units = create_units(lot, complaint_count + 2)
    for unit in units[:complaint_count]:
        file_and_close_aer(lot, unit, patient["id"], outcome="SUBSTANTIATED")
    return {"patient": patient, "product": product, "lot": lot, "units": units}


# ---------------------------------------------------------------------------
# Tier 7: support enrollment
# ---------------------------------------------------------------------------

def create_enrollment(patient, payer, **overrides):
    return _ok(
        api_client.create_support_enrollment(
            patient["id"], create_support_enrollment_payload(payer["id"], **overrides), SUPPORT
        ),
        "create enrollment", 201,
    )
