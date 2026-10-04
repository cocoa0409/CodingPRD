"""Carbon claims, offset retirements and manufacturing targets (PRD §3.7):
the pinned offset-requirement evaluation order and coverage gate, the
reject/resubmit loop, cross-entity gates on report and target state, the
breach cascade, posture thresholds, claim-creation structural rules, and
offset intake rules (PRD §2.4 immutability, §3.7 state and vintage guards).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_offset_retirement,
    assign_report,
    clear_report,
    create_carbon_claim_payload,
    create_claim,
    create_collection,
    create_installed_site,
    create_offset_payload,
    create_released_batch,
    create_report,
    create_target,
    lay_zone,
    make_manager_headers,
    post_reading,
    publish_claim,
    publish_report,
    retire_offset,
    review_claim,
    set_clock,
    setup_claim_in_review,
    setup_collection_with_batch,
    setup_credited_takeback,
    setup_published_report,
    submit_claim,
    submit_report,
    validate_created,
    validate_error,
    validate_paginated,
    validate_success,
    DEFAULT_MANAGER_ID,
)

MANAGER = make_manager_headers(DEFAULT_MANAGER_ID)

SECOND_MIX_300 = [
    (600, 0.40, "POST_CONSUMER_TILE", "NETCO"),
    (600, 2.10, "VIRGIN", "POLYCO"),
]


def _published_gate_report():
    """Collection GAT (CRADLE_TO_GATE) with the canonical released batch
    (embodied 6.400) and a PUBLISHED CRADLE_TO_GATE report over
    [2026-09-01, 2026-10-01): operational 6.400, lifecycle 6.750."""
    set_clock()
    built = setup_collection_with_batch(
        collection_overrides={
            "name": "Gatehouse",
            "pattern_code": "GAT",
            "lifecycle_boundary": "CRADLE_TO_GATE",
            "claim_intent": "NONE",
        }
    )
    rep = setup_published_report(built["collection"]["id"], boundary="CRADLE_TO_GATE")
    return built["collection"], rep


def _published_grave_report():
    """Collection CIR (CRADLE_TO_GRAVE) with the canonical released batch and
    a PUBLISHED CRADLE_TO_GRAVE report: operational 6.400, lifecycle 6.750."""
    set_clock()
    built = setup_collection_with_batch()
    rep = setup_published_report(
        built["collection"]["id"], boundary="CRADLE_TO_GRAVE"
    )
    return built["collection"], rep


def _published_grave_report_with_credit():
    """Collection CIR with released DL-100 (6.400) + DL-101 (5.800, 300 m2)
    and one CREDITED take-back (160 kg -> 40.00 m2 recovered, credited
    2026-09-12): the PUBLISHED GRAVE report stores lifecycle 6.090."""
    set_clock()
    col = create_collection(claim_intent="NONE")
    b1 = create_released_batch(col["id"])
    create_released_batch(
        col["id"],
        mix=SECOND_MIX_300,
        dye_lot_code="DL-101",
        production_date="2026-09-10T00:00:00Z",
        produced_m2=300,
        mfg_intensity_kgco2e_per_m2=0.8,
        delta_e=0.9,
    )
    site = create_installed_site()
    lay_zone(site, b1["batch"]["id"], zone_code="Z-0", area_m2=10)
    setup_credited_takeback(site, col["id"])
    rep = setup_published_report(col["id"], boundary="CRADLE_TO_GRAVE")
    return col, rep


def test_offset_requirement_fixed_at_submit_and_partial_coverage_gates_publish(
    api, admin_headers
):
    """PRD §3.7: "the requirement: the larger of zero and the gross obligation,
    plus — only for a `CARBON_NEGATIVE` claim — a fixed buffer of 500.0
    kilograms of CO2e."
    PRD §3.7: "`NONE` when the retired total is zero, `FULL` when the retired
    total is at least the requirement, and `PARTIAL` when some offsets have
    been retired but the retired total still falls short of the requirement."
    PRD §3.7: "requires `offset_coverage` to be `FULL`, otherwise
    `ERR_OFFSET_COVERAGE_INSUFFICIENT` (HTTP 422)."

    Design: Difficulty/combinatorial_formula/claim_offset_requirement_evaluation_order
    """
    col, rep = _published_grave_report_with_credit()
    tgt = create_target()
    claim = create_claim(
        col["id"], rep["id"],
        claim_type="CARBON_NEGATIVE", claimed_volume_m2=1000,
        boundary="CRADLE_TO_GRAVE", manufacturing_target_id=tgt["id"],
    )
    claim = submit_claim(claim)
    # max(0, 6.090 x 1000) + 500 buffer = 6590.0, fixed at submit.
    assert claim["required_offset_kgco2e"] == pytest.approx(6590.0, abs=1e-9)
    assert claim["offset_coverage"] == "NONE"

    retire_offset(claim["id"], quantity_kgco2e=6000)
    claim = validate_success(api.get_carbon_claim(claim["id"], admin_headers))
    assert claim["retired_kgco2e"] == 6000
    assert claim["offset_coverage"] == "PARTIAL"  # 0 < 6000 < 6590
    assert claim["required_offset_kgco2e"] == pytest.approx(6590.0, abs=1e-9)

    claim = review_claim(claim, "APPROVE")
    resp = api.publish_carbon_claim(claim["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_OFFSET_COVERAGE_INSUFFICIENT)


def test_coverage_full_at_exact_requirement_publishes(api, admin_headers):
    """PRD §3.7: "`FULL` when the retired total is at least the requirement" —
    the boundary is inclusive: retired == required is FULL.
    PRD §3.7: "the publication gate depends on coverage, and retiring offsets
    changes coverage but never changes the requirement — only a submit or
    resubmit recomputes it."

    Design: Difficulty/combinatorial_formula/claim_offset_requirement_evaluation_order
    """
    col, rep = _published_grave_report_with_credit()
    tgt = create_target()
    claim = create_claim(
        col["id"], rep["id"],
        claim_type="CARBON_NEGATIVE", claimed_volume_m2=1000,
        boundary="CRADLE_TO_GRAVE", manufacturing_target_id=tgt["id"],
    )
    claim = submit_claim(claim)
    retire_offset(claim["id"], quantity_kgco2e=6000)
    claim = review_claim(claim, "APPROVE")
    retire_offset(
        claim["id"], quantity_kgco2e=590, registry="GOLD_STANDARD", vintage_year=2024
    )
    claim = validate_success(api.get_carbon_claim(claim["id"], admin_headers))
    assert claim["retired_kgco2e"] == 6590
    assert claim["required_offset_kgco2e"] == pytest.approx(6590.0, abs=1e-9)
    assert claim["offset_coverage"] == "FULL"
    claim = publish_claim(claim)
    assert claim["status"] == "PUBLISHED"
    assert claim["required_offset_kgco2e"] == pytest.approx(6590.0, abs=1e-9)


def test_claim_review_reject_lands_rejected_with_reviewer(api):
    """PRD §3.7: "A `ClaimsApprover` reviews an `IN_REVIEW` claim with a
    `decision` of `APPROVE` or `REJECT`, moving it to `APPROVED` or `REJECTED`
    respectively and recording `reviewed_by`"

    Design: Difficulty/non_linear_state_machine/claim_reject_resubmit_cycle
    """
    col, rep = _published_gate_report()
    claim = setup_claim_in_review(
        col["id"], rep["id"],
        claim_type="CARBON_NEUTRAL", claimed_volume_m2=50,
        boundary="CRADLE_TO_GATE",
    )
    assert claim["required_offset_kgco2e"] == pytest.approx(320.0, abs=1e-9)
    claim = review_claim(claim, "REJECT")
    assert claim["status"] == "REJECTED"
    assert claim["reviewed_by"] == "ap-erin"


def test_claim_resubmit_recomputes_and_clears_then_approve(api):
    """PRD §3.7: "resubmission recomputes the requirement and clears
    `reviewed_by` so the earlier review cannot carry over."
    PRD §3.7: "Submission moves a claim from `DRAFT` to `IN_REVIEW` — and,
    because the claim lifecycle is a loop, the same action resubmits a
    `REJECTED` claim back to `IN_REVIEW`."

    Design: Difficulty/non_linear_state_machine/claim_reject_resubmit_cycle
    """
    col, rep = _published_gate_report()
    claim = setup_claim_in_review(
        col["id"], rep["id"],
        claim_type="CARBON_NEUTRAL", claimed_volume_m2=50,
        boundary="CRADLE_TO_GATE",
    )
    claim = review_claim(claim, "REJECT")
    claim = submit_claim(claim)
    assert claim["status"] == "IN_REVIEW"
    assert claim["reviewed_by"] is None
    # Recomputed from unchanged inputs: 6.400 x 50 = 320.0.
    assert claim["required_offset_kgco2e"] == pytest.approx(320.0, abs=1e-9)
    claim = review_claim(claim, "APPROVE")
    assert claim["status"] == "APPROVED"
    assert claim["reviewed_by"] == "ap-erin"


def test_target_reading_entering_breached_recomputes_posture(api):
    """PRD §3.7: "The posture is `ON_TRACK` when the current intensity is at or
    below the target intensity — the boundary is inclusive — otherwise
    `AT_RISK` when the current intensity is at or below the baseline, and
    `BREACHED` when it exceeds even that."

    Design: Difficulty/transitive_cascade/target_reading_breach_reverts_in_review_claim
    """
    set_clock()
    tgt = create_target(program_name="PlantGrid-40")
    assert tgt["posture"] == "AT_RISK"
    tgt = post_reading(
        tgt["id"],
        period_end="2026-10-05T00:00:00Z",
        intensity_kgco2e_per_m2=8.5,
    )
    # 8.5 exceeds even the 8.0 baseline -> BREACHED (target was 6.0).
    assert tgt["posture"] == "BREACHED"
    assert tgt["current_intensity_kgco2e_per_m2"] == 8.5


def test_target_breach_reverts_in_review_claim_without_claim_call(
    api, admin_headers
):
    """PRD §2.9 (cascade B): "When a new manufacturing-target reading pushes
    the target's posture into `BREACHED`, every carbon claim that references
    that target through `manufacturing_target_id` and is currently `IN_REVIEW`
    reverts to `DRAFT`; its `reviewed_by` is cleared while its
    `required_offset_kgco2e` is retained for audit."

    Design: Difficulty/transitive_cascade/target_reading_breach_reverts_in_review_claim
    """
    col, rep = _published_grave_report()
    tgt = create_target(program_name="PlantGrid-40")
    claim = create_claim(
        col["id"], rep["id"],
        claim_type="CARBON_NEGATIVE", claimed_volume_m2=10,
        boundary="CRADLE_TO_GRAVE", manufacturing_target_id=tgt["id"],
    )
    claim = submit_claim(claim)
    assert claim["status"] == "IN_REVIEW"
    # 6.750 x 10 + 500 = 567.5, computed at submit.
    assert claim["required_offset_kgco2e"] == pytest.approx(567.5, abs=1e-9)

    post_reading(
        tgt["id"],
        period_end="2026-10-05T00:00:00Z",
        intensity_kgco2e_per_m2=8.5,
    )
    # No claim endpoint was called: the revert is the readings call's cascade.
    claim = validate_success(api.get_carbon_claim(claim["id"], admin_headers))
    assert claim["status"] == "DRAFT"
    assert claim["reviewed_by"] is None
    assert claim["required_offset_kgco2e"] == pytest.approx(567.5, abs=1e-9)


def _verified_gate_report():
    """Collection GAT with a VERIFIED (not yet published) CRADLE_TO_GATE
    report over the canonical batch."""
    set_clock()
    built = setup_collection_with_batch(
        collection_overrides={
            "name": "Gatehouse",
            "pattern_code": "GAT",
            "lifecycle_boundary": "CRADLE_TO_GATE",
            "claim_intent": "NONE",
        }
    )
    rep = create_report(built["collection"]["id"], boundary="CRADLE_TO_GATE")
    rep = submit_report(rep)
    rep = assign_report(rep)
    rep = clear_report(rep)
    return built["collection"], rep


def test_claim_submit_requires_report_published(api, admin_headers):
    """PRD §3.7: "Both paths require the referenced report to be `PUBLISHED`,
    otherwise `ERR_REPORT_NOT_PUBLISHED` (HTTP 422)"

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_report_published
    """
    col, rep = _verified_gate_report()  # VERIFIED, not PUBLISHED
    claim = create_claim(
        col["id"], rep["id"],
        claim_type="CARBON_NEUTRAL", claimed_volume_m2=50,
        boundary="CRADLE_TO_GATE",
    )
    resp = api.submit_carbon_claim(claim["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_PUBLISHED)
    data = validate_success(api.get_carbon_claim(claim["id"], admin_headers))
    assert data["status"] == "DRAFT"


def test_claim_submit_succeeds_once_report_published(api):
    """PRD §3.7: "Both paths require the referenced report to be `PUBLISHED`,
    otherwise `ERR_REPORT_NOT_PUBLISHED` (HTTP 422)" — the identical submit
    succeeds once the report's state flips to PUBLISHED.
    PRD §3.7: "the gross obligation: the selected report value multiplied by
    the claim's `claimed_volume_m2`."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_report_published
    """
    col, rep = _verified_gate_report()
    claim = create_claim(
        col["id"], rep["id"],
        claim_type="CARBON_NEUTRAL", claimed_volume_m2=50,
        boundary="CRADLE_TO_GATE",
    )
    validate_error(
        api.submit_carbon_claim(claim["id"], MANAGER),
        ApiErrorId.ERR_REPORT_NOT_PUBLISHED,
    )
    publish_report(rep)
    claim = submit_claim(claim)
    assert claim["status"] == "IN_REVIEW"
    # Neutral claim on a CRADLE_TO_GATE report: operational 6.400 x 50.
    assert claim["required_offset_kgco2e"] == pytest.approx(320.0, abs=1e-9)


def test_negative_claim_blocked_when_target_breached(api, admin_headers):
    """PRD §3.7: "a `CARBON_NEGATIVE` claim additionally requires its
    referenced manufacturing target's posture to be anything other than
    `BREACHED`, otherwise `ERR_TARGET_BREACHED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/negative_claim_blocked_when_target_breached
    """
    col, rep = _published_grave_report()
    tgt = create_target(program_name="PlantGrid-40")
    post_reading(
        tgt["id"],
        period_end="2026-10-05T00:00:00Z",
        intensity_kgco2e_per_m2=8.5,
    )
    tgt = validate_success(api.get_manufacturing_target(tgt["id"], admin_headers))
    assert tgt["posture"] == "BREACHED"
    claim = create_claim(
        col["id"], rep["id"],
        claim_type="CARBON_NEGATIVE", claimed_volume_m2=10,
        boundary="CRADLE_TO_GRAVE", manufacturing_target_id=tgt["id"],
    )
    resp = api.submit_carbon_claim(claim["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_TARGET_BREACHED)
    data = validate_success(api.get_carbon_claim(claim["id"], admin_headers))
    assert data["status"] == "DRAFT"


def test_neutral_claim_unaffected_by_target_breach_gate(api):
    """PRD §3.7: "a `CARBON_NEGATIVE` claim additionally requires its
    referenced manufacturing target's posture to be anything other than
    `BREACHED`, otherwise `ERR_TARGET_BREACHED` (HTTP 422)" — the gate binds
    only negative claims with a referenced target.

    Design: Difficulty/cross_entity_state_dependency/negative_claim_blocked_when_target_breached
    """
    col, rep = _published_grave_report()
    tgt = create_target(program_name="PlantGrid-40")
    post_reading(
        tgt["id"],
        period_end="2026-10-05T00:00:00Z",
        intensity_kgco2e_per_m2=8.5,
    )
    claim = create_claim(
        col["id"], rep["id"],
        claim_type="CARBON_NEUTRAL", claimed_volume_m2=10,
        boundary="CRADLE_TO_GRAVE",
    )
    claim = submit_claim(claim)
    assert claim["status"] == "IN_REVIEW"


def test_offset_retirement_is_immutable_record_without_version(api, admin_headers):
    """PRD §2.4: "An offset retirement is an immutable event record: it carries
    `id` and `created_at` only, and both `updated_at` and `version` are absent
    from it."
    PRD §3.7: "Retirement is immediate at creation: the **OffsetRetirement**
    record is created with its `claim_id` taken from the path and its
    `retired_at` stamped from the logical clock, the claim's `retired_kgco2e`
    increases by the retired quantity, and the claim's `offset_coverage` is
    recomputed against the standing requirement."

    Design: Corner/entities/offset_retirement_is_immutable_record_without_version
    """
    col, rep = _published_gate_report()
    claim = setup_claim_in_review(
        col["id"], rep["id"],
        claim_type="CARBON_NEUTRAL", claimed_volume_m2=50,
        boundary="CRADLE_TO_GATE",
    )  # required 320.0
    resp = api.create_offset_retirement(
        claim["id"],
        create_offset_payload(registry="ACR", vintage_year=2021, quantity_kgco2e=10),
        MANAGER,
    )
    off = validate_created(resp)
    assert_offset_retirement(off)
    assert off["claim_id"] == claim["id"]
    # Stamped from the logical clock pinned at 2026-09-01T00:00:00Z (PRD §2.5).
    assert off["retired_at"].startswith("2026-09-01T00:00:00")
    claim = validate_success(api.get_carbon_claim(claim["id"], admin_headers))
    assert claim["retired_kgco2e"] == 10
    assert claim["offset_coverage"] == "PARTIAL"  # 0 < 10 < 320.0


def test_offsets_rejected_while_claim_is_draft(api, admin_headers):
    """PRD §3.7: "The claim must be `IN_REVIEW` or `APPROVED`; retiring against
    a claim in any other state is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/offsets_rejected_while_claim_is_draft
    """
    set_clock()
    col = create_collection(
        name="Gatehouse", pattern_code="GAT",
        lifecycle_boundary="CRADLE_TO_GATE", claim_intent="NONE",
    )
    rep = create_report(col["id"])  # DRAFT — claim creation needs no more
    claim = create_claim(
        col["id"], rep["id"],
        claim_type="CARBON_NEUTRAL", claimed_volume_m2=50,
        boundary="CRADLE_TO_GATE",
    )
    resp = api.create_offset_retirement(
        claim["id"],
        create_offset_payload(vintage_year=2022, quantity_kgco2e=100),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    claim = validate_success(api.get_carbon_claim(claim["id"], admin_headers))
    assert claim["retired_kgco2e"] == 0
    assert claim["offset_coverage"] == "NONE"


def test_target_posture_threshold_boundaries(api):
    """PRD §3.7: "The target intensity is the baseline multiplied by one minus
    the reduction fraction. The current intensity is the baseline before any
    reading exists; afterwards it is the intensity of the reading with the
    greatest `period_end`"
    PRD §3.7: "its `posture` starts `AT_RISK`"
    PRD §3.7: "The posture is `ON_TRACK` when the current intensity is at or
    below the target intensity — the boundary is inclusive — otherwise
    `AT_RISK` when the current intensity is at or below the baseline, and
    `BREACHED` when it exceeds even that."

    Design: Corner/calculations/target_posture_threshold_boundaries
    """
    set_clock()
    tgt = create_target(program_name="PG")  # baseline 8.0, reduction 0.25
    # Initial current == baseline 8.0, above the 6.0 target.
    assert tgt["posture"] == "AT_RISK"
    assert tgt["current_intensity_kgco2e_per_m2"] == 8.0
    tgt = post_reading(
        tgt["id"], period_end="2026-10-01T00:00:00Z", intensity_kgco2e_per_m2=6.0
    )
    assert tgt["posture"] == "ON_TRACK"  # 6.0 <= 6.0, inclusive boundary
    tgt = post_reading(
        tgt["id"], period_end="2026-10-02T00:00:00Z", intensity_kgco2e_per_m2=6.001
    )
    assert tgt["posture"] == "AT_RISK"  # 6.001 > 6.0 but <= 8.0
    tgt = post_reading(
        tgt["id"], period_end="2026-10-03T00:00:00Z", intensity_kgco2e_per_m2=8.0
    )
    assert tgt["posture"] == "AT_RISK"  # 8.0 <= 8.0 baseline, inclusive
    tgt = post_reading(
        tgt["id"], period_end="2026-10-04T00:00:00Z", intensity_kgco2e_per_m2=8.0001
    )
    assert tgt["posture"] == "BREACHED"  # 8.0001 > 8.0


def test_claim_boundary_mismatch_at_create_returns_422(api, admin_headers):
    """PRD §3.7: "The claim's `boundary` must equal the referenced report's
    `boundary`, otherwise `ERR_BOUNDARY_MISMATCH` (HTTP 422)."
    PRD §3.7: "Claims can be listed with optional `collection_id`,
    `report_id`, `manufacturing_target_id`, and `status` filters."

    Design: Corner/validations/claim_boundary_mismatch_at_create_returns_422
    """
    set_clock()
    col = create_collection(
        name="Gatehouse", pattern_code="GAT",
        lifecycle_boundary="CRADLE_TO_GATE", claim_intent="NONE",
    )
    rep = create_report(col["id"])  # CRADLE_TO_GATE, DRAFT
    payload = create_carbon_claim_payload(
        col["id"], rep["id"],
        claim_type="CARBON_NEUTRAL", claimed_volume_m2=10,
        boundary="CRADLE_TO_GRAVE",
    )
    resp = api.create_carbon_claim(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_BOUNDARY_MISMATCH)
    rows, meta = validate_paginated(
        api.list_carbon_claims(admin_headers, params={"collection_id": col["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_negative_claim_boundary_and_target_rules(api):
    """PRD §3.7: "A `CARBON_NEGATIVE` claim must declare the `CRADLE_TO_GRAVE`
    boundary — otherwise `ERR_NEGATIVE_REQUIRES_CRADLE_TO_GRAVE` (HTTP 422) —
    and must name a `manufacturing_target_id`, otherwise
    `ERR_TARGET_REQUIRED_FOR_NEGATIVE` (HTTP 422); neutral claims carry the
    field optionally."

    Design: Corner/validations/negative_claim_boundary_and_target_rules
    """
    set_clock()
    col_gate = create_collection(
        name="Gatehouse", pattern_code="GAT",
        lifecycle_boundary="CRADLE_TO_GATE", claim_intent="NONE",
    )
    rep_gate = create_report(col_gate["id"])  # CRADLE_TO_GATE
    col_grave = create_collection(
        name="Gravia", pattern_code="GRV", lifecycle_boundary="CRADLE_TO_GRAVE"
    )
    rep_grave = create_report(col_grave["id"], boundary="CRADLE_TO_GRAVE")

    # Boundary matches the report (GATE) but negative claims demand GRAVE.
    resp = api.create_carbon_claim(
        create_carbon_claim_payload(
            col_gate["id"], rep_gate["id"],
            claim_type="CARBON_NEGATIVE", claimed_volume_m2=10,
            boundary="CRADLE_TO_GATE",
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_NEGATIVE_REQUIRES_CRADLE_TO_GRAVE)

    # Boundary legal; the manufacturing-target tie is missing.
    resp = api.create_carbon_claim(
        create_carbon_claim_payload(
            col_grave["id"], rep_grave["id"],
            claim_type="CARBON_NEGATIVE", claimed_volume_m2=10,
            boundary="CRADLE_TO_GRAVE",
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_TARGET_REQUIRED_FOR_NEGATIVE)
