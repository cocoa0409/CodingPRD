"""Composite setup helpers: storage tanks, telemetry readings, deliveries,
and quality certificates. Re-exported through fixtures.py.

Default telemetry chains are clock-aware: every default timestamp sits after
the logical-clock start (2026-09-01T00:00:00Z), so a delivery triggered while
the clock is still at startup gets route_date 2026-09-01 and route_code
RT-2026-09-01 (PRD section 3.6).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    create_certificate_payload,
    create_certify_payload,
    create_confirm_delivery_payload,
    create_tank_payload,
    create_telemetry_payload,
)
from .test_users import TEST_USERS, make_quality_analyst_headers, make_quality_certifier_headers


# ---------------------------------------------------------------------------
# Storage tanks + telemetry
# ---------------------------------------------------------------------------

def create_tank(customer_id: str, **overrides) -> dict:
    """Create a StorageTank as PlantOperator: status NORMAL, level null."""
    return get_success_data(
        api_client.create_tank(
            create_tank_payload(customer_id, **overrides),
            TEST_USERS["plant_operator_headers"],
        )
    )


def post_telemetry(tank_id: str, measured_at: str, level_liters: int) -> dict:
    """Append one reading as TelemetryGateway; returns the refreshed tank."""
    return get_success_data(
        api_client.create_telemetry_reading(
            tank_id,
            create_telemetry_payload(measured_at, level_liters),
            TEST_USERS["telemetry_gateway_headers"],
        )
    )


def create_tank_with_readings(customer_id: str, readings: list, **tank_overrides) -> dict:
    """Tank plus an ordered list of (measured_at, level_liters) readings.
    Returns the tank as refreshed by the final reading."""
    tank = create_tank(customer_id, **tank_overrides)
    for measured_at, level_liters in readings:
        tank = post_telemetry(tank["id"], measured_at, level_liters)
    return tank


def list_tank_deliveries(tank_id: str) -> list:
    """All deliveries for one tank (data list)."""
    return get_success_data(
        api_client.list_deliveries(
            TEST_USERS["pipeline_dispatcher_headers"], params={"tank_id": tank_id}
        )
    )


# ---------------------------------------------------------------------------
# Telemetry-triggered delivery chains
# ---------------------------------------------------------------------------

def create_tank_with_telemetry_delivery(
    customer_id: str,
    first_level: int = 25000,
    trigger_level: int = 20000,
    first_at: str = DEFAULTS["FIRST_MEASURED_AT"],
    trigger_at: str = DEFAULTS["TRIGGER_MEASURED_AT"],
    **tank_overrides,
) -> tuple:
    """Tank whose second reading lands exactly on the reorder point (default
    20000 <= reorder_point 20000), edge-triggering one TELEMETRY delivery.
    Returns (tank_after_trigger, delivery)."""
    tank = create_tank_with_readings(
        customer_id,
        [(first_at, first_level), (trigger_at, trigger_level)],
        **tank_overrides,
    )
    deliveries = list_tank_deliveries(tank["id"])
    assert len(deliveries) == 1, (
        f"Setup failed: expected exactly 1 auto-created delivery, got {len(deliveries)}"
    )
    return tank, deliveries[0]


def confirm_delivery(delivery_id: str, delivered_quantity_liters: int = None,
                     headroom_liters: int = None) -> dict:
    """Confirm a SCHEDULED delivery as PipelineDispatcher. Quantity defaults to
    the supplied headroom (capacity minus current level) when given, else to
    the standard headroom default."""
    if delivered_quantity_liters is None:
        delivered_quantity_liters = (
            headroom_liters
            if headroom_liters is not None
            else DEFAULTS["DELIVERED_QUANTITY_LITERS"]
        )
    return get_success_data(
        api_client.confirm_delivery(
            delivery_id,
            create_confirm_delivery_payload(delivered_quantity_liters),
            TEST_USERS["pipeline_dispatcher_headers"],
        )
    )


def create_delivered_delivery(customer_id: str, **tank_overrides) -> tuple:
    """Tank + TELEMETRY delivery confirmed DELIVERED (quality QC_PENDING).
    The confirmed quantity equals the tank headroom at trigger time.
    Returns (tank, delivery)."""
    tank, delivery = create_tank_with_telemetry_delivery(customer_id, **tank_overrides)
    headroom = tank["capacity_liters"] - tank["current_level_liters"]
    delivery = confirm_delivery(delivery["id"], headroom_liters=headroom)
    return tank, delivery


# ---------------------------------------------------------------------------
# Quality certificate chains (segregation of duties at role AND identity)
# ---------------------------------------------------------------------------

def record_certificate(delivery_id: str, analyst_user_id: str = "qa-1",
                       **overrides) -> dict:
    """Record an analytical result (result RECORDED) as QualityAnalyst.
    The caller's X-User-ID becomes the certificate's analyst_user_id."""
    return get_success_data(
        api_client.create_quality_certificate(
            delivery_id,
            create_certificate_payload(**overrides),
            make_quality_analyst_headers(analyst_user_id),
        )
    )


def decide_certificate(certificate_id: str, decision: str = "CERTIFIED",
                       certifier_user_id: str = "qc-9") -> dict:
    """Certify or fail a recorded result as QualityCertifier. The default
    certifier identity differs from the default analyst identity, satisfying
    the two-person rule; pass certifier_user_id equal to the analyst's id to
    exercise the 422 identity gate."""
    return get_success_data(
        api_client.certify_quality_certificate(
            certificate_id,
            create_certify_payload(decision),
            make_quality_certifier_headers(certifier_user_id),
        )
    )


def create_recorded_certificate(customer_id: str, analyst_user_id: str = "qa-1",
                                cert_overrides: dict = None,
                                **tank_overrides) -> tuple:
    """Tank + DELIVERED delivery + RECORDED certificate.
    Returns (tank, delivery, certificate)."""
    tank, delivery = create_delivered_delivery(customer_id, **tank_overrides)
    certificate = record_certificate(
        delivery["id"], analyst_user_id=analyst_user_id, **(cert_overrides or {})
    )
    return tank, delivery, certificate


def create_certified_delivery(customer_id: str, analyst_user_id: str = "qa-1",
                              certifier_user_id: str = "qc-9",
                              cert_overrides: dict = None,
                              **tank_overrides) -> tuple:
    """Full quality path: delivery confirmed, certificate recorded and
    CERTIFIED (delivery COMPLETED/CERTIFIED). Default measurements satisfy the
    default tank specification snapshot.
    Returns (tank, delivery, certificate)."""
    tank, delivery, certificate = create_recorded_certificate(
        customer_id, analyst_user_id=analyst_user_id,
        cert_overrides=cert_overrides, **tank_overrides
    )
    certificate = decide_certificate(
        certificate["id"], "CERTIFIED", certifier_user_id
    )
    return tank, delivery, certificate


__all__ = [
    "create_tank",
    "post_telemetry",
    "create_tank_with_readings",
    "list_tank_deliveries",
    "create_tank_with_telemetry_delivery",
    "confirm_delivery",
    "create_delivered_delivery",
    "record_certificate",
    "decide_certificate",
    "create_recorded_certificate",
    "create_certified_delivery",
]
