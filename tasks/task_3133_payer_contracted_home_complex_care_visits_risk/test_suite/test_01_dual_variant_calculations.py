"""Difficulty-queue tests: dual-variant calculations (risk scoring + settlement models)."""
import pytest

from test_helpers import (
    CONTRACT_ADMIN,
    activate_care_team_for,
    activate_enrollment,
    api_client,
    complete_visit,
    create_capitated_contract,
    create_clinician,
    create_medical_cost_payload,
    create_member_with_enrollment,
    create_pcp,
    create_program,
    create_scheduled_visit,
    create_settlement,
    create_shared_savings_contract,
    drive_enrollment_to_consented,
    finalize_settlement,
    get_success_data,
    setup_active_enrollment,
)
from test_helpers import ADMIN


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/burden_score_provisional_vs_final_diverge_on_same_member
# ---------------------------------------------------------------------------

def _setup_member_with_completed_assessment():
    """Member with CHF + 2 ED + 1 IP (provisional 17, HIGH), then one COMPLETED
    INITIAL_ASSESSMENT carrying the assessment signals from the design recipe."""
    ctx = setup_active_enrollment(member_overrides={
        "chronic_condition_codes": ["CHF"],
        "prior_ed_visits_12mo": 2,
        "prior_inpatient_admits_12mo": 1,
    })
    visit = create_scheduled_visit(
        ctx["enrollment"]["id"],
        visit_type="INITIAL_ASSESSMENT",
        start="2026-09-02T09:00:00Z",
        end="2026-09-02T10:00:00Z",
    )
    complete_visit(visit, assessment_overrides={
        "medication_reconciliation": {
            "medications_reviewed": 8,
            "discrepancies_found": 2,
            "high_risk_med_changes": 1,
        },
        "safety_evaluation": {
            "fall_risk_score": 4,
            "home_hazard_count": 2,
            "adl_impairment_count": 1,
        },
        "social_needs_screening": {
            "food_insecurity": True,
            "housing_instability": False,
            "transportation_barrier": True,
            "social_isolation_score": 3,
        },
        "pcp_coordination_note": "Discussed med changes with Dr. Patel; will fax summary.",
    })
    return ctx, visit


def test_burden_provisional_preserved_after_final_computed(api):
    """PRD section 3.2: "At creation, the system computes a provisional risk score, `burden_score_provisional`, from claims history alone (the calculation is named `chronic_condition_burden_provisional` in the rule catalogue)."
    PRD section 3.5: "The final score starts from the member's `burden_score_provisional` as a base and adds three bonuses on top."

    Design: Difficulty/dual_variant_calc/burden_score_provisional_vs_final_diverge_on_same_member
    """
    ctx, _visit = _setup_member_with_completed_assessment()
    member = get_success_data(api.get_member(ctx["member"]["id"], ADMIN))
    assert member["burden_score_provisional"] == 17, (
        f"provisional score must remain the claims-only 17, got {member['burden_score_provisional']}"
    )
    assert member["burden_score_final"] == 35, (
        f"final score must be 17 + 4 + 8 + 6 = 35, got {member['burden_score_final']}"
    )
    assert member["burden_score_final"] != member["burden_score_provisional"]


def test_burden_final_steps_risk_tier_up_to_very_high(api):
    """PRD section 3.2: "A score of at least 25 yields `VERY_HIGH`."
    PRD section 3.5: "Because the final score incorporates in-home signals on top of claims history, the same member's `risk_tier` may step up after the first completed initial assessment even though their claims history did not change."

    Design: Difficulty/dual_variant_calc/burden_score_provisional_vs_final_diverge_on_same_member
    """
    ctx, _visit = _setup_member_with_completed_assessment()
    member = get_success_data(api.get_member(ctx["member"]["id"], ADMIN))
    assert member["risk_tier"] == "VERY_HIGH", (
        f"risk_tier must step up from HIGH to VERY_HIGH after completion, got {member['risk_tier']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/capitated_vs_shared_savings_settlement_diverge_on_same_population
# ---------------------------------------------------------------------------

def _enroll_member_active(program, contract, pcp, np, member_overrides):
    member, enrollment = create_member_with_enrollment(program, contract, pcp, member_overrides)
    drive_enrollment_to_consented(enrollment["id"])
    activate_care_team_for(enrollment["id"], np["id"])
    activate_enrollment(enrollment["id"])
    return member, enrollment


def _setup_two_contract_population():
    program = create_program()
    cap = create_capitated_contract(program["id"], payer_name="PlanCap")
    ss = create_shared_savings_contract(program["id"], payer_name="PlanSS")
    pcp = create_pcp(program["id"])
    np = create_clinician(program["id"], urgent_response_qualified=True)
    m_cap, _e_cap = _enroll_member_active(program, cap, pcp, np, {
        "member_external_id": "CAP-001", "full_name": "Cap Member",
    })
    m_ss_a, _e_a = _enroll_member_active(program, ss, pcp, np, {
        "member_external_id": "SS-001", "full_name": "SS Member A",
    })
    m_ss_b, _e_b = _enroll_member_active(program, ss, pcp, np, {
        "member_external_id": "SS-002", "full_name": "SS Member B",
        "chronic_condition_codes": ["COPD"], "prior_inpatient_admits_12mo": 0,
    })
    for m in (m_ss_a, m_ss_b):
        get_success_data(api_client.create_medical_cost(
            create_medical_cost_payload(ss["id"], m["id"], amount_cents=450000),
            CONTRACT_ADMIN,
        ))
    return program, cap, ss, m_cap, m_ss_a, m_ss_b


def test_capitated_settlement_amounts_diverge_from_shared_savings(api):
    """PRD section 3.7: "For a `CAPITATED` contract, the gross is `enrolled_member_count` multiplied by the contract's `pmpm_rate_cents`, recorded as `gross_capitation_cents`; `gross_savings_share_cents` is null on this branch."
    PRD section 3.7: "The `net_payment_cents` is the gross minus the withhold plus the released withhold — for a `CAPITATED` contract, `gross_capitation_cents` minus `quality_withhold_cents` plus `withhold_released_cents`; for a `SHARED_SAVINGS` contract, `gross_savings_share_cents` minus `quality_withhold_cents` plus `withhold_released_cents`."

    Design: Difficulty/dual_variant_calc/capitated_vs_shared_savings_settlement_diverge_on_same_population
    """
    _program, cap, ss, _m_cap, _a, _b = _setup_two_contract_population()
    cap_settle = finalize_settlement(cap["id"], create_settlement(cap["id"])["id"])
    assert cap_settle["gross_capitation_cents"] == 500000
    assert cap_settle["quality_withhold_cents"] == 50000
    assert cap_settle["withhold_released_cents"] == 50000
    assert cap_settle["net_payment_cents"] == 500000
    assert cap_settle["gross_savings_share_cents"] is None

    ss_settle = finalize_settlement(ss["id"], create_settlement(ss["id"])["id"])
    assert ss_settle["gross_savings_share_cents"] == 150000
    assert ss_settle["net_payment_cents"] == 150000
    assert ss_settle["gross_capitation_cents"] is None
    assert cap_settle["net_payment_cents"] != ss_settle["net_payment_cents"]


def test_shared_savings_settlement_pool_split_withhold_amounts(api):
    """PRD section 3.7: "Second, the per-member deltas are pooled: `pooled_savings_cents` is the sum of `member_delta_cents` across all enrolled members, so losing members offset winning members."
    PRD section 3.7: "otherwise `gross_savings_share_cents` is the product of `pooled_savings_cents` and the contract's `shared_savings_split_pct`, rounded half-up to integer cents."

    Design: Difficulty/dual_variant_calc/capitated_vs_shared_savings_settlement_diverge_on_same_population
    """
    _program, _cap, ss, _m_cap, _a, _b = _setup_two_contract_population()
    ss_settle = finalize_settlement(ss["id"], create_settlement(ss["id"])["id"])
    # Per-member delta 600000 - 450000 = 150000 each; pool 300000; share 50% = 150000.
    assert ss_settle["gross_savings_share_cents"] == 150000
    assert ss_settle["quality_withhold_cents"] == 15000
    assert ss_settle["withhold_released_cents"] == 15000
    assert ss_settle["net_payment_cents"] == 150000
