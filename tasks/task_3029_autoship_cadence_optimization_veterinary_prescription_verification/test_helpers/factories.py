"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PET_NAME": "Test Pet",
    "SPECIES": "DOG",
    "BREED": "Mixed",
    "WEIGHT_KG": 12.0,
    "OWNER_STATE": "CA",
    "VET_NAME": "Dr Test Vet",
    "CLINIC_NAME": "Test Clinic",
    "CLINIC_PHONE": "4155550100",
    "VET_EMAIL": "vet@testclinic.example",
    "LICENSE_NUMBER": "VET-CA-0001",
    "LICENSE_STATE": "CA",
    "SITE_CODE": "TST1",
    "SITE_STATE": "CA",
    "PRODUCT_NAME": "Test Product",
    "UNIT_DOSE_MG_PER_KG": 0.02,
    "PACK_SIZE_UNITS": 10,
    "UNIT_PRICE_CENTS": 1000,
}


def create_pet_payload(**overrides) -> dict:
    payload = {
        "pet_name": DEFAULTS["PET_NAME"],
        "species": DEFAULTS["SPECIES"],
        "breed": DEFAULTS["BREED"],
        "weight_kg": DEFAULTS["WEIGHT_KG"],
        "owner_state": DEFAULTS["OWNER_STATE"],
    }
    payload.update(overrides)
    return payload


def create_veterinarian_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["VET_NAME"],
        "clinic_name": DEFAULTS["CLINIC_NAME"],
        "clinic_phone": DEFAULTS["CLINIC_PHONE"],
        "vet_email": DEFAULTS["VET_EMAIL"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "license_state": DEFAULTS["LICENSE_STATE"],
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    payload = {
        "sku": "SKU-TEST-1",
        "product_name": DEFAULTS["PRODUCT_NAME"],
        "medication_scope": "OTC",
        "cold_pack_required": False,
        "unit_dose_mg_per_kg": DEFAULTS["UNIT_DOSE_MG_PER_KG"],
        "pack_size_units": DEFAULTS["PACK_SIZE_UNITS"],
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_site_payload(**overrides) -> dict:
    payload = {
        "site_code": DEFAULTS["SITE_CODE"],
        "site_state": DEFAULTS["SITE_STATE"],
        "licensed_states": ["CA"],
        "cold_pack_capacity_units": 100,
        "csr_registered": True,
    }
    payload.update(overrides)
    return payload


def create_plan_payload(pet_id, **overrides) -> dict:
    payload = {"pet_id": pet_id}
    payload.update(overrides)
    return payload


def create_item_payload(product_id, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "cadence_days": 28,
        "default_quantity": 1,
    }
    payload.update(overrides)
    return payload


def create_prescription_payload(autoship_item_id, prescriber_id, **overrides) -> dict:
    payload = {
        "autoship_item_id": autoship_item_id,
        "prescriber_id": prescriber_id,
        "script_source": "UPLOADED_SCRIPT",
        "script_document_id": "doc-test-1",
        "drug_schedule": "NONE",
        "temperature_sensitive": False,
        "authorized_qty_total": 90,
        "refills_authorized": 5,
    }
    payload.update(overrides)
    return payload


def create_shipment_payload(order_id) -> dict:
    return {"order_id": order_id}


def create_cancel_order_payload(**overrides) -> dict:
    payload = {"cancellation_reason": "CUSTOMER_REQUEST"}
    payload.update(overrides)
    return payload


def create_cancel_plan_payload(**overrides) -> dict:
    payload = {"cancellation_reason": "CUSTOMER_REQUEST"}
    payload.update(overrides)
    return payload


def create_passing_payload(**overrides) -> dict:
    payload = {"refund_destination": "WALLET"}
    payload.update(overrides)
    return payload