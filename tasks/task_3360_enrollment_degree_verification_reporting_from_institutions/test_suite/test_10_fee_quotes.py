"""Fee quotes: pinned rounding order, volume tier, quarter boundaries."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error,
    advance_clock, setup_student_with_file, setup_sealed_degree,
    setup_vetted_requester, create_degree_request, pay_request,
    fulfill_request, release_n_degree_requests, get_requester_balance,
    create_verification_request_payload, make_requester_headers,
)

OPS = TEST_USERS["ops_headers"]


def _degree_verifiable_scene(api):
    """Compliant institution, one student with a SEALED degree, at
    2026-11-15T00:00:00Z (Q4 2026)."""
    ctx = setup_student_with_file()
    setup_sealed_degree(ctx, ctx["student_id"])
    return ctx


def _preferred_tier_scene(api):
    """Three DEGREE releases in Q4 2026, then the clock at 03:00 so all
    three are strictly before the next quote."""
    ctx = _degree_verifiable_scene(api)
    rq = setup_vetted_requester(credit=50000)
    release_n_degree_requests(ctx, rq["id"], 3)
    advance_clock("2026-11-15T03:00:00Z")
    ctx["requester_id"] = rq["id"]
    return ctx


def test_preferred_rush_degree_fee_pinned_rounding(api):
    """PRD section 3.7: "A `PREFERRED` tier earns a discount of 2000 basis
    points off the base; `STANDARD` earns none. Step one rounds first: the
    discounted base is the base multiplied by the ten-thousandths remaining
    after the discount and divided by ten thousand, rounded half-up to
    integer cents. Step two computes the rush component on that rounded
    discounted base: when `rush` is true, a surcharge of 3333 basis points
    of the rounded discounted base, itself rounded half-up to integer cents;
    when `rush` is false, zero. Step three sums: `fee_cents` is the
    discounted base plus the rush component, a sum of two already-rounded
    components."

    Design: Difficulty/combinatorial_formula/verification_fee_rounding_order_pinned
    """
    ctx = _preferred_tier_scene(api)
    r4 = create_degree_request(
        ctx["inst_id"], ctx["student_id"], ctx["requester_id"], rush=True,
    )
    assert r4["volume_tier_at_quote"] == "PREFERRED", (
        "three prior RELEASED requests in Q4 2026 meet the threshold"
    )
    # round_half_up(2599 * 0.8) = 2079; round_half_up(2079 * 0.3333) = 693.
    assert r4["fee_cents"] == 2772, (
        "sum of rounded components; the forbidden sum-then-round order "
        "would give 2771"
    )


def test_preferred_rush_degree_debits_pinned_fee(api):
    """PRD section 3.7: "Payment debits `fee_cents` from the balance, stamps
    `paid_at`, and moves the request `QUOTED` → `PAID`."
    PRD section 3.7: "The base fee is 2599 cents for `DEGREE`".

    Design: Difficulty/combinatorial_formula/verification_fee_rounding_order_pinned
    """
    ctx = _preferred_tier_scene(api)
    r4 = create_degree_request(
        ctx["inst_id"], ctx["student_id"], ctx["requester_id"], rush=True,
    )
    pay_request(r4["id"], ctx["requester_id"])
    assert get_requester_balance(ctx["requester_id"]) == 39431, (
        "50000 - 3*2599 - 2772"
    )


def test_third_request_quotes_standard(api):
    """PRD section 3.7: "The requester's volume tier at quote time, recorded
    as `volume_tier_at_quote`, is `PREFERRED` when the requester already has
    at least three requests in `RELEASED` status whose `released_at` falls
    inside the current calendar quarter — January through March, April
    through June, July through September, or October through December — and
    strictly before the current instant, with the request being quoted never
    counting itself; otherwise the tier is `STANDARD`."

    Design: Difficulty/combinatorial_formula/volume_tier_self_exclusion_at_quote
    """
    ctx = _degree_verifiable_scene(api)
    rq = setup_vetted_requester(credit=50000)
    release_n_degree_requests(ctx, rq["id"], 2)
    advance_clock("2026-11-15T02:00:00Z")
    r3 = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    assert r3["volume_tier_at_quote"] == "STANDARD", (
        "only two releases are strictly before this quote"
    )
    assert r3["fee_cents"] == 2599


def test_fourth_request_quotes_preferred(api):
    """PRD section 3.7: "The requester's volume tier at quote time, recorded
    as `volume_tier_at_quote`, is `PREFERRED` when the requester already has
    at least three requests in `RELEASED` status whose `released_at` falls
    inside the current calendar quarter — January through March, April
    through June, July through September, or October through December — and
    strictly before the current instant, with the request being quoted never
    counting itself; otherwise the tier is `STANDARD`."

    Design: Difficulty/combinatorial_formula/volume_tier_self_exclusion_at_quote
    """
    ctx = _degree_verifiable_scene(api)
    rq = setup_vetted_requester(credit=50000)
    release_n_degree_requests(ctx, rq["id"], 2)
    advance_clock("2026-11-15T02:00:00Z")
    r3 = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    pay_request(r3["id"], rq["id"])
    fulfill_request(r3["id"])
    advance_clock("2026-11-15T03:00:00Z")
    r4 = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    assert r4["volume_tier_at_quote"] == "PREFERRED", (
        "the third release landed strictly before this quote"
    )
    assert r4["fee_cents"] == 2079, "round_half_up(2599 * 0.8), no rush"


def test_volume_tier_resets_at_quarter_boundary(api):
    """PRD section 3.7: "is `PREFERRED` when the requester already has at
    least three requests in `RELEASED` status whose `released_at` falls
    inside the current calendar quarter — January through March, April
    through June, July through September, or October through December".

    Design: Corner/calculations/volume_tier_resets_at_quarter_boundary
    """
    ctx = _degree_verifiable_scene(api)
    rq = setup_vetted_requester(credit=100000)
    release_n_degree_requests(ctx, rq["id"], 3)
    advance_clock("2027-01-10T00:00:00Z")
    r4 = create_degree_request(ctx["inst_id"], ctx["student_id"], rq["id"])
    assert r4["volume_tier_at_quote"] == "STANDARD", (
        "Q4 2026 releases are outside Q1 2027; the in-quarter count is zero"
    )
    assert r4["fee_cents"] == 2599


def test_enrollment_rush_fee_standard_tier(api):
    """PRD section 3.7: "The base fee is 2599 cents for `DEGREE`, 1599 cents
    for `ENROLLMENT`, and 0 cents for `TRANSCRIPT`."
    PRD section 3.7: "Step two computes the rush component on that rounded
    discounted base: when `rush` is true, a surcharge of 3333 basis points
    of the rounded discounted base, itself rounded half-up to integer cents".

    Design: Corner/calculations/enrollment_rush_fee_standard_tier
    """
    ctx = setup_student_with_file(
        advance_to=None, term_label="Early Fall 2026", term_start="2026-08-01",
        submission_opens_at="2026-08-15",
    )
    rq = setup_vetted_requester(credit=100000)
    payload = create_verification_request_payload(
        ctx["student_id"], ctx["inst_id"],
        requester_id=rq["id"], product_type="ENROLLMENT",
        purpose="INSURANCE", rush=True,
    )
    resp = api_client.create_verification_request(
        payload, make_requester_headers(rq["id"]),
    )
    req = validate_success(resp, 201)
    assert req["volume_tier_at_quote"] == "STANDARD"
    # 1599 + round_half_up(1599 * 0.3333) = 1599 + 533.
    assert req["fee_cents"] == 2132


def test_consent_exempt_paths_pass(api):
    """PRD section 3.7: "`ENROLLMENT` checks for `LOAN_DEFERMENT` or
    `INSURANCE` purposes are consent-exempt, and a `DEGREE` request without
    a block on file is likewise consent-exempt."
    PRD section 3.7: "The base fee is 2599 cents for `DEGREE`, 1599 cents
    for `ENROLLMENT`, and 0 cents for `TRANSCRIPT`."

    Design: Corner/validations/consent_exempt_paths_pass
    """
    ctx = setup_student_with_file(
        advance_to=None, term_label="Early Fall 2026", term_start="2026-08-01",
        submission_opens_at="2026-08-15",
    )
    rq = setup_vetted_requester(credit=100000)
    insurance = create_degree_request(
        ctx["inst_id"], ctx["student_id"], rq["id"],
    )
    enrollment_resp = api_client.create_verification_request(
        create_verification_request_payload(
            ctx["student_id"], ctx["inst_id"],
            requester_id=rq["id"], product_type="ENROLLMENT",
            purpose="INSURANCE",
        ),
        make_requester_headers(rq["id"]),
    )
    enrollment = validate_success(enrollment_resp, 201)
    assert enrollment["status"] == "QUOTED"
    assert enrollment["fee_cents"] == 1599
    assert insurance["status"] == "QUOTED"
    assert insurance["fee_cents"] == 2599
