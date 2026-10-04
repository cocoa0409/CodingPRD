"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_patient(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["state_code"], str)
    assert data["status"] in ["ACTIVE", "DECEASED", "TRANSFERRED_OUT"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_prescriber(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["full_name"], str)
    assert isinstance(data["npi"], str)
    assert data["specialty"] in ["ENDOCRINOLOGY", "PRIMARY_CARE", "OTHER"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["version"], int)


def assert_payer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["benefit_route"] in ["PHARMACY", "DME"]
    assert data["cgm_coverage_policy"] in ["STRICT", "STANDARD", "LENIENT"]
    assert data["status"] in ["ACTIVE", "TERMINATED"]


def assert_sensor_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["sku"], str)
    assert isinstance(data["generation"], int)
    assert isinstance(data["wear_days"], int)
    assert data["reader_channel"] in ["READER", "APP", "HYBRID"]
    assert isinstance(data["list_price_cents"], int)


def assert_sensor_lot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["lot_code"], str)
    assert isinstance(data["quantity_manufactured"], int)
    assert isinstance(data["complaint_count"], int)
    assert data["complaint_posture"] in ["NORMAL", "WATCH", "HOLD"]


def assert_prescription(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "EXHAUSTED", "EXPIRED", "CANCELLED"]
    assert isinstance(data["fills_consumed"], int)
    assert isinstance(data["fills_authorized"], int)
    assert isinstance(data["quantity_per_fill"], int)


def assert_coverage_verification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["decision"] in ["PENDING", "APPROVED", "DENIED"]
    assert data["benefit_route"] in ["PHARMACY", "DME"]
    for key in ("criteria_diagnosis_met", "criteria_insulin_met", "criteria_documentation_met"):
        assert isinstance(data[key], bool)


def assert_sensor_unit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in [
        "IN_STOCK", "ALLOCATED", "SHIPPED", "IN_HAND", "ACTIVE",
        "EXPIRED_WORN", "FAILED_EARLY", "REPLACED", "SCRAPPED",
    ]
    assert isinstance(data["serial_number"], str)


def assert_sensor_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["fulfillment_status"] in ["PENDING_PICK", "PICKED", "SHIPPED", "DELIVERED", "CANCELLED"]
    assert data["billing_status"] in ["UNBILLED", "ADJUDICATED", "PAID", "REVERSED"]
    assert isinstance(data["quantity"], int)


def assert_device_binding(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["channel"] in ["READER", "APP"]
    assert data["status"] in ["ACTIVE", "ENDED_NORMALLY", "ENDED_EARLY_FAILURE", "SUPERSEDED"]


def assert_warranty_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["SUBMITTED", "DATA_REVIEW", "MORE_INFO_REQUESTED", "APPROVED", "DENIED", "CLOSED"]
    assert data["failure_category"] in ["NO_READINGS", "INACCURATE", "ADHESIVE_FAILURE", "SENSOR_ERROR", "OTHER"]
    assert isinstance(data["replacement_credit_cents"], int)


def assert_replacement_shipment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["PENDING_SHIP", "SHIPPED", "DELIVERED", "CANCELLED"]


def assert_support_enrollment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ENROLLED", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["card_max_per_fill_cents"], int)
    assert isinstance(data["card_remaining_cents"], int)


def assert_adverse_event_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "INVESTIGATING", "CLOSED_SUBSTANTIATED", "CLOSED_UNSUBSTANTIATED"]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def assert_order_money_conserved(order: dict):
    """Money decomposition invariant on a SensorOrder:
    allowed_amount == plan_paid + patient_paid + savings_card_paid."""
    total = (
        order["plan_paid_cents"]
        + order["patient_paid_cents"]
        + order["savings_card_paid_cents"]
    )
    assert order["allowed_amount_cents"] == total, (
        f"allowed_amount_cents {order['allowed_amount_cents']} != "
        f"plan {order['plan_paid_cents']} + patient {order['patient_paid_cents']} "
        f"+ card {order['savings_card_paid_cents']}"
    )
