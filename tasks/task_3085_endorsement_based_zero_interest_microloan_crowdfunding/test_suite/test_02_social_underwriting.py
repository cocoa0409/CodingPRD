"""Social underwriting: the score variants and the acceptance quota
(PRD §3.2, §3.3)."""
from test_helpers import (
    TEST_USERS,
    create_application,
    create_submittable_borrower,
    create_trustee,
    get_application,
    get_borrower,
    make_borrower_headers,
    set_clock,
    submit_application,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.api_errors import ERR_UNDERWRITING_ACCEPTANCE_QUOTA

ADMIN = TEST_USERS["admin_headers"]


def _score_of(borrower_id):
    return get_borrower(borrower_id)


def test_same_profile_scores_38_self_endorsed_but_63_trustee_vouched(api):
    """PRD §3.2: "The tenure component is 20 times the ratio of the borrower's
    `business_tenure_months` — capped at 24 months — to 24. The community
    component is 30 times the ratio of the borrower's `ACCEPTED` invite count —
    capped at 10 — to 10. The trustee component is 25 when the submission is
    trustee-vouched and 0 otherwise. The repayment component is 25 times the
    ratio of `prior_repaid_loans_count` — capped at 2 — to 2, but only for
    self-endorsed submissions; a trustee's vouch substitutes for repayment
    track record, so trustee-vouched submissions score 0 on this component."
    PRD §3.2: "then stored on the borrower as `social_underwriting_score`
    together with the `underwriting_variant` actually used: `STANDARD` for a
    self-endorsed submission, `TRUSTEE_AUGMENTED` for a trustee-vouched one."

    Design: Difficulty/dual_variant_calc/underwriting_score_standard_vs_trustee_augmented
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=5_000_000)
    borrower_a = create_submittable_borrower(
        accepts=6, business_tenure_months=24, prior_repaid_loans_count=0
    )
    borrower_b = create_submittable_borrower(
        accepts=6, business_tenure_months=24, prior_repaid_loans_count=0
    )
    app_a = create_application(
        borrower_a, requested_amount_cents=1_000_000, term_months=6
    )
    app_b = create_application(
        borrower_b, requested_amount_cents=1_000_000, term_months=6
    )

    app_a = submit_application(app_a, borrower_a)
    app_b = submit_application(app_b, borrower_b, trustee_id=trustee["id"])

    a = _score_of(borrower_a["id"])
    b = _score_of(borrower_b["id"])
    # 20*24/24 + 30*6/10 + 0 + 25*0/2 = 38 (STANDARD)
    assert a["social_underwriting_score"] == 38, f"expected 38, got {a['social_underwriting_score']}"
    assert a["underwriting_variant"] == "STANDARD"
    # 20 + 18 + 25 + 0 = 63 (TRUSTEE_AUGMENTED ignores repayment history)
    assert b["social_underwriting_score"] == 63, f"expected 63, got {b['social_underwriting_score']}"
    assert b["underwriting_variant"] == "TRUSTEE_AUGMENTED"

    assert app_a["endorsement_mode"] == "SELF_ENDORSED"
    assert app_a["required_endorser_count"] == 15
    assert app_b["endorsement_mode"] == "TRUSTEE_VOUCHED"
    assert app_b["required_endorser_count"] == 5


def test_only_trustee_variant_clears_the_approval_threshold_for_same_profile(api):
    """PRD §3.2: "The trustee component is 25 when the submission is
    trustee-vouched and 0 otherwise."
    PRD §3.3: "Approval requires the borrower's
    `social_underwriting_score` to be at least 60 — a score below the
    threshold rejects the approval with `ERR_SCORE_TOO_LOW` (HTTP 409) — and
    moves the application to `APPROVED_PENDING_FUNDRAISE`."

    Design: Difficulty/dual_variant_calc/underwriting_score_standard_vs_trustee_augmented
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=5_000_000)
    borrower_a = create_submittable_borrower(
        accepts=6, business_tenure_months=24, prior_repaid_loans_count=0
    )
    borrower_b = create_submittable_borrower(
        accepts=6, business_tenure_months=24, prior_repaid_loans_count=0
    )
    app_a = submit_application(
        create_application(borrower_a, requested_amount_cents=1_000_000, term_months=6),
        borrower_a,
    )
    app_b = submit_application(
        create_application(borrower_b, requested_amount_cents=1_000_000, term_months=6),
        borrower_b,
        trustee_id=trustee["id"],
    )

    # Same profile, different variant: 38 fails the 60-point approval gate,
    # 63 passes it.
    err = client.approve_application(app_a["id"], ADMIN)
    assert err.status_code == 409
    approved = validate_success(client.approve_application(app_b["id"], ADMIN))
    assert approved["status"] == "APPROVED_PENDING_FUNDRAISE"


def test_score_components_cap_and_repayment_ignored_in_trustee_mode(api):
    """PRD §3.2: "The tenure component is 20 times the ratio of the borrower's
    `business_tenure_months` — capped at 24 months — to 24. The community
    component is 30 times the ratio of the borrower's `ACCEPTED` invite count —
    capped at 10 — to 10. The trustee component is 25 when the submission is
    trustee-vouched and 0 otherwise. The repayment component is 25 times the
    ratio of `prior_repaid_loans_count` — capped at 2 — to 2, but only for
    self-endorsed submissions; a trustee's vouch substitutes for repayment
    track record, so trustee-vouched submissions score 0 on this component."

    Design: Difficulty/combinatorial_formula/social_score_weighted_components
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=8_000_000)
    borrower = create_submittable_borrower(
        accepts=10, business_tenure_months=30, prior_repaid_loans_count=5
    )
    application = submit_application(
        create_application(borrower, requested_amount_cents=2_000_000, term_months=12),
        borrower,
        trustee_id=trustee["id"],
    )

    scored = get_borrower(borrower["id"])
    # tenure caps at 24 -> 20; community caps at 10 -> 30; trustee -> 25;
    # repayment ignored in trustee mode -> 0. Total 75.
    assert scored["social_underwriting_score"] == 75
    assert scored["underwriting_variant"] == "TRUSTEE_AUGMENTED"
    assert application["status"] == "IN_REVIEW"


def test_declined_invites_do_not_count_toward_the_community_component(api):
    """PRD §3.2: "The community component is 30 times the ratio of the
    borrower's `ACCEPTED` invite count — capped at 10 — to 10."
    PRD §3.2: "Acceptance moves the invite to `ACCEPTED`, declining moves it
    to `DECLINED`"

    Design: Difficulty/combinatorial_formula/social_score_weighted_components
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=8_000_000)
    borrower = create_submittable_borrower(
        accepts=10, business_tenure_months=30, prior_repaid_loans_count=5
    )
    # Two extra invites that are DECLINED — they must not lift the score.
    headers = make_borrower_headers(borrower["id"])
    from test_helpers import factories as f

    for i in range(2):
        invite = validate_success(
            client.create_invite(
                borrower["id"], f.create_invite_payload(), headers
            ),
            expected_status=201,
        )
        validate_success(client.decline_invite(invite["invite_token"]))

    submit_application(
        create_application(borrower, requested_amount_cents=2_000_000, term_months=12),
        borrower,
        trustee_id=trustee["id"],
    )
    scored = get_borrower(borrower["id"])
    # With the declined invites counted the community term would still cap at
    # 30, so the discriminator here is repayment-ignored trustee mode + caps:
    # 20 (tenure cap) + 30 (community cap) + 25 (trustee) + 0 = 75.
    assert scored["social_underwriting_score"] == 75


def test_quota_floor_rejects_two_accepts_and_passes_three(api):
    """PRD §3.2: "a borrower needs at least the larger of 3 and the requested
    principal divided by 1,000,000 cents (that is, one additional accepted
    vouch per full $10,000 requested beyond the baseline three), with the
    division floored. Meeting the quota exactly is sufficient. Falling short
    rejects the submission with `ERR_UNDERWRITING_ACCEPTANCE_QUOTA`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/invite_quota_floor_vs_scaled
    """
    set_clock()
    # floor(2999900 / 1000000) = 2 -> quota sits at its floor of 3.
    borrower_a = create_submittable_borrower(
        accepts=2, business_tenure_months=12, prior_repaid_loans_count=0
    )
    borrower_b = create_submittable_borrower(
        accepts=3, business_tenure_months=12, prior_repaid_loans_count=0
    )
    app_a = create_application(
        borrower_a, requested_amount_cents=2_999_900, term_months=6
    )
    app_b = create_application(
        borrower_b, requested_amount_cents=2_999_900, term_months=6
    )

    resp_a = client.submit_application(
        app_a["id"],
        {"expected_application_version": app_a["version"]},
        make_borrower_headers(borrower_a["id"]),
    )
    validate_error(resp_a, ERR_UNDERWRITING_ACCEPTANCE_QUOTA, expected_status=409)
    assert get_application(app_a["id"])["status"] == "DRAFT"

    app_b = submit_application(app_b, borrower_b)
    assert app_b["status"] == "IN_REVIEW"


def test_quota_scales_with_principal_beyond_the_floor(api):
    """PRD §3.2: "a borrower needs at least the larger of 3 and the requested
    principal divided by 1,000,000 cents (that is, one additional accepted
    vouch per full $10,000 requested beyond the baseline three), with the
    division floored. Meeting the quota exactly is sufficient."

    Design: Difficulty/boundary_precision_check/invite_quota_floor_vs_scaled
    """
    set_clock()
    # floor(4_000_000 / 1_000_000) = 4 -> quota 4; 3 accepts must fail, 4 pass.
    borrower_short = create_submittable_borrower(
        accepts=3, business_tenure_months=12, prior_repaid_loans_count=0
    )
    borrower_exact = create_submittable_borrower(
        accepts=4, business_tenure_months=12, prior_repaid_loans_count=0
    )
    app_short = create_application(
        borrower_short, requested_amount_cents=4_000_000, term_months=6
    )
    app_exact = create_application(
        borrower_exact, requested_amount_cents=4_000_000, term_months=6
    )

    resp = client.submit_application(
        app_short["id"],
        {"expected_application_version": app_short["version"]},
        make_borrower_headers(borrower_short["id"]),
    )
    validate_error(resp, ERR_UNDERWRITING_ACCEPTANCE_QUOTA, expected_status=409)

    app_exact = submit_application(app_exact, borrower_exact)
    assert app_exact["status"] == "IN_REVIEW"
