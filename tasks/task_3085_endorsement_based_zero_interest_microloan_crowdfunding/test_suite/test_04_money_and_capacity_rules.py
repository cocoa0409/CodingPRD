"""Lender accounts, trustee capacity, and fiscal validation rules
(PRD §3.1, §3.4, §3.5, §2.9)."""
from test_helpers import (
    TEST_USERS,
    create_application,
    create_borrower,
    create_lender,
    create_private_fundraising_application,
    create_submittable_borrower,
    create_trustee,
    deposit,
    endorse,
    get_application,
    get_lender,
    get_trustee,
    make_borrower_headers,
    make_lender_headers,
    make_trustee_headers,
    set_clock,
    trustee_endorse,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INSUFFICIENT_BALANCE,
    ERR_INVALID_STATE,
    ERR_MIN_CONTRIBUTION,
    ERR_OVERFUND,
    ERR_TRUSTEE_LIMIT_EXCEEDED,
    ERR_UNDERWRITING_ACCEPTANCE_QUOTA,
    ERR_DUPLICATE,
)

ADMIN = TEST_USERS["admin_headers"]


def test_deposit_credits_lending_account(api):
    """PRD §3.1: "Funds enter the account through deposits: each deposit adds
    its `amount_cents` to both `lending_balance_cents` and
    `total_deposited_cents` and bumps the lender's `version`."

    Design: Corner/endpoints/deposit_credits_lending_account
    """
    set_clock()
    lender = create_lender()
    updated = deposit(lender["id"], 75_000)
    assert updated["lending_balance_cents"] == 75_000
    assert updated["total_deposited_cents"] == 75_000
    assert updated["version"] == lender["version"] + 1, "deposit bumps version"


def test_trustee_endorsement_moves_no_money_but_counts_toward_quorum(api):
    """PRD §3.4: "Trustee endorsements move no money — no lender balance is
    debited — but they count toward the endorser quorum and their
    `amount_cents` counts against the trustee's cap"
    PRD §3.4: "A trustee endorsement raises the trustee's exposure, the
    application's `private_total_cents`, and its `distinct_endorser_count`
    exactly as a lender endorsement would."

    Design: Corner/endpoints/trustee_endorsement_moves_no_money_but_counts_toward_quorum
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=80_000)
    ns = create_private_fundraising_application(
        trustee=trustee, requested_amount_cents=50_000, term_months=3
    )
    bystander = create_lender(deposit_cents=100_000)

    endorsement = trustee_endorse(ns.application, trustee, 60_000)
    assert endorsement["is_trustee_endorsement"] is True
    assert endorsement["trustee_id"] == trustee["id"]

    application = get_application(ns.application["id"])
    assert application["private_total_cents"] == 60_000
    assert application["distinct_endorser_count"] == 1

    trustee_after = get_trustee(trustee["id"])
    assert trustee_after["active_endorsement_exposure_cents"] == 60_000

    # No lender balance moved: the bystander's deposit is untouched.
    assert get_lender(bystander["id"])["lending_balance_cents"] == 100_000


def test_trustee_endorsement_fills_the_fifth_quorum_slot(api):
    """PRD §3.4: "The quorum itself is a count of distinct endorsers: the
    number of distinct lenders holding `ACTIVE` non-trustee endorsements,
    plus the number of `ACTIVE` trustee endorsements."
    PRD §3.4: "the count must meet the `required_endorser_count` pinned at
    submission (15 self-endorsed, 5 trustee-vouched); meeting it exactly
    suffices"

    Design: Corner/endpoints/trustee_endorsement_moves_no_money_but_counts_toward_quorum
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=5_000_000)
    ns = create_private_fundraising_application(trustee=trustee)
    for _ in range(4):
        lender = create_lender(deposit_cents=100_000)
        endorse(ns.application, lender, 25_000)
    trustee_endorse(ns.application, trustee, 50_000)

    application = get_application(ns.application["id"])
    assert application["distinct_endorser_count"] == 5
    opened = validate_success(
        client.open_public(
            application["id"], make_borrower_headers(ns.borrower["id"])
        )
    )
    assert opened["status"] == "PUBLIC_FUNDRAISING"


def test_trustee_endorsement_over_limit_rejected(api):
    """PRD §3.4: "the trustee's `active_endorsement_exposure_cents` (the sum
    of `amount_cents` over that trustee's `ACTIVE` trustee endorsements) plus
    the new amount must stay within `endorsement_limit_cents`, else
    `ERR_TRUSTEE_LIMIT_EXCEEDED`"

    Design: Corner/endpoints/trustee_endorsement_over_limit_rejected
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=80_000)
    ns1 = create_private_fundraising_application(
        requested_amount_cents=50_000, term_months=3
    )
    trustee_endorse(ns1.application, trustee, 60_000)

    # Second live application from another borrower; exposure 60000 + 20001
    # breaches the 80000 cap.
    ns2 = create_private_fundraising_application(
        requested_amount_cents=50_000, term_months=3
    )
    resp = client.create_trustee_endorsement(
        trustee["id"],
        {"loan_application_id": ns2.application["id"], "amount_cents": 20_001},
        make_trustee_headers(trustee["id"]),
    )
    validate_error(resp, ERR_TRUSTEE_LIMIT_EXCEEDED, expected_status=422)
    assert get_trustee(trustee["id"])["active_endorsement_exposure_cents"] == 60_000


def test_trustee_endorsement_at_exact_remaining_capacity_succeeds(api):
    """PRD §3.4: "the trustee's `active_endorsement_exposure_cents` (the sum
    of `amount_cents` over that trustee's `ACTIVE` trustee endorsements) plus
    the new amount must stay within `endorsement_limit_cents`, else
    `ERR_TRUSTEE_LIMIT_EXCEEDED`"

    Design: Corner/endpoints/trustee_endorsement_over_limit_rejected
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=80_000)
    ns1 = create_private_fundraising_application(
        requested_amount_cents=50_000, term_months=3
    )
    trustee_endorse(ns1.application, trustee, 60_000)

    ns2 = create_private_fundraising_application(
        requested_amount_cents=50_000, term_months=3
    )
    endorsement = trustee_endorse(ns2.application, trustee, 20_000)
    assert endorsement["status"] == "ACTIVE"
    assert (
        get_trustee(trustee["id"])["active_endorsement_exposure_cents"] == 80_000
    ), "60000 + 20000 lands exactly on the cap"


def test_endorsement_below_minimum_rejected(api):
    """PRD §3.4: "Creating an endorsement requires the target application to
    be in `PRIVATE_FUNDRAISING`, names the lending `lender_id` and an
    `amount_cents` of at least 2,500 cents ($25) — anything smaller is
    rejected with `ERR_MIN_CONTRIBUTION` (HTTP 422)"

    Design: Corner/validations/contribution_below_minimum_rejected
    """
    set_clock()
    ns = create_private_fundraising_application()
    lender = create_lender(deposit_cents=100_000)

    resp = client.create_endorsement(
        ns.application["id"],
        {"lender_id": lender["id"], "amount_cents": 2_499},
        make_lender_headers(lender["id"]),
    )
    validate_error(resp, ERR_MIN_CONTRIBUTION, expected_status=422)
    assert get_lender(lender["id"])["lending_balance_cents"] == 100_000

    # The minimum itself is accepted.
    endorse(ns.application, lender, 2_500)
    assert get_lender(lender["id"])["lending_balance_cents"] == 97_500


def test_endorsement_insufficient_balance_rejected(api):
    """PRD §3.4: "debits the lender's `lending_balance_cents` by that amount;
    a balance short of the amount is rejected with `ERR_INSUFFICIENT_BALANCE`
    (HTTP 422)."

    Design: Corner/validations/endorsement_insufficient_balance_rejected
    """
    set_clock()
    ns = create_private_fundraising_application()
    lender = create_lender(deposit_cents=2_499)

    resp = client.create_endorsement(
        ns.application["id"],
        {"lender_id": lender["id"], "amount_cents": 2_500},
        make_lender_headers(lender["id"]),
    )
    validate_error(resp, ERR_INSUFFICIENT_BALANCE, expected_status=422)
    assert get_lender(lender["id"])["lending_balance_cents"] == 2_499


def test_overfund_rejected_above_exact_remaining(api):
    """PRD §3.5: "Overfunding is impossible by construction: a contribution
    that would push `funded_total_cents` (the sum of `private_total_cents`
    and `public_total_cents`) above `requested_amount_cents` is rejected with
    `ERR_OVERFUND` (HTTP 422)."

    Design: Corner/validations/overfund_rejected_at_exact_remaining
    """
    set_clock()
    # funded_total 475000 of 500000: 15 x 25000 endorsements + 100000 public.
    ns = create_private_fundraising_application(
        requested_amount_cents=500_000, term_months=6
    )
    application, _ = fx.meet_quorum_with_endorsements(ns, [25_000] * 15)
    application = fx.open_public(application, ns.borrower)
    whale = create_lender(deposit_cents=10_000_000)
    fx.contribute(application, whale, 100_000)

    resp = client.create_contribution(
        application["id"],
        {"lender_id": whale["id"], "amount_cents": 25_001},
        make_lender_headers(whale["id"]),
    )
    validate_error(resp, ERR_OVERFUND, expected_status=422)
    assert get_application(application["id"])["status"] == "PUBLIC_FUNDRAISING"


def test_contribution_at_exact_remaining_fills_and_flips_funded(api):
    """PRD §3.5: "The moment a contribution brings `funded_total_cents` to
    exactly the requested amount, the application transitions automatically
    to `FUNDED` and stamps `funded_at`."

    Design: Corner/validations/overfund_rejected_at_exact_remaining
    """
    set_clock()
    ns = create_private_fundraising_application(
        requested_amount_cents=500_000, term_months=6
    )
    application, _ = fx.meet_quorum_with_endorsements(ns, [25_000] * 15)
    application = fx.open_public(application, ns.borrower)
    whale = create_lender(deposit_cents=10_000_000)
    fx.contribute(application, whale, 100_000)

    fx.contribute(application, whale, 25_000)
    application = get_application(application["id"])
    assert application["status"] == "FUNDED"
    assert application["funded_total_cents"] == 500_000
    assert application["funded_at"] is not None


def test_duplicate_active_endorsement_same_lender_rejected(api):
    """PRD §2.8: "the pair (`loan_application_id`, `lender_id`) may have at
    most one `ACTIVE` endorsement — a lender who already holds a live
    endorsement on an application cannot place a second one, though a
    cancelled or refunded endorsement does not block a new one."

    Design: Corner/validations/duplicate_active_endorsement_same_lender_rejected
    """
    set_clock()
    ns = create_private_fundraising_application()
    lender = create_lender(deposit_cents=200_000)
    endorse(ns.application, lender, 25_000)

    resp = client.create_endorsement(
        ns.application["id"],
        {"lender_id": lender["id"], "amount_cents": 25_000},
        make_lender_headers(lender["id"]),
    )
    validate_error(resp, ERR_DUPLICATE, expected_status=409)


def test_contribution_to_draft_application_reports_state_not_overfund(api):
    """PRD §2.9: "When a request could fail for several reasons, checks are
    evaluated in a fixed global order so the reported error is
    deterministic."
    PRD §2.9: "Fourth, state permissibility of the target resource
    (`ERR_INVALID_STATE`)."
    PRD §3.5: "In `PUBLIC_FUNDRAISING`, any lender may contribute."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_contribution
    """
    set_clock()
    borrower = create_submittable_borrower()
    application = create_application(
        borrower, requested_amount_cents=250_000, term_months=3
    )
    lender = create_lender(deposit_cents=1_000_000)

    # 300000 would overfund a 250000 request, but the application is DRAFT:
    # the state check is evaluated before the fiscal rule.
    resp = client.create_contribution(
        application["id"],
        {"lender_id": lender["id"], "amount_cents": 300_000},
        make_lender_headers(lender["id"]),
    )
    validate_error(resp, ERR_INVALID_STATE, expected_status=409)
    assert get_lender(lender["id"])["lending_balance_cents"] == 1_000_000


def test_endorsement_to_draft_application_reports_state(api):
    """PRD §2.9: "Fourth, state permissibility of the target resource
    (`ERR_INVALID_STATE`)."
    PRD §3.4: "Creating an endorsement requires the target application to be
    in `PRIVATE_FUNDRAISING`"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_contribution
    """
    set_clock()
    borrower = create_submittable_borrower()
    application = create_application(
        borrower, requested_amount_cents=250_000, term_months=3
    )
    lender = create_lender(deposit_cents=1_000_000)

    resp = client.create_endorsement(
        application["id"],
        {"lender_id": lender["id"], "amount_cents": 25_000},
        make_lender_headers(lender["id"]),
    )
    validate_error(resp, ERR_INVALID_STATE, expected_status=409)
    assert get_lender(lender["id"])["lending_balance_cents"] == 1_000_000
    application = get_application(application["id"])
    assert application["private_total_cents"] == 0
    assert application["distinct_endorser_count"] == 0


def test_submit_failing_quota_reports_quota_not_trustee_limit(api):
    """PRD §2.9: "Seventh, the domain safety and fiscal rules in their stated
    per-endpoint order (§3 names the order where several apply to one
    endpoint)."
    PRD §3.3: "the acceptance quota of §3.2 must be met; and, when the
    submission names a `trustee_id`, the trustee must exist, must be `ACTIVE`
    (a suspended trustee yields `ERR_TRUSTEE_SUSPENDED`, HTTP 409), and must
    have remaining capacity — the application's `requested_amount_cents` plus
    the trustee's `active_endorsement_exposure_cents` must not exceed the
    trustee's `endorsement_limit_cents`, or the submission fails with
    `ERR_TRUSTEE_LIMIT_EXCEEDED` (HTTP 422)."
    PRD §3.2: "Falling short rejects the submission with
    `ERR_UNDERWRITING_ACCEPTANCE_QUOTA` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_submit
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=100_000)
    borrower = create_borrower(
        business_tenure_months=5, prior_repaid_loans_count=0
    )
    application = create_application(
        borrower, requested_amount_cents=500_000, term_months=6
    )

    # Zero accepted invites AND requested 500000 > trustee limit 100000: the
    # quota check is named before the trustee capacity check.
    resp = client.submit_application(
        application["id"],
        {
            "expected_application_version": application["version"],
            "trustee_id": trustee["id"],
        },
        make_borrower_headers(borrower["id"]),
    )
    validate_error(resp, ERR_UNDERWRITING_ACCEPTANCE_QUOTA, expected_status=409)
    assert get_application(application["id"])["status"] == "DRAFT"


def test_submit_past_quota_reports_trustee_limit(api):
    """PRD §3.3: "the application's `requested_amount_cents` plus the
    trustee's `active_endorsement_exposure_cents` must not exceed the
    trustee's `endorsement_limit_cents`, or the submission fails with
    `ERR_TRUSTEE_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_submit
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=100_000)
    borrower = create_submittable_borrower(
        accepts=3, business_tenure_months=5, prior_repaid_loans_count=0
    )
    application = create_application(
        borrower, requested_amount_cents=500_000, term_months=6
    )

    # Quota met (3 accepts); the trustee capacity rule now surfaces.
    resp = client.submit_application(
        application["id"],
        {
            "expected_application_version": application["version"],
            "trustee_id": trustee["id"],
        },
        make_borrower_headers(borrower["id"]),
    )
    validate_error(resp, ERR_TRUSTEE_LIMIT_EXCEEDED, expected_status=422)
    assert get_application(application["id"])["status"] == "DRAFT"
