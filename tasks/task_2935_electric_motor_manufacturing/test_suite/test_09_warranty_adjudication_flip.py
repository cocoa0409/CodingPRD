"""One claim, two analysis bases, and the credit waterfall between them."""

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers.fixtures import build_plant

ANALYSIS_CLOCK = F.instant("2027-02-05", 0, 0)
HARD_RUN_CLAIM = {
    "measured_load_pct": 128.0,
    "measured_ambient_c": 55.0,
    "measured_voltage_unbalance_pct": 2.8,
    "measured_starts_per_hour": 10,
    "claimed_parts_cents": 140000,
    "claimed_labor_cents": 60000,
    "claimed_freight_cents": 20000,
}
DESIGN = F.motor_design_payload()
ROLLUP = A.expected_cost_rollup(DESIGN, 12)
UNIT_STANDARD_COST_CENTS = ROLLUP["unit_standard_cost_cents"]
WATERFALL = A.expected_warranty_credit_cents(
    UNIT_STANDARD_COST_CENTS,
    HARD_RUN_CLAIM["claimed_parts_cents"],
    HARD_RUN_CLAIM["claimed_labor_cents"],
    HARD_RUN_CLAIM["claimed_freight_cents"],
    6,
)


def _claim_six_months_into_service(api):
    """A shipped motor whose claim is analysed six whole months after despatch."""
    plant = build_plant(api, "shipped")
    work_order = plant.get_work_order()
    assert work_order["standard_cost_cents"] == ROLLUP["standard_cost_cents"]
    assert work_order["shipped_at"] == F.RECORD_CLOCK
    plant.set_clock(ANALYSIS_CLOCK)
    claim = plant.file_claim(**HARD_RUN_CLAIM)
    assert claim["status"] == "SUBMITTED"
    assert claim["reported_at"] == ANALYSIS_CLOCK
    assert claim["dispute_round"] == 0
    assert claim["defect_presumption_applied"] is False
    assert (
        A.service_age_months(A.date_of(F.RECORD_CLOCK), A.date_of(ANALYSIS_CLOCK)) == 6
    )
    return plant, claim


def test_the_field_data_basis_reads_the_hard_run_application_as_misuse(api):
    """The four sub-scores alone weigh 0.6460, above the 0.50 threshold.

    PRD 3.10: "On the **`FIELD_DATA`** basis the index is the weighted sum of the
    four application sub-scores alone, with weights 0.34 on overload, 0.26 on
    thermal, 0.22 on voltage and 0.18 on starts — a total of 1.00."

    Design: Difficulty/dual_variant_calc/warranty_field_data_vs_teardown_adjudication_flip
    """
    plant, _claim = _claim_six_months_into_service(api)

    adjudicated = plant.analyze_claim(F.analyze_field_data_payload())

    assert adjudicated["misuse_index"] == 0.6460
    A.assert_rounded_to(
        adjudicated["misuse_index"],
        A.expected_misuse_index(
            F.warranty_claim_payload("w", "d", **HARD_RUN_CLAIM), "S1", "FIELD_DATA"
        ),
        4,
        "misuse_index",
    )
    assert adjudicated["adjudication"] == "MISUSE_DETERMINED"
    assert adjudicated["status"] == "MISUSE_DETERMINED"
    assert adjudicated["analysis_basis"] == "FIELD_DATA"
    assert adjudicated["teardown_defect_evidence_pct"] is None
    assert adjudicated["warranty_credit_cents"] == 0
    assert adjudicated["credit_posted"] is False
    assert plant.get_distributor()["warranty_credit_balance_cents"] == 0


def test_the_teardown_basis_flips_the_same_claim_to_a_confirmed_defect(api):
    """Ninety percent defect evidence pulls the identical inputs down to 0.4367.

    PRD 3.10: "On the **`TEARDOWN`** basis the same four sub-scores are carried at
    reduced weights — 0.20 on overload, 0.18 on thermal, 0.14 on voltage and 0.10
    on starts, a total of 0.62 — and a fifth term at weight 0.38 is added, equal to
    one minus `teardown_defect_evidence_pct` divided by 100."

    Design: Difficulty/dual_variant_calc/warranty_field_data_vs_teardown_adjudication_flip
    """
    plant, _claim = _claim_six_months_into_service(api)
    on_field_data = plant.analyze_claim(F.analyze_field_data_payload())
    assert on_field_data["adjudication"] == "MISUSE_DETERMINED"
    plant.dispute_claim()

    on_teardown = plant.analyze_claim(F.analyze_teardown_payload(90.0))

    assert on_teardown["misuse_index"] == 0.4367
    assert on_teardown["misuse_index"] != on_field_data["misuse_index"]
    A.assert_rounded_to(
        on_teardown["misuse_index"],
        A.expected_misuse_index(
            F.warranty_claim_payload("w", "d", **HARD_RUN_CLAIM), "S1", "TEARDOWN", 90.0
        ),
        4,
        "misuse_index",
    )
    assert on_teardown["adjudication"] == "DEFECT_CONFIRMED"
    assert on_teardown["status"] == "DEFECT_CONFIRMED"
    assert on_teardown["analysis_basis"] == "TEARDOWN"
    assert on_teardown["teardown_defect_evidence_pct"] == 90.0
    assert on_teardown["credit_posted"] is True


def test_the_confirmed_defect_settles_through_the_pro_rata_waterfall(api):
    """195976 cents at 0.85 and a 0.9 pro-rata ceiling grants 117586 plus 32336.

    PRD 3.10: "The parts grant is the least of `claimed_parts_cents`, 0.60 of
    `claim_unit_standard_cost_cents` rounded to whole cents, and the remaining
    ceiling."

    Design: Difficulty/dual_variant_calc/warranty_field_data_vs_teardown_adjudication_flip
    """
    plant, _claim = _claim_six_months_into_service(api)
    plant.analyze_claim(F.analyze_field_data_payload())
    plant.dispute_claim()

    settled = plant.analyze_claim(F.analyze_teardown_payload(90.0))

    assert settled["claim_unit_standard_cost_cents"] == 195976
    assert settled["claim_unit_standard_cost_cents"] == UNIT_STANDARD_COST_CENTS
    assert WATERFALL["ceiling_cents"] == 149922
    assert WATERFALL["parts_cents"] == 117586
    assert WATERFALL["labor_cents"] == 32336
    assert WATERFALL["freight_cents"] == 0
    assert settled["warranty_credit_cents"] == 149922
    assert settled["warranty_credit_cents"] == WATERFALL["warranty_credit_cents"]
    assert settled["credit_posted"] is True
    assert plant.get_distributor()["warranty_credit_balance_cents"] == 149922


def test_disputing_reverses_the_posted_credit_without_drift(api):
    """The compensating half returns the claim to UNDER_ANALYSIS and the balance to 0.

    PRD 3.10: "A dispute raises `dispute_round` by 1 and performs the compensating
    half of the credit invariant: `credit_posted` is cleared,
    `warranty_credit_cents` is set to 0, and `adjudication` and `misuse_index` are
    both cleared back to unset."

    Design: Difficulty/dual_variant_calc/warranty_field_data_vs_teardown_adjudication_flip
    """
    plant, _claim = _claim_six_months_into_service(api)
    plant.analyze_claim(F.analyze_teardown_payload(90.0))
    assert plant.get_distributor()["warranty_credit_balance_cents"] == 149922

    disputed = plant.dispute_claim()

    assert disputed["status"] == "UNDER_ANALYSIS"
    assert disputed["dispute_round"] == 1
    assert disputed["misuse_index"] is None
    assert disputed["adjudication"] is None
    assert disputed["warranty_credit_cents"] == 0
    assert disputed["credit_posted"] is False
    assert plant.get_distributor()["warranty_credit_balance_cents"] == 0
    reanalysed = plant.analyze_claim(F.analyze_teardown_payload(90.0))
    assert reanalysed["warranty_credit_cents"] == 149922
    assert plant.get_distributor()["warranty_credit_balance_cents"] == 149922
