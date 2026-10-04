"""Evidence posture precedence and the database-HIT cascade (chain B): the
exculpatory flag outranks item tallies and flips the ACTUAL_INNOCENCE
petition gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_effective_authorization,
    add_evidence_item,
    add_lab_analysis,
    advance_case_to,
    create_legal_petition,
    create_legal_petition_payload,
    get_case,
    record_result_on_ctx,
    run_database_comparison,
    setup_case_in_litigation,
    setup_case_with_destroyed_evidence,
    validate_created,
    validate_error,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]


def test_posture_exculpatory_precedence_over_compromised(api):
    """PRD section 3.3: "Evaluated top-down with the first match winning: if
    the case's `exculpatory_evidence_flag` is true the posture is
    `EXCULPATORY`; else if the case has no items, `NO_EVIDENCE`; else with at
    least one confirmed and no destroyed items, `SECURED`; with at least one
    confirmed and at least one destroyed, `PARTIALLY_COMPROMISED`; with none
    confirmed and at least one destroyed, `FULLY_COMPROMISED`; otherwise
    `SEEKING`."

    Design: Corner/calculations/posture_exculpatory_precedence_over_compromised
    """
    # Item 1 destroyed via the records cascade; no confirmed items yet.
    ctx = setup_case_with_destroyed_evidence(
        jurisdiction_overrides={"state_code": "KY", "name": "Kentucky"}
    )
    assert ctx["case"]["evidence_posture"] == "FULLY_COMPROMISED"
    assert ctx["case"]["destroyed_evidence_count"] == 1

    # Item 2 custody-confirmed: confirmed >= 1 AND destroyed >= 1.
    add_evidence_item(ctx)
    assert get_case(ctx["case"]["id"])["evidence_posture"] == "PARTIALLY_COMPROMISED"

    advance_case_to(ctx, "BEGIN_INVESTIGATION")
    add_effective_authorization(ctx)
    advance_case_to(ctx, "BEGIN_TESTING")
    add_lab_analysis(ctx, required_sample_ng=6)
    record_result_on_ctx(ctx)

    # The HIT sets the flag, and the flag outranks the item tallies.
    run_database_comparison(ctx["analysis"]["id"])
    case = get_case(ctx["case"]["id"])
    assert case["exculpatory_evidence_flag"] is True
    assert case["evidence_posture"] == "EXCULPATORY"


def test_db_hit_opens_actual_innocence_claim_basis(api):
    """PRD section 3.6: "a `claim_basis` of `ACTUAL_INNOCENCE` or `BOTH`
    requires the case's `exculpatory_evidence_flag` to be true —
    database-confirmed exculpatory evidence, per §3.5 — else
    `ERR_NO_EXCULPATORY_BASIS` (HTTP 422)."
    PRD section 3.5: "A `HIT` is the single most consequential write in the
    pipeline: it sets the owning case's `exculpatory_evidence_flag` true — a
    flag never auto-cleared once set".

    Design: Difficulty/transitive_cascade/db_hit_sets_exculpatory_flag_and_opens_innocence_basis
    """
    ctx = setup_case_in_litigation(
        jurisdiction_overrides={"state_code": "PA", "name": "Pennsylvania"}
    )
    assert ctx["case"]["exculpatory_evidence_flag"] is False

    # Pre-cascade: the ACTUAL_INNOCENCE basis is closed.
    resp = api.create_legal_petition(
        create_legal_petition_payload(
            ctx["case"]["id"],
            petition_type="POST_CONVICTION",
            court_name="PA Court of Common Pleas",
            claim_basis="ACTUAL_INNOCENCE",
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_NO_EXCULPATORY_BASIS)

    # The cascade flips the gate: the identical create now succeeds.
    run_database_comparison(ctx["analysis"]["id"])
    ok = api.create_legal_petition(
        create_legal_petition_payload(
            ctx["case"]["id"],
            petition_type="POST_CONVICTION",
            court_name="PA Court of Common Pleas",
            claim_basis="ACTUAL_INNOCENCE",
        ),
        ATTORNEY,
    )
    validate_created(ok)


def test_db_hit_sets_flag_and_exculpatory_posture(api):
    """PRD section 3.5: "The outcome lands in `db_comparison_status` (which
    starts at `NOT_RUN`) as `COMPLETED_HIT`, `COMPLETED_NO_HIT`, or
    `COMPLETED_PARTIAL`."
    PRD section 2.6: "runs from a database-comparison hit on a lab analysis
    to the owning case's `exculpatory_evidence_flag` being set true, followed
    by re-derivation of the case's `evidence_posture`, where the exculpatory
    result takes precedence over every other posture input."

    Design: Difficulty/transitive_cascade/db_hit_sets_exculpatory_flag_and_opens_innocence_basis
    """
    ctx = setup_case_in_litigation(
        jurisdiction_overrides={"state_code": "PA", "name": "Pennsylvania"}
    )
    assert ctx["analysis"]["db_comparison_status"] == "NOT_RUN"
    assert ctx["case"]["evidence_posture"] == "SECURED"

    analysis = run_database_comparison(
        ctx["analysis"]["id"], database_name="INTERSTATE_OFFENDER_DB"
    )
    assert analysis["db_comparison_status"] == "COMPLETED_HIT"
    assert analysis["db_matched_subject_name"] == "John Doe"

    case = get_case(ctx["case"]["id"])
    assert case["exculpatory_evidence_flag"] is True
    assert case["evidence_posture"] == "EXCULPATORY", (
        "the flag takes precedence over the SECURED item tally"
    )
