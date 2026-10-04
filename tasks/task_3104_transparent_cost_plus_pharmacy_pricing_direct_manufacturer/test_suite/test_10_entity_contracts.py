"""Entity-level behaviour: creation, retrieval, computed fields and bounds."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
    create_manufacturer,
    create_drug,
    create_price_row,
    create_patient,
    create_prescriber,
    create_prescription,
    reset_clock,
    OPS,
)


class TestManufacturerCreation:

    def test_manufacturer_is_server_minted_and_starts_active(self, api):
        """PRD §3.1: "A PharmacyOps operator registers one by supplying its
        manufacturer_name; the record is born with status set to ACTIVE."
        PRD §2.4: "version is an integer that starts at 1 on creation and
        increments by 1 on every mutation."

        Design: Corner/entities/manufacturer_create_returns_system_fields_and_starts_active
        """
        reset_clock()
        response = api.create_manufacturer({"manufacturer_name": "Bexley Generics"}, OPS)
        body = response.json()
        data = validate_success(response, 201)

        assert body["response_type"] == "object"
        assert data["manufacturer_name"] == "Bexley Generics"
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"]), "the id is a bare UUID"
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)


class TestDrugRetrieval:

    def test_drug_get_echoes_the_stored_inputs(self, api):
        """PRD §3.3: "It is created by an operator supplying its drug_name,
        strength, dosage_form, is_controlled flag and the two reference prices"

        Design: Corner/entities/drug_get_round_trips_stored_values_and_404s_on_unknown_id
        """
        reset_clock()
        drug = create_drug()
        fetched = validate_success(api.get_drug(drug["id"], OPS))
        assert fetched["strength"] == "500MG"
        assert fetched["dosage_form"] == "Tablet"
        assert fetched["retail_reference_price_cents"] == 4200
        assert fetched["insured_reference_price_cents"] == 3600

    def test_unknown_drug_id_is_a_not_found_error(self, api):
        """PRD §2.7: "The first identifier in the path that does not correspond
        to a persisted resource terminates the request immediately with
        ERR_RESOURCE_NOT_FOUND and HTTP 404"

        Design: Corner/entities/drug_get_round_trips_stored_values_and_404s_on_unknown_id
        """
        reset_clock()
        response = api.get_drug(NON_EXISTENT_UUID, OPS)
        validate_error(response, "ERR_RESOURCE_NOT_FOUND")


class TestPriceRowComputedFields:

    def test_interval_days_is_computed_from_tier_and_units(self, api):
        """PRD §3.2: "its reliability tier contributes a base of 7 days for tier
        A, 14 days for tier B, and 21 days for tier C, and that base is adjusted
        by its available units — a row holding at least 200 units has 7 days
        subtracted from its base"
        PRD §3.2: "a tier B row with 600 units contributes 14 minus 7, which is
        7 days"

        Design: Corner/entities/manufacturer_drug_price_exposes_computed_interval_days_and_ignores_supplied_price_status
        """
        reset_clock()
        manufacturer = create_manufacturer()
        drug = create_drug()
        row = create_price_row(drug["id"], manufacturer["id"], unit_cost_cents=12,
                               available_units=600, reliability_tier="B",
                               packaging="500-count bottle")
        assert row["interval_days"] == 7, (
            "base(B) 14 plus the at-least-200-units adjustment of -7 is 7"
        )
        assert row["version"] == 1

    def test_price_and_sourcing_dimensions_start_at_their_initial_values(self, api):
        """PRD §3.1: "A new row starts with its two dimensions at their initial
        values: price_status at PROPOSED and sourcing_status at UNDER_REVIEW."

        Design: Corner/entities/manufacturer_drug_price_exposes_computed_interval_days_and_ignores_supplied_price_status
        """
        reset_clock()
        manufacturer = create_manufacturer()
        drug = create_drug()
        row = create_price_row(drug["id"], manufacturer["id"], unit_cost_cents=12,
                               available_units=600, reliability_tier="B",
                               packaging="500-count bottle")
        assert row["price_status"] == "PROPOSED"
        assert row["sourcing_status"] == "UNDER_REVIEW"


class TestPriceRowNumericBounds:

    @pytest.mark.parametrize("bad_cost", [0, -1])
    def test_unit_cost_below_one_is_rejected(self, api, bad_cost):
        """PRD §3.1: "Two lower bounds apply at creation and are reported as
        ERR_INVALID_AMOUNT with HTTP 400 when violated: unit_cost_cents must be
        at least 1, and available_units must be at least 0."

        Design: Corner/entities/manufacturer_drug_price_rejects_out_of_range_numeric_inputs
        """
        reset_clock()
        manufacturer = create_manufacturer()
        drug = create_drug()
        response = api.create_price({
            "drug_id": drug["id"], "manufacturer_id": manufacturer["id"],
            "unit_cost_cents": bad_cost, "available_units": 100,
            "reliability_tier": "A", "packaging": "100-count bottle",
        }, OPS)
        validate_error(response, "ERR_INVALID_AMOUNT")

    def test_zero_available_units_is_a_legal_pending_row(self, api):
        """PRD §3.1: "available_units must be at least 0"

        Design: Corner/entities/manufacturer_drug_price_rejects_out_of_range_numeric_inputs
        """
        reset_clock()
        manufacturer = create_manufacturer()
        drug = create_drug()
        row = validate_success(api.create_price({
            "drug_id": drug["id"], "manufacturer_id": manufacturer["id"],
            "unit_cost_cents": 12, "available_units": 0,
            "reliability_tier": "A", "packaging": "100-count bottle",
        }, OPS), 201)
        assert row["available_units"] == 0
        assert row["sourcing_status"] == "UNDER_REVIEW"


class TestPrescriptionReferences:

    def test_unresolvable_prescriber_reference_is_a_not_found_error(self, api):
        """PRD §2.7: "The set of resource kinds subject to this rule is the whole graph: drug, pharmacy, manufacturer, prescriber, patient, prescription, request, order, shipment, claim, price row, licence, comparison and substantiation must each exist before the request proceeds."

        Design: Corner/entities/prescription_create_rejects_unresolvable_prescriber_and_patient_references
        """
        reset_clock()
        patient = create_patient()
        drug = create_drug()
        response = api.create_prescription({
            "patient_id": patient["id"],
            "prescriber_id": NON_EXISTENT_UUID,
            "drug_id": drug["id"],
            "ship_state_code": "CA",
            "total_refills_authorized": 2,
        }, OPS)
        validate_error(response, "ERR_RESOURCE_NOT_FOUND")

    def test_unresolvable_patient_reference_is_a_not_found_error(self, api):
        """PRD §2.7: "the server resolves them strictly left to right. The first
        identifier in the path that does not correspond to a persisted resource
        terminates the request immediately"

        Design: Corner/entities/prescription_create_rejects_unresolvable_prescriber_and_patient_references
        """
        reset_clock()
        drug = create_drug()
        prescriber = create_prescriber()
        response = api.create_prescription({
            "patient_id": NON_EXISTENT_UUID,
            "prescriber_id": prescriber["id"],
            "drug_id": drug["id"],
            "ship_state_code": "CA",
            "total_refills_authorized": 2,
        }, OPS)
        validate_error(response, "ERR_RESOURCE_NOT_FOUND")