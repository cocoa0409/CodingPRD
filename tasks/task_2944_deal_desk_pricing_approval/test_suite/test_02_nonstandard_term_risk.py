"""Non-standard term severity ramps and the two quote-level risk measures."""
import pytest

from test_helpers import (
    add_term,
    assert_nonstandard_term,
    list_terms,
    read_quote,
    setup_single_line_quote,
)


def _terms_by_category(api, quote_id):
    return {term["term_category"]: term for term in list_terms(api, quote_id)}


def test_each_term_category_uses_its_own_severity_ramp_and_weight(api, base):
    """PRD §3.4: "A payment-terms deviation is weighted at 20; the other four categories
    — service level commitments, indemnity caps, termination for convenience and
    price-hold renewals — are each weighted at 30."
    PRD §3.4: "For `TERMINATION_FOR_CONVENIENCE`, severity runs the other way — shorter
    notice is worse — ramping from zero at 12 months of notice to one at zero notice,
    that is, 12 less the requested months, divided by 12."
    PRD §3.4: "The term's `risk_contribution` is its category weight multiplied by its
    `severity_factor`, rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/nonstandard_term_risk_aggregate_weighted_vs_dominant_category_legal
    """
    quote, _ = setup_single_line_quote(
        api,
        base,
        "support",
        10,
        0.00,
        term_months=24,
        title="Northwind Support Renewal",
        payment_terms_days=90,
        billing_frequency="ANNUAL",
    )
    add_term(api, quote["id"], "PAYMENT_TERMS", 90, requested_text="Net 90 payment terms")
    add_term(
        api, quote["id"], "INDEMNITY_CAP", 3, requested_text="Indemnity capped at 3x annual fees"
    )
    triggered = add_term(
        api,
        quote["id"],
        "TERMINATION_FOR_CONVENIENCE",
        3,
        requested_text="Termination for convenience on 3 months notice",
    )
    assert_nonstandard_term(triggered)
    assert triggered["review_state"] == "PENDING"

    terms = _terms_by_category(api, quote["id"])
    pay = terms["PAYMENT_TERMS"]
    indemnity = terms["INDEMNITY_CAP"]
    termination = terms["TERMINATION_FOR_CONVENIENCE"]

    assert pay["severity_factor"] == pytest.approx(0.500000, abs=1e-9), "(90 - 30) / 120"
    assert pay["risk_contribution"] == pytest.approx(10.00, abs=1e-9), "weight 20 x 0.5"
    assert indemnity["severity_factor"] == pytest.approx(0.500000, abs=1e-9), "3 / 6"
    assert indemnity["risk_contribution"] == pytest.approx(15.00, abs=1e-9), "weight 30 x 0.5"
    assert termination["severity_factor"] == pytest.approx(0.750000, abs=1e-9), "(12 - 3) / 12"
    assert termination["risk_contribution"] == pytest.approx(22.50, abs=1e-9), "weight 30 x 0.75"


def test_aggregate_sums_the_terms_while_dominant_amplifies_the_largest(api, base):
    """PRD §3.4: "The **aggregate** measure, stored as `terms_risk_score_aggregate`, sums
    the already-rounded `risk_contribution` values across that input set, rounds the sum
    half up to two decimal places, and caps the result at 100."
    PRD §3.4: "it takes the single term with the highest `risk_contribution`, breaking
    ties by earlier `created_at`, multiplies that one contribution by 1.25, rounds half up
    to two decimal places, and caps the result at 100."
    PRD §3.4: "A CFO co-signature is mandatory exactly when `terms_risk_score_dominant` is
    at or above the pinned revision's `terms_cfo_risk_threshold`, and the obligation
    attaches to a single term: `requires_cfo_cosign` is set true on the dominant term
    only, and stays false on every other term of the quote."

    Design: Difficulty/dual_variant_calc/nonstandard_term_risk_aggregate_weighted_vs_dominant_category_legal
    """
    quote, _ = setup_single_line_quote(
        api,
        base,
        "support",
        10,
        0.00,
        term_months=24,
        title="Northwind Support Renewal",
        payment_terms_days=90,
        billing_frequency="ANNUAL",
    )
    add_term(api, quote["id"], "PAYMENT_TERMS", 90, requested_text="Net 90 payment terms")
    add_term(
        api, quote["id"], "INDEMNITY_CAP", 3, requested_text="Indemnity capped at 3x annual fees"
    )
    add_term(
        api,
        quote["id"],
        "TERMINATION_FOR_CONVENIENCE",
        3,
        requested_text="Termination for convenience on 3 months notice",
    )

    quote = read_quote(api, quote["id"])
    assert quote["terms_risk_score_aggregate"] == pytest.approx(47.50, abs=1e-9), (
        "10.00 + 15.00 + 22.50"
    )
    assert quote["terms_risk_score_dominant"] == pytest.approx(28.13, abs=1e-9), (
        "22.50 x 1.25 rounded half up to two places"
    )

    for term in list_terms(api, quote["id"]):
        assert term["requires_cfo_cosign"] is False, (
            "the dominant score sits below the CFO co-signature threshold"
        )
