"""Field evaluations and jurisdictional acceptance.

Covers the two parallel status dimensions (a failed evaluation blocks
acceptance), the one-hop reciprocity rule with group matching, and the
entity-backed ownership of the AHJAuthority role.
"""

from test_helpers import (
    ApiErrorId,
    BASE_CLOCK_ISO,
    acceptance_decision_payload,
    canonical_instant,
    create_field_evaluation,
    create_jurisdiction,
    create_manufacturer,
    create_standard,
    decide_acceptance,
    evaluate_field_evaluation,
    get_success_data,
    make_ahj_authority_headers,
    set_clock,
    setup_field_evaluation_world,
    validate_error,
)


def test_field_evaluation_failed_dimension_blocks_acceptance_dimension(api, officer_headers):
    """PRD §3.8: "A `FAIL` moves it to `EVALUATED_FAIL`, which is terminal for
    the evaluation dimension: no further evaluation may be recorded and no
    acceptance approval may follow, although the acceptance dimension may still
    be resolved by rejection — while a fail leaves `acceptance_status` at
    `PENDING`, only a rejection can follow."
    PRD §3.8: "An acceptance additionally requires `eval_status` to be
    `EVALUATED_PASS`; attempting to accept a failed or not-yet-evaluated
    evaluation is rejected with `ERR_FIELD_EVALUATION_NOT_PASSED`, and
    attempting any acceptance decision while `eval_status` is still `REQUESTED`
    meets the same error."

    Design: Corner/state_machines/field_evaluation_failed_dimension_blocks_acceptance_dimension
    """
    ctx = setup_field_evaluation_world(api, evaluate="FAIL")
    evaluation = ctx["field_evaluation"]
    response = api.decide_field_evaluation_acceptance(
        evaluation["id"],
        acceptance_decision_payload("ACCEPT"),
        make_ahj_authority_headers(ctx["jur_site"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FIELD_EVALUATION_NOT_PASSED)
    view = get_success_data(api.get_field_evaluation(evaluation["id"], officer_headers))
    assert view["eval_status"] == "EVALUATED_FAIL"
    assert view["acceptance_status"] == "PENDING"
    assert view["label_issued_on"] is None


def test_reciprocity_acceptance_one_hop_group_match_vs_mismatch(api, officer_headers):
    """PRD §3.8: "The site jurisdiction accepts the label outright when its own
    `accepts_field_labels` is true. Otherwise exactly one hop of reciprocity is
    available: the site jurisdiction must have `accepts_reciprocity` set, the
    evaluating jurisdiction's `jurisdiction_code` must appear in the site
    jurisdiction's `reciprocity_sources`, the evaluating jurisdiction must
    itself have `accepts_field_labels` set, and the two jurisdictions'
    `reciprocity_group` values must be equal — unless both are `NONE`, which
    also qualifies. Sources-of-sources are never consulted; there is no
    transitive closure. When none of this holds, the acceptance is rejected with
    `ERR_RECIPROCITY_NOT_GRANTED`."
    PRD §3.8: "On acceptance, `acceptance_status` becomes `ACCEPTED`,
    `label_issued_on` is set to the current logical time, and `ahj_decided_by`
    records the decider's `X-User-ID`."

    Design: Corner/calculations/reciprocity_acceptance_one_hop_group_match_vs_mismatch
    """
    set_clock(api, BASE_CLOCK_ISO)
    standard = create_standard(api)
    manufacturer = create_manufacturer(api)
    jur_evaluating = create_jurisdiction(api)  # US-OSHA: accepts labels, NATIONAL
    jur_direct = create_jurisdiction(
        api,
        jurisdiction_code="US-CPSC",
        name="CPSC",
        accepts_field_labels=True,
        accepts_reciprocity=False,
        reciprocity_sources=[],
        reciprocity_group="NATIONAL",
    )
    jur_reciprocity = create_jurisdiction(
        api,
        jurisdiction_code="CA-SCC",
        name="SCC Canada",
        accepts_field_labels=False,
        accepts_reciprocity=True,
        reciprocity_sources=["US-OSHA"],
        reciprocity_group="NATIONAL",
    )
    jur_mismatch = create_jurisdiction(
        api,
        jurisdiction_code="DE-LGA",
        name="LGA Bayern",
        accepts_field_labels=False,
        accepts_reciprocity=True,
        reciprocity_sources=["US-OSHA"],
        reciprocity_group="BILATERAL_EU",
    )
    fe_reciprocity = create_field_evaluation(
        api,
        manufacturer["id"],
        standard["id"],
        jur_evaluating["id"],
        jur_reciprocity["id"],
        equipment_description="Pump controller A",
        site_address="1 Rue King, Sherbrooke QC",
    )
    fe_mismatch = create_field_evaluation(
        api,
        manufacturer["id"],
        standard["id"],
        jur_evaluating["id"],
        jur_mismatch["id"],
        equipment_description="Pump controller B",
        site_address="5 Werkstrasse, Munich",
    )
    fe_direct = create_field_evaluation(
        api,
        manufacturer["id"],
        standard["id"],
        jur_evaluating["id"],
        jur_direct["id"],
    )
    for evaluation in (fe_reciprocity, fe_mismatch, fe_direct):
        evaluate_field_evaluation(api, evaluation["id"], "PASS")

    # One hop, groups match (NATIONAL == NATIONAL) -> accepted.
    accepted = decide_acceptance(
        api,
        fe_reciprocity["id"],
        jur_reciprocity["id"],
        "ACCEPT",
        basis="Reciprocity: SCC recognizes US-OSHA NRTL",
    )
    assert accepted["acceptance_status"] == "ACCEPTED"
    assert canonical_instant(accepted["label_issued_on"]) == canonical_instant(
        BASE_CLOCK_ISO
    )

    # Group mismatch (NATIONAL vs BILATERAL_EU) defeats reciprocity.
    blocked = api.decide_field_evaluation_acceptance(
        fe_mismatch["id"],
        acceptance_decision_payload("ACCEPT"),
        make_ahj_authority_headers(jur_mismatch["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_RECIPROCITY_NOT_GRANTED)
    mismatch_view = get_success_data(
        api.get_field_evaluation(fe_mismatch["id"], officer_headers)
    )
    assert mismatch_view["acceptance_status"] == "PENDING"

    # Direct acceptance needs no reciprocity at all.
    direct = decide_acceptance(api, fe_direct["id"], jur_direct["id"], "ACCEPT")
    assert direct["acceptance_status"] == "ACCEPTED"


def test_ahj_authority_for_other_jurisdiction_cannot_decide_returns_forbidden(
    api, officer_headers
):
    """PRD §3.8: "The authority's `X-User-ID` must equal the field evaluation's
    `site_jurisdiction_id` — an authority decides only for installations in its
    own jurisdiction, and any other authority is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/roles/ahj_authority_for_other_jurisdiction_cannot_decide_returns_forbidden
    """
    ctx = setup_field_evaluation_world(api, evaluate="PASS")
    evaluation = ctx["field_evaluation"]
    # The evaluating jurisdiction's authority is not the site authority.
    response = api.decide_field_evaluation_acceptance(
        evaluation["id"],
        acceptance_decision_payload("ACCEPT"),
        make_ahj_authority_headers(ctx["jur_evaluating"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN)
    view = get_success_data(api.get_field_evaluation(evaluation["id"], officer_headers))
    assert view["acceptance_status"] == "PENDING", "no decision may be recorded"
