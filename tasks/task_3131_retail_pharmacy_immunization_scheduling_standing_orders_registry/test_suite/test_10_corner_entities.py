"""Corner tests — entities section: creation defaults, required fields, computed
fields, immutability, not-found, parent relationships, enum constraints,
pagination, FK reverse reachability.

PRD §2.2 envelope, §2.5 common fields, §3.1 reference data.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid, is_iso8601_timestamp,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    create_store, create_product, create_protocol, create_patient, create_lot,
    book_appointment,
)


def _mgr():
    return TEST_USERS["store_manager_headers"]


def _co():
    return TEST_USERS["compliance_headers"]


def _tech():
    return TEST_USERS["technician_headers"]


def _pharm():
    return TEST_USERS["pharmacist_headers"]


def test_store_creation_defaults_and_system_fields(api):
    """PRD §2.5: "Every primary resource in the system carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is a system-managed integer that increments by one on every modification to the resource"
    PRD §3.1: "A store's `status` begins as `ACTIVE`"

    Design: Corner/entities/store_creation_defaults_and_system_fields
    """
    resp = api_client.create_store(
        {"store_number": "S-1", "state_code": "CA", "address_line": "1 Main St"},
        _mgr(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])


def test_patient_registration_optional_field_defaults(api):
    """PRD §3.1: "Optional at registration are `allergy_flags` — a list of known allergen codes that contraindication review matches against vaccine excipient lists, defaulting to empty — `high_risk_flag`, which when true mandates a 30-minute observation window instead of the standard one and defaults to false, and `insurance_plan_id`, which may be omitted at registration but is required before any non-cash checkout."

    Design: Corner/entities/patient_registration_optional_field_defaults
    """
    resp = api_client.create_patient(
        {"full_name": "Pat Default", "date_of_birth": "1990-05-05", "state_code": "CA"},
        _tech(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["allergy_flags"] == []
    assert data["high_risk_flag"] is False
    assert data["version"] == 1
    assert data.get("insurance_plan_id") is None


def test_product_registration_defaults_min_interval_and_observation(api):
    """PRD §3.1: "`min_interval_days` — the minimum gap between successive doses of the product — defaults to 0, and `observation_minutes`, the standard post-vaccination observation window, defaults to 15."

    Design: Corner/entities/product_registration_defaults_min_interval_and_observation
    """
    resp = api_client.create_vaccine_product(
        {"cvx_code": "141", "name": "Influenza Quadrivalent", "min_patient_age_years": 0,
         "doses_per_series": 1, "cash_price_cents": 5000, "fridge_temp_min_c": 2.0,
         "fridge_temp_max_c": 8.0},
        _co(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["min_interval_days"] == 0
    assert data["observation_minutes"] == 15


def test_patient_creation_missing_required_field_rejected(api):
    """PRD §3.1: "A PharmacyTechnician or Pharmacist registers a Patient with full_name, date_of_birth (an ISO 8601 date), and residence state_code."
    PRD §5: ERR_INVALID_REQUEST 400

    Design: Corner/entities/patient_creation_missing_required_field_rejected
    """
    err = validate_error(
        api_client.create_patient(
            {"full_name": "No Dob", "state_code": "CA"},
            _tech(),
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    assert err["error_id"] == "ERR_INVALID_REQUEST"
    data, meta = validate_paginated(api_client.list_patients(_tech()))
    assert meta["total_count"] == 0


def test_lot_creation_computed_doses_available_and_protocol_resolution_at_booking(api):
    """PRD §3.2: "Receipt initializes `doses_available` equal to `doses_received` and sets the lot's `status` to `RELEASED`."
    PRD §3.3: "the appointment's `state_protocol_id` is computed from the store's `state_code` and the requested product"
    PRD §3.3: "The appointment's `dose_number` is one plus the count of the patient's `COMPLETED` immunization records for the same product"
    PRD §3.3: "A booked appointment begins in `SCHEDULED`."

    Design: Corner/entities/lot_creation_computed_doses_available_and_protocol_resolution_at_booking
    """
    store = create_store(store_number="S-2", state_code="CA")
    product = create_product()
    protocol = create_protocol(vaccine_product_id=product["id"])
    patient = create_patient(full_name="Pat Cmp", date_of_birth="1980-01-01")

    lot = create_lot(store["id"], product["id"], doses_received=7)
    assert lot["doses_available"] == 7
    assert lot["status"] == "RELEASED"
    assert lot["store_id"] == store["id"]

    appt = book_appointment(store["id"], patient["id"], product["id"],
                            slot_start="2026-09-02T10:00:00Z")
    assert appt["state_protocol_id"] == protocol["id"]
    assert appt["dose_number"] == 1
    assert appt["status"] == "SCHEDULED"
    assert appt["is_walk_in"] is False


def test_temperature_reading_immutable_and_inband_no_side_effects(api):
    """PRD §2.5: "One entity is an exception: a `TemperatureReading` is an immutable fact about a refrigerator at an instant. It carries only `id` and `created_at`; both `updated_at` and `version` are absent from it, and no endpoint mutates a reading after it is posted."
    PRD §3.2: "A reading inside the band is accepted with no side effects and an `excursion_severity_tier` of `NONE`."

    Design: Corner/entities/temperature_reading_immutable_and_inband_no_side_effects
    """
    store = create_store(store_number="S-3", state_code="CA")
    product = create_product()
    lot = create_lot(store["id"], product["id"], doses_received=5)

    resp = api_client.create_temperature_reading(lot["id"],
        {"recorded_at": "2026-09-01T08:00:00Z", "temperature_c": 5.0}, _tech())
    reading = validate_success(resp, expected_status=201)
    assert reading["is_excursion"] is False
    assert reading["excursion_severity_tier"] == "NONE"
    assert "version" not in reading
    assert "updated_at" not in reading

    lot_after = get_success_data(api_client.get_lot(lot["id"], _mgr()))
    assert lot_after["status"] == "RELEASED"
    assert lot_after["doses_available"] == 5


def test_get_nonexistent_resource_returns_404(api):
    """PRD §2.6: "The request is rejected immediately with `ERR_NOT_FOUND` for the first identifier in the path that does not correspond to an existing resource"

    Design: Corner/entities/get_nonexistent_resource_returns_404
    """
    err = validate_error(
        api_client.get_store("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", _mgr()),
        ApiErrorId.ERR_NOT_FOUND,
    )
    assert err["error_id"] == "ERR_NOT_FOUND"


def test_lot_creation_requires_existing_parent_store(api):
    """PRD §2.6: "When an endpoint path contains multiple resource identifiers — for example a store id followed by a lot id, or an appointment id followed by a questionnaire — the system validates the existence of each identifier sequentially, left to right. The request is rejected immediately with `ERR_NOT_FOUND` for the first identifier in the path that does not correspond to an existing resource"

    Design: Corner/entities/lot_creation_requires_existing_parent_store
    """
    product = create_product()
    err = validate_error(
        api_client.create_lot("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            {"vaccine_product_id": product["id"], "lot_number": "L1",
             "expiration_date": "2027-01-01", "doses_received": 5},
            _mgr()),
        ApiErrorId.ERR_NOT_FOUND,
    )
    assert err["error_id"] == "ERR_NOT_FOUND"


def test_protocol_creation_enum_constraint_violation(api):
    """PRD §3.1: "declaring the `authority_type` (one of `STANDING_ORDER`, `PROTOCOL`, or `PRESCRIPTION_REQUIRED`)"
    PRD §5: ERR_INVALID_REQUEST 400

    Design: Corner/entities/protocol_creation_enum_constraint_violation
    """
    product = create_product()
    err = validate_error(
        api_client.create_state_protocol(
            {"state_code": "CA", "vaccine_product_id": product["id"],
             "authority_type": "ROYAL_DECREE", "registry_format": "HL7_VXU",
             "registry_deadline_hours": 24},
            _co(),
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    assert err["error_id"] == "ERR_INVALID_REQUEST"


def test_pagination_defaults_and_envelope_on_list(api):
    """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the start of the result set and defaults to 0."
    PRD §2.2: "The `meta` envelope on list responses carries `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/pagination_defaults_and_envelope_on_list
    """
    for i in range(3):
        create_patient(full_name=f"P{i+1}", date_of_birth=f"198{i}-01-01")
    data, meta = validate_paginated(api_client.list_patients(_tech()))
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(data) == 3


def test_fk_reverse_reachability_filtered_lists(api):
    """PRD §3.2: "The lot's `store_id` is recorded from the receiving store."
    PRD §3.3: "The request names the `store_id`, the `patient_id`, the `vaccine_product_id`"

    Design: Corner/entities/fk_reverse_reachability_filtered_lists
    """
    store = create_store(store_number="S-4", state_code="CA")
    product = create_product()
    create_protocol(vaccine_product_id=product["id"])
    patient = create_patient(full_name="Pat FK", date_of_birth="1980-01-01")
    lot = create_lot(store["id"], product["id"], doses_received=5)
    appt = book_appointment(store["id"], patient["id"], product["id"],
                            slot_start="2026-09-02T10:00:00Z")

    lots_data, _ = validate_paginated(api_client.list_store_lots(store["id"], _mgr()))
    assert len(lots_data) == 1
    assert lots_data[0]["id"] == lot["id"]

    appts_data, _ = validate_paginated(api_client.list_appointments(_tech(), params={"patient_id": patient["id"]}))
    assert len(appts_data) == 1
    assert appts_data[0]["id"] == appt["id"]
