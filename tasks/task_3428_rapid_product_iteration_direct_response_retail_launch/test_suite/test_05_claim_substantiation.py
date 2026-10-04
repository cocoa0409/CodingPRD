"""Comparative claim studies: sample-size floor, margin gate boundary,
variant-state gating, and the challenge/retest cycle (PRD §3.4).
"""
import pytest

from test_helpers import (
    LC_JANE,
    SCI_ANNA,
    SCI_BOB,
    ApiErrorId,
    api_client,
    challenge_claim_study,
    complete_claim_study,
    create_claim_study,
    create_claim_study_payload,
    create_partner,
    create_variant,
    get_variant,
    retest_claim_study,
    setup_engineering_locked_concept,
    setup_season_with_category,
    setup_substantiated_study,
    setup_tooled_variant,
    substantiate_claim_study,
    tool_variant,
    validate_created,
    validate_error,
    validate_ok,
)


def test_sample_size_floor_enforced_at_complete(api):
    """PRD §3.4: "`sample_size`, which must be at least 30 — the gate is
    inclusive — else `ERR_SAMPLE_SIZE_TOO_SMALL`."

    Design: Corner/calculations/sample_size_floor_enforced_at_complete
    """
    base = setup_season_with_category()
    bundle = setup_tooled_variant(base["category"]["id"])
    study = create_claim_study(bundle["variant"]["id"], conductor_headers=SCI_ANNA)
    resp = api_client.complete_claim_study(
        study["id"],
        {"our_metric": 120, "baseline_metric": 100, "sample_size": 29},
        SCI_ANNA,
    )
    validate_error(resp, ApiErrorId.ERR_SAMPLE_SIZE_TOO_SMALL)
    studies = validate_ok(
        api_client.list_variant_claim_studies(bundle["variant"]["id"], SCI_ANNA)
    )
    assert studies[0]["status"] == "RUNNING"
    data = complete_claim_study(study["id"], 120, 100, 30, conductor_headers=SCI_ANNA)
    assert data["status"] == "RESULTS_RECORDED"
    assert data["margin"] == pytest.approx(0.2, abs=1e-9)


def test_claim_margin_exactly_at_threshold_substantiates(api):
    """PRD §3.4: "The study's `margin` must be at least 0.15 — again inclusive,
    so a margin of exactly 0.1500 substantiates — else
    `ERR_MARGIN_BELOW_MINIMUM`".

    Design: Difficulty/boundary_precision_check/claim_margin_exactly_at_threshold_substantiates
    """
    base = setup_season_with_category()
    bundle = setup_tooled_variant(base["category"]["id"])
    study = create_claim_study(bundle["variant"]["id"], conductor_headers=SCI_ANNA)
    completed = complete_claim_study(
        study["id"], 115, 100, 40, conductor_headers=SCI_ANNA
    )
    assert completed["margin"] == pytest.approx(0.15, abs=1e-9)
    data = substantiate_claim_study(study["id"], substantiator_headers=SCI_BOB)
    assert data["status"] == "SUBSTANTIATED"
    assert data["substantiated_by_user_id"] == "sci-bob"
    assert get_variant(bundle["variant"]["id"])["claim_clearance"] == "SUBSTANTIATED"


def test_claim_margin_one_cent_below_threshold_rejected(api):
    """PRD §3.4: "The study's `margin` must be at least 0.15 — again inclusive,
    so a margin of exactly 0.1500 substantiates — else
    `ERR_MARGIN_BELOW_MINIMUM`, in which case the study remains
    `RESULTS_RECORDED` and may be substantiated later if its numbers change."

    Design: Difficulty/boundary_precision_check/claim_margin_exactly_at_threshold_substantiates
    """
    base = setup_season_with_category()
    bundle = setup_tooled_variant(base["category"]["id"])
    study = create_claim_study(bundle["variant"]["id"], conductor_headers=SCI_ANNA)
    completed = complete_claim_study(
        study["id"], 114, 100, 40, conductor_headers=SCI_ANNA
    )
    assert completed["margin"] == pytest.approx(0.14, abs=1e-9)
    resp = api_client.substantiate_claim_study(study["id"], SCI_BOB)
    validate_error(resp, ApiErrorId.ERR_MARGIN_BELOW_MINIMUM)
    studies = validate_ok(
        api_client.list_variant_claim_studies(bundle["variant"]["id"], SCI_ANNA)
    )
    assert studies[0]["status"] == "RESULTS_RECORDED"
    assert get_variant(bundle["variant"]["id"])["claim_clearance"] == "UNSUBSTANTIATED"


def test_claim_study_creation_rejected_while_variant_draft(api):
    """PRD §3.4: "A `ClaimsScientist` opens a ClaimStudy on a `TOOLED` variant
    by supplying the `variant_id` and the `claim_text` under test; creating a
    study for a variant in any other lifecycle state is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/claim_study_creation_gated_on_variant_tooled
    """
    base = setup_season_with_category()
    concept = setup_engineering_locked_concept(base["category"]["id"])
    variant = create_variant(concept["id"], "CV100-AMZ", "AMAZON")
    resp = api_client.create_claim_study(
        create_claim_study_payload(variant["id"], "50% more suction"), SCI_ANNA
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_claim_study_creation_succeeds_after_tooling(api):
    """PRD §3.4: "A `ClaimsScientist` opens a ClaimStudy on a `TOOLED` variant
    by supplying the `variant_id` and the `claim_text` under test; creating a
    study for a variant in any other lifecycle state is rejected with
    `ERR_INVALID_STATE`." PRD §3.3: "A successful tooling sets
    `factory_partner_id`, stamps `tooled_at` from the logical clock, and moves
    the variant `DRAFT` → `TOOLED`."

    Design: Difficulty/cross_entity_state_dependency/claim_study_creation_gated_on_variant_tooled
    """
    base = setup_season_with_category()
    concept = setup_engineering_locked_concept(base["category"]["id"])
    partner = create_partner()
    variant = create_variant(concept["id"], "CV100-AMZ", "AMAZON")
    resp = api_client.create_claim_study(
        create_claim_study_payload(variant["id"], "50% more suction"), SCI_ANNA
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    tool_variant(variant["id"], partner["id"])
    resp2 = api_client.create_claim_study(
        create_claim_study_payload(variant["id"], "50% more suction"), SCI_ANNA
    )
    data = validate_created(resp2)
    assert data["status"] == "RUNNING"
    assert data["conducted_by_user_id"] == "sci-anna"


def test_claim_study_challenge_then_retest_clears_results(api):
    """PRD §3.4: "A `LegalCounsel` may challenge a `SUBSTANTIATED` study,
    supplying a `reason`; the server records it in `challenge_reason`, moves
    the study to `CHALLENGED`, and flips the variant's `claim_clearance` to
    `CHALLENGED`. A challenged claim can be retaken: a `ClaimsScientist`
    retests the study, moving it `CHALLENGED` → `RUNNING`, resetting
    `our_metric`, `baseline_metric`, `sample_size`, `margin`, and
    `challenge_reason` to null, and returning the variant's `claim_clearance`
    to `UNSUBSTANTIATED`."

    Design: Difficulty/non_linear_state_machine/claim_study_challenge_retest_cycle
    """
    base = setup_season_with_category()
    bundle = setup_tooled_variant(base["category"]["id"])
    study = setup_substantiated_study(bundle["variant"]["id"])
    challenged = challenge_claim_study(study["id"], "Competitor dispute letter")
    assert challenged["status"] == "CHALLENGED"
    assert challenged["challenge_reason"] == "Competitor dispute letter"
    assert get_variant(bundle["variant"]["id"])["claim_clearance"] == "CHALLENGED"
    retaken = retest_claim_study(study["id"], scientist_headers=SCI_ANNA)
    assert retaken["status"] == "RUNNING"
    assert retaken["margin"] is None
    assert retaken["our_metric"] is None
    assert retaken["baseline_metric"] is None
    assert retaken["sample_size"] is None
    assert retaken["challenge_reason"] is None
    assert get_variant(bundle["variant"]["id"])["claim_clearance"] == "UNSUBSTANTIATED"


def test_claim_study_retest_resubstantiation_closes_cycle(api):
    """PRD §3.4: "When the retaken study substantiates again, clearance flips
    back to `SUBSTANTIATED`." PRD §3.4: "At completion the server computes the
    study's `margin`: the difference between `our_metric` and
    `baseline_metric`, divided by `baseline_metric`, rounded half-up to 4
    decimal places."

    Design: Difficulty/non_linear_state_machine/claim_study_challenge_retest_cycle
    """
    base = setup_season_with_category()
    bundle = setup_tooled_variant(base["category"]["id"])
    study = setup_substantiated_study(bundle["variant"]["id"])
    challenge_claim_study(study["id"], "Competitor dispute letter")
    retest_claim_study(study["id"], scientist_headers=SCI_ANNA)
    completed = complete_claim_study(
        study["id"], 120, 100, 35, conductor_headers=SCI_ANNA
    )
    assert completed["margin"] == pytest.approx(0.2, abs=1e-9)
    final = substantiate_claim_study(study["id"], substantiator_headers=SCI_BOB)
    assert final["status"] == "SUBSTANTIATED"
    assert final["substantiated_by_user_id"] == "sci-bob"
    assert get_variant(bundle["variant"]["id"])["claim_clearance"] == "SUBSTANTIATED"
