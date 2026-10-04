"""Difficulty queue: WEIGHTED_MEAN vs UNWEIGHTED_MEAN certified values."""
from test_helpers import (
    create_draft_certificate, make_program, setup_value_assignment_lot,
)


def _two_lots_with_accepted_methods():
    """Two identical lots in VALUE_ASSIGNMENT, each with the same two ACCEPTED
    methods (mean 100.0 u 2.0 by met-1; mean 104.0 u 1.0 by met-2)."""
    program = make_program(program_code="NIST-RM-01")
    lots = {}
    for key, code in (("a", "SRM-A"), ("b", "SRM-B")):
        ctx = setup_value_assignment_lot(program=program, total=20, material_code=code)
        lots[key] = ctx["lot"]
    return lots


def test_weighted_mean_certified_value_and_uncertainty(api):
    """PRD §3.4: "Under `WEIGHTED_MEAN`, each accepted method carries a weight
    of one divided by the square of its `method_std_uncertainty`;
    `certified_value` is the sum of each `method_mean` multiplied by its weight,
    divided by the sum of the weights, and `characterization_uncertainty` is the
    square root of one divided by the sum of the weights".
    PRD §2.6: "the combined standard uncertainty is rounded to six decimal
    places before it is doubled into the expanded uncertainty; doubling the
    unrounded value is forbidden."

    Design: Difficulty/dual_variant_calc/weighted_vs_unweighted_certified_value
    """
    lots = _two_lots_with_accepted_methods()
    cert_a = create_draft_certificate(
        lots["a"]["id"], certificate_code="CERT-A",
        value_assignment_variant="WEIGHTED_MEAN",
        uncertainty_components=[{"label": "stability", "std_uncertainty": 0.5}],
        validity_days=30)
    cert_b = create_draft_certificate(
        lots["b"]["id"], certificate_code="CERT-B",
        value_assignment_variant="UNWEIGHTED_MEAN",
        uncertainty_components=[], validity_days=30)
    assert cert_a["certified_value"] == 103.2
    assert cert_a["characterization_uncertainty"] == 0.894427
    assert cert_a["combined_standard_uncertainty"] == 1.024695
    assert cert_a["expanded_uncertainty"] == 2.04939
    assert cert_a["certified_value"] != cert_b["certified_value"]


def test_unweighted_mean_certified_value_and_uncertainty(api):
    """PRD §3.4: "Under `UNWEIGHTED_MEAN`, `certified_value` is the plain
    average of the accepted method means, and `characterization_uncertainty` is
    the standard error of that mean".
    PRD §3.4: "`combined_standard_uncertainty` is the square root of the sum of
    the square of `characterization_uncertainty`, the square of the lot's
    `homogeneity_u_hom`, and the squares of every component `std_uncertainty`."

    Design: Difficulty/dual_variant_calc/weighted_vs_unweighted_certified_value
    """
    lots = _two_lots_with_accepted_methods()
    cert_a = create_draft_certificate(
        lots["a"]["id"], certificate_code="CERT-A",
        value_assignment_variant="WEIGHTED_MEAN",
        uncertainty_components=[{"label": "stability", "std_uncertainty": 0.5}],
        validity_days=30)
    cert_b = create_draft_certificate(
        lots["b"]["id"], certificate_code="CERT-B",
        value_assignment_variant="UNWEIGHTED_MEAN",
        uncertainty_components=[], validity_days=30)
    assert cert_b["certified_value"] == 102.0
    assert cert_b["characterization_uncertainty"] == 2.0
    assert cert_b["combined_standard_uncertainty"] == 2.0
    assert cert_b["expanded_uncertainty"] == 4.0
    assert cert_b["certified_value"] != cert_a["certified_value"]
