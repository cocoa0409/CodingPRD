"""Citations, the compliance-points suspend/reinstate cycle, and the
optimistic-concurrency guard on agreement write paths.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    create_unit, create_final_determination, create_approved_permit,
    setup_awarded_agreement, get_agreement, refresh_agreement,
    assess_period, issue_agreement_citation, issue_permit_citation,
    void_citation,
    create_assess_payload, create_citation_payload,
)

RM = TEST_USERS["refuge_manager_headers"]
BIO = TEST_USERS["biologist_headers"]
LEO = TEST_USERS["law_enforcement_officer_headers"]


def test_agreement_suspend_reinstate_cycle_citation_driven(api):
    """PRD §3.8: "After every debit, if the agreement is `ACTIVE` and its
    `compliance_points` have fallen below the suspension threshold of 60, it
    moves to `SUSPENDED` — exactly 60 points remains `ACTIVE`, while 59
    suspends."
    PRD §3.8: "When the voided citation named an agreement subject, the
    agreement is credited the citation's points back and its `version`
    increments by one; and if the agreement was `SUSPENDED` and the restored
    `compliance_points` reach at least 60, it returns to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/agreement_suspend_reinstate_cycle_citation_driven
    """
    ctx = setup_awarded_agreement()
    agreement = ctx["agreement"]
    assert agreement["compliance_points"] == 100

    cit1 = issue_agreement_citation(
        agreement, severity="MAJOR", note="Fence damage")
    agreement = refresh_agreement(agreement)
    assert agreement["compliance_points"] == 75
    assert agreement["status"] == "ACTIVE", "75 >= 60: still ACTIVE"

    issue_agreement_citation(
        agreement, severity="MAJOR", note="Unauthorized access")
    agreement = refresh_agreement(agreement)
    assert agreement["compliance_points"] == 50
    assert agreement["status"] == "SUSPENDED", "50 < 60: cascade-suspended"

    void_citation(cit1["id"], reason="Dismissed on review")
    agreement = refresh_agreement(agreement)
    assert agreement["compliance_points"] == 75
    assert agreement["status"] == "ACTIVE", (
        "the void credit restores to 75 >= 60: auto-reinstated")

    issue_agreement_citation(
        agreement, severity="CRITICAL", note="Habitat destruction")
    agreement = refresh_agreement(agreement)
    assert agreement["compliance_points"] == 25
    assert agreement["status"] == "SUSPENDED", (
        "a fresh CRITICAL citation suspends again (the cycle ran twice)")


def test_citation_debit_suspends_agreement_depth2(api):
    """PRD §3.8: "The citation's `points` are computed from severity and
    never taken from the input, even if a value is supplied: 10 for `MINOR`,
    25 for `MAJOR`, 50 for `CRITICAL`."
    PRD §3.8: "After every debit, if the agreement is `ACTIVE` and its
    `compliance_points` have fallen below the suspension threshold of 60, it
    moves to `SUSPENDED` — exactly 60 points remains `ACTIVE`, while 59
    suspends."

    Design: Difficulty/transitive_cascade/citation_debit_suspends_agreement_depth2
    """
    ctx = setup_awarded_agreement()
    citation = issue_agreement_citation(
        ctx["agreement"], severity="CRITICAL", note="Destroyed nesting cover")
    assert citation["points"] == 50, (
        f"CRITICAL must compute 50 points, got {citation['points']}")
    agreement = refresh_agreement(ctx["agreement"])
    assert agreement["compliance_points"] == 50, (
        f"hop 1: the debit takes 100 - 50 = 50, "
        f"got {agreement['compliance_points']}")
    assert agreement["status"] == "SUSPENDED", (
        "hop 2: the debit crossing below 60 flips the agreement to "
        "SUSPENDED")


def test_citation_void_twice_rejected(api):
    """PRD §3.8: "A `LawEnforcementOfficer` or `RefugeManager` voids an
    `ISSUED` citation — the only transition it supports, moving it to
    `VOIDED` with the payload's `reason`."
    PRD §2.6: "5. **State preconditions** — the invoked transition's
    from-state holds; terminal states reject every transition
    (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/citation_void_twice_rejected
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_approved_permit(unit["id"], det["id"], applicant_ref="app-1")
    citation = issue_permit_citation(
        permit["id"], severity="MAJOR", note="Off-trail intrusion")
    voided = void_citation(citation["id"], reason="Dismissed")
    assert voided["status"] == "VOIDED"
    resp = api_client.void_citation(
        citation["id"], {"reason": "Dismissed again"}, LEO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_occ_assess_stale_version_rejected(api):
    """PRD §2.9: "Each carries a non-optional `expected_agreement_version`
    field in the request body, holding the `version` of the agreement the
    client last observed. If the supplied value does not equal the
    agreement's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.8: "Each assessment recomputes the outstanding balance and
    increments the agreement's `version` by one."

    Design: Corner/complexity_layers/occ_assess_stale_version_rejected
    """
    ctx = setup_awarded_agreement()
    agreement = ctx["agreement"]
    observed_version = agreement["version"]
    first = assess_period(
        agreement["id"], period_key="2026-11", aum_used=3,
        rate_cents_per_aum=1001,
        expected_agreement_version=observed_version)
    assert first["assessed_total_cents"] == 1502
    assert first["version"] == observed_version + 1
    resp = api_client.assess_agreement(
        agreement["id"],
        create_assess_payload(
            observed_version, period_key="2026-12", aum_used=3,
            rate_cents_per_aum=1001),
        BIO)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_citation_stale_version_rejected(api):
    """PRD §2.9: "The second guarded path is the issuance of a citation that
    names an agreement subject. Issuing a further citation is legitimate
    against an agreement regardless of how many citations came before, so
    again a strictly later, freshly-read request succeeds; the version check
    rejects the stale view, since the agreement's `compliance_points` may
    have been debited or restored since the officer last read it."

    Design: Corner/complexity_layers/occ_citation_stale_version_rejected
    """
    ctx = setup_awarded_agreement()
    agreement = ctx["agreement"]
    observed_version = agreement["version"]
    issue_agreement_citation(
        agreement, severity="MAJOR", note="Fence damage",
        expected_agreement_version=observed_version)
    resp = api_client.create_citation(
        create_citation_payload(
            subject_agreement_id=agreement["id"], severity="MINOR",
            note="Late report",
            expected_agreement_version=observed_version),
        LEO)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = get_agreement(agreement["id"])
    assert after["compliance_points"] == 75, (
        f"the rejected stale citation must not debit; points stay at "
        f"100 - 25 = 75, got {after['compliance_points']}")
