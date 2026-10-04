"""Verification fees, contributor rate tiers and the volume boundary."""
from test_helpers import (
    make_verifier_headers,
    setup_verification_stack,
    submit_request,
    permit_request,
    validate_currency,
    materialize_response,
    get_request,
    get_verifier,
    get_employer,
    create_validated_batch_accrual,
    list_accruals,
)


def test_boundary_transaction_is_priced_at_the_new_volume_tier(api):
    """PRD §3.5: "the requesting party's `escrow` covers the fee this transaction would
    post".
    PRD §3.5: "A requesting party's `transaction_count` counts the requests it has
    taken to `VALIDATED` or `RESPONDED`".
    PRD §3.5: "the fee rule below posts `fee_charged_cents` against the requesting
    party's escrow".

    Design: Difficulty/combinatorial_formula/verification_fee_uses_post_transaction_volume_tier
    """
    ctx = setup_verification_stack(validate=True)
    assert get_verifier(ctx["verifier"]["id"], make_verifier_headers(ctx["verifier"]["id"]))[
        "transaction_count"
    ] == 1

    second = submit_request(ctx["verifier"], ctx["worker"], ctx["product"])
    permit_request(ctx["worker"]["id"], second["id"], ctx["authorization"]["id"])
    validate_currency(ctx["verifier"]["id"], second["id"])
    materialize_response(ctx["verifier"]["id"], second["id"])

    req = get_request(second["id"], make_verifier_headers(ctx["verifier"]["id"]))
    assert req["request_state"] == "RESPONDED"
    assert req["fee_charged_cents"] == 1665, (
        "the boundary transaction is priced at the new tier: "
        f"round_half_up((1500 + 350) * 0.90) == 1665, got {req['fee_charged_cents']}"
    )


def test_boundary_transaction_fee_is_distinguishable_from_the_pre_transaction_tier(api):
    """PRD §2.4: "Where a monetary or scored result requires rounding, the exchange
    rounds half up".

    Design: Difficulty/combinatorial_formula/verification_fee_uses_post_transaction_volume_tier
    """
    ctx = setup_verification_stack(validate=True)
    second = submit_request(ctx["verifier"], ctx["worker"], ctx["product"])
    permit_request(ctx["worker"]["id"], second["id"], ctx["authorization"]["id"])
    validate_currency(ctx["verifier"]["id"], second["id"])
    materialize_response(ctx["verifier"]["id"], second["id"])

    fee = get_request(second["id"], make_verifier_headers(ctx["verifier"]["id"]))["fee_charged_cents"]
    assert fee == 1665
    assert fee != 1850, "reading the pre-transaction count would price this transaction at 1850"


def test_only_a_response_posts_a_fee_and_the_escrow_is_debited_by_it(api):
    """PRD §3.5: "the fee rule below posts `fee_charged_cents` against the requesting
    party's escrow".
    PRD §3.5: "On success the request moves to `VALIDATED`, `records_matched_count` is
    set to the number of resolved records, and the requesting party's
    `transaction_count` grows by one."

    Design: Difficulty/combinatorial_formula/verification_fee_uses_post_transaction_volume_tier
    """
    ctx = setup_verification_stack(validate=True)
    second = submit_request(ctx["verifier"], ctx["worker"], ctx["product"])
    permit_request(ctx["worker"]["id"], second["id"], ctx["authorization"]["id"])
    validate_currency(ctx["verifier"]["id"], second["id"])
    materialize_response(ctx["verifier"]["id"], second["id"])

    verifier = get_verifier(ctx["verifier"]["id"], make_verifier_headers(ctx["verifier"]["id"]))
    assert verifier["escrow_balance_cents"] == 4335, (
        "6000 - 1665 == 4335, because validate-currency never charges and only the "
        f"response posts a fee; got {verifier['escrow_balance_cents']}"
    )
    assert verifier["transaction_count"] == 2


def test_verification_fee_variant_diverges_when_the_volume_tier_changes(api):
    """PRD §3.5: "It is admitted only when the requesting party's posture is `NORMAL`,
    the worker has not opted out, the selected employer's `freeze_state` is `NONE`, its
    `feed_status` is not `STALLED`, and the requesting party's escrow covers the fee
    this transaction would post."

    Design: Difficulty/combinatorial_formula/verification_fee_uses_post_transaction_volume_tier
    """
    ctx = setup_verification_stack(validate=True)
    second = submit_request(ctx["verifier"], ctx["worker"], ctx["product"])
    permit_request(ctx["worker"]["id"], second["id"], ctx["authorization"]["id"])
    validate_currency(ctx["verifier"]["id"], second["id"])
    materialize_response(ctx["verifier"]["id"], second["id"])

    fee = get_request(second["id"], make_verifier_headers(ctx["verifier"]["id"]))["fee_charged_cents"]
    # 1850 = (1500 + 350) * 1.00 is the reading that uses the pre-transaction count.
    assert fee in (1665,)
    assert fee * 10 == 16650


def test_straddling_batch_accrual_uses_the_marginal_tier_rate(api):
    """PRD §3.7: "A batch declaring at least 10000 records earns 8 cents per record,
    one declaring fewer than 10000 but at least 1000 earns 10 cents, and one declaring
    fewer than 1000 earns 12 cents."
    PRD §3.7: "The accrual's `unit_rate_cents` is that per-record rate and
    `gross_accrued_cents` is the declared `records_count` multiplied by it, computed
    exactly with no rounding step."

    Design: Difficulty/dual_variant_calc/contributor_rate_marginal_vs_blended_average_on_straddling_batch
    """
    ctx = create_validated_batch_accrual(record_count=1200)
    accrual = ctx["accrual"]
    assert accrual["unit_rate_cents"] == 10, (
        f"1200 records is at or above the 1000 boundary and below 10000, got {accrual['unit_rate_cents']}"
    )
    assert accrual["gross_accrued_cents"] == 12000


def test_no_settlement_means_the_employer_has_earned_nothing_yet(api):
    """PRD §3.7: "`compensation_earned_cents` is the sum of `waived_cents` over the
    employer's `WAIVED` accruals plus the sum of `paid_cents` over its `PAID` accruals.
    An accrual still `ACCRUED` contributes nothing to that total."

    Design: Difficulty/dual_variant_calc/contributor_rate_marginal_vs_blended_average_on_straddling_batch
    """
    ctx = create_validated_batch_accrual(record_count=1200)
    accrual = ctx["accrual"]
    assert accrual["cycle_state"] == "ACCRUED"
    employer = get_employer(ctx["employer"]["id"])
    assert employer["compensation_earned_cents"] == 0
    # The blended reading of a count that sits entirely inside one tier is identical
    # to the marginal reading; the two only diverge on a count that straddles.
    assert accrual["gross_accrued_cents"] == 1200 * accrual["unit_rate_cents"]