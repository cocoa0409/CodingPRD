"""Corner-queue tests: calculation rules (burden scoring, composite, settlements, selectors)."""
import pytest

from test_helpers import (
    ApiErrorId,
    COORDINATOR,
    activate_care_team_for,
    activate_enrollment,
    api_client,
    create_clinician,
    create_dispatched_episode,
    create_medical_cost_payload,
    create_member,
    create_member_with_enrollment,
    create_pcp,
    create_program,
    create_scheduled_visit,
    create_settlement,
    create_shared_savings_contract,
    create_triggered_episode,
    dispatch_episode,
    drive_enrollment_to_consented,
    get_measurement_for_member,
    get_success_data,
    setup_active_enrollment,
    setup_basic_reference,
    validate_error,
    validate_success,
)
from test_helpers import CONTRACT_ADMIN


def _member_score(program, contract, pcp, codes, ed, ip):
    member = create_member(
        program["id"], contract["id"], pcp["id"],
        chronic_condition_codes=codes,
        prior_ed_visits_12mo=ed,
        prior_inpatient_admits_12mo=ip,
    )
    return member


class TestBurdenProvisional:
    def test_burden_provisional_exact_weight_sum(self, api):
        """PRD section 3.2: "First, each chronic condition code contributes a per-condition weight: `CHF` contributes 6 points, `COPD` 5, `CKD` 4, `DIABETES` 3, `DEMENTIA` 7, `DEPRESSION` 2, and `HTN` 1. Second, each prior emergency-department visit in the trailing twelve months contributes 3 points, so the `prior_ed_visits_12mo` count is multiplied by 3. Third, each prior inpatient admission in the trailing twelve months contributes 5 points, so the `prior_inpatient_admits_12mo` count is multiplied by 5. The three components are summed into a single integer; no rounding applies."

        Design: Corner/calculations/burden_provisional_exact_weight_sum
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        member = _member_score(program, contract, pcp, ["CHF"], 2, 1)
        assert member["burden_score_provisional"] == 17
        assert member["risk_tier"] == "HIGH"

    def test_burden_tier_boundary_medium_at_8(self, api):
        """PRD section 3.2: "A score of at least 8 but below 15 yields `MEDIUM`."

        Design: Corner/calculations/burden_provisional_risk_tier_boundary_medium
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        # COPD 5 + DIABETES 3 = 8 exactly.
        member = _member_score(program, contract, pcp, ["COPD", "DIABETES"], 0, 0)
        assert member["burden_score_provisional"] == 8
        assert member["risk_tier"] == "MEDIUM"

    def test_burden_tier_boundary_high_at_15(self, api):
        """PRD section 3.2: "A score of at least 15 but below 25 yields `HIGH`."

        Design: Corner/calculations/burden_provisional_risk_tier_boundary_high
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        # CHF 6 + COPD 5 + DIABETES 3 + 1 IP (5) = 19 -> too high; use CHF+COPD+DIABETES+0+...
        # 6 + 5 + 3 + 1 IP (5) = 19. To land exactly 15: CHF 6 + COPD 5 + DIABETES 3 + HTN 1 = 15.
        member = _member_score(program, contract, pcp, ["CHF", "COPD", "DIABETES", "HTN"], 0, 0)
        assert member["burden_score_provisional"] == 15
        assert member["risk_tier"] == "HIGH"

    def test_burden_tier_boundary_very_high_at_25(self, api):
        """PRD section 3.2: "A score of at least 25 yields `VERY_HIGH`."

        Design: Corner/calculations/burden_provisional_risk_tier_boundary_very_high
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        # CHF 6 + COPD 5 + DEMENTIA 7 = 18; + 3*? Let: 18 + 2 ED (6) + 0 IP = 24 -> one more HTN = 25.
        member = _member_score(
            program, contract, pcp,
            ["CHF", "COPD", "DEMENTIA", "HTN"], 2, 0,
        )
        assert member["burden_score_provisional"] == 25
        assert member["risk_tier"] == "VERY_HIGH"

    def test_burden_tier_low_below_medium(self, api):
        """PRD section 3.2: "A score below 8 yields `LOW`."

        Design: Corner/calculations/burden_provisional_risk_tier_low_below_medium
        """
        program, contract, pcp, _np = setup_basic_reference(with_clinician=False)
        # DIABETES 3 + HTN 1 + 1 ED (3) = 7.
        member = _member_score(program, contract, pcp, ["DIABETES", "HTN"], 1, 0)
        assert member["burden_score_provisional"] == 7
        assert member["risk_tier"] == "LOW"


class TestCompositeScore:
    def test_composite_empty_denominators_default_to_one(self, api):
        """PRD section 3.5: "Activation also seeds the performance infrastructure: a `PerformanceMeasurement` row is created for the triple of (`member.payer_contract_id`, `member.id`, `current_period_index`) if one does not already exist, with every counter at 0 and `composite_score` initialized to 1.0 — each of the score's components falls back to 1.0 when its denominator is empty (§3.7)."

        Design: Corner/calculations/composite_score_empty_denominators_default_to_one
        """
        ctx = setup_active_enrollment()
        row = get_measurement_for_member(ctx["member"]["id"])
        assert row["composite_score"] == pytest.approx(1.0, abs=1e-9)


class TestSettlementAmounts:
    def test_capitated_settlement_enrolled_member_count(self, api):
        """PRD section 3.7: "For a `CAPITATED` contract, the gross is `enrolled_member_count` multiplied by the contract's `pmpm_rate_cents`, recorded as `gross_capitation_cents`; `gross_savings_share_cents` is null on this branch."

        Design: Corner/calculations/capitated_settlement_enrolled_member_count
        """
        program, contract, pcp, np = setup_basic_reference()
        members = []
        for ext_id, codes, ed, ip in (
            ("M-001", ["CHF"], 1, 1),
            ("M-002", ["COPD"], 0, 1),
        ):
            member, enrollment = create_member_with_enrollment(
                program, contract, pcp,
                {"member_external_id": ext_id, "chronic_condition_codes": codes,
                 "prior_ed_visits_12mo": ed, "prior_inpatient_admits_12mo": ip},
            )
            drive_enrollment_to_consented(enrollment["id"])
            activate_care_team_for(enrollment["id"], np["id"])
            activate_enrollment(enrollment["id"])
            members.append(member)
        settle = create_settlement(contract["id"])
        assert settle["enrolled_member_count"] == 2
        assert settle["gross_capitation_cents"] == 1000000

    def test_shared_savings_pooled_negative_floored_to_zero(self, api):
        """PRD section 3.7: "Third, the pool is floored at zero: if `pooled_savings_cents` is less than or equal to 0 the provider's gross share is 0 (there is no clawback); otherwise `gross_savings_share_cents` is the product of `pooled_savings_cents` and the contract's `shared_savings_split_pct`, rounded half-up to integer cents."

        Design: Corner/calculations/shared_savings_pooled_negative_floored_to_zero
        """
        program = create_program()
        ss = create_shared_savings_contract(program["id"])
        pcp = create_pcp(program["id"])
        np = create_clinician(program["id"])
        member, enrollment = create_member_with_enrollment(program, ss, pcp)
        drive_enrollment_to_consented(enrollment["id"])
        activate_care_team_for(enrollment["id"], np["id"])
        activate_enrollment(enrollment["id"])
        get_success_data(api.create_medical_cost(
            create_medical_cost_payload(ss["id"], member["id"], amount_cents=700000),
            CONTRACT_ADMIN,
        ))
        settle = create_settlement(ss["id"])
        assert settle["gross_savings_share_cents"] == 0


class TestSelectors:
    def test_routine_selector_earliest_created_at_tiebreak(self, api):
        """PRD section 3.5: "Within the eligible pool the selector ranks by lowest `active_daily_visit_count` first, then by earliest clinician `created_at`; the clinician `id` is never used as a tie-break."

        Design: Corner/calculations/routine_selector_excludes_inactive_clinician
        """
        program, contract, pcp, np1 = setup_basic_reference()
        np2 = create_clinician(program["id"], full_name="Nick NP")
        member, enrollment = create_member_with_enrollment(program, contract, pcp)
        drive_enrollment_to_consented(enrollment["id"])
        activate_care_team_for(enrollment["id"], np1["id"])
        activate_enrollment(enrollment["id"])
        # Both NPs are ACTIVE with count 0; the earlier-created NP wins.
        visit = create_scheduled_visit(enrollment["id"])
        assert visit["clinician_id"] == np1["id"]
        assert visit["clinician_id"] != np2["id"]

    def test_urgent_selector_requires_urgent_response_qualified(self, api):
        """PRD section 3.6: "The urgent selector is stricter than the routine one: candidates must be `ACTIVE` clinicians in the same program as the member, must have `urgent_response_qualified` set to `true`, must have a `home_zip` in the program's `service_geography_zips`, and must have `active_daily_visit_count` strictly below `max_daily_visits`."

        Design: Corner/calculations/urgent_selector_requires_urgent_response_qualified
        """
        ctx = setup_active_enrollment(
            clinician_overrides={"urgent_response_qualified": True}
        )
        create_clinician(
            ctx["program"]["id"], full_name="Nick NP", urgent_response_qualified=False
        )
        episode = create_triggered_episode(ctx["enrollment"]["id"])
        dispatched = dispatch_episode(episode["id"])
        assert dispatched["dispatched_clinician_id"] == ctx["np"]["id"]

    def test_urgent_selector_geography_exclusion(self, api):
        """PRD section 3.6: "The urgent selector is stricter than the routine one: candidates must be `ACTIVE` clinicians in the same program as the member, must have `urgent_response_qualified` set to `true`, must have a `home_zip` in the program's `service_geography_zips`, and must have `active_daily_visit_count` strictly below `max_daily_visits`."

        Design: Corner/calculations/urgent_selector_geography_exclusion
        """
        ctx = setup_active_enrollment(
            clinician_overrides={"urgent_response_qualified": True}
        )
        create_clinician(
            ctx["program"]["id"], full_name="Nick NP", home_zip="99999",
            urgent_response_qualified=True,
        )
        episode = create_triggered_episode(ctx["enrollment"]["id"])
        dispatched = dispatch_episode(episode["id"])
        assert dispatched["dispatched_clinician_id"] == ctx["np"]["id"]
