"""Employer registration, domain verification, fraud scoring, and screening."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_employer,
    create_approved_employer,
    get_employer,
    make_employer_recruiter_headers,
    register_employer,
    screen_employer,
    set_clock,
    validate_error,
    validate_success,
    verify_employer,
)
from test_helpers.fixtures import PA


class TestFraudScoreVariants:
    def test_verify_domain_computes_auto_screen_score(self, api):
        """PRD §3.2: "On a match, the employer moves from `PENDING` to `DOMAIN_VERIFIED`,
        and the automatic screening variant computes its initial `fraud_risk_score` from
        the registration fields alone."
        PRD §3.2: "The computation starts at a base of 50 points. If the `contact_email`
        ends with the at-sign followed by the `website_domain`, 25 points are
        subtracted — the recruiter demonstrably controls the domain."

        Design: Difficulty/dual_variant_calc/fraud_risk_auto_vs_analyst_screening
        """
        set_clock()
        employer = register_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        assert employer["status"] == "PENDING"
        verified = validate_success(
            api.verify_domain(
                employer["id"],
                {"verification_token": employer["domain_verification_token"]},
                make_employer_recruiter_headers(employer["id"]),
            ),
            200,
        )
        assert_employer(verified)
        assert verified["status"] == "DOMAIN_VERIFIED"
        # auto variant: 50 - 25 (contact_email ends with "@acme.com") = 25.
        assert verified["fraud_risk_score"] == 25, (
            f"auto variant must yield 25 (50 - 25 email-domain match), "
            f"got {verified['fraud_risk_score']}"
        )
        assert verified["trust_tier"] == "STANDARD"

    def test_analyst_screen_recomputes_from_stored_score(self, api):
        """PRD §3.2: "Every screening call, before it applies the decision's state
        change, recomputes the score with the analyst variant: the computation starts
        from the currently stored `fraud_risk_score`, adds the
        `analyst_signal_adjustment`, and, when the decision is `FLAG`, adds a further
        10 points as the flag penalty; the result is clamped to the inclusive 0-to-100
        range and the `trust_tier` is re-derived."
        PRD §3.2: "a score of 20 or less is `LOW_RISK`; 50 or less is `STANDARD`;
        79 or less is `ELEVATED`; anything above that is `HIGH_RISK`."

        Design: Difficulty/dual_variant_calc/fraud_risk_auto_vs_analyst_screening
        """
        set_clock()
        employer = register_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        verify_employer(employer)
        screened = screen_employer(employer["id"], "CLEAR", analyst_signal_adjustment=30)
        # analyst variant over the SAME registration data: 25 + 30 = 55.
        assert screened["fraud_risk_score"] == 55, (
            f"analyst variant must yield 55 (25 + 30), got {screened['fraud_risk_score']}"
        )
        assert screened["fraud_risk_score"] != 25
        assert screened["trust_tier"] == "ELEVATED"
        assert screened["status"] == "APPROVED"
        assert screened["screen_count"] == 1


class TestEmployerReviewCycle:
    def test_flag_moves_approved_employer_to_under_review(self, api):
        """PRD §3.2: "`FLAG` moves an employer from `DOMAIN_VERIFIED` or `APPROVED` to
        `UNDER_REVIEW`."
        PRD §3.2: "the computation starts from the currently stored `fraud_risk_score`,
        adds the `analyst_signal_adjustment`, and, when the decision is `FLAG`, adds a
        further 10 points as the flag penalty"

        Design: Difficulty/non_linear_state_machine/employer_approved_under_review_cycle
        """
        set_clock()
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        assert employer["status"] == "APPROVED"
        assert employer["fraud_risk_score"] == 25
        assert employer["version"] == 3
        flagged = screen_employer(employer["id"], "FLAG")
        assert flagged["status"] == "UNDER_REVIEW"
        # 25 + 10 FLAG_PENALTY = 35; still STANDARD (<= 50).
        assert flagged["fraud_risk_score"] == 35
        assert flagged["trust_tier"] == "STANDARD"
        assert flagged["version"] == 4
        assert flagged["screen_count"] == 2

    def test_clear_from_under_review_closes_the_cycle(self, api):
        """PRD §3.2: "`CLEAR` moves an employer from `DOMAIN_VERIFIED` or from
        `UNDER_REVIEW` to `APPROVED`, but only when the resulting `trust_tier` is not
        `HIGH_RISK`"
        PRD §3.2: "Every screening call also increments `screen_count` by 1 and the
        employer's `version` by 1, regardless of which decision was issued"

        Design: Difficulty/non_linear_state_machine/employer_approved_under_review_cycle
        """
        set_clock()
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        screen_employer(employer["id"], "FLAG")
        cleared = screen_employer(employer["id"], "CLEAR", analyst_signal_adjustment=0)
        # The cycle APPROVED -> UNDER_REVIEW -> APPROVED closed.
        assert cleared["status"] == "APPROVED"
        # No second FLAG_PENALTY on CLEAR: 35 + 0 = 35.
        assert cleared["fraud_risk_score"] == 35
        assert cleared["version"] == 5
        assert cleared["screen_count"] == 3


class TestEmployerReads:
    def test_get_with_unknown_id_returns_employer_not_found(self, api, platform_admin_headers):
        """PRD §2.7: "Each resource type has its own not-found error:
        `ERR_UNIVERSITY_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`,
        `ERR_EMPLOYER_APPROVAL_NOT_FOUND`, `ERR_JOB_POSTING_NOT_FOUND`,
        `ERR_CAREER_EVENT_NOT_FOUND`, `ERR_EVENT_SESSION_NOT_FOUND`,
        `ERR_EVENT_SIGNUP_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, and
        `ERR_OUTREACH_MESSAGE_NOT_FOUND` — all HTTP 404."

        Design: Corner/entities/employer_get_with_unknown_id_returns_employer_not_found
        """
        set_clock()
        response = api.get_employer(NON_EXISTENT_UUID, platform_admin_headers)
        error = validate_error(response, ApiErrorId.ERR_EMPLOYER_NOT_FOUND, 404)
        assert isinstance(error["message"], str) and error["message"].strip()


class TestEmployerTerminalState:
    def test_rejected_is_terminal(self, api):
        """PRD §3.2: "`REJECTED` is terminal: any further screening decision against it,
        and any decision whose source state is not in the lists above, is rejected with
        `ERR_INVALID_EMPLOYER_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/employer_rejected_is_terminal
        """
        set_clock()
        employer = register_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        verify_employer(employer)
        rejected = screen_employer(employer["id"], "REJECT")
        assert rejected["status"] == "REJECTED"
        response = api.screen_employer(
            employer["id"], {"decision": "CLEAR", "analyst_signal_adjustment": 0}, PA
        )
        validate_error(response, ApiErrorId.ERR_INVALID_EMPLOYER_TRANSITION, 409)
        assert get_employer(employer["id"])["status"] == "REJECTED"


class TestTrustTierBoundary:
    def test_score_20_is_low_risk_21_is_standard(self, api):
        """PRD §3.2: "From the score, the `trust_tier` is re-derived after every score
        change, on fixed boundaries: a score of 20 or less is `LOW_RISK`; 50 or less is
        `STANDARD`; 79 or less is `ELEVATED`; anything above that is `HIGH_RISK`."
        PRD §3.2: "If the `website_domain` ends with the `.edu` or `.gov` suffix, 15
        points are subtracted for an established top-level domain."

        Design: Corner/calculations/fraud_tier_boundary_score_20_low_risk_21_standard
        """
        set_clock()
        # Both auto-score 10: 50 - 25 (email-domain match) - 15 (.edu TLD).
        beta = register_employer(
            company_name="Beta Works", website_domain="beta.edu",
            contact_email="hi@beta.edu",
        )
        beta = verify_employer(beta)
        assert beta["fraud_risk_score"] == 10
        delta = register_employer(
            company_name="Delta U", website_domain="delta.edu",
            contact_email="hi@delta.edu",
        )
        delta = verify_employer(delta)
        assert delta["fraud_risk_score"] == 10

        beta = screen_employer(beta["id"], "CLEAR", analyst_signal_adjustment=10)
        assert beta["fraud_risk_score"] == 20
        assert beta["trust_tier"] == "LOW_RISK", (
            f"score 20 must be LOW_RISK (<= 20), got {beta['trust_tier']}"
        )
        assert beta["status"] == "APPROVED"

        delta = screen_employer(delta["id"], "CLEAR", analyst_signal_adjustment=11)
        assert delta["fraud_risk_score"] == 21
        assert delta["trust_tier"] == "STANDARD", (
            f"score 21 must be STANDARD (> 20), got {delta['trust_tier']}"
        )
        assert delta["status"] == "APPROVED"
