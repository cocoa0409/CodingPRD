"""Corner-queue tests: entity creation, retrieval, defaults, computed fields."""
import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    CONTRACT_ADMIN,
    COORDINATOR,
    NON_EXISTENT_UUID,
    SPECIALIST,
    activate_care_team_for,
    activate_enrollment,
    api_client,
    create_care_program_payload,
    create_capitated_contract_payload,
    create_clinician,
    create_member,
    create_member_payload,
    create_member_with_enrollment,
    create_medical_cost_payload,
    create_pcp,
    create_program,
    create_scheduled_visit,
    create_settlement,
    drive_enrollment_to_consented,
    drive_enrollment_to_outreach,
    get_care_team_row,
    get_measurement_for_member,
    get_success_data,
    setup_active_enrollment,
    setup_basic_reference,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId


class TestCareProgramEntity:
    def test_care_program_creation_201_and_fields_returned(self, api):
        """PRD section 3.1: "They register a `CareProgram` with a unique `program_code` (for example, `LANDMARK-TX-001`), a human-readable `display_name`, the `service_geography_zips` list, and an optional `urgent_response_sla_hours` that defaults to 24 hours — the contractual ceiling from an urgent trigger to a clinician on scene. At creation the program's `current_period_index` is initialized to 0 and advances only via the operator's period-advance capability, which takes a `by_days` increment."

        Design: Corner/entities/care_program_creation_201_and_fields_returned
        """
        payload = create_care_program_payload()
        del payload["urgent_response_sla_hours"]
        resp = api.create_care_program(payload, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["program_code"] == payload["program_code"]
        assert data["current_period_index"] == 0
        assert data["urgent_response_sla_hours"] == 24

    def test_care_program_retrieval_returns_stored_fields(self, api):
        """PRD section 4: "New resources are returned with HTTP 201; all other successful operations, including state transitions, return HTTP 200."
        PRD section 3.1: "They register a `CareProgram` with a unique `program_code` (for example, `LANDMARK-TX-001`), a human-readable `display_name`, the `service_geography_zips` list, and an optional `urgent_response_sla_hours` that defaults to 24 hours — the contractual ceiling from an urgent trigger to a clinician on scene."

        Design: Corner/entities/care_program_retrieval_returns_stored_fields
        """
        program = create_program()
        data = validate_success(api.get_care_program(program["id"], ADMIN))
        assert data["program_code"] == program["program_code"]
        assert data["service_geography_zips"] == program["service_geography_zips"]
        assert data["urgent_response_sla_hours"] == program["urgent_response_sla_hours"]

    def test_care_program_not_found_404(self, api):
        """PRD section 2.6: "3. Path-template identifiers resolve to existing resources, validated left-to-right along the URL — failure is the resource-specific not-found error (e.g., `ERR_MEMBER_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_EPISODE_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_PCP_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CARE_TEAM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_MEASUREMENT_NOT_FOUND`), or the generic `ERR_NOT_FOUND` when no resource-specific code applies."

        Design: Corner/entities/care_program_not_found_404
        """
        resp = api.get_care_program(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND, expected_status=404)


class TestPayerContractEntity:
    def test_capitated_contract_requires_pmpm_rate(self, api):
        """PRD section 2.8: "A `CAPITATED` contract must supply `pmpm_rate_cents` (the per-member-per-month capitation rate in integer cents); a `SHARED_SAVINGS` contract must supply both `shared_savings_baseline_pmpm_cents` (the baseline medical cost per member per month against which savings are computed) and `shared_savings_split_pct` (the provider's share of any pooled savings, expressed as a number between 0 and 1). Mixing models — omitting the rate the chosen model requires — is rejected at creation with `ERR_PAYMENT_MODEL_MISMATCH` (HTTP 400)."

        Design: Corner/entities/payer_contract_creation_capitated_requires_pmpm
        """
        program = create_program()
        payload = create_capitated_contract_payload(program["id"])
        del payload["pmpm_rate_cents"]
        resp = api.create_payer_contract(payload, CONTRACT_ADMIN)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_MODEL_MISMATCH, expected_status=400)

    def test_shared_savings_contract_requires_baseline_and_split(self, api):
        """PRD section 2.8: "A `CAPITATED` contract must supply `pmpm_rate_cents` (the per-member-per-month capitation rate in integer cents); a `SHARED_SAVINGS` contract must supply both `shared_savings_baseline_pmpm_cents` (the baseline medical cost per member per month against which savings are computed) and `shared_savings_split_pct` (the provider's share of any pooled savings, expressed as a number between 0 and 1). Mixing models — omitting the rate the chosen model requires — is rejected at creation with `ERR_PAYMENT_MODEL_MISMATCH` (HTTP 400)."

        Design: Corner/entities/payer_contract_creation_shared_savings_requires_baseline_and_split
        """
        program = create_program()
        payload = {
            "care_program_id": program["id"],
            "payer_name": "PlanSS",
            "contract_effective_date": "2026-01-01T00:00:00Z",
            "contract_expiration_date": "2027-12-31T23:59:59Z",
            "payment_model": "SHARED_SAVINGS",
            "shared_savings_split_pct": 0.50,
        }
        resp = api.create_payer_contract(payload, CONTRACT_ADMIN)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_MODEL_MISMATCH, expected_status=400)


class TestClinicianEntity:
    def test_clinician_creation_defaults_active_and_zero_count(self, api):
        """PRD section 3.1: "A newly registered clinician starts with `status` set to `ACTIVE` and `active_daily_visit_count` at 0."

        Design: Corner/entities/clinician_creation_defaults_active_and_zero_count
        """
        program = create_program()
        clinician = create_clinician(program["id"])
        assert clinician["status"] == "ACTIVE"
        assert clinician["active_daily_visit_count"] == 0


class TestMemberEntity:
    def test_member_creation_computes_provisional_burden_and_tier(self, api):
        """PRD section 3.2: "First, each chronic condition code contributes a per-condition weight: `CHF` contributes 6 points, `COPD` 5, `CKD` 4, `DIABETES` 3, `DEMENTIA` 7, `DEPRESSION` 2, and `HTN` 1. Second, each prior emergency-department visit in the trailing twelve months contributes 3 points, so the `prior_ed_visits_12mo` count is multiplied by 3. Third, each prior inpatient admission in the trailing twelve months contributes 5 points, so the `prior_inpatient_admits_12mo` count is multiplied by 5."
        PRD section 3.2: "A score of at least 15 but below 25 yields `HIGH`."

        Design: Corner/entities/member_creation_computes_provisional_burden_and_tier
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        member = create_member(
            program["id"], contract["id"], pcp["id"],
            chronic_condition_codes=["CHF"],
            prior_ed_visits_12mo=2,
            prior_inpatient_admits_12mo=1,
        )
        assert member["burden_score_provisional"] == 17
        assert member["risk_tier"] == "HIGH"


class TestVisitEntity:
    def test_visit_creation_assigns_clinician_by_selector_not_client(self, api):
        """PRD section 3.5: "The server — never the client — assigns the `clinician_id` via a deterministic selector (the routine visit clinician selector, named `routine_visit_clinician_selector` in the rule catalogue)."

        Design: Corner/entities/visit_creation_assigns_clinician_by_selector_not_client
        """
        ctx = setup_active_enrollment()
        resp = api.create_visit(
            {
                "enrollment_id": ctx["enrollment"]["id"],
                "visit_type": "ROUTINE_FOLLOWUP",
                "scheduled_start": "2026-09-02T09:00:00Z",
                "scheduled_end": "2026-09-02T10:00:00Z",
                "clinician_id": NON_EXISTENT_UUID,
            },
            COORDINATOR,
        )
        visit = validate_success(resp, expected_status=201)
        assert visit["clinician_id"] == ctx["np"]["id"]
        assert visit["clinician_id"] != NON_EXISTENT_UUID


class TestMedicalCostEntity:
    def test_medical_cost_amount_zero_accepted(self, api):
        """PRD section 3.7: "(a `ContractAdministrator` records `MedicalCost` rows as costs are observed, supplying `payer_contract_id`, `member_id`, `period_index`, `amount_cents` which must be greater than or equal to 0, and `incurred_date`)."

        Design: Corner/entities/medical_cost_amount_zero_accepted
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        member = create_member(program["id"], contract["id"], pcp["id"])
        resp = api.create_medical_cost(
            create_medical_cost_payload(contract["id"], member["id"], amount_cents=0),
            CONTRACT_ADMIN,
        )
        cost = validate_success(resp, expected_status=201)
        assert cost["amount_cents"] == 0


class TestEnrollmentEntity:
    def test_enrollment_creation_sets_is_current_true_and_attempts_zero(self, api):
        """PRD section 3.3: "At creation the new `MemberEnrollment` starts in `IDENTIFIED` status with `is_current` set to `true` and `outreach_attempts` at 0, and any prior enrollment for the same member that was still `is_current` flips to `false`."

        Design: Corner/entities/enrollment_creation_sets_is_current_true_and_outreach_attempts_zero
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        assert enrollment["status"] == "IDENTIFIED"
        assert enrollment["is_current"] is True
        assert enrollment["outreach_attempts"] == 0


class TestCareTeamEntity:
    def test_composition_complete_false_when_only_np_set(self, api):
        """PRD section 3.4: "After each assignment the system recomputes `composition_complete`, which is `true` only when all three slots are populated."

        Design: Corner/entities/care_team_composition_complete_false_when_only_np_set
        """
        program, contract, pcp, np = setup_basic_reference()
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_consented(enrollment["id"])
        resp = api.update_care_team(enrollment["id"], {"primary_np_id": np["id"]}, COORDINATOR)
        team = validate_success(resp)
        assert team["composition_complete"] is False

    def test_composition_complete_true_when_all_three_set(self, api):
        """PRD section 3.4: "After each assignment the system recomputes `composition_complete`, which is `true` only when all three slots are populated."

        Design: Corner/entities/care_team_composition_complete_true_when_all_three_set
        """
        program, contract, pcp, np = setup_basic_reference()
        sw = create_clinician(program["id"], full_name="Sam SW", discipline="SW")
        bh = create_clinician(program["id"], full_name="Bob BH", discipline="BH")
        _member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_consented(enrollment["id"])
        resp = api.update_care_team(
            enrollment["id"],
            {
                "primary_np_id": np["id"],
                "social_worker_id": sw["id"],
                "behavioral_clinician_id": bh["id"],
            },
            COORDINATOR,
        )
        team = validate_success(resp)
        assert team["composition_complete"] is True


class TestPerformanceMeasurementEntity:
    def test_measurement_created_on_enrollment_activate(self, api):
        """PRD section 3.5: "Activation also seeds the performance infrastructure: a `PerformanceMeasurement` row is created for the triple of (`member.payer_contract_id`, `member.id`, `current_period_index`) if one does not already exist, with every counter at 0 and `composite_score` initialized to 1.0 — each of the score's components falls back to 1.0 when its denominator is empty (§3.7)."

        Design: Corner/entities/performance_measurement_created_on_enrollment_activate
        """
        ctx = setup_active_enrollment()
        row = get_measurement_for_member(ctx["member"]["id"])
        assert row["urgent_episodes_triggered"] == 0
        assert row["visits_completed"] == 0
        assert row["composite_score"] == pytest.approx(1.0, abs=1e-9)


class TestSettlementEntity:
    def test_settlement_creation_provisional_with_period_index(self, api):
        """PRD section 3.7: "Generating a settlement creates a `PayerSettlement` in `PROVISIONAL` status with `period_index` set to the program's current `current_period_index`, and runs the payment-model-appropriate calculation — `capitated_settlement_amount` for a `CAPITATED` contract or `shared_savings_settlement_amount` for a `SHARED_SAVINGS` contract."

        Design: Corner/entities/settlement_creation_provisional_with_period_index
        """
        ctx = setup_active_enrollment()
        settle = create_settlement(ctx["contract"]["id"])
        assert settle["status"] == "PROVISIONAL"
        assert settle["period_index"] == 0
