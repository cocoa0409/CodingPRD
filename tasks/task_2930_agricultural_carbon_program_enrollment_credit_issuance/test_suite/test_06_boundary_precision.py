"""Thresholds tested at the exact value and one decimal step past it.

The additionality ceiling and the quality-control floor are both inclusive and both
compared after the figure has been rounded to two decimals, so each is probed at the
boundary itself and at the nearest value on the wrong side of it.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import (
    ERR_ADDITIONALITY_FAILED,
    ERR_INSUFFICIENT_PRACTICE_HISTORY,
    ERR_QC_SCORE_BELOW_THRESHOLD,
)
from test_helpers.assertions import assert_pct
from test_helpers.constants import (
    COMPLETENESS_PARTIAL,
    ENROLLMENT_DRAFT,
    ENROLLMENT_SCREENING,
    EVIDENCE_EQUIPMENT_TELEMETRY,
    EVIDENCE_FARM_RECORD,
    EVIDENCE_REMOTE_SENSING,
    QC_PASSED,
    QC_PENDING,
)
from test_helpers.test_users import ADMIN_HEADERS

EAST_FIELD = {
    "field_name": "Line East",
    "boundary_min_x": 2000,
    "boundary_max_x": 4000,
    "gross_acres": 1010.00,
    "county_code": "IN-063",
}


def _history_at(scenario, field_id, adopted_farm_acres):
    """The reference evidence base with the 2021 farm-record row set to a chosen acreage."""
    scenario.file_history(2021, field_id, adopted=True, evidence_source=EVIDENCE_FARM_RECORD,
                         acres=adopted_farm_acres, observed_emissions_per_acre=0.1000)
    scenario.file_history(2022, field_id, adopted=True, evidence_source=EVIDENCE_REMOTE_SENSING,
                         acres=1000.00, observed_emissions_per_acre=0.1200)
    scenario.file_history(2023, field_id, adopted=False, evidence_source=EVIDENCE_FARM_RECORD,
                         acres=0.00, observed_emissions_per_acre=0.1400)
    scenario.file_history(2024, field_id, adopted=False,
                         evidence_source=EVIDENCE_EQUIPMENT_TELEMETRY,
                         acres=0.00, observed_emissions_per_acre=0.1600)
    scenario.file_history(2025, field_id, adopted=False, evidence_source=EVIDENCE_FARM_RECORD,
                         acres=0.00, observed_emissions_per_acre=0.1800)


def test_prior_adoption_exactly_at_the_ceiling_is_admitted(scenario):
    """Weighted adoption of exactly 20.00 per cent clears the ceiling and screens with a
    score of 80.00.

    PRD §3.2: "- `max_prior_adoption_pct`, between 0 and 100 at two decimal places, is the
    **inclusive** ceiling on weighted prior adoption above which the practice is judged
    business-as-usual."

    Design: Difficulty/boundary_precision_check/additionality_ceiling_inclusive_at_20_00_and_rejected_at_20_10
    """
    scenario.set_clock()
    scenario.publish_standard()
    scenario.create_grower()
    scenario.mapped_field(field_name="Line West", county_code="IN-063")
    _history_at(scenario, scenario.field_id, 200.00)
    scenario.create_enrollment()

    enrollment = scenario.submit_enrollment()

    assert_pct(enrollment["prior_adoption_pct"], 20.00)
    assert enrollment["documented_years"] == 5
    assert_pct(enrollment["additionality_score"], 80.00)
    assert enrollment["status"] == ENROLLMENT_SCREENING


def test_prior_adoption_one_decimal_step_past_the_ceiling_is_refused(scenario):
    """Five more evidence-weighted acres put the same field at 20.10 per cent, which the
    second additionality gate refuses while the enrollment stays in draft.

    PRD §2.10: "**Additionality gates**, evaluated as a two-step cascade: first that
    `documented_years` is at least the standard's `min_documented_years`, then that
    `prior_adoption_pct` is not greater than the standard's `max_prior_adoption_pct` →
    `ERR_INSUFFICIENT_PRACTICE_HISTORY` or `ERR_ADDITIONALITY_FAILED` respectively (both
    422)."

    Design: Difficulty/boundary_precision_check/additionality_ceiling_inclusive_at_20_00_and_rejected_at_20_10
    """
    scenario.set_clock()
    scenario.publish_standard()
    scenario.create_grower()
    scenario.mapped_field(field_name="Line West", county_code="IN-063")
    _history_at(scenario, scenario.field_id, 200.00)
    east = scenario.register_field(**EAST_FIELD)
    scenario.map_confirm(east["id"])
    _history_at(scenario, east["id"], 205.00)
    enrollment = scenario.create_enrollment(field_id=east["id"])

    response = scenario.api.submit_enrollment(enrollment["id"], None, ADMIN_HEADERS)

    validate_error(response, ERR_ADDITIONALITY_FAILED, 422)
    # Both fields document five years, so the first gate of the cascade is satisfied.
    assert ERR_INSUFFICIENT_PRACTICE_HISTORY not in response.text
    assert scenario.reload_enrollment(enrollment["id"])["status"] == ENROLLMENT_DRAFT


def test_quality_score_just_below_the_floor_cannot_be_passed(scenario):
    """A farm-record packet at 55.00 per cent coverage scores exactly 69.50 and is refused a
    pass, leaving the quality axis where it was.

    PRD §3.5: "A `decision` of `PASS` requires the packet's `qc_score` to be greater than or
    equal to 70.00 — equality passes — and moves `qc_status` from `PENDING` to `PASSED`; a
    score below that floor is refused with `ERR_QC_SCORE_BELOW_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/qc_pass_threshold_inclusive_at_70_00_and_refused_at_69_50
    """
    scenario.active_enrollment()
    packet = scenario.file_packet(
        source=EVIDENCE_FARM_RECORD, coverage_pct=55.00, measured_value=0.2500
    )

    assert_pct(packet["qc_score"], 69.50)
    assert packet["completeness_status"] == COMPLETENESS_PARTIAL

    response = scenario.api.qc_data_packet(packet["id"], {"decision": "PASS"}, ADMIN_HEADERS)

    validate_error(response, ERR_QC_SCORE_BELOW_THRESHOLD, 422)
    reread = get_success_data(scenario.api.get_data_packet(packet["id"], ADMIN_HEADERS))
    assert reread["qc_status"] == QC_PENDING
    assert_pct(reread["qc_score"], 69.50)
    # The score keeps two decimals and the farm-record source weight is 0.6.
    assert reread["qc_score"] not in (69, 70, 69.60, 70.10)


def test_quality_score_exactly_at_the_floor_passes_in_place(scenario):
    """One point of extra coverage brings the same packet to exactly 70.00, which passes,
    and the coverage axis stays partial because that is a different threshold.

    PRD §3.5: "A packet is `COMPLETE` when its `coverage_pct` is greater than or equal to
    85.00, and `PARTIAL` otherwise."

    Design: Difficulty/boundary_precision_check/qc_pass_threshold_inclusive_at_70_00_and_refused_at_69_50
    """
    scenario.active_enrollment()
    packet = scenario.file_packet(
        source=EVIDENCE_FARM_RECORD, coverage_pct=55.00, measured_value=0.2500
    )
    scenario.qc_packet(packet["id"], "FLAG", flag_reason="coverage below programme expectation")

    corrected = get_success_data(
        scenario.api.correct_data_packet(packet["id"], {"coverage_pct": 56.00}, ADMIN_HEADERS)
    )

    assert_pct(corrected["qc_score"], 70.00)
    assert_pct(corrected["coverage_pct"], 56.00)
    assert corrected["qc_status"] == QC_PENDING
    assert corrected["correction_count"] == 1

    passed = scenario.qc_packet(packet["id"], "PASS")

    assert passed["qc_status"] == QC_PASSED
    assert passed["completeness_status"] == COMPLETENESS_PARTIAL
