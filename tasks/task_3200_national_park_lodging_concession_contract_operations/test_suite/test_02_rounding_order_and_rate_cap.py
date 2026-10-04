"""The two places rounding order and multi-input interplay decide the answer.

The franchise fee statement pins per-line-then-sum as the payable order and
carries the aggregate-first figure only as a diagnostic (PRD 3.5); the rate
cap folds the study's weighted mean, the 1.05 multiplier, integer-cent
rounding and a per-band comparison into a single gate (PRD 3.2).
"""

from test_helpers import constants as C
from test_helpers.api_errors import ERR_RATE_EXCEEDS_COMPARABILITY
from test_helpers.assertions import (
    assert_cents,
    get_success_data,
    validate_error,
)
from test_helpers.fixtures import (
    accepted_report,
    active_contract,
    add_room_class,
    add_study,
    approve_filing,
    contract_version,
    issue_statement,
    read_contract,
    reset_clock,
    submit_filing,
)
from test_helpers.test_users import RATE_ANALYST, RATE_MANAGER


class TestPerLineRoundingOrder:
    """Per-line round-then-sum is payable; aggregate-first is diagnostic."""

    def _scenario(self, client):
        """Three ACCEPTED reports for 2027-07: 20000 / 15000 / 9000 cents."""
        reset_clock(client)
        contract, _season, lines = active_contract(
            client, franchise_fee_rate=0.0385
        )
        contract_id = contract["id"]
        for line_type, amount in (
            (C.LINE_LODGING, 20000),
            (C.LINE_FOOD, 15000),
            (C.LINE_RETAIL, 9000),
        ):
            accepted_report(
                client, contract_id, lines[line_type]["id"],
                gross_receipts_cents=amount,
            )
        return contract_id

    def test_payable_total_is_the_sum_of_per_line_fees(self, client):
        """PRD 3.5: "The fee math is pinned to a per-line-then-sum order: each
        line's fee is that line's gross receipts multiplied by the contract's
        `franchise_fee_rate`, rounded half-up to whole cents, and the
        statement's `total_fee_cents` is the sum of those per-line fees."

        Design: Difficulty/combinatorial_formula/franchise_fee_per_line_rounding_order
        """
        contract_id = self._scenario(client)
        statement = issue_statement(client, contract_id, "2027-07")
        # 770 + 578 + 347 = 1695; the aggregate-first figure would be 1694.
        assert_cents(statement["total_fee_cents"], 1695, "total_fee_cents")
        assert statement["reporting_method"] == C.REPORTING_METHOD_PER_LINE_ROUNDED

    def test_aggregate_first_figure_is_a_diagnostic_only(self, client):
        """PRD 3.5: "For transparency the statement also carries
        `aggregate_diagnostic_cents`, computed in the opposite order — all
        lines' gross receipts summed first, then multiplied by the fee rate
        and rounded half-up once — which may legitimately differ from the
        payable total; it is a diagnostic only and is never the amount owed."

        Design: Difficulty/combinatorial_formula/franchise_fee_per_line_rounding_order
        """
        contract_id = self._scenario(client)
        statement = issue_statement(client, contract_id, "2027-07")
        assert_cents(
            statement["aggregate_diagnostic_cents"], 1694,
            "aggregate_diagnostic_cents",
        )
        assert (
            statement["total_fee_cents"] - statement["aggregate_diagnostic_cents"]
            == 1
        ), "the two rounding orders must differ by exactly 1 cent here"


class TestWeightedMeanCapInteraction:
    """An overweighted comparable flips the approval verdict."""

    def _scenario(self, client):
        """One contract, one season/room class, and both studies."""
        reset_clock(client)
        contract, season, _lines = active_contract(client)
        contract_id = contract["id"]
        room_class = add_room_class(client, contract_id)
        study_hi = add_study(client, contract_id, title="S1")  # mean 25000
        study_lo = add_study(
            client, contract_id, title="S2",
            comparables=[
                dict(c) for c in C.STUDY_MEAN_20500_COMPARABLES
            ],
        )  # mean 20500
        return contract_id, season["id"], room_class["id"], study_hi, study_lo

    def test_rates_under_the_25000_mean_cap_are_approved(self, client):
        """PRD 3.2: "The rate cap is then enforced band by band: the cap is
        the cited study's `weighted_mean_cents` multiplied by 1.05, with the
        product rounded half-up to a whole number of cents, and every band's
        submitted nightly rate must be at most that cap — a rate exactly
        equal to the cap passes, a rate one cent above it fails with
        `ERR_RATE_EXCEEDS_COMPARABILITY`."

        Design: Difficulty/combinatorial_formula/rate_cap_three_way_nonlinear_interaction
        """
        contract_id, season_id, room_class_id, study_hi, _lo = self._scenario(client)
        assert study_hi["weighted_mean_cents"] == 25000
        filing = submit_filing(
            client, contract_id, season_id, room_class_id, study_hi["id"],
            submitted_rates=f_rates(24000, 25000, 26000),
        )
        approved = approve_filing(client, contract_id, filing["id"])
        assert approved["status"] == C.FILING_APPROVED

    def test_the_same_room_class_over_the_20500_mean_cap_is_rejected(self, client):
        """PRD 3.2: "a rate exactly equal to the cap passes, a rate one cent
        above it fails with `ERR_RATE_EXCEEDS_COMPARABILITY`."

        Design: Difficulty/combinatorial_formula/rate_cap_three_way_nonlinear_interaction
        """
        contract_id, season_id, room_class_id, _hi, study_lo = self._scenario(client)
        assert study_lo["weighted_mean_cents"] == 20500
        filing = submit_filing(
            client, contract_id, season_id, room_class_id, study_lo["id"],
            submitted_rates=f_rates(20000, 21000, 22000),
        )
        response = client.start_review_filing(
            contract_id, filing["id"], headers=RATE_ANALYST
        )
        assert get_success_data(response)["status"] == C.FILING_UNDER_REVIEW
        # cap = 21525; the FAMILY band at 22000 exceeds it.
        response = client.approve_filing(
            contract_id, filing["id"], headers=RATE_ANALYST
        )
        validate_error(response, ERR_RATE_EXCEEDS_COMPARABILITY)


class TestWeightedMeanFormula:
    """The division happens before the integer-cent rounding."""

    def test_weighted_mean_of_known_inputs_is_exactly_20500(self, client):
        """PRD 3.2: "each comparable's nightly rate is multiplied by its
        weight, the products are summed, the sum of the weights is taken, the
        first sum is divided by the second, and the quotient is rounded
        half-up to a whole number of cents."

        Design: Corner/calculations/comparability_weighted_mean_rounds_half_up
        """
        reset_clock(client)
        contract = active_contract(client)[0]
        study = add_study(
            client, contract["id"], title="W",
            comparables=[dict(c) for c in C.STUDY_MEAN_20500_COMPARABLES],
        )
        # (20000*1 + 22000*2 + 18000*1) / 4 = 82000/4 = 20500 exactly.
        assert_cents(study["weighted_mean_cents"], 20500, "weighted_mean_cents")
        assert study["status"] == C.STUDY_REGISTERED


def f_rates(solo, double, family):
    from test_helpers import factories as f
    return f.band_rates_payload(solo=solo, double=double, family=family)
