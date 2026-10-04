"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

REGIONS = ["NA", "EU", "APAC", "ROW"]


def assert_campaign(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data.get("status") in [
        "DRAFT",
        "LIVE",
        "CLOSED_SUCCESS",
        "CLOSED_FAILED",
        "IN_PRODUCTION",
        "FULFILLING",
        "COMPLETE",
        "CANCELLED",
    ], f"unexpected campaign status {data.get('status')}"
    assert isinstance(data.get("gross_charged_cents"), int)
    assert isinstance(data.get("platform_fee_cents"), int)
    assert isinstance(data.get("payment_fee_cents"), int)
    assert isinstance(data.get("customs_duty_paid_cents"), int)
    assert isinstance(data.get("net_payable_cents"), int)
    assert isinstance(data.get("total_backers_charged"), int)


def assert_pledge(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data.get("charge_status") in [
        "PENDING",
        "CHARGED",
        "CHARGE_FAILED",
        "REFUNDED",
    ]
    assert data.get("address_status") in ["UNCONFIRMED", "CONFIRMED", "LOCKED"]
    assert data.get("fulfillment_status") in [
        "QUEUED",
        "WAVE_ASSIGNED",
        "PICKED",
        "SHIPPED",
        "DELIVERED",
    ]
    assert data.get("region_code") in REGIONS
    assert isinstance(data.get("pledge_total_cents"), int)


def assert_manufacturing_quote(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ["PROVISIONAL", "SUBMITTED", "FINAL", "SUPERSEDED"]
    assert isinstance(data.get("provisional_units"), int)
    assert isinstance(data.get("provisional_unit_price_cents"), int)


def assert_production_run(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in [
        "QUOTED",
        "LOCKED",
        "IN_PRODUCTION",
        "SHIPPED",
        "CANCELLED",
    ]


def assert_freight_shipment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in [
        "BOOKED",
        "IN_TRANSIT",
        "CUSTOMS_HOLD",
        "DUTY_ASSESSED",
        "CLEARED",
        "DELIVERED",
    ]
    assert data.get("region_code") in REGIONS


def assert_wave(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in [
        "SCHEDULED",
        "OPEN",
        "CLOSED",
        "DISPATCHED",
        "CANCELLED",
    ]
    assert data.get("region_code") in REGIONS
    assert isinstance(data.get("capacity_used"), int)
    assert isinstance(data.get("assignments"), list)


def assert_distributor_allocation(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ["RESERVED", "CONFIRMED", "SHIPPED", "RELEASED"]
    assert isinstance(data.get("units_reserved"), int)


def assert_replacement_request(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ["PENDING", "APPROVED", "REJECTED", "SHIPPED"]
    assert data.get("region_code") in REGIONS
    assert isinstance(data.get("spare_units_debited"), int)


def assert_localization_agreement(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ["NEGOTIATING", "SIGNED", "PRINTED", "TERMINATED"]


def assert_reprint_decision(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("status") in ["PROPOSED", "APPROVED", "REJECTED", "LOCKED"]
    assert isinstance(data.get("inventory_risk_score"), int)


def assert_wave_capacity_invariant(wave: dict):
    """capacity_used is always the count of embedded assignment entries whose
    status is ASSIGNED (PRD §3.6)."""
    assigned = [a for a in wave.get("assignments", []) if a.get("status") == "ASSIGNED"]
    assert wave.get("capacity_used") == len(assigned), (
        f"capacity_used {wave.get('capacity_used')} != count(ASSIGNED) {len(assigned)}"
    )
