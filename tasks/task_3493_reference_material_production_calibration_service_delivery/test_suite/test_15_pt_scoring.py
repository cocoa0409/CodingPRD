"""PT/KC evaluation arithmetic: z-score boundary, chi-squared boundary, DoE."""
from test_helpers import (
    make_accreditation_officer_headers, make_customer,
    setup_lot_in_distribution, setup_pt_round_open, submit_result,
    transition_round, validate_success,
)

_AO = make_accreditation_officer_headers()


def test_z_score_exactly_two_passes(api):
    """PRD §3.7: "Each submitted result's `z_score` is its `measured_value`
    minus the assigned value, divided by the reference uncertainty, stored at
    three decimal places rounded half up; its `performance_flag` is `PASS` when
    the absolute value of that stored score is at most the `Z_PASS_THRESHOLD` of
    2.0, and `FAIL` otherwise."
    PRD §2.6: "Wherever a verdict or flag is compared against a threshold, the
    comparison uses the stored, rounded value."

    Design: Corner/calculations/z_score_exactly_two_passes
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C25",
                                    variant="UNWEIGHTED_MEAN",
                                    program_overrides={"program_code": "NIST-RM-C25"})
    customer_a = make_customer(name="C25A")
    customer_b = make_customer(name="C25B")
    rnd = setup_pt_round_open(ctx["lot"]["id"], round_code="PT-C25")
    res_a = submit_result(rnd["id"], customer_a["id"], 110.0, lab_code="LAB-A")
    res_b = submit_result(rnd["id"], customer_b["id"], 110.004, lab_code="LAB-B")
    transition_round(rnd["id"], "EVALUATION")
    a = validate_success(api.get_participant_result(res_a["id"], _AO))
    b = validate_success(api.get_participant_result(res_b["id"], _AO))
    assert a["z_score"] == 2.0
    assert a["performance_flag"] == "PASS"
    assert b["z_score"] == 2.001
    assert b["performance_flag"] == "FAIL"


def test_kc_chi_squared_exactly_df_consistent(api):
    """PRD §3.7: "`consistency_verdict` is `CONSISTENT` when the stored, rounded
    chi-squared value is at most one less than the number of results, else
    `INCONSISTENT`."
    PRD §3.7: "each result weighs one divided by the square of its
    `measurement_uncertainty`, `assigned_value` is the weight-averaged mean of
    the measured values, and `reference_uncertainty` is the square root of one
    divided by the sum of the weights."

    Design: Corner/calculations/kc_chi_squared_exactly_df_consistent
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C26",
                                    program_overrides={"program_code": "NIST-RM-C26"})
    customers = [make_customer(name=n) for n in ("C26A", "C26B", "C26C")]
    rnd = setup_pt_round_open(ctx["lot"]["id"], round_code="KC-C26",
                              round_type="KEY_COMPARISON")
    for customer, value in zip(customers, (98.0, 100.0, 102.0)):
        submit_result(rnd["id"], customer["id"], value, uncertainty=2.0,
                      lab_code=f"LAB-{customer['name'][-1]}")
    evaluated = transition_round(rnd["id"], "EVALUATION")
    assert evaluated["assigned_value"] == 100.0
    assert evaluated["reference_uncertainty"] == 1.154701
    assert evaluated["chi_squared"] == 2.0
    assert evaluated["consistency_verdict"] == "CONSISTENT"
    assert evaluated["evaluated_count"] == 3


def test_kc_inconsistent_verdict_and_doe_literals(api):
    """PRD §3.7: "Each result then earns a `degree_of_equivalence` — its
    measured value minus the assigned value — and an `equivalence_uncertainty`
    of twice the square root of the sum of its own squared uncertainty and the
    squared reference uncertainty; its `performance_flag` is `PASS` when the
    absolute degree of equivalence is at most the equivalence uncertainty, and
    `FAIL` otherwise."

    Design: Corner/calculations/kc_inconsistent_verdict_and_doe_literals
    """
    ctx = setup_lot_in_distribution(total=10, material_code="SRM-C27",
                                    program_overrides={"program_code": "NIST-RM-C27"})
    customer_a = make_customer(name="C27A")
    customer_b = make_customer(name="C27B")
    rnd = setup_pt_round_open(ctx["lot"]["id"], round_code="KC-C27",
                              round_type="KEY_COMPARISON")
    res_a = submit_result(rnd["id"], customer_a["id"], 100.0, uncertainty=2.0,
                          lab_code="LAB-A")
    res_b = submit_result(rnd["id"], customer_b["id"], 104.0, uncertainty=1.0,
                          lab_code="LAB-B")
    evaluated = transition_round(rnd["id"], "EVALUATION")
    assert evaluated["assigned_value"] == 103.2
    assert evaluated["chi_squared"] == 3.2
    assert evaluated["consistency_verdict"] == "INCONSISTENT"
    a = validate_success(api.get_participant_result(res_a["id"], _AO))
    b = validate_success(api.get_participant_result(res_b["id"], _AO))
    assert a["degree_of_equivalence"] == -3.2
    assert a["equivalence_uncertainty"] == 4.38178
    assert a["performance_flag"] == "PASS"
    assert b["degree_of_equivalence"] == 0.8
    # NOTE: b's exact equivalence_uncertainty literal is intentionally not
    # asserted. PRD §2.6 pins only two rounding orders (uncertainty budget
    # combined->expanded; order unit pricing) and stored-value usage only for
    # verdict/flag comparisons; it is silent on whether the KC equivalence
    # formula consumes the stored-rounded reference_uncertainty (yields
    # 2.683281) or the exact in-flight value (yields 2.683282). Both readings
    # are PRD-faithful, so the exact 6th-decimal literal is not uniquely
    # derivable from PRD.
    assert b["performance_flag"] == "PASS"
