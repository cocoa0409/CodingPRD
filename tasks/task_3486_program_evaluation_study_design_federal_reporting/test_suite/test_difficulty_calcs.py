"""Difficulty queue — calculation variant and rounding-order instances."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_record,
    create_design_plan,
    get_participant,
    get_study,
    setup_burden_rounding_scenario,
    setup_contract_with_study,
    setup_pipeline_projection_scenario,
    validate_paginated,
    validate_success,
)

PI = TEST_USERS["principal_investigator_headers"]
SD = TEST_USERS["study_director_headers"]


def test_design_plan_power_rct_vs_qed_variants(api):
    """PRD §3.2: "For illustration, with `mde` 0.5, `cluster_size` 10, `icc`
    0.05, and `attrition_rate` 0.15, the design effect is 1.45 and the raw
    requirement is 90.944; an `RCT` plan then requires 107 per arm for a
    `required_total_n` of 214, while a quasi-experimental plan requires 155 per
    arm for a total of 310."
    PRD §3.2: "Creation automatically supersedes the study's current plan when
    that plan sits in `DRAFT` or `RETURNED_FOR_REVISION`: the older plan moves
    to `SUPERSEDED`, a terminal state, and is never again the study's current
    plan."

    Design: Difficulty/dual_variant_calc/design_plan_power_rct_vs_qed_variants
    """
    ctx = setup_contract_with_study()
    study_id = ctx["study"]["id"]

    plan_rct = create_design_plan(study_id)
    assert plan_rct["n_per_arm"] == 107, f"RCT n_per_arm: {plan_rct['n_per_arm']}"
    assert plan_rct["required_total_n"] == 214
    assert plan_rct["status"] == "DRAFT"

    study = get_study(study_id)
    plan_qed = create_design_plan(
        study_id, expected_study_version=study["version"], design_type="QED_DID"
    )
    assert plan_qed["n_per_arm"] == 155, f"QED n_per_arm: {plan_qed['n_per_arm']}"
    assert plan_qed["required_total_n"] == 310

    plans, _meta = validate_paginated(api.list_design_plans(study_id, PI))
    rct_after = next(p for p in plans if p["id"] == plan_rct["id"])
    assert rct_after["status"] == "SUPERSEDED", (
        f"superseded by the QED revision, got {rct_after['status']}"
    )


def test_feasibility_committed_vs_pipeline_variants(api):
    """PRD §3.4: "For illustration, a study with one `RECRUITED` site of
    capacity 60 and two `CONTACTED` sites of capacity 300 each reports a
    committed projection of 60 and a pipeline projection of 270 — 60 plus 105
    plus 105."
    PRD §3.4: "The study's `committed_projected_n`, `pipeline_projected_n`,
    `enrolled_total`, and `sample_adequacy` are then recomputed — and because a
    withdrawn site contributes nothing, adequacy can flip from `ADEQUATE` back
    to `UNDERPOWERED`."

    Design: Difficulty/dual_variant_calc/feasibility_committed_vs_pipeline_variants
    """
    ctx = setup_pipeline_projection_scenario()
    study = ctx["study"]
    assert study["committed_projected_n"] == 60
    assert study["pipeline_projected_n"] == 270, (
        "60 + floor(300*0.35) + floor(300*0.35) = 270"
    )
    assert study["sample_adequacy"] == "ADEQUATE"  # 270 >= required_total_n 214

    site_a = ctx["sites"][0]
    withdrawn = validate_success(
        api.withdraw_site(site_a["id"], SD, {"reason": "Site lost funding"}), 200
    )
    assert withdrawn["status"] == "WITHDRAWN"

    study = get_study(study["id"])
    assert study["committed_projected_n"] == 0
    assert study["pipeline_projected_n"] == 210  # two CONTACTED sites remain
    assert study["sample_adequacy"] == "UNDERPOWERED"  # 210 < 214


def test_sample_size_cluster_icc_interaction(api):
    """PRD §3.2: "First, the design effect is one plus the product of the
    intra-cluster correlation and one less than the average cluster size.
    Second, the raw per-arm requirement is twice the square of the sum of the
    two pinned critical values — the two-sided significance critical value
    `Z_ALPHA_CRIT` of 1.96 and the power critical value `Z_POWER_CRIT` of 0.84 —
    multiplied by the design effect and divided by the square of the minimum
    detectable effect. Third, for an `RCT` design the per-arm sample size
    `n_per_arm` is the raw requirement divided by one minus the attrition rate,
    rounded up to the next whole participant."
    PRD §3.2: "Finally, `required_total_n` is exactly twice `n_per_arm`."

    With icc 0.00 the design effect is 1.0 (raw 62.72 / 0.85 -> ceil 74); with
    icc 0.05 it is 1.45 (raw 90.944 / 0.85 -> ceil 107).

    Design: Difficulty/combinatorial_formula/sample_size_cluster_icc_interaction
    """
    ctx = setup_contract_with_study()
    study_id = ctx["study"]["id"]

    plan_icc0 = create_design_plan(study_id, icc=0.0)
    assert plan_icc0["n_per_arm"] == 74, f"icc=0 n_per_arm: {plan_icc0['n_per_arm']}"
    assert plan_icc0["required_total_n"] == 148

    study = get_study(study_id)
    plan_icc5 = create_design_plan(
        study_id, expected_study_version=study["version"], icc=0.05
    )
    assert plan_icc5["n_per_arm"] == 107, f"icc=0.05 n_per_arm: {plan_icc5['n_per_arm']}"
    assert plan_icc5["required_total_n"] == 214


def test_burden_rounding_per_record_then_sum(api):
    """PRD §3.6: "The rounding order is pinned — each record is rounded first,
    then the integers are summed — and the alternative of summing raw products
    and rounding once is explicitly rejected."
    PRD §3.6: "For illustration, two `SITE_VISIT` records of 45 minutes and one
    `SURVEY` record of 45 minutes bill as 56 plus 56 plus 45, totalling 157; the
    rejected sum-first order would produce 158."

    Design: Difficulty/combinatorial_formula/burden_rounding_per_record_then_sum
    """
    ctx = setup_burden_rounding_scenario()
    p1 = ctx["participant"]

    rec1 = add_record(ctx["wave_visit"]["id"], p1["id"], instrument_minutes=45,
                      payload_ref="visit-1")
    rec2 = add_record(ctx["wave_visit"]["id"], p1["id"], instrument_minutes=45,
                      payload_ref="visit-2")
    rec3 = add_record(ctx["wave_survey"]["id"], p1["id"], instrument_minutes=45,
                      payload_ref="survey-1")

    assert rec1["billed_minutes"] == 56, "round_half_up(45 * 1.25) = 56"
    assert rec2["billed_minutes"] == 56
    assert rec3["billed_minutes"] == 45, "45 * 1.0 = 45"

    p1 = get_participant(p1["id"])
    assert p1["burden_total_minutes"] == 157, (
        f"per-record rounding pins 157 (sum-first would give 158), "
        f"got {p1['burden_total_minutes']}"
    )
