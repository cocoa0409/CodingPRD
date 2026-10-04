"""Depth tests: dual-variant calculations and combinatorial formulas."""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    DONOR_REPORTING_OFFICER_HEADERS,
    assert_money_two_dp,
)
from test_helpers import fixtures


class TestValuationSnapshotDualVariant:
    """The same two lots produce different totals under the two valuation methods."""

    def _setup_donor_with_two_lots(self, api):
        fixtures.set_clock(api)
        donor = fixtures.create_donor(
            api,
            legal_name="Meridian Pharma",
            country_code="US",
            tax_id="12-3456789",
            dea_registration_no="BM1234567",
        )
        fixtures.create_lot(
            api,
            donor["id"],
            ndc_code="00001-0001-01",
            product_name="Amoxicillin 500mg",
            quantity_received=100,
            unit_acquisition_value_usd=1.25,
            unit_wholesale_value_usd=2.00,
        )
        fixtures.create_lot(
            api,
            donor["id"],
            ndc_code="00002-0002-01",
            product_name="Lisinopril 10mg",
            quantity_received=40,
            unit_acquisition_value_usd=3.10,
            unit_wholesale_value_usd=4.05,
        )
        return donor

    def test_acquisition_cost_snapshot_total(self, api):
        """PRD §3.10: "Each included lot contributes its `quantity_received`
        multiplied by the per-unit value for the chosen method —
        `unit_acquisition_value_usd` under `ACQUISITION_COST` (the basis required
        for donor tax reporting) or `unit_wholesale_value_usd` under
        `WHOLESALE_REFERENCE` (the basis used for GAAP inventory disclosure)."

        Design: Difficulty/dual_variant_calc/valuation_snapshot_acquisition_vs_wholesale_diverge
        """
        donor = self._setup_donor_with_two_lots(api)
        resp = api.create_valuation_snapshot(
            {
                "donor_id": donor["id"],
                "snapshot_period": "2026-09",
                "method": "ACQUISITION_COST",
            },
            DONOR_REPORTING_OFFICER_HEADERS,
        )
        snap = validate_success(resp, 201)
        assert snap["total_value_usd"] == pytest.approx(249.00, abs=0.001), (
            f"expected 100*1.25 + 40*3.10 = 249.00, got {snap['total_value_usd']}"
        )
        assert snap["lot_count"] == 2

    def test_wholesale_reference_snapshot_diverges(self, api):
        """PRD §3.10: "Each included lot contributes its `quantity_received`
        multiplied by the per-unit value for the chosen method —
        `unit_acquisition_value_usd` under `ACQUISITION_COST` (the basis required
        for donor tax reporting) or `unit_wholesale_value_usd` under
        `WHOLESALE_REFERENCE` (the basis used for GAAP inventory disclosure)."

        Design: Difficulty/dual_variant_calc/valuation_snapshot_acquisition_vs_wholesale_diverge
        """
        donor = self._setup_donor_with_two_lots(api)
        acq = validate_success(
            api.create_valuation_snapshot(
                {
                    "donor_id": donor["id"],
                    "snapshot_period": "2026-09",
                    "method": "ACQUISITION_COST",
                },
                DONOR_REPORTING_OFFICER_HEADERS,
            ),
            201,
        )
        whl = validate_success(
            api.create_valuation_snapshot(
                {
                    "donor_id": donor["id"],
                    "snapshot_period": "2026-09",
                    "method": "WHOLESALE_REFERENCE",
                },
                DONOR_REPORTING_OFFICER_HEADERS,
            ),
            201,
        )
        assert whl["total_value_usd"] == pytest.approx(362.00, abs=0.001), (
            f"expected 100*2.00 + 40*4.05 = 362.00, got {whl['total_value_usd']}"
        )
        assert whl["lot_count"] == 2
        assert acq["total_value_usd"] != whl["total_value_usd"], (
            "the two methods must diverge on these lots"
        )


class TestNeedScoreEmergencyVariant:
    """Identical sites diverge on need_score when one request is emergency-anchored."""

    def _setup_pair(self, api):
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot1 = fixtures.create_and_release_lot(api, donor["id"], ndc_code="X1")
        lot2 = fixtures.create_and_release_lot(api, donor["id"], ndc_code="X2")
        site_a = fixtures.setup_qualified_site(
            api,
            organization_name="Clinic A",
            monthly_patient_volume=2000,
            underserved_index=0.5,
        )
        site_b = fixtures.setup_qualified_site(
            api,
            organization_name="Clinic B",
            monthly_patient_volume=2000,
            underserved_index=0.5,
        )
        event = fixtures.create_active_event(
            api, event_name="Hurricane Delta", severity=3, affected_country_codes=["US"]
        )
        return donor, lot1, lot2, site_a, site_b, event

    def _finalize(self, api, site_id, lot_id, ndc, emergency_event_id=None):
        request = fixtures.create_request(
            api, site_id, quantity_requested=10, ndc_code=ndc,
            emergency_event_id=emergency_event_id,
        )
        fixtures.begin_review(api, request["id"])
        current = fixtures.get_request(api, request["id"])
        decision = fixtures.create_draft_decision(
            api, request["id"], [{"lot_id": lot_id, "quantity": 10}]
        )
        fixtures.finalize_decision(api, decision["id"], current["version"])
        return fixtures.get_request(api, request["id"])

    def test_emergency_anchored_request_scores_higher(self, api):
        """PRD §3.6: "The emergency component contributes ten points per unit of
        the referenced event's `severity`, but only when the request references an
        `EmergencyEvent` whose status is `ACTIVE` at finalize time; otherwise it
        contributes zero."

        Design: Difficulty/dual_variant_calc/need_score_emergency_weighted_vs_standard_diverge
        """
        _, lot1, lot2, site_a, site_b, event = self._setup_pair(api)
        req_a = self._finalize(api, site_a["id"], lot1["id"], "X1", emergency_event_id=event["id"])
        req_b = self._finalize(api, site_b["id"], lot2["id"], "X2")
        assert req_a["need_score"] == pytest.approx(130.00, abs=0.001), (
            f"expected 100*0.5 + 25*min(2000/1000,2) + 10*3 = 130.00, got {req_a['need_score']}"
        )
        assert req_b["need_score"] == pytest.approx(100.00, abs=0.001), (
            f"expected 100*0.5 + 25*min(2000/1000,2) = 100.00, got {req_b['need_score']}"
        )

    def test_emergency_divergence_is_exactly_ten_times_severity(self, api):
        """PRD §3.6: "The emergency component contributes ten points per unit of
        the referenced event's `severity`, but only when the request references an
        `EmergencyEvent` whose status is `ACTIVE` at finalize time; otherwise it
        contributes zero."

        Design: Difficulty/dual_variant_calc/need_score_emergency_weighted_vs_standard_diverge
        """
        _, lot1, lot2, site_a, site_b, event = self._setup_pair(api)
        req_a = self._finalize(api, site_a["id"], lot1["id"], "X1", emergency_event_id=event["id"])
        req_b = self._finalize(api, site_b["id"], lot2["id"], "X2")
        assert req_a["need_score"] - req_b["need_score"] == pytest.approx(30.00, abs=0.001)


class TestNeedScoreCombinatorial:
    """Multi-input formula: volume cap saturates at 2000 patients/month."""

    def test_volume_cap_saturates_at_maximum_points(self, api):
        """PRD §3.6: "The volume component takes the site's
        `monthly_patient_volume`, divides it by 1000, caps the result at 2.0, and
        multiplies the capped figure by 25 — so a site reporting 1000 patients per
        month earns 25 volume points and any site at or above 2000 patients per
        month earns the maximum 50."

        Design: Difficulty/combinatorial_formula/need_score_multi_input_non_linear_mode_a
        """
        fixtures.set_clock(api)
        world = fixtures.setup_finalized_decision(
            api,
            quantity_requested=5,
            site_overrides={
                "organization_name": "Big Clinic",
                "site_type": "FQHC",
                "monthly_patient_volume": 5000,
                "underserved_index": 0.8,
            },
        )
        request = world["request"]
        assert request["need_score"] == pytest.approx(130.00, abs=0.001), (
            f"expected 100*0.8 + 25*min(5000/1000,2) = 130.00, got {request['need_score']}"
        )
        assert_money_two_dp(request["need_score"])

    def test_full_coverage_request_approved_with_full_quantity(self, api):
        """PRD §3.5: "The request then transitions to `APPROVED` when the
        finalized lines exactly cover `quantity_requested`, or to
        `PARTIALLY_APPROVED` when they cover a positive quantity less than
        `quantity_requested`; `quantity_approved` is set to the covered amount,
        and the request's `version` increments."

        Design: Difficulty/combinatorial_formula/need_score_multi_input_non_linear_mode_a
        """
        fixtures.set_clock(api)
        world = fixtures.setup_finalized_decision(
            api,
            quantity_requested=5,
            site_overrides={
                "organization_name": "Big Clinic",
                "site_type": "FQHC",
                "monthly_patient_volume": 5000,
                "underserved_index": 0.8,
            },
        )
        request = world["request"]
        assert request["status"] == "APPROVED"
        assert request["quantity_approved"] == 5


class TestValuationPerLotRounding:
    """Per-lot rounding before summation; sum-then-round would differ by a cent."""

    def _setup_rounding_lots(self, api):
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        fixtures.create_lot(
            api, donor["id"], ndc_code="A", quantity_received=3,
            unit_acquisition_value_usd=0.335, unit_wholesale_value_usd=0.50,
        )
        fixtures.create_lot(
            api, donor["id"], ndc_code="B", quantity_received=7,
            unit_acquisition_value_usd=0.045, unit_wholesale_value_usd=0.10,
        )
        return donor

    def test_per_lot_rounding_then_sum_total(self, api):
        """PRD §2.11: "Both aggregation calculations that sum per-unit values —
        the donor valuation snapshot and the customs declared value — round each
        line's contribution to two decimal places *before* summing; summing raw
        products and rounding once at the end produces different cents, and this
        specification pins the per-line-then-sum order."

        Design: Difficulty/combinatorial_formula/valuation_per_lot_rounding_then_sum_mode_b
        """
        donor = self._setup_rounding_lots(api)
        resp = api.create_valuation_snapshot(
            {"donor_id": donor["id"], "snapshot_period": "2026-09", "method": "ACQUISITION_COST"},
            DONOR_REPORTING_OFFICER_HEADERS,
        )
        snap = validate_success(resp, 201)
        # round_half_up(3*0.335)=1.01, round_half_up(7*0.045)=0.32; sum-then-round
        # of the raw 1.320 would give 1.32 — the per-lot order pins 1.33.
        assert snap["total_value_usd"] == pytest.approx(1.33, abs=0.001), (
            f"expected per-lot-then-sum 1.01 + 0.32 = 1.33, got {snap['total_value_usd']}"
        )

    def test_per_lot_rounding_lot_count(self, api):
        """PRD §3.10: "`lot_count` records how many lots were included, and
        `generated_at` is stamped from the logical clock."

        Design: Difficulty/combinatorial_formula/valuation_per_lot_rounding_then_sum_mode_b
        """
        donor = self._setup_rounding_lots(api)
        resp = api.create_valuation_snapshot(
            {"donor_id": donor["id"], "snapshot_period": "2026-09", "method": "ACQUISITION_COST"},
            DONOR_REPORTING_OFFICER_HEADERS,
        )
        snap = validate_success(resp, 201)
        assert snap["lot_count"] == 2
