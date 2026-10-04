"""The four priced settlement options and the reinsurance retention waterfall."""
import pytest

from prd_bench_local_runner.testing import validate_success, get_success_data

from test_helpers import (
    api_client, setup_loan_with_approved_claim, setup_loan_with_treaty_and_approved_claim,
    settle_claim, refresh_loan, UNDERWRITER,
)


def test_an_accepted_cession_caps_at_the_aggregate_capacity_rather_than_rejecting():
    """PRD §3.10: "where the sum would exceed the cap, the per-claim ceded is
    reduced so that the sum lands exactly at the cap rather than the cession
    being refused."
    PRD §3.10: "The accepted cession's `ceded_amount_cents` is that capped
    figure, and its `retained_amount_cents` is the settlement amount less the
    ceded figure."

    Design: Difficulty/combinatorial_formula/third_party_sale_floor_then_reinsurance_retention_waterfall
    """
    book = setup_loan_with_treaty_and_approved_claim(treaty_overrides={
        "retention_per_claim_cents": 9_000_000,
        "exhaustion_per_claim_cents": 15_000_000,
        "aggregate_ceded_cap_cents": 5_000_000,
    })
    # CASH pays the whole 6098400 net; the 9000000 retention exceeds it, so the
    # per-claim ceded clamps to zero.
    claim = settle_claim(book, book["claim_id"], option="CASH")
    assert claim["settlement_amount_cents"] == 6_098_400

    cessions = get_success_data(api_client.list_cessions(
        UNDERWRITER, params={"claim_id": book["claim_id"]}))
    assert len(cessions) == 1
    assert cessions[0]["ceded_amount_cents"] == 0
    assert cessions[0]["retained_amount_cents"] == 6_098_400
    assert refresh_loan(book)["aggregate_ceded_cents"] == 0


def test_approval_prices_the_third_party_sale_option_off_the_net_claim_amount():
    """PRD §3.9: "`THIRD_PARTY_SALE` pays the net claim amount less a share of
    it, computed by multiplying the net claim amount by the policy's
    `min_third_party_net_bps` floor in basis points, dividing by ten thousand,
    discarding any fractional cent, and subtracting that from the net claim
    amount, with the result floored at zero."
    PRD §3.9: "`CASH` pays the claim's net claim amount outright."

    Design: Difficulty/combinatorial_formula/third_party_sale_floor_then_reinsurance_retention_waterfall
    """
    book = setup_loan_with_approved_claim()
    claim = get_success_data(api_client.get_claim(book["claim_id"], UNDERWRITER))
    assert claim["net_claim_amount_cents"] == 6_098_400

    options = get_success_data(api_client.list_settlement_options(
        book["claim_id"], UNDERWRITER))
    by_kind = {option["option_kind"]: option for option in options}
    assert set(by_kind) == {"CASH", "THIRD_PARTY_SALE", "DEED_IN_LIEU", "DIL"}

    # The 1500-basis-point floor is applied to the net claim amount, floored.
    expected_floor = 6_098_400 - int(6_098_400 * 1500 / 10000)
    assert by_kind["THIRD_PARTY_SALE"]["computed_amount_cents"] == expected_floor == 5_183_640
    assert by_kind["CASH"]["computed_amount_cents"] == 6_098_400


def test_third_party_sale_settlement_runs_through_the_treaty_retention_waterfall():
    """PRD §3.10: "the per-claim ceded amount is the settlement amount less the
    treaty's `retention_per_claim_cents`, confined to the range from zero up to
    the treaty's per-claim capacity."
    PRD §3.10: "An accepted cession also advances the loan's
    `aggregate_ceded_cents` by the ceded amount".

    Design: Difficulty/combinatorial_formula/third_party_sale_floor_then_reinsurance_retention_waterfall
    """
    book = setup_loan_with_treaty_and_approved_claim(treaty_overrides={
        "retention_per_claim_cents": 1_000_000,
        "exhaustion_per_claim_cents": 6_000_000,
        "aggregate_ceded_cap_cents": 5_000_000,
    })
    claim = settle_claim(book, book["claim_id"], option="THIRD_PARTY_SALE")

    assert claim["status"] == "SETTLED"
    assert claim["settlement_option_kind"] == "THIRD_PARTY_SALE"
    assert claim["settlement_amount_cents"] == 5_183_640

    cessions = get_success_data(api_client.list_cessions(
        UNDERWRITER, params={"claim_id": book["claim_id"]}))
    assert len(cessions) == 1
    cession = cessions[0]
    assert cession["status"] == "ACCEPTED"
    assert cession["ceded_amount_cents"] == 5_183_640 - 1_000_000 == 4_183_640
    assert cession["retained_amount_cents"] == 1_000_000

    loan = refresh_loan(book)
    assert loan["aggregate_ceded_cents"] == 4_183_640


def test_third_party_sale_equals_cash_when_the_policy_floor_is_zero():
    """PRD §3.9: "a policy whose floor is zero would make `THIRD_PARTY_SALE` equal
    to `CASH`."
    PRD §3.9: "`CASH` pays the claim's net claim amount outright."

    Design: Difficulty/combinatorial_formula/third_party_sale_floor_then_reinsurance_retention_waterfall
    """
    book = setup_loan_with_approved_claim(
        policy_overrides={"min_third_party_net_bps": 0})
    options = get_success_data(api_client.list_settlement_options(
        book["claim_id"], UNDERWRITER))
    by_kind = {option["option_kind"]: option for option in options}

    assert by_kind["CASH"]["computed_amount_cents"] == 6_098_400
    assert by_kind["THIRD_PARTY_SALE"]["computed_amount_cents"] == 6_098_400


def test_settlement_options_read_exposes_the_four_priced_rows():
    """PRD §3.9: "Approval prices four ways of closing a claim, and the lender
    chooses one of them at settlement. The four kinds are `CASH`,
    `THIRD_PARTY_SALE`, `DEED_IN_LIEU` and `DIL`, each carried on its own priced
    option row recording the `claim_id` it belongs to, the `option_kind`, and the
    `computed_amount_cents` the option would pay".

    Design: Corner/endpoints/settlement_options_read_exposes_the_four_priced_options_of_an_approved_claim
    """
    book = setup_loan_with_approved_claim()
    claim_id = book["claim_id"]

    options = get_success_data(api_client.list_settlement_options(claim_id, UNDERWRITER))
    assert len(options) == 4
    by_kind = {option["option_kind"]: option for option in options}

    assert by_kind["CASH"]["computed_amount_cents"] == 6_098_400
    assert by_kind["DEED_IN_LIEU"]["computed_amount_cents"] == 6_098_400
    assert by_kind["THIRD_PARTY_SALE"]["computed_amount_cents"] == 5_183_640
    # The reinstatement credit covers the balance, so DIL floors at zero here.
    assert by_kind["DIL"]["computed_amount_cents"] == 0
    for option in options:
        assert option["claim_id"] == claim_id