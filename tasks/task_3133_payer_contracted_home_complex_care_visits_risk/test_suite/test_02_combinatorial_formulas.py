"""Difficulty-queue tests: combinatorial formulas (composite score, shared-savings order)."""
import pytest

from test_helpers import (
    ADMIN,
    ANALYST,
    CONTRACT_ADMIN,
    COORDINATOR,
    SPECIALIST,
    advance_clock,
    arrive_episode,
    complete_visit,
    create_clinician,
    create_dispatched_episode,
    create_medical_cost_payload,
    create_member_with_enrollment,
    create_pcp,
    create_program,
    create_scheduled_visit,
    create_settlement,
    create_shared_savings_contract,
    dispatch_episode,
    finalize_settlement,
    get_measurement_for_member,
    get_success_data,
    resolve_episode,
    set_clock,
    setup_active_enrollment,
    drive_enrollment_to_consented,
    activate_care_team_for,
    activate_enrollment,
    upsert_and_submit_assessment,
    drive_visit_to_in_progress,
    make_clinician_headers,
    validate_success,
    api_client,
)


def _enroll_active(program, contract, pcp, np, member_overrides):
    member, enrollment = create_member_with_enrollment(program, contract, pcp, member_overrides)
    drive_enrollment_to_consented(enrollment["id"])
    activate_care_team_for(enrollment["id"], np["id"])
    activate_enrollment(enrollment["id"])
    return member, enrollment


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/composite_score_weighted_four_component_two_step_rounding
# ---------------------------------------------------------------------------

def _setup_composite_counters():
    """Drive one member's measurement row to:
    triggered=2, sla_met=2, avoided_ed=1, completed=3, no_show=1, cancelled=0."""
    program = create_program()
    contract = create_shared_savings_contract(program["id"])  # any model works here
    pcp = create_pcp(program["id"])
    np = create_clinician(
        program["id"], max_daily_visits=10, urgent_response_qualified=True
    )
    member, enrollment = _enroll_active(program, contract, pcp, np, {
        "member_external_id": "M-001",
    })
    enr_id = enrollment["id"]

    # Episode 1: resolved AVOIDED_ED within SLA.
    ep1 = create_dispatched_episode(enr_id, trigger_source="MEMBER_CALL")
    arrive_episode(ep1)
    resolve_episode(ep1, "AVOIDED_ED")

    # Episode 2: resolved REFERRED_TO_ED within SLA.
    ep2 = create_dispatched_episode(enr_id, trigger_source="PCP_ALERT")
    arrive_episode(ep2)
    resolve_episode(ep2, "REFERRED_TO_ED")

    # Episode 2 resolves REFERRED_TO_ED, which cascades a SCHEDULED
    # POST_ED_FOLLOWUP visit on the primary NP spanning [now, now+72h)
    # (PRD §3.6). With the clock at 2026-09-01T00:00:00Z, that window runs
    # through 2026-09-04T00:00:00Z, so subsequent visits for the same
    # clinician must start at or after 2026-09-04 to clear the PRD §2.10
    # half-open overlap check.
    # Three completed visits.
    for day, vtype in (("2026-09-04", "INITIAL_ASSESSMENT"),
                       ("2026-09-05", "ROUTINE_FOLLOWUP"),
                       ("2026-09-06", "ROUTINE_FOLLOWUP")):
        visit = create_scheduled_visit(
            enr_id, visit_type=vtype,
            start=f"{day}T09:00:00Z", end=f"{day}T10:00:00Z",
        )
        complete_visit(visit)

    # One no-show visit: advance the logical clock to the end of its window.
    v4 = create_scheduled_visit(
        enr_id, visit_type="ROUTINE_FOLLOWUP",
        start="2026-09-07T09:00:00Z", end="2026-09-07T10:00:00Z",
    )
    set_clock("2026-09-07T10:00:00Z")
    get_success_data(api_client.mark_no_show(
        v4["id"], make_clinician_headers(v4["clinician_id"])
    ))
    return member, enrollment


def test_composite_score_counters_after_mixed_activity(api):
    """PRD section 3.7: "The counters — `urgent_episodes_triggered`, `urgent_episodes_sla_met`, `urgent_episodes_avoided_ed`, `visits_completed`, `visits_no_show`, `visits_cancelled` — accumulate per the workflows above."

    Design: Difficulty/combinatorial_formula/composite_score_weighted_four_component_two_step_rounding
    """
    member, _enrollment = _setup_composite_counters()
    row = get_measurement_for_member(member["id"])
    assert row["urgent_episodes_triggered"] == 2
    assert row["urgent_episodes_sla_met"] == 2
    assert row["urgent_episodes_avoided_ed"] == 1
    assert row["visits_completed"] == 3
    assert row["visits_no_show"] == 1
    assert row["visits_cancelled"] == 0
    assert row["pcp_coordination_rate"] == pytest.approx(1.0, abs=1e-9)


def test_composite_score_weighted_sum_two_stage_rounding(api):
    """PRD section 3.7: "Each component is first rounded to 4 decimal places with round-half-up. The weighted sum then multiplies the SLA component by 0.40, the ED-avoidance component by 0.30, the visit-completion component by 0.20, and the PCP-coordination component by 0.10, sums the four products, and rounds the result to 4 decimal places with round-half-up."

    Design: Difficulty/combinatorial_formula/composite_score_weighted_four_component_two_step_rounding
    """
    member, _enrollment = _setup_composite_counters()
    row = get_measurement_for_member(member["id"])
    # components: sla = 2/2 = 1.0, ed_avoid = 1/2 = 0.5, visit = 3/4 = 0.75, pcp = 1.0
    # composite = round4(0.40*1.0 + 0.30*0.5 + 0.20*0.75 + 0.10*1.0) = 0.80
    assert row["composite_score"] == pytest.approx(0.80, abs=1e-9)


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/shared_savings_per_member_delta_pool_then_split_then_withhold_pinned_order
# ---------------------------------------------------------------------------

def _setup_shared_savings_three_members():
    program = create_program()
    ss = create_shared_savings_contract(program["id"])
    pcp = create_pcp(program["id"])
    np = create_clinician(program["id"], max_daily_visits=10)
    members = []
    specs = [
        ({"member_external_id": "SS-A", "full_name": "SS A"}, 450000),
        ({"member_external_id": "SS-B", "full_name": "SS B",
          "chronic_condition_codes": ["COPD"], "prior_inpatient_admits_12mo": 0}, 650000),
        ({"member_external_id": "SS-C", "full_name": "SS C",
          "chronic_condition_codes": ["DIABETES"], "prior_ed_visits_12mo": 0}, 350000),
    ]
    for overrides, cost in specs:
        member, _enrollment = _enroll_active(program, ss, pcp, np, overrides)
        members.append(member)
        get_success_data(api_client.create_medical_cost(
            create_medical_cost_payload(ss["id"], member["id"], amount_cents=cost),
            CONTRACT_ADMIN,
        ))
    return ss, members


def test_shared_savings_pool_then_split_then_withhold_order(api):
    """PRD section 3.7: "For a `SHARED_SAVINGS` contract, the gross is computed in a pinned multi-step order — per-member delta first, then pooling, then split, then withhold, then release — so that no reader can accidentally compute the withhold before the pool."

    Design: Difficulty/combinatorial_formula/shared_savings_per_member_delta_pool_then_split_then_withhold_pinned_order
    """
    ss, _members = _setup_shared_savings_three_members()
    settle = finalize_settlement(ss["id"], create_settlement(ss["id"])["id"])
    # deltas: +150000, -50000, +250000 -> pool 350000; share 50% = 175000.
    assert settle["enrolled_member_count"] == 3
    assert settle["gross_savings_share_cents"] == 175000
    assert settle["quality_withhold_cents"] == 17500


def test_shared_savings_net_payment_with_full_release(api):
    """PRD section 3.7: "The `withhold_released_cents` is then the product of `quality_withhold_cents` and `release_fraction`, rounded half-up to integer cents."
    PRD section 3.7: "The `net_payment_cents` is the gross minus the withhold plus the released withhold — for a `CAPITATED` contract, `gross_capitation_cents` minus `quality_withhold_cents` plus `withhold_released_cents`; for a `SHARED_SAVINGS` contract, `gross_savings_share_cents` minus `quality_withhold_cents` plus `withhold_released_cents`."

    Design: Difficulty/combinatorial_formula/shared_savings_per_member_delta_pool_then_split_then_withhold_pinned_order
    """
    ss, _members = _setup_shared_savings_three_members()
    settle = finalize_settlement(ss["id"], create_settlement(ss["id"])["id"])
    # All three members sit at composite 1.0 (>= 0.80) -> release_fraction == 1.
    assert settle["withhold_released_cents"] == 17500
    assert settle["net_payment_cents"] == 175000
    assert settle["gross_capitation_cents"] is None
