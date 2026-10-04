"""Cross-entity state dependencies: plan scheduling gated on the site's
APPROVED assessment (PRD §3.4); dispense events gated on the station's own
COMMISSIONED status (PRD §3.6).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_site, create_assessment_payload, create_active_contract,
    create_planned_station, file_and_issue_permit, create_conversion_plan_payload,
    create_fueling_event_payload,
    MANAGER, SAFETY, COMPLIANCE,
)


def _setup_submitted_assessment_and_draft_plan(api):
    site = create_site(code="S-XD1")
    ass = get_success_data(api.create_assessment(
        site["id"], create_assessment_payload(
            forklift_count=4, duty_cycle_hours_per_day=8.0, peak_shift_hours=8),
        MANAGER))
    validate_success(api.submit_assessment(site["id"], ass["id"], MANAGER))
    plan = get_success_data(api.create_conversion_plan(
        site["id"], create_conversion_plan_payload(
            name="Wave X", target_forklift_count=4, transition_mode="PARALLEL",
            start_date="2026-10-05", end_date="2026-10-25",
            baseline_productivity_units_per_hour=50.0,
            expected_productivity_gain_pct=15), MANAGER))
    return site, ass, plan


class TestPlanScheduleGatedOnAssessment:
    def test_schedule_rejected_while_assessment_not_approved(self, api):
        """PRD §3.4: "The cross-entity gate: the site must have an assessment
        in `APPROVED` status, and the plan's `target_forklift_count` must not
        exceed that assessment's `forklift_count` — failure is
        `ERR_ASSESSMENT_NOT_APPROVED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/plan_schedule_blocked_by_unapproved_assessment
        """
        site, _ass, plan = _setup_submitted_assessment_and_draft_plan(api)
        resp = api.schedule_plan(
            site["id"], plan["id"], {"expected_plan_version": plan["version"]}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED)
        after = get_success_data(api.get_conversion_plan(plan["id"], MANAGER))
        assert after["status"] == "DRAFT", "a rejected schedule leaves the plan DRAFT"

    def test_schedule_succeeds_once_assessment_approved(self, api):
        """PRD §3.4: "The cross-entity gate: the site must have an assessment
        in `APPROVED` status, and the plan's `target_forklift_count` must not
        exceed that assessment's `forklift_count` — failure is
        `ERR_ASSESSMENT_NOT_APPROVED` (HTTP 422)."
        PRD §3.4: "A successful schedule moves the plan to `SCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/plan_schedule_blocked_by_unapproved_assessment
        """
        site, ass, plan = _setup_submitted_assessment_and_draft_plan(api)
        validate_error(
            api.schedule_plan(site["id"], plan["id"],
                              {"expected_plan_version": plan["version"]}, MANAGER),
            ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED)
        validate_success(api.approve_assessment(site["id"], ass["id"], SAFETY))
        scheduled = validate_success(api.schedule_plan(
            site["id"], plan["id"], {"expected_plan_version": plan["version"]}, MANAGER))
        assert scheduled["status"] == "SCHEDULED"


def _setup_station_in_construction(api):
    """ACTIVE contract + station with both base permits issued and construction
    started — but not yet commissioned."""
    site = create_site(code="S-XD2")
    contract = create_active_contract(
        site["id"], supply_mode="PIPELINE", base_price_per_kg=2.5,
        reliability_sla_pct=99.0, committed_monthly_kg=10)
    station = create_planned_station(
        site["id"], station_code="ST-X2", capacity_kg_per_day=200,
        storage_capacity_kg=500, construction_start="2026-10-01",
        construction_end="2026-11-01")
    file_and_issue_permit(station["id"], "CONSTRUCTION")
    file_and_issue_permit(station["id"], "FIRE")
    validate_success(api.start_construction(station["id"], MANAGER))
    return site, contract, station


class TestFuelingEventGatedOnStationState:
    def test_dispense_rejected_while_station_in_construction(self, api):
        """PRD §3.6: "The station must be `COMMISSIONED` and the `occurred_at`
        must not precede the station's `commissioned_at` — violations are
        `ERR_STATION_NOT_COMMISSIONED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/fueling_event_blocked_by_station_state
        """
        _site, contract, station = _setup_station_in_construction(api)
        resp = api.create_fueling_event(
            station["id"], create_fueling_event_payload(
                forklift_id="FL-X2", occurred_at="2026-10-05T08:00:00Z",
                kg_dispensed=10, supply_contract_id=contract["id"]), MANAGER)
        validate_error(resp, ApiErrorId.ERR_STATION_NOT_COMMISSIONED)

    def test_dispense_accepted_once_station_commissioned(self, api):
        """PRD §3.6: "The station must be `COMMISSIONED` and the `occurred_at`
        must not precede the station's `commissioned_at` — violations are
        `ERR_STATION_NOT_COMMISSIONED` (HTTP 422)."
        PRD §3.3: "Only a `COMMISSIONED` station may be referenced by dispense
        events."

        Design: Difficulty/cross_entity_state_dependency/fueling_event_blocked_by_station_state
        """
        _site, contract, station = _setup_station_in_construction(api)
        commissioned = validate_success(api.commission_station(station["id"], COMPLIANCE))
        assert commissioned["construction_status"] == "COMMISSIONED"
        assert commissioned["commissioned_at"] is not None
        resp = api.create_fueling_event(
            station["id"], create_fueling_event_payload(
                forklift_id="FL-X2", occurred_at="2026-10-05T08:00:00Z",
                kg_dispensed=10, supply_contract_id=contract["id"]), MANAGER)
        event = validate_success(resp, 201)
        assert event["station_id"] == station["id"]
