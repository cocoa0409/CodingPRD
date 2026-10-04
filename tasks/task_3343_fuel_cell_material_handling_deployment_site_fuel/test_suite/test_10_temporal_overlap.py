"""Resource temporal overlap: strict-overlap technician windows (PRD §3.4) and
half-open contract windows per (site, supply_mode) (PRD §3.2).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_site, create_technician, create_approved_assessment,
    create_scheduled_plan, create_event, create_supply_contract_payload,
    MANAGER,
)


def _setup_plan_with_morning_event(api):
    """Technician with an existing SCHEDULED event 2026-10-05T08:00-10:00."""
    site = create_site(code="S-OV1")
    tech = create_technician(name="Tech Overlap")
    create_approved_assessment(
        site["id"], forklift_count=5, duty_cycle_hours_per_day=8.0,
        peak_shift_hours=8)
    plan = create_scheduled_plan(
        site["id"], name="Wave OV", target_forklift_count=3,
        transition_mode="PARALLEL", start_date="2026-10-01",
        end_date="2026-10-31", baseline_productivity_units_per_hour=50.0,
        expected_productivity_gain_pct=10)
    ev1 = create_event(
        plan["id"], tech["id"], forklift_id="FL-O1",
        scheduled_start="2026-10-05T08:00:00Z",
        scheduled_end="2026-10-05T10:00:00Z")
    return plan, tech, ev1


class TestTechnicianStrictOverlap:
    def test_touching_windows_allowed(self, api):
        """PRD §3.4: "Strict overlap means the new window starts before the
        other's end **and** ends after the other's start; windows that merely
        touch (one's end equal to the other's start) are allowed."

        Design: Difficulty/resource_temporal_overlap/technician_strict_overlap_touching_allowed
        """
        plan, tech, _ev1 = _setup_plan_with_morning_event(api)
        resp = api.create_conversion_event(plan["id"], {
            "forklift_id": "FL-O2",
            "scheduled_start": "2026-10-05T10:00:00Z",
            "scheduled_end": "2026-10-05T12:00:00Z",
            "technician_id": tech["id"]}, MANAGER)
        event = validate_success(resp, 201)
        assert event["status"] == "SCHEDULED"

    def test_one_minute_overlap_rejected(self, api):
        """PRD §3.4: "creating an event whose window strictly overlaps another
        event assigned to the same technician — where the other event is
        `SCHEDULED` or `IN_PROGRESS` — is rejected with
        `ERR_TECHNICIAN_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/technician_strict_overlap_touching_allowed
        """
        plan, tech, _ev1 = _setup_plan_with_morning_event(api)
        validate_success(api.create_conversion_event(plan["id"], {
            "forklift_id": "FL-O2",
            "scheduled_start": "2026-10-05T10:00:00Z",
            "scheduled_end": "2026-10-05T12:00:00Z",
            "technician_id": tech["id"]}, MANAGER), 201)
        resp = api.create_conversion_event(plan["id"], {
            "forklift_id": "FL-O3",
            "scheduled_start": "2026-10-05T09:59:00Z",
            "scheduled_end": "2026-10-05T11:00:00Z",
            "technician_id": tech["id"]}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED)


class TestContractHalfOpenOverlap:
    def _existing_contract(self, api):
        site = create_site(code="S-OV2")
        c1 = validate_success(api.create_supply_contract(
            site["id"], create_supply_contract_payload(
                supply_mode="DELIVERED_LIQUID", start_date="2026-10-01",
                end_date="2026-12-31", base_price_per_kg=2.0,
                reliability_sla_pct=99.0, committed_monthly_kg=50), MANAGER), 201)
        return site, c1

    def test_back_to_back_accepted_overlapping_rejected(self, api):
        """PRD §3.2: "The overlap test is half-open — two windows where one's
        `start_date` equals the other's `end_date` sit back-to-back without
        overlapping — and contracts of different supply modes may overlap
        freely. A violation is rejected with `ERR_CONTRACT_PERIOD_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/contract_half_open_same_mode_overlap
        """
        site, _c1 = self._existing_contract(api)
        back_to_back = api.create_supply_contract(
            site["id"], create_supply_contract_payload(
                supply_mode="DELIVERED_LIQUID", start_date="2026-12-31",
                end_date="2027-03-31", base_price_per_kg=2.1,
                reliability_sla_pct=99.0, committed_monthly_kg=50), MANAGER)
        validate_success(back_to_back, 201)
        overlapping = api.create_supply_contract(
            site["id"], create_supply_contract_payload(
                supply_mode="DELIVERED_LIQUID", start_date="2026-12-30",
                end_date="2027-03-31", base_price_per_kg=2.1,
                reliability_sla_pct=99.0, committed_monthly_kg=50), MANAGER)
        validate_error(overlapping, ApiErrorId.ERR_CONTRACT_PERIOD_OVERLAP)

    def test_different_supply_mode_may_overlap_freely(self, api):
        """PRD §3.2: "The overlap test is half-open — two windows where one's
        `start_date` equals the other's `end_date` sit back-to-back without
        overlapping — and contracts of different supply modes may overlap
        freely. A violation is rejected with `ERR_CONTRACT_PERIOD_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/contract_half_open_same_mode_overlap
        """
        site, _c1 = self._existing_contract(api)
        resp = api.create_supply_contract(
            site["id"], create_supply_contract_payload(
                supply_mode="PIPELINE", start_date="2026-11-01",
                end_date="2027-01-31", base_price_per_kg=2.4,
                reliability_sla_pct=99.5, committed_monthly_kg=40), MANAGER)
        contract = validate_success(resp, 201)
        assert contract["supply_mode"] == "PIPELINE"
