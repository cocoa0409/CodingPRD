"""Corner tests: calculation rules — valuation input filtering, customs
declared value, and the shipment temperature band."""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    DONOR_REPORTING_OFFICER_HEADERS,
    LOGISTICS_COORDINATOR_HEADERS,
    QA_PHARMACIST_HEADERS,
    ApiErrorId as E,
)
from test_helpers import fixtures


class TestValuationExcludesRecalledLots:
    def test_recalled_lot_excluded_from_snapshot(self, api):
        """PRD §3.10: "The snapshot aggregates the donor's lots whose
        `intake_recorded_at` falls in the named period, excluding any lot in
        `RECALLED` posture."

        Design: Corner/calculations/valuation_snapshot_excludes_recalled_lots
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot_a = fixtures.create_and_release_lot(
            api, donor["id"], ndc_code="A", quantity_received=100,
            unit_acquisition_value_usd=1.00, unit_wholesale_value_usd=1.50,
        )
        lot_b = fixtures.create_lot(
            api, donor["id"], ndc_code="B", quantity_received=50,
            unit_acquisition_value_usd=2.00, unit_wholesale_value_usd=3.00,
        )
        get_success_data(api.recall_lot(lot_b["id"], QA_PHARMACIST_HEADERS))
        resp = api.create_valuation_snapshot(
            {"donor_id": donor["id"], "snapshot_period": "2026-09", "method": "ACQUISITION_COST"},
            DONOR_REPORTING_OFFICER_HEADERS,
        )
        snap = validate_success(resp, 201)
        assert snap["total_value_usd"] == pytest.approx(100.00, abs=0.001), (
            f"only the non-recalled lot may count: expected 100.00, got {snap['total_value_usd']}"
        )
        assert snap["lot_count"] == 1


class TestCustomsDeclaredValue:
    def _setup_international_shipment(self, api):
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot_a = fixtures.create_and_release_lot(
            api, donor["id"], ndc_code="A", quantity_received=100,
            unit_acquisition_value_usd=0.335, unit_wholesale_value_usd=0.50,
        )
        lot_b = fixtures.create_and_release_lot(
            api, donor["id"], ndc_code="B", quantity_received=100,
            unit_acquisition_value_usd=0.045, unit_wholesale_value_usd=0.10,
        )
        site = fixtures.setup_qualified_site(
            api, organization_name="HT", country_code="HT", underserved_index=0.9
        )
        request = fixtures.create_request(api, site["id"], quantity_requested=10, ndc_code="A")
        fixtures.begin_review(api, request["id"])
        current = fixtures.get_request(api, request["id"])
        decision = fixtures.create_draft_decision(
            api, request["id"],
            [{"lot_id": lot_a["id"], "quantity": 3}, {"lot_id": lot_b["id"], "quantity": 7}],
        )
        fixtures.finalize_decision(api, decision["id"], current["version"])
        shipment = fixtures.create_shipment_for_decision(api, decision["id"])
        licenses = api.list_licenses(
            COMPLIANCE_OFFICER_HEADERS, params={"site_id": site["id"]}
        ).json()["data"]
        import_license = licenses[0]
        declaration = get_success_data(
            api.create_customs_declaration(
                {
                    "shipment_id": shipment["id"],
                    "hs_code": "3004.90",
                    "import_license_id": import_license["id"],
                },
                LOGISTICS_COORDINATOR_HEADERS,
            ),
            201,
        )
        return declaration

    def test_declared_value_uses_acquisition_cost_per_line(self, api):
        """PRD §3.7: "Submitting the declaration computes `declared_value_usd`:
        for every `PICKED` line on the shipment's decision, the line's `quantity`
        is multiplied by the referenced lot's `unit_acquisition_value_usd`, each
        product is rounded half-up to two decimal places, and the rounded
        per-line amounts are summed."

        Design: Corner/calculations/customs_declared_value_uses_acquisition_cost_per_line
        """
        declaration = self._setup_international_shipment(api)
        submitted = get_success_data(
            api.submit_customs_declaration(declaration["id"], LOGISTICS_COORDINATOR_HEADERS)
        )
        # round_half_up(3*0.335)=1.01, round_half_up(7*0.045)=0.32 -> 1.33.
        assert submitted["declared_value_usd"] == pytest.approx(1.33, abs=0.001), (
            f"expected per-line acquisition-cost sum 1.33, got {submitted['declared_value_usd']}"
        )
        assert submitted["status"] == "SUBMITTED"


class TestShipmentTemperatureBand:
    def _setup_mixed_band_shipment(self, api):
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot_ambient = fixtures.create_and_release_lot(
            api, donor["id"], ndc_code="AMB", quantity_received=10,
            storage_temp_min_c=15, storage_temp_max_c=25,
        )
        lot_cold = fixtures.create_and_release_lot(
            api, donor["id"], ndc_code="COLD", product_name="Cold",
            product_class="COLD_CHAIN", dosage_form="VIAL", unit_of_measure="VIAL",
            quantity_received=10, storage_temp_min_c=2, storage_temp_max_c=8,
            unit_acquisition_value_usd=5.00, unit_wholesale_value_usd=8.00,
        )
        site = fixtures.setup_qualified_site(
            api, site_type="FQHC", cold_storage_capacity_l=100
        )
        request = fixtures.create_request(api, site["id"], quantity_requested=2, ndc_code="AMB")
        fixtures.begin_review(api, request["id"])
        current = fixtures.get_request(api, request["id"])
        decision = fixtures.create_draft_decision(
            api, request["id"],
            [{"lot_id": lot_ambient["id"], "quantity": 1},
             {"lot_id": lot_cold["id"], "quantity": 1}],
        )
        fixtures.finalize_decision(api, decision["id"], current["version"])
        shipment = fixtures.create_shipment_for_decision(
            api, decision["id"], packed_with_cold_shipper=True
        )
        return shipment

    def test_incompatible_bands_rejected(self, api):
        """PRD §3.7: "Over the distinct lots referenced by the shipment's
        `PICKED` lines, `temperature_band_min_c` is the largest of the lots'
        `storage_temp_min_c` values and `temperature_band_max_c` is the smallest
        of the lots' `storage_temp_max_c` values — the tightest band that
        satisfies every lot. A shipment with no lines is rejected. If the
        resulting minimum exceeds the maximum, the lots cannot travel together
        and pack completion is rejected with `ERR_INCOMPATIBLE_TEMPERATURE_BANDS`
        (HTTP 422)."

        Design: Corner/calculations/shipment_temperature_band_uses_tightest_intersection
        """
        shipment = self._setup_mixed_band_shipment(api)
        resp = api.pack_complete(shipment["id"], LOGISTICS_COORDINATOR_HEADERS)
        # max(min_c) = 15 > min(max_c) = 8 -> incompatible.
        validate_error(resp, E.ERR_INCOMPATIBLE_TEMPERATURE_BANDS, 422)
        shipment_after = fixtures.get_shipment(api, shipment["id"])
        assert shipment_after["status"] == "PACKING"
