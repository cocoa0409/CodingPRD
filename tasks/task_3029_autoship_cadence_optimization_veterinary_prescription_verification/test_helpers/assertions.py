"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_system_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_pet(data: dict):
    """Pet carries only id and created_at — no updated_at and no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "Pet.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Pet.created_at must be ISO 8601"
    assert "updated_at" not in data or data["updated_at"] is None, (
        "Pet must not expose updated_at"
    )
    assert "version" not in data or data["version"] is None, "Pet must not expose version"
    assert isinstance(data["pet_name"], str) and data["pet_name"]
    assert data["species"] in ["DOG", "CAT", "HORSE", "BIRD"]
    assert isinstance(data["breed"], str) and data["breed"]
    assert isinstance(data["weight_kg"], (int, float))
    assert isinstance(data["owner_state"], str) and len(data["owner_state"]) == 2
    assert data["pet_status"] in ["ACTIVE", "PASSED"]
    assert data["pet_lifecycle_state"] in ["ALIVE", "PASSED", "ARCHIVED"]


def assert_veterinarian(data: dict):
    _assert_system_fields(data, "Veterinarian")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["clinic_name"], str) and data["clinic_name"]
    assert isinstance(data["clinic_phone"], str) and data["clinic_phone"]
    assert isinstance(data["vet_email"], str) and data["vet_email"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["license_state"], str) and len(data["license_state"]) == 2
    assert data["vet_status"] in [
        "LISTED", "VETERINARIAN_VERIFIED", "SUSPENDED", "RETIRED", "BLOCKED",
    ]


def assert_pharmacy_site(data: dict):
    _assert_system_fields(data, "PharmacySite")
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert isinstance(data["site_state"], str) and len(data["site_state"]) == 2
    assert isinstance(data["licensed_states"], list)
    assert isinstance(data["cold_pack_capacity_units"], int)
    assert data["cold_pack_capacity_units"] >= 0
    assert isinstance(data["csr_registered"], bool)
    assert isinstance(data["cold_pack_committed_units"], int)
    assert data["cold_pack_committed_units"] >= 0
    assert data["site_status"] in ["ACTIVE", "RESTRICTED", "CLOSED"]


def assert_product(data: dict):
    _assert_system_fields(data, "Product")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["product_name"], str) and data["product_name"]
    assert data["medication_scope"] in ["OTC", "PRESCRIPTION"]
    assert isinstance(data["cold_pack_required"], bool)
    assert isinstance(data["unit_dose_mg_per_kg"], (int, float))
    assert data["unit_dose_mg_per_kg"] > 0
    assert isinstance(data["pack_size_units"], int)
    assert data["pack_size_units"] >= 1
    assert isinstance(data["unit_price_cents"], int)


def assert_autoship_plan(data: dict):
    _assert_system_fields(data, "AutoshipPlan")
    assert is_valid_uuid(data["pet_id"]), "AutoshipPlan.pet_id must be a valid UUID"
    assert data["plan_status"] in [
        "ACTIVE", "PAUSED", "SUSPENDED", "CANCELED", "COMPASSIONATE_CANCELED",
    ]
    assert data["autoship_discount_eligibility"] in ["ELIGIBLE", "INELIGIBLE"]
    assert isinstance(data["autoship_item_count"], int)
    assert data["autoship_item_count"] >= 0
    assert isinstance(data["cadence_prompt_due_days_delta"], int)
    assert isinstance(data["released_refunds_cents"], int)
    assert isinstance(data["transaction_adjustments_cents"], int)


def assert_autoship_item(data: dict):
    _assert_system_fields(data, "AutoshipItem")
    assert is_valid_uuid(data["autoship_plan_id"]), "AutoshipItem.autoship_plan_id must be a valid UUID"
    assert is_valid_uuid(data["product_id"]), "AutoshipItem.product_id must be a valid UUID"
    assert data["item_status"] in ["ACTIVE", "PAUSED", "COMPLETED", "CANCELED"]
    assert data["verification_state"] in [
        "UNVERIFIED", "VERIFIED", "BLOCKED", "EXPIRATION_MARKED",
    ]
    assert data["cadence_days"] in [14, 21, 28, 42, 56, 84]
    assert isinstance(data["default_quantity"], int) and data["default_quantity"] >= 1
    assert data["cadence_prompt_state"] in [
        "UNDER_CONSUMPTION", "ALIGNED", "OVER_CONSUMPTION",
    ]
    assert data["protection_state"] in ["PROTECTED", "REPRICED"]
    assert isinstance(data["unit_lifecycle_equivalent_days"], int)
    assert 14 <= data["unit_lifecycle_equivalent_days"] <= 84


def assert_prescription(data: dict):
    _assert_system_fields(data, "Prescription")
    assert is_valid_uuid(data["autoship_item_id"]), "Prescription.autoship_item_id must be a valid UUID"
    assert is_valid_uuid(data["prescriber_id"]), "Prescription.prescriber_id must be a valid UUID"
    assert data["rx_status"] in [
        "PENDING_VERIFICATION", "VERIFICATION_IN_PROGRESS", "VERIFIED",
        "VERIFICATION_FAILED", "EXPIRED",
    ]
    assert data["script_source"] in ["UPLOADED_SCRIPT", "WRITTEN_PRESCRIPTION"]
    assert data["drug_schedule"] in ["NONE", "CII", "CIII", "CIV", "CV"]
    assert isinstance(data["temperature_sensitive"], bool)
    assert isinstance(data["authorized_qty_total"], int) and data["authorized_qty_total"] >= 1
    assert isinstance(data["authorized_qty_remaining"], int)
    assert isinstance(data["refills_authorized"], int) and data["refills_authorized"] >= 0
    assert isinstance(data["refills_used"], int)
    assert 0 <= data["callback_attempt_count"] <= 3


def assert_order(data: dict):
    _assert_system_fields(data, "Order")
    assert is_valid_uuid(data["autoship_plan_id"]), "Order.autoship_plan_id must be a valid UUID"
    assert data["order_kind"] in ["FIRST", "RECURRING"]
    assert data["order_status"] in [
        "PLACED", "PROCESSING", "SHIPPED",
        "AWAITING_PET_PASSING_DECISION", "DELIVERED", "CANCELED",
    ]
    assert isinstance(data["bundle_line_count"], int) and data["bundle_line_count"] >= 0


def assert_order_invariants(data: dict):
    """order_total_cents is always equal to order_total_components_sum (PRD §2.6)."""
    assert data["order_total_cents"] == data["order_total_components_sum"], (
        f"order_total_cents {data['order_total_cents']} != "
        f"order_total_components_sum {data['order_total_components_sum']}"
    )
    assert data["settlement_net_cents"] == (
        data["order_total_cents"] - data["refunded_amount_cents"]
    ), "settlement_net_cents must be order_total_cents minus refunded_amount_cents"
    assert data["refunded_amount_cents"] >= 0


def assert_order_line(data: dict):
    _assert_system_fields(data, "OrderLine")
    assert is_valid_uuid(data["order_id"]), "OrderLine.order_id must be a valid UUID"
    assert is_valid_uuid(data["autoship_item_id"]), "OrderLine.autoship_item_id must be a valid UUID"
    assert is_valid_uuid(data["product_id"]), "OrderLine.product_id must be a valid UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["line_item_subtotal_cents"] == (
        data["line_unit_price_cents"] * data["quantity"]
    ), "line_item_subtotal_cents must be line_unit_price_cents * quantity"
    assert isinstance(data["line_requires_clinic_auth"], bool)


def assert_shipment(data: dict):
    _assert_system_fields(data, "Shipment")
    assert is_valid_uuid(data["order_id"]), "Shipment.order_id must be a valid UUID"
    assert is_valid_uuid(data["origin_site_id"]), "Shipment.origin_site_id must be a valid UUID"
    assert isinstance(data["destination_state"], str) and len(data["destination_state"]) == 2
    assert data["shipment_status"] in [
        "PENDING", "PACKED", "DISPATCHED",
        "AWAITING_PET_PASSING_DECISION", "DELIVERED", "CANCELED",
    ]
    assert isinstance(data["cold_pack_required"], bool)
    assert isinstance(data["cold_pack_units"], int) and data["cold_pack_units"] >= 0


def assert_cold_pack_reservation(data: dict):
    _assert_system_fields(data, "ColdPackReservation")
    assert is_valid_uuid(data["shipment_id"]), "ColdPackReservation.shipment_id must be a valid UUID"
    assert is_valid_uuid(data["site_id"]), "ColdPackReservation.site_id must be a valid UUID"
    assert isinstance(data["units"], int) and data["units"] >= 0
    assert data["reservation_status"] in ["HELD", "CONSUMED", "RELEASED"]


def assert_compassionate_review(data: dict):
    _assert_system_fields(data, "CompassionateReview")
    assert is_valid_uuid(data["pet_id"]), "CompassionateReview.pet_id must be a valid UUID"
    assert data["review_status"] in ["OPEN", "APPROVED", "REJECTED"]
    assert data["refund_destination"] in ["WALLET", "ORIGINAL_PAYMENT"]
    assert isinstance(data["refunded_amount_cents"], int)


def assert_pet_lifecycle_consistent(pet: dict, review_status=None):
    """pet_lifecycle_state is derived from the pet's status and its review (PRD §3.6)."""
    if pet["pet_status"] == "ACTIVE":
        assert pet["pet_lifecycle_state"] == "ALIVE"
    elif pet["pet_status"] == "PASSED":
        if review_status is None or review_status == "OPEN":
            assert pet["pet_lifecycle_state"] == "PASSED"
        else:
            assert pet["pet_lifecycle_state"] == "ARCHIVED"


def assert_cold_pack_invariant(site: dict, reservations: list):
    """PharmacySite.cold_pack_committed_units == sum of HELD reservation units (PRD §3.5)."""
    held = sum(r["units"] for r in reservations if r["reservation_status"] == "HELD")
    assert site["cold_pack_committed_units"] == held, (
        f"site committed {site['cold_pack_committed_units']} != sum of held "
        f"reservations {held}"
    )