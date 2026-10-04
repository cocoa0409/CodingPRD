"""Boundary precision: the availability SLA strictly-below trigger (PRD §3.5)
and the inclusive 200 kg indoor storage ceiling (PRD §2.7).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_site, create_approved_assessment, create_active_agreement,
    report_downtime, create_station_payload,
    MANAGER, BILLING,
)


def _setup_availability_site(api):
    """Site with APPROVED assessment (forklift_count 1 -> 730 fleet hours) and
    an ACTIVE agreement: guarantee 90.0%, monthly fee 2,000,000 cents."""
    site = create_site(code="S-BND")
    create_approved_assessment(
        site["id"], forklift_count=1, duty_cycle_hours_per_day=8.0,
        peak_shift_hours=8)
    create_active_agreement(
        site["id"], coverage_start="2026-10-01", coverage_end="2027-09-30",
        availability_guarantee_pct=90.0, monthly_fee_cents=2000000)
    return site


class TestAvailabilityBoundary:
    def test_availability_exactly_at_guarantee_earns_no_credit(self, api):
        """PRD §3.5: "The SLA credit triggers only when availability falls
        **strictly below** the guarantee — a month landing exactly on the
        guarantee earns nothing."
        PRD §3.5: "`availability_pct` is one hundred times one minus the ratio
        of downtime hours to fleet hours, rounded half-up to 2 decimal places."

        Design: Difficulty/boundary_precision_check/availability_exactly_at_guarantee_earns_no_credit
        """
        site = _setup_availability_site(api)
        report_downtime(site["id"], month="2026-10", forklift_id="FL-B1",
                        downtime_hours=73.0)
        report = validate_success(
            api.get_availability_report(site["id"], "2026-10", BILLING))
        # 100 x (1 - 73/730) = 90.00 — exactly AT the 90.0 guarantee.
        assert report["downtime_hours"] == pytest.approx(73.0)
        assert report["availability_pct"] == pytest.approx(90.0)
        assert report["guarantee_pct"] == pytest.approx(90.0)
        assert report["credit_cents"] == 0, "the boundary itself never fires"

    def test_availability_one_step_below_guarantee_earns_credit(self, api):
        """PRD §3.5: "When it does trigger, `credit_cents` is the agreement's
        `monthly_fee_cents` multiplied by a 10 percent credit rate, rounded
        half-up to integer cents."
        PRD §3.5: "Fleet capacity is the `forklift_count` of the site's
        latest-created `APPROVED` assessment multiplied by 730 hours per month"

        Design: Difficulty/boundary_precision_check/availability_exactly_at_guarantee_earns_no_credit
        """
        site = _setup_availability_site(api)
        report_downtime(site["id"], month="2026-10", forklift_id="FL-B1",
                        downtime_hours=73.0)
        report_downtime(site["id"], month="2026-10", forklift_id="FL-B2",
                        downtime_hours=73.0)
        report = validate_success(
            api.get_availability_report(site["id"], "2026-10", BILLING))
        # 146 / 730 -> availability 80.00, strictly below 90.0.
        assert report["downtime_hours"] == pytest.approx(146.0)
        assert report["availability_pct"] == pytest.approx(80.0)
        # ROUND_HALF_UP(2,000,000 x 0.10) = 200,000 cents.
        assert report["credit_cents"] == 200000


class TestIndoorStorageCeiling:
    def test_indoor_station_at_exactly_200kg_accepted(self, api):
        """PRD §2.7: "An `INDOOR` station's `storage_capacity_kg` must not
        exceed 200 kg — the fire-code maximum for indoor hydrogen storage;
        violating this at station creation or at a later station update is
        rejected with `ERR_INDOOR_STORAGE_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/indoor_storage_at_exactly_200kg_accepted
        """
        site = create_site(code="S-CAP")
        resp = api.create_station(site["id"], create_station_payload(
            station_code="ST-OK", location_type="INDOOR",
            capacity_kg_per_day=100, storage_capacity_kg=200,
            construction_start="2026-10-01", construction_end="2026-11-01"), MANAGER)
        station = validate_success(resp, 201)
        assert station["construction_status"] == "PLANNED"
        assert station["storage_capacity_kg"] == pytest.approx(200)

    def test_indoor_station_above_200kg_rejected(self, api):
        """PRD §2.7: "An `INDOOR` station's `storage_capacity_kg` must not
        exceed 200 kg — the fire-code maximum for indoor hydrogen storage;
        violating this at station creation or at a later station update is
        rejected with `ERR_INDOOR_STORAGE_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/indoor_storage_at_exactly_200kg_accepted
        """
        site = create_site(code="S-CAP")
        resp = api.create_station(site["id"], create_station_payload(
            station_code="ST-NO", location_type="INDOOR",
            capacity_kg_per_day=100, storage_capacity_kg=200.01,
            construction_start="2026-10-01", construction_end="2026-11-01"), MANAGER)
        validate_error(resp, ApiErrorId.ERR_INDOOR_STORAGE_EXCEEDED)
