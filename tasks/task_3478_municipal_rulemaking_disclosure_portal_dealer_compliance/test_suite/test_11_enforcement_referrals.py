"""Enforcement referrals: rule-citation gating, the exactly-one-subject
rule, segregation of duties at close, and not-found identity (PRD sections
2.7, 3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_referral,
    create_dealer_org,
    create_effective_proposal,
    create_professional,
    create_referred_referral,
    create_rule_proposal,
    make_compliance_officer_headers,
    validate_error,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]

UNKNOWN_REFERRAL_ID = "11111111-2222-3333-4444-555555555555"


def test_creating_officer_cannot_close_own_referral(api):
    """PRD section 3.8: "Segregation of duties applies at the close: the
    closing officer's `X-User-ID` must differ from `created_by_user_id`,
    and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    Design: Corner/validations/closing_own_referral_returns_segregation
    """
    referral, rule, subject = create_referred_referral(api, rule_code="G-302")
    # The referral was created by the default compliance officer (co-1).
    own_close = api.advance_enforcement_referral(
        referral["id"],
        {"to_state": "CLOSED_NO_ACTION", "closure_notes": "unsubstantiated"},
        COMPLIANCE,
    )
    validate_error(own_close, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    other_close = advance_referral(
        api,
        referral["id"],
        "CLOSED_NO_ACTION",
        officer_headers=make_compliance_officer_headers("co-2"),
        closure_notes="unsubstantiated",
    )
    assert other_close["status"] == "CLOSED_NO_ACTION", (
        "the identical close succeeds under a different officer"
    )


def test_referral_with_two_subjects_returns_ambiguous_subject(api):
    """PRD section 3.8: "The referral names exactly one subject: setting
    both `subject_org_id` and `subject_professional_id`, or neither, is
    rejected with `ERR_AMBIGUOUS_SUBJECT` (HTTP 422)."

    Design: Corner/validations/referral_with_both_subjects_returns_ambiguous_subject
    """
    rule = create_effective_proposal(
        api, expedited=True, rule_code="G-303", category="DEALER_CONDUCT"
    )
    org = create_dealer_org(api, org_code="BD-3004", name="Dealer Ambig")
    prof = create_professional(api, org["id"], full_name="Pro Ambig")

    resp = api.create_enforcement_referral(
        {
            "rule_code": rule["rule_code"],
            "violation_summary": "both subjects",
            "subject_org_id": org["id"],
            "subject_professional_id": prof["id"],
        },
        COMPLIANCE,
    )
    validate_error(resp, ApiErrorId.ERR_AMBIGUOUS_SUBJECT)


def test_referral_citation_splits_unknown_rule_from_non_effective_rule(api):
    """PRD section 3.8: "The cited `rule_code` must match the `rule_code`
    of an existing rule proposal — otherwise `ERR_RULE_NOT_FOUND`
    (HTTP 404) — and that proposal must currently be `EFFECTIVE`, otherwise
    `ERR_RULE_NOT_EFFECTIVE` (HTTP 422): referrals cannot cite rules still
    in development."

    Design: Corner/validations/referral_citing_non_effective_or_unknown_rule_returns_rule_errors
    """
    org = create_dealer_org(api, org_code="BD-3005", name="Dealer Cite")
    create_rule_proposal(
        api, rule_code="G-304", title="Draft rule", body="d", category="DISCLOSURE"
    )

    unknown = api.create_enforcement_referral(
        {"rule_code": "ZZ-999", "violation_summary": "ghost rule", "subject_org_id": org["id"]},
        COMPLIANCE,
    )
    validate_error(unknown, ApiErrorId.ERR_RULE_NOT_FOUND)

    not_effective = api.create_enforcement_referral(
        {"rule_code": "G-304", "violation_summary": "draft rule", "subject_org_id": org["id"]},
        COMPLIANCE,
    )
    validate_error(not_effective, ApiErrorId.ERR_RULE_NOT_EFFECTIVE)


def test_advance_unknown_referral_returns_referral_not_found(api):
    """PRD section 2.7: "Each resource family carries its own not-found
    error identifier:" — for enforcement referrals that identifier is
    `ERR_REFERRAL_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/advance_unknown_referral_returns_referral_not_found
    """
    resp = api.advance_enforcement_referral(
        UNKNOWN_REFERRAL_ID, {"to_state": "REFERRED"}, COMPLIANCE
    )
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_FOUND)
