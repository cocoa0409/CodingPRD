"""Undo operations that must restore a conserved quantity exactly.

Voiding a manifest conserves kilograms of spent media; withdrawing an award
conserves an integer cents ledger and unwinds a derived money cascade with it.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_decimal,
    assert_equals,
    assert_is_null,
    assert_money_cents,
    assert_rate_ladder,
    assert_status,
)
from test_helpers.fixtures import (
    apply_for_funding,
    award_funding,
    classify_manifest,
    completed_gac_pilot,
    open_evaluation,
    piloted_evaluation,
    project_of_evaluation,
    raise_manifest,
    read_application,
    read_evaluation,
    read_manifest,
    read_pilot,
    read_project,
    register_entry_point,
    select_technology,
)
from test_helpers.test_users import FINANCE_OFFICER_HEADERS, TREATMENT_ENGINEER_HEADERS

_WITHDRAW_REASON = "The state reallocated the SRF set-aside to another system."


def _classified_manifest_splitting_the_media(api):
    """800 kg of spent carbon split 500 unmanifested / 300 on one CLASSIFIED manifest."""
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"])
    pilot = completed_gac_pilot(api, evaluation["id"])
    manifest = raise_manifest(api, pilot["id"], media_type="GAC_CARBON", mass_kg=300.00)
    classified = classify_manifest(api, manifest["id"], 49.99)
    return evaluation, pilot, classified


def test_voiding_a_classified_manifest_returns_its_mass_to_the_pilot(api):
    """The mass identity holds as 800 = 500 + 300 and again as 800 = 800 + 0.

    Before the void the pilot's spent media is split between 500.00 kg still
    unmanifested and the 300.00 kg riding on the manifest; voiding the manifest
    for a mass correction hands that 300.00 kg straight back, so the ledger reads
    800.00 kg unmanifested against 800.00 kg spent with no drift.

    PRD: "The manifest moves `DRAFT → VOIDED` or `CLASSIFIED → VOIDED`, and the
    pilot's `unmanifested_media_kg` rises by exactly the voided mass, restoring
    the mass invariant to the penny of a kilogram."

    Design: Difficulty/compensating_invariant/residuals_mass_identity_is_restored_exactly_when_a_manifest_is_voided
    """
    _, pilot, classified = _classified_manifest_splitting_the_media(api)
    before = read_pilot(api, pilot["id"])
    assert_decimal(before["spent_media_kg"], 800.00, label="spent_media_kg")
    assert_decimal(before["unmanifested_media_kg"], 500.00, label="unmanifested_media_kg")

    voided = validate_success(
        api.void_residuals_manifest(
            classified["id"],
            f.void_manifest_payload(void_reason_code="MASS_CORRECTION"),
            TREATMENT_ENGINEER_HEADERS,
        )
    )

    assert_status(voided, "VOIDED")
    assert_equals(voided, "void_reason_code", "MASS_CORRECTION")
    assert_decimal(voided["mass_kg"], 300.00, label="mass_kg")

    after = read_pilot(api, pilot["id"])
    assert_decimal(after["spent_media_kg"], 800.00, label="spent_media_kg")
    assert_decimal(after["unmanifested_media_kg"], 800.00, label="unmanifested_media_kg")


def test_the_void_keeps_the_leaching_evidence_and_never_charges_the_budget(api):
    """The undo is partial by design: mass returns, evidence stays, money never moved.

    A leachate reading of 49.99 is a hundredth below the special-waste threshold,
    so the manifest was classified NON_HAZARDOUS_SOLID; after the void that
    classification and its reading are still on the row, no disposal route or cost
    was ever recorded, and the evaluation's residuals spending is untouched at zero
    against its 250000-cent budget.

    PRD: "Voiding from `CLASSIFIED` retains the recorded `waste_classification`
    and `leachate_pfas_ng_per_l` on the voided row rather than clearing them,
    because the leaching evidence remains valid even though the shipment was
    abandoned."

    Design: Difficulty/compensating_invariant/residuals_mass_identity_is_restored_exactly_when_a_manifest_is_voided
    """
    evaluation, _, classified = _classified_manifest_splitting_the_media(api)
    assert_equals(classified, "waste_classification", "NON_HAZARDOUS_SOLID")

    validate_success(
        api.void_residuals_manifest(
            classified["id"],
            f.void_manifest_payload(void_reason_code="MASS_CORRECTION"),
            TREATMENT_ENGINEER_HEADERS,
        )
    )

    stored = read_manifest(api, classified["id"])
    assert_status(stored, "VOIDED")
    assert_equals(stored, "waste_classification", "NON_HAZARDOUS_SOLID")
    assert_decimal(stored["leachate_pfas_ng_per_l"], 49.99, label="leachate_pfas_ng_per_l")
    assert_is_null(stored, "disposal_method", "disposal_cost_cents")

    parent = read_evaluation(api, evaluation["id"])
    assert_money_cents(parent["residuals_spent_cents"], 0, "residuals_spent_cents")
    assert_money_cents(parent["residuals_budget_cents"], 250000, "residuals_budget_cents")


def _project_with_a_forgiven_award(api):
    """A 680000000-cent GAC project carrying a fully awarded disadvantaged SRF loan."""
    entry_point = register_entry_point(api)
    piloted = piloted_evaluation(api, entry_point["id"])
    select_technology(api, piloted["evaluation_id"])
    project = project_of_evaluation(api, piloted["evaluation_id"])
    application = apply_for_funding(
        api,
        project["id"],
        program="SRF_LOAN",
        amount_requested_cents=400000000,
        disadvantaged_community=True,
    )
    award_funding(api, application["id"], 400000000)
    return project, application


def test_a_forgiven_award_splits_the_cents_ledger_three_ways(api):
    """The identity 680000000 = 400000000 + 0 + 280000000 holds while the award stands.

    Forty-nine percent of the 400000000-cent award is forgiven outright, so
    196000000 becomes a grant equivalent and only 204000000 must be repaid; the
    borrowing total therefore falls to 484000000 and the whole ladder drops with
    it, to a 6.00 percent rate impact and a 285-cent monthly bill.

    PRD: "An award moves the application `SUBMITTED → AWARDED`, stores
    `awarded_cents`, computes `forgiven_cents` as `awarded_cents` multiplied by
    `forgiveness_pct` divided by 100 and rounded half-up to whole cents, records
    `decided_by_user_id` and `decision_note`, re-derives the project's
    `funding_status`, and recomputes the whole ladder."

    Design: Difficulty/compensating_invariant/capital_funding_ledger_identity_is_restored_when_an_award_is_withdrawn
    """
    project, application = _project_with_a_forgiven_award(api)

    awarded_application = read_application(api, application["id"])
    assert_status(awarded_application, "AWARDED")
    assert_decimal(awarded_application["forgiveness_pct"], 49.00, label="forgiveness_pct")
    assert_money_cents(awarded_application["forgiven_cents"], 196000000, "forgiven_cents")

    awarded = read_project(api, project["id"])
    assert_equals(awarded, "funding_status", "AWARDED")
    assert_money_cents(awarded["capital_cost_cents"], 680000000, "capital_cost_cents")
    assert_money_cents(awarded["funding_awarded_cents"], 400000000, "funding_awarded_cents")
    assert_money_cents(awarded["grant_equivalent_cents"], 196000000, "grant_equivalent_cents")
    assert_money_cents(awarded["loan_principal_cents"], 204000000, "loan_principal_cents")
    assert_money_cents(awarded["recovered_cents"], 0, "recovered_cents")
    assert_rate_ladder(
        awarded,
        local_share_cents=280000000,
        borrowed_cents=484000000,
        annual_debt_service_cents=29599852,
        base_annual_requirement_cents=60599852,
        provisional_rate_impact_pct=5.91,
        surcharge_bp=150,
        final_annual_requirement_cents=61508850,
        rate_impact_pct=6.00,
        uniform_monthly_increase_cents=285,
    )


def test_withdrawing_the_award_restores_every_rung_of_the_ladder_exactly(api):
    """The reversal is complete, not approximate, and it unwinds the forgiveness too.

    Withdrawing the awarded application clears its money fields back to null and
    leaves the project with no live award, so the local share absorbs the whole
    680000000 cents again and every derived figure returns to its exact pre-award
    value, right down to the 341-cent monthly bill.

    PRD: "Withdrawing an awarded application clears both `awarded_cents` and
    `forgiven_cents` back to null, and the project's ledger and full ladder are
    recomputed, returning every figure to exactly what it was before the award —
    the reversal is complete, not approximate."

    Design: Difficulty/compensating_invariant/capital_funding_ledger_identity_is_restored_when_an_award_is_withdrawn
    """
    project, application = _project_with_a_forgiven_award(api)

    withdrawn = validate_success(
        api.withdraw_funding_application(
            application["id"],
            f.withdraw_payload(withdraw_reason=_WITHDRAW_REASON),
            FINANCE_OFFICER_HEADERS,
        )
    )

    assert_status(withdrawn, "WITHDRAWN")
    assert_is_null(withdrawn, "awarded_cents", "forgiven_cents")
    assert_equals(withdrawn, "withdraw_reason", _WITHDRAW_REASON)
    assert_money_cents(
        withdrawn["amount_requested_cents"], 400000000, "amount_requested_cents"
    )
    assert_decimal(withdrawn["forgiveness_pct"], 49.00, label="forgiveness_pct")

    restored = read_project(api, project["id"])
    assert_equals(restored, "funding_status", "DENIED")
    assert_equals(restored, "construction_status", "PLANNED")
    assert_money_cents(restored["funding_awarded_cents"], 0, "funding_awarded_cents")
    assert_money_cents(restored["grant_equivalent_cents"], 0, "grant_equivalent_cents")
    assert_money_cents(restored["loan_principal_cents"], 0, "loan_principal_cents")
    assert_money_cents(restored["recovered_cents"], 0, "recovered_cents")
    assert_rate_ladder(
        restored,
        local_share_cents=680000000,
        borrowed_cents=680000000,
        annual_debt_service_cents=41586568,
        base_annual_requirement_cents=72586568,
        provisional_rate_impact_pct=7.07,
        surcharge_bp=150,
        final_annual_requirement_cents=73675367,
        rate_impact_pct=7.18,
        uniform_monthly_increase_cents=341,
        monthly_bill_increase_cents=341,
    )
